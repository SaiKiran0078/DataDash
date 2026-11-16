"""Computing the data behind every widget of a dashboard."""
from __future__ import annotations

import pandas as pd

from app.engine.errors import DataError
from app.engine.query import build_chart


def _table_row_matches(
    row: dict,
    column: str,
    op: str,
    value,
) -> bool:
    """Evaluate one table row against a dashboard filter."""
    current = row.get(column)

    if op == "eq":
        return str(current) == str(value)
    if op == "ne":
        return str(current) != str(value)
    if op == "contains":
        return str(value).lower() in str(current).lower()
    if op == "in":
        return str(current) in {str(v) for v in (value or [])}

    try:
        left = float(current)
        if op == "between":
            return float(value[0]) <= left <= float(value[1])

        right = float(value)
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        if op == "lte":
            return left <= right
    except (TypeError, ValueError, IndexError):
        return False

    return True


def widget_filters(dashboard_filters: list[dict], widget: dict) -> list[dict]:
    return list(dashboard_filters or []) + list(widget.get("filters") or [])


def render_widgets(frame: pd.DataFrame, schema: list[dict], widgets: list[dict], dashboard_filters: list[dict]) -> list[dict]:
    """One broken widget must not break the whole dashboard, so errors are reported per widget."""
    out = []
    for w in widgets:
        display_type = w.get("display_type", "chart")
        if display_type == "table":
            data = None
            table_columns = w.get("table_columns") or []
            table_rows = list(w.get("table_rows") or [])
            # Pivot snapshots can still participate in cross-filtering when the
            # selected dimension is one of their displayed columns.
            for f in widget_filters(dashboard_filters, w):
                column, op, value = f.get("column"), f.get("op"), f.get("value")
                if column not in table_columns:
                    continue
                table_rows = [
                    row
                    for row in table_rows
                    if _table_row_matches(row, column, op, value)
                ]
        else:
            try:
                data = build_chart(frame, schema, w["spec"], widget_filters(dashboard_filters, w))
            except DataError as exc:
                data = {"error": str(exc)}
            table_columns, table_rows = [], []
        out.append({"id": w["id"], "title": w["title"], "spec": w.get("spec"), "page": w.get("page", "Overview"),
                    "display_type": display_type, "table_columns": table_columns, "table_rows": table_rows, "data": data})
    return out


def validate_widgets(frame: pd.DataFrame, schema: list[dict], widgets: list[dict], dashboard_filters: list[dict]) -> None:
    """Reject a dashboard that references unknown columns, bad aggregations, etc. before saving it."""
    for w in widgets:
        if w.get("display_type", "chart") == "table":
            columns = w.get("table_columns") or []
            rows = w.get("table_rows") or []
            if not columns or len(columns) > 20 or len(rows) > 500:
                raise DataError(f'Widget "{w["title"]}": invalid table dimensions', 422)
            if any(not isinstance(row, dict) for row in rows):
                raise DataError(f'Widget "{w["title"]}": table rows must be objects', 422)
            continue
        if not w.get("spec"):
            raise DataError(f'Widget "{w["title"]}": chart specification is required', 422)
        try:
            build_chart(frame, schema, w["spec"], widget_filters(dashboard_filters, w))
        except DataError as exc:
            raise DataError(f'Widget "{w["title"]}": {exc}', 422) from exc
