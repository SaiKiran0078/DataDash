import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api, { errorMessage } from "../api/client.js";
import CleaningStudio from "../components/CleaningStudio.jsx";
import ChartCard from "../components/ChartCard.jsx";
import ChartBuilder from "../components/ChartBuilder.jsx";
import FilterBar from "../components/FilterBar.jsx";
import DataTable from "../components/DataTable.jsx";
import ModelingWorkbench from "../components/ModelingWorkbench.jsx";
import { fmt, KIND_LABEL } from "../utils.js";

const STAGES = [
  ["01", "Understand", "Frame the question and inspect the data", "◈"],
  ["02", "Prepare", "Improve quality without losing context", "⌁"],
  ["03", "Analyze", "Find patterns, exceptions and relationships", "⌗"],
  ["04", "Visualize", "Choose the right evidence for the question", "▥"],
  ["05", "Story", "Write findings and recommendations", "✎"],
  ["06", "Deliver", "Publish a report and dashboard", "↗"],
];

const safe = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const businessOnly = (items = []) => items.filter((item) =>
  !/missing data|missing values|duplicate rows|duplicate records|data[- ]quality|parse error|outlier|type conversion|empty cells/i
    .test(String(item.title || "")));


export default function AnalystWorkflow() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [dataset, setDataset] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [stage, setStage] = useState(() => { try { return Number(sessionStorage.getItem("datadash:workflow-stage:" + id)) || 0; } catch { return 0; } });
  const [hiddenSuggestionIds, setHiddenSuggestionIds] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [chartData, setChartData] = useState({});
  const firstCategory = useMemo(() => dataset?.schema?.find((c) => ["categorical", "boolean"].includes(c.kind)) || dataset?.schema?.find((c) => c.kind !== "id"), [dataset]);
  const [customSpec, setCustomSpec] = useState(null);
  const [customFilters, setCustomFilters] = useState([]);
  const [customChart, setCustomChart] = useState(null);
  const [reports, setReports] = useState([]);
  const [reportId, setReportId] = useState(null);
  const [reportInitialized, setReportInitialized] = useState(false);
  const [reportsLoaded, setReportsLoaded] = useState(false);
  const [title, setTitle] = useState("Data analysis report");
  const [businessQuestion, setBusinessQuestion] = useState("");
  const [audience, setAudience] = useState("Business stakeholders");
  const [rowGrain, setRowGrain] = useState("");
  const [summary, setSummary] = useState("");
  const [findings, setFindings] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [dashboards, setDashboards] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setError("");
    setReportsLoaded(false);
    // Paint the workspace as soon as the small dataset metadata response arrives.
    try {
      const d = await api.get(`/datasets/${id}`);
      setDataset(d.data);
      setTitle(`${d.data.name} — Analysis report`);
      setSummary(`This analysis reviews ${d.data.profile.rows.toLocaleString("en-IN")} records across ${d.data.profile.columns} fields to identify business performance, opportunities and practical next steps.`);
    } catch (e) {
      setError(errorMessage(e));
      return;
    }

    // Independent, non-blocking requests: optional reports and dashboard lists must
    // never hold the analysis workspace or its KPI/quality cards behind them.
    const tasks = [
      api.get(`/datasets/${id}/analysis`).then((r) => {
        setAnalysis(r.data);
        setFindings(r.data.business_insights || []);
        setRecommendations(r.data.recommendations || []);
      }).catch((e) => setError(errorMessage(e))),
    ];
    await Promise.allSettled(tasks);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // Load stage-specific supporting data only when the analyst reaches that stage.
  // This keeps the first workspace view focused on the dataset and its core analysis.
  useEffect(() => {
    if (stage !== 3 || suggestions.length || !dataset) return;
    let live = true;
    api.get(`/datasets/${id}/suggestions`)
      .then((r) => { if (live) setSuggestions(r.data.suggestions || []); })
      .catch(() => { if (live) setSuggestions([]); });
    return () => { live = false; };
  }, [id, stage, dataset, suggestions.length]);

  useEffect(() => {
    if (stage !== 4 || reportsLoaded) return;
    let live = true;
    api.get(`/datasets/${id}/reports`)
      .then((r) => { if (live) { setReports(r.data.reports || []); setReportsLoaded(true); } })
      .catch(() => { if (live) setReportsLoaded(true); });
    return () => { live = false; };
  }, [id, stage, reportsLoaded]);

  useEffect(() => {
    if (stage !== 5 || dashboards.length) return;
    let live = true;
    api.get("/dashboards").then((r) => { if (live) setDashboards(r.data.dashboards || []); })
      .catch(() => { if (live) setDashboards([]); });
    return () => { live = false; };
  }, [stage, dashboards.length]);

  // Chart previews are deliberately deferred until the Visualize stage is opened.
  // This removes up to six chart requests from the critical workspace-load path.
  useEffect(() => {
    if (stage !== 3 || !suggestions.length) return;
    let live = true;
    const missing = suggestions.filter((item) => !chartData[item.id]).slice(0, 6);
    if (!missing.length) return;
    Promise.all(missing.map(async (item) => {
      try { return [item.id, (await api.post(`/datasets/${id}/chart`, { spec: item.spec, filters: [] })).data]; }
      catch (e) { return [item.id, { error: errorMessage(e) }]; }
    })).then((entries) => {
      if (live) setChartData((current) => ({ ...current, ...Object.fromEntries(entries) }));
    });
    return () => { live = false; };
  }, [id, stage, suggestions, chartData]);
  useEffect(() => { try { sessionStorage.setItem("datadash:workflow-stage:" + id, String(stage)); } catch { /* unavailable */ } }, [id, stage]);
  useEffect(() => { window.scrollTo({ top: 0, left: 0, behavior: "instant" }); }, [stage]);
  useEffect(() => { setCustomSpec(null); setCustomFilters([]); setCustomChart(null); setHiddenSuggestionIds([]); }, [id]);

  useEffect(() => {
    if (firstCategory?.name && !customSpec) setCustomSpec({ type: "bar", x: firstCategory.name, agg: "count" });
  }, [firstCategory, customSpec]);

  useEffect(() => {
    if (!customSpec?.x || !dataset) return;
    const timer = setTimeout(() => api.post(`/datasets/${id}/chart`, { spec: customSpec, filters: customFilters })
      .then((r) => setCustomChart(r.data)).catch((e) => setCustomChart({ error: errorMessage(e) })), 220);
    return () => clearTimeout(timer);
  }, [id, dataset, customSpec, customFilters]);

  useEffect(() => {
    if (!reportsLoaded || reportInitialized) return;
    if (reports.length) {
      const newest = reports[0];
      setReportId(newest.id); setTitle(newest.title); setBusinessQuestion(newest.business_question || ""); setAudience(newest.audience || "Business stakeholders"); setRowGrain(newest.row_grain || ""); setSummary(newest.executive_summary || "");
      setFindings(businessOnly(newest.findings || [])); setRecommendations(businessOnly(newest.recommendations || []));
    }
    setReportInitialized(true);
  }, [reports, reportsLoaded, reportInitialized]);

  const qualityIssueCount = analysis?.data_quality?.issue_count ?? analysis?.data_quality?.issues?.length ?? 0;
  const completeness = analysis?.dataset
    ? Math.max(0, Math.min(100, 100 - Number(analysis.dataset.missing_pct || 0)))
    : null;

  async function refreshAfterClean(updated) {
    setDataset(updated);
    await load();
    setNotice("Dataset profile and analyst findings refreshed from the cleaned version.");
  }

  async function saveReport() {
    setBusy(true); setError(""); setNotice("");
    const body = { title, business_question: businessQuestion, audience, row_grain: rowGrain, executive_summary: summary, findings, recommendations };
    try {
      const response = reportId
        ? await api.put(`/datasets/${id}/reports/${reportId}`, body)
        : await api.post(`/datasets/${id}/reports`, body);
      setReportId(response.data.id);
      const all = (await api.get(`/datasets/${id}/reports`)).data.reports;
      setReports(all); setNotice("Report saved to your DataDash workspace.");
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  async function loadReport(report) {
    if (!report) return;
    setReportId(report.id); setTitle(report.title); setBusinessQuestion(report.business_question || ""); setAudience(report.audience || "Business stakeholders"); setRowGrain(report.row_grain || ""); setSummary(report.executive_summary || "");
    setFindings(businessOnly(report.findings || [])); setRecommendations(businessOnly(report.recommendations || []));
    setNotice(`Loaded report: ${report.title}`);
  }

  function newDraft() {
    setReportId(null); setTitle(`${dataset.name} — Analysis report`); setBusinessQuestion(""); setAudience("Business stakeholders"); setRowGrain("");
    setSummary(`This analysis reviews ${dataset.profile.rows.toLocaleString("en-IN")} records across ${dataset.profile.columns} fields to identify business performance, opportunities and practical next steps.`);
    setFindings(analysis.business_insights || []); setRecommendations(analysis.recommendations || []); setNotice("Started a new report draft.");
  }

  async function deleteCurrentReport() {
    if (!reportId || !window.confirm("Delete this saved report?")) return;
    try { await api.delete(`/datasets/${id}/reports/${reportId}`); setReports((items) => items.filter((r) => r.id !== reportId)); newDraft(); setNotice("Saved report deleted."); }
    catch (e) { setError(errorMessage(e)); }
  }

  async function runFullAnalystPipeline() {
    if (!dataset) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api.post(`/datasets/${id}/auto-build`, {
        business_question: businessQuestion,
        audience,
        row_grain: rowGrain,
        apply_safe_text_trim: true,
      });
      setNotice(`Analysis completed: ${result.data.dashboard.widgets} visuals across ${result.data.dashboard.pages.length} pages; ${result.data.report.title} saved.`);
      navigate(`/dashboards/${result.data.dashboard.id}`, { state: { autoRun: result.data } });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function createDashboard() {
    if (!suggestions.length) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const widgets = suggestions.slice(0, 8).map((s, index) => ({
        id: `auto-${index + 1}`, title: s.title.slice(0, 120), spec: s.spec, filters: [],
      }));
      const dashboardName = `${dataset.name} — Insight dashboard`;
      const existing = dashboards.find((d) => d.dataset_id === Number(id) && d.name === dashboardName);
      const payload = { name: dashboardName, dataset_id: Number(id), widgets, filters: [] };
      const result = existing ? await api.put(`/dashboards/${existing.id}`, payload) : await api.post("/dashboards", payload);
      setDashboards((items) => [result.data, ...items.filter((d) => d.id !== result.data.id)]);
      setNotice(`${existing ? "Updated" : "Created"} a dashboard with ${widgets.length} analyst-recommended charts.`);
      setStage(5);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  function exportReport() {
    const body = `<!doctype html><html><head><meta charset="utf-8"><title>${safe(title)}</title><style>body{font:15px/1.65 Inter,Arial,sans-serif;max-width:900px;margin:50px auto;padding:0 24px;color:#172033}h1,h2{color:#27265a}h1{font-size:32px}h2{margin-top:32px;border-bottom:1px solid #ddd;padding-bottom:8px}.meta{color:#64748b}.item{padding:14px 0;border-bottom:1px solid #e5e7eb}.tag{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#655be0;font-weight:bold}footer{margin-top:40px;color:#64748b;font-size:12px}</style></head><body><div class="tag">DATADASH · INSIGHT STUDIO</div><h1>${safe(title)}</h1><p class="meta">Dataset: ${safe(dataset?.name)} · Audience: ${safe(audience)} · Grain: ${safe(rowGrain || "Not specified")} · ${new Date().toLocaleString()}</p><h2>Business question</h2><p>${safe(businessQuestion || "Not specified")}</p><h2>Executive summary</h2><p>${safe(summary).replace(/\n/g,"<br>")}</p><h2>Key findings</h2>${findings.map((f) => `<div class="item"><strong>${safe(f.title)}</strong><p>${safe(f.evidence)}</p><p>${safe(f.impact || f.interpretation)}</p>${f.action ? `<p><b>Next step:</b> ${safe(f.action)}</p>` : ""}</div>`).join("")}<h2>Recommendations</h2>${recommendations.map((r) => `<div class="item"><strong>${safe(r.title)}</strong><p>${safe(r.action)}</p><p class="meta">Priority: ${safe(r.priority || "Not set")}</p></div>`).join("")}<footer>Generated in DataDash Insight Studio. Findings are descriptive; validate business definitions and assumptions before acting.</footer></body></html>`;
    const blob = new Blob([body], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob); const a = document.createElement("a");
    a.href = url; a.download = `${(title || "analysis-report").replace(/[^a-z0-9_-]/gi, "_")}.html`; a.click(); URL.revokeObjectURL(url);
  }

  function updateItem(setter, index, key, value) {
    setter((items) => items.map((item, i) => i === index ? { ...item, [key]: value } : item));
  }

  if (error && !dataset) return <div className="card"><p className="error">{error}</p><Link to="/">Back to workspace</Link></div>;
  if (!dataset) return <div className="workflow-loading"><span className="pulse-orb"/> Opening your dataset workspace…</div>;
  if (!analysis) return <div className="analyst-workspace">
    <div className="workflow-topline"><Link to="/" className="muted small">← Dataset library</Link><span className="live-indicator">WORKSPACE LIVE</span></div>
    <header className="workflow-hero"><div><span className="eyebrow">DATADASH / ANALYST WORKSPACE</span><h1>{dataset.name}</h1><p>Your dataset is ready. Analytical quality checks and findings are loading separately.</p></div><div className="hero-orbit"><span>DD</span><i/><b/></div></header>
    <div className="grid stats workflow-metrics">
      <Metric label="Records" value={fmt(dataset.profile.rows)} detail="Rows in current snapshot" tone="violet" />
      <Metric label="Fields" value={dataset.profile.columns} detail="Detected columns" tone="cyan" />
    </div>
    <div className="card workflow-loading">
      {error ? <><strong>Analysis could not finish.</strong><p className="error workflow-alert">{error}</p><button className="btn" onClick={load}>Retry analysis</button></> : <><span className="pulse-orb"/> Calculating data quality, KPIs and analyst findings…<p className="muted small">The analysis runs once for this dataset version and is reused when you reopen the workspace or dashboard.</p></>}
    </div>
  </div>;

  async function exportCsv() {
    try { const r = await api.get(`/datasets/${id}/export`, { responseType: "blob" }); const url = URL.createObjectURL(r.data); const a = document.createElement("a"); a.href = url; a.download = `${dataset.name.replace(/[^a-z0-9_-]/gi, "_")}_cleaned.csv`; a.click(); URL.revokeObjectURL(url); } catch (e) { setError(errorMessage(e)); }
  }

  return <div className="analyst-workspace">
    <div className="workflow-topline"><Link to="/" className="muted small">← Dataset library</Link><div className="row wrap"><span className="live-indicator">WORKSPACE LIVE</span><button className="btn btn-outline small" onClick={exportCsv}>↓ Export cleaned CSV</button></div></div>
    <header className="workflow-hero">
      <div><span className="eyebrow">DATADASH / ANALYST WORKSPACE</span><h1>{dataset.name}</h1><p>Your dataset, preparation tools, analysis, charts and reporting — connected in one continuous workspace.</p></div>
      <div className="hero-orbit"><span>DD</span><i/><b/></div>
    </header>

    <nav className="workflow-stepper" aria-label="Analyst workflow stages">
      {STAGES.map(([number, name, desc, icon], index) => <button key={name} className={`workflow-step ${stage === index ? "active" : ""} ${stage > index ? "complete" : ""}`} onClick={() => setStage(index)}>
        <span className="workflow-step-icon">{stage > index ? "✓" : icon}</span><span className="workflow-step-copy"><small>{number}</small><strong>{name}</strong><em>{desc}</em></span>
      </button>)}
    </nav>

    {error && <p className="error workflow-alert">{error}</p>}{notice && <p className="workflow-notice">✦ {notice}</p>}

    {stage === 0 && <section className="workflow-stage">
      <StageHeading number="01" title="Understand the data" subtitle="Start with context. Confirm what one row represents, what each field means, and what decision this analysis should support." />
      <div className="grid stats workflow-metrics">
        <Metric label="Records" value={fmt(analysis.dataset.rows)} detail="Rows in current snapshot" tone="violet" />
        <Metric label="Fields" value={analysis.dataset.columns} detail="Detected columns" tone="cyan" />
        <Metric label="Completeness" value={`${completeness.toFixed(2)}%`} detail={`${fmt(analysis.dataset.missing_cells)} empty cells · ${fmt(analysis.dataset.rows * analysis.dataset.columns)} total cells`} tone="amber" />
        <Metric label="Quality issues" value={fmt(qualityIssueCount)} detail="Detected items to review in Prepare" tone="pink" />
      </div>
      <section className="card quality-overview-panel">
        <div className="row between wrap"><div><div className="panel-kicker">DATA QUALITY DIAGNOSTICS</div><h3>What needs attention?</h3><p className="muted small">Issues are detected from the current dataset. Each finding includes affected fields, sample row numbers and a suggested treatment.</p></div><span className="count-pill">{analysis.data_quality?.issue_count || 0} issues</span></div>
        {analysis.data_quality?.issues?.length ? <div className="quality-issue-grid">{analysis.data_quality.issues.slice(0, 8).map((issue) => <article className="quality-issue-card" key={issue.id}><div className="row between"><span className={`finding-severity severity-${issue.severity}`}>{issue.severity}</span><span className="muted small">{issue.column || issue.type}</span></div><strong>{issue.title}</strong><p>{issue.suggestion}</p>{issue.sample_rows?.length > 0 && <small>Sample record positions (1-based; header excluded): {issue.sample_rows.join(", ")}</small>}</article>)}</div> : <div className="empty-state compact"><strong>No material data-quality issues detected</strong><p className="muted small">Continue with business context and metric validation.</p></div>}
        {analysis.data_quality?.missing_by_column?.length > 0 && <div className="quality-missing-table"><h4>Missing-value breakdown by column</h4><div className="table-wrap"><table><thead><tr><th>Column</th><th>Missing</th><th>Share of rows</th><th>Suggested treatment</th><th>Sample record positions</th></tr></thead><tbody>{analysis.data_quality.missing_by_column.map((m) => <tr key={m.column}><td><strong>{m.column}</strong></td><td>{fmt(m.missing)}</td><td>{m.pct}%</td><td>{m.suggested_strategy === "review" ? "Manual review" : m.suggested_strategy}</td><td>{m.sample_rows.join(", ")}</td></tr>)}</tbody></table></div></div>}
        <div className="row between wrap"><p className="helper-text">Review these findings before choosing a cleaning rule. Recommendations are suggestions, not automatic edits.</p><button className="btn" onClick={() => setStage(1)}>Review fixes in Prepare →</button></div>
      </section>
      <div className="grid workflow-two-col">
        <section className="card glass-panel"><div className="panel-kicker">01 / BUSINESS CONTEXT</div><h3>Questions an analyst should ask</h3><ul className="question-list">{analysis.analyst_questions.map((q, i) => <li key={i}><span>{String(i + 1).padStart(2, "0")}</span>{q}</li>)}</ul><p className="helper-text">Before charting, write down the business question, target audience, metric definitions and expected grain of the analysis.</p></section>
        <section className="card glass-panel"><div className="panel-kicker">02 / FIELD INVENTORY</div><h3>Data dictionary snapshot</h3><div className="field-inventory">{dataset.schema.map((col) => <div className="field-row" key={col.name}><span className={`field-type type-${col.kind}`}>{KIND_LABEL[col.kind] || col.kind}</span><strong>{col.name}</strong><span>{fmt(dataset.profile.column_profiles.find((p) => p.name === col.name)?.unique)} unique</span></div>)}</div></section>
      </div>
      <div className="card context-panel"><div><span className="panel-kicker">DEFINE THE ANALYSIS</span><h3>Set the decision context</h3><p className="muted small">A useful analysis starts with a question, an audience and a clear unit of analysis.</p></div><div className="context-fields"><label>Business question<input value={businessQuestion} onChange={(e) => setBusinessQuestion(e.target.value)} placeholder="e.g. What is driving the decline in monthly sales?"/></label><label>Who will use this analysis?<input value={audience} onChange={(e) => setAudience(e.target.value)} placeholder="e.g. Sales leadership"/></label><label>What does one row represent?<input value={rowGrain} onChange={(e) => setRowGrain(e.target.value)} placeholder="e.g. One row per order line"/></label></div><div className="row between wrap"><p className="helper-text">These details will be included in your saved report.</p><div className="row wrap"><button className="btn btn-outline" onClick={() => setStage(1)}>Review preparation →</button><button className="btn" disabled={busy} onClick={runFullAnalystPipeline}>{busy ? "Running analyst pipeline…" : "✦ Run complete analysis & build dashboard"}</button></div></div></div>
      <section className="card integrated-data-panel"><div className="row between wrap"><div><div className="panel-kicker">LIVE DATA GRID</div><h3>Inspect the actual records</h3><p className="muted small">Preview, sort and filter the rows behind your profile before choosing transformations or metrics.</p></div><span className="count-pill">{fmt(dataset.profile.rows)} records</span></div><DataTable datasetId={dataset.id} schema={dataset.schema} /></section>
    </section>}

    {stage === 1 && <section className="workflow-stage">
      <StageHeading number="02" title="Prepare and clean" subtitle="Treat cleaning as a controlled transformation: inspect the issue, choose a business rule, preview the impact, then apply." />
      <div className="prep-checklist"><span>Recommended order</span><b>Profile → Duplicates → Missingness → Consistency → Types → Outliers</b></div>
      <section className="card prep-diagnostics"><div className="row between wrap"><div><div className="panel-kicker">ANALYST REVIEW QUEUE</div><h3>Detected issues and suggested fixes</h3><p className="muted small">Choose a suggested fix to add it to the cleaning queue. Preview the complete sequence before applying.</p></div><span className="count-pill">{analysis.data_quality?.issue_count || 0} findings</span></div>
        {analysis.data_quality?.issues?.length ? <div className="prep-issue-list">{analysis.data_quality.issues.filter((issue) => !hiddenSuggestionIds.includes(String(issue.id))).map((issue) => <article className="prep-issue" key={issue.id}><div className="prep-issue-main"><div className="row wrap"><span className={`finding-severity severity-${issue.severity}`}>{issue.severity}</span><strong>{issue.title}</strong></div><p>{issue.suggestion}</p>{issue.sample_rows?.length > 0 && <small>Example record positions (1-based; header excluded): {issue.sample_rows.join(", ")}</small>}</div>{issue.recommended_operation ? <button className="btn btn-outline small" onClick={() => window.dispatchEvent(new CustomEvent("datadash:add-clean-step", { detail: { operation: issue.recommended_operation, suggestionId: String(issue.id) } }))}>＋ Add suggested step</button> : <span className="muted small">Review manually</span>}</article>)}</div> : <p className="success-banner">No outstanding quality issues detected in this snapshot.</p>}
      </section>
      <CleaningStudio dataset={dataset} onApplied={refreshAfterClean} qualityIssues={analysis.data_quality?.issues || []} onSuggestionVisibilityChange={(suggestionId, hidden) => setHiddenSuggestionIds((items) => hidden ? [...new Set([...items, suggestionId])] : items.filter((item) => item !== suggestionId))} />
    </section>}

    {stage === 2 && <section className="workflow-stage">
      <StageHeading number="03" title="Analyze and investigate" subtitle="Move beyond totals. Compare distributions, segments, relationships and unusual records. The findings below are computed from this dataset." />
      <div className="grid workflow-two-col">
        <section className="card glass-panel"><div className="panel-kicker">NUMERIC EXPLORATION</div><h3>Measure summary</h3><div className="table-wrap"><table><thead><tr><th>Measure</th><th>Average</th><th>Median</th><th>Min</th><th>Max</th><th>Std dev</th></tr></thead><tbody>{analysis.numeric_summary.map((x) => <tr key={x.column}><td><strong>{x.column}</strong></td><td>{fmt(x.mean)}</td><td>{fmt(x.median)}</td><td>{fmt(x.min)}</td><td>{fmt(x.max)}</td><td>{fmt(x.std)}</td></tr>)}</tbody></table></div></section>
        <section className="card glass-panel"><div className="panel-kicker">SEGMENT EXPLORATION</div><h3>Category mix</h3>{analysis.category_summary.slice(0, 5).map((cat) => <div className="category-insight" key={cat.column}><div className="row between"><strong>{cat.column}</strong><span className="muted small">{cat.unique} groups</span></div>{cat.top_values.slice(0, 4).map((v) => <div className="mix-row" key={v.value}><span>{v.value}</span><div><i style={{ width: `${v.share_pct}%` }}/></div><b>{v.share_pct}%</b></div>)}</div>)}</section>
      </div>
      <section className="card deep-analysis-panel"><div className="panel-kicker">DISTRIBUTION & EXCEPTION ANALYSIS</div><h3>How are the numeric measures behaving?</h3><p className="muted small">Quartiles, skew and outlier counts help distinguish typical values from unusually large or small observations.</p><div className="table-wrap"><table><thead><tr><th>Measure</th><th>Q1</th><th>Median</th><th>Q3</th><th>Skew</th><th>Negatives</th><th>Zeros</th></tr></thead><tbody>{analysis.numeric_summary.map((x) => <tr key={x.column}><td><strong>{x.column}</strong></td><td>{fmt(x.q1)}</td><td>{fmt(x.median)}</td><td>{fmt(x.q3)}</td><td>{fmt(x.skew)}</td><td>{fmt(x.negative_count)}</td><td>{fmt(x.zero_count)}</td></tr>)}</tbody></table></div><div className="analysis-callouts">{analysis.numeric_summary.slice(0, 8).map((x) => <article key={x.column}><strong>{x.column}</strong><p>{Math.abs(x.skew) >= 1 ? `Highly ${x.skew > 0 ? "right" : "left"}-skewed: the mean may not represent a typical record; compare it with the median.` : Math.abs(x.skew) >= .5 ? "Moderately skewed: compare mean and median when reporting typical performance." : "Relatively balanced distribution by skew; still inspect quartiles and extreme records."}</p>{x.negative_count > 0 && <small>{x.negative_count} negative values need business interpretation.</small>}</article>)}</div></section>
      {analysis.segment_analysis?.length > 0 && <section className="card segment-analysis-panel"><div className="panel-kicker">SEGMENT PERFORMANCE</div><h3>Which groups contribute, and which perform differently?</h3><p className="muted small">Compare totals with averages. Large segments naturally contribute more total volume; averages help compare typical performance.</p><div className="segment-analysis-grid">{analysis.segment_analysis.slice(0, 6).map((item) => <article key={`${item.category}-${item.measure}`}><div className="row between"><strong>{item.category}</strong><span className="muted small">{item.measure}</span></div><div className="table-wrap"><table><thead><tr><th>Group</th><th>Rows</th><th>Total</th><th>Average</th></tr></thead><tbody>{item.groups.map((g) => <tr key={g.value}><td>{g.value}</td><td>{fmt(g.count)}</td><td>{fmt(g.sum)}</td><td>{fmt(g.mean)}</td></tr>)}</tbody></table></div></article>)}</div></section>}
      {analysis.time_series?.some((x) => x.periods.length) && <section className="card time-analysis-panel"><div className="panel-kicker">TIME-BASED ANALYSIS</div><h3>Monthly movement</h3><p className="muted small">Monthly totals and averages are calculated from {analysis.time_series[0].date_column}. Review incomplete date coverage before comparing periods.</p>{analysis.time_series.filter((x) => x.periods.length).slice(0, 3).map((series) => <div className="time-series-block" key={series.measure}><h4>{series.measure}</h4><div className="table-wrap"><table><thead><tr><th>Month</th><th>Records</th><th>Total</th><th>Average</th></tr></thead><tbody>{series.periods.map((p) => <tr key={p.period}><td>{p.period}</td><td>{fmt(p.count)}</td><td>{fmt(p.sum)}</td><td>{fmt(p.mean)}</td></tr>)}</tbody></table></div></div>)}</section>}
      <section className="card glass-panel"><div className="panel-kicker">RELATIONSHIP CHECK</div><h3>Strongest numeric correlations</h3><p className="muted small">Pearson correlation identifies linear association only. It does not prove causation.</p>{analysis.correlations.filter((x) => Math.abs(x.correlation) >= .3).slice(0, 8).map((c) => <div className="correlation-row" key={`${c.left}-${c.right}`}><span>{c.left}</span><div className="correlation-track"><i style={{ width: `${Math.abs(c.correlation) * 100}%` }}/></div><span>{c.right}</span><strong>{c.correlation > 0 ? "+" : ""}{c.correlation.toFixed(2)}</strong></div>)}{!analysis.correlations.length && <p className="muted">At least two numeric columns are needed to calculate correlations.</p>}</section>
      <ModelingWorkbench dataset={dataset} analysis={analysis} />
      <OutlierInspector datasetId={dataset.id} schema={dataset.schema} />
      <section className="card analyst-findings"><div className="panel-kicker">EVIDENCE LED FINDINGS</div><h3>What stands out in this dataset?</h3><div className="finding-grid">{analysis.findings.map((f) => <article className="finding-card" key={f.id}><span className={`finding-severity severity-${f.severity}`}>{f.severity}</span><h4>{f.title}</h4><p><strong>Evidence:</strong> {f.evidence}</p><p>{f.interpretation}</p></article>)}</div></section>
    </section>}

    {stage === 3 && <section className="workflow-stage">
      <StageHeading number="04" title="Visualize the evidence" subtitle="Choose a visual based on the analytical question: trend, comparison, composition, distribution or relationship." />
      <div className="chart-purpose-grid">{[["Trend", "Line", "How does a measure change over time?"], ["Comparison", "Bar", "Which categories are higher or lower?"], ["Composition", "Pie / Bar", "How is the total split?"], ["Distribution", "Histogram", "Where are values concentrated?"], ["Relationship", "Scatter", "Do two numeric measures move together?"]].map(([a,b,c]) => <div className="purpose-card" key={a}><span>{a}</span><strong>{b}</strong><p>{c}</p></div>)}</div>
      <div className="row between wrap"><div><span className="panel-kicker">RECOMMENDED VISUALS</span><h3>Charts suggested from your columns</h3></div><button className="btn" disabled={busy || !suggestions.length} onClick={createDashboard}>{busy ? "Creating…" : "✦ Build recommended dashboard"}</button></div>
      <section className="card custom-explorer"><div className="panel-kicker">BUILD YOUR OWN ANALYSIS</div><h3>Interactive chart explorer</h3><p className="muted small">Choose fields and aggregation, then filter the dataset. Add the resulting chart to a dashboard from the preview.</p>{customSpec && <><ChartBuilder schema={dataset.schema} spec={customSpec} onChange={setCustomSpec}/><FilterBar schema={dataset.schema} filters={customFilters} onChange={setCustomFilters}/><ChartCard title={`${customSpec.type} · ${customSpec.x}${customSpec.y ? ` / ${customSpec.y}` : ""}`} subtitle={customChart?.meta ? `${customChart.meta.filtered_rows.toLocaleString()} filtered records` : "Live chart preview"} type={customSpec.type} data={customChart}><button className="btn btn-outline small" onClick={async () => { try { const title = `${customSpec.type} · ${customSpec.x}`; const r = await api.post("/dashboards", { name: `${dataset.name} — Custom analysis`, dataset_id: dataset.id, widgets: [{ id: `custom-${Date.now()}`, title, spec: customSpec, filters: customFilters }], filters: [] }); setDashboards((items) => [r.data, ...items]); setNotice("Your custom chart has been saved to a new dashboard."); } catch (e) { setError(errorMessage(e)); } }}>＋ Save chart to dashboard</button></ChartCard></>}</section>
      <div className="grid charts">{suggestions.slice(0, 6).map((s) => <ChartCard key={s.id} title={s.title} subtitle={s.reason} type={s.spec.type} data={chartData[s.id]}/>)}</div>
      <p className="helper-text">Recommendations are based on inferred field types and statistical patterns. Confirm the business meaning of each field before publishing.</p>
    </section>}

    {stage === 4 && <section className="workflow-stage">
      <StageHeading number="05" title="Write the story" subtitle="A strong analyst report separates observation, interpretation and action. Edit the generated starting points to reflect business context." />
      <div className="report-editor card glass-panel">
        <div className="row between wrap"><div><div className="panel-kicker">REPORT DRAFT</div><h3>Executive narrative</h3></div><div className="row wrap"><select aria-label="Load saved report" value={reportId || ""} onChange={(e) => e.target.value ? loadReport(reports.find((r) => String(r.id) === e.target.value)) : newDraft()}><option value="">Current draft</option>{reports.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</select><button className="btn btn-outline small" onClick={newDraft}>＋ New report</button>{reportId && <button className="btn btn-ghost small" onClick={deleteCurrentReport}>Delete saved</button>}</div></div>
        <label>Report title<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160}/></label>
        <label>Business question<input value={businessQuestion} onChange={(e) => setBusinessQuestion(e.target.value)} placeholder="What decision should this analysis support?"/></label>
        <div className="context-fields"><label>Audience<input value={audience} onChange={(e) => setAudience(e.target.value)}/></label><label>Unit of analysis / row grain<input value={rowGrain} onChange={(e) => setRowGrain(e.target.value)} placeholder="e.g. One row per invoice line"/></label></div>
        <label>Executive summary<textarea rows="5" value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="What was analysed, what matters most, and what should happen next?"/></label>
        <div className="row between"><h3>Key findings</h3><button className="btn btn-outline small" onClick={() => setFindings((items) => [...items, { id: `manual-${Date.now()}`, title: "New finding", evidence: "Add the supporting metric or observation.", interpretation: "Explain what this could mean and any caveats.", severity: "info" }])}>＋ Add finding</button></div>
        {findings.map((f, i) => <div className="editable-insight" key={f.id || i}><div className="row between"><span className="panel-kicker">FINDING {String(i + 1).padStart(2, "0")}</span><button className="btn btn-ghost small" onClick={() => setFindings((items) => items.filter((_, j) => i !== j))}>Remove</button></div><input value={f.title} onChange={(e) => updateItem(setFindings, i, "title", e.target.value)}/><textarea rows="2" value={f.evidence} onChange={(e) => updateItem(setFindings, i, "evidence", e.target.value)} placeholder="Evidence / metric"/><textarea rows="2" value={f.impact || f.interpretation || ""} onChange={(e) => updateItem(setFindings, i, f.impact ? "impact" : "interpretation", e.target.value)} placeholder="Why this matters to the business"/></div>)}
        <div className="row between"><h3>Recommendations</h3><button className="btn btn-outline small" onClick={() => setRecommendations((items) => [...items, { id: `manual-${Date.now()}`, title: "New recommendation", action: "Describe a practical next step, owner and expected outcome.", priority: "medium" }])}>＋ Add recommendation</button></div>
        {recommendations.map((r, i) => <div className="editable-insight recommendation-editor" key={r.id || i}><div className="row between"><span className="panel-kicker">ACTION {String(i + 1).padStart(2, "0")}</span><button className="btn btn-ghost small" onClick={() => setRecommendations((items) => items.filter((_, j) => i !== j))}>Remove</button></div><input value={r.title} onChange={(e) => updateItem(setRecommendations, i, "title", e.target.value)}/><textarea rows="3" value={r.action} onChange={(e) => updateItem(setRecommendations, i, "action", e.target.value)}/><label>Priority<select value={r.priority || "medium"} onChange={(e) => updateItem(setRecommendations, i, "priority", e.target.value)}><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label></div>)}
        <div className="row wrap"><button className="btn" disabled={busy || !title.trim()} onClick={saveReport}>{busy ? "Saving…" : "Save report"}</button><button className="btn btn-outline" onClick={exportReport}>Export report HTML</button></div>
      </div>
    </section>}

    {stage === 5 && <section className="workflow-stage">
      <StageHeading number="06" title="Deliver and communicate" subtitle="Package the analysis for a decision-maker. Publish a dashboard for exploration and a written report for context, caveats and action." />
      <div className="grid workflow-two-col">
        <section className="card delivery-card"><div className="delivery-icon">▥</div><div className="panel-kicker">INTERACTIVE OUTPUT</div><h3>Dashboards</h3><p>Saved dashboards combine charts, filters and shareable read-only links.</p>{dashboards.filter((d) => d.dataset_id === Number(id)).map((d) => <div className="delivery-link" key={d.id}><span>{d.name}</span><Link to={`/dashboards/${d.id}`}>Open ↗</Link></div>)}<button className="btn btn-outline" onClick={createDashboard} disabled={busy || !suggestions.length}>{busy ? "Creating…" : "＋ Generate charts-only dashboard"}</button><button className="btn" onClick={runFullAnalystPipeline} disabled={busy}>{busy ? "Running…" : "✦ Run full analyst pipeline"}</button></section>
        <section className="card delivery-card"><div className="delivery-icon">✎</div><div className="panel-kicker">WRITTEN OUTPUT</div><h3>Analysis report</h3><p>Executive summary, evidence-led findings and prioritised recommendations.</p><strong>{title}</strong><p className="muted small">{findings.length} findings · {recommendations.length} recommendations</p><div className="row wrap"><button className="btn" disabled={busy} onClick={saveReport}>Save report</button><button className="btn btn-outline" onClick={exportReport}>Export HTML</button><button className="btn btn-ghost" onClick={() => window.print()}>Print / PDF</button></div></section>
      </div>
      <section className="card final-check"><div className="panel-kicker">PRE-PUBLISH CHECKLIST</div><h3>Before you share the work</h3>{["The business question and unit of analysis are clear.", "Cleaning decisions are documented and justified.", "Chart titles, units, filters and date ranges are clear.", "Findings include evidence and avoid causal claims without proof.", "Recommendations have a practical next step and priority.", "Sensitive data and access permissions have been reviewed."].map((item, i) => <label className="check-row" key={item}><input type="checkbox"/> {item}</label>)}</section>
    </section>}

    <footer className="workflow-footer"><button className="btn btn-outline" disabled={stage === 0} onClick={() => setStage((s) => Math.max(0, s - 1))}>← Previous stage</button><span>STAGE {stage + 1} / {STAGES.length}</span><button className="btn" disabled={stage === STAGES.length - 1} onClick={() => setStage((s) => Math.min(STAGES.length - 1, s + 1))}>Next stage →</button></footer>
    <div className="method-footnote">{analysis.method_notes.map((n) => <p key={n}>ⓘ {n}</p>)}</div>
  </div>;
}


function OutlierInspector({ datasetId, schema }) {
  const numeric = schema.filter((c) => c.kind === "numeric");
  const [column, setColumn] = useState(numeric[0]?.name || "");
  const [result, setResult] = useState(null);
  useEffect(() => { if (!column) return; setResult(null); api.get(`/datasets/${datasetId}/outliers`, { params: { column } }).then((r) => setResult(r.data)).catch((e) => setResult({ error: errorMessage(e) })); }, [datasetId, column]);
  if (!numeric.length) return null;
  return <section className="card outlier-inspector"><div className="row between wrap"><div><div className="panel-kicker">EXCEPTION REVIEW</div><h3>Potential outliers</h3><p className="muted small">Investigate unusual values before removing them; they may represent valid events.</p></div><label className="inline">Measure<select value={column} onChange={(e) => setColumn(e.target.value)}>{numeric.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select></label></div>{result?.error ? <p className="error">{result.error}</p> : result ? <p>{result.count ? <><strong>{result.count}</strong> values outside the IQR review range ({fmt(result.lower)} – {fmt(result.upper)}).</> : "No potential outliers were flagged for this measure."}</p> : <p className="muted">Checking values…</p>}</section>;
}

function StageHeading({ number, title, subtitle }) { return <div className="stage-heading"><span>{number}</span><div><h2>{title}</h2><p>{subtitle}</p></div></div>; }
function Metric({ label, value, detail, tone }) { return <div className={`card workflow-metric metric-${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small><i/></div>; }
