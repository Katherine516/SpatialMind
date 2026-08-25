import html
import math
import os
from typing import Dict, Iterable, List

from ..schemas import SpatialDataset, ToolResult
from .display_sampling import DEFAULT_DISPLAY_CAP, display_caption, downsample_for_display
from .export import PdfSection, PdfTable, ReportPaths, normalize_report_format, write_pdf_report


PALETTE = [
    "#2f7ebc",
    "#f28e2b",
    "#59a14f",
    "#e15759",
    "#b07aa1",
    "#9c755f",
    "#ff9da7",
    "#edc948",
    "#76b7b2",
    "#4e79a7",
    "#af7aa1",
    "#8cd17d",
    "#b6992d",
    "#499894",
    "#d37295",
    "#fabfd2",
    "#79706e",
    "#86bcb6",
    "#d4a6c8",
    "#bab0ac",
]


class VisualizationLayer:
    """Renders portable artifacts for spatial results."""

    def render_distribution_svg(
        self,
        dataset: SpatialDataset,
        run_dir: str,
        focus_cell_types: List[str],
        max_display_points: int = DEFAULT_DISPLAY_CAP,
    ) -> str:
        bounds = dataset.bounds()
        # One <circle> per cell; cap the drawn set so full sections stay openable.
        display_records, display_info = downsample_for_display(dataset.records, max_points=max_display_points)
        width = 980
        plot_x = 78
        plot_y = 58
        plot_w = 500
        plot_h = 390
        cell_types = focus_cell_types or dataset.cell_types
        color_by_type = {cell_type: PALETTE[index % len(PALETTE)] for index, cell_type in enumerate(cell_types)}
        default_color = "#c7cfd8"
        legend_columns = 2 if len(cell_types) > 10 else 1
        legend_rows = int(math.ceil(len(cell_types) / float(legend_columns))) if cell_types else 1
        height = max(540, plot_y + plot_h + 70, 82 + legend_rows * 24)

        def sx(value: float) -> float:
            span = max(bounds["max_x"] - bounds["min_x"], 1.0)
            return plot_x + ((value - bounds["min_x"]) / span) * plot_w

        def sy(value: float) -> float:
            span = max(bounds["max_y"] - bounds["min_y"], 1.0)
            return plot_y + plot_h - ((value - bounds["min_y"]) / span) * plot_h

        points = []
        radius = 2.7 if len(display_records) > 500 else 4.0
        for record in display_records:
            color = color_by_type.get(record.cell_type, default_color)
            opacity = "0.90" if record.cell_type in color_by_type else "0.20"
            points.append(
                '<circle cx="%.2f" cy="%.2f" r="%.1f" fill="%s" opacity="%s"><title>%s %.1f, %.1f</title></circle>'
                % (sx(record.x), sy(record.y), radius, color, opacity, html.escape(record.cell_type), record.x, record.y)
            )

        legend = []
        legend_x = 625
        legend_y = 74
        legend_col_w = 168
        for index, cell_type in enumerate(cell_types):
            col = index // legend_rows
            row = index % legend_rows
            x = legend_x + col * legend_col_w
            y = legend_y + row * 24
            legend.append('<circle cx="%d" cy="%d" r="6" fill="%s"/>' % (x, y, color_by_type[cell_type]))
            legend.append(
                '<text x="%d" y="%d" fill="#20262d" font-size="13" font-family="Arial, sans-serif">%s</text>'
                % (x + 14, y + 4, html.escape(cell_type))
            )

        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="Spatial cell type distribution">
<rect width="100%%" height="100%%" fill="#ffffff"/>
<text x="%d" y="28" text-anchor="middle" fill="#1f2933" font-size="18" font-family="Arial, sans-serif">Cluster</text>
<text x="%d" y="%d" text-anchor="middle" fill="#1f2933" font-size="14" font-family="Arial, sans-serif">spatial1</text>
<text transform="translate(24 %d) rotate(-90)" text-anchor="middle" fill="#1f2933" font-size="14" font-family="Arial, sans-serif">spatial2</text>
<rect x="%d" y="%d" width="%d" height="%d" fill="#fbfbf7" stroke="#222222" stroke-width="1.2"/>
<text x="%d" y="%d" fill="#66717a" font-size="11" font-family="Arial, sans-serif">%s</text>
%s
%s
</svg>
""" % (
            width,
            height,
            width,
            height,
            plot_x + plot_w / 2,
            plot_x + plot_w / 2,
            plot_y + plot_h + 38,
            plot_y + plot_h / 2,
            plot_x,
            plot_y,
            plot_w,
            plot_h,
            plot_x,
            height - 14,
            html.escape(_image_context_label(dataset)),
            "\n".join(points),
            "\n".join(legend),
        )
        path = os.path.join(run_dir, "spatial_distribution.svg")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(svg)
        return path

    def render_distribution_interactive_html(
        self,
        dataset: SpatialDataset,
        run_dir: str,
        focus_cell_types: List[str],
        max_display_points: int = DEFAULT_DISPLAY_CAP,
    ) -> str:
        bounds = dataset.bounds()
        display_records, display_info = downsample_for_display(dataset.records, max_points=max_display_points)
        cell_types = focus_cell_types or dataset.cell_types
        color_by_type = {cell_type: PALETTE[index % len(PALETTE)] for index, cell_type in enumerate(cell_types)}
        default_color = "#9aa6b2"

        def sx(value: float) -> float:
            span = max(bounds["max_x"] - bounds["min_x"], 1.0)
            return ((value - bounds["min_x"]) / span) * 100.0

        def sy(value: float) -> float:
            span = max(bounds["max_y"] - bounds["min_y"], 1.0)
            return 100.0 - ((value - bounds["min_y"]) / span) * 100.0

        points = []
        for index, record in enumerate(display_records):
            color = color_by_type.get(record.cell_type, default_color)
            opacity = "0.92" if record.cell_type in color_by_type else "0.22"
            feature_total = sum(record.genes.values())
            points.append(
                '<button class="pt" style="left:%.4f%%;top:%.4f%%;background:%s;opacity:%s" data-label="%s" data-x="%.2f" data-y="%.2f" data-total="%.3f" aria-label="%s"></button>'
                % (
                    sx(record.x),
                    sy(record.y),
                    color,
                    opacity,
                    html.escape(record.cell_type, quote=True),
                    record.x,
                    record.y,
                    feature_total,
                    html.escape(record.cell_type, quote=True),
                )
            )
        legend = []
        for cell_type in cell_types:
            legend.append(
                '<span class="legend-item"><span style="background:%s"></span>%s</span>'
                % (color_by_type[cell_type], html.escape(cell_type))
            )

        content = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SpatialMind Interactive Spatial View - %s</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; color: #1f2933; background: #f7f9fb; }
    main { padding: 24px; }
    h1 { font-size: 22px; margin: 0 0 6px; text-align: center; }
    .meta { color: #5f6f7a; margin-bottom: 16px; }
    .layout { display: grid; grid-template-columns: minmax(320px, 720px) minmax(220px, 1fr); gap: 22px; align-items: start; }
    .plot-wrap { display: grid; grid-template-columns: 28px minmax(0, 1fr); grid-template-rows: minmax(0, 1fr) 28px; max-width: 720px; }
    .axis-y { writing-mode: vertical-rl; transform: rotate(180deg); text-align: center; font-size: 13px; color: #1f2933; }
    .axis-x { grid-column: 2; text-align: center; font-size: 13px; color: #1f2933; }
    .plot { position: relative; width: 100%%; aspect-ratio: 1.28; background: #fbfbf7; border: 1px solid #222; overflow: hidden; }
    .pt { position: absolute; width: 8px; height: 8px; border: 0; border-radius: 50%%; transform: translate(-50%%, -50%%); cursor: pointer; }
    .pt:hover, .pt:focus { outline: 2px solid #111827; z-index: 2; }
    .legend { display: grid; grid-template-columns: repeat(2, minmax(120px, 1fr)); gap: 9px 16px; margin: 4px 0 14px; }
    .legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
    .legend-item span { width: 10px; height: 10px; border-radius: 50%%; display: inline-block; }
    #tip { min-height: 24px; color: #334e68; font-size: 13px; }
    @media (max-width: 760px) { .layout { grid-template-columns: 1fr; } .legend { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <h1>Cluster</h1>
    <div class="meta">Sample %s · %d observations · %d features · coordinates: %s</div>
    <div class="layout">
      <div class="plot-wrap">
        <div class="axis-y">spatial2</div>
        <div class="plot" id="plot">%s</div>
        <div></div>
        <div class="axis-x">spatial1</div>
      </div>
      <aside>
        <div class="legend">%s</div>
        <div id="tip">Hover or focus a point for details.</div>
      </aside>
    </div>
  </main>
  <script>
    const tip = document.getElementById('tip');
    document.querySelectorAll('.pt').forEach((point) => {
      point.addEventListener('mouseenter', show);
      point.addEventListener('focus', show);
    });
    function show(event) {
      const p = event.currentTarget.dataset;
      tip.textContent = `${p.label} · x=${p.x}, y=${p.y}, total=${p.total}`;
    }
  </script>
</body>
</html>
""" % (
            html.escape(dataset.sample_id),
            html.escape(dataset.sample_id),
            len(dataset.records),
            len(dataset.genes),
            html.escape(dataset.coordinate_system),
            "\n".join(points),
            "\n".join(legend),
        )
        path = os.path.join(run_dir, "spatial_distribution_interactive.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def render_report(
        self,
        dataset: SpatialDataset,
        prompt: str,
        results: List[ToolResult],
        run_dir: str,
        svg_path: str,
        similar_runs: List[Dict[str, object]],
        report_format: str = "html",
    ) -> ReportPaths:
        normalized_format = normalize_report_format(report_format)
        result_blocks = []
        for result in results:
            metrics = html.escape(_format_metrics(result.metrics))
            caveats = "".join("<li>%s</li>" % html.escape(item) for item in result.caveats)
            result_blocks.append(
                """
<section>
  <h2>%s</h2>
  <p>%s</p>
  <pre>%s</pre>
  <ul>%s</ul>
</section>
"""
                % (html.escape(result.tool_name), html.escape(result.summary), metrics, caveats)
            )

        memory_block = ""
        if similar_runs:
            items = "".join(
                "<li>%s: %s</li>" % (html.escape(str(run.get("run_id"))), html.escape(str(run.get("summary"))))
                for run in similar_runs
            )
            memory_block = "<section><h2>Related prior runs</h2><ul>%s</ul></section>" % items

        relative_svg = os.path.basename(svg_path)
        interactive_path = self.render_distribution_interactive_html(dataset, run_dir, [])
        relative_interactive = os.path.basename(interactive_path)
        content = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SpatialMind Report - %s</title>
  <style>
    body { font-family: Arial, sans-serif; color: #1f2933; margin: 36px; line-height: 1.45; }
    header { border-bottom: 1px solid #d9e2ec; margin-bottom: 24px; padding-bottom: 16px; }
    h1 { font-size: 28px; margin: 0 0 8px; }
    h2 { font-size: 18px; margin-top: 28px; }
    pre { background: #f5f7fa; border: 1px solid #d9e2ec; padding: 12px; overflow-x: auto; }
    img { max-width: 100%%; border: 1px solid #d9e2ec; }
  </style>
</head>
<body>
  <header>
    <h1>SpatialMind Report</h1>
    <p><strong>Sample:</strong> %s</p>
    <p><strong>Request:</strong> %s</p>
  </header>
  <img src="%s" alt="Spatial distribution">
  <p><a href="%s">Open interactive spatial view</a></p>
  %s
  %s
</body>
</html>
""" % (
            html.escape(dataset.sample_id),
            html.escape(dataset.sample_id),
            html.escape(prompt),
            html.escape(relative_svg),
            html.escape(relative_interactive),
            "\n".join(result_blocks),
            memory_block,
        )
        path = os.path.join(run_dir, "report.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        pdf_path = ""
        if normalized_format in {"pdf", "both"}:
            pdf_path = os.path.join(run_dir, "report.pdf")
            pdf_sections = [
                PdfSection(title="Analysis Request", paragraphs=[prompt]),
                PdfSection(
                    title="Spatial Visualization",
                    paragraphs=[
                        "The spatial distribution is available as %s and as an interactive HTML artifact."
                        % os.path.basename(svg_path)
                    ],
                ),
            ]
            for result in results:
                metric_rows = [(str(key), str(value)) for key, value in result.metrics.items()]
                pdf_sections.append(
                    PdfSection(
                        title=result.tool_name,
                        paragraphs=[result.summary],
                        bullets=list(result.caveats),
                        tables=[PdfTable(headers=["Metric", "Value"], rows=metric_rows, column_widths=[1, 3])]
                        if metric_rows
                        else [],
                    )
                )
            if similar_runs:
                pdf_sections.append(
                    PdfSection(
                        title="Related Prior Runs",
                        bullets=["%s: %s" % (run.get("run_id"), run.get("summary")) for run in similar_runs],
                    )
                )
            write_pdf_report(
                pdf_path,
                "SpatialMind Report",
                pdf_sections,
                metadata=[
                    ("Sample", dataset.sample_id),
                    ("Modality", dataset.modality),
                    ("Observations", len(dataset.records)),
                    ("Features", len(dataset.genes)),
                    ("Requested format", normalized_format),
                ],
            )
        return ReportPaths(html=path, pdf=pdf_path)


def _format_metrics(metrics: Dict[str, object]) -> str:
    lines = []
    for key, value in metrics.items():
        lines.append("%s: %s" % (key, value))
    return "\n".join(lines) if lines else "No metrics reported."


def _image_context_label(dataset: SpatialDataset) -> str:
    image_paths = [source.image_path for source in dataset.sources if source.image_path]
    if image_paths:
        return "Morphology image available: %s" % os.path.basename(str(image_paths[0]))
    return "No registered morphology image was rendered in this lightweight view."
