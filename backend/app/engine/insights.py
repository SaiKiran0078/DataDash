"""Dataset-agnostic analyst insight generation.

Only emit comparisons that are interpretable from the available data. Identifiers,
binary flags and low-support segments are not treated as headline measures.
"""
from __future__ import annotations

import re

import pandas as pd

ID_HINT = re.compile(r"(^|[^a-z])(id|uuid|guid|key|code|index|serial|customerid|userid|accountid|transactionid|orderid)([^a-z]|$)", re.I)
OUTCOME_HINT = re.compile(r"(churn|attrition|returned|return|conversion|converted|default|fraud|late|delay|delayed|cancel|cancelled|approved|success|failed|failure|complaint|satisfied|response|target|outcome|status|retention|renewal|defect|incident|loss)", re.I)
ADVERSE_OUTCOME_HINT = re.compile(r"(churn|attrition|return|default|fraud|late|delayed|cancel|failed|failure|complaint|defect|incident|loss)", re.I)
FAVOURABLE_OUTCOME_HINT = re.compile(r"(conversion|converted|approv|success|satisfied|retention|retained|renewal)", re.I)
RATE_HINT = re.compile(r"(rate|ratio|percent|pct|margin|score|rating|satisfaction|nps|price|average|avg|duration|age|tenure)", re.I)
VALUE_HINT = re.compile(r"(revenue|sales|turnover|gmv|income|profit|loss|earnings|premium|claim|cost|expense|spend|amount|value|balance|totalcharges|total_charges)", re.I)
COUNT_HINT = re.compile(r"(qty|quantity|units|orders|transactions|visits|clicks|views|count|volume)", re.I)


def _is_identifier(name: str) -> bool:
    n = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    compact = n.replace(" ", "")
    return bool(ID_HINT.search(n)) or compact.endswith(("customerid", "userid", "accountid", "transactionid", "orderid")) or compact in {"id", "uuid", "guid", "index", "rownumber", "rownumber"}


def _is_binary(series: pd.Series) -> bool:
    values = series.dropna().unique()
    return len(values) <= 2 and len(values) > 0


def _label(value) -> str:
    if pd.isna(value):
        return "(Not recorded)"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _fmt(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def build_analyst_insights(*, frame, schema, numeric_summary, category_summary, segment_analysis, time_series, correlations, rows):
    kinds = {c["name"]: c.get("kind") for c in schema}
    numeric = [c for c, k in kinds.items() if k == "numeric" and not _is_identifier(c)]
    categorical = [c for c, k in kinds.items() if k in {"categorical", "boolean", "text"} and frame[c].nunique(dropna=True) > 1]
    # Numeric flags with two values are dimensions, not additive KPI measures.
    dimensions = [c for c in categorical if not _is_identifier(c) and frame[c].nunique(dropna=True) <= 30]
    for col in numeric:
        if _is_binary(frame[col]) and frame[col].nunique(dropna=True) <= 2:
            dimensions.append(col)
    dimensions = list(dict.fromkeys(dimensions))

    stats = {item["column"]: item for item in numeric_summary}
    metric_candidates = []
    for position, col in enumerate(numeric):
        values = frame[col].dropna()
        if len(values) < 2 or values.nunique(dropna=True) <= 1 or (_is_binary(values) and set(values.unique()).issubset({0, 1, False, True})):
            continue
        rate_like = bool(RATE_HINT.search(col))
        value_like = bool(VALUE_HINT.search(col))
        count_like = bool(COUNT_HINT.search(col))
        aggregation = "sum" if (value_like or count_like) and not rate_like else "mean"
        score = (8 if value_like else 0) + (5 if count_like else 0) + (3 if rate_like else 0) + (2 if col.lower() in {"amount", "revenue", "sales", "profit"} else 0)
        stat = stats.get(col) or {
            "column": col, "count": int(values.count()), "missing": int(frame[col].isna().sum()),
            "sum": float(values.sum()), "mean": float(values.mean()), "median": float(values.median()),
            "min": float(values.min()), "max": float(values.max()),
        }
        metric_candidates.append({**stat, "suggested_aggregation": aggregation, "semantic_score": score, "position": position})
    metric_candidates.sort(key=lambda x: (-x["semantic_score"], x["position"]))
    for item in metric_candidates:
        item.pop("position", None)

    kpis = [{"id": f"kpi-{m['column']}", "label": ("Total " if m["suggested_aggregation"] == "sum" else "Average ") + m["column"],
             "column": m["column"], "aggregation": m["suggested_aggregation"],
             "value": m["sum"] if m["suggested_aggregation"] == "sum" else m["mean"],
             "valid_records": m["count"], "missing": m["missing"]}
            for m in metric_candidates[:4]]
    if rows:
        kpis.insert(0, {"id": "kpi-records", "label": "Records analysed", "column": None, "aggregation": "count", "value": int(rows), "valid_records": int(rows), "missing": 0})
    kpis = kpis[:5]


    business_insights, recommendations, suggested_visuals = [], [], []

    # Transactional datasets need financial analysis, not arbitrary averages of
    # currency columns across every dimension.
    def semantic_column(patterns):
        for col in frame.columns:
            compact = re.sub(r"[^a-z0-9]+", "", col.lower())
            if any(re.fullmatch(pattern, compact) for pattern in patterns):
                return col
        return None

    revenue_col = semantic_column([r"(net)?revenue(inr|usd|eur|gbp)?", r"(net)?sales(inr|usd|eur|gbp)?", r"gmv"])
    profit_col = semantic_column([r"(gross|net)?profit(inr|usd|eur|gbp)?", r"earnings(inr|usd|eur|gbp)?"])
    cost_col = semantic_column([r"(total)?cost(inr|usd|eur|gbp)?", r"cogs(inr|usd|eur|gbp)?"])
    quantity_col = semantic_column([r"quantity", r"qty", r"units"])
    unit_cost_col = semantic_column([r"unitcost(inr|usd|eur|gbp)?", r"costperunit(inr|usd|eur|gbp)?"])
    financial_mode = bool(revenue_col and (profit_col or cost_col or (quantity_col and unit_cost_col)))
    financial_frame = frame.drop_duplicates().copy() if financial_mode else frame
    exact_duplicate_count = int(len(frame) - len(financial_frame)) if financial_mode else 0
    cost_mismatches = 0

    if financial_mode:
        revenue_values = pd.to_numeric(financial_frame[revenue_col], errors="coerce")
        if quantity_col and unit_cost_col:
            expected_cost = (pd.to_numeric(financial_frame[quantity_col], errors="coerce")
                             * pd.to_numeric(financial_frame[unit_cost_col], errors="coerce"))
            if cost_col:
                recorded_cost = pd.to_numeric(financial_frame[cost_col], errors="coerce")
                tolerance = expected_cost.abs().clip(lower=1) * 0.005
                cost_mismatches = int(((recorded_cost - expected_cost).abs() > tolerance).fillna(False).sum())
            profit_values = revenue_values - expected_cost
        elif profit_col:
            profit_values = pd.to_numeric(financial_frame[profit_col], errors="coerce")
        else:
            profit_values = revenue_values - pd.to_numeric(financial_frame[cost_col], errors="coerce")

        valid = revenue_values.notna() & profit_values.notna()
        revenue_total = float(revenue_values[valid].sum())
        profit_total = float(profit_values[valid].sum())
        margin_total = profit_total / revenue_total * 100 if revenue_total else 0.0
        records_total = int(valid.sum())

        # Use reconciled business KPIs; calculated profit is revenue minus
        # quantity times unit cost whenever those inputs are available.
        kpis = [
            {"id": "kpi-records", "label": "Unique records analysed", "column": None,
             "aggregation": "count", "value": records_total, "valid_records": records_total, "missing": 0},
            {"id": "kpi-revenue", "label": "Total revenue", "column": revenue_col,
             "aggregation": "sum", "value": round(revenue_total, 2), "valid_records": records_total, "missing": int(revenue_values.isna().sum())},
            {"id": "kpi-profit", "label": "Calculated profit", "column": profit_col or cost_col,
             "aggregation": "sum", "value": round(profit_total, 2), "valid_records": records_total, "missing": int(profit_values.isna().sum())},
            {"id": "kpi-margin", "label": "Profit margin", "column": None,
             "aggregation": "rate", "value": round(margin_total, 2), "valid_records": records_total, "missing": 0},
        ]
        if quantity_col:
            units = pd.to_numeric(financial_frame[quantity_col], errors="coerce")
            kpis.append({"id": "kpi-units", "label": "Units sold", "column": quantity_col,
                         "aggregation": "sum", "value": round(float(units.sum()), 2),
                         "valid_records": int(units.notna().sum()), "missing": int(units.isna().sum())})

        business_insights.append({
            "id": "financial-overview", "type": "financial_overview",
            "title": f"Sales generated a {margin_total:.1f}% calculated profit margin",
            "evidence": f"{records_total:,} unique records generated {_fmt(revenue_total)} revenue and {_fmt(profit_total)} calculated profit; weighted margin: {margin_total:.1f}%.",
            "impact": "This is the overall performance baseline. Profit is calculated from revenue less quantity multiplied by unit cost when those fields are available.",
            "action": "Use this weighted margin as the baseline for product, category and channel decisions.",
            "severity": "info", "measure": revenue_col, "margin_pct": round(margin_total, 2),
            "revenue_total": round(revenue_total, 2), "profit_total": round(profit_total, 2)
        })

        # Prefer commercial dimensions. Summaries use sums and weighted margin,
        # never averages of currency columns or unweighted average margins.
        commercial_dims = [c for c in dimensions if re.search(
            r"product|category|channel|region|segment|customer|store|branch|state|territory",
            c, re.I) and not _is_identifier(c)]
        commercial_dims.sort(key=lambda c: 0 if "category" in c.lower() else 1 if "product" in c.lower() else 2 if "channel" in c.lower() else 3)
        for dimension in commercial_dims:
            grouped_frame = financial_frame.assign(
                _rev=revenue_values, _profit=profit_values, _group=financial_frame[dimension].map(_label))
            grouped = grouped_frame.groupby("_group", dropna=False).agg(
                records=("_rev", "count"), revenue=("_rev", "sum"), profit=("_profit", "sum")
            ).reset_index()
            grouped = grouped[grouped["records"] >= max(5, int(records_total * 0.03))]
            if len(grouped) < 2:
                continue
            grouped["margin"] = grouped["profit"] / grouped["revenue"].replace(0, pd.NA) * 100
            grouped["share"] = grouped["revenue"] / revenue_total * 100 if revenue_total else 0

            if "category" in dimension.lower():
                chart_groups = grouped.sort_values("revenue", ascending=False)
                suggested_visuals.append({
                    "id": f"financial-revenue-by-{dimension}", "title": f"Revenue contribution by {dimension}",
                    "reason": "Compares total revenue and share of revenue across categories.",
                    "spec": {"type": "bar", "x": dimension, "metric": "sum", "y": revenue_col},
                    "data": {"labels": [str(v) for v in chart_groups["_group"].tolist()],
                             "datasets": [{"label": "Revenue", "data": [round(float(v), 2) for v in chart_groups["revenue"].tolist()]}],
                             "meta": {"x": dimension, "measure": revenue_col, "aggregation": "sum",
                                      "group_counts": [int(v) for v in chart_groups["records"].tolist()],
                                      "revenue_share_pct": [round(float(v), 2) for v in chart_groups["share"].tolist()]}}
                })
                lead = grouped.sort_values("revenue", ascending=False).iloc[0]
                if float(lead["share"]) >= 20:
                    business_insights.append({
                        "id": "financial-category-mix", "type": "revenue_contribution",
                        "title": f"{lead['_group']} contributes {float(lead['share']):.1f}% of revenue",
                        "evidence": f"{lead['_group']}: {_fmt(float(lead['revenue']))} revenue across {int(lead['records']):,} records ({float(lead['share']):.1f}% of total), with a {float(lead['margin']):.1f}% calculated margin.",
                        "impact": "This category has a material influence on total sales and profitability.",
                        "action": f"Protect availability and monitor the cost and pricing drivers for {lead['_group']}.",
                        "severity": "info", "dimension": dimension, "revenue_share_pct": round(float(lead["share"]), 2)
                    })
            material = grouped[grouped["share"] >= 8].sort_values("margin")
            if not material.empty and not any(x.get("dimension") == dimension and x.get("type") == "margin_opportunity" for x in business_insights):
                low = material.iloc[0]
                gap = margin_total - float(low["margin"])
                if gap >= 3:
                    business_insights.append({
                        "id": f"financial-margin-{dimension}", "type": "margin_opportunity",
                        "title": f"{low['_group']} has a {float(low['margin']):.1f}% margin on {float(low['share']):.1f}% of revenue",
                        "evidence": f"{low['_group']}: {_fmt(float(low['revenue']))} revenue across {int(low['records']):,} records; margin {float(low['margin']):.1f}% versus {margin_total:.1f}% overall ({gap:.1f} percentage points lower).",
                        "impact": "A margin gap in a material revenue segment can affect total profitability.",
                        "action": f"Review unit costs, discounting and pricing for {low['_group']} before changing its sales mix.",
                        "severity": "medium", "dimension": dimension, "gap_pp": round(gap, 2),
                        "revenue_share_pct": round(float(low["share"]), 2)
                    })
            if "channel" in dimension.lower():
                lead = grouped.sort_values("revenue", ascending=False).iloc[0]
                business_insights.append({
                    "id": "financial-channel-mix", "type": "channel_mix",
                    "title": f"{lead['_group']} is the largest revenue channel",
                    "evidence": f"{lead['_group']} contributes {_fmt(float(lead['revenue']))} ({float(lead['share']):.1f}% of revenue) across {int(lead['records']):,} records, at a {float(lead['margin']):.1f}% calculated margin.",
                    "impact": "The largest channel is a major source of revenue exposure; monitor its margin alongside its sales share.",
                    "action": f"Track revenue and margin together for {lead['_group']}; compare acquisition or servicing costs if available.",
                    "severity": "info", "dimension": dimension, "revenue_share_pct": round(float(lead["share"]), 2)
                })
            if len(business_insights) >= 6:
                break

        # Compare the latest month with the previous month on revenue, profit
        # and weighted margin rather than emitting an isolated quantity change.
        date_col = next((c["name"] for c in schema if c.get("kind") == "datetime"), None)
        if date_col:
            dated = financial_frame[[date_col]].copy()
            dated["_revenue"] = revenue_values
            dated["_profit"] = profit_values
            dated["_period"] = pd.to_datetime(dated[date_col], errors="coerce").dt.to_period("M")
            monthly = dated.dropna(subset=["_period"]).groupby("_period").agg(
                records=("_revenue", "count"), revenue=("_revenue", "sum"), profit=("_profit", "sum")
            ).sort_index()
            if len(monthly) >= 2:
                prior, latest = monthly.iloc[-2], monthly.iloc[-1]
                if float(prior["revenue"]) > 0:
                    rev_change = (float(latest["revenue"]) - float(prior["revenue"])) / float(prior["revenue"]) * 100
                    prior_margin = float(prior["profit"]) / float(prior["revenue"]) * 100
                    latest_margin = float(latest["profit"]) / float(latest["revenue"]) * 100 if latest["revenue"] else 0
                    suggested_visuals.append({
                        "id": "financial-monthly-revenue", "title": "Monthly revenue and calculated profit",
                        "reason": "Shows monthly revenue and calculated profit over the available reporting period.",
                        "spec": {"type": "line", "x": "period", "y": revenue_col},
                        "data": {"labels": [str(v) for v in monthly.index.tolist()],
                                 "datasets": [
                                     {"label": "Revenue", "data": [round(float(v), 2) for v in monthly["revenue"].tolist()]},
                                     {"label": "Calculated profit", "data": [round(float(v), 2) for v in monthly["profit"].tolist()]}
                                 ],
                                 "meta": {"aggregation": "sum", "measure": revenue_col,
                                          "record_counts": [int(v) for v in monthly["records"].tolist()]}}
                    })
                    if abs(rev_change) >= 8:
                        business_insights.append({
                            "id": "financial-monthly-change", "type": "financial_period_change",
                            "title": f"Revenue changed {rev_change:+.1f}% in the latest month",
                            "evidence": f"{str(monthly.index[-1])}: {_fmt(float(latest['revenue']))} revenue and {_fmt(float(latest['profit']))} calculated profit across {int(latest['records']):,} records; prior month {str(monthly.index[-2])}: {_fmt(float(prior['revenue']))} revenue and {_fmt(float(prior['profit']))} profit. Margin moved from {prior_margin:.1f}% to {latest_margin:.1f}%.",
                            "impact": "The change in revenue and margin shows whether sales growth translated into stronger profitability.",
                            "action": "Break down the latest month's revenue and margin by product and channel to identify the segments contributing to the movement.",
                            "severity": "medium", "change_pct": round(rev_change, 2),
                            "margin_change_pp": round(latest_margin - prior_margin, 2)
                        })

        recommendations.append({
            "id": "financial-review", "title": "Protect profit while growing sales",
            "action": "Prioritise high-revenue segments with below-baseline margins. Review pricing, discounting and unit costs before changing the sales mix.",
            "priority": "medium"
        })

    used = set()

    # Detect a plausible categorical/binary outcome and compare outcome rates by dimensions.
    outcome_cols = [c for c in dimensions if OUTCOME_HINT.search(c)]
    for outcome in outcome_cols[:2]:
        vals = frame[outcome].dropna().unique().tolist()
        if len(vals) != 2:
            continue
        direction = "adverse" if ADVERSE_OUTCOME_HINT.search(outcome) else "favourable" if FAVOURABLE_OUTCOME_HINT.search(outcome) else "unknown"
        adverse_labels = {"churn", "churned", "returned", "fraud", "late", "delay", "delayed", "cancelled", "canceled", "default", "failed", "failure", "complaint", "loss", "defect", "incident"}
        favourable_labels = {"converted", "approved", "success", "satisfied", "retained", "renewed"}
        neutral_event_labels = {"yes", "true", "1"}
        observed_labels = {_label(v).strip().lower() for v in vals}
        if direction == "unknown" and observed_labels & adverse_labels and observed_labels & favourable_labels:
            # A generic status field containing both a favourable and adverse event
            # has no declared polarity; choosing either would manufacture a rate.
            continue
        recognised = adverse_labels if direction == "adverse" else favourable_labels if direction == "favourable" else adverse_labels | favourable_labels
        positive = next((v for v in vals if _label(v).strip().lower() in recognised | neutral_event_labels), None)
        if positive is None:
            # A known negative label does not make its arbitrary counterpart positive.
            # Require an explicitly recognised event label before calculating an outcome rate.
            continue
        valid_outcome = frame[outcome].notna()
        outcome_mask = frame[outcome].eq(positive) & valid_outcome
        valid_count = int(valid_outcome.sum())
        overall = float(outcome_mask.sum() / valid_count * 100) if valid_count else None
        if overall is None:
            continue
        kpis.append({"id": f"kpi-rate-{outcome}", "label": f"{outcome} rate", "column": outcome,
                     "aggregation": "rate", "value": round(overall, 2),
                     "valid_records": valid_count, "missing": int(frame[outcome].isna().sum())})
        if direction == "adverse":
            overview_impact = f"This is the baseline adverse {outcome} rate; higher segment rates warrant investigation."
            overview_action = f"Use the {overall:.1f}% baseline to identify segments with materially higher adverse {outcome} rates."
        elif direction == "favourable":
            overview_impact = f"This is the baseline favourable {outcome} rate; higher segment rates indicate stronger observed results."
            overview_action = f"Compare segments with this {overall:.1f}% baseline and learn from groups with stronger {outcome} rates."
        else:
            overview_impact = f"This establishes the observed {outcome} baseline, but the field name does not establish whether a higher rate is desirable."
            overview_action = f"Confirm what a positive {outcome} represents before prioritising groups with higher rates."
        business_insights.append({"id": f"outcome-overall-{outcome}", "type": "outcome_overview",
            "title": f"Overall {outcome} rate", "evidence": f"{int(outcome_mask.sum()):,} of {valid_count:,} records with a recorded {outcome} ({overall:.1f}%) are marked {positive}.",
            "impact": overview_impact, "action": overview_action,
            "severity": "high" if direction == "adverse" and overall >= 25 else "positive" if direction == "favourable" and overall >= 50 else "info", "measure": outcome, "rate_pct": round(overall, 2), "outcome_direction": direction})
        other_count = valid_count - int(outcome_mask.sum())
        suggested_visuals.append({
            "id": f"visual-outcome-overall-{outcome}",
            "title": f"{outcome} outcome breakdown",
            "reason": f"Shows the recorded {outcome} outcome counts; {int(frame[outcome].isna().sum()):,} missing outcomes are excluded.",
            "spec": {"type": "bar", "x": outcome, "metric": "outcome_count"},
            "data": {
                "labels": [str(positive), "Other outcome"],
                "datasets": [{"label": "Records", "data": [int(outcome_mask.sum()), int(other_count)]}],
                "meta": {"measure": outcome, "positive_label": str(positive), "valid_records": valid_count,
                         "missing_records": int(frame[outcome].isna().sum()), "aggregation": "count"}
            }
        })
        for dimension in dimensions:
            if dimension == outcome:
                continue
            grouped_frame = frame.assign(_group=frame[dimension].map(_label), _positive=outcome_mask.astype(float).where(valid_outcome))
            grouped = grouped_frame.groupby("_group", dropna=False)["_positive"].agg(["count", "mean"]).reset_index()
            minimum_group = max(3, int(len(frame) * 0.01)) if len(frame) < 30 else max(10, int(len(frame) * 0.01))
            grouped = grouped[grouped["count"] >= minimum_group]
            if len(grouped) < 2:
                continue
            grouped = grouped.sort_values("mean", ascending=False)
            high, low = grouped.iloc[0], grouped.iloc[-1]
            gap = (float(high["mean"]) - float(low["mean"])) * 100
            if gap < 3 or high["_group"] == low["_group"]:
                continue
            key = (outcome, dimension)
            if key in used:
                continue
            used.add(key)
            high_rate, low_rate = float(high["mean"]) * 100, float(low["mean"]) * 100
            title = (f"{outcome} risk is elevated for {high['_group']}" if direction == "adverse"
                     else f"{outcome} performance is strongest for {high['_group']}" if direction == "favourable"
                     else f"{outcome} differs across {dimension}")
            if direction == "adverse":
                impact = f"The {high['_group']} group has a {gap:.1f}-percentage-point higher observed adverse {outcome} rate than {low['_group']}. This is an association, not proof of cause."
                action = f"Investigate the {high['_group']} segment's experience and compare relevant drivers before testing a targeted intervention."
                severity = "high" if gap >= 15 else "medium"
            elif direction == "favourable":
                impact = f"The {high['_group']} group has a {gap:.1f}-percentage-point higher observed favourable {outcome} rate than {low['_group']}. This is an association, not proof of cause."
                action = f"Understand what contributes to the stronger {high['_group']} result and test whether those practices can be reproduced."
                severity = "positive"
            else:
                impact = f"The {high['_group']} group has a {gap:.1f}-percentage-point higher observed {outcome} rate than {low['_group']}; the field name does not establish whether this is desirable."
                action = f"Confirm what a positive {outcome} represents, then investigate differences between {high['_group']} and {low['_group']}."
                severity = "info"
            business_insights.append({"id": f"outcome-{outcome}-{dimension}", "type": "outcome_segment",
                "title": title, "evidence": f"{high['_group']}: {int(round(float(high['mean']) * int(high['count']))):,} of {int(high['count']):,} ({high_rate:.1f}%); {low['_group']}: {int(round(float(low['mean']) * int(low['count']))):,} of {int(low['count']):,} ({low_rate:.1f}%). Overall: {overall:.1f}%. Gap: {gap:.1f} percentage points.",
                "impact": impact, "action": action, "severity": severity, "dimension": dimension, "measure": outcome,
                "aggregation": "rate", "outcome_direction": direction,
                "high_group": {"value": str(high["_group"]), "count": int(high["count"]), "rate_pct": round(high_rate, 2)},
                "low_group": {"value": str(low["_group"]), "count": int(low["count"]), "rate_pct": round(low_rate, 2)},
                "overall_rate_pct": round(overall, 2), "gap_pp": round(gap, 2)})
            rate_groups = grouped_frame.groupby("_group", dropna=False)["_positive"].agg(["count", "mean"]).reset_index()
            rate_groups = rate_groups[rate_groups["count"] >= minimum_group].sort_values("mean", ascending=False)
            suggested_visuals.append({"id": f"visual-{outcome}-{dimension}", "title": f"{outcome} rate by {dimension}",
                "reason": f"Shows the percentage of records marked {positive}; groups with missing {outcome} values are excluded from each rate.",
                "spec": {"type": "bar", "x": dimension, "metric": "rate"},
                "data": {"labels": [str(v) for v in rate_groups["_group"].tolist()],
                         "datasets": [{"label": f"{outcome} rate (%)", "data": [round(float(v) * 100, 2) for v in rate_groups["mean"].tolist()]}],
                         "meta": {"x": dimension, "measure": outcome, "aggregation": "rate", "denominator": "non-missing outcome records", "group_counts": [int(v) for v in rate_groups["count"].tolist()], "positive_counts": [int(round(float(v) * int(n))) for v, n in zip(rate_groups["mean"].tolist(), rate_groups["count"].tolist())]}}})
        if outcome_cols:
            if direction == "adverse":
                rec_title = f"Investigate high-{outcome}-rate segments"
                rec_action = f"Review the segments with the highest {outcome} rates, validate sample sizes and investigate potential drivers before testing an intervention."
                rec_priority = "high"
            elif direction == "favourable":
                rec_title = f"Learn from high-{outcome}-rate segments"
                rec_action = f"Compare the highest-{outcome}-rate segments and test whether their successful practices can be reproduced."
                rec_priority = "medium"
            else:
                rec_title = f"Validate the meaning of {outcome}"
                rec_action = f"Confirm whether a higher {outcome} rate is desirable before prioritising segments or recommending an intervention."
                rec_priority = "medium"
            recommendations.append({"id": f"action-{outcome}", "title": rec_title,
                "action": rec_action, "priority": rec_priority})

    # Compare meaningful measures using averages/rates, not raw totals alone. Exclude IDs and binary flags.
    # Numeric comparison visuals can support exploration, but generic metric gaps are not
    # promoted to executive findings when a clear business outcome is available.
    for measure in ([] if financial_mode else numeric):
        if measure not in {m["column"] for m in metric_candidates}:
            continue
        rate_like = bool(RATE_HINT.search(measure))
        for dimension in dimensions:
            if dimension in outcome_cols:
                continue
            series = frame.assign(_group=frame[dimension].map(_label)).groupby("_group")[measure].agg(["count", "mean", "sum"]).reset_index()
            minimum_group = max(3, int(len(frame) * 0.01)) if len(frame) < 30 else max(10, int(len(frame) * 0.01))
            series = series[series["count"] >= minimum_group]
            if len(series) < 2:
                continue
            # For comparisons, mean is the fair default; totals are only described as volume when appropriate.
            ranked = series.sort_values("mean", ascending=False)
            high, low = ranked.iloc[0], ranked.iloc[-1]
            if pd.isna(high["mean"]) or pd.isna(low["mean"]):
                continue
            difference = float(high["mean"] - low["mean"])
            baseline = abs(float(low["mean"]))
            # Relative change is unstable around a zero baseline; omit rather than
            # manufacture an enormous percentage from a negligible denominator.
            if baseline < 1e-9 or abs(difference) < 1e-9:
                continue
            relative = abs(difference) / baseline * 100
            if relative < 15:
                continue
            if not outcome_cols:
                title = f"{measure} averages differ across {dimension}"
                business_insights.append({"id": f"measure-{measure}-{dimension}", "type": "segment_comparison",
                    "title": title,
                    "evidence": f"{high['_group']} averages {_fmt(float(high['mean']))} across {int(high['count']):,} records; {low['_group']} averages {_fmt(float(low['mean']))} across {int(low['count']):,} records ({relative:.1f}% difference).",
                    "impact": "Average values help control for unequal group sizes; check the measure definition and distribution before interpreting the gap.",
                    "action": f"Investigate what distinguishes {high['_group']} from {low['_group']} and confirm whether the difference is operationally meaningful.",
                    "severity": "medium", "dimension": dimension, "measure": measure, "aggregation": "mean",
                    "high_group": {"value": str(high["_group"]), "count": int(high["count"]), "mean": float(high["mean"])},
                    "low_group": {"value": str(low["_group"]), "count": int(low["count"]), "mean": float(low["mean"])},
                    "relative_difference_pct": round(relative, 2)})
    
            suggested_visuals.append({"id": f"visual-{measure}-{dimension}", "title": f"Average {measure} by {dimension}",
                "reason": f"Compares average {measure} across groups; use the displayed sample counts when interpreting differences.",
                "spec": {"type": "bar", "x": dimension, "y": measure, "agg": "mean", "top_n": 50},
                "data": {"labels": [str(v) for v in ranked["_group"].tolist()],
                         "datasets": [{"label": f"Average {measure}", "data": [round(float(v), 2) for v in ranked["mean"].tolist()]}],
                         "meta": {"x": dimension, "measure": measure, "aggregation": "mean",
                                  "group_counts": [int(v) for v in ranked["count"].tolist()]}}})

    for series in ([] if financial_mode else time_series):
        periods = series.get("periods", [])
        if len(periods) < 3:
            continue
        measure = series["measure"]
        measure_metric = next((item for item in metric_candidates if item["column"] == measure), None)
        aggregation = measure_metric["suggested_aggregation"] if measure_metric else ("mean" if RATE_HINT.search(measure) else "sum")
        vals = [p["mean"] if aggregation == "mean" else p["sum"] for p in periods]
        valid = [(p, v) for p, v in zip(periods, vals) if v is not None and pd.notna(v) and int(p.get("count", 0)) > 0]
        if len(valid) < 3:
            continue
        prior, current = valid[-2], valid[-1]
        before, after = float(prior[1]), float(current[1])
        if before == 0:
            continue
        change = (after - before) / abs(before) * 100
        if abs(change) >= 10:
            business_insights.append({"id": f"period-{measure}-{series['date_column']}", "type": "period_change",
                "title": f"{measure} changed {change:+.1f}% in the latest period",
                "evidence": f"{current[0]['period']}: {_fmt(after)} versus {_fmt(before)} in {prior[0]['period']} ({change:+.1f}%).",
                "impact": "A period-to-period movement is a signal to investigate; check seasonality and record volume before calling it growth or decline.",
                "action": f"Break down {measure} in {current[0]['period']} by relevant segments to identify what contributed to the movement.",
                "severity": "medium", "measure": measure, "aggregation": aggregation, "change_pct": round(change, 2)})

    if not business_insights:
        business_insights.append({"id": "no-material-patterns", "type": "data_observation",
            "title": "No material segment differences detected",
            "evidence": "The available fields did not produce a sufficiently supported outcome, segment gap or period movement using the current conservative thresholds.",
            "impact": "Avoiding weak comparisons is preferable to presenting arbitrary highest/lowest rankings as business insights.",
            "action": "Confirm the dataset's row meaning and identify the business outcome or decision this analysis should support.",
            "severity": "info"})
    # Executive reporting: keep one overall outcome baseline, then select a small,
    # diverse set of decision-relevant findings. Related dimensions (such as optional
    # service add-ons) are supporting evidence, not separate headline stories.
    business_insights.sort(key=lambda item: (
        0 if item.get("type") in {"outcome_overview", "financial_overview"} else
        1 if item.get("type") == "data_integrity" else
        2 if item.get("type") in {"margin_opportunity", "financial_period_change"} else 3,
        -float(item.get("revenue_share_pct", item.get("gap_pp", abs(item.get("change_pct", 0))))),
        -int((item.get("high_group") or {}).get("count", 0)),
    ))
    def _insight_family(item):
        dimension = str(item.get("dimension", "")).lower()
        if re.search(r"security|support|backup|protect|stream|internet|service", dimension):
            return "service_adoption"
        if re.search(r"payment|billing|invoice|method", dimension):
            return "payment_billing"
        if re.search(r"contract|plan|subscription|term", dimension):
            return "contract_plan"
        if re.search(r"senior|age|gender|partner|depend|marital", dimension):
            return "customer_profile"
        return dimension or item.get("type", "other")
    selected, families = [], set()
    for item in business_insights:
        if item.get("type") in {"outcome_overview", "financial_overview"}:
            selected.append(item)
            continue
        family = _insight_family(item)
        if family in families:
            continue
        selected.append(item)
        families.add(family)
        if len(selected) >= 7:
            break
    business_insights = selected[:7]
    # Keep the chart for the strongest displayed segment finding near the front,
    # so the UI can always pair a headline insight with its matching visual.
    insight_order = {}
    for index, item in enumerate(business_insights):
        if item.get("measure") and item.get("dimension"):
            insight_order.setdefault((item["measure"], item["dimension"]), index)
    def _visual_order(item):
        meta = (item.get("data") or {}).get("meta") or {}
        spec = item.get("spec") or {}
        if spec.get("metric") == "outcome_count":
            return -1
        measure = meta.get("measure") or spec.get("y")
        dimension = spec.get("x")
        return insight_order.get((measure, dimension), len(business_insights))
    suggested_visuals.sort(key=_visual_order)
    suggested_visuals = suggested_visuals[:8]
    if not recommendations:
        recommendations.append({"id": "metric-review", "title": "Confirm the primary measure",
            "action": "Define the decision and primary outcome, then compare supported segments using appropriate averages, rates or totals.",
            "priority": "medium"})
    # Put dataset size and detected outcome rate ahead of supporting numeric measures.
    kpis.sort(key=lambda item: 0 if item["aggregation"] == "count" else 1 if item["aggregation"] == "rate" else 2)
    return {"business_insights": business_insights, "recommendations": recommendations[:6],
            "metric_candidates": metric_candidates, "suggested_visuals": suggested_visuals, "kpis": kpis[:5]}
