"""Chart recommendation: look at the column types and suggest the charts a human analyst would draw first.

Rules (each suggestion carries a score and a plain-English reason):
  * date + number            -> line chart of the number over time
  * category + number/count  -> bar chart (pie if only a few categories)
  * number                   -> histogram (distribution), flagged when outliers exist
  * number + number          -> scatter when the columns are clearly correlated
"""
from __future__ import annotations

import re

import pandas as pd

from .outliers import count_outliers

# Name hints. A column named "revenue" is almost always THE number the reader cares about; a "unit_price" or
# "rating" should be averaged, never summed.
HEADLINE_NAMES = re.compile(r"(revenue|sales|amount|total|profit|income|spend|expense|cost|turnover|gmv)", re.IGNORECASE)
ADDITIVE_NAMES = re.compile(r"(qty|quantity|units|count|orders|visits|clicks|views)", re.IGNORECASE)
AVERAGE_NAMES = re.compile(r"(price|rate|rating|score|age|percent|pct|ratio|margin|discount|temp|average|avg)", re.IGNORECASE)
MAX_MEASURES = 3
MAX_CATEGORIES = 3


def _default_agg(name: str) -> str:
    """Totals make sense for money and counts; averages for prices, rates and scores."""
    if AVERAGE_NAMES.search(name):
        return "mean"
    return "sum" if HEADLINE_NAMES.search(name) or ADDITIVE_NAMES.search(name) else "mean"


def _measure_rank(name: str, position: int) -> tuple:
    """Lower sorts first: headline metrics, then additive counts, then the rest, then averages-only columns."""
    if AVERAGE_NAMES.search(name):
        tier = 3
    elif HEADLINE_NAMES.search(name):
        tier = 0
    elif ADDITIVE_NAMES.search(name):
        tier = 1
    else:
        tier = 2
    return (tier, position)


def _pretty(agg: str, y: str, x: str, by: bool = True) -> str:
    verb = {"sum": "Total", "mean": "Average", "count": "Number of rows"}.get(agg, agg.title())
    return f"{verb} {y} by {x}" if agg != "count" else f"Number of rows by {x}"


def recommend_charts(df: pd.DataFrame, schema: list[dict], limit: int = 12) -> list[dict]:
    kinds = {c["name"]: c["kind"] for c in schema}
    numeric = [c for c, k in kinds.items() if k == "numeric"]
    datetimes = [c for c, k in kinds.items() if k == "datetime"]
    cats = [c for c, k in kinds.items() if k in ("categorical", "boolean", "text")]
    # Best categories first: fewest distinct values (but at least 2 so there is something to compare)
    cats = sorted((c for c in cats if 2 <= df[c].nunique() <= (20 if kinds[c] == "text" else 30)), key=lambda c: (df[c].nunique(), list(kinds).index(c)))[:MAX_CATEGORIES]
    # Prefer headline metrics (revenue, sales...) first, then counts, then everything else
    measures = sorted(numeric, key=lambda c: _measure_rank(c, numeric.index(c)))[:MAX_MEASURES]

    out: list[dict] = []

    def add(score, title, reason, **spec):
        out.append({"score": score, "title": title, "reason": reason, "spec": spec})

    if datetimes:
        dt = min(datetimes, key=lambda c: df[c].isna().sum())
        for i, m in enumerate(measures):
            agg = _default_agg(m)
            add(92 - i * 4, f"{'Total' if agg == 'sum' else 'Average'} {m} over time",
                f"'{dt}' is a date and '{m}' is a number - a trend line shows how it changes.",
                type="line", x=dt, y=m, agg=agg)
        add(70, "Number of rows over time", f"Shows how many records fall in each period of '{dt}'.",
            type="line", x=dt, agg="count")
        if cats and measures and df[cats[0]].nunique() <= 6:
            c, m = cats[0], measures[0]
            add(74, f"{m} over time by {c}", f"Compares how each '{c}' contributes over time.",
                type="line", x=dt, y=m, agg=_default_agg(m), color_by=c)

    for ci, c in enumerate(cats):
        n = df[c].nunique()
        add(80 - ci * 3, f"Number of rows by {c}", f"'{c}' has {n} groups - counting rows shows the mix.",
            type="pie" if n <= 6 else "bar", x=c, agg="count")
        for mi, m in enumerate(measures[:2]):
            agg = _default_agg(m)
            add(86 - ci * 3 - mi * 2, _pretty(agg, m, c), f"Compares '{m}' across the groups in '{c}'.",
                type="bar", x=c, y=m, agg=agg)

    for i, m in enumerate(numeric[:4]):
        outliers = count_outliers(df[m])
        reason = f"Shows how '{m}' is distributed."
        if outliers:
            reason += f" {outliers} unusual value(s) detected."
        add(60 + (10 if outliers else 0) - i, f"Distribution of {m}", reason, type="histogram", x=m, bins=10)

    pairs = []
    cols = numeric[:8]
    if len(cols) >= 2:
        corr = df[cols].corr()
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                r = corr.loc[a, b]
                if pd.notna(r) and abs(r) >= 0.3:
                    pairs.append((abs(r), r, a, b))
        for _, r, a, b in sorted(pairs, reverse=True)[:2]:
            add(55 + int(abs(r) * 30), f"{a} vs {b}", f"These two move together (correlation {r:+.2f}).",
                type="scatter", x=a, y=b)

    out.sort(key=lambda s: -s["score"])
    # Keep the list varied: cap how many suggestions of one chart type can appear.
    caps = {"line": 3, "bar": 4, "pie": 2, "histogram": 3, "scatter": 2}
    used: dict[str, int] = {}
    seen, unique = set(), []
    for s in out:
        key = (s["spec"]["type"], s["spec"].get("x"), s["spec"].get("y"), s["spec"].get("agg"), s["spec"].get("color_by"))
        t = s["spec"]["type"]
        if key in seen or used.get(t, 0) >= caps[t]:
            continue
        seen.add(key)
        used[t] = used.get(t, 0) + 1
        unique.append(s)
    for i, s in enumerate(unique[:limit], start=1):
        s["id"] = f"s{i}"
    return unique[:limit]
