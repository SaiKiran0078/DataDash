import { useEffect, useMemo, useState } from "react";
import api, { errorMessage } from "../api/client.js";
import { fmt, KIND_LABEL } from "../utils.js";

const INITIAL = { type: "drop_duplicates" };
const TITLES = {
  trim_text: "Trim whitespace", fill_missing: "Fill missing values", drop_missing_rows: "Remove incomplete rows",
  drop_duplicates: "Remove duplicate rows", drop_column: "Remove a column", rename_column: "Rename a column",
  convert_type: "Convert data type", remove_outliers: "Remove outliers", replace_value: "Find and replace", calculated_column: "Create calculated column",
};

export default function CleaningStudio({ dataset, onApplied, onSuggestionVisibilityChange }) {
  const [operation, setOperation] = useState(INITIAL);
  const [queue, setQueue] = useState([]);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [appliedSuggestionHistory, setAppliedSuggestionHistory] = useState([]);
  const [redoSuggestionHistory, setRedoSuggestionHistory] = useState([]);
  const numeric = useMemo(() => dataset.schema.filter((c) => c.kind === "numeric"), [dataset.schema]);
  const columns = dataset.schema;

  function change(key, value) { setOperation((o) => ({ ...o, [key]: value })); setPreview(null); }
  useEffect(() => {
    function addSuggested(event) {
      const { operation: suggested, suggestionId } = event.detail || {};
      if (!suggested?.type) return;
      setQueue((items) => [...items, { ...suggested, _suggestionId: suggestionId || null }]);
      if (suggestionId) onSuggestionVisibilityChange?.(suggestionId, true);
      setPreview(null); setError(""); setSuccess(`${suggested.column || "Dataset"}: suggested cleaning step added to your queue.`);
    }
    window.addEventListener("datadash:add-clean-step", addSuggested);
    return () => window.removeEventListener("datadash:add-clean-step", addSuggested);
  }, [onSuggestionVisibilityChange]);
  function addOperation() {
    const next = { ...operation };
    if (next.type === "fill_missing" && !next.strategy) {
      const field = columns.find((c) => c.name === next.column);
      if (field?.kind === "datetime") { setError("Choose a date fill method explicitly. Forward/backward fill is only appropriate when row order is meaningful."); return; }
      next.strategy = "mode";
    }
    if (["fill_missing", "drop_column", "rename_column", "convert_type", "remove_outliers", "replace_value"].includes(next.type) && !next.column) {
      setError("Choose a column for this operation."); return;
    }
    if (next.type === "rename_column" && !next.new_name?.trim()) { setError("Enter the new column name."); return; }
    if (next.type === "calculated_column" && (!next.new_name?.trim() || !next.formula?.trim())) { setError("Enter a calculated column name and formula."); return; }
    if (next.type === "replace_value" && next.find === undefined) { setError("Enter the value to find."); return; }
    setQueue((q) => [...q, next]); setPreview(null); setError(""); setSuccess("");
  }
  async function makePreview() {
    if (!queue.length) { setError("Add at least one cleaning step first."); return; }
    setBusy(true); setError(""); setSuccess("");
    try { setPreview((await api.post(`/datasets/${dataset.id}/clean/preview`, { operations: queue.map(({ _suggestionId, ...op }) => op) })).data); }
    catch (e) { setError(errorMessage(e)); setPreview(null); }
    finally { setBusy(false); }
  }
  async function apply() {
    if (!preview) return;
    if (!window.confirm("Apply these transformations to the dataset? A recoverable version snapshot will be created first.")) return;
    setBusy(true); setError("");
    try {
      const suggestionIds = queue.map((op) => op._suggestionId).filter(Boolean);
      const updated = (await api.post(`/datasets/${dataset.id}/clean/apply`, { operations: queue.map(({ _suggestionId, ...op }) => op) })).data;
      setAppliedSuggestionHistory((items) => [...items, suggestionIds]);
      setRedoSuggestionHistory([]);
      setQueue([]); setPreview(null); setSuccess("Cleaning changes applied. Dataset profile and charts have been refreshed.");
      onApplied?.(updated); await refreshHistory();
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  const selectedColumn = columns.find((c) => c.name === operation.column);
  const fillKind = selectedColumn?.kind;
  const needsColumn = ["fill_missing", "drop_missing_rows", "drop_column", "rename_column", "convert_type", "remove_outliers", "replace_value", "trim_text"].includes(operation.type);
  const [history, setHistory] = useState({ undo: [], redo: [] });
  async function refreshHistory() { try { setHistory((await api.get(`/datasets/${dataset.id}/history`)).data); } catch { /* history is additive */ } }
  useEffect(() => { refreshHistory(); }, [dataset.id]);
  async function travel(direction) {
    setBusy(true); setError("");
    try {
      const result = (await api.post(`/datasets/${dataset.id}/${direction}`)).data;
      setHistory(result.history); setQueue([]); setPreview(null);
      if (direction === "undo") {
        const last = appliedSuggestionHistory.at(-1) || [];
        setAppliedSuggestionHistory((items) => items.slice(0, -1));
        setRedoSuggestionHistory((items) => [...items, last]);
        last.forEach((suggestionId) => onSuggestionVisibilityChange?.(suggestionId, false));
      } else {
        const last = redoSuggestionHistory.at(-1) || [];
        setRedoSuggestionHistory((items) => items.slice(0, -1));
        setAppliedSuggestionHistory((items) => [...items, last]);
        last.forEach((suggestionId) => onSuggestionVisibilityChange?.(suggestionId, true));
      }
      setSuccess(direction === "undo" ? "Last transformation reverted." : "Transformation restored.");
      onApplied?.(result.dataset);
    }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  return <div className="cleaning-layout">
    <section className="card clean-builder">
      <div className="section-heading"><div><span className="eyebrow">DATA PREPARATION</span><h2>Cleaning studio</h2><p className="muted">Build a sequence of changes, preview the impact, then apply it.</p></div><span className="icon-orb">✦</span></div>
      <div className="clean-step-form">
        <label>Cleaning action<select value={operation.type} onChange={(e) => { setOperation({ type: e.target.value }); setPreview(null); }}>
          <option value="drop_duplicates">Remove duplicate rows</option><option value="fill_missing">Fill empty cells</option><option value="drop_missing_rows">Remove rows with missing values</option><option value="trim_text">Trim extra spaces</option><option value="replace_value">Find and replace values</option><option value="rename_column">Rename a column</option><option value="drop_column">Remove a column</option><option value="convert_type">Convert column type</option><option value="remove_outliers">Remove numeric outliers</option><option value="calculated_column">Create calculated column</option>
        </select></label>
        {needsColumn && <label>Column<select value={operation.column || ""} onChange={(e) => {
          const name = e.target.value;
          const field = columns.find((c) => c.name === name);
          setOperation((o) => ({ ...o, column: name, ...(o.type === "fill_missing" ? { strategy: field?.kind === "datetime" ? "" : "mode", value: undefined } : {}) }));
          setPreview(null);
        }}><option value="">Choose column</option>{columns.map((c) => <option key={c.name} value={c.name}>{c.name} · {KIND_LABEL[c.kind] || c.kind}</option>)}</select></label>}
        {operation.type === "fill_missing" && <>
          <label>Fill method<select value={operation.strategy || (fillKind === "datetime" ? "" : "mode")} onChange={(e) => change("strategy", e.target.value)}>
            {fillKind === "datetime" ? <>
              <option value="" disabled>Choose a date fill method</option><option value="ffill">Forward fill · previous valid date</option><option value="bfill">Backward fill · next valid date</option><option value="value">Custom date</option>
            </> : fillKind === "numeric" ? <>
              <option value="mean">Average (mean)</option><option value="median">Median</option><option value="mode">Most common value (mode)</option><option value="value">Custom number</option>
            </> : fillKind === "boolean" ? <>
              <option value="mode">Most common value (mode)</option><option value="value">Custom true / false</option>
            </> : <>
              <option value="mode">Most common value (mode)</option><option value="value">Custom category / text</option>
            </>}
          </select></label>
          {operation.strategy === "value" && <label>{fillKind === "datetime" ? "Replacement date (YYYY-MM-DD)" : fillKind === "numeric" ? "Replacement number" : fillKind === "boolean" ? "Replacement true / false" : "Replacement value"}
            <input type={fillKind === "datetime" ? "date" : fillKind === "numeric" ? "number" : "text"} value={operation.value ?? ""} placeholder={fillKind === "boolean" ? "true or false" : fillKind === "numeric" ? "Enter a number" : fillKind === "datetime" ? "Choose a date" : "e.g. Unknown"} onChange={(e) => change("value", e.target.value)} />
          </label>}
          {fillKind === "datetime" && <p className="helper-text">Date values are never replaced with 0 or “Unknown”. Forward/backward fill uses adjacent records and is appropriate only when row order is meaningful. Otherwise use a verified source date or leave the value missing with a documented reason.</p>}
          {fillKind === "numeric" && <p className="helper-text">Mean and median change only missing numeric cells. Choose based on the distribution; use a custom number only when it has a valid business meaning.</p>}
        </>}
        {operation.type === "drop_missing_rows" && <label>Apply to<select value={operation.column || ""} onChange={(e) => change("column", e.target.value || undefined)}><option value="">Any column (remove rows with any blanks)</option>{columns.map((c) => <option key={c.name} value={c.name}>{c.name} only</option>)}</select></label>}
        {operation.type === "rename_column" && <label>New column name<input placeholder="e.g. Customer Segment" value={operation.new_name || ""} onChange={(e) => change("new_name", e.target.value)} /></label>}
        {operation.type === "convert_type" && <label>Convert to<select value={operation.target || "numeric"} onChange={(e) => change("target", e.target.value)}><option value="numeric">Number</option><option value="datetime">Date / time</option><option value="text">Text</option><option value="boolean">True / false</option></select></label>}
        {operation.type === "remove_outliers" && <label>Outlier sensitivity<select value={operation.factor || 1.5} onChange={(e) => change("factor", Number(e.target.value))}><option value="1.5">Standard · 1.5× IQR</option><option value="3">Conservative · 3× IQR</option></select></label>}
        {operation.type === "replace_value" && <><label>Find value<input value={operation.find ?? ""} onChange={(e) => change("find", e.target.value)} /></label><label>Replace with<input value={operation.replace ?? ""} onChange={(e) => change("replace", e.target.value)} /></label></>}
        {operation.type === "trim_text" && <p className="helper-text">Choose a column to trim only that field, or leave it unselected to trim all text columns.</p>}
        <button className="btn" type="button" onClick={addOperation}>＋ Add cleaning step</button>
      </div>
      <div className="clean-guidance"><strong>Formula examples</strong><p className="small muted">revenue / units · unit_price * units · round(revenue / units, 2)</p><strong>Suggested workflow</strong><ol><li>Remove duplicate records.</li><li>Trim spaces and standardise inconsistent values.</li><li>Review missing values; fill or remove them intentionally.</li><li>Check data types and outliers.</li><li>Preview before applying.</li></ol><p className="muted small">Tip: use mean or median for numeric fields, mode for categories, and a custom value when “Unknown” is more honest than guessing.</p></div>
    </section>
    <section className="stack">
      <div className="card clean-queue"><div className="row between wrap"><div><span className="eyebrow">YOUR WORKFLOW</span><h3>Applied steps & transformation queue</h3></div><div className="row wrap"><button className="btn btn-outline small" disabled={busy || !history.undo?.length} onClick={() => travel("undo")}>↶ Undo</button><button className="btn btn-outline small" disabled={busy || !history.redo?.length} onClick={() => travel("redo")}>↷ Redo</button><button className="btn btn-ghost small" disabled={!queue.length} onClick={() => { queue.forEach((op) => op._suggestionId && onSuggestionVisibilityChange?.(op._suggestionId, false)); setQueue([]); setPreview(null); }}>Clear queue</button></div></div><p className="muted small">{history.undo?.length || 0} undoable version(s) · {history.redo?.length || 0} redoable version(s). Changes are versioned so you can recover the previous dataset.</p>
        {!queue.length ? <div className="empty-state"><span>⌁</span><strong>No steps added yet</strong><p className="muted small">Select a cleaning action and add it to your workflow.</p></div> : <ol className="operation-list">{queue.map((op, i) => <li key={`${op.type}-${i}`}><div><span className="step-index">{i + 1}</span><div><strong>{TITLES[op.type]}</strong><p className="muted small">{op.column || "All columns"}{op.strategy ? ` · ${op.strategy}` : ""}{op.new_name ? ` → ${op.new_name}` : ""}</p></div></div><button className="icon-button" aria-label="Remove step" onClick={() => { if (op._suggestionId) onSuggestionVisibilityChange?.(op._suggestionId, false); setQueue((q) => q.filter((_, j) => j !== i)); setPreview(null); }}>×</button></li>)}</ol>}
        <div className="row wrap"><button className="btn btn-outline" disabled={!queue.length || busy} onClick={makePreview}>{busy ? "Working…" : "Preview changes"}</button><button className="btn" disabled={!preview || busy} onClick={apply}>Apply changes</button></div>
      </div>
      {error && <p className="error" role="alert">{error}</p>}{success && <p className="success-banner">✓ {success}</p>}
      {preview && <div className="card preview-card"><div className="row between"><div><span className="eyebrow">PREVIEW</span><h3>Impact analysis</h3></div><span className="badge badge-good">Previewed · not applied</span></div>
        <div className="grid stats"><div className="stat metric-tile"><span className="muted small">Rows</span><strong>{fmt(preview.before.rows)} <span className="delta">→ {fmt(preview.after.rows)}</span></strong></div><div className="stat metric-tile"><span className="muted small">Columns</span><strong>{preview.before.columns} <span className="delta">→ {preview.after.columns}</span></strong></div><div className="stat metric-tile"><span className="muted small">Missing cells</span><strong>{fmt(preview.before.missing)} <span className="delta">→ {fmt(preview.after.missing)}</span></strong></div><div className="stat metric-tile"><span className="muted small">Duplicate rows</span><strong>{fmt(preview.before.duplicates)} <span className="delta">→ {fmt(preview.after.duplicates)}</span></strong></div></div>
        <h4>Operation impact</h4><ul className="impact-list">{preview.operations.map((o, i) => <li key={i}><div><strong>{TITLES[o.type]}{o.column ? ` · ${o.column}` : ""}</strong>{o.cells_filled > 0 && <p className="muted small">{fmt(o.cells_filled)} missing value(s) will be filled using {o.strategy === "ffill" ? "the previous valid date" : o.strategy === "bfill" ? "the next valid date" : o.strategy}.</p>}</div><span>{o.cells_filled > 0 ? `${fmt(o.cells_filled)} values to fill` : o.rows_removed ? `${fmt(o.rows_removed)} rows to remove` : o.columns_removed ? `${fmt(o.columns_removed)} column(s) to remove` : "Previewed"}</span></li>)}</ul>
        <h4>Sample after cleaning</h4><div className="table-wrap"><table><thead><tr>{Object.keys(preview.sample[0] || {}).map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>{preview.sample.map((r, i) => <tr key={i}>{Object.values(r).map((v, j) => <td key={j}>{v == null ? <em className="missing-cell">Empty</em> : String(v)}</td>)}</tr>)}</tbody></table></div>
        <p className="muted small">Preview only — no stored data has changed. Apply changes only after reviewing the sample, value counts and business impact. A successful server response is required before the UI reports that changes were applied.</p>
      </div>}
    </section>
  </div>;
}
