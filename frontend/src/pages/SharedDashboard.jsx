import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import api from "../api/client.js";
import ChartCard from "../components/ChartCard.jsx";

/** Public, read-only dashboard opened from a share link. No login, no raw data. */
export default function SharedDashboard() {
  const { token } = useParams();
  const [dash, setDash] = useState(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    api.get(`/shared/${token}`)
      .then((r) => setDash(r.data))
      .catch(() => setMissing(true));
  }, [token]);

  if (missing) return <div className="card center"><h2>Link not available</h2><p className="muted">This dashboard link is invalid or sharing has been turned off.</p></div>;
  if (!dash) return <p className="muted">Loading...</p>;
  return (
    <>
      <div className="row between wrap">
        <h1>{dash.name}</h1>
        <button className="btn btn-outline no-print" onClick={() => window.print()}>Print / Save as PDF</button>
      </div>
      <p className="muted small no-print">Shared, read-only view · built with DataDash</p>
      <div className="grid charts">
        {dash.widgets.map((w) => w.display_type === "table" ? <section className="card dashboard-pivot-card" key={w.id}><span className="eyebrow">PIVOT SUMMARY</span><h3>{w.title}</h3><div className="table-wrap dashboard-pivot-scroll"><table><thead><tr>{(w.table_columns || []).map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>{(w.table_rows || []).map((row, i) => <tr key={i}>{(w.table_columns || []).map((c) => <td key={c}>{String(row[c] ?? "—")}</td>)}</tr>)}</tbody></table></div></section> : <ChartCard key={w.id} title={w.title} type={w.spec?.type || "bar"} data={w.data} />)}
      </div>
    </>
  );
}
