import { AGGS } from "../utils.js";

const TYPES = [["bar", "Bar"], ["line", "Line"], ["pie", "Pie"], ["histogram", "Histogram"], ["scatter", "Scatter"]];
const GRAINS = ["day", "week", "month", "quarter", "year"];

/** Form that edits a chart spec. The options offered depend on the chosen chart type and column kinds. */
export default function ChartBuilder({ schema, spec, onChange }) {
  const kindOf = (name) => schema.find((c) => c.name === name)?.kind;
  const by = (...kinds) => schema.filter((c) => kinds.includes(c.kind));
  const numeric = by("numeric");
  const xOptions = spec.type === "histogram" || spec.type === "scatter" ? numeric : by("categorical", "boolean", "datetime", "numeric", "text");
  const colorOptions = by("categorical", "boolean");

  function set(patch) {
    const next = { ...spec, ...patch };
    // Switching chart type: reset fields that no longer make sense.
    if (patch.type) {
      const xs = patch.type === "histogram" || patch.type === "scatter" ? numeric : by("categorical", "boolean", "datetime", "numeric", "text");
      if (!xs.some((c) => c.name === next.x)) next.x = xs[0]?.name;
      if (patch.type === "scatter") next.y = numeric.find((c) => c.name !== next.x)?.name;
      if (patch.type === "histogram") { delete next.y; delete next.agg; delete next.color_by; }
      if (patch.type === "pie") delete next.color_by;
      if (patch.type !== "scatter" && patch.type !== "histogram") next.agg = next.agg || "count";
    }
    for (const k of Object.keys(next)) if (next[k] === "" || next[k] === undefined) delete next[k];
    onChange(next);
  }

  const grouped = ["bar", "line", "pie"].includes(spec.type);
  const needsY = spec.type === "scatter" || (grouped && spec.agg && spec.agg !== "count");

  return (
    <div className="builder no-print">
      <label>Chart type
        <select value={spec.type} onChange={(e) => set({ type: e.target.value })}>
          {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>

      <label>{spec.type === "scatter" ? "X axis (number)" : spec.type === "histogram" ? "Column" : "Group by"}
        <select value={spec.x || ""} onChange={(e) => set({ x: e.target.value })}>
          {xOptions.map((c) => <option key={c.name}>{c.name}</option>)}
        </select>
      </label>

      {grouped && (
        <label>Measure
          <select value={spec.agg || "count"} onChange={(e) => set({ agg: e.target.value, y: e.target.value === "count" ? undefined : spec.y || numeric[0]?.name })}>
            {AGGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      )}

      {needsY && (
        <label>{spec.type === "scatter" ? "Y axis (number)" : "of column"}
          <select value={spec.y || ""} onChange={(e) => set({ y: e.target.value })}>
            {numeric.map((c) => <option key={c.name}>{c.name}</option>)}
          </select>
        </label>
      )}

      {grouped && kindOf(spec.x) === "datetime" && (
        <label>Time step
          <select value={spec.time_grain || ""} onChange={(e) => set({ time_grain: e.target.value })}>
            <option value="">Auto</option>
            {GRAINS.map((g) => <option key={g}>{g}</option>)}
          </select>
        </label>
      )}

      {(spec.type === "bar" || spec.type === "line") && (
        <label>Split by (optional)
          <select value={spec.color_by || ""} onChange={(e) => set({ color_by: e.target.value })}>
            <option value="">None</option>
            {colorOptions.filter((c) => c.name !== spec.x).map((c) => <option key={c.name}>{c.name}</option>)}
          </select>
        </label>
      )}

      {spec.type === "histogram" && (
        <label>Bars
          <input type="number" min="2" max="50" value={spec.bins || 10} onChange={(e) => set({ bins: Number(e.target.value) })} />
        </label>
      )}
    </div>
  );
}
