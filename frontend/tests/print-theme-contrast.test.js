import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const css = await readFile(new URL("../src/styles/index.css", import.meta.url), "utf8");

test("print styles force opaque light surfaces for pivot tables", () => {
  assert.match(css, /\.dashboard-print-all \.dashboard-pivot-scroll,\s*\n\s*\.dashboard-print-all \.dashboard-pivot-scroll\.table-wrap,\s*\n\s*\.dashboard-print-all \.table-wrap\s*\{[\s\S]*?background:\s*#ffffff\s*!important/);
  assert.match(css, /\.dashboard-print-all \.dashboard-pivot-scroll th\s*\{[\s\S]*?background:\s*#edf2f8\s*!important/);
  assert.match(css, /\.dashboard-print-all \.dashboard-pivot-scroll tbody tr:nth-child\(even\)\s*\{[\s\S]*?background:\s*#f7f9fc\s*!important/);
  assert.match(css, /\.dashboard-print-all \.dashboard-pivot-scroll\s*\{[\s\S]*?overflow:\s*visible\s*!important/);
});

test("light-theme authentication submit button keeps a high-contrast visible state", () => {
  assert.match(css, /:root\[data-theme="light"\] \.auth-layout \.auth-form button\.auth-submit[\s\S]*?color:\s*#ffffff\s*!important/);
  assert.match(css, /:root\[data-theme="light"\] \.auth-layout \.auth-form button\.auth-submit:disabled[\s\S]*?opacity:\s*\.82\s*!important/);
  assert.match(css, /:root\[data-theme="light"\] \.auth-layout \.auth-form button\.auth-submit:focus-visible[\s\S]*?outline:/);
});

test("print stylesheet neutralises dark KPI cards and analyst summary panels", () => {
  assert.match(css, /\.dashboard-kpis-premium \.kpi-card,[\s\S]*?background:\s*#ffffff\s*!important/);
  assert.match(css, /\.dashboard-kpis-premium \.kpi-card > strong\s*\{[\s\S]*?color:\s*#172033\s*!important/);
  assert.match(css, /\.dashboard-findings,[\s\S]*?background:\s*#ffffff\s*!important/);
  assert.match(css, /\.dashboard-finding-grid article,[\s\S]*?background:\s*#f8faff\s*!important/);
});

test("print stylesheet removes the orphaned auto-visual heading when its charts are duplicated", () => {
  assert.match(css, /\.dashboard-visual-heading-duplicated\s*\{\s*display:\s*none\s*!important/);
});
