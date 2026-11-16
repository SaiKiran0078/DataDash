"""Request bodies. Pydantic rejects unknown fields and out-of-range values before any logic runs."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Credentials(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("Enter a valid email address")
        return v


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["bar", "line", "pie", "histogram", "scatter"]
    x: str | None = Field(None, max_length=200)
    y: str | None = Field(None, max_length=200)
    agg: Literal["count", "sum", "mean", "median", "min", "max"] | None = None
    time_grain: Literal["day", "week", "month", "quarter", "year"] | None = None
    color_by: str | None = Field(None, max_length=200)
    top_n: int | None = Field(None, ge=1, le=50)
    sort: Literal["value_desc", "label"] | None = None
    bins: int | None = Field(None, ge=2, le=50)

    def clean(self) -> dict:
        return self.model_dump(exclude_none=True)


class FilterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=200)
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "between", "contains"]
    value: Any = None


class ChartRequest(BaseModel):
    spec: ChartSpec
    filters: list[FilterIn] = Field(default_factory=list, max_length=10)


class WidgetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=120)
    spec: ChartSpec | None = None
    filters: list[FilterIn] = Field(default_factory=list, max_length=10)
    page: str = Field(default="Overview", min_length=1, max_length=40)
    display_type: Literal["chart", "table"] = "chart"
    table_columns: list[str] = Field(default_factory=list, max_length=20)
    table_rows: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dataset_id: int
    widgets: list[WidgetIn] = Field(default_factory=list, max_length=20)
    filters: list[FilterIn] = Field(default_factory=list, max_length=10)


class AutoBuildRequest(BaseModel):
    business_question: str = Field(default="", max_length=1200)
    audience: str = Field(default="Business stakeholders", max_length=300)
    row_grain: str = Field(default="", max_length=500)
    apply_safe_text_trim: bool = True


class DatasetRename(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class RowsRequest(BaseModel):
    filters: list[FilterIn] = Field(default_factory=list, max_length=10)


class CleanRequest(BaseModel):
    """A small, explicit list of reversible-in-preview dataset cleaning operations."""
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=20)


class AnalysisReportIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    business_question: str = Field(default="", max_length=1200)
    audience: str = Field(default="", max_length=300)
    row_grain: str = Field(default="", max_length=500)
    executive_summary: str = Field(default="", max_length=12000)
    findings: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    recommendations: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
