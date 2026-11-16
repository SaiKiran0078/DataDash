# DataDash API Reference

Base URL: `http://localhost:8001/api` (or `http://localhost:8081/api` via Docker). Interactive docs: `/api/docs`.
Protected endpoints need `Authorization: Bearer <token>`.
Errors look like `{ "detail": "message" }` (validation errors list the failing fields).

## Auth
### POST /auth/register · POST /auth/login
```json
{ "email": "asha@example.com", "password": "password123" }
```
→ `{ "token": "eyJ...", "user": { "id": 1, "email": "asha@example.com" } }`
Errors: `422` invalid email / password < 8 chars · `409` email taken (register) · `401` wrong credentials (login) · `429` too many attempts.

### GET /auth/me → `{ "user": { id, email } }`

## Datasets
### POST /datasets  (multipart/form-data)
| Field | Notes |
|---|---|
| `file` | `.csv`, `.tsv`, `.xlsx` · ≤ 10 MB · ≤ 200,000 rows · ≤ 200 columns |
| `name` | optional display name |

```bash
curl -H "Authorization: Bearer $TOKEN" -F "file=@sample_data/sales.csv" localhost:8001/api/datasets
```
→ `201`
```json
{ "id": 1, "name": "sales", "rows": 421, "columns": 10,
  "schema": [ { "name": "order_date", "kind": "datetime" }, { "name": "revenue", "kind": "numeric" } ],
  "profile": { "rows": 421, "duplicate_rows": 1, "missing_pct": 2.6,
    "column_profiles": [ { "name": "revenue", "kind": "numeric", "missing": 0, "min": 899, "max": 239952, "mean": 8568.3,
                           "median": 5397, "outliers": 21, "outlier_bounds": [-8248, 21744] } ] },
  "notes": [] }
```
Column `kind` is one of `numeric`, `datetime`, `boolean`, `categorical`, `text`, `id`.
Errors: `415` unsupported type · `413` too large / too many rows or columns · `400` unreadable or empty · `409` dataset quota reached.

### GET /datasets · GET /datasets/{id} · PATCH /datasets/{id} `{ "name" }` · DELETE /datasets/{id}
Deleting a dataset also deletes its stored file and its dashboards. Other users' datasets return `404`.

### GET /datasets/{id}/suggestions
```json
{ "suggestions": [ { "id": "s1", "score": 92, "title": "Total revenue over time",
  "reason": "'order_date' is a date and 'revenue' is a number - a trend line shows how it changes.",
  "spec": { "type": "line", "x": "order_date", "y": "revenue", "agg": "sum" } } ] }
```

### POST /datasets/{id}/chart
```json
{ "spec": { "type": "bar", "x": "region", "y": "revenue", "agg": "sum", "top_n": 10 },
  "filters": [ { "column": "category", "op": "eq", "value": "Home" } ] }
```
**Chart spec**
| Field | Values |
|---|---|
| `type` | `bar`, `line`, `pie`, `histogram`, `scatter` |
| `x`, `y` | column names (histogram: numeric `x`; scatter: numeric `x` and `y`) |
| `agg` | `count` (default), `sum`, `mean`, `median`, `min`, `max` (all but count need numeric `y`) |
| `time_grain` | `day`, `week`, `month`, `quarter`, `year` (auto if omitted, for date `x`) |
| `color_by` | categorical column with ≤ 8 values (one series per value) |
| `top_n` | 1-50 (pie ≤ 12) · `sort`: `value_desc` or `label` · `bins`: 2-50 (histogram) |

**Filter** - `{ column, op, value }`; ops: `eq ne gt gte lt lte` · `in` (list ≤ 100) · `between` (`[low, high]`) · `contains` (text columns). At most 10 filters.

Response (bar/line/pie/histogram):
```json
{ "type": "bar", "labels": ["West", "North", "South", "East"], "datasets": [ { "label": "sum of revenue", "data": [1000544, 931090, 884189, 791431] } ],
  "meta": { "x": "region", "y": "revenue", "agg": "sum", "rows_used": 421, "filtered_rows": 421, "truncated": false } }
```
Scatter returns `{ "points": [{x, y}], "meta": { correlation, sampled } }` (max 1,000 points, evenly sampled).
Bad column, operator, aggregation or value → `400`/`422` with a plain message.

### POST /datasets/{id}/clean/preview and POST /datasets/{id}/clean/apply
Build a cleaning workflow using `{ "operations": [...] }`. Preview returns before/after row, column, missing-cell and duplicate counts, an operation log, a refreshed profile and an eight-row sample. Preview never mutates stored data. Apply executes the same validated operations, replaces the stored dataset file and refreshes the schema/profile.

Supported operation objects (one `type` per item):
- `{ "type": "trim_text", "column": "region" }` (omit `column` to trim all text columns)
- `{ "type": "fill_missing", "column": "revenue", "strategy": "mean" }` (`mean`, `median`, `mode`, or `value`; custom uses `value`)
- `{ "type": "drop_missing_rows", "column": "region" }` (omit `column` to remove rows with any missing cell)
- `{ "type": "drop_duplicates" }`
- `{ "type": "rename_column", "column": "old", "new_name": "new" }`
- `{ "type": "drop_column", "column": "unused" }`
- `{ "type": "convert_type", "column": "amount", "target": "numeric" }` (`numeric`, `datetime`, `text`, `boolean`)
- `{ "type": "remove_outliers", "column": "amount", "factor": 1.5 }` (`factor`: `1.5` or `3`)
- `{ "type": "replace_value", "column": "status", "find": "N/A", "replace": "Unknown" }`

### GET /datasets/{id}/export
Downloads the currently stored (cleaned) dataset as UTF-8 CSV.

### POST /datasets/{id}/rows?page=1&page_size=25&sort_by=revenue&descending=true
Body (optional): `{ "filters": [...] }` → `{ columns, kinds, rows, total, page, page_size }` (page size ≤ 100).

### GET /datasets/{id}/outliers?column=units
```json
{ "column": "units", "count": 2, "lower": -3.5, "upper": 8.5, "rows": [ { "row": 78, "value": 55 }, { "row": 279, "value": 48 } ] }
```
Rule: outside Q1 − 1.5×IQR or Q3 + 1.5×IQR. Not numeric → `400`.

## Dashboards
Body for create/update:
```json
{ "name": "Q4 review", "dataset_id": 1,
  "widgets": [ { "id": "w1", "title": "Revenue by region", "spec": { "type": "bar", "x": "region", "y": "revenue", "agg": "sum" }, "filters": [] } ],
  "filters": [ { "column": "region", "op": "in", "value": ["North", "West"] } ] }
```
| Method | Path | Notes |
|---|---|---|
| POST | `/dashboards` | `201`; every widget is test-built first, a bad one → `422` naming the widget (max 20 widgets) |
| GET | `/dashboards`, `/dashboards/{id}` | Includes `shared` and `share_token` |
| PUT | `/dashboards/{id}` | Replace name/widgets/filters |
| DELETE | `/dashboards/{id}` | `204` |
| GET | `/dashboards/{id}/data` | `{ widgets: [{ id, title, spec, data }] }` - dashboard filters + widget filters applied; per-widget `data.error` if one fails |
| POST | `/dashboards/{id}/share` | Create **or rotate** the secret link token |
| DELETE | `/dashboards/{id}/share` | Stop sharing (old link stops working) |

## Public share link
### GET /shared/{token}  (no login)
→ `{ "name": "...", "widgets": [ { id, title, spec, data } ] }`
Unknown/disabled token → `404`. Responses are `Cache-Control: no-store` and `X-Robots-Tag: noindex`. Rate-limited (`429`). Never includes raw rows, schema, owner or dataset id.

## Status codes
`200` ok · `201` created · `204` deleted · `400` bad data or request · `401` not logged in · `404` not found (also for other users' resources) · `409` conflict/quota · `413` too large · `415` unsupported file type · `422` validation failed · `429` rate limited.

## Analyst workflow and saved reports

### `GET /api/datasets/{dataset_id}/analysis`

Returns a descriptive analysis snapshot for an owned dataset:

- `dataset`: record counts, missingness, duplicate counts and detected field groups.
- `numeric_summary`: count, sum, mean, median, min, max, standard deviation, quartiles, negative/zero counts and skew for numeric columns.
- `category_summary`: unique counts and the most frequent values with row shares.
- `correlations`: strongest Pearson correlations among up to 12 numeric fields.
- `findings` and `recommendations`: evidence-led prompts generated from data quality and statistical patterns.
- `analyst_questions` and `method_notes`: questions and caveats to guide interpretation.

The endpoint is descriptive and does not claim causality or prediction. Pearson correlation is a linear association measure; exact duplicate rows must be checked against the business key.

### Saved reports

- `GET /api/datasets/{dataset_id}/reports` — list reports for the dataset.
- `POST /api/datasets/{dataset_id}/reports` — create a report.
- `PUT /api/datasets/{dataset_id}/reports/{report_id}` — update a report.
- `DELETE /api/datasets/{dataset_id}/reports/{report_id}` — delete a report.

A report accepts `title`, `business_question`, `audience`, `row_grain`, `executive_summary`, `findings` and `recommendations`. All routes require an authenticated user who owns the dataset and report. Reports are stored in the `analysis_reports` table and are deleted with their parent dataset.


## Automated analyst pipeline (v5.0)

`POST /api/datasets/{dataset_id}/auto-build` runs the explainable analyst workflow and creates/updates a multi-page dashboard plus a saved analysis report. Optional JSON fields: `business_question`, `audience`, `row_grain`, `apply_safe_text_trim`. The response contains the dataset snapshot, dashboard/report IDs, applied steps, pending analyst decisions, counts of findings/recommendations/quality issues and a generated timestamp.

The upload experience invokes this endpoint after a successful upload. The pipeline only auto-applies low-risk text whitespace normalization (recorded in dataset undo history). It does not silently impute missing values, delete duplicates or remove outliers.

## Interactive dashboard and data modeling additions (5.3)

- `POST /api/dashboards/{dashboard_id}/query` accepts `{ "filters": [...] }` and returns all saved widgets rendered against temporary cross-filters. This does not persist the filter state; use the dashboard update route to save it.
- `GET /api/datasets/{dataset_id}/values?column={column}&limit=100` returns owner-scoped distinct values (datetime columns are grouped by month for drill-down).
- `POST /api/datasets/{dataset_id}/combine` creates a new derived dataset using `{ "mode":"append", "other_dataset_id": 2 }` or `{ "mode":"join", "other_dataset_id": 2, "left_key":"id", "right_key":"id", "join_type":"left" }`. Append requires matching column names. Join supports left, inner, right and outer. Source datasets are not modified.
- `GET /api/dashboards/{dashboard_id}/export/powerbi-project` returns a self-contained PBIP project ZIP with an embedded CSV snapshot, report definition and semantic model.
- `GET /api/dashboards/{dashboard_id}/export/tableau` returns a `.twbx` packaged workbook.
- `GET /api/dashboards/{dashboard_id}/export/powerpoint` returns an editable `.pptx` executive deck.


## Numeric relationships

`GET /api/datasets/{dataset_id}/relationships` returns pairwise Pearson correlations for numeric columns in a dataset owned by the authenticated user. Each result includes the two field names, coefficient, direction, descriptive strength label and number of pairwise-complete records. Pairs with fewer than three complete records or no variation in either field are omitted. The computation is capped at 40 numeric fields and 200 pairs. Correlation is descriptive and does not establish causation.


## Excel worksheet import (6.0.2)

- `POST /api/datasets/workbook/sheets` accepts multipart `file` (`.xlsx`) and returns the workbook's worksheet names. It does not create a dataset.
- `POST /api/datasets/workbook/import` accepts multipart `file` and `sheet_names` (a JSON array of exact worksheet names). Each selected worksheet is ingested independently and saved as its own dataset. The import is all-or-nothing: if any selected sheet fails validation or storage/DB commit, no datasets from that request are retained.
- Worksheet selection is owner-authenticated, enforces upload/row/column/dataset quotas, and rejects unknown or duplicate sheet names. Existing `POST /api/datasets` remains backward-compatible and imports the first worksheet when no sheet is specified.
