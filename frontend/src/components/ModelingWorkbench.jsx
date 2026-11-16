import { useMemo, useState } from "react";
import api, { errorMessage } from "../api/client.js";

const makeId = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;

export default function ModelingWorkbench({ dataset, analysis }) {
  const categorical = useMemo(() => dataset.schema.filter((c) => ["categorical", "boolean", "text", "id"].includes(c.kind)), [dataset.schema]);
  const numeric = useMemo(() => dataset.schema.filter((c) => c.kind === "numeric"), [dataset.schema]);
  const [rowFields, setRowFields] = useState([categorical.find((c) => !/(^id$|_id$|id$|customer|account|email)/i.test(c.name))?.name || categorical[0]?.name || dataset.schema[0]?.name || ""]);
  const [columnFields, setColumnFields] = useState([]);
  const [measures, setMeasures] = useState([{ id: makeId(), field: numeric[0]?.name || "", aggregation: "sum" }]);
  const [rowChoice, setRowChoice] = useState("");
  const [columnChoice, setColumnChoice] = useState("");
  const [measureChoice, setMeasureChoice] = useState(numeric[1]?.name || numeric[0]?.name || "");
  const [pivot, setPivot] = useState(null);
  const [savedPivots, setSavedPivots] = useState([]);
  const [viewName, setViewName] = useState("Sales summary");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [pivotSearch, setPivotSearch] = useState("");
  const [relationships, setRelationships] = useState(null);
  const [relationshipBusy, setRelationshipBusy] = useState(false);
  const [relationshipError, setRelationshipError] = useState("");

  const selectedDimensions = [...rowFields, ...columnFields];
  const availableRows = dataset.schema.filter((c) => !selectedDimensions.includes(c.name));
  const availableColumns = categorical.filter((c) => !selectedDimensions.includes(c.name));
  const highCardinality = rowFields.some((name) => {
    const field = dataset.schema.find((c) => c.name === name);
    return field?.kind === "id" || /(^id$|_id$|id$|customer|account|email)/i.test(name);
  });

  function addRowField() {
    if (rowChoice && rowFields.length + columnFields.length < 4) setRowFields((v) => [...v, rowChoice]);
    setRowChoice("");
  }
  function addColumnField() {
    if (columnChoice && rowFields.length + columnFields.length < 4) setColumnFields((v) => [...v, columnChoice]);
    setColumnChoice("");
  }
  function addMeasure() {
    if (measures.length >= 4) return;
    setMeasures((v) => [...v, { id: makeId(), field: measureChoice, aggregation: "sum" }]);
    setMeasureChoice(numeric.find((x) => !measures.some((m) => m.field === x.name))?.name || "");
  }
  function updateMeasure(id, patch) { setMeasures((v) => v.map((m) => m.id === id ? { ...m, ...patch } : m)); }

  async function loadRelationships() {
    setRelationshipBusy(true); setRelationshipError("");
    try {
      const response = await api.get(`/datasets/${dataset.id}/relationships`);
      setRelationships(response.data);
    } catch (e) {
      setRelationshipError(errorMessage(e));
      setRelationships(null);
    } finally {
      setRelationshipBusy(false);
    }
  }

  async function buildPivot() {
    if (!selectedDimensions.length) { setError("Add at least one row or column dimension."); return; }
    if (rowFields.length + columnFields.length > 4) { setError("Choose no more than four dimensions."); return; }
    setBusy(true); setError("");
    try {
      const configs = measures.length ? measures : [{ id: "records", field: "", aggregation: "count" }];
      const responses = await Promise.all(configs.map((m) => api.post(`/datasets/${dataset.id}/pivot`, {
        rows: rowFields, columns: columnFields, measure: m.field || null,
        aggregation: m.field ? m.aggregation : "count",
      }).then((r) => ({ ...r.data, measure: m.field || "Records", aggregation: m.aggregation || "count" }))));
      const keyFor = (row) => JSON.stringify(rowFields.map((f) => row[f] ?? null));
      const merged = new Map();
      responses.forEach((result) => result.rows.forEach((row) => {
        const key = keyFor(row);
        if (!merged.has(key)) {
          const base = {};
          rowFields.forEach((field) => { base[field] = row[field]; });
          merged.set(key, base);
        }
        const target = merged.get(key);
        result.columns.filter((col) => !rowFields.includes(col)).forEach((col) => {
          const label = `${result.measure} · ${col}`;
          target[label] = row[col];
        });
      }));
      const resultColumns = [...rowFields, ...responses.flatMap((r) => r.columns.filter((c) => !rowFields.includes(c)).map((c) => `${r.measure} · ${c}`))];
      const rows = [...merged.values()].slice(0, 500);
      setPivot({ columns: [...new Set(resultColumns)], rows, row_count: Math.max(...responses.map((r) => r.row_count)), truncated: responses.some((r) => r.truncated), configuration: { rows: rowFields, columns: columnFields, measures: configs } });
    } catch (e) { setError(errorMessage(e)); setPivot(null); }
    finally { setBusy(false); }
  }

  function savePivotView() {
    if (!pivot) return;
    const name = viewName.trim() || `Pivot view ${savedPivots.length + 1}`;
    setSavedPivots((v) => [...v, { id: makeId(), name, result: pivot, savedAt: new Date().toLocaleTimeString() }]);
    setViewName(`Pivot view ${savedPivots.length + 2}`);
  }

  function exportPivot() {
    if (!pivot) return;
    const escape = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
    const csv = [pivot.columns.map(escape).join(","), ...pivot.rows.map((r) => pivot.columns.map((c) => escape(r[c])).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a"); a.href = url; a.download = `${dataset.name.replace(/[^a-z0-9-_]/gi, "_")}_pivot.csv`; a.click(); URL.revokeObjectURL(url);
  }

  function ask() {
    const q = question.trim().toLowerCase();
    if (!q) return;
    const numericStats = analysis?.numeric_summary || [];
    const categories = analysis?.category_summary || [];
    const match = [...numericStats, ...categories].find((x) => q.includes(x.column.toLowerCase()));
    if (/missing|null|blank|empty/.test(q)) {
      const missing = analysis?.data_quality?.missing_by_column || [];
      setAnswer({ title: "Missing-value review", body: missing.length ? missing.filter((x) => x.missing > 0).map((x) => `${x.column}: ${x.missing} missing (${x.pct}%).`).join(" ") : "No missing values were found in the current dataset snapshot.", caveat: "Deterministic summary of the current profile; inspect affected records before choosing a treatment." }); return;
    }
    if (match && "mean" in match) {
      setAnswer({ title: `${match.column} · descriptive summary`, body: `There are ${match.count} non-empty values and ${match.missing} missing values. Mean ${Number(match.mean).toLocaleString()}, median ${Number(match.median).toLocaleString()}, minimum ${Number(match.min).toLocaleString()}, maximum ${Number(match.max).toLocaleString()}.`, caveat: "Descriptive statistics do not explain causes. Validate units and business definitions before acting." }); return;
    }
    if (match && match.top_values) {
      setAnswer({ title: `${match.column} · category mix`, body: match.top_values.slice(0, 5).map((v) => `${v.value}: ${v.count} records (${v.share_pct}%).`).join(" "), caveat: "Category share uses all dataset rows as the denominator." }); return;
    }
    const finding = (analysis?.findings || []).find((f) => q.split(/\W+/).some((word) => word.length > 3 && `${f.title} ${f.evidence} ${f.interpretation}`.toLowerCase().includes(word)));
    if (finding) setAnswer({ title: finding.title, body: `${finding.evidence} ${finding.interpretation}`, caveat: "This finding is generated from descriptive evidence in the current dataset." });
    else setAnswer({ title: "I need a more specific question", body: `Try asking about a column name, missing values, a category distribution, or one of these measures: ${numericStats.slice(0, 6).map((x) => x.column).join(", ") || "no numeric fields detected"}.`, caveat: "The built-in assistant uses deterministic dataset summaries. A connected language-model provider is not configured in this release." });
  }

  return <section className="modeling-workbench stack">
    <div className="card modeling-hero"><div><span className="eyebrow">DATA MODELING STUDIO</span><h3>Explore the data like a spreadsheet analyst</h3><p className="muted small">Build multi-dimensional summaries, compare several measures and save reusable pivot views. Explorations never modify source records.</p></div><span className="modeling-orb">▦</span></div>
    <section className="card relationship-explorer">
      <div className="row between wrap">
        <div><div className="panel-kicker">RELATIONSHIP EXPLORER</div><h3>Which measures move together?</h3>
          <p className="muted small">Pairwise Pearson correlations using records with values in both fields. This identifies linear association, not cause and effect.</p></div>
        <button className="btn btn-outline" onClick={loadRelationships} disabled={relationshipBusy || numeric.length < 2}>{relationshipBusy ? "Calculating…" : relationships ? "Refresh relationships" : "Calculate relationships →"}</button>
      </div>
      {numeric.length < 2 && <p className="muted small">At least two numeric columns are needed for this analysis.</p>}
      {relationshipError && <p className="error">{relationshipError}</p>}
      {relationships && <div className="relationship-results">
        {relationships.pairs?.length ? <div className="relationship-table-wrap"><table className="relationship-table">
          <thead><tr><th>Measure A</th><th>Measure B</th><th>Correlation</th><th>Association</th><th>Complete records</th></tr></thead>
          <tbody>{relationships.pairs.slice(0, 30).map((pair) => <tr key={`${pair.x}-${pair.y}`}>
            <td>{pair.x}</td><td>{pair.y}</td><td><strong>{pair.correlation > 0 ? "+" : ""}{pair.correlation.toFixed(3)}</strong></td>
            <td><span className={`relationship-direction ${pair.direction}`}>{pair.strength} {pair.direction}</span></td><td>{pair.sample_count.toLocaleString()}</td>
          </tr>)}</tbody>
        </table></div> : <p className="muted small">{relationships.message || "No eligible numeric pairs were found. Each pair needs at least three complete records and variation in both fields."}</p>}
        <p className="muted tiny">{relationships.method}. {relationships.caveat} {relationships.truncated ? "The result is capped to the first 40 numeric fields and 200 pairs." : ""}</p>
      </div>}
    </section>
    <div className="grid workflow-two-col">
      <section className="card pivot-builder">
        <div className="row between wrap"><div><div className="panel-kicker">PIVOT TABLE BUILDER</div><h3>Summarise by dimensions</h3><p className="muted small">Add or remove fields to shape the table. Use multiple measures for side-by-side comparisons.</p></div><span className="badge">Max 4 dimensions</span></div>
        <div className="pivot-axis-grid">
          <div className="pivot-axis"><div className="row between"><strong>Rows</strong><span className="badge">{rowFields.length} selected</span></div><div className="pivot-chip-list">{rowFields.map((field) => <span className="pivot-field-chip" key={field}>{field}<button aria-label={`Remove ${field} row`} onClick={() => setRowFields((v) => v.filter((x) => x !== field))}>×</button></span>)}</div><div className="row pivot-add-control"><select aria-label="Add row field" value={rowChoice} onChange={(e) => setRowChoice(e.target.value)}><option value="">Choose a field…</option>{availableRows.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select><button className="btn btn-outline small" onClick={addRowField} disabled={!rowChoice || selectedDimensions.length >= 4}>＋ Add</button></div></div>
          <div className="pivot-axis"><div className="row between"><strong>Columns</strong><span className="badge">{columnFields.length} selected</span></div><div className="pivot-chip-list">{columnFields.map((field) => <span className="pivot-field-chip teal" key={field}>{field}<button aria-label={`Remove ${field} column`} onClick={() => setColumnFields((v) => v.filter((x) => x !== field))}>×</button></span>)}</div><div className="row pivot-add-control"><select aria-label="Add column field" value={columnChoice} onChange={(e) => setColumnChoice(e.target.value)}><option value="">Choose a field…</option>{availableColumns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select><button className="btn btn-outline small" onClick={addColumnField} disabled={!columnChoice || selectedDimensions.length >= 4}>＋ Add</button></div></div>
        </div>
        <div className="pivot-measures"><div className="row between wrap"><strong>Values / measures</strong><span className="muted small">{measures.length} of 4</span></div>{measures.map((m, i) => <div className="pivot-measure-row" key={m.id}><label>Measure {i + 1}<select value={m.field} onChange={(e) => updateMeasure(m.id, { field: e.target.value })}><option value="">Count records</option>{numeric.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select></label><label>Aggregation<select value={m.aggregation} onChange={(e) => updateMeasure(m.id, { aggregation: e.target.value })}>{["sum", "mean", "median", "count", "min", "max"].map((v) => <option key={v} value={v}>{v[0].toUpperCase()+v.slice(1)}</option>)}</select></label><button className="btn btn-ghost small pivot-remove" onClick={() => setMeasures((v) => v.filter((x) => x.id !== m.id))} disabled={measures.length === 1} title="Remove measure">Remove</button></div>)}<div className="row between wrap"><button className="btn btn-outline small" onClick={addMeasure} disabled={measures.length >= 4 || (!measureChoice && numeric.length > 0)}>＋ Add measure</button><span className="muted tiny">Up to 4 measures per pivot</span></div></div>
        <div className="pivot-guidance"><strong>Suggested analysis workflow</strong><span>Start with a business segment (region, category or product), add a numeric measure, compare Sum with Average, then add a second dimension to investigate the differences. Use IDs only when you need record- or customer-level detail.</span></div>
        {highCardinality && <div className="pivot-guidance warning"><strong>Analyst tip: high-cardinality dimension</strong><span>You selected an ID-like field. This can create hundreds of groups. For an executive summary, try region, category or product first; use customer IDs for customer-level investigation.</span></div>}
        <div className="row wrap pivot-actions"><button className="btn" onClick={buildPivot} disabled={busy || !selectedDimensions.length}>{busy ? "Building pivot…" : "Generate pivot table →"}</button><button className="btn btn-outline" onClick={() => { setPivot(null); setError(""); }}>Clear result</button><button className="btn btn-outline" onClick={() => { setRowFields([categorical.find((c) => !/(^id$|_id$|id$|customer|account|email)/i.test(c.name))?.name || categorical[0]?.name || dataset.schema[0]?.name || ""]); setColumnFields([]); setMeasures([{ id: makeId(), field: numeric[0]?.name || "", aggregation: "sum" }]); setPivot(null); setPivotSearch(""); setError(""); setViewName(`Pivot view ${savedPivots.length + 1}`); }}>＋ New pivot view</button><button className="btn btn-ghost" onClick={() => { setRowFields([]); setColumnFields([]); setMeasures([{ id: makeId(), field: numeric[0]?.name || "", aggregation: "sum" }]); setPivot(null); setError(""); }}>Reset builder</button></div>
        {error && <p className="error">{error}</p>}
        {pivot && <div className="pivot-result"><div className="row between wrap"><div><strong>Pivot result</strong><p className="muted tiny">{pivot.rows.length.toLocaleString()} rows shown · {pivot.columns.length} columns</p></div><span className="badge">{pivot.row_count.toLocaleString()} groups</span></div><div className="row between wrap pivot-result-tools"><input aria-label="Filter pivot rows" value={pivotSearch} onChange={(e) => setPivotSearch(e.target.value)} placeholder="Filter results…"/><div className="row wrap"><input className="pivot-view-name" value={viewName} onChange={(e) => setViewName(e.target.value)} aria-label="Saved pivot view name"/><button className="btn btn-outline small" onClick={savePivotView}>＋ Save view</button><button className="btn btn-outline small" onClick={exportPivot}>↓ Export CSV</button></div></div><div className="pivot-scroll" role="region" aria-label="Pivot table results" tabIndex="0"><table className="pivot-table"><thead><tr>{pivot.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>{pivot.rows.filter((r) => !pivotSearch || pivot.columns.some((c) => String(r[c] ?? "").toLowerCase().includes(pivotSearch.toLowerCase()))).map((r, i) => <tr key={i}>{pivot.columns.map((c) => <td key={c}>{typeof r[c] === "number" ? r[c].toLocaleString(undefined,{maximumFractionDigits:2}) : String(r[c] ?? "—")}</td>)}</tr>)}</tbody></table></div>{pivot.truncated && <p className="muted small">Showing up to 500 groups. Refine dimensions or filters to narrow the result.</p>}</div>}
        {savedPivots.length > 0 && <section className="saved-pivots"><div className="row between"><strong>Saved pivot views</strong><span className="badge">{savedPivots.length}</span></div><p className="muted tiny">Saved in this workspace session. Export CSV to retain results outside the current session.</p><div className="saved-pivot-list">{savedPivots.map((view) => <article key={view.id}><button className="saved-pivot-open" onClick={() => { setPivot(view.result); setViewName(view.name); setPivotSearch(""); }}>{view.name}<small>{view.result.row_count} groups · {view.savedAt}</small></button><button className="btn btn-ghost small" title={`Delete ${view.name}`} onClick={() => setSavedPivots((v) => v.filter((x) => x.id !== view.id))}>Remove</button></article>)}</div></section>}
      </section>
      <section className="card copilot-panel"><div className="panel-kicker">INSIGHT ASSISTANT · DATA-GROUNDED</div><h3>Ask about this dataset</h3><p className="muted small">Ask about a field, missing values or a finding. Answers are calculated from the dataset profile and analysis results.</p><div className="assistant-prompts">{["Which columns have missing values?", `Summarise ${numeric[0]?.name || "the numeric measures"}`, `What is the distribution of ${categorical[0]?.name || "categories"}?`].map((p) => <button className="prompt-chip" key={p} onClick={() => setQuestion(p)}>{p}</button>)}</div><div className="row assistant-input"><input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()} placeholder="Ask about revenue, ratings, missing values…"/><button className="btn" onClick={ask}>Ask</button></div>{answer && <article className="assistant-answer"><strong>{answer.title}</strong><p>{answer.body}</p><small>{answer.caveat}</small></article>}<div className="assistant-footnote">No external AI service is connected. Responses are deterministic and auditable.</div></section>
    </div>
  </section>;
}
