import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { errorMessage } from "../api/client.js";

export default function DatasetCombine({ dataset }) {
  const [open, setOpen] = useState(false);
  const [datasets, setDatasets] = useState([]);
  const [otherId, setOtherId] = useState("");
  const [mode, setMode] = useState("join");
  const [leftKey, setLeftKey] = useState("");
  const [rightKey, setRightKey] = useState("");
  const [joinType, setJoinType] = useState("left");
  const [otherSchema, setOtherSchema] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState(null);

  useEffect(() => {
    if (!open) return;
    api.get("/datasets").then((r) => setDatasets((r.data.datasets || []).filter((d) => d.id !== dataset.id))).catch((e) => setError(errorMessage(e)));
  }, [open, dataset.id]);
  useEffect(() => {
    if (!otherId) { setOtherSchema([]); return; }
    api.get(`/datasets/${otherId}`).then((r) => setOtherSchema(r.data.schema || [])).catch((e) => setError(errorMessage(e)));
  }, [otherId]);

  async function combine() {
    setBusy(true); setError(""); setCreated(null);
    try {
      const body = mode === "append" ? { mode, other_dataset_id: Number(otherId) } : { mode, other_dataset_id: Number(otherId), left_key: leftKey, right_key: rightKey, join_type: joinType };
      const response = await api.post(`/datasets/${dataset.id}/combine`, body);
      setCreated(response.data);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  return <section className="card dataset-combine-card no-print">
    <div className="row between wrap"><div><span className="eyebrow">DATA MODELING</span><h3>Combine datasets</h3><p className="muted small">Join related tables or append matching files. DataDash creates a new derived dataset and leaves both source datasets unchanged.</p></div><button className="btn btn-outline" onClick={() => setOpen((v) => !v)}>{open ? "Close" : "＋ Combine data"}</button></div>
    {open && <div className="stack">
      <div className="row wrap"><label>Second dataset<select value={otherId} onChange={(e) => setOtherId(e.target.value)}><option value="">Choose dataset…</option>{datasets.map((d) => <option key={d.id} value={d.id}>{d.name} · {d.rows.toLocaleString()} rows</option>)}</select></label><label>Operation<select value={mode} onChange={(e) => setMode(e.target.value)}><option value="join">Join tables</option><option value="append">Append rows</option></select></label></div>
      {mode === "join" && <div className="row wrap"><label>Current dataset key<select value={leftKey} onChange={(e) => setLeftKey(e.target.value)}><option value="">Choose key…</option>{dataset.schema.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select></label><label>Second dataset key<select value={rightKey} onChange={(e) => setRightKey(e.target.value)}><option value="">Choose key…</option>{otherSchema.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select></label><label>Join type<select value={joinType} onChange={(e) => setJoinType(e.target.value)}><option value="left">Left join</option><option value="inner">Inner join</option><option value="right">Right join</option><option value="outer">Full outer join</option></select></label></div>}
      {mode === "append" && <p className="helper-text">Append requires matching column names. Columns are aligned by name, not position. Missing fields are not silently discarded.</p>}
      <div className="row wrap"><button className="btn" onClick={combine} disabled={busy || !otherId || (mode === "join" && (!leftKey || !rightKey))}>{busy ? "Combining…" : "Create derived dataset"}</button></div>
      {error && <p className="error">{error}</p>}{created && <p className="success">Created {created.name} · {created.rows.toLocaleString()} rows · <Link to={`/datasets/${created.id}`}>Open derived dataset ↗</Link></p>}
    </div>}
  </section>;
}
