// Colour-blind-friendly categorical palette (Tableau 10).
export const PALETTE = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2", "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac"];

export function fmt(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value !== "number") return String(value);
  if (Number.isInteger(value)) return value.toLocaleString("en-IN");
  return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export const KIND_LABEL = {
  numeric: "Number", datetime: "Date", boolean: "Yes/No", categorical: "Category", text: "Text", id: "ID", empty: "Empty",
};

export const AGGS = [
  ["count", "Count of rows"], ["sum", "Sum"], ["mean", "Average"], ["median", "Median"], ["min", "Minimum"], ["max", "Maximum"],
];

export const OPS_BY_KIND = {
  numeric: ["eq", "ne", "gt", "gte", "lt", "lte", "between"],
  datetime: ["gte", "lte", "between", "eq"],
  boolean: ["eq"],
  categorical: ["eq", "ne", "in"],
  text: ["contains", "eq"],
  id: ["eq", "in"],
};

export const OP_LABEL = {
  eq: "=", ne: "≠", gt: ">", gte: "≥", lt: "<", lte: "≤", between: "between", in: "is one of", contains: "contains",
};

/** Turns the text boxes of a filter row into the shape the API expects. */
export function buildFilter({ column, op, value, value2 }) {
  if (op === "between") return { column, op, value: [value, value2] };
  if (op === "in") return { column, op, value: String(value).split(",").map((v) => v.trim()).filter(Boolean) };
  return { column, op, value };
}

export function describeFilter(f) {
  const joiner = f.op === "between" ? " and " : ", ";
  const value = Array.isArray(f.value) ? f.value.join(joiner) : f.value;
  return `${f.column} ${OP_LABEL[f.op]} ${value}`;
}

/** Append a filter state while keeping a bounded, branch-aware undo/redo history. */
export function appendFilterHistory(history, index, nextFilters, limit = 31) {
  const current = history[index] || [];
  if (JSON.stringify(current) === JSON.stringify(nextFilters)) return { history, index };
  const branch = history.slice(0, index + 1);
  const updated = [...branch, nextFilters].slice(-limit);
  return { history: updated, index: updated.length - 1 };
}

/** Toggle a categorical chart selection; selecting the same value clears that field's filter. */
export function toggleValueFilter(filters, column, value) {
  if (!column) return filters;
  const current = filters.find((filter) => filter.column === column);
  const sameSelection = current?.op === "eq" && String(current.value) === String(value);
  const next = filters.filter((filter) => filter.column !== column);
  if (!sameSelection) next.push({ column, op: "eq", value });
  return next;
}

/** Toggle a YYYY-MM chart selection as a complete calendar-month interval. */
export function toggleMonthFilter(filters, column, monthValue) {
  if (!column || !/^\d{4}-\d{2}$/.test(monthValue)) return toggleValueFilter(filters, column, monthValue);
  const [year, month] = monthValue.split("-").map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  const current = filters.find((filter) => filter.column === column);
  const isSameMonth = current?.op === "between" && Array.isArray(current.value) && current.value[0] === `${monthValue}-01`;
  const next = filters.filter((filter) => filter.column !== column);
  if (!isSameMonth) next.push({ column, op: "between", value: [`${monthValue}-01`, `${monthValue}-${String(lastDay).padStart(2, "0")}`] });
  return next;
}

export function removeColumnFilters(filters, column) {
  return column ? filters.filter((filter) => filter.column !== column) : filters;
}

export function downloadDataUrl(dataUrl, filename) {
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  a.click();
}

export const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "chart";
