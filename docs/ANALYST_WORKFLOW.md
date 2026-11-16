# DataDash Analyst Workflow

DataDash now includes a guided workflow designed around the sequence a data analyst follows:

1. **Understand** — inspect dataset grain, inferred field types, basic profile and business questions to clarify before analysis.
2. **Prepare** — use the existing cleaning studio to preview and apply explicit transformations. Cleaning operations include duplicate handling, missing-value treatment, whitespace trimming, value replacement, column rename/removal, type conversion and IQR outlier filtering.
3. **Analyze** — review descriptive statistics, category mix, Pearson correlations and reproducible findings generated from the current dataset snapshot.
4. **Visualize** — review chart recommendations and create a dashboard containing up to eight recommended visualisations.
5. **Story** — edit an executive summary, evidence-backed findings and prioritised recommendations; save multiple report drafts to PostgreSQL.
6. **Deliver** — open dashboards, export a standalone HTML report or print the report to PDF from the browser.

## Analyst interpretation guardrails

- The analysis endpoint is descriptive, not predictive. It does not establish causality.
- Pearson correlation describes linear association only.
- Exact duplicate rows are a signal to investigate; they are not automatically invalid business records.
- The workflow's quality indicator is a transparent prioritisation heuristic, not a certified data-quality standard.
- Generated findings and recommendations are starting points. Analysts should validate row grain, metric definitions, business context, date coverage and assumptions before publication.
- Cleaning preview does not mutate the saved dataset. Applying a cleaning plan replaces the current stored dataset version; preserve the source file when rollback is important.

## API additions

### `GET /api/datasets/{dataset_id}/analysis`

Returns dataset-level metrics, numeric summaries, category summaries, Pearson correlations, findings, recommendations, analyst questions and method notes. Requires an authenticated owner of the dataset.

### `GET /api/datasets/{dataset_id}/reports`

Lists the authenticated user's saved narrative reports for a dataset.

### `POST /api/datasets/{dataset_id}/reports`

Creates a report with `title`, `executive_summary`, `findings` and `recommendations`.

### `PUT /api/datasets/{dataset_id}/reports/{report_id}`

Updates a report owned by the authenticated user.

### `DELETE /api/datasets/{dataset_id}/reports/{report_id}`

Deletes a report owned by the authenticated user.

The `analysis_reports` table is created by the existing SQLAlchemy metadata bootstrap. Existing dataset and dashboard tables are not dropped or reset.


## Data quality intelligence (3.1)
- The Understand stage lists each detected issue, affected column, severity, count, percentage, and sample 1-based row numbers.
- Missingness is reported per column, not only as an overall cell count. The quality scan counts nulls and whitespace-only strings.
- Prepare repeats the issue queue and lets the analyst add safe suggested transformations to the cleaning queue. The full sequence must still be previewed and explicitly applied.
- Numeric fields generally suggest median imputation; categorical fields suggest mode only when missingness is below 40%. ID and date fields are never auto-filled. Ordinal feedback fields such as rating/score are flagged for review rather than automatic imputation to avoid distorting averages.
- Analyze now includes quartiles, skew, negative/zero counts, segment comparisons showing totals and averages, and monthly aggregates where date and numeric fields are available. These are descriptive summaries, not causal or predictive claims.


## Dashboard view controls (6.0.3)

Dashboard filter interactions support a bounded Undo/Redo history, filter chips, a dashboard-wide reset, and per-visual reset for the chart's grouping field. Clicking the currently selected segment/month again toggles that filter off. These controls affect the query/view state only; they do not edit source dataset rows. Filter changes are persisted to the dashboard only after selecting **Save changes**.
