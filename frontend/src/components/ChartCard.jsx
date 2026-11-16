import { useRef } from "react";
import ChartView from "./ChartView.jsx";
import { downloadDataUrl, slug } from "../utils.js";

/** A titled chart with a "Download PNG" button and optional extra actions (children). */
export default function ChartCard({ title, subtitle, type, data, children, printMode = false, onPointClick, onReset, isFiltered = false }) {
  const chartRef = useRef(null);

  function downloadPng() {
    const chart = chartRef.current;
    if (!chart) return;
    // Chart.js draws on a transparent canvas; export with a white background so it pastes into slides/docs.
    const canvas = chart.canvas;
    const out = document.createElement("canvas");
    out.width = canvas.width;
    out.height = canvas.height;
    const ctx = out.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(canvas, 0, 0);
    downloadDataUrl(out.toDataURL("image/png"), `${slug(title)}.png`);
  }

  return (
    <section className="card chart-card">
      <header className="row between">
        <div>
          <h3>{title}</h3>
          {subtitle && <p className="muted small">{subtitle}</p>}
        </div>
        <div className="row wrap chart-header-actions no-print">
          {isFiltered && <span className="badge chart-filter-badge">Filtered</span>}
          {isFiltered && onReset && <button className="btn btn-outline small" type="button" onClick={onReset} title={`Clear the ${title} selection`}>↺ Reset visual</button>}
          {data && !data.error && <button className="btn btn-ghost small" type="button" onClick={downloadPng} aria-label={`Download ${title} as PNG`}>⬇ PNG</button>}
        </div>
      </header>
      <ChartView ref={chartRef} type={type} data={data} printMode={printMode} onPointClick={onPointClick} />
      {children && <div className="row wrap no-print card-actions">{children}</div>}
    </section>
  );
}
