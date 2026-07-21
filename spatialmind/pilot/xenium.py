import html
import json
import uuid
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from spatialmind.agent.runtime import DEFAULT_XENIUM_INPUTS, build_xenium_mvp_plan, validate_tool_plan
from spatialmind.ingestion import (
    apply_best_available_labels,
    apply_best_available_regions,
    build_readiness_report,
    load_xenium,
    summarize_xenium_expert_readiness,
    validate_cell_by_feature_contract,
    write_expert_label_template,
    write_region_label_template,
)
from spatialmind.pilot.claims import build_pilot_claim_ledger, build_pilot_claim_reliability, claim_ledger_summary
from spatialmind.schemas import SpatialDataset, ToolResult
from spatialmind.storage import StorageLayer
from spatialmind.tools import build_mvp_registry
from spatialmind.tools.implementations import run_neighborhood_robustness
from spatialmind.viz import (
    PdfFigure,
    PdfSection,
    PdfTable,
    VisualizationLayer,
    XeniumExplorerLiteViewer,
    normalize_report_format,
    write_pdf_report,
)


DEFAULT_DATASET = "data/Human_Breast_Biomarkers_S1_Top_outs"
DEFAULT_OUTPUT = "outputs/xenium_validated_pilot"


def run_pilot(
    dataset_path: str,
    output_dir: Path,
    max_records: int = 5000,
    min_label_coverage: float = 0.7,
    min_region_coverage: float = 0.7,
    allow_single_region: bool = False,
    report_format: str = "html",
) -> Dict[str, Any]:
    normalized_format = normalize_report_format(report_format)
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset = load_xenium(dataset_path, max_records=max_records)
    dataset.metadata["analysis_dataset_path"] = dataset_path
    label_report = apply_best_available_labels(dataset, dataset_path, fallback=None)
    region_report = apply_best_available_regions(dataset, dataset_path)
    contract = validate_cell_by_feature_contract(dataset)
    readiness = build_readiness_report(dataset)
    asset_readiness = summarize_xenium_expert_readiness(dataset_path)

    label_template = write_expert_label_template(
        dataset,
        str(output_dir / "expert_label_template.csv"),
        max_rows=max_records,
        dataset_path=dataset_path,
    )
    region_template = write_region_label_template(
        dataset,
        str(output_dir / "region_label_template.csv"),
        max_rows=max_records,
        dataset_path=dataset_path,
    )

    gate = pilot_gate(
        dataset=dataset,
        asset_readiness=asset_readiness.to_dict(),
        label_report=label_report.to_dict(),
        region_report=region_report.to_dict(),
        min_label_coverage=min_label_coverage,
        min_region_coverage=min_region_coverage,
        allow_single_region=allow_single_region,
    )

    results: List[ToolResult] = []
    review_figures = _write_review_figures(dataset, output_dir)
    figures: List[str] = list(review_figures)
    registry = build_mvp_registry()
    plan = build_xenium_mvp_plan()
    plan_validation = validate_tool_plan(
        plan,
        available_inputs=_pilot_structural_inputs(),
        registry_tool_names=[tool.name for tool in registry.list_all()],
    )
    if gate["status"] == "validated_ready" and not plan_validation.ok:
        gate["status"] = "blocked_invalid_tool_plan"
        gate["blocking_reasons"].extend(plan_validation.errors)
        gate["required_next_inputs"].append("Fix the typed Xenium MVP tool plan before running analysis.")

    spatial_robustness: Dict[str, Any] = {
        "status": "not_run",
        "score": 0.0,
        "reason": "Neighborhood robustness sweep runs only for validated pilots.",
    }
    if gate["status"] == "validated_ready":
        results = _run_validated_tools(dataset, plan)
        for result in results:
            _write_json(output_dir / ("%s.json" % result.tool_name), result)
        figures.extend(_write_figures(dataset, output_dir))
        spatial_robustness = run_neighborhood_robustness(dataset)

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": dataset_path,
        "output_dir": str(output_dir),
        "status": gate["status"],
        "blocking_reasons": gate["blocking_reasons"],
        "required_next_inputs": gate["required_next_inputs"],
        "records_loaded": len(dataset.records),
        "features_loaded": len(dataset.genes),
        "cell_types": dataset.cell_types,
        "regions": sorted({record.region for record in dataset.records if record.region}),
        "cell_type_counts": dict(Counter(record.cell_type for record in dataset.records)),
        "region_counts": dict(Counter(record.region or "unassigned" for record in dataset.records)),
        "label_report": label_report.to_dict(),
        "region_report": region_report.to_dict(),
        "asset_readiness": asset_readiness.to_dict(),
        "workflow_readiness": _jsonable(readiness),
        "contract": _jsonable(contract),
        "tool_plan": _jsonable(plan),
        "plan_validation": _jsonable(plan_validation),
        "expert_label_template": label_template,
        "region_label_template": region_template,
        "tools": [result.tool_name for result in results],
        "review_figures": review_figures,
        "figures": figures,
        "figure_policy": {
            "review_figures": "Generated from current loader labels/clusters for expert review and QA only.",
            "validated_figures": "Generated only after expert labels and user regions pass the pilot gate.",
        },
        "spatial_robustness": spatial_robustness,
        "report_md": str(output_dir / "validated_xenium_pilot_report.md"),
        "report_html": str(output_dir / "validated_xenium_pilot_report.html"),
        "report_pdf": str(output_dir / "validated_xenium_pilot_report.pdf")
        if normalized_format in {"pdf", "both"}
        else "",
        "report_format": normalized_format,
        "report_path": str(output_dir / "validated_xenium_pilot_report.pdf")
        if normalized_format == "pdf"
        else str(output_dir / "validated_xenium_pilot_report.html"),
        "run_record_path": "",
    }
    planned_run_id = "mvp_%s_%s" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8])
    payload["run_record_path"] = str(output_dir / "runs" / ("%s.json" % planned_run_id))
    payload["claim_ledger"] = build_pilot_claim_ledger(payload, results)
    payload["claim_reliability"] = build_pilot_claim_reliability(payload, results)
    payload["claim_summary"] = claim_ledger_summary(payload["claim_ledger"])
    _write_markdown_report(output_dir / "validated_xenium_pilot_report.md", payload, results)
    _write_html_report(output_dir / "validated_xenium_pilot_report.html", payload, results)
    if payload["report_pdf"]:
        _write_pilot_pdf_report(Path(payload["report_pdf"]), payload, results)
    _write_json(output_dir / "pilot_validation.json", payload)
    report_artifacts = {
        "pilot_validation": str(output_dir / "pilot_validation.json"),
        "markdown_report": str(output_dir / "validated_xenium_pilot_report.md"),
        "html_report": str(output_dir / "validated_xenium_pilot_report.html"),
    }
    if payload["report_pdf"]:
        report_artifacts["pdf_report"] = payload["report_pdf"]
    run_record = StorageLayer(root=str(output_dir)).write_mvp_run_record(
        query="Validated Xenium pilot: annotate cells, summarize user regions, and test neighborhoods.",
        tool_trace=[{"tool_name": result.tool_name, "summary": result.summary, "metrics": result.metrics} for result in results],
        params={
            "max_records": max_records,
            "min_label_coverage": min_label_coverage,
            "min_region_coverage": min_region_coverage,
            "allow_single_region": allow_single_region,
            "report_format": normalized_format,
            "tool_plan": _jsonable(plan),
        },
        input_files=[dataset_path],
        artifacts=report_artifacts,
        figures=figures,
        tables=[label_template, region_template],
        run_id=planned_run_id,
    )
    payload["run_record_path"] = run_record.run_record_path
    return payload


def scan_pilot_readiness(
    dataset_paths: List[str],
    output_dir: Path,
    max_records: int = 1200,
    min_label_coverage: float = 0.7,
    min_region_coverage: float = 0.7,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    datasets = []
    for dataset_path in dataset_paths:
        slug = Path(dataset_path).name.lower().replace(" ", "_")
        result = run_pilot(
            dataset_path=dataset_path,
            output_dir=output_dir / slug,
            max_records=max_records,
            min_label_coverage=min_label_coverage,
            min_region_coverage=min_region_coverage,
        )
        datasets.append(
            {
                "dataset_path": dataset_path,
                "status": result["status"],
                "records_loaded": result["records_loaded"],
                "features_loaded": result["features_loaded"],
                "label_status": result["label_report"]["status"],
                "region_status": result["region_report"]["status"],
                "blocking_reasons": result["blocking_reasons"],
                "report_md": result["report_md"],
                "report_html": result["report_html"],
            }
        )
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_count": len(datasets),
        "validated_ready_count": sum(1 for item in datasets if item["status"] == "validated_ready"),
        "datasets": datasets,
    }
    _write_json(output_dir / "pilot_readiness_scorecard.json", summary)
    _write_scorecard_markdown(output_dir / "pilot_readiness_scorecard.md", summary)
    return summary


def pilot_gate(
    dataset: SpatialDataset,
    asset_readiness: Dict[str, Any],
    label_report: Dict[str, Any],
    region_report: Dict[str, Any],
    min_label_coverage: float,
    min_region_coverage: float,
    allow_single_region: bool,
) -> Dict[str, Any]:
    blockers: List[str] = []
    required: List[str] = []
    for key, name in [
        ("has_cell_table", "Xenium cell table"),
        ("has_feature_matrix", "Xenium feature matrix"),
        ("has_morphology", "morphology image metadata"),
        ("has_boundaries", "cell/nucleus boundaries"),
    ]:
        if not asset_readiness.get(key):
            blockers.append("Missing %s." % name)
            required.append("Provide %s." % name)

    total = max(int(label_report.get("total_records") or len(dataset.records)), 1)
    label_coverage = float(label_report.get("matched_cells") or 0) / float(total)
    if label_report.get("status") != "expert_labels_applied":
        blockers.append("Expert cell labels were not applied.")
        required.append("Add `expert_cell_labels.csv` with `cell_id,expert_label,confidence,notes` to the Xenium folder.")
    elif label_coverage < min_label_coverage:
        blockers.append("Expert label coverage %.3f is below required %.3f." % (label_coverage, min_label_coverage))
        required.append("Increase expert label coverage or lower the explicit threshold.")

    region_total = max(int(region_report.get("total_records") or len(dataset.records)), 1)
    region_coverage = float(region_report.get("matched_cells") or 0) / float(region_total)
    if region_report.get("status") != "user_regions_applied":
        blockers.append("User-provided region labels were not applied.")
        required.append("Add `cell_regions.csv` with `cell_id,region,region_confidence,notes` to the Xenium folder.")
    elif region_coverage < min_region_coverage:
        blockers.append("Region label coverage %.3f is below required %.3f." % (region_coverage, min_region_coverage))
        required.append("Increase region label coverage or lower the explicit threshold.")

    labels = {record.cell_type for record in dataset.records if record.cell_type and "unannotated" not in record.cell_type.lower()}
    if len(labels) < 2:
        blockers.append("At least two biological cell labels are required for marker/neighborhood validation.")
        required.append("Provide at least two reviewed biological cell classes.")

    regions = {record.region for record in dataset.records if record.region}
    if not allow_single_region and len(regions) < 2:
        blockers.append("At least two user-defined regions are required for a validated region summary pilot.")
        required.append("Provide at least two reviewed tissue/ROI regions.")

    return {
        "status": "validated_ready" if not blockers else "blocked_missing_validation_inputs",
        "blocking_reasons": _dedupe(blockers),
        "required_next_inputs": _dedupe(required),
        "label_coverage": round(label_coverage, 4),
        "region_coverage": round(region_coverage, 4),
    }


def _run_validated_tools(dataset: SpatialDataset, plan: List[Any]) -> List[ToolResult]:
    registry = build_mvp_registry()
    results = []
    for spec in plan:
        # marker_detection runs one-vs-rest across every reviewed cell type by
        # default, so no arbitrary pairwise group selection is imposed here.
        results.append(registry.get(spec.tool_name).run(dataset, dict(spec.params)))
    return results


def _write_figures(dataset: SpatialDataset, output_dir: Path) -> List[str]:
    viz = VisualizationLayer()
    return [
        viz.render_distribution_svg(dataset, str(output_dir), []),
        viz.render_distribution_interactive_html(dataset, str(output_dir), []),
    ]


def _write_review_figures(dataset: SpatialDataset, output_dir: Path) -> List[str]:
    figures = [
        _render_review_cluster_png(dataset, output_dir / "review_current_label_map.png"),
        _render_review_composition_svg(dataset, output_dir / "review_cell_type_composition.svg"),
    ]
    viz = VisualizationLayer()
    figures.append(viz.render_distribution_svg(dataset, str(output_dir), []))
    figures.append(viz.render_distribution_interactive_html(dataset, str(output_dir), []))
    figures.append(
        XeniumExplorerLiteViewer().render(
            dataset,
            str(output_dir),
            dataset_path=str(dataset.metadata.get("analysis_dataset_path") or dataset.source_path),
        )
    )
    return figures


def _render_review_cluster_png(dataset: SpatialDataset, path: Path) -> str:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return _render_review_cluster_svg(dataset, path.with_suffix(".svg"))

    cell_types = dataset.cell_types
    palette = [
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
    color_by_type = {cell_type: palette[index % len(palette)] for index, cell_type in enumerate(cell_types)}
    fig = plt.figure(figsize=(11.2, 5.8), dpi=180)
    ax = fig.add_axes([0.07, 0.15, 0.52, 0.72])
    legend_ax = fig.add_axes([0.64, 0.11, 0.33, 0.80])
    legend_ax.axis("off")
    ax.set_facecolor("#fbfbf3")
    for cell_type in cell_types:
        xs = [record.x for record in dataset.records if record.cell_type == cell_type]
        ys = [record.y for record in dataset.records if record.cell_type == cell_type]
        ax.scatter(xs, ys, s=4.0, c=color_by_type[cell_type], alpha=0.70, linewidths=0)
    ax.set_title("Review Map: Current Labels", fontsize=13, pad=8)
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
        y = 0.95 - row * (0.90 / max(rows_per_col - 1, 1))
        legend_ax.scatter([x], [y], s=34, c=color_by_type[cell_type], transform=legend_ax.transAxes)
        legend_ax.text(x + 0.04, y, cell_type, fontsize=8.5, va="center", transform=legend_ax.transAxes)
    fig.text(
        0.07,
        0.035,
        "Review-only visualization: current loader labels are not expert-confirmed biological ground truth.",
        fontsize=8.5,
        color="#5b6770",
    )
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def _render_review_cluster_svg(dataset: SpatialDataset, path: Path) -> str:
    viz = VisualizationLayer()
    return viz.render_distribution_svg(dataset, str(path.parent), [])


def _render_review_composition_svg(dataset: SpatialDataset, path: Path) -> str:
    counts = Counter(record.cell_type for record in dataset.records)
    total = max(sum(counts.values()), 1)
    labels = [label for label, _count in counts.most_common()]
    palette = [
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
    ]
    width = 980
    row_h = 28
    height = max(220, 96 + len(labels) * row_h)
    rows = []
    for index, label in enumerate(labels):
        count = counts[label]
        fraction = count / float(total)
        y = 70 + index * row_h
        bar_w = 520 * fraction
        color = palette[index % len(palette)]
        rows.append('<text x="34" y="%d" font-size="12" font-family="Arial">%s</text>' % (y + 5, html.escape(label)))
        rows.append('<rect x="245" y="%d" width="%.2f" height="16" fill="%s"/>' % (y - 8, bar_w, color))
        rows.append('<text x="%d" y="%d" font-size="12" font-family="Arial">%d (%.1f%%)</text>' % (775, y + 5, count, fraction * 100))
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">
<rect width="100%%" height="100%%" fill="#ffffff"/>
<text x="34" y="34" font-size="18" font-family="Arial" fill="#1f2933">Review Cell-Type Composition</text>
<text x="34" y="54" font-size="11" font-family="Arial" fill="#66717a">Review-only counts from current loader labels; not expert-validated.</text>
%s
</svg>""" % (
        width,
        height,
        width,
        height,
        "\n".join(rows),
    )
    path.write_text(svg, encoding="utf-8")
    return str(path)


def _write_markdown_report(path: Path, payload: Dict[str, Any], results: List[ToolResult]) -> None:
    lines = [
        "# Validated Xenium Pilot Report",
        "",
        "Created: `%s`" % payload["created_at"],
        "",
        "## Status",
        "",
        "- Status: `%s`" % payload["status"],
        "- Dataset: `%s`" % payload["dataset_path"],
        "- Loaded cells: `%d`" % payload["records_loaded"],
        "- Loaded features: `%d`" % payload["features_loaded"],
        "",
    ]
    if payload["blocking_reasons"]:
        lines.extend(["## Blocking Reasons", ""])
        lines.extend("- %s" % item for item in payload["blocking_reasons"])
        lines.extend(["", "## Required Next Inputs", ""])
        lines.extend("- %s" % item for item in payload["required_next_inputs"])
        lines.extend([""])
    lines.extend(["## Typed Tool Plan", ""])
    lines.extend(
        "- `%s` requires `%s`" % (item["tool_name"], ", ".join(item.get("requires") or item.get("depends_on") or []) or "none")
        for item in payload["tool_plan"]
    )
    lines.extend(["", "- Plan validation: `%s`" % payload["plan_validation"]["status"], ""])
    if payload["plan_validation"]["errors"]:
        lines.extend("- %s" % item for item in payload["plan_validation"]["errors"])
        lines.append("")
    lines.extend(
        [
            "## Generated Review Templates",
            "",
            "- Expert labels: `%s`" % payload["expert_label_template"],
            "- Region labels: `%s`" % payload["region_label_template"],
            "",
            "## Label and Region Readiness",
            "",
            "- Label status: `%s`" % payload["label_report"]["status"],
            "- Region status: `%s`" % payload["region_report"]["status"],
            "",
        ]
    )
    lines.extend(["## Review Visualizations", ""])
    lines.extend("- `%s`" % item for item in payload["review_figures"])
    lines.extend(
        [
            "",
            "These figures are generated for QA and expert review from current loader labels or clusters. They are not validated biological result figures until the gate passes.",
            "",
            "## Current Label Summary",
            "",
            "| Label | Count |",
            "| --- | ---: |",
        ]
    )
    for label, count in sorted(payload["cell_type_counts"].items(), key=lambda item: item[1], reverse=True):
        lines.append("| `%s` | %d |" % (label, count))
    lines.extend(["", "## Current Region Summary", "", "| Region | Count |", "| --- | ---: |"])
    for region, count in sorted(payload["region_counts"].items(), key=lambda item: item[1], reverse=True):
        lines.append("| `%s` | %d |" % (region, count))
    lines.append("")
    if results:
        lines.extend(["## Tool Results", ""])
        for result in results:
            lines.extend(["### `%s`" % result.tool_name, "", result.summary, ""])
            lines.extend(_marker_group_markdown(result))
    lines.extend(["## Claim Ledger", ""])
    for item in payload["claim_ledger"]:
        lines.extend(
            [
                "- Status `%s`: %s" % (item.get("status"), item.get("claim_text")),
                "  Allowed wording: `%s`" % (item.get("allowed_wording") or "none"),
            ]
        )
    lines.extend(["", "## Claim Reliability", ""])
    if payload.get("claim_reliability"):
        lines.extend(
            [
                "| Claim | Reliability | S_statistical | A_annotation | P_panel | R_spatial_robustness | Interpretation |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for index, item in enumerate(payload["claim_reliability"], start=1):
            lines.append(
                "| `%s` | %.4f | %.4f | %.4f | %.4f | %.4f | %s |"
                % (
                    item.get("claim_ref") or "claim_%03d" % index,
                    float(item.get("reliability") or 0.0),
                    float(item.get("S_statistical") or 0.0),
                    float(item.get("A_annotation") or 0.0),
                    float(item.get("P_panel") or 0.0),
                    float(item.get("R_spatial_robustness") or 0.0),
                    str(item.get("interpretation") or "").replace("|", "/"),
                )
            )
    else:
        lines.append("No claim reliability records were generated.")
    lines.extend(["", "## Limitations", ""])
    lines.extend("- %s" % item for item in _limitations(payload))
    if payload.get("run_record_path"):
        lines.extend(["", "## Run Record", "", "- `%s`" % payload["run_record_path"], ""])
    lines.extend(
        [
            "## Claim Policy",
            "",
            "This pilot report only allows validated biological claims when expert labels and user-provided regions pass the gate. Weak marker-rule labels and section-level placeholder regions are suitable for software checks only.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_html_report(path: Path, payload: Dict[str, Any], results: List[ToolResult]) -> None:
    result_html = "".join(
        "<section><h3>%s</h3><p>%s</p>%s</section>"
        % (html.escape(result.tool_name), html.escape(result.summary), _marker_group_html(result))
        for result in results
    )
    gallery = "".join(_figure_html(item) for item in payload["review_figures"])
    blockers = "".join("<li>%s</li>" % html.escape(item) for item in payload["blocking_reasons"])
    required = "".join("<li>%s</li>" % html.escape(item) for item in payload["required_next_inputs"])
    plan = "".join(
        "<li><code>%s</code> requires <code>%s</code></li>"
        % (html.escape(item["tool_name"]), html.escape(", ".join(item.get("requires") or item.get("depends_on") or []) or "none"))
        for item in payload["tool_plan"]
    )
    claims = "".join(
        "<li><b>%s</b>: %s<br><small>Allowed wording: %s</small></li>"
        % (
            html.escape(str(item.get("status"))),
            html.escape(str(item.get("claim_text"))),
            html.escape(str(item.get("allowed_wording") or "none")),
        )
        for item in payload["claim_ledger"]
    )
    reliability_rows = "".join(
        "<tr><td>%s</td><td>%.4f</td><td>%.4f</td><td>%.4f</td><td>%.4f</td><td>%.4f</td><td>%s</td></tr>"
        % (
            html.escape(str(item.get("claim_ref") or "")),
            float(item.get("reliability") or 0.0),
            float(item.get("S_statistical") or 0.0),
            float(item.get("A_annotation") or 0.0),
            float(item.get("P_panel") or 0.0),
            float(item.get("R_spatial_robustness") or 0.0),
            html.escape(str(item.get("interpretation") or "")),
        )
        for item in payload.get("claim_reliability", [])
    )
    limitations = "".join("<li>%s</li>" % html.escape(item) for item in _limitations(payload))
    label_rows = "".join(
        "<tr><td>%s</td><td>%d</td></tr>" % (html.escape(label), count)
        for label, count in sorted(payload["cell_type_counts"].items(), key=lambda item: item[1], reverse=True)
    )
    region_rows = "".join(
        "<tr><td>%s</td><td>%d</td></tr>" % (html.escape(region), count)
        for region, count in sorted(payload["region_counts"].items(), key=lambda item: item[1], reverse=True)
    )
    content = """<!doctype html>
<html><head><meta charset="utf-8"><title>Validated Xenium Pilot</title>
<style>body{font-family:Arial,sans-serif;margin:32px;line-height:1.45;color:#1f2933}code{background:#f6f8fa;padding:1px 4px}section{margin:24px 0}li{margin:4px 0}.gallery{display:grid;grid-template-columns:minmax(280px,1fr);gap:18px;max-width:1100px}.figure{border:1px solid #d6dde5;padding:12px;background:#fff}.figure img{max-width:100%%;height:auto}table{border-collapse:collapse;min-width:380px}td,th{border:1px solid #d6dde5;padding:6px 8px;text-align:left}</style>
</head><body>
<h1>Validated Xenium Pilot</h1>
<p>Status: <code>%s</code></p>
<p>Dataset: <code>%s</code>. Loaded %d cells and %d features.</p>
<section><h2>Blocking Reasons</h2><ul>%s</ul></section>
<section><h2>Required Next Inputs</h2><ul>%s</ul></section>
<section><h2>Review Visualizations</h2><p>Generated for QA and expert review from current labels/clusters. These are not validated biological result figures until the gate passes.</p><div class="gallery">%s</div></section>
<section><h2>Current Label Summary</h2><table><tr><th>Label</th><th>Count</th></tr>%s</table></section>
<section><h2>Current Region Summary</h2><table><tr><th>Region</th><th>Count</th></tr>%s</table></section>
<section><h2>Typed Tool Plan</h2><p>Plan validation: <code>%s</code></p><ul>%s</ul></section>
<section><h2>Generated Templates</h2><ul><li><code>%s</code></li><li><code>%s</code></li></ul></section>
<section><h2>Tool Results</h2>%s</section>
<section><h2>Claim Ledger</h2><ul>%s</ul></section>
<section><h2>Claim Reliability</h2><table><tr><th>Claim</th><th>Reliability</th><th>S</th><th>A</th><th>P</th><th>R</th><th>Interpretation</th></tr>%s</table><p><small>S = statistical strength, A = annotation quality, P = panel adequacy, R = spatial robustness. The current default combiner is weakest-link.</small></p></section>
<section><h2>Limitations</h2><ul>%s</ul></section>
<section><h2>Run Record</h2><p><code>%s</code></p></section>
<section><h2>Claim Policy</h2><p>Validated biological claims require expert labels and user-provided regions. Weak labels remain software QA only.</p></section>
</body></html>""" % (
        html.escape(payload["status"]),
        html.escape(payload["dataset_path"]),
        payload["records_loaded"],
        payload["features_loaded"],
        blockers or "<li>None</li>",
        required or "<li>None</li>",
        gallery,
        label_rows,
        region_rows,
        html.escape(payload["plan_validation"]["status"]),
        plan,
        html.escape(payload["expert_label_template"]),
        html.escape(payload["region_label_template"]),
        result_html or "<p>No analysis tools were run because validation inputs are incomplete.</p>",
        claims,
        reliability_rows or "<tr><td colspan=\"7\">No reliability records generated.</td></tr>",
        limitations,
        html.escape(payload.get("run_record_path") or "not written"),
    )
    path.write_text(content, encoding="utf-8")


def _write_pilot_pdf_report(path: Path, payload: Dict[str, Any], results: List[ToolResult]) -> None:
    reliability_by_ref = {
        str(item.get("claim_ref") or ""): item for item in payload.get("claim_reliability", [])
    }
    claim_rows = []
    for index, item in enumerate(payload.get("claim_ledger", []), start=1):
        claim_ref = str(item.get("claim_ref") or "claim_%03d" % index)
        reliability = reliability_by_ref.get(claim_ref, {})
        claim_rows.append(
            (
                claim_ref,
                str(item.get("status") or ""),
                "%.4f" % float(reliability.get("reliability") or 0.0),
                str(item.get("claim_text") or ""),
            )
        )
    tool_rows = [
        (
            str(item.get("tool_name") or ""),
            ", ".join(item.get("requires") or item.get("depends_on") or []) or "none",
        )
        for item in payload.get("tool_plan", [])
    ]
    label_rows = [
        (label, count)
        for label, count in sorted(payload.get("cell_type_counts", {}).items(), key=lambda item: item[1], reverse=True)
    ]
    region_rows = [
        (region, count)
        for region, count in sorted(payload.get("region_counts", {}).items(), key=lambda item: item[1], reverse=True)
    ]
    result_sections = []
    for result in results:
        tables = []
        marker_rows = _marker_group_rows(result)
        if marker_rows:
            tables.append(
                PdfTable(
                    headers=["Cell type", "Top markers (one-vs-rest)"],
                    rows=[(group, ", ".join(genes)) for group, genes in marker_rows],
                    column_widths=[1, 3],
                )
            )
        result_sections.append(
            PdfSection(
                title="Tool Result: %s" % result.tool_name,
                paragraphs=[result.summary],
                bullets=list(result.caveats),
                tables=tables,
            )
        )

    raster_figures = [
        PdfFigure(path=item, caption=Path(item).stem.replace("_", " ").title())
        for item in payload.get("review_figures", [])
        if Path(item).suffix.lower() in {".png", ".jpg", ".jpeg"}
    ]
    sections = [
        PdfSection(
            title="Executive Summary",
            paragraphs=[
                "This report records the validation-gated Xenium workflow. Biological interpretation is released only when expert labels and user-provided regions pass coverage and diversity gates."
            ],
        ),
        PdfSection(title="Blocking Reasons", bullets=payload.get("blocking_reasons", []) or ["None"]),
        PdfSection(title="Required Next Inputs", bullets=payload.get("required_next_inputs", []) or ["None"]),
        PdfSection(
            title="Review Visualizations",
            paragraphs=[
                "These figures use current loader labels or clusters for expert review and QA. They are not validated biological result figures unless the pilot gate passes."
            ],
            figures=raster_figures,
            page_break_before=True,
        ),
        PdfSection(
            title="Current Label Summary",
            tables=[PdfTable(headers=["Label", "Count"], rows=label_rows, column_widths=[3, 1])],
        ),
        PdfSection(
            title="Current Region Summary",
            tables=[PdfTable(headers=["Region", "Count"], rows=region_rows, column_widths=[3, 1])],
        ),
        PdfSection(
            title="Typed Tool Plan",
            paragraphs=["Plan validation status: %s" % payload.get("plan_validation", {}).get("status", "unknown")],
            tables=[PdfTable(headers=["Tool", "Required inputs"], rows=tool_rows, column_widths=[2, 3])],
        ),
    ]
    sections.extend(result_sections)
    sections.extend(
        [
            PdfSection(
                title="Claim Ledger and Reliability",
                paragraphs=[
                    "Reliability is the weakest of statistical support, annotation quality, panel adequacy, and spatial robustness."
                ],
                tables=[
                    PdfTable(
                        headers=["Claim", "Status", "Reliability", "Text"],
                        rows=claim_rows,
                        column_widths=[1, 1.4, 1, 5],
                    )
                ],
            ),
            PdfSection(title="Limitations", bullets=_limitations(payload)),
            PdfSection(
                title="Provenance and Artifacts",
                paragraphs=[
                    "Run record: %s" % (payload.get("run_record_path") or "not written"),
                    "Expert-label template: %s" % payload.get("expert_label_template", ""),
                    "Region template: %s" % payload.get("region_label_template", ""),
                    "HTML source: %s" % payload.get("report_html", ""),
                ],
            ),
        ]
    )
    write_pdf_report(
        str(path),
        "Validated Xenium Pilot",
        sections,
        metadata=[
            ("Status", payload.get("status", "unknown")),
            ("Dataset", payload.get("dataset_path", "")),
            ("Created", payload.get("created_at", "")),
            ("Cells loaded", payload.get("records_loaded", 0)),
            ("Features loaded", payload.get("features_loaded", 0)),
            ("Label status", payload.get("label_report", {}).get("status", "unknown")),
            ("Region status", payload.get("region_report", {}).get("status", "unknown")),
        ],
    )


def _marker_group_rows(result: ToolResult, top_n: int = 5) -> List[Tuple[str, List[str]]]:
    if result.tool_name != "marker_detection":
        return []
    markers_by_group = result.metrics.get("markers_by_group")
    if not isinstance(markers_by_group, dict):
        return []
    rows: List[Tuple[str, List[str]]] = []
    for group, entries in markers_by_group.items():
        genes = [str(entry.get("gene")) for entry in entries[:top_n] if isinstance(entry, dict) and entry.get("gene")]
        if genes:
            rows.append((str(group), genes))
    return rows


def _marker_group_markdown(result: ToolResult, top_n: int = 5) -> List[str]:
    rows = _marker_group_rows(result, top_n)
    if not rows:
        return []
    lines = ["| Cell type | Top markers (one-vs-rest) |", "| --- | --- |"]
    for group, genes in rows:
        lines.append("| `%s` | %s |" % (group, ", ".join("`%s`" % gene for gene in genes)))
    lines.append("")
    return lines


def _marker_group_html(result: ToolResult, top_n: int = 5) -> str:
    rows = _marker_group_rows(result, top_n)
    if not rows:
        return ""
    body = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (html.escape(group), html.escape(", ".join(genes)))
        for group, genes in rows
    )
    return '<table><tr><th>Cell type</th><th>Top markers (one-vs-rest)</th></tr>%s</table>' % body


def _write_scorecard_markdown(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Xenium Pilot Readiness Scorecard",
        "",
        "Created: `%s`" % summary["created_at"],
        "",
        "- Datasets scanned: `%d`" % summary["dataset_count"],
        "- Validated-ready datasets: `%d`" % summary["validated_ready_count"],
        "",
        "| Dataset | Status | Labels | Regions | Report |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in summary["datasets"]:
        lines.append(
            "| `%s` | `%s` | `%s` | `%s` | `%s` |"
            % (item["dataset_path"], item["status"], item["label_status"], item["region_status"], item["report_md"])
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _pilot_structural_inputs() -> List[str]:
    # Validate plan STRUCTURE (tool order, known tools, dependency wiring) assuming
    # all external inputs are present. Input AVAILABILITY is owned by the pilot gate,
    # so a blocked run reports a structurally valid plan instead of a misleading
    # "invalid" caused only by pending expert labels / user regions.
    return list(DEFAULT_XENIUM_INPUTS) + ["expert_labels", "user_regions"]


def _limitations(payload: Dict[str, Any]) -> List[str]:
    feature_count = payload.get("features_loaded", 0)
    label_status = payload.get("label_report", {}).get("status", "unknown")
    region_status = payload.get("region_report", {}).get("status", "unknown")
    items = [
        "Xenium uses a targeted panel (%s loaded features); absence of a gene means it was not measured, not that it is unexpressed." % feature_count,
        "Cell-type labels status: %s. Validated biological interpretation requires expert-reviewed labels." % label_status,
        "Region labels status: %s. Region summaries use user-provided regions; they are not image-derived or independently validated by this MVP." % region_status,
        "Neighborhood enrichment reflects spatial adjacency only; it does not establish interaction, signaling, causation, or mechanism.",
        "No deconvolution, trajectory, motif activity, ligand-receptor, pathway, CNV, or causal inference was run.",
    ]
    if payload.get("status") != "validated_ready":
        items.append("Analysis tools were not run because validation inputs are incomplete; generated templates are preparation artifacts.")
    return items


def _figure_html(path: str) -> str:
    name = Path(path).name
    escaped_name = html.escape(name)
    if name.lower().endswith((".png", ".svg")):
        return '<div class="figure"><img src="%s" alt="%s"><p><code>%s</code></p></div>' % (
            escaped_name,
            escaped_name,
            escaped_name,
        )
    if name.lower().endswith(".html"):
        return '<div class="figure"><p><a href="%s">%s</a></p></div>' % (escaped_name, escaped_name)
    return '<div class="figure"><p><code>%s</code></p></div>' % escaped_name
