# DataDash 5.3 — Portable dashboard exports

DataDash can export the current saved dashboard and its source dataset for use in other analytics tools.

## PDF
Use **Export full PDF** on a dashboard. The print view includes the KPI snapshot, automatic overview visuals, analyst findings, and every saved dashboard page (not only the currently selected tab).

## Power BI Project (PBIP)
The single **Export to Power BI (.pbip)** action creates an editable PBIP/PBIR project ZIP containing:
- `Data.csv` — the current stored dataset snapshot
- `Field_Dictionary.csv` — inferred types, missing counts, unique counts and example values
- an embedded Power Query M data expression using the dataset snapshot (no machine-specific file path)
- `DAX_Measures.dax` — starter record-count, sum, average and median measures for numeric fields
- `Dashboard_Model.json` — dashboard page names, widget specifications and filters
- `Visual_Data/` — chart-ready data extracts for saved visuals

This is an editable `.pbip` project, not a `.pbix` binary. Open the `.pbip` in a recent Power BI Desktop; the model's data snapshot is embedded and should not require a local source-path edit. The project contains a generated semantic model and multi-page report definitions. Native Desktop validation is required before production use; this build environment cannot run Power BI Desktop.

## Tableau packaged workbook
The Tableau `.twbx` package contains a `.twb` workbook definition and its packaged `Data/Data.csv` source, plus field dictionary and visual data extracts. Open the `.twbx` in Tableau Desktop or Tableau Reader. The workbook uses a packaged relative data source rather than the exporting machine's file path. Native Tableau validation is still required before production publication.

## PowerPoint executive report
The `.pptx` contains editable KPI cards, PowerPoint chart objects for saved dashboard visuals, descriptive numeric/category findings, and data-quality considerations. It reflects the current dataset snapshot at export time.

## Excel workbook
The `.xlsx` workbook includes `Data`, `Field Dictionary`, `KPI Summary`, `Dashboard Pages`, and one chart-ready sheet per saved dashboard visual.

## Data and security
Exports are authenticated and owner-scoped. They use the current stored dataset snapshot and saved dashboard definition. Dashboard filters are applied to exported visual summaries; the packaged `Data.csv`/Excel `Data` sheet contains the full current dataset snapshot so downstream tools can create their own slicers and filters. Export files are generated on request and are not stored on the server. Visual semantics and KPI definitions are aligned with DataDash, but platform renderers may differ in styling and layout; Power BI Desktop and Tableau Desktop native-open tests are not available in the Linux build environment.
