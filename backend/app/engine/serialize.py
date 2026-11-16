"""Make pandas / numpy values safe for JSON (NaN, inf, Timestamps, numpy scalars)."""
from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np
import pandas as pd


def to_jsonable(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    return str(value) if not isinstance(value, str) else value
