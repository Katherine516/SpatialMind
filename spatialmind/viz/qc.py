import html
import os
from typing import List, Optional

from ..ingestion import IngestionReport
from ..schemas import SpatialDataset


class QCReportBuilder:
    """Dependency-light HTML QC dashboard builder.

    The current renderer is dependency-light but includes the v2 dashboard
    sections: metric distributions, spatial QC overlays, filtration waterfall,
    warnings, and approval guidance.
    """

    def build(self, dataset: SpatialDataset, report: IngestionReport, output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "qc_dashboard.html")
        warnings = report.warnings or dataset.notes
        warning_items = "".join("<li>%s</li>" % html.escape(item) for item in warnings)
        umi_values = [_total_features(record.genes) for record in dataset.records]
        gene_count_values = [_positive_feature_count(record.genes) for record in dataset.records]
        pct_mito_values = [_pct_mito(record.genes) for record in dataset.records]
        distribution_panels = "\n".join(
            [
                _distribution_panel("nUMI", umi_values, "Total normalized feature signal per observation."),
                _distribution_panel("nGenes", gene_count_values, "Detected positive features per observation."),
                _distribution_panel("pct_mito", pct_mito_values, "Percent mitochondrial signal inferred from MT-/mt- features."),
            ]
        )
        spatial_overlay = _spatial_qc_overlay(dataset, umi_values, pct_mito_values)
        waterfall = _filtration_waterfall(report)
        qc_rows = "".join(
            "<tr><td>%s</td><td>%s</td></tr>" % (html.escape(str(key)), html.escape(str(value)))
            for key, value in sorted(report.qc_metrics.items())
        )
        content = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SpatialMind QC Dashboard - %s</title>
  <style>
    body { font-family: Arial, sans-serif; color: #1f2933; margin: 32px; line-height: 1.45; }
    h1 { margin-bottom: 4px; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 12px; margin: 20px 0; }
    .card { border: 1px solid #d9e2ec; padding: 14px; background: #f8fafc; }
    .value { font-size: 24px; font-weight: 700; }
    .section-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; margin: 18px 0; }
    .panel { border: 1px solid #d9e2ec; padding: 14px; background: #fff; }
    .panel h3 { margin: 0 0 8px; font-size: 16px; }
    svg { max-width: 100%%; height: auto; display: block; }
    table { border-collapse: collapse; width: 100%%; margin-top: 20px; }
    td { border-bottom: 1px solid #d9e2ec; padding: 8px; vertical-align: top; }
    ul { color: #7c2d12; }
    .approval { border-left: 4px solid #2563eb; padding: 10px 14px; background: #eff6ff; margin: 18px 0; }
  </style>
</head>
<body>
  <h1>QC Dashboard</h1>
  <p>Sample: <strong>%s</strong></p>
  <div class="approval">Review QC before analysis. API sessions should call the QC approval endpoint before executing analysis tools.</div>
  <div class="grid">
    <div class="card"><div class="value">%d</div><div>Raw observations</div></div>
    <div class="card"><div class="value">%d</div><div>After QC</div></div>
    <div class="card"><div class="value">%d</div><div>Features</div></div>
    <div class="card"><div class="value">%d</div><div>Cell types</div></div>
  </div>
  <h2>Metric Distributions</h2>
  <div class="section-grid">%s</div>
  <h2>Spatial QC Overlay</h2>
  <div class="section-grid">%s</div>
  <h2>Filtration Waterfall</h2>
  <div class="panel">%s</div>
  <h2>Warnings</h2>
  <ul>%s</ul>
  <h2>QC Metrics</h2>
  <table>%s</table>
</body>
</html>
""" % (
            html.escape(dataset.sample_id),
            html.escape(dataset.sample_id),
            report.n_spots_raw,
            report.n_spots_after_qc,
            report.n_genes_after_qc,
            len(dataset.cell_types),
            distribution_panels,
            spatial_overlay,
            waterfall,
            warning_items or "<li>No warnings.</li>",
            qc_rows,
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path


class QCGate:
    def __init__(self) -> None:
        self._approved_sessions: set[str] = set()

    def approve(self, session_id: str) -> None:
        self._approved_sessions.add(session_id)

    def is_approved(self, session_id: Optional[str]) -> bool:
        return bool(session_id and session_id in self._approved_sessions)


def _total_features(genes: dict) -> float:
    return sum(max(float(value), 0.0) for value in genes.values())


def _positive_feature_count(genes: dict) -> float:
    return float(sum(1 for value in genes.values() if float(value) > 0.0))


def _pct_mito(genes: dict) -> float:
    total = _total_features(genes)
    if total <= 0:
        return 0.0
    mito = sum(float(value) for key, value in genes.items() if str(key).upper().startswith("MT-") or str(key).startswith("mt-"))
    return (max(mito, 0.0) / total) * 100.0


def _distribution_panel(title: str, values: List[float], description: str) -> str:
    summary = _summary_stats(values)
    bars = _histogram_svg(values, width=260, height=86)
    return """
<div class="panel">
  <h3>%s</h3>
  <p>%s</p>
  %s
  <p>min %.2f · median %.2f · max %.2f</p>
</div>
""" % (
        html.escape(title),
        html.escape(description),
        bars,
        summary["min"],
        summary["median"],
        summary["max"],
    )


def _histogram_svg(values: List[float], width: int, height: int, bins: int = 18) -> str:
    if not values:
        return '<svg viewBox="0 0 %d %d"><text x="8" y="22">No values</text></svg>' % (width, height)
    low = min(values)
    high = max(values)
    span = max(high - low, 1.0)
    counts = [0 for _ in range(bins)]
    for value in values:
        index = min(bins - 1, int(((value - low) / span) * bins))
        counts[index] += 1
    max_count = max(counts) or 1
    bar_gap = 2
    bar_w = (width - (bins - 1) * bar_gap) / float(bins)
    rects = []
    for index, count in enumerate(counts):
        bar_h = (count / float(max_count)) * (height - 18)
        x = index * (bar_w + bar_gap)
        y = height - bar_h - 16
        rects.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#2f7ebc"/>' % (x, y, bar_w, bar_h))
    return '<svg viewBox="0 0 %d %d" role="img" aria-label="Histogram">%s<line x1="0" y1="%d" x2="%d" y2="%d" stroke="#66717a"/></svg>' % (
        width,
        height,
        "".join(rects),
        height - 16,
        width,
        height - 16,
    )


def _spatial_qc_overlay(dataset: SpatialDataset, umi_values: List[float], pct_mito_values: List[float]) -> str:
    return "\n".join(
        [
            '<div class="panel"><h3>nUMI spatial overlay</h3>%s</div>' % _spatial_metric_svg(dataset, umi_values, "nUMI"),
            '<div class="panel"><h3>pct_mito spatial overlay</h3>%s</div>' % _spatial_metric_svg(dataset, pct_mito_values, "pct_mito"),
        ]
    )


def _spatial_metric_svg(dataset: SpatialDataset, values: List[float], label: str) -> str:
    bounds = dataset.bounds()
    width = 300
    height = 220
    margin = 22
    min_value = min(values) if values else 0.0
    max_value = max(values) if values else 1.0
    span_value = max(max_value - min_value, 1.0)

    def sx(value: float) -> float:
        span = max(bounds["max_x"] - bounds["min_x"], 1.0)
        return margin + ((value - bounds["min_x"]) / span) * (width - margin * 2)

    def sy(value: float) -> float:
        span = max(bounds["max_y"] - bounds["min_y"], 1.0)
        return height - margin - ((value - bounds["min_y"]) / span) * (height - margin * 2)

    points = []
    for record, value in zip(dataset.records, values):
        color = _blue_red((value - min_value) / span_value)
        points.append('<circle cx="%.2f" cy="%.2f" r="3.2" fill="%s" opacity="0.86"/>' % (sx(record.x), sy(record.y), color))
    return """
<svg viewBox="0 0 %d %d" role="img" aria-label="%s spatial QC overlay">
  <rect x="%d" y="%d" width="%d" height="%d" fill="#fbfbf7" stroke="#222"/>
  %s
  <text x="%d" y="%d" font-size="11" fill="#66717a">low %.2f</text>
  <text x="%d" y="%d" font-size="11" fill="#66717a" text-anchor="end">high %.2f</text>
</svg>
""" % (
        width,
        height,
        html.escape(label),
        margin,
        margin,
        width - margin * 2,
        height - margin * 2,
        "".join(points),
        margin,
        height - 4,
        min_value,
        width - margin,
        height - 4,
        max_value,
    )


def _blue_red(value: float) -> str:
    clipped = max(0.0, min(1.0, value))
    red = int(45 + clipped * 190)
    green = int(105 - clipped * 45)
    blue = int(170 - clipped * 120)
    return "#%02x%02x%02x" % (red, green, blue)


def _filtration_waterfall(report: IngestionReport) -> str:
    raw = max(report.n_spots_raw, report.n_spots_after_qc, 1)
    after_qc = report.n_spots_after_qc
    removed_low_counts = int(report.qc_metrics.get("spots_removed_low_counts", 0) or 0)
    removed_low_genes = int(report.qc_metrics.get("spots_removed_low_genes", 0) or 0)
    steps = [
        ("Raw", report.n_spots_raw, "#2f7ebc"),
        ("After QC", after_qc, "#59a14f"),
        ("Low counts removed", removed_low_counts, "#e15759"),
        ("Low genes removed", removed_low_genes, "#f28e2b"),
    ]
    rows = []
    for label, value, color in steps:
        width = max(1.0, (float(value) / float(raw)) * 100.0)
        rows.append(
            '<div style="margin:8px 0;"><strong>%s</strong> %d<div style="height:16px;width:%.2f%%;background:%s;"></div></div>'
            % (html.escape(label), value, width, color)
        )
    return "".join(rows)


def _summary_stats(values: List[float]) -> dict:
    if not values:
        return {"min": 0.0, "median": 0.0, "max": 0.0}
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[mid]
    else:
        median = (ordered[mid - 1] + ordered[mid]) / 2.0
    return {"min": min(values), "median": median, "max": max(values)}
