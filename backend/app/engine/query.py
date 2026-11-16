"""Filtering, aggregation and chart-data building.

SECURITY: user input is never evaluated as code or a query string. Columns, operators,
aggregations and chart types are checked against allow-lists, and values are coerced
to the column's type before use.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .errors import DataError
from .inference import BOOL_FALSE, BOOL_TRUE
from .serialize import to_jsonable

AGGS = {"count", "sum", "mean", "median", "min", "max"}
CHART_TYPES = {"bar", "line", "pie", "histogram", "scatter"}
FILTER_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "between", "contains"}
TIME_GRAINS = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
MAX_FILTERS = 10
MAX_IN_VALUES = 100
MAX_SCATTER_POINTS = 1000
MAX_COLOR_SERIES = 8
MAX_PAGE_SIZE = 100


def kinds_of(schema: list[dict]) -> dict[str, str]:
    return {c["name"]: c["kind"] for c in schema}


def _need_column(kinds: dict, name, what="column") -> str:
    if not isinstance(name, str) or name not in kinds:
        raise DataError(f'Unknown {what}: "{name}"')
    return name


# ------------------------------------------------------------------ filters
def _coerce(value, kind: str):
    try:
        if kind == "numeric":
            return float(value)
        if kind == "datetime":
            ts = pd.to_datetime(value)
            if pd.isna(ts):
                raise ValueError
            return ts
        if kind == "boolean":
            low = str(value).strip().lower()
            if low in BOOL_TRUE or low == "1":
                return True
            if low in BOOL_FALSE or low == "0":
                return False
            raise ValueError
        return str(value)
    except (ValueError, TypeError, OverflowError):
        raise DataError(f"Invalid value {value!r} for a {kind} column") from None


def apply_filters(df: pd.DataFrame, schema: list[dict], filters: list[dict] | None) -> pd.DataFrame:
    filters = filters or []
    if len(filters) > MAX_FILTERS:
        raise DataError(f"At most {MAX_FILTERS} filters are allowed.")
    kinds = kinds_of(schema)
    mask = pd.Series(True, index=df.index)
    for f in filters:
        col = _need_column(kinds, f.get("column"), "filter column")
        op = f.get("op")
        if op not in FILTER_OPS:
            raise DataError(f'Unknown filter operator "{op}"')
        kind, s, value = kinds[col], df[col], f.get("value")

        if op == "contains":
            if kind not in ("categorical", "text", "id"):
                raise DataError('"contains" only works on text columns.')
            hit = s.str.contains(str(value), case=False, regex=False)
        elif op == "in":
            if not isinstance(value, list) or not value or len(value) > MAX_IN_VALUES:
                raise DataError(f'"in" needs a list of 1-{MAX_IN_VALUES} values.')
            hit = s.isin([_coerce(v, kind) for v in value])
        elif op == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise DataError('"between" needs [low, high].')
            lo, hi = _coerce(value[0], kind), _coerce(value[1], kind)
            hit = (s >= lo) & (s <= hi)
        else:
            v = _coerce(value, kind)
            if op in ("gt", "gte", "lt", "lte") and kind in ("boolean",):
                raise DataError("Comparison operators do not apply to boolean columns.")
            hit = {"eq": s == v, "ne": s != v, "gt": s > v, "gte": s >= v, "lt": s < v, "lte": s <= v}[op]
        mask &= hit.fillna(False).astype(bool)
    return df[mask]


# ------------------------------------------------------------------ chart building
def auto_grain(s: pd.Series) -> str:
    s = s.dropna()
    if s.empty:
        return "month"
    span = (s.max() - s.min()).days
    return "day" if span <= 62 else "month" if span <= 1100 else "year"


def _period_label(p: pd.Period, grain: str) -> str:
    return p.start_time.strftime("%Y-%m-%d") if grain == "week" else str(p)


def build_chart(df: pd.DataFrame, schema: list[dict], spec: dict, filters: list[dict] | None = None) -> dict:
    kinds = kinds_of(schema)
    ctype = spec.get("type")
    if ctype not in CHART_TYPES:
        raise DataError(f'Unknown chart type "{ctype}"')
    data = apply_filters(df, schema, filters)
    if ctype == "histogram":
        result = _histogram(data, kinds, spec)
    elif ctype == "scatter":
        result = _scatter(data, kinds, spec)
    else:
        result = _grouped(data, kinds, spec, ctype)
    result["type"] = ctype
    result["meta"]["filtered_rows"] = len(data)
    return to_jsonable(result)


def _histogram(df, kinds, spec) -> dict:
    x = _need_column(kinds, spec.get("x"), "x column")
    if kinds[x] != "numeric":
        raise DataError("A histogram needs a numeric column.")
    bins = int(min(max(int(spec.get("bins") or 10), 2), 50))
    source = df[x]
    s = source.dropna()
    if s.empty:
        return {"labels": [], "datasets": [{"label": "Count", "data": []}], "meta": {"x": x, "rows_used": 0, "rows_excluded_missing": int(source.isna().sum())}}
    counts, edges = np.histogram(s, bins=bins)
    labels = [f"{edges[i]:.4g} to {edges[i + 1]:.4g}" for i in range(len(counts))]
    return {"labels": labels, "datasets": [{"label": "Count", "data": counts.tolist()}],
            "meta": {"x": x, "rows_used": len(s), "rows_excluded_missing": int(source.isna().sum())}}


def _scatter(df, kinds, spec) -> dict:
    x = _need_column(kinds, spec.get("x"), "x column")
    y = _need_column(kinds, spec.get("y"), "y column")
    if kinds[x] != "numeric" or kinds[y] != "numeric":
        raise DataError("A scatter plot needs two numeric columns.")
    source = df[[x, y]]
    pts = source.dropna()
    corr = float(pts[x].corr(pts[y])) if len(pts) > 2 else None
    sampled = len(pts) > MAX_SCATTER_POINTS
    if sampled:  # deterministic, evenly spaced sample so the same request gives the same picture
        pts = pts.iloc[np.linspace(0, len(pts) - 1, MAX_SCATTER_POINTS).astype(int)]
    return {"points": [{"x": a, "y": b} for a, b in zip(pts[x], pts[y])],
            "meta": {"x": x, "y": y, "rows_used": len(pts), "rows_excluded_missing": int(len(source) - len(pts)), "sampled": sampled, "correlation": corr}}


def _grouped(df, kinds, spec, ctype) -> dict:
    x = _need_column(kinds, spec.get("x"), "x column")
    agg = spec.get("agg") or "count"
    if agg not in AGGS:
        raise DataError(f'Unknown aggregation "{agg}"')
    y = spec.get("y")
    if agg != "count" or y:
        _need_column(kinds, y, "y column")
        if agg != "count" and kinds[y] != "numeric":
            raise DataError(f'"{agg}" needs a numeric y column.')
    xkind = kinds[x]
    if xkind == "numeric" and df[x].nunique() > 30:
        raise DataError("Too many distinct numeric values for a bar/line chart - use a histogram.")

    grain = None
    if xkind == "datetime":
        grain = spec.get("time_grain") or auto_grain(df[x])
        if grain not in TIME_GRAINS:
            raise DataError(f'Unknown time grain "{grain}"')
        key = df[x].dt.to_period(TIME_GRAINS[grain])
    else:
        key = df[x]

    work = pd.DataFrame({"_x": key})
    if y:
        work["_y"] = df[y]
    color = spec.get("color_by")
    if color:
        _need_column(kinds, color, "color_by column")
        if kinds[color] not in ("categorical", "boolean"):
            raise DataError("color_by needs a categorical column.")
        if df[color].nunique() > MAX_COLOR_SERIES:
            raise DataError(f"color_by column has more than {MAX_COLOR_SERIES} distinct values.")
        work["_c"] = df[color].astype("string")

    # Treat missing categorical dimensions as an explicit, honest segment rather than
    # silently dropping those records. Missing dates/numeric measures remain null and
    # are excluded only from visuals that require those values.
    if xkind in {"categorical", "text", "boolean", "id"}:
        work["_x"] = work["_x"].astype("string").fillna("(Not recorded)")
    missing_x = int(work["_x"].isna().sum())
    if color:
        work["_c"] = work["_c"].fillna("(Not recorded)")
    valid_x = work["_x"].notna()
    work = work.loc[valid_x].copy()

    group_cols = ["_x"] + (["_c"] if color else [])
    if agg == "count" and not y:
        res = work.groupby(group_cols, observed=True).size()
    elif agg == "count":
        res = work.dropna(subset=["_y"]).groupby(group_cols, observed=True)["_y"].count()
    else:
        res = work.groupby(group_cols, observed=True)["_y"].agg(agg)

    top_n = int(min(max(int(spec.get("top_n") or 20), 1), 50 if ctype != "pie" else 12))
    sort = spec.get("sort") or ("label" if grain else "value_desc")
    truncated = False

    if color:
        table = res.unstack(fill_value=0)
        order = table.sum(axis=1).sort_values(ascending=False).index if sort == "value_desc" else table.index
        if len(order) > top_n:
            order, truncated = order[:top_n], True
        table = table.loc[order]
        labels = [_label(i, grain) for i in table.index]
        datasets = [{"label": str(c), "data": table[c].tolist()} for c in table.columns]
    else:
        if sort == "value_desc":
            res = res.sort_values(ascending=False)
        elif sort == "label" and not grain:
            res = res.sort_index()
        if len(res) > top_n:
            res, truncated = res.iloc[:top_n], True
        labels = [_label(i, grain) for i in res.index]
        label = "Rows" if agg == "count" and not y else f"{agg} of {y}"
        datasets = [{"label": label, "data": res.tolist()}]

    measure_missing = int(work["_y"].isna().sum()) if y and "_y" in work else 0
    return {"labels": labels, "datasets": datasets,
            "meta": {"x": x, "y": y, "agg": agg, "time_grain": grain,
                     "rows_used": len(work), "rows_excluded_missing_dimension": missing_x,
                     "rows_missing_measure": measure_missing,
                     "missing_category_policy": "label_as_not_recorded" if xkind in {"categorical", "text", "boolean", "id"} else "exclude_from_this_visual",
                     "truncated": truncated}}


def _label(value, grain) -> str:
    return _period_label(value, grain) if isinstance(value, pd.Period) else str(value)


# ------------------------------------------------------------------ table rows
def table_page(df, schema, *, page=1, page_size=25, sort_by=None, descending=False, filters=None) -> dict:
    kinds = kinds_of(schema)
    data = apply_filters(df, schema, filters)
    if sort_by:
        _need_column(kinds, sort_by, "sort column")
        data = data.sort_values(sort_by, ascending=not descending, na_position="last")
    page = max(int(page), 1)
    page_size = min(max(int(page_size), 1), MAX_PAGE_SIZE)
    start = (page - 1) * page_size
    chunk = data.iloc[start:start + page_size]
    return to_jsonable({
        "columns": [c["name"] for c in schema],
        "kinds": [c["kind"] for c in schema],
        "rows": chunk.astype(object).where(chunk.notna(), None).values.tolist(),
        "total": len(data),
        "page": page,
        "page_size": page_size,
    })
