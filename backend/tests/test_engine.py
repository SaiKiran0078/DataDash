import json

import pandas as pd
import pytest
from app.engine.errors import DataError
from app.engine.inference import (
    apply_schema,
    clean_column_names,
    infer_kind,
    normalize_frame,
    to_numeric_text,
)
from app.engine.loader import load_upload
from app.engine.outliers import find_outliers, iqr_bounds
from app.engine.pipeline import ingest
from app.engine.query import apply_filters, build_chart, table_page
from app.engine.recommend import recommend_charts

from .sample_data import sales_csv, xlsx_bytes


@pytest.fixture(scope="module")
def sales():
    return ingest("sales.csv", sales_csv())


def kinds(ing):
    return {c["name"]: c["kind"] for c in ing.schema}


# ------------------------------------------------------------ loading
def test_loads_csv_and_detects_types(sales):
    k = kinds(sales)
    assert k["order_id"] == "id"
    assert k["order_date"] == "datetime"
    assert k["region"] == "categorical"
    assert k["product"] == "categorical"
    assert k["units"] == "numeric"
    assert k["revenue"] == "numeric"          # "₹1,234" strings parsed as numbers
    assert k["returned"] == "boolean"          # Yes / No
    assert k["customer_note"] == "text"        # near-unique sentences


def test_currency_and_negative_parsing():
    s = pd.Series(["₹1,200", "$3,400.50", "(50)", "12%", "abc"])
    out = to_numeric_text(s)
    assert out.iloc[0] == 1200 and out.iloc[1] == 3400.5 and out.iloc[2] == -50 and out.iloc[3] == 12
    assert pd.isna(out.iloc[4])


def test_missing_tokens_become_na(sales):
    # one row had "N/A" as region
    assert sales.frame["region"].isna().sum() == 1


def test_leading_zero_codes_stay_text():
    s = pd.Series(["00123", "04567", "00890", "01234", "09876", "01111"])
    assert infer_kind(s, "zip") in ("text", "categorical")


def test_duplicate_and_blank_headers_are_fixed():
    assert clean_column_names(["a", "a", "", " b  c "]) == ["a", "a_2", "column_3", "b c"]


def test_empty_rows_and_columns_are_dropped():
    raw = pd.DataFrame({"a": ["1", "", "3"], "empty": ["", "", ""], "b": ["x", "", "z"]}).astype("string")
    df, notes = normalize_frame(raw)
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2                       # the middle row was empty in every remaining column
    assert any("empty column" in n for n in notes) and any("empty row" in n for n in notes)


def test_bom_semicolon_and_latin1():
    bom = "﻿name;amount\nÉlise;10\nBob;20\nCara;30\n".encode()
    df = load_upload("x.csv", bom)
    assert list(df.columns) == ["name", "amount"]
    latin = "name,city\nJosé,São Paulo\nAna,Lima\n".encode("cp1252")
    assert "São Paulo" in load_upload("y.csv", latin)["city"].tolist()


def test_xlsx_roundtrip():
    ing = ingest("scores.xlsx", xlsx_bytes())
    k = kinds(ing)
    assert k["Score"] == "numeric" and k["Joined"] == "datetime"
    assert len(ing.frame) == 12


@pytest.mark.parametrize(
    "name,content,status",
    [("a.exe", b"x", 415), ("a.csv", b"", 400), ("a.csv", b"   \n", 400), ("a.xlsx", b"not a zip", 400)],
)
def test_rejects_bad_files(name, content, status):
    with pytest.raises(DataError) as e:
        load_upload(name, content)
    assert e.value.status == status


def test_size_row_and_column_limits():
    with pytest.raises(DataError) as e:
        load_upload("a.csv", b"a\n" + b"1\n" * 100, max_bytes=50)
    assert e.value.status == 413
    with pytest.raises(DataError):
        load_upload("a.csv", b"a\n" + b"1\n" * 50, max_rows=10)
    with pytest.raises(DataError):
        load_upload("a.csv", ("," .join(f"c{i}" for i in range(30)) + "\n" + ",".join("1" * 30) + "\n").encode(), max_cols=10)


def test_zip_bomb_guard(monkeypatch):
    monkeypatch.setattr("app.engine.loader.MAX_UNCOMPRESSED_XLSX", 1000)
    with pytest.raises(DataError) as e:
        load_upload("big.xlsx", xlsx_bytes())
    assert e.value.status == 413


# ------------------------------------------------------------ profile & outliers
def test_profile_numbers(sales):
    p = sales.profile
    assert p["rows"] == 120 and p["columns"] == 8
    rev = next(c for c in p["column_profiles"] if c["name"] == "revenue")
    assert rev["outliers"] >= 1 and rev["max"] == 900000
    region = next(c for c in p["column_profiles"] if c["name"] == "region")
    assert region["missing"] == 1 and region["top_values"][0]["count"] >= 29
    json.dumps(p)  # must be JSON-serialisable (no NaN / numpy types)


def test_iqr_outliers(sales):
    out = find_outliers(sales.frame, sales.schema, "revenue")
    assert out["count"] >= 1
    assert out["rows"][0]["value"] == 900000 and out["rows"][0]["row"] == 5
    with pytest.raises(DataError):
        find_outliers(sales.frame, sales.schema, "region")
    assert iqr_bounds(pd.Series([1, 2, 3])) is None            # too few rows
    assert iqr_bounds(pd.Series([5] * 20)) is None             # no spread


# ------------------------------------------------------------ charts
def test_bar_chart_sum_by_category(sales):
    spec = {"type": "bar", "x": "product", "y": "units", "agg": "sum"}
    res = build_chart(sales.frame, sales.schema, spec)
    assert set(res["labels"]) == {"Laptop", "Phone", "Tablet"}
    assert sum(res["datasets"][0]["data"]) == sales.frame["units"].sum()
    assert res["datasets"][0]["data"] == sorted(res["datasets"][0]["data"], reverse=True)


def test_line_chart_by_month_is_chronological(sales):
    res = build_chart(sales.frame, sales.schema, {"type": "line", "x": "order_date", "y": "units", "agg": "sum", "time_grain": "month"})
    assert res["labels"] == [f"2025-{m:02d}" for m in range(1, 13)]


def test_count_with_color_by(sales):
    res = build_chart(sales.frame, sales.schema, {"type": "bar", "x": "product", "agg": "count", "color_by": "returned"})
    assert {d["label"] for d in res["datasets"]} == {"False", "True"}
    assert sum(sum(d["data"]) for d in res["datasets"]) == 120


def test_histogram_and_scatter(sales):
    h = build_chart(sales.frame, sales.schema, {"type": "histogram", "x": "units", "bins": 5})
    assert sum(h["datasets"][0]["data"]) == 120 and len(h["labels"]) == 5
    s = build_chart(sales.frame, sales.schema, {"type": "scatter", "x": "units", "y": "revenue"})
    assert len(s["points"]) == 120 and s["meta"]["sampled"] is False


def test_scatter_is_sampled_when_large():
    n = 5000
    df = pd.DataFrame({"a": range(n), "b": [float(i % 7) for i in range(n)]})
    schema = [{"name": "a", "kind": "numeric"}, {"name": "b", "kind": "numeric"}]
    res = build_chart(df, schema, {"type": "scatter", "x": "a", "y": "b"})
    assert len(res["points"]) == 1000 and res["meta"]["sampled"] is True


def test_chart_validation_errors(sales):
    f, s = sales.frame, sales.schema
    for spec in [
        {"type": "donut", "x": "region"},
        {"type": "bar", "x": "nope"},
        {"type": "bar", "x": "region", "agg": "sum", "y": "region"},     # non-numeric y
        {"type": "bar", "x": "region", "agg": "evil()"},
        {"type": "histogram", "x": "region"},
        {"type": "scatter", "x": "units", "y": "region"},
        {"type": "bar", "x": "customer_note", "agg": "count", "color_by": "returned", "top_n": 5},  # fine -> checked below
    ]:
        if spec["type"] == "bar" and spec["x"] == "customer_note":
            continue
        with pytest.raises(DataError):
            build_chart(f, s, spec)


# ------------------------------------------------------------ filters
def test_filters(sales):
    f, s = sales.frame, sales.schema
    assert len(apply_filters(f, s, [{"column": "region", "op": "eq", "value": "North"}])) == 30
    assert len(apply_filters(f, s, [{"column": "units", "op": "between", "value": [3, 5]}])) == int(f["units"].between(3, 5).sum())
    assert len(apply_filters(f, s, [{"column": "product", "op": "in", "value": ["Laptop", "Phone"]}])) == 80
    assert len(apply_filters(f, s, [{"column": "order_date", "op": "gte", "value": "2025-06-01"}])) == int((f["order_date"] >= "2025-06-01").sum())
    assert len(apply_filters(f, s, [{"column": "returned", "op": "eq", "value": "yes"}])) == 12
    assert len(apply_filters(f, s, [{"column": "customer_note", "op": "contains", "value": "number 7 "}])) == 1
    both = apply_filters(f, s, [{"column": "region", "op": "eq", "value": "North"}, {"column": "units", "op": "gt", "value": 5}])
    assert (both["region"] == "North").all() and (both["units"] > 5).all()


@pytest.mark.parametrize(
    "bad",
    [
        {"column": "units", "op": "eq", "value": "abc"},
        {"column": "units", "op": "DROP TABLE", "value": 1},
        {"column": "__class__", "op": "eq", "value": 1},
        {"column": "units", "op": "contains", "value": "1"},
        {"column": "units", "op": "between", "value": [1]},
        {"column": "units", "op": "in", "value": []},
        {"column": "returned", "op": "gt", "value": "yes"},
    ],
)
def test_bad_filters_rejected(sales, bad):
    with pytest.raises(DataError):
        apply_filters(sales.frame, sales.schema, [bad])


def test_too_many_filters(sales):
    with pytest.raises(DataError):
        apply_filters(sales.frame, sales.schema, [{"column": "units", "op": "gt", "value": 0}] * 11)


def test_filtered_chart_reports_rows(sales):
    res = build_chart(sales.frame, sales.schema, {"type": "bar", "x": "product", "agg": "count"},
                      [{"column": "region", "op": "eq", "value": "North"}])
    assert res["meta"]["filtered_rows"] == 30 and sum(res["datasets"][0]["data"]) == 30


# ------------------------------------------------------------ table
def test_table_paging_and_sorting(sales):
    page = table_page(sales.frame, sales.schema, page=2, page_size=10, sort_by="revenue", descending=True)
    assert page["total"] == 120 and len(page["rows"]) == 10 and page["page"] == 2
    top = table_page(sales.frame, sales.schema, page_size=1, sort_by="revenue", descending=True)
    assert top["rows"][0][top["columns"].index("revenue")] == 900000
    assert table_page(sales.frame, sales.schema, page_size=5000)["page_size"] == 100
    json.dumps(page)
    with pytest.raises(DataError):
        table_page(sales.frame, sales.schema, sort_by="bogus")


# ------------------------------------------------------------ recommendations
def test_recommendations(sales):
    recs = recommend_charts(sales.frame, sales.schema)
    assert 4 <= len(recs) <= 12
    assert recs == sorted(recs, key=lambda r: -r["score"])
    types = {r["spec"]["type"] for r in recs}
    assert {"line", "bar", "histogram"} <= types
    assert recs[0]["spec"]["type"] == "line" and recs[0]["spec"]["x"] == "order_date"
    assert all(r["reason"] and r["id"] for r in recs)
    # no suggestion may use id/text columns
    used = {v for r in recs for k, v in r["spec"].items() if k in ("x", "y", "color_by")}
    assert "order_id" not in used and "customer_note" not in used
    # every suggested spec must actually run
    for r in recs:
        build_chart(sales.frame, sales.schema, r["spec"])


def test_recommendations_flag_outliers(sales):
    hist = next(r for r in recommend_charts(sales.frame, sales.schema) if r["spec"]["type"] == "histogram" and r["spec"]["x"] == "revenue")
    assert "unusual" in hist["reason"]


def test_recommendations_for_text_only_data():
    ing = ingest("t.csv", b"a,b\n" + b"\n".join(f"word{i} text,other{i} words".encode() for i in range(30)))
    assert recommend_charts(ing.frame, ing.schema) == []


# ------------------------------------------------------------ storage round-trip
def test_schema_roundtrip_through_csv(sales, tmp_path):
    path = tmp_path / "d.csv"
    sales.frame.to_csv(path, index=False)
    back = apply_schema(pd.read_csv(path, dtype=str, keep_default_na=True), sales.schema)
    assert list(back.columns) == list(sales.frame.columns)
    assert back["order_date"].dtype.kind == "M"
    assert back["returned"].dtype.name == "boolean"
    assert back["revenue"].sum() == sales.frame["revenue"].sum()
    assert back["region"].isna().sum() == 1


def test_recommendations_sum_money_but_average_prices():
    """Totals for money/counts, averages for prices and ratings; headline metrics are suggested first."""
    rows = ["day,units,unit_price,revenue,rating"]
    for i in range(1, 41):
        rows.append(f"2025-01-{(i - 1) % 28 + 1:02d},{i % 7 + 1},{100 + i % 5},{(i % 7 + 1) * (100 + i % 5)},{3 + i % 3}")
    ing = ingest("m.csv", ("\n".join(rows) + "\n").encode())
    recs = recommend_charts(ing.frame, ing.schema)
    line = {r["spec"]["y"]: r["spec"]["agg"] for r in recs if r["spec"]["type"] == "line" and r["spec"].get("y")}
    assert line["revenue"] == "sum" and line["units"] == "sum"
    assert line["unit_price"] == "mean"
    assert recs[0]["spec"]["y"] == "revenue"


# ------------------------------------------------------------ date order (DD-MM vs MM-DD)
def _parse(values):
    import pandas as pd
    from app.engine.inference import to_datetime_text
    return [d.strftime("%Y-%m-%d") for d in to_datetime_text(pd.Series(values))]


def test_day_first_dates_are_detected_from_the_data():
    # 13 can only be a day, so the whole column is DD-MM-YYYY - including the ambiguous 02-01-2025
    assert _parse(["13-01-2025", "02-01-2025"]) == ["2025-01-13", "2025-01-02"]


def test_month_first_dates_are_detected_from_the_data():
    assert _parse(["01-13-2025", "02-01-2025"]) == ["2025-01-13", "2025-02-01"]


def test_iso_dates_are_never_swapped():
    assert _parse(["2025-01-02", "2025-12-31"]) == ["2025-01-02", "2025-12-31"]


def test_indian_sample_file_dates_survive_ingest():
    """Regression: 138 of 421 sample dates used to come back with day and month swapped."""
    from pathlib import Path

    import pandas as pd
    path = Path(__file__).resolve().parents[2] / "sample_data" / "sales.csv"
    raw = pd.read_csv(path, dtype=str)
    truth = pd.to_datetime(raw["order_date"], format="%d-%m-%Y")
    got = ingest("sales.csv", path.read_bytes()).frame["order_date"]
    assert (truth.values == got.values).all()


def test_ingest_retains_type_coercion_diagnostics():
    rows = [f"{(i * 17) % 53},2025-01-{(i % 28) + 1:02d}" for i in range(1, 101)]
    rows[4] = "not-money,2025-01-05"
    rows[8] = "9,not-a-date"
    payload = ("amount,when\n" + "\n".join(rows) + "\n").encode()
    ing = ingest("parse.csv", payload)
    diagnostics = ing.profile["ingestion_diagnostics"]
    assert {item["column"] for item in diagnostics} == {"amount", "when"}
    assert all(item["count"] == 1 for item in diagnostics)
    assert any(sample["value"] == "not-money" for item in diagnostics for sample in item["sample_values"])


def test_grouped_chart_preserves_missing_categories_as_not_recorded():
    frame = pd.DataFrame({"segment": pd.Series(["A", None, "B", None], dtype="string"),
                          "amount": [10.0, 20.0, None, 40.0]})
    schema = [{"name": "segment", "kind": "categorical"}, {"name": "amount", "kind": "numeric"}]
    result = build_chart(frame, schema, {"type": "bar", "x": "segment", "y": "amount", "agg": "sum"})
    assert "(Not recorded)" in result["labels"]
    assert result["meta"]["missing_category_policy"] == "label_as_not_recorded"
    assert result["meta"]["rows_used"] == 4
    assert result["meta"]["rows_missing_measure"] == 1


def test_time_chart_excludes_missing_dates_only_from_that_visual():
    frame = pd.DataFrame({"event_date": pd.to_datetime(["2025-01-01", None, "2025-02-01"]),
                          "amount": [10.0, 20.0, 30.0]})
    schema = [{"name": "event_date", "kind": "datetime"}, {"name": "amount", "kind": "numeric"}]
    result = build_chart(frame, schema, {"type": "line", "x": "event_date", "y": "amount", "agg": "sum", "time_grain": "month"})
    assert result["meta"]["rows_used"] == 2
    assert result["meta"]["rows_excluded_missing_dimension"] == 1
    assert len(frame) == 3  # visual scoping never mutates or deletes source records
