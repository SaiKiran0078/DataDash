import pandas as pd

from app.engine.insights import build_analyst_insights


def test_telco_like_data_prioritises_outcome_rates_and_excludes_customer_ids():
    rows = []
    for contract, n, churn_n in [("Month-to-month", 100, 43), ("One year", 100, 11), ("Two year", 100, 3)]:
        for i in range(n):
            rows.append({"customerID": f"C-{contract}-{i}", "Contract": contract,
                         "Churn": "Yes" if i < churn_n else "No",
                         "MonthlyCharges": 75.0 if contract == "Month-to-month" else 60.0,
                         "SeniorCitizen": i % 2})
    frame = pd.DataFrame(rows)
    schema = [{"name": "customerID", "kind": "text"}, {"name": "Contract", "kind": "categorical"},
              {"name": "Churn", "kind": "categorical"}, {"name": "MonthlyCharges", "kind": "numeric"},
              {"name": "SeniorCitizen", "kind": "numeric"}]
    result = build_analyst_insights(frame=frame, schema=schema, numeric_summary=[], category_summary=[],
                                    segment_analysis=[], time_series=[], correlations=[], rows=len(frame))
    assert any(x["type"] == "outcome_overview" for x in result["business_insights"])
    contract = next(x for x in result["business_insights"] if x.get("dimension") == "Contract")
    assert contract["high_group"]["value"] == "Month-to-month"
    assert contract["high_group"]["rate_pct"] == 43.0
    assert contract["outcome_direction"] == "adverse"
    assert contract["severity"] == "high"
    assert all("customerID" not in x["title"] for x in result["business_insights"])
    assert all("customerID" not in str(x["spec"]) for x in result["suggested_visuals"])
    assert any(k["column"] == "MonthlyCharges" and k["aggregation"] == "mean" for k in result["kpis"])
    assert any(v["spec"].get("metric") == "rate" and v["spec"].get("x") == "Contract" for v in result["suggested_visuals"])
    assert all(x["type"] != "segment_comparison" for x in result["business_insights"])
    assert any(v["spec"].get("y") == "MonthlyCharges" for v in result["suggested_visuals"])  # supporting visual, not a headline finding


def test_no_outcome_does_not_emit_arbitrary_highest_lowest_comparisons():
    frame = pd.DataFrame({"record_id": [f"R{i}" for i in range(40)],
                          "gender": ["F", "M"] * 20,
                          "flag": [0, 1] * 20,
                          "unit_price": [10 + i for i in range(40)]})
    schema = [{"name": "record_id", "kind": "text"}, {"name": "gender", "kind": "categorical"},
              {"name": "flag", "kind": "numeric"}, {"name": "unit_price", "kind": "numeric"}]
    result = build_analyst_insights(frame=frame, schema=schema, numeric_summary=[], category_summary=[],
                                    segment_analysis=[], time_series=[], correlations=[], rows=len(frame))
    assert all(x["type"] != "segment_comparison" for x in result["business_insights"])
    assert all("record_id" not in str(x) for x in result["business_insights"])
    assert all("flag" not in k["column"] for k in result["kpis"] if k["column"])

def test_outcome_rates_exclude_missing_outcomes_and_visuals_show_percentages():
    frame = pd.DataFrame({
        "segment": ["A"] * 50 + ["B"] * 50,
        "response": ["Yes"] * 20 + ["No"] * 20 + [None] * 10
                  + ["Yes"] * 5 + ["No"] * 35 + [None] * 10,
        "revenue": [100.0] * 100,
    })
    schema = [{"name": "segment", "kind": "categorical"},
              {"name": "response", "kind": "categorical"},
              {"name": "revenue", "kind": "numeric"}]
    result = build_analyst_insights(frame=frame, schema=schema, numeric_summary=[],
                                    category_summary=[], segment_analysis=[],
                                    time_series=[], correlations=[], rows=len(frame))
    overview = next(x for x in result["business_insights"] if x["type"] == "outcome_overview")
    assert overview["rate_pct"] == 31.25
    assert "25 of 80" in overview["evidence"]
    kpi = next(x for x in result["kpis"] if x["aggregation"] == "rate")
    assert kpi["value"] == 31.25
    visual = next(x for x in result["suggested_visuals"] if x["spec"].get("metric") == "rate")
    values = dict(zip(visual["data"]["labels"], visual["data"]["datasets"][0]["data"]))
    assert values == {"A": 50.0, "B": 12.5}

def test_unknown_binary_status_labels_are_not_assumed_to_have_a_positive_polarity():
    frame = pd.DataFrame({"status": ["Open", "Closed"] * 30,
                          "group": ["A"] * 30 + ["B"] * 30,
                          "amount": list(range(60))})
    schema = [{"name": "status", "kind": "categorical"},
              {"name": "group", "kind": "categorical"},
              {"name": "amount", "kind": "numeric"}]
    result = build_analyst_insights(frame=frame, schema=schema, numeric_summary=[],
                                    category_summary=[], segment_analysis=[],
                                    time_series=[], correlations=[], rows=len(frame))
    assert not any(k["aggregation"] == "rate" for k in result["kpis"])
    assert not any(x["type"].startswith("outcome_") for x in result["business_insights"])




def test_favourable_outcome_is_not_reported_as_a_risk():
    frame = pd.DataFrame({
        "channel": ["Organic"] * 40 + ["Paid"] * 40,
        "Conversion": ["Yes"] * 30 + ["No"] * 10 + ["Yes"] * 12 + ["No"] * 28,
        "order_value": [100.0] * 80,
    })
    schema = [
        {"name": "channel", "kind": "categorical"},
        {"name": "Conversion", "kind": "categorical"},
        {"name": "order_value", "kind": "numeric"},
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    overview = next(x for x in result["business_insights"] if x["type"] == "outcome_overview")
    segment = next(x for x in result["business_insights"] if x.get("dimension") == "channel")
    recommendation = next(x for x in result["recommendations"] if x["id"] == "action-Conversion")
    visual = next(x for x in result["suggested_visuals"] if x["spec"].get("metric") == "rate")

    assert overview["outcome_direction"] == "favourable"
    assert overview["severity"] != "high"
    assert segment["severity"] == "positive"
    assert "favourable" in segment["impact"]
    assert recommendation["priority"] == "medium"
    assert "Learn from" in recommendation["title"]
    assert visual["data"]["meta"]["group_counts"] == [40, 40]
    assert visual["data"]["meta"]["positive_counts"] == [30, 12]



def test_monthly_charge_trend_uses_average_not_volume_inflated_sum():
    frame = pd.DataFrame({"MonthlyCharges": [60.0, 70.0, 80.0], "TotalCharges": [60.0, 140.0, 240.0]})
    schema = [{"name": "MonthlyCharges", "kind": "numeric"}, {"name": "TotalCharges", "kind": "numeric"}]
    numeric_summary = [{
        "column": "MonthlyCharges", "count": 3, "missing": 0,
        "sum": 210.0, "mean": 70.0, "median": 70.0, "min": 60.0, "max": 80.0,
    }]
    periods = [
        {"period": "2026-01", "count": 5, "sum": 300.0, "mean": 60.0},
        {"period": "2026-02", "count": 5, "sum": 350.0, "mean": 70.0},
        {"period": "2026-03", "count": 20, "sum": 1600.0, "mean": 80.0},
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=numeric_summary,
        category_summary=[], segment_analysis=[],
        time_series=[{"date_column": "BillingDate", "measure": "MonthlyCharges", "periods": periods}],
        correlations=[], rows=3,
    )
    trend = next(x for x in result["business_insights"] if x["type"] == "period_change")
    metrics = {item["column"]: item for item in result["metric_candidates"]}
    assert metrics["MonthlyCharges"]["suggested_aggregation"] == "mean"
    assert metrics["TotalCharges"]["suggested_aggregation"] == "sum"
    assert trend["aggregation"] == "mean"
    assert trend["change_pct"] == 14.29



def test_known_negative_word_does_not_make_an_unknown_counterpart_positive():
    frame = pd.DataFrame({
        "status": ["No", "Open"] * 30,
        "group": ["A"] * 30 + ["B"] * 30,
        "amount": list(range(60)),
    })
    schema = [
        {"name": "status", "kind": "categorical"},
        {"name": "group", "kind": "categorical"},
        {"name": "amount", "kind": "numeric"},
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    assert not any(item["aggregation"] == "rate" for item in result["kpis"])
    assert not any(item["type"].startswith("outcome_") for item in result["business_insights"])



def test_numeric_zero_one_churn_is_recognised_as_an_adverse_outcome():
    frame = pd.DataFrame({
        "Contract": ["Monthly"] * 40 + ["Annual"] * 40,
        "Churn": [1.0] * 20 + [0.0] * 20 + [1.0] * 4 + [0.0] * 36,
        "MonthlyCharges": [80.0] * 40 + [60.0] * 40,
    })
    schema = [
        {"name": "Contract", "kind": "categorical"},
        {"name": "Churn", "kind": "numeric"},
        {"name": "MonthlyCharges", "kind": "numeric"},
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    overview = next(x for x in result["business_insights"] if x["type"] == "outcome_overview")
    contract = next(x for x in result["business_insights"] if x.get("dimension") == "Contract")
    assert overview["rate_pct"] == 30.0
    assert contract["high_group"]["value"] == "Monthly"
    assert contract["high_group"]["rate_pct"] == 50.0
    assert contract["outcome_direction"] == "adverse"



def test_retained_label_is_recognised_for_retention_outcomes():
    frame = pd.DataFrame({
        "Retention": ["Retained"] * 24 + ["Not retained"] * 16,
        "segment": ["A"] * 20 + ["B"] * 20,
        "spend": [10.0] * 40,
    })
    schema = [
        {"name": "Retention", "kind": "categorical"},
        {"name": "segment", "kind": "categorical"},
        {"name": "spend", "kind": "numeric"},
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    overview = next(x for x in result["business_insights"] if x["type"] == "outcome_overview")
    assert overview["rate_pct"] == 60.0
    assert overview["outcome_direction"] == "favourable"



def test_failure_field_selects_failure_not_success_as_the_adverse_event():
    frame = pd.DataFrame({
        "Failure": ["Success"] * 30 + ["Failure"] * 10,
        "team": ["A"] * 20 + ["B"] * 20,
        "amount": [50.0] * 40,
    })
    schema = [
        {"name": "Failure", "kind": "categorical"},
        {"name": "team", "kind": "categorical"},
        {"name": "amount", "kind": "numeric"},
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    overview = next(x for x in result["business_insights"] if x["type"] == "outcome_overview")
    assert "10 of 40" in overview["evidence"]
    assert overview["rate_pct"] == 25.0
    assert overview["outcome_direction"] == "adverse"



def test_generic_yes_no_status_requires_business_polarity_confirmation():
    frame = pd.DataFrame({
        "status": ["Yes"] * 30 + ["No"] * 30,
        "segment": ["A"] * 30 + ["B"] * 30,
        "amount": [100.0] * 60,
    })
    schema = [
        {"name": "status", "kind": "categorical"},
        {"name": "segment", "kind": "categorical"},
        {"name": "amount", "kind": "numeric"},
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    overview = next(x for x in result["business_insights"] if x["type"] == "outcome_overview")
    assert overview["outcome_direction"] == "unknown"
    assert overview["severity"] == "info"
    assert "Confirm what a positive status represents" in overview["action"]



def test_generic_status_with_success_and_failure_labels_is_not_guessed():
    frame = pd.DataFrame({
        "status": ["Success"] * 30 + ["Failure"] * 30,
        "segment": ["A"] * 30 + ["B"] * 30,
        "amount": [100.0] * 60,
    })
    schema = [
        {"name": "status", "kind": "categorical"},
        {"name": "segment", "kind": "categorical"},
        {"name": "amount", "kind": "numeric"},
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    assert not any(item["aggregation"] == "rate" for item in result["kpis"])
    assert not any(item["type"].startswith("outcome_") for item in result["business_insights"])



def test_zero_baseline_does_not_create_infinite_or_huge_relative_insight():
    frame = pd.DataFrame({
        "segment": ["A"] * 20 + ["B"] * 20,
        "spend": [0.0] * 20 + [100.0] * 20,
    })
    schema = [
        {"name": "segment", "kind": "categorical"},
        {"name": "spend", "kind": "numeric"},
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    assert not any(item["type"] == "segment_comparison" for item in result["business_insights"])



def test_constant_numeric_fields_are_not_presented_as_kpis_or_segment_measures():
    frame = pd.DataFrame({
        "constant_score": [5.0] * 40,
        "revenue": [10.0 + i for i in range(40)],
        "segment": ["A"] * 20 + ["B"] * 20,
    })
    schema = [
        {"name": "constant_score", "kind": "numeric"},
        {"name": "revenue", "kind": "numeric"},
        {"name": "segment", "kind": "categorical"},
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    assert all(item["column"] != "constant_score" for item in result["metric_candidates"])
    assert all(item.get("measure") != "constant_score" for item in result["business_insights"])


def test_executive_insights_are_capped_and_related_service_dimensions_are_consolidated():
    rows = []
    for contract, n, churn_n in [("Month-to-month", 100, 43), ("One year", 100, 11), ("Two year", 100, 3)]:
        for i in range(n):
            rows.append({
                "Contract": contract,
                "Churn": "Yes" if i < churn_n else "No",
                "OnlineSecurity": "No" if i < 60 else "Yes",
                "TechSupport": "No" if i < 55 else "Yes",
                "OnlineBackup": "No" if i < 50 else "Yes",
                "PaymentMethod": "Electronic check" if i < 60 else "Credit card",
                "SeniorCitizen": i % 2,
                "MonthlyCharges": 75.0 if contract == "Month-to-month" else 60.0,
            })
    frame = pd.DataFrame(rows)
    schema = [
        {"name": col, "kind": "numeric" if col in {"SeniorCitizen", "MonthlyCharges"} else "categorical"}
        for col in frame.columns
    ]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    findings = result["business_insights"]
    assert len(findings) <= 7
    service_findings = [
        item for item in findings
        if item.get("dimension") in {"OnlineSecurity", "TechSupport", "OnlineBackup"}
    ]
    assert len(service_findings) <= 1
    contract = next(item for item in findings if item.get("dimension") == "Contract")
    assert "Month-to-month" in contract["title"]
    assert "43 of 100" in contract["evidence"]


def test_financial_dataset_generates_decision_ready_weighted_insights_and_reconciles_costs():
    rows = []
    for i in range(24):
        category = "Furniture" if i < 12 else "Appliances"
        product = "Office Chair" if i < 12 else "Air Fryer"
        revenue = 6200.0 if i < 12 else 5000.0
        unit_cost = 4100.0 if i < 12 else 4050.0
        rows.append({
            "order_id": f"O-{i}", "order_date": pd.Timestamp("2025-11-20") + pd.Timedelta(days=i),
            "product_category": category, "product": product,
            "sales_channel": "Online" if i % 2 else "Retail",
            "quantity": 1, "unit_cost_inr": unit_cost,
            "revenue_inr": revenue, "cost_inr": unit_cost,
            "profit_inr": revenue - unit_cost, "discount_pct": 5.0,
        })
    # Two exact duplicate records and one corrupted recorded cost.
    rows.extend([rows[0].copy(), rows[1].copy()])
    rows[2]["cost_inr"] = 9999.0
    frame = pd.DataFrame(rows)
    schema = [{"name": col, "kind": "datetime" if col == "order_date" else
               "numeric" if col in {"quantity", "unit_cost_inr", "revenue_inr", "cost_inr", "profit_inr", "discount_pct"} else "categorical"}
              for col in frame.columns]
    result = build_analyst_insights(
        frame=frame, schema=schema, numeric_summary=[], category_summary=[],
        segment_analysis=[], time_series=[], correlations=[], rows=len(frame),
    )
    findings = result["business_insights"]
    assert any(item["type"] == "financial_overview" for item in findings)
    assert all(item["type"] != "data_integrity" for item in findings)
    assert all(not any(word in (item["title"] + " " + item["action"]).lower()
                       for word in ("duplicate", "missing", "data quality", "cost mismatch", "reconcile"))
               for item in result["recommendations"])
    assert any(item["type"] == "margin_opportunity" for item in findings)
    assert all(item["type"] != "segment_comparison" for item in findings)
    assert all("averages differ" not in item["title"] for item in findings)
    assert any(kpi["label"] == "Total revenue" for kpi in result["kpis"])
    assert any(kpi["label"] == "Calculated profit" for kpi in result["kpis"])
    assert any(visual["id"] == "financial-monthly-revenue" for visual in result["suggested_visuals"])
    overview = next(item for item in findings if item["type"] == "financial_overview")
    assert overview["revenue_total"] == 134400.0
    assert overview["profit_total"] == 36600.0
