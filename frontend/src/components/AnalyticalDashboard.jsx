import { useState } from "react";
import ChartCard from "./ChartCard.jsx";

const moneyLike = /(revenue|sales|amount|turnover|premium|profit|income|spend|expense|cost|gmv)/i;
const averageLike = /(price|rate|rating|score|satisfaction|age|percent|pct|ratio|margin|discount|average|avg)/i;
const countLike = /(qty|quantity|units|orders|count|visits|clicks|views)/i;

function fmt(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}
function pct(value) {
  return value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value).toFixed(1)}%`;
}
function insightSymbol(item) {
  const type = item?.type || "";
  if (type.includes("financial_overview") || type.includes("outcome_overview")) return "📊";
  if (type.includes("margin") || type.includes("risk")) return "⚠️";
  if (type.includes("contribution") || type.includes("channel_mix")) return "🎯";
  if (type.includes("period")) return "📈";
  if (type.includes("outcome")) return "👥";
  return "💡";
}
function recommendationSymbol(item) {
  const priority = item?.priority || "medium";
  return priority === "high" ? "⚠️" : priority === "low" ? "🌱" : "✅";
}

export default function AnalyticalDashboard({ datasetInfo, analysis, analysisLoading = false, summary, filters, onFilter, onReset, savedWidgets = [], savedData = {}, onRemoveWidget }) {
  const [page, setPage] = useState("Overview");
  const stats = analysis?.numeric_summary || [];
  const categories = analysis?.category_summary || [];
  const times = analysis?.time_series || [];
  const segments = analysis?.segment_analysis || [];
  
  const rows = summary?.rows ?? datasetInfo?.profile?.rows ?? analysis?.dataset?.rows ?? 0;
  const metricCandidates = analysis?.metric_candidates || stats.filter((item) => !/(^|[^a-z])(id|uuid|guid|key|code|index|serial)([^a-z]|$)/i.test(item.column)).map((item) => ({...item, suggested_aggregation: moneyLike.test(item.column) || countLike.test(item.column) ? "sum" : "mean"}));
  const usableMetrics = metricCandidates.filter((item) => Number(item.count) > 0 && Number.isFinite(Number(item.sum ?? item.mean)));
  const selectedMetrics = usableMetrics.slice(0, 4);
  const aggregationFor = (column) => metricCandidates.find((item) => item.column === column)?.suggested_aggregation || (averageLike.test(column || "") ? "mean" : "sum");
  const valueFor = (group, aggregation) => aggregation === "mean" ? group?.mean : group?.sum;
  const metricValue = (metric) => {
    const live = summary?.numeric_summary?.find((item) => item.column === metric?.column) || metric;
    return metric?.suggested_aggregation === "mean" ? live?.mean : live?.sum;
  };
  const metricCards = (analysis?.kpis?.length ? analysis.kpis : selectedMetrics.map((metric) => ({
    label: `${metric.suggested_aggregation === "mean" ? "Average" : "Total"} ${metric.column}`,
    column: metric.column, aggregation: metric.suggested_aggregation, value: metricValue(metric),
    valid_records: metric.count, missing: metric.missing,
  }))).slice(0, 5).map((metric) => {
    const filteredMetric = metric.column ? summary?.numeric_summary?.find((item) => item.column === metric.column) : null;
    const currentValue = metric.aggregation === "count" ? rows
      : metric.aggregation === "mean" ? (filteredMetric?.mean ?? metric.value)
      : metric.aggregation === "sum" ? (filteredMetric?.sum ?? metric.value)
      : metric.value;
    const validRecords = metric.aggregation === "count" ? rows : (filteredMetric?.count ?? metric.valid_records);
    const missing = filteredMetric ? Math.max(0, rows - filteredMetric.count) : metric.missing;
    const detail = metric.aggregation === "count" ? "Rows in the current filter"
      : metric.aggregation === "rate" ? (filters?.length ? "Whole-dataset baseline; outcome rate is not recalculated by dashboard filters" : `${fmt(metric.valid_records)} recorded outcomes`)
      : `${fmt(validRecords)} valid records · ${fmt(missing)} missing`;
    return {
      label: metric.label,
      aggregation: metric.aggregation,
      value: metric.aggregation === "rate" ? pct(currentValue) : fmt(currentValue),
      detail,
    };
  });
  const primaryKpiIndex = metricCards.findIndex((metric) => metric.aggregation !== "count");
  const primary = selectedMetrics[0] || null;
  const businessInsights = analysis?.business_insights || [];
  const outcomeInsight = businessInsights.find((item) => item.type === "outcome_segment");
  const segmentInsight = outcomeInsight || businessInsights.find((item) => item.type === "segment_comparison");
  const segmentMeasure = segmentInsight?.measure || primary?.column;
  const segmentDimension = segmentInsight?.dimension;
  const bestSegment = segments.find((item) => item.measure === segmentMeasure && item.category === segmentDimension) ||
    segments.find((item) => item.measure === segmentMeasure && item.groups?.length > 1);
  const segmentAggregation = segmentInsight?.aggregation || aggregationFor(segmentMeasure);
  const rankedGroups = bestSegment?.groups?.slice().sort((a, b) => Number(valueFor(b, segmentAggregation) ?? -Infinity) - Number(valueFor(a, segmentAggregation) ?? -Infinity)) || [];
  const insightHigh = segmentInsight?.high_group;
  const insightLow = segmentInsight?.low_group;
  const bestGroup = insightHigh ? { ...insightHigh, displayValue: segmentAggregation === "rate" ? insightHigh.rate_pct : insightHigh.mean } : rankedGroups[0];
  const worstGroup = insightLow ? { ...insightLow, displayValue: segmentAggregation === "rate" ? insightLow.rate_pct : insightLow.mean } : rankedGroups[rankedGroups.length - 1];
  const primaryTrend = times.find((item) => item.measure === primary?.column && item.periods?.length > 1) || times.find((item) => item.periods?.length > 1);
  const trendAggregation = aggregationFor(primaryTrend?.measure);
  const trendValue = (period) => valueFor(period, trendAggregation);
  const trendPeriods = (primaryTrend?.periods || []).filter((period) => {
    const value = trendValue(period);
    return value != null && Number.isFinite(Number(value));
  });
  const previous = trendPeriods.length > 1 ? trendPeriods[trendPeriods.length - 2] : null;
  const latest = trendPeriods.length ? trendPeriods[trendPeriods.length - 1] : null;
  const previousValue = trendValue(previous);
  const latestValue = trendValue(latest);
  const trendChange = previous && latest && Number.isFinite(Number(previousValue)) && Number.isFinite(Number(latestValue)) && Number(previousValue) !== 0 ? ((latestValue - previousValue) / Math.abs(previousValue)) * 100 : null;
  const trendData = primaryTrend && trendPeriods.length > 1 ? { labels: trendPeriods.map((p) => p.period), datasets: [{ label: (trendAggregation === "mean" ? "Average " : "Total ") + primaryTrend.measure, data: trendPeriods.map(trendValue) }] } : null;
  const suggestedVisuals = analysis?.suggested_visuals || [];
  const outcomeBreakdownVisual = suggestedVisuals.find((item) => item.spec?.metric === "outcome_count" && item.data);
  const outcomeVisual = suggestedVisuals.find((item) => item.spec?.metric === "rate" && item.spec?.x === segmentDimension && item.data?.meta?.measure === segmentMeasure);
  const numericSegmentVisual = suggestedVisuals.find((item) => item.spec?.x === segmentDimension && item.spec?.y === segmentMeasure && item.spec?.agg === segmentAggregation && item.data);
  const segmentData = outcomeVisual?.data || numericSegmentVisual?.data || (bestSegment ? { labels: bestSegment.groups.map((g) => g.value), datasets: [{ label: (segmentAggregation === "mean" ? "Average " : "Total ") + bestSegment.measure, data: bestSegment.groups.map((g) => valueFor(g, segmentAggregation)) }] } : null);
  const segmentChartDimension = outcomeVisual?.spec?.x || numericSegmentVisual?.spec?.x || bestSegment?.category;
  const segmentChartMeasure = outcomeVisual?.data?.meta?.measure || numericSegmentVisual?.spec?.y || bestSegment?.measure || segmentMeasure;
  const category = categories.find((item) => item.unique > 1 && item.unique <= 12 && item.top_values?.length > 1);
  const categoryData = category ? { labels: category.top_values.map((v) => v.value), datasets: [{ label: "Records", data: category.top_values.map((v) => v.count) }] } : null;
  const builtInPages = ["Overview", "Performance", "Trends", "Insights"];
  const savedPageAliases = new Set(["Segments", "Distributions", "Trends", "Overview"]);
  const savedPages = [...new Set(savedWidgets.map((w) => w.page || "Saved analysis"))].filter((name) => !builtInPages.includes(name) && !savedPageAliases.has(name));
  const pages = [...builtInPages, ...savedPages];
  const findings = businessInsights;
  const recommendations = analysis?.recommendations || [];
  const nextSteps = recommendations.length ? recommendations : businessInsights.map((item) => ({ id: item.id, title: item.title, action: item.action, priority: "medium" }));
  const correlations = analysis?.correlations || [];
  const pageDescription = {
    Overview: "A decision-ready summary of the dataset's current condition and strongest signals.",
    Performance: "Find the segments and categories contributing most to the selected measure.",
    Trends: "Understand how the selected measure changes over time. Trends are shown only when a usable date field exists.",
    Insights: "Evidence-backed performance patterns, period changes and practical next steps discovered from this dataset."
  };

  return (
    <section className="analytical-dashboard">
      <header className="analytical-page-header">
        <div><span className="eyebrow">DATA-DRIVEN ANALYSIS</span><h2>{page}</h2><p className="muted small">{pageDescription[page]}</p></div>
        <span className="badge">{Number(rows).toLocaleString("en-IN")} records · {datasetInfo?.schema?.length || datasetInfo?.profile?.columns || 0} fields</span>
      </header>
      <nav className="analytical-tabs" aria-label="Analytical dashboard pages">
        {pages.map((item, index) => <button key={item} type="button" className={page === item ? "active" : ""} onClick={() => setPage(item)}><span>{String(index + 1).padStart(2, "0")}</span>{item}</button>)}
      </nav>

      {page === "Overview" && <>
        <div className="analytical-kpi-grid">
          {metricCards.map((metric, index) => <article className={`card analytical-kpi ${index === 0 ? "kpi-primary" : ""}`} key={metric.label}><span className="eyebrow">{metric.aggregation === "count" ? "DATASET SIZE" : index === primaryKpiIndex ? "PRIMARY KPI" : "SUPPORTING KPI"}</span><strong>{metric.value}</strong><b>{metric.label}</b><small>{metric.detail}</small></article>)}
        </div>
        <div className="analytical-insight-row">
          <article className="card"><span className="eyebrow">LATEST PERIOD · {primaryTrend?.measure || "DATA SIGNAL"}</span><strong>{latest ? fmt(averageLike.test(primaryTrend.measure) && !moneyLike.test(primaryTrend.measure) ? latest.mean : latest.sum) : "Not available"}</strong><p>{latest ? `${primaryTrend.measure} in ${latest.period}` : "No multi-period date series detected"}</p>{trendChange != null && <small className={trendChange >= 0 ? "signal-positive" : "signal-negative"}>{trendChange >= 0 ? "↑" : "↓"} {Math.abs(trendChange).toFixed(1)}% vs previous period</small>}</article>
          <article className="card"><span className="eyebrow">HIGHEST OBSERVED {segmentAggregation === "rate" ? "RATE" : "VALUE"}</span><strong>{segmentInsight ? (bestGroup?.value || "Not available") : "Not available"}</strong><p>{segmentInsight ? segmentDimension + " · " + (segmentAggregation === "rate" ? "Rate " : segmentAggregation === "mean" ? "Average " : "Total ") + segmentMeasure + ": " + (segmentAggregation === "rate" ? pct(bestGroup?.displayValue) : fmt(bestGroup?.displayValue)) : "No supported segment comparison detected"}</p><small>{segmentAggregation === "rate" ? "Outcome rate; missing outcomes excluded" : "Uses the aggregation stated by the finding"}</small></article>
          <article className="card"><span className="eyebrow">LOWEST OBSERVED {segmentAggregation === "rate" ? "RATE" : "VALUE"}</span><strong>{segmentInsight ? (worstGroup?.value || "Not available") : "Not available"}</strong><p>{segmentInsight ? segmentDimension + " · " + (segmentAggregation === "rate" ? "Rate " : segmentAggregation === "mean" ? "Average " : "Total ") + segmentMeasure + ": " + (segmentAggregation === "rate" ? pct(worstGroup?.displayValue) : fmt(worstGroup?.displayValue)) : "No supported segment comparison detected"}</p><small>Observed difference is not proof of causation</small></article>
        </div>
        <div className="grid charts analytical-chart-grid">
          {trendData && <ChartCard title={`${primaryTrend.measure} trend`} subtitle={`By ${primaryTrend.date_column} · latest period compared with previous`} type="line" data={trendData} onPointClick={(v) => onFilter(primaryTrend.date_column, v)} onReset={() => onReset(primaryTrend.date_column)} />}
          {outcomeBreakdownVisual && <ChartCard title={`${outcomeBreakdownVisual.data.meta.measure} outcome breakdown`} subtitle={`${fmt(outcomeBreakdownVisual.data.meta.valid_records)} valid records · ${fmt(outcomeBreakdownVisual.data.meta.missing_records)} missing outcomes excluded`} type="bar" data={outcomeBreakdownVisual.data} />}
          {segmentData && segmentChartDimension && <ChartCard title={`${segmentChartMeasure} by ${segmentChartDimension}`} subtitle="Compare the selected measure across groups" type="bar" data={segmentData} onPointClick={(v) => onFilter(segmentChartDimension, v)} onReset={() => onReset(segmentChartDimension)} />}
          {categoryData && <ChartCard title={`${category.column} mix`} subtitle="Record distribution across leading categories" type="pie" data={categoryData} onPointClick={(v) => onFilter(category.column, v)} onReset={() => onReset(category.column)} />}
        </div>
        <section className="card analytical-priority-list"><div className="section-heading"><div><span className="eyebrow">WHAT NEEDS ATTENTION</span><h3>Priority findings</h3></div><span className="badge">{analysisLoading ? "Calculating insights…" : `${findings.length} priority insights`}</span></div>{analysisLoading ? <p className="muted small">Calculating outcome rates and supported segment findings…</p> : findings.slice(0, 3).map((item) => <article key={item.id}><span className={`severity-dot severity-${item.severity || "info"}`}/><div><strong>{item.title}</strong><p>{item.evidence}</p></div></article>)}</section>
      </>}

      {page === "Performance" && <>
        <div className="grid charts analytical-chart-grid">
          {outcomeBreakdownVisual && <ChartCard title={`${outcomeBreakdownVisual.data.meta.measure} outcome breakdown`} subtitle={`${fmt(outcomeBreakdownVisual.data.meta.valid_records)} valid records · ${fmt(outcomeBreakdownVisual.data.meta.missing_records)} missing outcomes excluded`} type="bar" data={outcomeBreakdownVisual.data} />}
          {segmentData && segmentChartDimension && <ChartCard title={`${segmentChartMeasure} by ${segmentChartDimension}`} subtitle="Compare the strongest observed groups" type="bar" data={segmentData} onPointClick={(v) => onFilter(segmentChartDimension, v)} onReset={() => onReset(segmentChartDimension)} />}
          {categoryData && <ChartCard title={`${category.column} distribution`} subtitle="Share of records by category" type="pie" data={categoryData} onPointClick={(v) => onFilter(category.column, v)} onReset={() => onReset(category.column)} />}
        </div>
        <section className="card"><span className="eyebrow">SEGMENT SCORECARD</span><h3>Where performance is concentrated</h3>{bestSegment || outcomeVisual || numericSegmentVisual ? <div className="table-wrap"><table><thead>{outcomeVisual ? <tr><th>{outcomeVisual.spec.x}</th><th>Positive outcomes</th><th>Valid outcome records</th><th>{outcomeVisual.data.meta?.measure ? outcomeVisual.data.meta.measure + " rate" : "Outcome rate"}</th></tr> : numericSegmentVisual ? <tr><th>{numericSegmentVisual.spec.x}</th><th>{segmentAggregation === "mean" ? "Average" : "Total"} {segmentMeasure}</th><th>Records</th></tr> : bestSegment ? <tr><th>{bestSegment.category}</th><th>{segmentAggregation === "mean" ? "Average" : "Total"} {bestSegment.measure}</th><th>Records</th></tr> : <tr><th>{segmentDimension}</th><th>{segmentAggregation === "mean" ? "Average" : "Total"} {segmentMeasure}</th></tr>}</thead><tbody>{outcomeVisual ? outcomeVisual.data.labels.map((label, index) => <tr key={label}><td>{label}</td><td>{fmt(outcomeVisual.data.meta?.positive_counts?.[index])}</td><td>{fmt(outcomeVisual.data.meta?.group_counts?.[index])}</td><td>{pct(outcomeVisual.data.datasets?.[0]?.data?.[index])}</td></tr>) : numericSegmentVisual ? numericSegmentVisual.data.labels.map((label,index)=><tr key={label}><td>{label}</td><td>{fmt(numericSegmentVisual.data.datasets?.[0]?.data?.[index])}</td><td>{fmt(numericSegmentVisual.data.meta?.group_counts?.[index])}</td></tr>) : bestSegment ? bestSegment.groups.slice().sort((a,b)=>Number(valueFor(b,segmentAggregation)??-Infinity)-Number(valueFor(a,segmentAggregation)??-Infinity)).map(g=><tr key={g.value}><td>{g.value}</td><td>{fmt(valueFor(g,segmentAggregation))}</td><td>{fmt(g.count)}</td></tr>) : null}</tbody></table></div> : <p className="muted">No sufficiently supported segment comparison is available for this dataset.</p>}</section>
        {correlations.length > 0 && <section className="card"><span className="eyebrow">RELATIONSHIPS</span><h3>Strongest numeric associations</h3><div className="table-wrap"><table><thead><tr><th>Measure A</th><th>Measure B</th><th>Correlation</th><th>Interpretation</th></tr></thead><tbody>{correlations.slice(0,8).map((c,i)=><tr key={i}><td>{c.left}</td><td>{c.right}</td><td>{Number(c.correlation).toFixed(3)}</td><td>{Math.abs(c.correlation)>=.65?"Strong association":Math.abs(c.correlation)>=.3?"Moderate association":"Weak association"}</td></tr>)}</tbody></table></div><p className="muted small">Correlation describes association, not causation.</p></section>}
      </>}

      {page === "Trends" && <>
        {trendData ? <div className="grid charts analytical-chart-grid"><ChartCard title={`${primaryTrend.measure} over time`} subtitle={`Monthly aggregation using ${primaryTrend.date_column}`} type="line" data={trendData} onPointClick={(v) => onFilter(primaryTrend.date_column, v)} onReset={() => onReset(primaryTrend.date_column)} /></div> : <div className="card empty-state"><span>⌁</span><strong>No usable time series</strong><p className="muted">A date field with multiple periods and a numeric measure is required to show trends. No trend has been fabricated.</p></div>}
        {trendPeriods.length > 0 && <section className="card"><span className="eyebrow">PERIOD DETAIL</span><h3>Latest observed periods</h3><div className="table-wrap"><table><thead><tr><th>Period</th><th>Records</th><th>Total</th><th>Average</th></tr></thead><tbody>{trendPeriods.slice().reverse().slice(0,12).map(p=><tr key={p.period}><td>{p.period}</td><td>{fmt(p.count)}</td><td>{fmt(p.sum)}</td><td>{fmt(p.mean)}</td></tr>)}</tbody></table></div></section>}
        <p className="muted small">Forecasting is not displayed unless a validated forecasting method and sufficient history are available.</p>
      </>}

      {page === "Insights" && <>
        <section className="card"><div className="section-heading"><div><span className="eyebrow">EVIDENCE-BASED FINDINGS</span><h3>What the data is telling you</h3></div><span className="badge">{analysisLoading ? "Calculating insights…" : `${findings.length} executive insights`}</span></div><div className="analytical-insight-cards">{analysisLoading ? <p className="muted small">Calculating evidence-backed findings…</p> : findings.map(item=><article key={item.id}><span className={`severity-dot severity-${item.severity || "info"}`}/><div><strong><span className="insight-symbol" aria-hidden="true">{insightSymbol(item)}</span> {item.title}</strong><p>{item.evidence}</p><small>{item.impact || item.interpretation}</small>{item.action && <p className="insight-next-action"><b>What this means:</b> {item.action}</p>}</div></article>)}</div></section>
        {(analysis?.suggested_visuals || []).filter((item) => item.data && (item.spec?.metric === "outcome_count" || findings.some((finding) => finding.dimension === item.spec?.x && finding.measure === (item.data?.meta?.measure || item.spec?.y)))).length > 0 && <section className="card"><div className="section-heading"><div><span className="eyebrow">VISUAL EVIDENCE</span><h3>Charts supporting priority insights</h3><p className="muted small">Only visuals linked to the selected headline findings are shown here.</p></div></div><div className="grid charts analytical-chart-grid">{analysis.suggested_visuals.filter((item) => item.data && (item.spec?.metric === "outcome_count" || findings.some((finding) => finding.dimension === item.spec?.x && finding.measure === (item.data?.meta?.measure || item.spec?.y)))).map((item) => <ChartCard key={item.id} title={item.title} subtitle={item.reason} type={item.spec.type} data={item.data} onPointClick={(value) => onFilter(item.spec.x, value)} onReset={() => onReset(item.spec.x)} />)}</div></section>}
        <section className="card"><div className="section-heading"><div><span className="eyebrow">RECOMMENDED NEXT STEPS</span><h3>What to do next</h3></div><span className="badge">{nextSteps.length} recommendations</span></div><div className="analytical-recommendations">{nextSteps.map(item=><article key={item.id}><span className={`priority-pill priority-${item.priority || "medium"}`}>{recommendationSymbol(item)} {item.priority || "medium"} priority</span><div><strong>{item.title}</strong><p>{item.action}</p></div></article>)}</div></section>
        {analysis?.analyst_questions?.length > 0 && <section className="card"><span className="eyebrow">QUESTIONS FOR THE ANALYST</span><h3>Validate before making a decision</h3><ol>{analysis.analyst_questions.map((q,i)=><li key={i}>{q}</li>)}</ol></section>}
      </>}
      {(() => {
        const aliases = page === "Performance" ? ["Segments", "Distributions"] : page === "Overview" ? ["Overview"] : [page];
        const visuals = savedWidgets.filter((w) => aliases.includes(w.page || "Overview"));
        if (!visuals.length) return null;
        return <section className="saved-analytical-visuals">
          <div className="section-heading"><div><span className="eyebrow">SAVED ANALYSIS</span><h3>Additional dashboard visuals</h3><p className="muted small">These saved visuals belong to this analytical page and use the same filters.</p></div><span className="badge">{visuals.length} visuals</span></div>
          <div className="grid charts analytical-chart-grid">{visuals.map((w) => w.display_type === "table" ? <section className="card dashboard-pivot-card" key={w.id}>
            <header className="row between"><div><span className="eyebrow">SAVED TABLE</span><h3>{w.title}</h3></div><span className="badge">{w.table_rows?.length || 0} groups</span></header>
            <div className="table-wrap dashboard-pivot-scroll"><table><thead><tr>{(w.table_columns || []).map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{(savedData[w.id]?.table_rows || w.table_rows || []).map((row, ri) => <tr key={ri}>{(w.table_columns || []).map((column) => <td key={column}>{typeof row[column] === "number" ? fmt(row[column]) : String(row[column] ?? "—")}</td>)}</tr>)}</tbody></table></div>
            {onRemoveWidget && <button className="btn btn-ghost small no-print" onClick={() => onRemoveWidget(w.id)}>Remove</button>}
          </section> : <ChartCard key={w.id} title={w.title} subtitle={`${w.page || page} · Click a segment to cross-filter`} type={w.spec?.type || "bar"} data={savedData[w.id]?.data} onPointClick={(value) => onFilter(w.spec?.x, value)} onReset={() => onReset(w.spec?.x)} isFiltered={filters.some((f) => f.column === w.spec?.x)}>
            {onRemoveWidget && <button className="btn btn-ghost small no-print" onClick={() => onRemoveWidget(w.id)}>Remove</button>}
          </ChartCard>)}</div>
        </section>;
      })()}
    </section>
  );
}
