"""Safe file loading: CSV / TSV / XLSX bytes -> a raw all-text DataFrame.

Everything is read as text on purpose. Type detection happens later in one place
(`inference.py`), so CSV and Excel files follow exactly the same path.
"""
from __future__ import annotations

import csv
import io
import zipfile

import pandas as pd

from .errors import DataError

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".xlsx"}
MAX_UNCOMPRESSED_XLSX = 100 * 1024 * 1024  # zip-bomb guard


def _extension(filename: str) -> str:
    name = (filename or "").lower().strip()
    return name[name.rfind("."):] if "." in name else ""


def _decode(content: bytes) -> str:
    # utf-8-sig strips the BOM Excel adds; cp1252 covers most legacy exports; latin-1 never fails.
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")


def _sniff_delimiter(text: str, extension: str) -> str:
    if extension == ".tsv":
        return "\t"
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def load_upload(
    filename: str,
    content: bytes,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    max_rows: int = 200_000,
    max_cols: int = 200,
    sheet_name: str | None = None,
) -> pd.DataFrame:
    """Validate and parse an uploaded file. Raises DataError with a user-friendly message."""
    ext = _extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise DataError("Unsupported file type. Upload a .csv, .tsv or .xlsx file.", 415)
    if not content:
        raise DataError("The file is empty.")
    if len(content) > max_bytes:
        raise DataError(f"File is too large (limit {max_bytes // (1024 * 1024)} MB).", 413)

    try:
        if ext == ".xlsx":
            df = _read_xlsx(content, max_rows, sheet_name=sheet_name)
        else:
            text = _decode(content)
            if not text.strip():
                raise DataError("The file is empty.")
            sep = _sniff_delimiter(text, ext)
            df = pd.read_csv(
                io.StringIO(text),
                sep=sep,
                dtype=str,
                keep_default_na=False,
                nrows=max_rows + 1,
                skip_blank_lines=True,
                engine="python" if len(sep) > 1 else "c",
            )
    except DataError:
        raise
    except pd.errors.EmptyDataError:
        raise DataError("The file has no data.")
    except Exception as exc:  # parser errors, corrupt workbooks, ...
        raise DataError(f"Could not read the file: {type(exc).__name__}") from exc

    if len(df) > max_rows:
        raise DataError(f"Too many rows (limit {max_rows:,}).", 413)
    if df.shape[1] > max_cols:
        raise DataError(f"Too many columns (limit {max_cols}).", 413)
    if df.shape[1] == 0 or len(df) == 0:
        raise DataError("The file has no data rows.")

    # One text-typed frame, whatever the source format.
    return df.astype("string")


def workbook_sheet_names(content: bytes) -> list[str]:
    """Return worksheet names after validating the XLSX container and expansion size."""
    if not content.startswith(b"PK"):
        raise DataError("This does not look like a valid .xlsx file.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            if sum(i.file_size for i in zf.infolist()) > MAX_UNCOMPRESSED_XLSX:
                raise DataError("Workbook is too large once unpacked.", 413)
        book = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
        return list(book.sheet_names)
    except DataError:
        raise
    except Exception as exc:
        raise DataError("Could not inspect this Excel workbook. Ensure it is a valid .xlsx file.") from exc


def _read_xlsx(content: bytes, max_rows: int, sheet_name: str | None = None) -> pd.DataFrame:
    if not content.startswith(b"PK"):
        raise DataError("This does not look like a valid .xlsx file.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            if sum(i.file_size for i in zf.infolist()) > MAX_UNCOMPRESSED_XLSX:
                raise DataError("Workbook is too large once unpacked.", 413)
    except zipfile.BadZipFile:
        raise DataError("This does not look like a valid .xlsx file.")
    sheets = workbook_sheet_names(content)
    selected = sheet_name if sheet_name is not None else (sheets[0] if sheets else None)
    if selected not in sheets:
        raise DataError("The selected worksheet does not exist in this workbook.", 422)
    df = pd.read_excel(io.BytesIO(content), engine="openpyxl", sheet_name=selected, dtype=object, nrows=max_rows + 1)
    return df
