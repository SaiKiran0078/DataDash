"""Outlier detection with the IQR rule (Tukey fences).

A value is an outlier if it is below Q1 - 1.5*IQR or above Q3 + 1.5*IQR.
Robust to skew and does not assume a normal distribution.
"""
from __future__ import annotations

import pandas as pd

from .errors import DataError

MIN_ROWS = 8


def iqr_bounds(s: pd.Series, k: float = 1.5):
    """Returns (lower, upper) or None when there is too little data / no spread."""
    s = pd.to_numeric(s, errors="coerce").dropna()
    if len(s) < MIN_ROWS:
        return None
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    return float(q1 - k * iqr), float(q3 + k * iqr)


def count_outliers(s: pd.Series) -> int:
    bounds = iqr_bounds(s)
    if bounds is None:
        return 0
    s = pd.to_numeric(s, errors="coerce")
    return int(((s < bounds[0]) | (s > bounds[1])).sum())


def find_outliers(df: pd.DataFrame, schema: list[dict], column: str, limit: int = 50) -> dict:
    kinds = {c["name"]: c["kind"] for c in schema}
    if kinds.get(column) != "numeric":
        raise DataError(f'"{column}" is not a numeric column.')
    s = df[column]
    bounds = iqr_bounds(s)
    if bounds is None:
        return {"column": column, "count": 0, "lower": None, "upper": None, "rows": []}
    mask = (s < bounds[0]) | (s > bounds[1])
    hits = s[mask].dropna()
    # Most extreme first (furthest from the nearest fence).
    distance = hits.map(lambda v: max(bounds[0] - v, v - bounds[1]))
    hits = hits.loc[distance.sort_values(ascending=False).index][:limit]
    return {
        "column": column,
        "count": int(mask.sum()),
        "lower": bounds[0],
        "upper": bounds[1],
        "rows": [{"row": int(i) + 1, "value": float(v)} for i, v in hits.items()],
    }
