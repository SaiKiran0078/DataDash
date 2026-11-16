"""Column cleaning and type detection.

Kinds: numeric | datetime | boolean | categorical | text | id | empty
"""
from __future__ import annotations

import re
import warnings

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

MISSING_TOKENS = {"", "na", "n/a", "nan", "null", "none", "#n/a"}
BOOL_TRUE = {"true", "t", "yes", "y"}
BOOL_FALSE = {"false", "f", "no", "n"}
ID_NAME = re.compile(r"(^id$|_id$|^id_|uuid|guid|^index$|^sr\.?\s?no)", re.IGNORECASE)
PARSE_THRESHOLD = 0.95
CATEGORY_MAX_UNIQUE = 50


# ---------------------------------------------------------------- cleaning
def clean_column_names(columns) -> list[str]:
    """Strip, fill blanks, and make duplicates unique: ['a', 'a', ''] -> ['a', 'a_2', 'column_3']."""
    seen: dict[str, int] = {}
    out = []
    for i, raw in enumerate(columns, start=1):
        name = re.sub(r"\s+", " ", str(raw)).strip() or f"column_{i}"
        base, k = name, seen.get(name, 0) + 1
        seen[name] = k
        if k > 1:
            name = f"{base}_{k}"
            seen[name] = 1
        out.append(name)
    return out


def normalize_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Tidy a raw text frame: names, whitespace, missing-value tokens, empty rows/columns."""
    notes: list[str] = []
    df = df.copy()
    df.columns = clean_column_names(df.columns)

    for col in df.columns:
        s = df[col].astype("string").str.strip()
        df[col] = s.mask(s.str.lower().isin(MISSING_TOKENS))

    before_rows, _ = df.shape
    df = df.dropna(axis=0, how="all")
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        df = df.drop(columns=empty_cols)
        notes.append(f"Dropped {len(empty_cols)} empty column(s): {', '.join(empty_cols[:5])}")
    if len(df) < before_rows:
        notes.append(f"Dropped {before_rows - len(df)} empty row(s)")
    return df.reset_index(drop=True), notes


# ---------------------------------------------------------------- parsing helpers
def to_numeric_text(s: pd.Series) -> pd.Series:
    """'₹1,200' -> 1200.0, '(50)' -> -50.0, '12%' -> 12.0, junk -> NaN."""
    t = s.astype("string").str.strip()
    negative = t.str.match(r"^\(.*\)$").fillna(False).to_numpy(dtype=bool)
    t = t.str.replace(r"[()₹$€£¥,%\s]", "", regex=True)
    values = pd.to_numeric(t, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
    values[negative] = -values[negative]
    return pd.Series(values, index=s.index, dtype="float64")


_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})[-/.]\d{2,4}")


def detect_dayfirst(t: pd.Series) -> bool:
    """Is a column of dates like 02-01-2025 written day-first (DD-MM-YYYY) or month-first (MM-DD-YYYY)?

    Let the data decide: a first number above 12 can only be a day (13-01-2025), a second number above 12
    can only be a day in a month-first file (01-13-2025). If every value is ambiguous we keep pandas' default
    (month-first); ISO dates (2025-01-02) are never ambiguous.
    """
    parts = t.astype("string").str.extract(_NUMERIC_DATE)
    first = pd.to_numeric(parts[0], errors="coerce")
    second = pd.to_numeric(parts[1], errors="coerce")
    return bool((first > 12).any() and not (second > 12).any())


def to_datetime_text(s: pd.Series) -> pd.Series:
    t = s.astype("string").str.strip()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(t, errors="coerce", format="mixed", dayfirst=detect_dayfirst(t))
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
    return parsed


def _has_leading_zero_codes(t: pd.Series) -> bool:
    """'00123' / '0712' look numeric but are codes (zip, phone) - keep them as text."""
    return bool(t.str.match(r"^0\d+$").fillna(False).any())


# ---------------------------------------------------------------- detection
def infer_kind(series: pd.Series, name: str = "") -> str:
    s = series.dropna()
    n = len(s)
    if n == 0:
        return "empty"
    if is_bool_dtype(s):
        return "boolean"
    if is_datetime64_any_dtype(s):
        return "datetime"

    t = s.astype("string").str.strip()
    unique_lower = set(t.str.lower().unique())

    # Two (or fewer) distinct values, all of them yes/no style words -> boolean.
    if len(unique_lower) <= 2 and unique_lower <= (BOOL_TRUE | BOOL_FALSE):
        return "boolean"

    if not _has_leading_zero_codes(t):
        num = to_numeric_text(t)
        if num.notna().mean() >= PARSE_THRESHOLD:
            return _numeric_or_id(num.dropna(), name)

    # A date needs digits AND a separator or month name; pure-digit strings (codes) are not dates.
    date_shaped = t.str.contains(r"\d") & t.str.contains(r"\D")
    if (
        date_shaped.mean() >= PARSE_THRESHOLD
        and to_datetime_text(t).notna().mean() >= PARSE_THRESHOLD
    ):
        return "datetime"

    nunique = t.nunique()
    if nunique == n and n >= 5 and ID_NAME.search(name):
        return "id"
    if nunique <= CATEGORY_MAX_UNIQUE and (nunique / n <= 0.5 or nunique <= 12):
        return "categorical"
    return "text"


def _numeric_or_id(num: pd.Series, name: str) -> str:
    is_integer = bool((num == num.round()).all())
    unique = num.nunique() == len(num)
    if (
        is_integer
        and unique
        and len(num) >= 5
        and (ID_NAME.search(name) or (len(num) >= 20 and num.is_monotonic_increasing))
    ):
        return "id"
    return "numeric"


def convert(series: pd.Series, kind: str) -> pd.Series:
    """Cast a text/mixed column to the dtype that matches its detected kind."""
    if kind == "numeric":
        return series if is_numeric_dtype(series) and not is_bool_dtype(series) else to_numeric_text(series)
    if kind == "datetime":
        return series if is_datetime64_any_dtype(series) else to_datetime_text(series)
    if kind == "boolean":
        if is_bool_dtype(series):
            return series.astype("boolean")
        low = series.astype("string").str.strip().str.lower()
        return low.map(lambda v: pd.NA if pd.isna(v) else v in BOOL_TRUE).astype("boolean")
    return series.astype("string")


def analyze_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Detect every column's kind and return (typed frame, schema)."""
    typed = {}
    schema = []
    for col in df.columns:
        kind = infer_kind(df[col], col)
        typed[col] = convert(df[col], kind)
        schema.append({"name": col, "kind": kind})
    return pd.DataFrame(typed), schema


def apply_schema(df: pd.DataFrame, schema: list[dict]) -> pd.DataFrame:
    """Re-apply a stored schema to a frame re-read from disk (no re-detection)."""
    out = {}
    for col in schema:
        out[col["name"]] = convert(df[col["name"]], col["kind"])
    return pd.DataFrame(out)
