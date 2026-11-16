import { useEffect, useState } from "react";
import api, { errorMessage } from "../api/client.js";
import { Link } from "react-router-dom";

/** Adds a chart (title + spec + filters) to an existing dashboard of this dataset, or to a new one. */
export default function AddToDashboard({ datasetId, title, spec, filters }) {
  const [open, setOpen] = useState(false);
  const [dashboards, setDashboards] = useState([]);
  const [choice, setChoice] = useState("new");
  const [name, setName] = useState("My dashboard");
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    if (!open) return;
    api.get("/dashboards").then((r) => {
      const mine = r.data.dashboards.filter((d) => d.dataset_id === datasetId);
      setDashboards(mine);
      if (mine.length) setChoice(String(mine[0].id));
    });
  }, [open, datasetId]);

  async function add() {
    setMsg(null);
    const widget = { id: `w${Date.now().toString(36)}`, title, spec, filters };
    try {
      if (choice === "new") {
        const res = await api.post("/dashboards", { name, dataset_id: datasetId, widgets: [widget], filters: [] });
        setMsg({ ok: true, id: res.data.id });
      } else {
        const d = dashboards.find((x) => String(x.id) === choice);
        await api.put(`/dashboards/${d.id}`, { name: d.name, dataset_id: d.dataset_id, filters: d.filters, widgets: [...d.widgets, widget] });
        setMsg({ ok: true, id: d.id });
      }
    } catch (err) {
      setMsg({ ok: false, text: errorMessage(err) });
    }
  }

  if (!open) return <button className="btn btn-outline small" onClick={() => setOpen(true)}>+ Add to dashboard</button>;
  return (
    <div className="row wrap add-box">
      <select aria-label="Dashboard" value={choice} onChange={(e) => setChoice(e.target.value)}>
        {dashboards.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        <option value="new">+ New dashboard</option>
      </select>
      {choice === "new" && <input aria-label="New dashboard name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />}
      <button className="btn small" onClick={add}>Add</button>
      <button className="btn btn-ghost small" onClick={() => setOpen(false)}>Close</button>
      {msg?.ok && <span className="success small">Added! <Link to={`/dashboards/${msg.id}`}>Open dashboard</Link></span>}
      {msg && !msg.ok && <span className="error small" role="alert">{msg.text}</span>}
    </div>
  );
}
