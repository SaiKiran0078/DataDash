import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api, { errorMessage } from "../api/client.js";
import ChartCard from "../components/ChartCard.jsx";
import ChartBuilder from "../components/ChartBuilder.jsx";
import FilterBar from "../components/FilterBar.jsx";
import DataTable from "../components/DataTable.jsx";
import AddToDashboard from "../components/AddToDashboard.jsx";
import CleaningStudio from "../components/CleaningStudio.jsx";
import DatasetCombine from "../components/DatasetCombine.jsx";
import { KIND_LABEL, fmt } from "../utils.js";

const TABS = [["overview", "Overview"], ["clean", "Clean data"], ["suggested", "Suggested charts"], ["explore", "Chart builder"], ["data", "Data preview"], ["outliers", "Outliers"]];

export default function DatasetPage() {
  const { id } = useParams();
  const [ds, setDs] = useState(null);
  const [tab, setTab] = useState("overview");
  const [error, setError] = useState("");

  useEffect(() => {
    api.get(`/datasets/${id}`).then((r) => setDs(r.data)).catch((e) => setError(errorMessage(e)));
  }, [id]);

  if (error) return <div className="card"><p className="error">{error}</p><Link to="/">Back</Link></div>;
  if (!ds) return <p className="muted">Loading...</p>;

  return (
    <>
      <Link to="/" className="muted small">← All datasets</Link>
      <div className="page-heading"><div><span className="eyebrow">DATA WORKSPACE</span><h1>{ds.name}</h1><p className="muted">{ds.rows.toLocaleString()} rows · {ds.columns} columns · {ds.original_filename}</p></div><div className="row wrap"><Link className="btn" to={`/datasets/${ds.id}/workflow`}>✦ Analyst workflow</Link><button className="btn btn-outline" onClick={async () => { try { const r = await api.get(`/datasets/${ds.id}/export`, { responseType: "blob" }); const url = URL.createObjectURL(r.data); const a = document.createElement("a"); a.href = url; a.download = `${ds.name.replace(/[^a-z0-9_-]/gi, "_")}_cleaned.csv`; a.click(); URL.revokeObjectURL(url); } catch (e) { setError(errorMessage(e)); } }}>↓ Export CSV</button><Link className="btn btn-outline" to="/dashboards">Dashboards ↗</Link></div></div>
      {ds.notes.map((n) => <p key={n} className="note">ℹ {n}</p>)}
      <DatasetCombine dataset={ds} />

      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {tab === "overview" && <Overview ds={ds} onTab={setTab} />}
      {tab === "clean" && <CleaningStudio dataset={ds} onApplied={(updated) => setDs(updated)} />}
      {tab === "suggested" && <Suggested ds={ds} />}
      {tab === "explore" && <Explore ds={ds} />}
      {tab === "data" && <DataTable datasetId={ds.id} schema={ds.schema} />}
      {tab === "outliers" && <Outliers ds={ds} />}
    </>
  );
}

// ---------------------------------------------------------------- overview
function summaryText(c) {
  if (c.kind === "numeric" && c.min != null) return `${fmt(c.min)} – ${fmt(c.max)} · avg ${fmt(c.mean)}`;
  if (c.kind === "datetime" && c.min) return `${c.min.slice(0, 10)} → ${c.max.slice(0, 10)}`;
  if (c.kind === "boolean") return `${c.true_count} yes · ${c.false_count} no`;
  if (c.top_values?.length) return c.top_values.slice(0, 3).map((v) => `${v.value} (${v.count})`).join(", ");
  return "";
}

function Overview({ ds, onTab }) {
  const p = ds.profile;
  const outlierColumns = p.column_profiles.filter((c) => c.outliers > 0);
  const recommendations = [
    ...(p.duplicate_rows > 0 ? [{ title: `Review ${fmt(p.duplicate_rows)} duplicate rows`, detail: "Duplicate records can inflate totals and counts. Remove them when they represent repeated records, not legitimate transactions.", action: "Remove duplicates" }] : []),
    ...(p.missing_cells > 0 ? [{ title: `${fmt(p.missing_cells)} missing cells need attention`, detail: "Review missingness by column. Use mean/median for numeric measures, mode for categories, or an explicit label when the value is unknown.", action: "Review missing values" }] : []),
    ...(outlierColumns.length ? [{ title: `${outlierColumns.length} column(s) contain potential outliers`, detail: `Flagged columns: ${outlierColumns.slice(0, 4).map((c) => c.name).join(", ")}. Investigate before removing; unusual values may be valid business events.`, action: "Inspect outliers" }] : []),
  ];
  return (
    <div className="stack">
      <div className="grid stats">
        <div className="card stat"><span className="muted small">Rows</span><strong>{p.rows.toLocaleString()}</strong></div>
        <div className="card stat"><span className="muted small">Columns</span><strong>{p.columns}</strong></div>
        <div className="card stat"><span className="muted small">Missing cells</span><strong>{p.missing_pct}%</strong></div>
        <div className="card stat"><span className="muted small">Duplicate rows</span><strong>{p.duplicate_rows}</strong></div>
      </div>
      <section className="card quality-card">
        <div className="section-heading"><div><span className="eyebrow">DATA QUALITY CHECK</span><h2>{recommendations.length ? "Recommended next steps" : "Your data looks tidy"}</h2><p className="muted small">Use these checks before interpreting results or sharing a dashboard.</p></div><span className="icon-orb">✦</span></div>
        {recommendations.length ? <div className="quality-list">{recommendations.map((r) => <div className="quality-item" key={r.title}><div><strong>{r.title}</strong><p className="muted small">{r.detail}</p></div><button className="btn btn-outline small" onClick={() => onTab(r.action === "Inspect outliers" ? "outliers" : "clean")}>{r.action}</button></div>)}</div> : <p className="success small">No missing cells, duplicate rows or IQR outliers were flagged by the initial profile. Continue with chart exploration.</p>}
      </section>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Column</th><th>Type</th><th>Missing</th><th>Unique</th><th>Summary</th><th>Outliers</th></tr></thead>
          <tbody>
            {p.column_profiles.map((c) => (
              <tr key={c.name}>
                <td><strong>{c.name}</strong></td>
                <td><span className={`badge kind-${c.kind}`}>{KIND_LABEL[c.kind]}</span></td>
                <td>{c.missing ? `${c.missing} (${c.missing_pct}%)` : "-"}</td>
                <td>{fmt(c.unique)}</td>
                <td className="small">{summaryText(c)}</td>
                <td>{c.outliers ? <span className="badge warn">{c.outliers}</span> : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- suggested charts
function Suggested({ ds }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [createdId, setCreatedId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const sug = (await api.get(`/datasets/${ds.id}/suggestions`)).data.suggestions;
        const withData = await Promise.all(
          sug.map(async (s) => {
            try {
              const res = await api.post(`/datasets/${ds.id}/chart`, { spec: s.spec, filters: [] });
              return { ...s, data: res.data };
            } catch (err) {
              return { ...s, data: { error: errorMessage(err) } };
            }
          })
        );
        if (!cancelled) setItems(withData);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      }
    })();
    return () => { cancelled = true; };
  }, [ds.id]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!items) return <p className="muted">Looking for interesting charts...</p>;
  if (items.length === 0) return <p className="muted">This file has no numeric, date or category columns to chart. Try the Data tab.</p>;
  async function createDashboard() {
    setCreating(true); setError("");
    try {
      const widgets = items.filter((s) => !s.data?.error).slice(0, 8).map((s, i) => ({ id: `auto${i + 1}`, title: s.title, spec: s.spec, filters: [] }));
      if (!widgets.length) throw new Error("No valid suggested charts are available yet.");
      const res = await api.post("/dashboards", { name: `${ds.name} · Insights`, dataset_id: ds.id, widgets, filters: [] });
      setCreatedId(res.data.id);
    } catch (e) { setError(errorMessage(e)); }
    finally { setCreating(false); }
  }

  return (
    <>
    <div className="row between wrap dashboard-generate"><div><span className="eyebrow">AUTOMATED INSIGHTS</span><h2>Start with the patterns in your data</h2><p className="muted small">DataDash recommends charts based on your column types and distributions.</p></div><div className="row wrap"><button className="btn" disabled={creating || !items.some((s) => !s.data?.error)} onClick={createDashboard}>{creating ? "Building…" : "✦ Generate dashboard"}</button>{createdId && <Link className="btn btn-outline" to={`/dashboards/${createdId}`}>Open dashboard ↗</Link>}</div></div>
    <div className="grid charts">
      {items.map((s) => (
        <ChartCard key={s.id} title={s.title} subtitle={s.reason} type={s.spec.type} data={s.data}>
          <AddToDashboard datasetId={ds.id} title={s.title} spec={s.spec} filters={[]} />
        </ChartCard>
      ))}
    </div>
    </>
  );
}

// ---------------------------------------------------------------- explore
function Explore({ ds }) {
  const firstCat = ds.schema.find((c) => ["categorical", "boolean"].includes(c.kind)) || ds.schema.find((c) => c.kind !== "id");
  const [spec, setSpec] = useState({ type: "bar", x: firstCat?.name, agg: "count" });
  const [filters, setFilters] = useState([]);
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!spec.x) return;
    setData(null);
    const t = setTimeout(() => {
      api.post(`/datasets/${ds.id}/chart`, { spec, filters })
        .then((r) => setData(r.data))
        .catch((e) => setData({ error: errorMessage(e) }));
    }, 250); // wait for the user to stop clicking before asking the server
    return () => clearTimeout(t);
  }, [ds.id, spec, filters]);

  const title = `${spec.type} of ${spec.x}${spec.y ? ` / ${spec.y}` : ""}`;
  return (
    <div className="stack">
      <ChartBuilder schema={ds.schema} spec={spec} onChange={setSpec} />
      <FilterBar schema={ds.schema} filters={filters} onChange={setFilters} />
      <ChartCard title={title} subtitle={data?.meta ? `${data.meta.filtered_rows.toLocaleString()} rows used` : ""} type={spec.type} data={data}>
        <AddToDashboard datasetId={ds.id} title={title} spec={spec} filters={filters} />
      </ChartCard>
    </div>
  );
}

// ---------------------------------------------------------------- outliers
function Outliers({ ds }) {
  const numeric = ds.schema.filter((c) => c.kind === "numeric");
  const [column, setColumn] = useState(numeric[0]?.name || "");
  const [res, setRes] = useState(null);

  useEffect(() => {
    if (!column) return;
    api.get(`/datasets/${ds.id}/outliers`, { params: { column } }).then((r) => setRes(r.data)).catch((e) => setRes({ error: errorMessage(e) }));
  }, [ds.id, column]);

  if (numeric.length === 0) return <p className="muted">There are no numeric columns to check.</p>;
  return (
    <div className="stack">
      <label className="inline">Column
        <select value={column} onChange={(e) => setColumn(e.target.value)}>{numeric.map((c) => <option key={c.name}>{c.name}</option>)}</select>
      </label>
      {res?.error && <p className="error">{res.error}</p>}
      {res && !res.error && (
        <>
          <p>
            {res.count === 0
              ? "No unusual values found (or there isn't enough data to tell)."
              : <><strong>{res.count}</strong> unusual value(s) outside <code>{fmt(res.lower)}</code> – <code>{fmt(res.upper)}</code>.</>}
          </p>
          <p className="muted small">Rule: a value is flagged if it is more than 1.5 × IQR below the 1st quartile or above the 3rd quartile.</p>
          {res.rows.length > 0 && (
            <div className="table-wrap narrow">
              <table><thead><tr><th>Row #</th><th>{column}</th></tr></thead>
                <tbody>{res.rows.map((r) => <tr key={r.row}><td>{r.row}</td><td className="num">{fmt(r.value)}</td></tr>)}</tbody></table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
