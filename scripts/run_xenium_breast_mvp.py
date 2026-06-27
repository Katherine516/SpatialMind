import html
import json
import os
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from spatialmind.ingestion import apply_best_available_labels, build_readiness_report, load_xenium, validate_cell_by_feature_contract
from spatialmind.schemas import SpatialDataset, ToolResult
from spatialmind.storage import StorageLayer
from spatialmind.tools import build_mvp_registry
from spatialmind.viz import VisualizationLayer


DATASET = "data/Human_Breast_Biomarkers_S1_Top_outs"
OUTPUT_ROOT = "outputs/xenium_breast_mvp"
MAX_RECORDS = 6000
MAX_FEATURES_PER_RECORD = 80


PALETTE = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
    "#aec7e8",
    "#ffbb78",
    "#98df8a",
    "#ff9896",
    "#c5b0d5",
    "#c49c94",
    "#f7b6d2",
    "#c7c7c7",
]


def main() -> None:
    run_dir = Path(OUTPUT_ROOT)
    run_dir.mkdir(parents=True, exist_ok=True)
    dataset = load_xenium(DATASET, max_records=MAX_RECORDS)
    dataset.metadata["analysis_dataset_path"] = DATASET
    label_report = apply_best_available_labels(dataset, DATASET, fallback="breast_marker_rule")
    contract = validate_cell_by_feature_contract(dataset)
    readiness = build_readiness_report(dataset)

    registry = build_mvp_registry()
    group1, group2 = _choose_de_groups(dataset)
    tool_plan = [
        ("qc_and_cluster", {"resolution": 0.55, "engine": "prototype"}),
        ("annotation", {"method": "marker_rule_v0"}),
        ("marker_detection", {"group_key": "cell_type", "group1": group1, "group2": group2, "engine": "prototype", "n_top": 20}),
        ("cell_neighborhood_enrichment", {"radius": 35.0, "engine": "prototype"}),
    ]

    results: List[ToolResult] = []
    for tool_name, params in tool_plan:
        result = registry.get(tool_name).run(dataset, params)
        results.append(result)
        _write_json(run_dir / ("%s.json" % tool_name), result)

    cluster_png = _render_cluster_png(dataset, run_dir / "xenium_breast_cluster.png")
    cluster_svg = VisualizationLayer().render_distribution_svg(dataset, str(run_dir), [])
    interactive_html = VisualizationLayer().render_distribution_interactive_html(dataset, str(run_dir), [])
    report_path = _write_report(
        dataset=dataset,
        contract=contract,
        readiness=readiness,
        results=results,
        figure_paths=[cluster_png, cluster_svg, interactive_html],
        output_path=run_dir / "xenium_breast_mvp_report.html",
    )
    run_record = StorageLayer(root=str(run_dir)).write_mvp_run_record(
        query="Annotate the Xenium breast cells and show which cell types are co-located.",
        tool_trace=results,
        params={tool: params for tool, params in tool_plan},
        input_files=[DATASET],
        artifacts={"report": str(report_path)},
        figures=[cluster_png, cluster_svg, interactive_html],
    )

    summary = {
        "dataset": DATASET,
        "output_dir": str(run_dir),
        "records": len(dataset.records),
        "features": len(dataset.genes),
        "cell_types": dataset.cell_types,
        "top_cell_type_counts": Counter(record.cell_type for record in dataset.records).most_common(12),
        "label_readiness": label_report.to_dict(),
        "report": str(report_path),
        "cluster_png": cluster_png,
        "cluster_svg": cluster_svg,
        "interactive_html": interactive_html,
        "run_record": run_record.run_record_path,
        "tools": [result.tool_name for result in results],
    }
    _write_json(run_dir / "run_summary.json", summary)
    print(json.dumps(summary, indent=2))


def _choose_de_groups(dataset: SpatialDataset) -> tuple[str, str]:
    counts = Counter(record.cell_type for record in dataset.records)
    first = "CD8+_T_Cells" if "CD8+_T_Cells" in counts else counts.most_common(1)[0][0]
    second = "Invasive_Tumor" if "Invasive_Tumor" in counts else counts.most_common(2)[-1][0]
    if first == second and len(counts) > 1:
        second = counts.most_common(2)[1][0]
    return first, second


def _render_cluster_png(dataset: SpatialDataset, path: Path) -> str:
    cell_types = dataset.cell_types
    color_by_type = {cell_type: PALETTE[index % len(PALETTE)] for index, cell_type in enumerate(cell_types)}
    fig = plt.figure(figsize=(10.8, 5.4), dpi=180)
    ax = fig.add_axes([0.08, 0.16, 0.50, 0.70])
    legend_ax = fig.add_axes([0.63, 0.12, 0.34, 0.78])
    legend_ax.axis("off")
    ax.set_facecolor("#fbfbf3")
    for cell_type in cell_types:
        xs = [record.x for record in dataset.records if record.cell_type == cell_type]
        ys = [record.y for record in dataset.records if record.cell_type == cell_type]
        ax.scatter(xs, ys, s=3.5, c=color_by_type[cell_type], label=cell_type, alpha=0.72, linewidths=0)
    ax.set_title("Cluster", fontsize=13, pad=8)
    ax.set_xlabel("spatial1")
    ax.set_ylabel("spatial2")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
        spine.set_color("#222222")
    rows = len(cell_types)
    cols = 2 if rows > 10 else 1
    rows_per_col = (rows + cols - 1) // cols
    for index, cell_type in enumerate(cell_types):
        col = index // rows_per_col
        row = index % rows_per_col
        x = 0.02 + col * 0.50
        y = 0.96 - row * (0.92 / max(rows_per_col - 1, 1))
        legend_ax.scatter([x], [y], s=34, c=color_by_type[cell_type], transform=legend_ax.transAxes)
        legend_ax.text(x + 0.04, y, cell_type, fontsize=8.5, va="center", transform=legend_ax.transAxes)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def _write_report(
    dataset: SpatialDataset,
    contract: Any,
    readiness: Any,
    results: List[ToolResult],
    figure_paths: List[str],
    output_path: Path,
) -> Path:
    counts = Counter(record.cell_type for record in dataset.records)
    result_blocks = []
    for result in results:
        result_blocks.append(
            "<section><h3>%s</h3><p>%s</p><pre>%s</pre></section>"
            % (
                html.escape(result.tool_name),
                html.escape(result.summary),
                html.escape(json.dumps(result.metrics, indent=2, sort_keys=True)[:4000]),
            )
        )
    readiness_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (html.escape(item.workflow), html.escape(item.status), html.escape(item.reason))
        for item in readiness.workflows
    )
    count_rows = "".join(
        "<tr><td>%s</td><td>%d</td></tr>" % (html.escape(label), count) for label, count in counts.most_common()
    )
    figure_links = "".join('<li><a href="%s">%s</a></li>' % (html.escape(os.path.basename(path)), html.escape(os.path.basename(path))) for path in figure_paths)
    limitations = [
        "Xenium uses a targeted panel; absence of a gene means it was not measured, not that it is unexpressed.",
        "Cell-type labels are marker-rule MVP labels and should be validated before strong biological interpretation.",
        "Neighborhood enrichment was run with a prototype radius-neighbor method for this report artifact.",
        "No deconvolution, ligand-receptor, pathway, causal, or mechanistic inference was run.",
    ]
    content = """<!doctype html>
<html><head><meta charset="utf-8"><title>SpatialMind Xenium Breast MVP Report</title>
<style>
body{font-family:Arial,sans-serif;margin:32px;color:#1f2933;line-height:1.45}h1,h2{font-weight:600}table{border-collapse:collapse;margin:12px 0 24px;width:100%%;max-width:960px}td,th{border:1px solid #d6dde5;padding:7px 9px;text-align:left}pre{background:#f6f8fa;padding:12px;overflow:auto;max-height:360px}.hero{max-width:980px}.fig{max-width:980px;border:1px solid #d6dde5}
</style></head><body>
<h1>SpatialMind Xenium Breast MVP Report</h1>
<p class="hero">Run time: %s. Dataset: <code>%s</code>. Loaded %d cells and %d features into the v7 <code>CellByFeatureContract</code>.</p>
<h2>Primary Cluster Visualization</h2>
<img class="fig" src="%s" alt="Xenium breast cluster map">
<h2>Figure Artifacts</h2><ul>%s</ul>
<h2>Contract</h2><p>Assay subtype: <b>%s</b>; feature type: <b>%s</b>; resolution: <b>%s</b>; targeted panel: <b>%s</b>.</p>
<h2>Cell-Type Counts</h2><table><tr><th>Cell Type</th><th>Count</th></tr>%s</table>
<h2>Readiness</h2><table><tr><th>Workflow</th><th>Status</th><th>Reason</th></tr>%s</table>
<h2>Results</h2>%s
<h2>Limitations</h2><ul>%s</ul>
</body></html>""" % (
        datetime.now(timezone.utc).isoformat(),
        html.escape(DATASET),
        len(dataset.records),
        len(dataset.genes),
        html.escape(os.path.basename(figure_paths[0])),
        figure_links,
        html.escape(contract.assay_subtype),
        html.escape(contract.feature_type),
        html.escape(contract.resolution),
        html.escape(str(contract.is_targeted_panel)),
        count_rows,
        readiness_rows,
        "\n".join(result_blocks),
        "".join("<li>%s</li>" % html.escape(item) for item in limitations),
    )
    output_path.write_text(content, encoding="utf-8")
    return output_path


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


if __name__ == "__main__":
    main()
