import { useEffect, useState } from "react";
import api, { errorMessage } from "../api/client.js";
import FilterBar from "./FilterBar.jsx";
import { fmt } from "../utils.js";

/** Paged, sortable, filterable view of the raw rows (server-side, so large files stay fast). */
export default function DataTable({ datasetId, schema }) {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState(null);
  const [desc, setDesc] = useState(false);
  const [filters, setFilters] = useState([]);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const params = { page, page_size: 25, descending: desc };
    if (sortBy) params.sort_by = sortBy;
    api.post(`/datasets/${datasetId}/rows`, { filters }, { params })
      .then((r) => { setData(r.data); setError(""); })
      .catch((e) => setError(errorMessage(e)));
  }, [datasetId, page, sortBy, desc, filters]);

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const toggleSort = (col) => {
    if (sortBy === col) setDesc(!desc); else { setSortBy(col); setDesc(false); }
    setPage(1);
  };

  return (
    <div className="stack">
      <FilterBar schema={schema} filters={filters} onChange={(f) => { setFilters(f); setPage(1); }} />
      {error && <p className="error" role="alert">{error}</p>}
      {data && (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {data.columns.map((c, i) => (
                    <th key={c}>
                      <button className="link" onClick={() => toggleSort(c)} aria-label={`Sort by ${c}`}>
                        {c} {sortBy === c ? (desc ? "▼" : "▲") : ""}
                      </button>
                      <div className="muted small">{data.kinds[i]}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, r) => (
                  <tr key={r}>{row.map((v, i) => <td key={i} className={data.kinds[i] === "numeric" ? "num" : ""}>{fmt(v)}</td>)}</tr>
                ))}
                {data.rows.length === 0 && <tr><td colSpan={data.columns.length} className="muted">No rows match.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="row between">
            <span className="muted small">{data.total.toLocaleString()} rows</span>
            <div className="row">
              <button className="btn btn-outline small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="small">Page {page} of {pages}</span>
              <button className="btn btn-outline small" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
