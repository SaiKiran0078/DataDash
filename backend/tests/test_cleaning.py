import pandas as pd
import pytest
from app.api.routes.datasets import _clean_frame
from app.engine.errors import DataError


def test_clean_pipeline_trims_deduplicates_and_fills():
    frame = pd.DataFrame({"name": [" Alice ", "Bob", "Bob"], "sales": [10.0, 20.0, 20.0], "segment": ["A", None, None]})
    cleaned, log = _clean_frame(frame, [
        {"type": "trim_text"},
        {"type": "drop_duplicates"},
        {"type": "fill_missing", "column": "segment", "strategy": "mode"},
    ])
    assert len(cleaned) == 2
    assert cleaned["name"].tolist() == ["Alice", "Bob"]
    assert cleaned["segment"].isna().sum() == 0
    assert len(log) == 3


def test_clean_preview_operations_do_not_mutate_input():
    frame = pd.DataFrame({"x": [1.0, None, 3.0]})
    cleaned, _ = _clean_frame(frame, [{"type": "fill_missing", "column": "x", "strategy": "median"}])
    assert frame["x"].isna().sum() == 1
    assert cleaned["x"].isna().sum() == 0


def test_clean_rejects_dropping_last_column():
    frame = pd.DataFrame({"only": [1, 2]})
    with pytest.raises(DataError):
        _clean_frame(frame, [{"type": "drop_column", "column": "only"}])


def test_clean_rejects_unknown_column():
    frame = pd.DataFrame({"x": [1, 2]})
    with pytest.raises(DataError):
        _clean_frame(frame, [{"type": "fill_missing", "column": "missing", "strategy": "mean"}])



def test_date_fill_rejects_non_date_custom_value_as_data_error():
    frame = pd.DataFrame({"ClaimDate": pd.to_datetime(["2024-01-01", None, "2024-01-03"])})
    with pytest.raises(DataError, match="not a valid date"):
        _clean_frame(frame, [{"type": "fill_missing", "column": "ClaimDate", "strategy": "value", "value": "Unknown"}])


def test_date_forward_fill_is_typed_and_reports_filled_cell_count():
    frame = pd.DataFrame({"ClaimDate": pd.to_datetime(["2024-01-01", None, "2024-01-03"])})
    cleaned, log = _clean_frame(frame, [{"type": "fill_missing", "column": "ClaimDate", "strategy": "ffill"}])
    assert cleaned["ClaimDate"].isna().sum() == 0
    assert str(cleaned["ClaimDate"].dtype).startswith("datetime64")
    assert log[0]["cells_filled"] == 1
    assert log[0]["missing_before"] == 1
    assert log[0]["missing_after"] == 0


def test_numeric_custom_fill_rejects_unknown_string():
    frame = pd.DataFrame({"amount": [10.0, None, 30.0]})
    with pytest.raises(DataError, match="valid numeric replacement"):
        _clean_frame(frame, [{"type": "fill_missing", "column": "amount", "strategy": "value", "value": "Unknown"}])
