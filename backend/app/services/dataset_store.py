"""Database-backed CSV snapshots with a small in-process DataFrame cache.

CSV text is stored in the configured SQL database (Neon in the hosted demo), not
on Render's ephemeral filesystem. Filesystem mode remains available for isolated
unit tests and local callers that do not supply a session factory.
"""
from __future__ import annotations

import re
import secrets
import threading
from collections import OrderedDict
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.db.models import DatasetFile
from app.engine.inference import apply_schema


class DatasetStore:
    def __init__(self, data_dir: Path, cache_size: int = 8, session_factory=None):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._session_factory = session_factory
        self._cache: OrderedDict[tuple, pd.DataFrame] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()

    def _validate_name(self, stored_name: str) -> str:
        if not isinstance(stored_name, str) or not re.fullmatch(r"[0-9a-f]{32}\.csv", stored_name):
            raise ValueError("Invalid stored dataset filename")
        return stored_name

    def _path_for(self, stored_name: str) -> Path:
        return self.dir / self._validate_name(stored_name)

    def save(self, frame: pd.DataFrame) -> str:
        name = f"{secrets.token_hex(16)}.csv"
        if self._session_factory is not None:
            content = frame.to_csv(index=False)
            db = self._session_factory()
            try:
                db.add(DatasetFile(stored_name=name, csv_content=content))
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
            return name

        # Local filesystem fallback for tests and development.
        frame.to_csv(self._path_for(name), index=False, encoding="utf-8")
        return name

    def load(self, dataset) -> pd.DataFrame:
        name = self._validate_name(dataset.stored_name)
        if self._session_factory is not None:
            db = self._session_factory()
            try:
                content = db.scalar(select(DatasetFile.csv_content).where(DatasetFile.stored_name == name))
            finally:
                db.close()
            if content is None:
                raise FileNotFoundError(f"Dataset content is missing from the database: {name}")
            cache_key = (name, hash(content))
        else:
            path = self._path_for(name)
            stat = path.stat()
            content = path.read_text(encoding="utf-8")
            cache_key = (name, stat.st_mtime_ns)

        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]

        from io import StringIO
        raw = pd.read_csv(StringIO(content), dtype=str, keep_default_na=False, na_values=[""])
        frame = apply_schema(raw, dataset.schema_json)
        with self._lock:
            self._cache[cache_key] = frame
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return frame

    def delete_file(self, stored_name: str) -> None:
        name = self._validate_name(stored_name)
        if self._session_factory is not None:
            db = self._session_factory()
            try:
                row = db.get(DatasetFile, name)
                if row is not None:
                    db.delete(row)
                    db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        else:
            self._path_for(name).unlink(missing_ok=True)
        with self._lock:
            for key in [key for key in self._cache if key[0] == name]:
                del self._cache[key]

    def delete(self, dataset) -> None:
        self.delete_file(dataset.stored_name)
