import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api, { errorMessage } from "../api/client.js";

export default function Dashboards() {
  const navigate = useNavigate();
  const [items, setItems] = useState(null);
  const [datasets, setDatasets] = useState([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ name: "", dataset_id: "" });
  const [search, setSearch] = useState("");
  const [deletingId, setDeletingId] = useState(null);

  const load = useCallback(async () => {
    try {
      const [d, ds] = await Promise.all([api.get("/dashboards"), api.get("/datasets")]);
      setItems(d.data.dashboards);
      setDatasets(ds.data.datasets);
      setForm((f) => ({ ...f, dataset_id: f.dataset_id || String(ds.data.datasets[0]?.id || "") }));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function create(e) {
    e.preventDefault();
    setError("");
    try {
      const res = await api.post("/dashboards", { name: form.name, dataset_id: Number(form.dataset_id), widgets: [], filters: [] });
      navigate(`/dashboards/${res.data.id}`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove(d) {
    if (!window.confirm(`Delete dashboard "${d.name}"? Any shared link will stop working. This cannot be undone.`)) return;
    setDeletingId(d.id);
    setError("");
    try {
      await api.delete(`/dashboards/${d.id}`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDeletingId(null);
    }
  }

  const nameOf = (id) => datasets.find((d) => d.id === id)?.name || "dataset";
  const visibleItems = (items || []).filter((item) => `${item.name || ""} ${nameOf(item.dataset_id)}`.toLowerCase().includes(search.trim().toLowerCase()));
  return (
    <>
      <h1>Dashboards</h1>
      {datasets.length > 0 && (
        <form className="card row wrap" onSubmit={create}>
          <input required maxLength={120} placeholder="Dashboard name" aria-label="Dashboard name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select aria-label="Dataset" value={form.dataset_id} onChange={(e) => setForm({ ...form, dataset_id: e.target.value })}>
            {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <button className="btn">Create</button>
        </form>
      )}
      {datasets.length === 0 && items && <p className="muted">Upload a dataset first, then build dashboards from its charts.</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {(items?.length ?? 0) > 0 && <div className="dataset-library-tools"><input aria-label="Search dashboards" placeholder="Search dashboards or datasets…" value={search} onChange={(e) => setSearch(e.target.value)} /><button className="btn btn-ghost small" type="button" onClick={load}>⟳ Refresh</button></div>}
      <div className="grid">
        {visibleItems.map((d) => (
          <div key={d.id} className="card">
            <h3><Link to={`/dashboards/${d.id}`}>{d.name}</Link></h3>
            <p className="muted small">{d.widgets.length} chart(s) · from {nameOf(d.dataset_id)} {d.shared && "· 🔗 shared"}</p>
            <div className="row">
              <Link className="btn btn-outline small" to={`/dashboards/${d.id}`}>Open</Link>
              <button className="btn btn-ghost small" disabled={deletingId === d.id} onClick={() => remove(d)}>{deletingId === d.id ? "Deleting…" : "Delete"}</button>
            </div>
          </div>
        ))}
      </div>
      {items?.length === 0 && <p className="muted center">No dashboards yet.</p>}
      {items?.length > 0 && visibleItems.length === 0 && <div className="card empty-state"><strong>No matching dashboards</strong><p className="muted">Try another dashboard or dataset name.</p><button className="btn btn-ghost small" onClick={() => setSearch("")}>Clear search</button></div>}
    </>
  );
}
