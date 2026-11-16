from types import SimpleNamespace

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import DatasetFile
from app.db.session import Base
from app.engine.pipeline import ingest
from app.services.dataset_store import DatasetStore
from .sample_data import sales_csv


def test_database_backed_store_survives_recreation(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    imported = ingest("sales.csv", sales_csv())
    dataset = SimpleNamespace(stored_name=None, schema_json=imported.schema)

    first = DatasetStore(tmp_path / "first", session_factory=sessions)
    dataset.stored_name = first.save(imported.frame)
    assert not list((tmp_path / "first").glob("*.csv"))

    restarted = DatasetStore(tmp_path / "after-restart", session_factory=sessions)
    restored = restarted.load(dataset)
    assert restored["revenue"].sum() == imported.frame["revenue"].sum()
    assert restored["order_date"].dtype.kind == "M"

    with sessions() as db:
        assert db.get(DatasetFile, dataset.stored_name) is not None

    restarted.delete(dataset)
    with sessions() as db:
        assert db.get(DatasetFile, dataset.stored_name) is None
    engine.dispose()


def test_database_backed_store_rejects_invalid_keys(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    store = DatasetStore(tmp_path, session_factory=sessionmaker(engine))
    for name in ("../escape.csv", "anything.csv", "", None):
        try:
            store.delete_file(name)
        except ValueError as exc:
            assert "Invalid stored dataset filename" in str(exc)
        else:
            raise AssertionError(f"Expected invalid key rejection: {name!r}")
    engine.dispose()
