import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api, { errorMessage } from "../api/client.js";

export default function Datasets() {
  const navigate = useNavigate();
  const input = useRef(null);
  const [datasets, setDatasets] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [workbook, setWorkbook] = useState(null);
  const [selectedSheets, setSelectedSheets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("name");
  const [deletingId, setDeletingId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get("/datasets");
      setDatasets(response.data.datasets || []);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);
  const visibleDatasets = useMemo(() => {
    const filtered = (datasets || []).filter((dataset) => `${dataset.name || ""} ${dataset.original_filename || ""}`.toLowerCase().includes(search.trim().toLowerCase()));
    return filtered.sort((a, b) => sort === "rows" ? (b.rows || 0) - (a.rows || 0) : sort === "name" ? String(a.name || "").localeCompare(String(b.name || "")) : String(b.created_at || "").localeCompare(String(a.created_at || "")));
  }, [datasets, search, sort]);
  useEffect(() => { load(); }, [load]);

  async function upload(file) {
    if (!file) return;
    const maxUploadBytes = 25 * 1024 * 1024;
    if (file.size > maxUploadBytes) {
      setError(`This file is ${(file.size / (1024 * 1024)).toFixed(2)} MB. The upload limit is 25 MB.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (file.name.toLowerCase().endsWith(".xlsx")) {
        const body = new FormData();
        body.append("file", file);
        const res = await api.post("/datasets/workbook/sheets", body);
        setWorkbook({ file, sheets: res.data.sheets });
        setSelectedSheets(res.data.sheets.map((sheet) => sheet.name));
        setBusy(false);
        return;
      }
      const body = new FormData();
      body.append("file", file);
      const res = await api.post("/datasets", body);
      try {
        const run = await api.post(`/datasets/${res.data.id}/auto-build`, {
          business_question: "Identify the most important patterns, performance differences and data-quality risks in this dataset.",
          audience: "Business stakeholders",
          row_grain: "To be confirmed during dataset understanding",
          apply_safe_text_trim: true,
        });
        navigate(`/dashboards/${run.data.dashboard.id}`, { state: { autoRun: run.data } });
      } catch {
        navigate(`/datasets/${res.data.id}`);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function importSelectedSheets() {
    if (!workbook || selectedSheets.length === 0) return;
    setBusy(true);
    setError("");
    const body = new FormData();
    body.append("file", workbook.file);
    body.append("sheet_names", JSON.stringify(selectedSheets));
    try {
      const res = await api.post("/datasets/workbook/import", body);
      setWorkbook(null);
      setSelectedSheets([]);
      await load();
      // Build the initial dashboard for the first imported sheet; every selected sheet remains
      // available as a separate dataset in the library for its own analysis.
      const first = res.data.datasets[0];
      try {
        const run = await api.post(`/datasets/${first.id}/auto-build`, {
          business_question: "Identify the most important patterns, performance differences and data-quality risks in this worksheet.",
          audience: "Business stakeholders",
          row_grain: "To be confirmed during dataset understanding",
          apply_safe_text_trim: true,
        });
        navigate(`/dashboards/${run.data.dashboard.id}`, { state: { autoRun: run.data } });
      } catch {
        navigate(`/datasets/${first.id}`);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(d) {
    if (!window.confirm(`Delete "${d.name}" and any dashboards built on it? This cannot be undone.`)) return;
    setDeletingId(d.id);
    setError("");
    try {
      await api.delete(`/datasets/${d.id}`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <>
      <div className="page-heading"><div><span className="eyebrow">YOUR ANALYTICS WORKSPACE</span><h1>Turn raw data into clear decisions.</h1><p className="muted">One workspace for data preparation, analysis, visualization and decision-ready reporting.</p></div><div className="hero-mark">✦</div></div>
      <div
        className={`dropzone ${dragging ? "drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); upload(e.dataTransfer.files[0]); }}
      >
        <div className="upload-icon">↑</div><p><strong>Drop your data file here</strong></p>
        <p className="muted small">CSV, TSV or Excel · up to 25 MB · up to 200,000 rows</p><p className="upload-pipeline-note">After upload, DataDash automatically profiles, safely prepares, analyses and builds a multi-page dashboard and report.</p>
        <button className="btn" disabled={busy} onClick={() => input.current.click()}>{busy ? "Preparing, analysing & building dashboard…" : "Choose a file"}</button>
        <input ref={input} type="file" accept=".csv,.tsv,.xlsx" hidden onChange={(e) => { upload(e.target.files[0]); e.target.value = ""; }} />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {workbook && <div className="card" role="dialog" aria-modal="true" aria-labelledby="sheet-dialog-title" style={{ marginTop: 18 }}>
        <div className="section-heading"><div><span className="eyebrow">EXCEL WORKBOOK</span><h2 id="sheet-dialog-title">Choose worksheets to import</h2><p className="muted small">Each selected worksheet becomes its own independent dataset. The original workbook is not changed.</p></div></div>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <span className="muted small">{selectedSheets.length} of {workbook.sheets.length} selected</span>
          <button className="btn btn-ghost small" type="button" onClick={() => setSelectedSheets(selectedSheets.length === workbook.sheets.length ? [] : workbook.sheets.map((sheet) => sheet.name))}>{selectedSheets.length === workbook.sheets.length ? "Clear selection" : "Select all"}</button>
        </div>
        <div style={{ display: "grid", gap: 9 }}>
          {workbook.sheets.map((sheet) => <label key={sheet.name} className="row" style={{ flexDirection: "row", alignItems: "center", padding: "11px 13px", border: "1px solid var(--border)", borderRadius: 10 }}>
            <input type="checkbox" checked={selectedSheets.includes(sheet.name)} onChange={(e) => setSelectedSheets((old) => e.target.checked ? [...old, sheet.name] : old.filter((name) => name !== sheet.name))} />
            <span>{sheet.name}</span>
          </label>)}
        </div>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 18 }}>
          <button className="btn btn-outline" type="button" disabled={busy} onClick={() => { setWorkbook(null); setSelectedSheets([]); }}>Cancel</button>
          <button className="btn" type="button" disabled={busy || selectedSheets.length === 0} onClick={importSelectedSheets}>{busy ? "Importing worksheets…" : `Import ${selectedSheets.length} worksheet${selectedSheets.length === 1 ? "" : "s"}`}</button>
        </div>
      </div>}

      <div className="section-heading list-heading"><div><span className="eyebrow">LIBRARY</span><h2>Your datasets</h2></div><div className="row wrap"><span className="count-pill">{datasets?.length ?? 0} datasets</span><button className="btn btn-ghost small" type="button" onClick={load} disabled={loading}>⟳ Refresh</button></div></div>
      {(datasets?.length ?? 0) > 0 && <div className="dataset-library-tools no-print"><input aria-label="Search datasets" placeholder="Search by dataset or filename…" value={search} onChange={(e) => setSearch(e.target.value)} /><select aria-label="Sort datasets" value={sort} onChange={(e) => setSort(e.target.value)}><option value="name">Sort: Name</option><option value="rows">Sort: Largest first</option><option value="newest">Sort: Newest first</option></select></div>}
      {loading && !datasets && <div className="card empty-state"><strong>Loading your datasets…</strong></div>}
      {datasets?.length === 0 && <div className="card empty-state"><span>▤</span><strong>Your workspace is ready</strong><p className="muted">Upload your first spreadsheet to start exploring your data.</p></div>}
      {datasets?.length > 0 && visibleDatasets.length === 0 && <div className="card empty-state"><strong>No matching datasets</strong><p className="muted">Try another dataset name or filename.</p><button className="btn btn-ghost small" onClick={() => setSearch("")}>Clear search</button></div>}
      <div className="grid">
        {visibleDatasets.map((d) => (
          <div key={d.id} className="card dataset-card">
            <div className="dataset-icon">▦</div>
            <h3><Link to={`/datasets/${d.id}`}>{d.name}</Link></h3>
            <p className="muted small">{Number(d.rows || 0).toLocaleString("en-IN")} rows · {d.columns} columns</p>
            <p className="muted small dataset-filename">{d.original_filename}</p>
            <div className="row">
              <Link className="btn btn-outline small" to={`/datasets/${d.id}`}>Open workspace ↗</Link>
              <button className="btn btn-ghost small" disabled={deletingId === d.id} onClick={() => remove(d)}>{deletingId === d.id ? "Deleting…" : "Delete"}</button>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
