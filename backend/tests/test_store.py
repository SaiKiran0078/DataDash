from types import SimpleNamespace

import pytest
from app.engine.errors import DataError
from app.engine.pipeline import ingest
from app.services.dashboards import render_widgets, validate_widgets
from app.services.dataset_store import DatasetStore

from .sample_data import sales_csv


def test_store_roundtrip_cache_and_delete(tmp_path):
    ing = ingest("s.csv", sales_csv())
    store = DatasetStore(tmp_path)
    name = store.save(ing.frame)
    ds = SimpleNamespace(stored_name=name, schema_json=ing.schema)

    first = store.load(ds)
    assert store.load(ds) is first                                   # served from cache
    assert first["revenue"].sum() == ing.frame["revenue"].sum()
    assert first["order_date"].dtype.kind == "M"
    assert first["region"].isna().sum() == 1                          # missing values survive the round trip

    store.delete(ds)
    assert not (tmp_path / name).exists()


def test_store_cache_is_bounded(tmp_path):
    ing = ingest("s.csv", sales_csv(rows=20))
    store = DatasetStore(tmp_path, cache_size=2)
    datasets = [SimpleNamespace(stored_name=store.save(ing.frame), schema_json=ing.schema) for _ in range(4)]
    for d in datasets:
        store.load(d)
    assert len(store._cache) == 2


def test_dashboard_rendering_isolates_broken_widgets():
    ing = ingest("s.csv", sales_csv())
    good = {"id": "w1", "title": "Units by product", "spec": {"type": "bar", "x": "product", "y": "units", "agg": "sum"}}
    bad = {"id": "w2", "title": "Broken", "spec": {"type": "bar", "x": "no_such_column"}}
    out = render_widgets(ing.frame, ing.schema, [good, bad], [])
    assert "labels" in out[0]["data"] and "error" in out[1]["data"]
    with pytest.raises(DataError) as e:
        validate_widgets(ing.frame, ing.schema, [good, bad], [])
    assert e.value.status == 422 and "Broken" in str(e.value)
    validate_widgets(ing.frame, ing.schema, [good], [{"column": "region", "op": "eq", "value": "North"}])



def test_dashboard_table_filters_apply_all_operators_and_bounds():
    from app.services.dashboards import _table_row_matches

    row = {"region": "North", "revenue": "150", "units": "8"}
    assert _table_row_matches(row, "region", "eq", "North")
    assert _table_row_matches(row, "region", "ne", "South")
    assert _table_row_matches(row, "region", "contains", "ort")
    assert _table_row_matches(row, "region", "in", ["South", "North"])
    assert _table_row_matches(row, "revenue", "gt", 100)
    assert _table_row_matches(row, "revenue", "gte", 150)
    assert _table_row_matches(row, "revenue", "lt", 200)
    assert _table_row_matches(row, "revenue", "lte", 150)
    assert _table_row_matches(row, "revenue", "between", [100, 200])
    assert not _table_row_matches(row, "revenue", "between", [151, 200])
    assert not _table_row_matches({"revenue": "not-a-number"}, "revenue", "gt", 10)
    assert not _table_row_matches({"revenue": "not-a-number"}, "revenue", "between", [1, 10])


def test_dashboard_table_widget_applies_dashboard_and_widget_filters():
    frame = __import__("pandas").DataFrame(
        {"region": ["North", "South", "North"], "revenue": [100, 150, 250]}
    )
    widgets = [{
        "id": "table-1",
        "title": "Regional sales",
        "display_type": "table",
        "table_columns": ["region", "revenue"],
        "table_rows": [
            {"region": "North", "revenue": "100"},
            {"region": "South", "revenue": "150"},
            {"region": "North", "revenue": "250"},
        ],
        "filters": [{"column": "revenue", "op": "between", "value": [100, 200]}],
    }]
    out = render_widgets(
        frame,
        [],
        widgets,
        [{"column": "region", "op": "eq", "value": "North"}],
    )
    assert out[0]["table_rows"] == [{"region": "North", "revenue": "100"}]



def test_store_rejects_path_traversal_and_non_generated_names(tmp_path):
    store = DatasetStore(tmp_path)
    for unsafe in ("../outside.csv", "subdir/file.csv", "anything.csv", "", None):
        with pytest.raises(ValueError, match="Invalid stored dataset filename"):
            store.delete_file(unsafe)


def test_store_save_is_atomic_and_creates_only_final_snapshot(tmp_path):
    import pandas as pd

    store = DatasetStore(tmp_path)
    name = store.save(pd.DataFrame({"value": [1, 2, 3]}))
    assert len(name) == 36 and name.endswith(".csv")
    assert sorted(path.name for path in tmp_path.iterdir()) == [name]
    loaded = store.load(SimpleNamespace(stored_name=name, schema_json=[{"name": "value", "kind": "numeric"}]))
    assert loaded["value"].tolist() == [1, 2, 3]
