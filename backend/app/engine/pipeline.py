"""High-level entry point used by the API: raw upload bytes -> typed frame + schema + profile."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .errors import DataError
from .inference import analyze_frame, convert, infer_kind, normalize_frame
from .loader import load_upload
from .profile import profile_frame


@dataclass
class Ingested:
    frame: pd.DataFrame
    schema: list[dict]
    profile: dict
    notes: list[str]


def ingest(filename: str, content: bytes, **limits) -> Ingested:
    raw = load_upload(filename, content, **limits)
    cleaned, notes = normalize_frame(raw)
    if cleaned.empty or cleaned.shape[1] == 0:
        raise DataError("No usable data found (all rows or columns were empty).")
    # Capture coercion failures before typed conversion turns invalid values into nulls.
    # This preserves evidence for the analyst even though the analytical frame is typed.
    parse_diagnostics = []
    for column in cleaned.columns:
        kind = infer_kind(cleaned[column], column)
        if kind not in {"numeric", "datetime", "boolean"}:
            continue
        converted = convert(cleaned[column], kind)
        bad = cleaned[column].notna() & converted.isna()
        count = int(bad.sum())
        if count:
            sample = []
            for idx, value in cleaned.loc[bad, column].head(10).items():
                sample.append({"row": int(idx) + 1, "value": str(value)[:120]})
            parse_diagnostics.append({"column": column, "detected_type": kind, "count": count,
                                      "sample_values": sample,
                                      "recommendation": "Review the source values and locale/format. Correct only confirmed invalid entries; do not replace them with zero or an arbitrary value."})
    frame, schema = analyze_frame(cleaned)
    profile = profile_frame(frame, schema)
    profile["ingestion_diagnostics"] = parse_diagnostics
    if parse_diagnostics:
        notes.append(f"Detected {sum(x['count'] for x in parse_diagnostics):,} value(s) that could not be parsed into their inferred data types; see the data-quality diagnostics.")
    return Ingested(frame, schema, profile, notes)
