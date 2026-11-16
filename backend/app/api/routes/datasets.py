import copy
import io
import json
import re
from datetime import UTC

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    current_user,
    get_db,
    get_settings_dep,
    get_store,
    owned_dataset,
)
from app.core.config import Settings
from app.db.models import AnalysisReport, Dashboard, Dataset, DatasetHistory, User
from app.engine.errors import DataError
from app.engine.inference import analyze_frame

from app.engine.loader import workbook_sheet_names
from app.engine.outliers import find_outliers
from app.engine.pipeline import ingest
from app.engine.profile import profile_frame
from app.engine.query import build_chart, table_page
from app.engine.recommend import recommend_charts
from app.engine.serialize import to_jsonable
from app.schemas import (
    AutoBuildRequest,
    ChartRequest,
    CleanRequest,
    DatasetRename,
    RowsRequest,
)
from app.services.dashboards import validate_widgets
from app.services.dataset_store import DatasetStore

router = APIRouter(prefix="/datasets", tags=["datasets"])

# Bounded process-local cache for read-only analysis results.
# Committed cleaning operations create a new stored_name, invalidating old entries.
_ANALYSIS_CACHE: dict[tuple, dict] = {}
_ANALYSIS_CACHE_LIMIT = 8


def summary(ds: Dataset) -> dict:
    return {
        "id": ds.id, "name": ds.name, "original_filename": ds.original_filename,
        "rows": ds.n_rows, "columns": ds.n_cols, "created_at": ds.created_at.isoformat(),
    }


def detail(ds: Dataset) -> dict:
    return {**summary(ds), "schema": ds.schema_json, "profile": ds.profile_json, "notes": ds.notes_json or []}


@router.post("", status_code=201)
def upload(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    store: DatasetStore = Depends(get_store),
):
    count = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.owner_id == user.id))
    if count >= settings.max_datasets_per_user:
        raise HTTPException(409, f"You can keep at most {settings.max_datasets_per_user} datasets. Delete one first.")

    limit = settings.max_upload_mb * 1024 * 1024
    content = file.file.read(limit + 1)          # never read more than limit + 1 bytes
    if len(content) > limit:
        raise HTTPException(413, f"File is too large (limit {settings.max_upload_mb} MB).")

    filename = (file.filename or "upload").strip()[:255]
    result = ingest(filename, content, max_bytes=limit, max_rows=settings.max_rows, max_cols=settings.max_cols)

    stored = store.save(result.frame)
    ds = Dataset(
        owner_id=user.id,
        name=(name or filename.rsplit(".", 1)[0] or "Dataset").strip()[:150],
        original_filename=filename,
        stored_name=stored,
        n_rows=len(result.frame),
        n_cols=result.frame.shape[1],
        schema_json=result.schema,
        profile_json=result.profile,
        notes_json=result.notes,
    )
    try:
        db.add(ds)
        db.commit()
    except Exception:
        db.rollback()
        store.delete(ds)                         # don't leave orphan files behind
        raise
    return detail(ds)


@router.post("/workbook/sheets")
def inspect_workbook(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings_dep),
):
    """Inspect worksheet names without creating a dataset or modifying the workbook."""
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(415, "Worksheet selection is available for .xlsx workbooks.")
    content = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File is too large (limit {settings.max_upload_mb} MB).")
    try:
        names = workbook_sheet_names(content)
    except DataError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    if not names:
        raise HTTPException(400, "This workbook contains no worksheets.")
    return {"filename": filename, "sheets": [{"name": name} for name in names]}


@router.post("/workbook/import", status_code=201)
def import_workbook_sheets(
    file: UploadFile = File(...),
    sheet_names: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    store: DatasetStore = Depends(get_store),
):
    """Import selected workbook worksheets as independent datasets in one transaction."""
    filename = (file.filename or "workbook.xlsx").strip()[:255]
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(415, "This endpoint accepts .xlsx workbooks only.")
    limit = settings.max_upload_mb * 1024 * 1024
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, f"File is too large (limit {settings.max_upload_mb} MB).")
    try:
        requested = json.loads(sheet_names)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "sheet_names must be a JSON array of worksheet names.") from exc
    if not isinstance(requested, list) or not requested or any(not isinstance(x, str) for x in requested):
        raise HTTPException(422, "Select at least one valid worksheet.")
    if len(requested) != len(set(requested)):
        raise HTTPException(422, "A worksheet can only be selected once.")
    try:
        available = workbook_sheet_names(content)
        if any(name not in available for name in requested):
            raise HTTPException(422, "One or more selected worksheets are not in this workbook.")
        count = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.owner_id == user.id)) or 0
        if count + len(requested) > settings.max_datasets_per_user:
            raise HTTPException(409, f"Importing {len(requested)} worksheets would exceed your dataset limit ({settings.max_datasets_per_user}). Delete a dataset or select fewer worksheets.")
        created, stored_names = [], []
        try:
            for sheet in requested:
                result = ingest(filename, content, max_bytes=limit, max_rows=settings.max_rows, max_cols=settings.max_cols, sheet_name=sheet)
                stored = store.save(result.frame)
                stored_names.append(stored)
                base = filename.rsplit(".", 1)[0]
                ds = Dataset(owner_id=user.id, name=f"{base} — {sheet}".strip()[:150],
                    original_filename=filename, stored_name=stored, n_rows=len(result.frame),
                    n_cols=result.frame.shape[1], schema_json=result.schema, profile_json=result.profile, notes_json=result.notes)
                db.add(ds)
                created.append(ds)
            db.commit()
        except Exception:
            db.rollback()
            for stored in stored_names:
                store.delete_file(stored)
            raise
        return {"datasets": [detail(ds) for ds in created]}
    except DataError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("")
def list_datasets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Dataset).where(Dataset.owner_id == user.id).order_by(Dataset.id.desc())).all()
    return {"datasets": [summary(d) for d in rows]}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return detail(owned_dataset(db, user, dataset_id))


@router.patch("/{dataset_id}")
def rename(dataset_id: int, body: DatasetRename, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ds = owned_dataset(db, user, dataset_id)
    ds.name = body.name.strip()
    db.commit()
    return summary(ds)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    ds = owned_dataset(db, user, dataset_id)
    history = db.scalars(select(DatasetHistory).where(DatasetHistory.dataset_id == ds.id)).all()
    historical_names = [item.stored_name for item in history]
    db.delete(ds)                                # dashboards and history rows are deleted too
    db.commit()
    store.delete(ds)
    for stored_name in historical_names: store.delete_file(stored_name)


@router.get("/{dataset_id}/suggestions")
def suggestions(
    dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db), store: DatasetStore = Depends(get_store)
):
    ds = owned_dataset(db, user, dataset_id)
    frame = store.load(ds)
    schema = ds.schema_json
    return {"suggestions": recommend_charts(frame, schema)}


@router.post("/{dataset_id}/chart")
def chart(
    dataset_id: int,
    body: ChartRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    ds = owned_dataset(db, user, dataset_id)
    frame = store.load(ds)
    schema = ds.schema_json
    return build_chart(frame, schema, body.spec.clean(), [f.model_dump() for f in body.filters])


@router.post("/{dataset_id}/rows")
def rows(
    dataset_id: int,
    body: RowsRequest | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort_by: str | None = Query(None, max_length=200),
    descending: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    ds = owned_dataset(db, user, dataset_id)
    frame = store.load(ds)
    schema = ds.schema_json
    return table_page(
        frame, schema, page=page, page_size=page_size, sort_by=sort_by,
        descending=descending, filters=[f.model_dump() for f in (body.filters if body else [])],
    )


@router.get("/{dataset_id}/values")
def distinct_values(
    dataset_id: int,
    column: str = Query(..., max_length=200),
    limit: int = Query(100, ge=1, le=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    import pandas as pd
    ds = owned_dataset(db, user, dataset_id)
    if column not in {c["name"] for c in ds.schema_json}:
        raise HTTPException(422, "Unknown column")
    series = store.load(ds)[column].dropna()
    kind = next((c.get("kind") for c in ds.schema_json if c.get("name") == column), None)
    grain = "month"
    if kind == "datetime":
        parsed = pd.to_datetime(series, errors="coerce").dropna()
        values = parsed.dt.to_period("M").astype(str).value_counts().head(limit)
    else:
        grain = "value"
        values = series.astype(str).value_counts().head(limit)
    return {"column": column, "grain": grain, "values": [{"value": v, "count": int(n)} for v, n in values.items()]}


@router.post("/{dataset_id}/combine", status_code=201)
def combine_datasets(
    dataset_id: int,
    body: dict,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    store: DatasetStore = Depends(get_store),
):
    """Create a new derived dataset by appending or joining two owned datasets; sources stay untouched."""
    import pandas as pd
    source = owned_dataset(db, user, dataset_id)
    other_id = body.get("other_dataset_id")
    try:
        other_id = int(other_id)
    except (TypeError, ValueError):
        raise HTTPException(422, "Choose a valid second dataset")
    other = owned_dataset(db, user, other_id)
    if source.id == other.id:
        raise HTTPException(422, "Choose a different dataset")
    mode = body.get("mode")
    left, right = store.load(source), store.load(other)
    if mode == "append":
        if set(left.columns) != set(right.columns):
            raise HTTPException(422, "Append requires the same column names in both datasets")
        result = pd.concat([left, right[list(left.columns)]], ignore_index=True)
        label = "Append"
    elif mode == "join":
        left_key, right_key = body.get("left_key"), body.get("right_key")
        join_type = body.get("join_type", "left")
        if left_key not in left.columns or right_key not in right.columns:
            raise HTTPException(422, "Select valid join keys from both datasets")
        if join_type not in {"left", "inner", "right", "outer"}:
            raise HTTPException(422, "Unsupported join type")
        if left[left_key].isna().any() or right[right_key].isna().any():
            # pandas null-key joins can create surprising matches; preserve rows but make the choice explicit.
            raise HTTPException(422, "Join keys contain missing values. Resolve or filter them before joining.")
        left_counts = left[left_key].value_counts(dropna=True)
        right_counts = right[right_key].value_counts(dropna=True)
        shared = left_counts.index.intersection(right_counts.index)
        inner_rows = sum(int(left_counts[k]) * int(right_counts[k]) for k in shared)
        left_only = sum(int(v) for k, v in left_counts.items() if k not in right_counts.index)
        right_only = sum(int(v) for k, v in right_counts.items() if k not in left_counts.index)
        estimate = inner_rows + (left_only if join_type in {"left", "outer"} else 0) + (right_only if join_type in {"right", "outer"} else 0)
        if estimate > settings.max_rows:
            raise HTTPException(413, f"Join is estimated to produce {estimate:,} rows, above the {settings.max_rows:,}-row limit")
        try:
            result = left.merge(right, left_on=left_key, right_on=right_key, how=join_type, suffixes=("_left", "_right"), validate="many_to_many")
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, f"The selected join keys are incompatible: {exc}") from exc
        label = f"{join_type.title()} join"
    else:
        raise HTTPException(422, "Mode must be append or join")
    if len(result) > settings.max_rows:
        raise HTTPException(413, f"Combined dataset exceeds the {settings.max_rows:,}-row limit")
    count = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.owner_id == user.id))
    if count >= settings.max_datasets_per_user:
        raise HTTPException(409, f"You can keep at most {settings.max_datasets_per_user} datasets. Delete one first.")
    typed, schema = analyze_frame(result)
    profile = profile_frame(typed, schema)
    stored = store.save(typed)
    derived = Dataset(owner_id=user.id, name=f"{source.name} + {other.name}", original_filename=f"{label}: {source.original_filename} + {other.original_filename}", stored_name=stored, n_rows=len(typed), n_cols=typed.shape[1], schema_json=schema, profile_json=profile, notes_json=[f"Derived using {label} from datasets {source.id} and {other.id}.", "Source datasets were not modified."])
    try:
        db.add(derived); db.commit(); db.refresh(derived)
    except Exception:
        db.rollback(); store.delete_file(stored); raise
    return detail(derived)


@router.get("/{dataset_id}/outliers")
def outliers(
    dataset_id: int,
    column: str = Query(..., max_length=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    ds = owned_dataset(db, user, dataset_id)
    return find_outliers(store.load(ds), ds.schema_json, column)



@router.get("/{dataset_id}/analysis")
def analyst_analysis(
    dataset_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    """Return reproducible, descriptive analyst findings grounded in the uploaded data."""
    import pandas as pd

    ds = owned_dataset(db, user, dataset_id)
    cache_key = (ds.id, ds.name, ds.stored_name, repr((ds.profile_json or {}).get("ingestion_diagnostics", [])))
    cached = _ANALYSIS_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)
    frame = store.load(ds)
    schema = ds.schema_json
    profile = ds.profile_json or {}
    numeric_cols = [c["name"] for c in schema if c.get("kind") == "numeric"]
    date_cols = [c["name"] for c in schema if c.get("kind") == "datetime"]
    def _identifier_column(name):
        compact = re.sub(r"[^a-z0-9]+", "", name.lower())
        return bool(re.search(r"(^|[^a-z])(id|uuid|guid|key|code|index|serial)([^a-z]|$)", name, re.I)) or compact.endswith(("customerid", "userid", "accountid", "transactionid", "orderid")) or compact in {"id", "uuid", "guid", "index"}
    category_cols = [c["name"] for c in schema if c.get("kind") in {"categorical", "boolean", "text"}
                     and not _identifier_column(c["name"]) and 2 <= frame[c["name"]].nunique(dropna=True) <= 30]
    analysis_numeric_cols = [c for c in numeric_cols if not _identifier_column(c) and frame[c].nunique(dropna=True) > 2]

    numeric_summary = []
    for name in numeric_cols[:20]:
        values = pd.to_numeric(frame[name], errors="coerce").dropna()
        if values.empty:
            continue
        numeric_summary.append({
            "column": name,
            "count": int(values.count()),
            "missing": int(frame[name].isna().sum()),
            "sum": float(values.sum()),
            "mean": float(values.mean()),
            "median": float(values.median()),
            "min": float(values.min()),
            "max": float(values.max()),
            "std": float(values.std()) if len(values) > 1 else 0.0,
            "q1": float(values.quantile(.25)),
            "q3": float(values.quantile(.75)),
            "negative_count": int((values < 0).sum()),
            "zero_count": int((values == 0).sum()),
            "skew": float(values.skew()) if len(values) > 2 and pd.notna(values.skew()) else 0.0,
        })

    category_summary = []
    for name in category_cols[:20]:
        counts = frame[name].astype("string").fillna("(Missing)").value_counts().head(8)
        category_summary.append({
            "column": name,
            "unique": int(frame[name].nunique(dropna=True)),
            "top_values": [{"value": str(k), "count": int(v), "share_pct": round(100 * int(v) / max(len(frame), 1), 1)} for k, v in counts.items()],
        })

    correlations = []
    corr_cols = analysis_numeric_cols[:12]
    if len(corr_cols) >= 2:
        corr = frame[corr_cols].corr(numeric_only=True)
        for i, left in enumerate(corr_cols):
            for right in corr_cols[i + 1:]:
                value = corr.loc[left, right]
                if pd.notna(value):
                    correlations.append({"left": left, "right": right, "correlation": round(float(value), 3)})
    correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)

    # Include low-cardinality numeric flags (for example SeniorCitizen 0/1) as
    # dimensions, but never as additive measures.
    binary_numeric_cols = [
        c for c in numeric_cols
        if not _identifier_column(c) and frame[c].nunique(dropna=True) == 2
    ]
    segment_dimension_cols = list(dict.fromkeys(category_cols + binary_numeric_cols))
    # Segment comparisons report both total and average to avoid volume bias.
    segment_analysis = []
    for category in segment_dimension_cols[:8]:
        top_groups = frame[category].astype("string").fillna("(Missing)").value_counts().head(8).index.tolist()
        subset = frame[frame[category].astype("string").fillna("(Missing)").isin(top_groups)]
        for measure in analysis_numeric_cols[:3]:
            grouped = subset.assign(_segment=subset[category].astype("string").fillna("(Missing)")).groupby("_segment", dropna=False)[measure].agg(["count", "sum", "mean"]).reset_index()
            segment_analysis.append({"category": category, "measure": measure, "groups": [{"value": str(r["_segment"]), "count": int(r["count"]), "sum": float(r["sum"]) if pd.notna(r["sum"]) else 0.0, "mean": float(r["mean"]) if pd.notna(r["mean"]) else None} for _, r in grouped.iterrows()]})

    time_series = []
    if date_cols and analysis_numeric_cols:
        date_name = date_cols[0]
        dated = frame[[date_name] + analysis_numeric_cols[:3]].copy()
        dated[date_name] = pd.to_datetime(dated[date_name], errors="coerce")
        dated = dated.dropna(subset=[date_name])
        if not dated.empty:
            dated["_period"] = dated[date_name].dt.to_period("M").astype(str)
            for measure in analysis_numeric_cols[:3]:
                grouped = dated.groupby("_period")[measure].agg(["count", "sum", "mean"]).tail(36).reset_index()
                time_series.append({"date_column": date_name, "measure": measure, "periods": [{"period": str(r["_period"]), "count": int(r["count"]), "sum": float(r["sum"]) if pd.notna(r["sum"]) else 0.0, "mean": float(r["mean"]) if pd.notna(r["mean"]) else None} for _, r in grouped.iterrows()]})

    rows = len(frame)
    cells = rows * len(schema)
    # Count true nulls plus whitespace-only strings so the quality report matches what an analyst sees.
    missing_masks = {}
    missing_by_column = []
    parse_error_columns = {item.get("column") for item in (profile.get("ingestion_diagnostics", []) or [])}
    for col in schema:
        name = col["name"]
        series = frame[name]
        mask = series.isna()
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            mask = mask | series.astype("string").str.strip().eq("").fillna(False)
        missing_masks[name] = mask
        count = int(mask.sum())
        if count:
            kind = col.get("kind", "text")
            if kind == "numeric" and re.search(r"(^|_)(rating|score|satisfaction|nps)(_|$)", name, re.IGNORECASE):
                strategy, method = "review", "This looks like an ordinal feedback score. Keep missing values as 'not rated' for descriptive reporting and calculate averages on rated records only. If a modelling workflow requires imputation, use the median only with a missingness indicator and compare results before and after."
            elif kind == "numeric":
                strategy, method = "median", "Fill with the median after checking whether the missingness is random; median is less sensitive to skew and extreme values. Compare results before and after imputation."
            elif kind in {"categorical", "boolean", "text"}:
                strategy, method = "mode", "Use the most frequent category only if the field has a clear dominant value; otherwise use an explicit Unknown / Not recorded label."
            elif kind == "id":
                strategy, method = "review", "Do not invent identifiers. Recover from the source system or keep the record flagged as missing."
            elif kind == "datetime":
                strategy, method = "review", "Do not use mean or mode dates by default. Recover from the source, derive from a trusted field, or leave missing with a documented reason."
            else:
                strategy, method = "review", "Inspect the field meaning and source before choosing a treatment."
            if name in parse_error_columns:
                strategy, method = "review", "Some non-empty source values failed type conversion. Inspect the original examples and correct the source format or explicitly replace only confirmed invalid entries; do not impute these parse failures automatically."
            pct = round(100 * count / rows, 1) if rows else 0.0
            missing_by_column.append({
                "column": name, "kind": kind, "missing": count, "pct": pct,
                "sample_rows": [int(i) + 1 for i in frame.index[mask][:12].tolist()],
                "suggested_strategy": strategy, "suggestion": method,
                "recommended_operation": ({"type": "fill_missing", "column": name, "strategy": strategy} if strategy in {"median", "mode"} and pct < 40 else None),
            })
    missing = sum(item["missing"] for item in missing_by_column)
    duplicates = int(frame.duplicated().sum())
    # Preserve precision for small but real missingness; one-decimal rounding can hide it as 0.0%.
    missing_pct = (100 * missing / cells) if cells else 0.0
    duplicate_pct = round(100 * duplicates / rows, 1) if rows else 0.0

    quality_issues = []
    for item in missing_by_column:
        severity = "high" if item["pct"] >= 20 else "medium" if item["pct"] >= 5 else "low"
        quality_issues.append({"id": f"missing-{item['column']}", "type": "missing", "severity": severity, "title": f"{item['missing']:,} missing values in {item['column']}", "column": item["column"], "count": item["missing"], "pct": item["pct"], "sample_rows": item["sample_rows"], "suggestion": item["suggestion"], "recommended_operation": item["recommended_operation"]})
    if duplicates:
        quality_issues.append({"id": "duplicate-rows", "type": "duplicates", "severity": "medium", "title": f"{duplicates:,} exact duplicate rows", "count": duplicates, "pct": duplicate_pct, "suggestion": "Inspect duplicate records and confirm the true business key before removing them. Exact duplicates are not always invalid repeated events.", "recommended_operation": {"type": "drop_duplicates"}})
    # Upload-time parse failures are retained in the profile because coercion to a typed
    # analytical column can otherwise look indistinguishable from an originally blank cell.
    parse_diagnostics = profile.get("ingestion_diagnostics", []) or []
    for item in parse_diagnostics:
        quality_issues.append({
            "id": f"parse-{item['column']}", "type": "parse_errors", "severity": "high",
            "title": f"{item['count']:,} values could not be parsed in {item['column']}",
            "column": item["column"], "count": item["count"],
            "sample_rows": [sample["row"] for sample in item.get("sample_values", [])],
            "sample_values": item.get("sample_values", []),
            "suggestion": item.get("recommendation", "Review source values before changing them."),
        })

    for col in schema:
        name = col["name"]
        unique = int(frame[name].nunique(dropna=True))
        if rows and unique <= 1 and int(missing_masks[name].sum()) < rows:
            quality_issues.append({"id": f"constant-{name}", "type": "constant", "severity": "low", "title": f"{name} has only {unique} distinct non-empty value", "column": name, "count": unique, "suggestion": "Confirm whether this field is useful for analysis. A constant field cannot explain differences between records; retain it if it is an important identifier or audit attribute."})
    for stat in numeric_summary:
        if stat["count"] >= 4:
            values = pd.to_numeric(frame[stat["column"]], errors="coerce").dropna()
            q1, q3 = values.quantile(.25), values.quantile(.75)
            flagged = int(((values < q1 - 1.5 * (q3-q1)) | (values > q3 + 1.5 * (q3-q1))).sum())
            if flagged:
                quality_issues.append({"id": f"outlier-{stat['column']}", "type": "outliers", "severity": "medium", "title": f"{flagged:,} potential outliers in {stat['column']}", "column": stat["column"], "count": flagged, "suggestion": "Inspect the extreme records. They may be valid high-value events; investigate before removing, capping or winsorising them."})

    findings = []
    recommendations = []
    for item in parse_diagnostics:
        samples = ", ".join(f"row {sample['row']}: {sample['value']}" for sample in item.get("sample_values", [])[:4])
        findings.append({
            "id": f"parse-{item['column']}",
            "title": f"Type conversion needs review in {item['column']}",
            "evidence": f"{item['count']:,} non-empty source value(s) could not be parsed as {item['detected_type']}. {samples}",
            "interpretation": "These values are distinct from genuinely blank cells. Review the original format or locale before correcting them; automatic imputation could hide source-data errors.",
            "severity": "high",
        })
        recommendations.append({
            "id": f"parse-review-{item['column']}",
            "title": f"Resolve parsing exceptions in {item['column']}",
            "action": item.get("recommendation", "Inspect source values and correct only confirmed invalid entries."),
            "priority": "high",
        })
    if missing:
        worst = sorted(
            [{"column": c["name"], "missing": int(frame[c["name"]].isna().sum()), "pct": round(100 * float(frame[c["name"]].isna().mean()), 1)} for c in schema],
            key=lambda x: x["missing"], reverse=True,
        )[:3]
        findings.append({"id": "missing", "title": "Missing data needs review", "evidence": f"{missing:,} of {cells:,} cells are empty ({missing_pct}%). Most affected: " + ", ".join(f"{x['column']} ({x['pct']}%)" for x in worst if x["missing"]), "interpretation": "Missingness can change averages, totals and group comparisons. The pattern matters as much as the overall percentage.", "severity": "high" if missing_pct >= 10 else "medium"})
        recommendations.append({"id": "missing-review", "title": "Investigate missingness by field", "action": "Check whether blanks mean not recorded, not applicable or zero. Fill only when a defensible rule exists; otherwise preserve an explicit Unknown category or exclude with a documented reason.", "priority": "high"})
    else:
        findings.append({"id": "complete", "title": "No empty cells detected", "evidence": "The current dataset has no null or empty cells in the inferred dataframe.", "interpretation": "Completeness is strong for this snapshot, but it does not guarantee accuracy or consistency.", "severity": "positive"})
    if duplicates:
        findings.append({"id": "duplicates", "title": "Potential duplicate records found", "evidence": f"{duplicates:,} exact duplicate rows ({duplicate_pct}% of records).", "interpretation": "Duplicates can inflate counts and additive measures. Confirm whether repeated rows represent accidental duplication or valid repeated events.", "severity": "medium"})
        recommendations.append({"id": "duplicate-check", "title": "Validate duplicate business keys", "action": "Identify the true record key (for example order ID + line item) before removing rows. Exact-row duplicates are a useful signal, not proof of invalid records.", "priority": "high"})
    if len(frame) < 30:
        findings.append({"id": "small-sample", "title": "Small dataset: interpret patterns cautiously", "evidence": f"Only {rows:,} records are available.", "interpretation": "Small samples can make segment rankings and correlations unstable.", "severity": "medium"})
        recommendations.append({"id": "sample-size", "title": "Validate with a larger time window", "action": "If possible, add more periods or records and compare whether the same patterns persist before making operational decisions.", "priority": "medium"})

    for stat in numeric_summary:
        if stat["negative_count"]:
            findings.append({"id": f"negative-{stat['column']}", "title": f"Negative values in {stat['column']}", "evidence": f"{stat['negative_count']:,} negative value(s); range {stat['min']:,.3g} to {stat['max']:,.3g}.", "interpretation": "Negative values may be valid (refunds, credits, losses) or may indicate sign or parsing issues. Their meaning depends on the measure.", "severity": "medium"})
            recommendations.append({"id": f"negative-check-{stat['column']}", "title": f"Review negative {stat['column']} values", "action": "Inspect the underlying records and business definition. Do not convert negatives to positive values without a documented rule.", "priority": "medium"})

    for item in correlations[:3]:
        if abs(item["correlation"]) >= 0.65:
            direction = "positive" if item["correlation"] > 0 else "negative"
            findings.append({"id": f"corr-{item['left']}-{item['right']}", "title": f"Strong {direction} association detected", "evidence": f"{item['left']} and {item['right']} have Pearson correlation r = {item['correlation']:+.2f}.", "interpretation": "This is an association, not evidence that one variable causes the other. Check segment effects, time trends and outliers.", "severity": "info"})
    if date_cols and numeric_summary:
        findings.append({"id": "time-analysis", "title": "Time-based analysis is available", "evidence": f"Detected date field(s): {', '.join(date_cols[:3])}.", "interpretation": "Trend and period-over-period views can reveal seasonality, growth or unusual changes when date coverage is sufficiently complete.", "severity": "info"})
        recommendations.append({"id": "trend-review", "title": "Build a time trend", "action": f"Aggregate a key measure by month using {date_cols[0]}. Compare absolute values and percentage changes, and annotate unusual periods.", "priority": "high"})
    if category_summary and numeric_summary:
        recommendations.append({"id": "segment-review", "title": "Compare performance by segment", "action": f"Break a meaningful measure such as {numeric_summary[0]['column']} down by a business category. Compare both total and average so large groups do not automatically dominate.", "priority": "high"})
    if not recommendations:
        recommendations.append({"id": "validate-definitions", "title": "Confirm metric definitions", "action": "Document what each row represents, the grain of the dataset, the definition of key measures and the reporting period before sharing conclusions.", "priority": "medium"})

    questions = [
        "What does one row represent, and what is the correct unit of analysis?",
        "Which metric best represents the business outcome we want to improve?",
        "Which segments contribute most, and which underperform after normalising for volume?",
        "How does the primary metric change over time, and are there unusual periods?",
        "Which records or assumptions could materially change the conclusion?",
    ]
    if date_cols:
        questions.insert(3, f"Are there monthly or quarterly patterns in {date_cols[0]}?")

    # Rank usable numeric measures without assuming the dataset belongs to a particular industry.
    metric_candidates = []
    for position, stat in enumerate(numeric_summary):
        name = stat["column"].lower().replace("-", "_").replace(" ", "_")
        if re.search(r"(^id$|_id$|^id_|uuid|guid|(^|_)code($|_))", name, re.I):
            continue
        rate_like = bool(re.search(r"rate|ratio|percent|pct|margin|score|rating|price|average|avg|duration", name, re.I))
        outcome_like = bool(re.search(r"revenue|sales|turnover|gmv|income|profit|earnings|premium|claim|cost|expense|spend|amount|value", name, re.I))
        volume_like = bool(re.search(r"qty|quantity|units|orders|transactions|visits|clicks|views|volume", name, re.I))
        metric_candidates.append({**stat, "suggested_aggregation": "sum" if (outcome_like or volume_like) and not rate_like else "mean", "semantic_score": (5 if outcome_like else 0) + (4 if volume_like else 0) + (3 if rate_like else 0), "position": position})
    metric_candidates.sort(key=lambda item: (-item["semantic_score"], item["position"]))
    for item in metric_candidates:
        item.pop("position", None)

    from app.engine.insights import build_analyst_insights

    insight_result = build_analyst_insights(
        frame=frame,
        schema=schema,
        numeric_summary=numeric_summary,
        category_summary=category_summary,
        segment_analysis=segment_analysis,
        time_series=time_series,
        correlations=correlations,
        rows=rows,
    )
    business_insights = insight_result["business_insights"]
    # Keep concrete data-quality actions, but replace generic template advice with
    # recommendations tied to evidence from the analyst insight engine.
    # Data-quality remediation belongs to Prepare, not the business story.
    # Executive recommendations come only from business performance analysis.
    recommendations = insight_result["recommendations"]
    metric_candidates = insight_result["metric_candidates"]
    suggested_visuals = insight_result["suggested_visuals"]
    for visual in suggested_visuals:
        # Curated insight visuals are pre-aggregated with the exact mean/rate
        # semantics and sample counts used by their corresponding findings.
        if visual.get("data") is not None:
            continue
        try:
            visual["data"] = build_chart(frame, schema, visual["spec"])
        except DataError:
            visual["data"] = None
    kpis = insight_result["kpis"]
    result = {
        "dataset": {"id": ds.id, "name": ds.name, "rows": rows, "columns": len(schema), "missing_cells": missing, "missing_pct": round(missing_pct, 6), "duplicate_rows": duplicates, "duplicate_pct": round(duplicate_pct, 6), "date_columns": date_cols, "numeric_columns": numeric_cols, "categorical_columns": category_cols},
        "data_quality": {"missing_by_column": missing_by_column, "parse_diagnostics": parse_diagnostics, "issues": quality_issues, "issue_count": len(quality_issues), "rows_scanned": rows, "cells_scanned": cells},
        "numeric_summary": numeric_summary,
        "metric_candidates": metric_candidates,
        "kpis": kpis,
        "suggested_visuals": suggested_visuals,
        "business_insights": business_insights,
        "category_summary": category_summary,
        "segment_analysis": segment_analysis,
        "time_series": time_series,
        "correlations": correlations[:15],
        "findings": findings,
        "recommendations": recommendations,
        "analyst_questions": questions,
        "method_notes": ["Findings are descriptive and calculated from the current dataset snapshot.", "Pearson correlation measures linear association; it does not establish causation.", "Potential duplicates are exact full-row duplicates. Validate business keys before removal.", "Outlier and missing-value treatment should be justified and documented before publication."],
    }
    if len(_ANALYSIS_CACHE) >= _ANALYSIS_CACHE_LIMIT:
        _ANALYSIS_CACHE.pop(next(iter(_ANALYSIS_CACHE)))
    _ANALYSIS_CACHE[cache_key] = copy.deepcopy(result)
    return result

_CLEAN_OPS = {"trim_text", "fill_missing", "drop_missing_rows", "drop_duplicates", "drop_column", "rename_column", "convert_type", "remove_outliers", "replace_value", "calculated_column"}


def _clean_frame(frame, operations):
    """Apply validated, explicit operations to a copy; never mutate the stored frame in preview mode."""
    import pandas as pd
    from pandas.api.types import is_numeric_dtype

    from app.engine.inference import (
        to_datetime_text,
        to_numeric_text,
    )

    df = frame.copy()
    log = []
    for op in operations:
        kind = op.get("type")
        if kind not in _CLEAN_OPS:
            raise DataError(f"Unsupported cleaning operation: {kind}")
        col = op.get("column")
        if col is not None and col not in df.columns:
            raise DataError(f"Column not found: {col}")
        before_rows, before_cols = len(df), len(df.columns)
        if kind == "trim_text":
            targets = [col] if col else list(df.columns)
            for name in targets:
                if not pd.api.types.is_numeric_dtype(df[name]) and not pd.api.types.is_datetime64_any_dtype(df[name]):
                    df[name] = df[name].astype("string").str.strip().replace("", pd.NA)
        elif kind == "fill_missing":
            if not col: raise DataError("Choose a column to fill")
            strategy = op.get("strategy", "mode")
            s = df[col]
            missing_before = int(s.isna().sum())
            if missing_before == 0:
                raise DataError(f"{col} has no missing values to fill.")
            is_date = pd.api.types.is_datetime64_any_dtype(s)
            is_number = is_numeric_dtype(s)
            is_boolean = pd.api.types.is_bool_dtype(s)

            # Never coerce an arbitrary string (for example, 'Unknown' or '0') into
            # a date/number column. Validate against the inferred field type first.
            if is_date:
                if strategy in {"ffill", "bfill"}:
                    df[col] = s.ffill() if strategy == "ffill" else s.bfill()
                elif strategy == "value":
                    raw_value = op.get("value")
                    parsed = pd.to_datetime(raw_value, errors="coerce")
                    if pd.isna(parsed):
                        raise DataError(f"'{raw_value}' is not a valid date for {col}. Choose a valid date, forward fill, or backward fill.")
                    df[col] = s.fillna(parsed)
                else:
                    raise DataError(f"{col} is a date field. Use Forward fill, Backward fill, or a valid custom date. Do not use a numeric or category fill method.")
            elif is_number:
                if strategy == "mean": value = s.mean()
                elif strategy == "median": value = s.median()
                elif strategy == "mode":
                    modes = s.mode(dropna=True); value = modes.iloc[0] if not modes.empty else None
                elif strategy == "value":
                    value = pd.to_numeric(op.get("value"), errors="coerce")
                    if pd.isna(value):
                        raise DataError(f"Enter a valid numeric replacement for {col}.")
                else:
                    raise DataError(f"{col} is numeric. Choose mean, median, mode, or a valid numeric custom value.")
                if value is None or pd.isna(value):
                    raise DataError(f"Cannot calculate a fill value for {col}; provide a valid custom value.")
                df[col] = s.fillna(value)
            elif is_boolean:
                if strategy == "mode":
                    modes = s.mode(dropna=True); value = modes.iloc[0] if not modes.empty else None
                elif strategy == "value":
                    raw = str(op.get("value", "")).strip().lower()
                    mapping = {"true": True, "yes": True, "1": True, "false": False, "no": False, "0": False}
                    if raw not in mapping:
                        raise DataError(f"Enter true/false (or yes/no) for {col}.")
                    value = mapping[raw]
                else:
                    raise DataError(f"{col} is boolean. Choose mode or a true/false custom value.")
                if value is None or pd.isna(value): raise DataError(f"Cannot calculate a fill value for {col}.")
                df[col] = s.fillna(value)
            else:
                if strategy == "mode":
                    modes = s.mode(dropna=True); value = modes.iloc[0] if not modes.empty else None
                elif strategy == "value":
                    value = op.get("value", "Unknown")
                    if value is None or not str(value).strip():
                        raise DataError(f"Enter a non-empty replacement value for {col}.")
                    value = str(value)
                else:
                    raise DataError(f"{col} is categorical/text. Choose mode or a custom category value.")
                if value is None or pd.isna(value): raise DataError(f"Cannot calculate a fill value for {col}.")
                df[col] = s.fillna(value)
            filled = missing_before - int(df[col].isna().sum())
            log_entry = {"type": kind, "column": col, "rows_removed": 0, "columns_removed": 0,
                         "cells_filled": filled, "missing_before": missing_before,
                         "missing_after": int(df[col].isna().sum()), "strategy": strategy}
            log.append(log_entry)
            continue
        elif kind == "drop_missing_rows":
            subset = [col] if col else None
            df = df.dropna(subset=subset)
        elif kind == "drop_duplicates":
            df = df.drop_duplicates()
        elif kind == "drop_column":
            if not col: raise DataError("Choose a column to remove")
            if len(df.columns) <= 1: raise DataError("A dataset must retain at least one column")
            df = df.drop(columns=[col])
        elif kind == "rename_column":
            new_name = str(op.get("new_name", "")).strip()
            if not col or not new_name: raise DataError("Provide a column and a new name")
            if new_name in df.columns and new_name != col: raise DataError(f"Column already exists: {new_name}")
            df = df.rename(columns={col: new_name})
        elif kind == "convert_type":
            target = op.get("target")
            if not col or target not in {"numeric", "datetime", "text", "boolean"}: raise DataError("Choose a valid target type")
            if target == "numeric": df[col] = to_numeric_text(df[col])
            elif target == "datetime": df[col] = to_datetime_text(df[col])
            elif target == "text": df[col] = df[col].astype("string")
            else:
                low = df[col].astype("string").str.lower().str.strip().map({"true": True, "yes": True, "1": True, "false": False, "no": False, "0": False})
                df[col] = low.astype("boolean")
        elif kind == "remove_outliers":
            if not col or not is_numeric_dtype(df[col]): raise DataError("Outlier removal requires a numeric column")
            s = df[col].dropna()
            if len(s) < 4: raise DataError("At least four numeric values are needed")
            q1, q3 = s.quantile(.25), s.quantile(.75); spread = q3-q1
            factor = float(op.get("factor", 1.5))
            if factor not in (1.5, 3.0): raise DataError("Outlier factor must be 1.5 or 3")
            df = df[df[col].isna() | df[col].between(q1-factor*spread, q3+factor*spread)]
        elif kind == "calculated_column":
            from app.engine.formula import evaluate_formula
            new_name = str(op.get("new_name", "")).strip()
            if not new_name or len(new_name) > 120: raise DataError("Provide a calculated column name (maximum 120 characters)")
            if new_name in df.columns: raise DataError(f"Column already exists: {new_name}")
            try:
                df[new_name] = evaluate_formula(df, op.get("formula", ""))
            except Exception as exc:
                raise DataError(str(exc)) from exc
        elif kind == "replace_value":
            if not col: raise DataError("Choose a column to update")
            old, new = op.get("find"), op.get("replace", "")
            series = df[col]
            if is_numeric_dtype(series):
                old_value = pd.to_numeric(old, errors="coerce")
                new_value = pd.to_numeric(new, errors="coerce") if str(new).strip() else pd.NA
                if pd.isna(old_value): raise DataError(f"Enter a numeric value to find in {col}")
                df[col] = series.replace(old_value, new_value)
            elif pd.api.types.is_datetime64_any_dtype(series):
                old_value = pd.to_datetime(old, errors="coerce")
                new_value = pd.to_datetime(new, errors="coerce") if str(new).strip() else pd.NaT
                if pd.isna(old_value): raise DataError(f"Enter a valid date to find in {col}")
                df[col] = series.replace(old_value, new_value)
            else:
                df[col] = series.replace(old, new if str(new).strip() else pd.NA)
        if len(df) == 0: raise DataError("That operation would remove every row. No changes were applied.")
        log.append({"type": kind, "column": col, "rows_removed": before_rows-len(df), "columns_removed": before_cols-len(df.columns),
                    "cells_filled": 0, "missing_before": None, "missing_after": None})
    return df.reset_index(drop=True), log


@router.post("/{dataset_id}/clean/preview")
def preview_clean(dataset_id: int, body: CleanRequest, user: User = Depends(current_user), db: Session = Depends(get_db), store: DatasetStore = Depends(get_store)):
    ds = owned_dataset(db, user, dataset_id)
    import pandas as pd
    original = store.load(ds)
    cleaned, log = _clean_frame(original, body.operations)
    typed, schema = analyze_frame(cleaned)
    return {"before": {"rows": len(original), "columns": len(original.columns), "missing": int(original.isna().sum().sum()), "duplicates": int(original.duplicated().sum())}, "after": {"rows": len(typed), "columns": len(typed.columns), "missing": int(typed.isna().sum().sum()), "duplicates": int(typed.duplicated().sum())}, "operations": log, "profile": profile_frame(typed, schema), "sample": to_jsonable(typed.head(8).astype(object).where(pd.notna(typed), None).to_dict(orient="records"))}


@router.post("/{dataset_id}/clean/apply")
def apply_clean(dataset_id: int, body: CleanRequest, user: User = Depends(current_user), db: Session = Depends(get_db), store: DatasetStore = Depends(get_store)):
    ds = owned_dataset(db, user, dataset_id)
    original_name = ds.stored_name
    # Keep the previous immutable file as an undo snapshot. A new transformation clears redo.
    redo_entries = db.scalars(select(DatasetHistory).where(DatasetHistory.dataset_id == ds.id, DatasetHistory.stack == "redo")).all()
    cleaned, log = _clean_frame(store.load(ds), body.operations)
    typed, schema = analyze_frame(cleaned)
    new_name = store.save(typed)
    try:
        # Keep saved dashboards aligned with renamed/removed columns and discard only widgets
        # that no longer validate against the cleaned dataset.
        column_map = {op.get("column"): op.get("new_name") for op in body.operations if op.get("type") == "rename_column"}
        removed_columns = {op.get("column") for op in body.operations if op.get("type") == "drop_column"}
        dashboards = db.scalars(select(Dashboard).where(Dashboard.dataset_id == ds.id)).all()
        valid_names = {c["name"] for c in schema}
        removed_widgets = 0
        for dashboard in dashboards:
            def remap_filter(item):
                # Older dashboard records may contain null or malformed filter entries.
                if not isinstance(item, dict):
                    return None
                mapped = dict(item)
                old_column = mapped.get("column")
                mapped["column"] = column_map.get(old_column, old_column)
                return mapped

            dashboard_filters = [
                mapped for item in (dashboard.filters or [])
                if (mapped := remap_filter(item)) is not None
                and mapped.get("column") in valid_names
                and item.get("column") not in removed_columns
            ]
            dashboard.filters = dashboard_filters
            kept = []
            for widget in dashboard.widgets or []:
                # Legacy/partially saved widgets can have spec=None. A bad widget must
                # never abort a dataset-cleaning transaction; discard only that widget.
                if not isinstance(widget, dict):
                    removed_widgets += 1
                    continue
                candidate = dict(widget)
                raw_spec = candidate.get("spec")
                spec = dict(raw_spec) if isinstance(raw_spec, dict) else {}
                for key in ("x", "y", "color_by"):
                    if spec.get(key) in column_map:
                        spec[key] = column_map[spec[key]]
                candidate["spec"] = spec
                raw_filters = candidate.get("filters") or []
                candidate["filters"] = [
                    mapped for item in raw_filters
                    if (mapped := remap_filter(item)) is not None
                    and mapped.get("column") in valid_names
                    and item.get("column") not in removed_columns
                ]
                try:
                    validate_widgets(typed, schema, [candidate], dashboard.filters)
                    kept.append(candidate)
                except (DataError, TypeError, ValueError, AttributeError):
                    removed_widgets += 1
            dashboard.widgets = kept
        db.add(DatasetHistory(dataset_id=ds.id, stack="undo", stored_name=original_name,
            n_rows=ds.n_rows, n_cols=ds.n_cols, schema_json=ds.schema_json,
            profile_json=ds.profile_json, notes_json=ds.notes_json or [],
            label=" + ".join(op.get("type", "Transform").replace("_", " ").title() for op in body.operations[:3])))
        old_undo = db.scalars(select(DatasetHistory).where(DatasetHistory.dataset_id == ds.id, DatasetHistory.stack == "undo").order_by(DatasetHistory.id.desc()).offset(30)).all()
        for entry in old_undo:
            store.delete_file(entry.stored_name)
            db.delete(entry)
        for entry in redo_entries:
            store.delete_file(entry.stored_name)
            db.delete(entry)
        ds.stored_name = new_name
        ds.n_rows, ds.n_cols = len(typed), len(typed.columns)
        ds.schema_json = schema
        updated_profile = profile_frame(typed, schema)
        prior_diagnostics = (ds.profile_json or {}).get("ingestion_diagnostics", [])
        rename_map = {op.get("column"): op.get("new_name") for op in body.operations if op.get("type") == "rename_column"}
        removed_names = {op.get("column") for op in body.operations if op.get("type") == "drop_column"}
        updated_profile["ingestion_diagnostics"] = [
            {**item, "column": rename_map.get(item.get("column"), item.get("column"))}
            for item in prior_diagnostics
            if item.get("column") not in removed_names and rename_map.get(item.get("column"), item.get("column")) in typed.columns
        ]
        ds.profile_json = updated_profile
        note = f"Applied {len(log)} cleaning operation(s)."
        if removed_widgets: note += f" Removed {removed_widgets} dashboard chart(s) that no longer matched the cleaned data."
        ds.notes_json = (ds.notes_json or []) + [note]
        db.commit()
    except Exception:
        db.rollback(); store.delete_file(new_name); raise
    return detail(ds)


@router.get("/{dataset_id}/history")
def dataset_history(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ds = owned_dataset(db, user, dataset_id)
    undo = db.scalars(select(DatasetHistory).where(DatasetHistory.dataset_id == ds.id, DatasetHistory.stack == "undo").order_by(DatasetHistory.id.desc()).limit(30)).all()
    redo = db.scalars(select(DatasetHistory).where(DatasetHistory.dataset_id == ds.id, DatasetHistory.stack == "redo").order_by(DatasetHistory.id.desc()).limit(30)).all()
    return {"undo": [{"id": x.id, "label": x.label, "created_at": x.created_at.isoformat()} for x in undo],
            "redo": [{"id": x.id, "label": x.label, "created_at": x.created_at.isoformat()} for x in redo]}


def _restore_history(dataset_id: int, stack: str, user: User, db: Session, store: DatasetStore):
    ds = owned_dataset(db, user, dataset_id)
    entry = db.scalar(select(DatasetHistory).where(DatasetHistory.dataset_id == ds.id, DatasetHistory.stack == stack).order_by(DatasetHistory.id.desc()).limit(1))
    if not entry:
        raise HTTPException(409, f"Nothing to {stack}.")
    opposite = "redo" if stack == "undo" else "undo"
    db.add(DatasetHistory(dataset_id=ds.id, stack=opposite, stored_name=ds.stored_name,
        n_rows=ds.n_rows, n_cols=ds.n_cols, schema_json=ds.schema_json,
        profile_json=ds.profile_json, notes_json=ds.notes_json or [], label=entry.label))
    ds.stored_name = entry.stored_name
    ds.n_rows, ds.n_cols = entry.n_rows, entry.n_cols
    ds.schema_json, ds.profile_json, ds.notes_json = entry.schema_json, entry.profile_json, entry.notes_json
    db.delete(entry)
    db.commit()
    return {"dataset": detail(ds), "history": dataset_history(dataset_id, user, db)}


@router.post("/{dataset_id}/undo")
def undo_dataset(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db), store: DatasetStore = Depends(get_store)):
    return _restore_history(dataset_id, "undo", user, db, store)


@router.post("/{dataset_id}/redo")
def redo_dataset(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db), store: DatasetStore = Depends(get_store)):
    return _restore_history(dataset_id, "redo", user, db, store)




@router.get("/{dataset_id}/relationships")
def numeric_relationships(
    dataset_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    """Return pairwise Pearson correlations with pairwise-complete sample counts.

    This is descriptive association, not causal evidence. Pairs with fewer than
    three complete observations or zero variance are omitted.
    """
    import itertools
    import math

    import pandas as pd

    ds = owned_dataset(db, user, dataset_id)
    frame = store.load(ds)
    numeric = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    if len(numeric) < 2:
        return {
            "columns": numeric,
            "pairs": [],
            "message": "At least two numeric columns are required.",
            "method": "Pearson correlation; pairwise complete observations",
        }

    pairs = []
    for left, right in itertools.combinations(numeric[:40], 2):
        valid = frame[[left, right]].replace([float("inf"), float("-inf")], pd.NA).dropna()
        n = len(valid)
        if n < 3:
            continue
        if valid[left].nunique(dropna=True) < 2 or valid[right].nunique(dropna=True) < 2:
            continue
        coefficient = valid[left].corr(valid[right], method="pearson")
        if pd.isna(coefficient) or not math.isfinite(float(coefficient)):
            continue
        value = float(coefficient)
        magnitude = abs(value)
        strength = "very strong" if magnitude >= 0.8 else "strong" if magnitude >= 0.6 else "moderate" if magnitude >= 0.4 else "weak"
        pairs.append({
            "x": left,
            "y": right,
            "correlation": round(value, 6),
            "sample_count": n,
            "direction": "positive" if value > 0 else "negative" if value < 0 else "none",
            "strength": strength,
        })
    pairs.sort(key=lambda item: abs(item["correlation"]), reverse=True)
    return {
        "columns": numeric[:40],
        "pairs": pairs[:200],
        "truncated": len(pairs) > 200 or len(numeric) > 40,
        "method": "Pearson correlation; pairwise complete observations",
        "caveat": "Correlation describes linear association, not causation. Results may be affected by outliers, non-linear relationships, mixed populations and measurement choices.",
    }


@router.post("/{dataset_id}/pivot")
def pivot_table(dataset_id: int, body: dict, user: User = Depends(current_user), db: Session = Depends(get_db), store: DatasetStore = Depends(get_store)):
    """Return an aggregated pivot preview without changing the source dataset."""
    import pandas as pd
    ds = owned_dataset(db, user, dataset_id)
    frame = store.load(ds)
    rows = body.get("rows") or []
    columns = body.get("columns") or []
    measure = body.get("measure")
    agg = body.get("aggregation", "sum")
    allowed = {"sum", "mean", "median", "count", "min", "max"}
    if agg not in allowed: raise HTTPException(422, "Unsupported aggregation")
    dimensions = rows + columns
    if not dimensions or len(dimensions) > 4 or any(c not in frame.columns for c in dimensions):
        raise HTTPException(422, "Choose one to four valid row/column dimensions")
    if measure and measure not in frame.columns: raise HTTPException(422, "Choose a valid measure")
    if agg != "count" and (not measure or not pd.api.types.is_numeric_dtype(frame[measure])):
        raise HTTPException(422, "Choose a numeric measure for this aggregation")
    try:
        if not measure:
            work = frame.copy()
            work["__datadash_record_count__"] = 1
            value_field, function = "__datadash_record_count__", "sum"
        else:
            work, value_field, function = frame, measure, agg
        if columns:
            pivot = pd.pivot_table(work, index=rows or None, columns=columns, values=value_field, aggfunc=function, fill_value=0, dropna=False)
            pivot = pivot.reset_index()
            pivot.columns = [" / ".join(str(v) for v in c if str(v) not in ("", "None")) if isinstance(c, tuple) else str(c) for c in pivot.columns]
        else:
            pivot = work.groupby(rows, dropna=False)[value_field].agg(function).reset_index(name=("count_records" if not measure else f"{agg}_{measure}"))
        pivot = pivot.head(500)
        records = pivot.astype(object).where(pd.notna(pivot), None).to_dict(orient="records")
        return {"columns": list(pivot.columns), "rows": to_jsonable(records), "row_count": len(pivot), "truncated": len(pivot) >= 500,
                "configuration": {"rows": rows, "columns": columns, "measure": measure, "aggregation": agg}}
    except Exception as exc:
        raise HTTPException(422, f"Could not build pivot: {exc}") from exc


@router.post("/{dataset_id}/auto-build")
def auto_build_analyst_workspace(
    dataset_id: int,
    body: AutoBuildRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    """Run a conservative, explainable analyst pipeline and publish a multi-page dashboard + report.

    Only reversible-in-history, low-risk text trimming is applied automatically. Missing values,
    duplicates and outliers are diagnosed and reported, never silently imputed or deleted.
    """
    from datetime import datetime

    import pandas as pd

    ds = owned_dataset(db, user, dataset_id)
    original = store.load(ds)
    applied_steps = []
    pending_decisions = []

    # Safe normalization: trim accidental leading/trailing whitespace and convert blank-only
    # strings to nulls. The existing apply_clean path records an undo snapshot.
    if body.apply_safe_text_trim:
        text_cols = [c for c in original.columns if pd.api.types.is_object_dtype(original[c]) or pd.api.types.is_string_dtype(original[c])]
        trim_count = 0
        for col in text_cols:
            raw = original[col].astype("string")
            trim_count += int((raw.notna() & raw.ne(raw.str.strip())).sum())
        if trim_count:
            apply_clean(dataset_id, CleanRequest(operations=[{"type": "trim_text"}]), user, db, store)
            applied_steps.append({
                "step": "Normalize text whitespace", "status": "applied",
                "detail": f"Trimmed leading/trailing whitespace in {trim_count:,} text value(s); whitespace-only values are now treated as missing.",
                "undo_available": True,
            })
        else:
            applied_steps.append({"step": "Normalize text whitespace", "status": "checked", "detail": "No leading/trailing whitespace found in text columns; no changes were needed.", "undo_available": False})

    ds = owned_dataset(db, user, dataset_id)
    analysis = analyst_analysis(dataset_id, user, db, store)
    frame = store.load(ds)
    suggestions_list = recommend_charts(frame, ds.schema_json, limit=12)

    # Generate a varied dashboard, grouped into navigable analytical pages.
    widgets = []
    page_counts = {"Overview": 0, "Trends": 0, "Segments": 0, "Distributions": 0, "Relationships": 0}
    for index, suggestion in enumerate(suggestions_list, start=1):
        spec = suggestion["spec"]
        if spec.get("type") == "line":
            page = "Trends"
        elif spec.get("type") == "scatter":
            page = "Relationships"
        elif spec.get("type") == "histogram":
            page = "Distributions"
        else:
            page = "Segments"
        # Put the two strongest, complementary visuals on the landing page as well.
        if index <= 2:
            page = "Overview"
        candidate = {
            "id": f"auto-{index}", "title": str(suggestion["title"])[:120],
            "spec": spec, "filters": [], "page": page,
        }
        try:
            validate_widgets(frame, ds.schema_json, [candidate], [])
        except DataError:
            continue
        widgets.append(candidate)
        page_counts[page] += 1

    # Add compact, decision-useful pivot summaries to the Segments page.
    for pivot_index, segment in enumerate(analysis.get("segment_analysis", [])[:3], start=1):
        groups = segment.get("groups") or []
        if len(groups) < 2:
            continue
        measure = segment.get("measure", "measure")
        category = segment.get("category", "segment")
        table_rows = [{
            "Segment": group.get("value"),
            "Records": group.get("count"),
            f"Total {measure}": group.get("sum"),
            f"Average {measure}": group.get("mean"),
        } for group in groups[:20]]
        widgets.append({
            "id": f"auto-pivot-{pivot_index}",
            "title": f"{category} × {measure} — pivot summary",
            "spec": None, "filters": [], "page": "Segments", "display_type": "table",
            "table_columns": ["Segment", "Records", f"Total {measure}", f"Average {measure}"],
            "table_rows": table_rows,
        })
        page_counts["Segments"] += 1

    if not widgets:
        raise HTTPException(422, "The dataset does not contain suitable fields for automatic charts. Review its schema and try the manual chart builder.")

    dashboard_name = f"{ds.name} — Analyst dashboard"
    dashboard = db.scalar(select(Dashboard).where(
        Dashboard.owner_id == user.id, Dashboard.dataset_id == ds.id, Dashboard.name == dashboard_name
    ))
    if dashboard:
        dashboard.widgets = widgets
        dashboard.filters = []
    else:
        dashboard = Dashboard(owner_id=user.id, dataset_id=ds.id, name=dashboard_name, widgets=widgets, filters=[])
        db.add(dashboard)
    db.flush()

    findings = analysis.get("business_insights", [])[:7]
    recommendations = analysis.get("recommendations", [])[:6]
    quality = analysis.get("data_quality", {})
    for item in quality.get("issues", [])[:20]:
        pending_decisions.append({
            "issue": item.get("title", "Data quality issue"),
            "decision": "Review required",
            "reason": item.get("suggestion", "Confirm the business meaning before changing data."),
        })
    if quality.get("missing_by_column"):
        applied_steps.append({
            "step": "Data-quality assessment", "status": "completed",
            "detail": f"Inspected {quality.get('cells_scanned', 0):,} cells and identified {quality.get('issue_count', 0)} issue(s), including missingness by field.",
            "undo_available": False,
        })
    applied_steps.extend([
        {"step": "Field-aware analytical validation", "status": "completed", "detail": "Every generated visual uses only valid values for its required fields. Missing categorical values are retained as '(Not recorded)'; missing dates and numeric measures are excluded only from visuals that require them. No source records were deleted or values invented.", "undo_available": False},
        {"step": "Statistical analysis", "status": "completed", "detail": f"Calculated descriptive statistics for {len(analysis.get('numeric_summary', []))} numeric field(s), category profiles, segment comparisons and correlations.", "undo_available": False},
        {"step": "Chart selection", "status": "completed", "detail": f"Validated and selected {len(widgets)} charts across {len({w['page'] for w in widgets})} dashboard page(s).", "undo_available": False},
        {"step": "Narrative generation", "status": "completed", "detail": f"Prepared {len(findings)} evidence-led finding(s) and {len(recommendations)} recommendation(s). These are descriptive rules-based outputs, not generative AI claims.", "undo_available": False},
    ])

    row_count = analysis.get("dataset", {}).get("rows", ds.n_rows)
    num_cols = analysis.get("dataset", {}).get("columns", ds.n_cols)
    question = body.business_question or "What are the most important business performance patterns, opportunities and risks in this dataset?"
    executive_summary = (
        f"This automated analyst run reviewed {row_count:,} records across {num_cols} fields in '{ds.name}'. "
        f"prepared {len(widgets)} validated visual(s) across {len({w['page'] for w in widgets})} dashboard page(s), "
        f"and generated {len(findings)} business finding(s) with {len(recommendations)} practical recommendation(s). "
        "Findings describe observed performance, contribution, segment differences and trends; they are descriptive and do not establish causation."
    )
    report_title = f"{ds.name} — Automated analysis report"
    report = db.scalar(select(AnalysisReport).where(
        AnalysisReport.owner_id == user.id, AnalysisReport.dataset_id == ds.id, AnalysisReport.title == report_title
    ))
    if report:
        report.business_question = question
        report.audience = body.audience
        report.row_grain = body.row_grain
        report.executive_summary = executive_summary
        report.findings = findings
        report.recommendations = recommendations
    else:
        report = AnalysisReport(
            owner_id=user.id, dataset_id=ds.id, title=report_title,
            business_question=question, audience=body.audience, row_grain=body.row_grain,
            executive_summary=executive_summary, findings=findings, recommendations=recommendations,
        )
        db.add(report)
    db.commit()
    db.refresh(dashboard)
    db.refresh(report)

    return {
        "status": "completed", "dataset": {"id": ds.id, "name": ds.name, "rows": ds.n_rows, "columns": ds.n_cols},
        "dashboard": {"id": dashboard.id, "name": dashboard.name, "pages": sorted({w["page"] for w in widgets}), "widgets": len(widgets)},
        "report": {"id": report.id, "title": report.title},
        "applied_steps": applied_steps, "pending_decisions": pending_decisions,
        "analysis_summary": {"findings": len(findings), "recommendations": len(recommendations), "quality_issues": quality.get("issue_count", 0)},
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/{dataset_id}/export")
def export_dataset(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db), store: DatasetStore = Depends(get_store)):
    ds = owned_dataset(db, user, dataset_id)
    frame = store.load(ds)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", ds.name).strip("._") or "dataset"
    return StreamingResponse(io.BytesIO(buffer.getvalue().encode("utf-8-sig")), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}_cleaned.csv"'})
