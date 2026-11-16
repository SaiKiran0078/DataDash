import test from "node:test";
import assert from "node:assert/strict";
import { appendFilterHistory, removeColumnFilters, toggleMonthFilter, toggleValueFilter } from "../src/utils.js";

test("clicking a category adds a filter and clicking it again clears it", () => {
  const selected = toggleValueFilter([], "region", "North");
  assert.deepEqual(selected, [{ column: "region", op: "eq", value: "North" }]);
  assert.deepEqual(toggleValueFilter(selected, "region", "North"), []);
});

test("changing a category replaces only that column filter", () => {
  const current = [{ column: "region", op: "eq", value: "North" }, { column: "year", op: "eq", value: 2025 }];
  assert.deepEqual(toggleValueFilter(current, "region", "South"), [
    { column: "year", op: "eq", value: 2025 }, { column: "region", op: "eq", value: "South" },
  ]);
});

test("month selection uses the full month range and toggles off", () => {
  const selected = toggleMonthFilter([], "order_date", "2024-02");
  assert.deepEqual(selected, [{ column: "order_date", op: "between", value: ["2024-02-01", "2024-02-29"] }]);
  assert.deepEqual(toggleMonthFilter(selected, "order_date", "2024-02"), []);
});

test("removing a chart filter preserves other filters", () => {
  const current = [{ column: "region", op: "eq", value: "North" }, { column: "status", op: "eq", value: "Open" }];
  assert.deepEqual(removeColumnFilters(current, "region"), [{ column: "status", op: "eq", value: "Open" }]);
});

test("filter history supports undo, redo branching and a bounded length", () => {
  const a = []; const b = [{ column: "region", op: "eq", value: "North" }];
  let state = appendFilterHistory([a], 0, b);
  assert.equal(state.index, 1);
  assert.deepEqual(state.history, [a, b]);
  state = appendFilterHistory(state.history, 0, [{ column: "region", op: "eq", value: "South" }]);
  assert.equal(state.history.length, 2);
  assert.equal(state.index, 1);
  let history = [[]]; let index = 0;
  for (let i = 0; i < 40; i++) { const next = appendFilterHistory(history, index, [{ column: "n", op: "eq", value: i }]); history = next.history; index = next.index; }
  assert.equal(history.length, 31);
});
