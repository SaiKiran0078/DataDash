import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import api, { errorMessage } from "../api/client.js";
import ChartCard from "../components/ChartCard.jsx";
import AnalyticalDashboard from "../components/AnalyticalDashboard.jsx";
import FilterBar from "../components/FilterBar.jsx";
import { appendFilterHistory, removeColumnFilters, toggleMonthFilter, toggleValueFilter } from "../utils.js";

export default function DashboardPage() {
  const { id } = useParams();
  const location = useLocation();
  const [dash, setDash] = useState(null);
  const [schema, setSchema] = useState([]);
  const [datasetInfo, setDatasetInfo] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(true);
  const [data, setData] = useState({});
  const [interactiveSummary, setInteractiveSummary] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [printingAll, setPrintingAll] = useState(false);
  const [exporting, setExporting] = useState("");
  const [activeFilters, setActiveFilters] = useState([]);
  const [filterHistory, setFilterHistory] = useState([[]]);
  const [historyIndex, setHistoryIndex] = useState(0);

  const loadData = useCallback(async (filters = []) => {
    const res = await api.post(`/dashboards/${id}/query`, { filters });
    setData(Object.fromEntries(res.data.widgets.map((w) => [w.id, w])));
    setInteractiveSummary(res.data.summary || null);
  }, [id]);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        // Fetch dashboard definition and lightweight dataset metadata together.
        // Start the expensive visual query and analyst analysis in parallel only
        // after the dashboard tells us which dataset to load.
        const d = (await api.get(`/dashboards/${id}`)).data;
        if (!live) return;
        setDash(d);
        setAnalysisLoading(true);
        const initialFilters = Array.isArray(d.filters) ? d.filters : [];
        setActiveFilters(initialFilters);
        setFilterHistory([initialFilters]);
        setHistoryIndex(0);

        api.get(`/datasets/${d.dataset_id}`).then((response) => {
          if (!live) return;
          setSchema(response.data.schema);
          setDatasetInfo(response.data);
        }).catch((err) => { if (live) setError(errorMessage(err)); });
        api.post(`/dashboards/${id}/query`, { filters: initialFilters }).then((response) => {
          if (!live) return;
          setData(Object.fromEntries(response.data.widgets.map((w) => [w.id, w])));
          setInteractiveSummary(response.data.summary || null);
        }).catch((err) => { if (live) setError(errorMessage(err)); });
        api.get(`/datasets/${d.dataset_id}/analysis`).then((response) => {
          if (live) { setAnalysis(response.data); setAnalysisLoading(false); }
        }).catch(() => {
          if (live) setAnalysisLoading(false);
          // Analyst insights are supplemental; saved dashboard visuals remain usable.
        });
        // Each section paints as soon as its own request completes.
      } catch (err) {
        if (live) setError(errorMessage(err));
      }
    })();
    return () => { live = false; };
  }, [id]);

  useEffect(() => {
    const finishPrint = () => setPrintingAll(false);
    window.addEventListener("afterprint", finishPrint);
    return () => window.removeEventListener("afterprint", finishPrint);
  }, []);

  const edit = (patch) => { setDash({ ...dash, ...patch }); setDirty(true); };

  async function save() {
    setError("");
    try {
      const body = { name: dash.name, dataset_id: dash.dataset_id, widgets: dash.widgets, filters: activeFilters };
      setDash((await api.put(`/dashboards/${id}`, body)).data);
      setDirty(false);
      await loadData(activeFilters);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function toggleShare() {
    try {
      const res = dash.shared ? await api.delete(`/dashboards/${id}/share`) : await api.post(`/dashboards/${id}/share`);
      setDash((d) => ({ ...d, shared: res.data.shared, share_token: res.data.share_token }));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function rotate() {
    if (!window.confirm("Create a new link? The old link will stop working.")) return;
    const res = await api.post(`/dashboards/${id}/share`);
    setDash((d) => ({ ...d, share_token: res.data.share_token }));
  }

  async function refreshInteractive(filters) {
    try {
      const result = await api.post(`/dashboards/${id}/query`, { filters });
      setData(Object.fromEntries(result.data.widgets.map((w) => [w.id, w])));
      setInteractiveSummary(result.data.summary || null);
    } catch (err) { setError(errorMessage(err)); }
  }

  function applyFilterState(filters) {
    const next = Array.isArray(filters) ? filters : [];
    setActiveFilters(next);
    setDash((current) => current ? { ...current, filters: next } : current);
    setDirty(true);
    refreshInteractive(next);
  }

  function changeFilters(filters) {
    const next = Array.isArray(filters) ? filters : [];
    const updated = appendFilterHistory(filterHistory, historyIndex, next);
    if (updated.history !== filterHistory) {
      setFilterHistory(updated.history);
      setHistoryIndex(updated.index);
    }
    applyFilterState(next);
  }

  function moveFilterHistory(nextIndex) {
    if (nextIndex < 0 || nextIndex >= filterHistory.length || nextIndex === historyIndex) return;
    setHistoryIndex(nextIndex);
    applyFilterState(filterHistory[nextIndex]);
  }

  function resetFilter(column) {
    if (!column) return;
    changeFilters(removeColumnFilters(activeFilters, column));
  }

  function crossFilter(column, value) {
    if (!column) return;
    // Clicking the same segment a second time toggles that selection off.
    changeFilters(toggleValueFilter(activeFilters, column, value));
  }

  function crossFilterMonth(column, value) {
    changeFilters(toggleMonthFilter(activeFilters, column, value));
  }



  if (!dash) return error ? <div className="card"><p className="error">{error}</p><Link to="/dashboards">Back</Link></div> : <p className="muted">Loading...</p>;

  const link = dash.share_token ? `${window.location.origin}/s/${dash.share_token}` : "";
  const dashboardPages = [...new Set((dash.widgets || []).map((w) => w.page || "Overview"))];

  function exportFullPdf() {
    setPrintingAll(true);
    // Let React mount every dashboard page and Chart.js measure its print canvas first.
    window.setTimeout(() => window.print(), 700);
  }

  async function exportPlatform(platform) {
    setExporting(platform);
    setError("");
    try {
      const response = await api.get(`/dashboards/${id}/export/${platform}`, { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      const ext = platform === "excel" ? "xlsx" : platform === "powerpoint" ? "pptx" : platform === "tableau" ? "twbx" : "zip";
      anchor.download = `${(dash.name || "datadash").replace(/[^a-z0-9_-]+/gi, "_")}_${platform}_export.${ext}`;
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1500);
    } catch (err) {
      setError(errorMessage(err));
    } finally { setExporting(""); }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(link); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* user can copy manually */ }
  }

  return (
    <>
      <Link to="/dashboards" className="muted small no-print">← All dashboards</Link>
      <div className="dashboard-header">
        <div className="dashboard-title-row"><div><span className="eyebrow">DASHBOARD WORKSPACE</span><input className="title-input no-print" aria-label="Dashboard name" value={dash.name} maxLength={120} onChange={(e) => edit({ name: e.target.value })} /><h1 className="print-only">{dash.name}</h1><p className="muted small">{datasetInfo?.name || "Dataset insights"} · Live from your saved dataset</p></div></div>
        <div className="dashboard-actions no-print">
          <button className="btn" disabled={!dirty} onClick={save}>{dirty ? "Save changes" : "✓ Saved"}</button>
          <button className="btn btn-outline" onClick={exportFullPdf}>↓ Export full PDF</button>
          <button className="btn btn-outline" disabled={!!exporting} onClick={() => exportPlatform("powerbi-project")}>{exporting === "powerbi-project" ? "Preparing Power BI…" : "↗ Export to Power BI (.pbip)"}</button>
          <button className="btn btn-outline" disabled={!!exporting} onClick={() => exportPlatform("tableau")}>{exporting === "tableau" ? "Preparing Tableau…" : "↗ Export to Tableau"}</button>
          <button className="btn btn-outline" disabled={!!exporting} onClick={() => exportPlatform("excel")}>{exporting === "excel" ? "Preparing Excel…" : "Excel workbook"}</button>
          <button className="btn btn-outline" disabled={!!exporting} onClick={() => exportPlatform("powerpoint")}>{exporting === "powerpoint" ? "Preparing slides…" : "PowerPoint report"}</button>
        </div>
      </div>
      {location.state?.autoRun && <section className="card auto-run-receipt"><div className="row between wrap"><div><span className="eyebrow">AUTOMATED ANALYST RUN COMPLETE</span><h3>Your first analysis is ready</h3><p className="muted small">{location.state.autoRun.dataset.rows.toLocaleString("en-IN")} records · {location.state.autoRun.dashboard.widgets} visuals · {location.state.autoRun.dashboard.pages.length} dashboard pages · report saved</p></div><span className="badge">Pipeline completed</span></div><div className="auto-run-steps">{location.state.autoRun.applied_steps.map((step, index) => <article key={`${step.step}-${index}`}><strong>{step.step}</strong><span>{step.detail}</span></article>)}</div>{location.state.autoRun.pending_decisions?.length > 0 && <p className="helper-text">{location.state.autoRun.pending_decisions.length} data-quality decision(s) remain for analyst review. No missing values, duplicates or outliers were silently removed.</p>}</section>}
      {error && <p className="error" role="alert">{error}</p>}
      <section className="card dashboard-quality-policy no-print"><div className="row between wrap"><div><span className="eyebrow">ANALYTICAL DATA POLICY</span><h3>Validated visual data · source records preserved</h3><p className="muted small">Charts use valid values for the fields they require. Missing categories are shown as “Not recorded”; missing dates and measures are excluded only from affected visuals. No source rows are silently deleted and no values are invented.</p></div><span className="badge">Field-aware validation</span></div></section>
      {datasetInfo && <section className="dashboard-control-deck no-print">
        <div className="dashboard-control-heading">
          <div><span className="eyebrow">DASHBOARD CONTROLS</span><strong>Filter, explore and share</strong><small>All saved and automatic visuals respond to the same filters.</small></div>
          <div className="dashboard-share-actions">
            <button className="btn btn-outline small" onClick={toggleShare}>{dash.shared ? "Stop sharing" : "Create read-only link"}</button>
            {dash.shared && <button className="btn btn-ghost small" onClick={rotate}>Regenerate link</button>}
          </div>
        </div>
        <div className="dashboard-control-grid">
          <div className="dashboard-filter-panel">
            <div className="row between wrap"><strong>Filters</strong><span className="muted small">{activeFilters.length ? `${activeFilters.length} active` : "All records"}</span></div>
            <FilterBar schema={schema} filters={activeFilters} onChange={changeFilters} />
            <div className="row wrap dashboard-history-actions">
              <button className="btn btn-outline small" type="button" onClick={() => moveFilterHistory(historyIndex - 1)} disabled={historyIndex <= 0}>↶ Undo</button>
              <button className="btn btn-outline small" type="button" onClick={() => moveFilterHistory(historyIndex + 1)} disabled={historyIndex >= filterHistory.length - 1}>↷ Redo</button>
              <button className="btn btn-ghost small" type="button" onClick={() => changeFilters([])} disabled={activeFilters.length === 0}>↺ Reset</button>
              <button className="btn btn-ghost small" type="button" onClick={() => refreshInteractive(activeFilters)}>⟳ Refresh</button>
            </div>
          </div>
          <div className="dashboard-share-panel">
            <strong>Share dashboard</strong>
            <p className="muted small">Create a read-only link to these visuals. Raw dataset access is not shared.</p>
            {dash.shared ? <div className="row wrap"><input readOnly aria-label="Share link" value={link} onFocus={(e) => e.target.select()} /><button className="btn small" onClick={copy}>{copied ? "Copied ✓" : "Copy link"}</button></div> : <span className="muted small">Sharing is currently off.</span>}
          </div>
        </div>
        {dirty && <p className="muted small">You have unsaved dashboard changes. Select “Save changes” above to keep them.</p>}
      </section>}
      {datasetInfo && <AnalyticalDashboard
        datasetInfo={datasetInfo}
        analysis={analysis}
        analysisLoading={analysisLoading}
        summary={interactiveSummary}
        filters={activeFilters}
        onFilter={(column, value) => schema.find((item) => item.name === column)?.kind === "datetime" ? crossFilterMonth(column, value) : crossFilter(column, value)}
        onReset={resetFilter}
        savedWidgets={dash.widgets || []}
        savedData={data}
        onRemoveWidget={(widgetId) => edit({ widgets: dash.widgets.filter((widget) => widget.id !== widgetId) })}
      />}
            {printingAll && dash.widgets.length > 0 && <div className="dashboard-print-all" aria-hidden="true">
        <h2 className="print-dashboard-title">{dash.name} — Complete dashboard</h2>
        <p className="print-dashboard-subtitle">{datasetInfo?.name || "Dataset"} · All analysis pages · Generated {new Date().toLocaleString()}</p>
        {dashboardPages.map((page) => <section className="dashboard-print-page" key={page}>
          <div className="dashboard-print-page-heading"><span className="eyebrow">ANALYSIS PAGE</span><h2>{page}</h2></div>
          <div className="grid charts">{dash.widgets.filter((w) => (w.page || "Overview") === page).map((w) => w.display_type === "table" ? <section className="card dashboard-pivot-card" key={w.id}>
            <header><span className="eyebrow">PIVOT SUMMARY</span><h3>{w.title}</h3></header>
            <div className="table-wrap dashboard-pivot-scroll"><table><thead><tr>{(w.table_columns || []).map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{(data[w.id]?.table_rows || w.table_rows || []).map((row, ri) => <tr key={ri}>{(w.table_columns || []).map((column) => <td key={column}>{typeof row[column] === "number" ? Number(row[column]).toLocaleString("en-IN", { maximumFractionDigits: 2 }) : String(row[column] ?? "—")}</td>)}</tr>)}</tbody></table></div>
          </section> : <ChartCard key={w.id} title={w.title} subtitle={w.page || "Analysis"} type={w.spec?.type || "bar"} data={data[w.id]?.data} printMode />)}</div>
        </section>)}
      </div>}
    </>
  );
}
