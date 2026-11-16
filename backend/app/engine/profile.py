"""Dataset profiling: summary statistics for every column (computed once at upload)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .outliers import count_outliers, iqr_bounds
from .serialize import to_jsonable


def _numeric_profile(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {}
    hist_counts, edges = np.histogram(s, bins=min(10, max(1, s.nunique())))
    return {
        "min": s.min(), "max": s.max(), "mean": s.mean(), "median": s.median(),
        "std": s.std() if len(s) > 1 else 0.0,
        "q1": s.quantile(0.25), "q3": s.quantile(0.75),
        "outliers": count_outliers(s),
        "outlier_bounds": iqr_bounds(s),
        "histogram": {"edges": edges.tolist(), "counts": hist_counts.tolist()},
    }


def _categorical_profile(s: pd.Series) -> dict:
    counts = s.value_counts(dropna=True).head(10)
    return {"top_values": [{"value": str(k), "count": int(v)} for k, v in counts.items()]}


def _datetime_profile(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {}
    return {"min": s.min(), "max": s.max(), "span_days": int((s.max() - s.min()).days)}


def _boolean_profile(s: pd.Series) -> dict:
    s = s.dropna()
    return {"true_count": int(s.sum()), "false_count": int((~s.astype(bool)).sum())}


def profile_frame(df: pd.DataFrame, schema: list[dict]) -> dict:
    n = len(df)
    columns = []
    for col in schema:
        s = df[col["name"]]
        missing = int(s.isna().sum())
        entry = {
            "name": col["name"],
            "kind": col["kind"],
            "missing": missing,
            "missing_pct": round(100 * missing / n, 1) if n else 0.0,
            "unique": int(s.nunique(dropna=True)),
        }
        kind = col["kind"]
        if kind == "numeric":
            entry.update(_numeric_profile(s))
        elif kind in ("categorical", "text", "id"):
            entry.update(_categorical_profile(s))
        elif kind == "datetime":
            entry.update(_datetime_profile(s))
        elif kind == "boolean":
            entry.update(_boolean_profile(s))
        columns.append(entry)

    total_cells = n * len(schema)
    missing_cells = int(df.isna().sum().sum())
    return to_jsonable(
        {
            "rows": n,
            "columns": len(schema),
            "duplicate_rows": int(df.duplicated().sum()),
            "missing_cells": missing_cells,
            "missing_pct": round(100 * missing_cells / total_cells, 1) if total_cells else 0.0,
            "column_profiles": columns,
        }
    )
