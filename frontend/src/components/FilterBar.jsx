import { useState } from "react";
import { OPS_BY_KIND, OP_LABEL, buildFilter, describeFilter } from "../utils.js";

/**
 * Edits a list of filters. `schema` is [{name, kind}], `filters` is the API shape
 * ([{column, op, value}]). Each chip can be removed; the form adds a new one.
 */
export default function FilterBar({ schema, filters, onChange }) {
  const usable = schema.filter((c) => OPS_BY_KIND[c.kind]);
  const [row, setRow] = useState({ column: usable[0]?.name || "", op: "", value: "", value2: "" });

  const kind = usable.find((c) => c.name === row.column)?.kind;
  const ops = OPS_BY_KIND[kind] || [];
  const op = ops.includes(row.op) ? row.op : ops[0];
  const inputType = kind === "numeric" ? "number" : kind === "datetime" ? "date" : "text";

  function add(e) {
    e.preventDefault();
    if (row.value === "" || (op === "between" && row.value2 === "")) return;
    onChange([...filters, buildFilter({ ...row, op })]);
    setRow({ ...row, value: "", value2: "" });
  }

  return (
    <div className="filter-bar no-print">
      <div className="row wrap">
        {filters.map((f, i) => (
          <span className="chip" key={i}>
            {describeFilter(f)}
            <button className="chip-x" aria-label={`Remove filter ${describeFilter(f)}`} onClick={() => onChange(filters.filter((_, j) => j !== i))}>×</button>
          </span>
        ))}
        {filters.length === 0 && <span className="muted small">No filters - showing all rows.</span>}
      </div>
      {filters.length < 10 && usable.length > 0 && (
        <form className="row wrap" onSubmit={add}>
          <select aria-label="Filter column" value={row.column} onChange={(e) => setRow({ ...row, column: e.target.value, op: "" })}>
            {usable.map((c) => <option key={c.name}>{c.name}</option>)}
          </select>
          <select aria-label="Filter operator" value={op} onChange={(e) => setRow({ ...row, op: e.target.value })}>
            {ops.map((o) => <option key={o} value={o}>{OP_LABEL[o]}</option>)}
          </select>
          {kind === "boolean" ? (
            <select aria-label="Filter value" value={row.value} onChange={(e) => setRow({ ...row, value: e.target.value })}>
              <option value="">choose…</option><option value="true">Yes</option><option value="false">No</option>
            </select>
          ) : (
            <input aria-label="Filter value" type={op === "in" ? "text" : inputType} step="any" value={row.value}
              placeholder={op === "in" ? "a, b, c" : "value"} onChange={(e) => setRow({ ...row, value: e.target.value })} />
          )}
          {op === "between" && (
            <input aria-label="Filter upper value" type={inputType} step="any" value={row.value2}
              onChange={(e) => setRow({ ...row, value2: e.target.value })} />
          )}
          <button className="btn btn-outline small">+ Add filter</button>
        </form>
      )}
    </div>
  );
}
