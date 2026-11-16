# Modeling Workbench (4.0)

## Calculated columns
Use Prepare → Cleaning Studio → Create calculated column. Formula identifiers must match column names exactly; identifiers with spaces are not supported in formulas. Supported arithmetic operators are `+`, `-`, `*`, `/`, `//`, `%`, and `**` (constant exponent magnitude up to 8), plus unary signs and one comparison. Supported functions are `abs(x)`, `round(x[, digits])`, `sqrt(x)`, and `log(x)`. Expressions are parsed into a restricted AST; arbitrary Python execution is not available. Null or non-numeric operands propagate as missing values where pandas arithmetic does so.

Example: `revenue / units` creates a per-unit revenue measure. Preview before applying.

## Undo and redo
After a cleaning operation is applied, the previous dataset file, schema and profile are stored as a version snapshot. Use Undo / Redo in the Cleaning Studio. The service retains up to 30 undo snapshots per dataset; applying a new operation clears the redo stack. Snapshot CSV files live in the configured dataset data directory and must be included in backups.

## Pivot tables
Analyze → Data Modeling Studio lets you choose a row dimension, optional column dimension, measure and aggregation. Supported aggregations: sum, mean, median, count, min and max. Pivot results are capped at 500 rows and are read-only; they do not alter the source dataset.

## Insight Assistant
The built-in assistant answers a small set of questions from the current dataset profile, numeric summaries, category distributions and generated findings. It is deterministic and auditable, not a connected generative AI model. Do not treat it as a substitute for a model-backed copilot.

## Remaining roadmap
Full Excel formula compatibility, multi-query Power Query joins/append, drag-and-drop dashboard layout, cross-visual brushing, drill-through navigation, scheduled refresh and external AI-provider integration remain future capabilities.


## Numeric relationship explorer (5.6.0)

The Modeling Studio can calculate pairwise Pearson correlations for numeric columns.
Each pair uses pairwise-complete records and reports its sample count. Pairs with fewer
than three complete records or no variation in either field are omitted. The API limits
the analysis to the first 40 numeric columns and returns at most 200 pairs.

Interpretation is descriptive: correlation measures linear association and does not
establish causation. Outliers, non-linear relationships, mixed populations and the
meaning/units of fields can materially affect the result. Investigate the underlying
records and business context before making decisions.
