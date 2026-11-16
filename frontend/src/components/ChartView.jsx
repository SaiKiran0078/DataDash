import { forwardRef } from "react";
import { Bar, Line, Pie, Scatter } from "react-chartjs-2";
import { PALETTE } from "../utils.js";

/**
 * Draws one chart from the API's response shape:
 *   bar/line/pie/histogram -> { labels, datasets: [{label, data}] }
 *   scatter                -> { points: [{x, y}], meta: {x, y} }
 * `ref` is the Chart.js instance, used for "Download PNG" (ref.current.toBase64Image()).
 */
const valueLabels = {
  id: "valueLabels",
  afterDatasetsDraw(chart) {
    if (chart.config.type !== "bar" || chart.data.labels.length > 16) return;
    const { ctx } = chart;
    ctx.save(); ctx.font = "600 10px DM Sans, sans-serif"; ctx.fillStyle = "#65718a"; ctx.textAlign = "center";
    chart.data.datasets.forEach((dataset, i) => {
      const meta = chart.getDatasetMeta(i);
      meta.data.forEach((element, index) => {
        const value = dataset.data[index];
        if (value == null || !Number.isFinite(Number(value))) return;
        const pos = element.tooltipPosition();
        ctx.fillText(Number(value).toLocaleString("en-IN", { maximumFractionDigits: 1 }), pos.x, pos.y - 7);
      });
    });
    ctx.restore();
  },
};

const ChartView = forwardRef(function ChartView({ type, data, printMode = false, onPointClick }, ref) {
  if (!data) return <p className="muted">Loading chart...</p>;
  if (data.error) return <p className="error" role="alert">{data.error}</p>;

  const base = { responsive: true, maintainAspectRatio: false, animation: { duration: printMode ? 0 : 500 },
    interaction: { intersect: false, mode: "index" },
    onClick: (_event, elements, chart) => {
      if (!onPointClick || !elements?.length) return;
      const point = elements[0];
      const label = chart.data.labels?.[point.index];
      if (label != null) onPointClick(String(label));
    },
    plugins: { tooltip: { backgroundColor: "#172033", padding: 12, cornerRadius: 10, titleFont: { weight: "700" }, callbacks: { label: (ctx) => ` ${ctx.dataset.label || "Value"}: ${Number(ctx.parsed.y ?? ctx.parsed).toLocaleString("en-IN", { maximumFractionDigits: 2 })}` } } },
  };

  if (type === "scatter") {
    if (!data.points?.length) return <p className="muted">No data for this chart.</p>;
    const options = {
      ...base,
      plugins: { ...base.plugins, legend: { display: false } },
      scales: { x: { title: { display: true, text: data.meta.x }, grid: { display: false } }, y: { title: { display: true, text: data.meta.y }, grid: { color: "rgba(148,163,184,.16)" } } },
    };
    return (
      <div className="chart-box">
        <Scatter ref={ref} options={options}
          data={{ datasets: [{ label: `${data.meta.y} vs ${data.meta.x}`, data: data.points, backgroundColor: PALETTE[0] + "99" }] }} />
        {data.meta.correlation != null && (
          <p className="muted small">Correlation: {data.meta.correlation.toFixed(2)}{data.meta.sampled ? " · showing a sample of 1,000 points" : ""}</p>
        )}
        {data.meta?.rows_used != null && <p className="muted small chart-quality-note">Validated visual scope: {Number(data.meta.rows_used).toLocaleString("en-IN")} complete records · {Number(data.meta.rows_excluded_missing || 0).toLocaleString("en-IN")} excluded because a required field is missing.</p>}
      </div>
    );
  }

  if (!data.labels?.length) return <p className="muted">No data matches these settings.</p>;

  const datasets = data.datasets.map((d, i) => ({
    ...d,
    backgroundColor: type === "pie" ? data.labels.map((_, j) => PALETTE[j % PALETTE.length]) : PALETTE[i % PALETTE.length],
    borderColor: type === "line" ? PALETTE[i % PALETTE.length] : "#ffffff",
    borderWidth: type === "line" ? 2 : type === "pie" ? 1 : 0,
    tension: 0.25,
    pointRadius: type === "line" && data.labels.length > 40 ? 0 : 3,
  }));
  const multi = datasets.length > 1;
  const options = {
    ...base,
    plugins: { ...base.plugins, legend: { display: multi || type === "pie", position: type === "pie" ? "right" : "top", labels: { usePointStyle: true, boxWidth: 8, padding: 18 } } },
    ...(type === "pie" ? {} : { scales: { x: { grid: { display: false }, ticks: { color: "#64748b", autoSkip: true, maxTicksLimit: 10, maxRotation: 35, minRotation: 0 } }, y: { beginAtZero: true, grid: { color: "rgba(148,163,184,.16)" }, ticks: { color: "#64748b", callback: (v) => Number(v).toLocaleString("en-IN") } } } }),
  };
  const chartData = { labels: data.labels, datasets };
  const Component = { bar: Bar, histogram: Bar, line: Line, pie: Pie }[type] || Bar;

  return (
    <div className="chart-box">
      <Component ref={ref} data={chartData} options={options} plugins={[valueLabels]} />
      {data.meta?.truncated && <p className="muted small">Showing the top results only.</p>}
      {data.meta?.rows_used != null && <p className="muted small chart-quality-note">Validated visual scope: {Number(data.meta.rows_used).toLocaleString("en-IN")} records used{(data.meta.rows_excluded_missing || data.meta.rows_missing_measure) ? ` · ${Number((data.meta.rows_excluded_missing || 0) + (data.meta.rows_missing_measure || 0)).toLocaleString("en-IN")} excluded only where required values are missing` : ""}{data.meta.missing_category_policy === "label_as_not_recorded" ? " · unrecorded categories shown separately" : ""}.</p>}
    </div>
  );
});

export default ChartView;
