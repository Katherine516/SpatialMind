import html
import time
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
    build_xenium_label_intake_report,
    build_readiness_report,
    load_xenium,
    summarize_xenium_expert_readiness,
    validate_cell_by_feature_contract,
    write_expert_label_template,
    write_region_label_template,
)
from spatialmind.pilot.claims import build_pilot_claim_ledger, build_pilot_claim_reliability, claim_ledger_summary
from spatialmind.pilot.spatial_relationships import build_spatial_relationship_summary
from spatialmind.schemas import SpatialDataset, ToolResult
from spatialmind.storage import StorageLayer
from spatialmind.tools import build_mvp_registry
from spatialmind.tools.implementations import (
    CLUSTER_ASSIGNMENT_KEY,
    run_distance_dependent_cooccurrence,
    run_neighborhood_robustness,
    run_region_stratified_neighborhoods,
)
from spatialmind.viz.renderers import PALETTE
from spatialmind.viz import (
    PdfFigure,
    PdfSection,
    PdfTable,
    VisualizationLayer,
    XeniumExplorerLiteViewer,
    normalize_report_format,
    write_pdf_report,
)


MIN_CELLS_FOR_STABLE_CLUSTERS = 6000
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
    readiness_only: bool = False,
    require_complete_section: bool = True,
    review_max_records: int = 5000,
    query: str = "Validated Xenium pilot: annotate cells, summarize user regions, and test spatial relationships.",
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

    gate = pilot_gate(
        dataset=dataset,
        asset_readiness=asset_readiness.to_dict(),
        label_report=label_report.to_dict(),
        region_report=region_report.to_dict(),
        min_label_coverage=min_label_coverage,
        min_region_coverage=min_region_coverage,
        allow_single_region=allow_single_region,
    )
    analysis_scope = _analysis_scope(dataset)
    if (
        gate["status"] == "validated_ready"
        and require_complete_section
        and not readiness_only
        and not analysis_scope["complete_section"]
    ):
        gate["status"] = "blocked_sampled_inference"
        gate["blocking_reasons"].append(
            "Validated biological inference requires the complete tissue section; this run loaded %.2f%% of cells."
            % (100.0 * float(analysis_scope["fraction_loaded"]))
        )
        gate["required_next_inputs"].append(
            "Rerun with `max_records=0` (CLI: `--full-section`) after review labels and regions are complete."
        )
    intake_report = build_xenium_label_intake_report(
        dataset=dataset,
        dataset_path=dataset_path,
        label_report=label_report,
        region_report=region_report,
        asset_readiness=asset_readiness,
        min_label_coverage=min_label_coverage,
        min_region_coverage=min_region_coverage,
        allow_single_region=allow_single_region,
    )

    results: List[ToolResult] = []
    if readiness_only:
        # Fast path for multi-dataset readiness scans: skip templates, review
        # figures, rendered reports, and the run record. Only the gate, readiness,
        # plan-validation, and claim status are computed and written to JSON.
        label_template = ""
        region_template = ""
        review_figures: List[str] = []
        figures: List[str] = []
    else:
        label_template = write_expert_label_template(
            dataset,
            str(output_dir / "expert_label_template.csv"),
            max_rows=review_max_records if review_max_records > 0 else len(dataset.records),
            dataset_path=dataset_path,
        )
        region_template = write_region_label_template(
            dataset,
            str(output_dir / "region_label_template.csv"),
            max_rows=review_max_records if review_max_records > 0 else len(dataset.records),
            dataset_path=dataset_path,
        )
        review_figures = _write_review_figures(dataset, output_dir)
        figures = list(review_figures)
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
    # Descriptive lane: QC, expression clusters, per-cluster markers, and
    # cluster-level neighbourhood structure need no expert labels, because they
    # group by data-derived clusters rather than claimed cell identities. A
    # blocked run should still hand back this analysis instead of only a refusal.
    # Runs for validated pilots too: the cluster-level view is independent evidence
    # that does not depend on the labels, so a labelled dataset should keep it
    # alongside the cell-type view rather than lose it.
    descriptive: Dict[str, Any] = {"status": "not_run", "reason": "Descriptive analysis was not requested."}
    if not readiness_only:
        descriptive = _run_descriptive_lane(dataset, output_dir)

    analysis_backend_error = ""
    if gate["status"] == "validated_ready" and not readiness_only:
        try:
            results = _run_validated_tools(dataset, plan)
            for result in results:
                _write_json(output_dir / ("%s.json" % result.tool_name), result)
            figures.extend(_write_figures(dataset, output_dir))
            neighborhood_result = next(
                (result for result in results if result.tool_name == "cell_neighborhood_enrichment"),
                None,
            )
            spatial_robustness = run_neighborhood_robustness(dataset, baseline_result=neighborhood_result)
        except Exception as exc:
            analysis_backend_error = "%s: %s" % (type(exc).__name__, exc)
            results = []
            gate["status"] = "blocked_analysis_backend"
            gate["blocking_reasons"].append("Validated analysis backend failed: %s" % analysis_backend_error)
            gate["required_next_inputs"].append(
                "Repair the Scanpy/Squidpy environment and rerun; prototype fallbacks are disabled for validated claims."
            )

    if readiness_only:
        spatial_relationships = {
            "status": "not_run",
            "reason": "Readiness-only mode skips spatial analysis.",
            "relationships": [],
            "warnings": [],
        }
    else:
        spatial_relationships = build_spatial_relationship_summary(
            dataset=dataset,
            results=results,
            robustness=spatial_robustness,
            validated=gate["status"] == "validated_ready",
        )

    region_stratified_neighborhoods: Dict[str, Any] = {
        "status": "not_run",
        "reason": "Region-stratified testing runs only for validated pilots.",
        "regions": [],
        "pair_consistency": [],
    }
    distance_cooccurrence: Dict[str, Any] = {
        "status": "not_run",
        "reason": "Distance-dependent co-occurrence runs only for validated pilots.",
        "curves": [],
    }
    if gate["status"] == "validated_ready" and not readiness_only:
        try:
            region_stratified_neighborhoods = run_region_stratified_neighborhoods(
                dataset, params={"strict_engine": True}
            )
            relationship_pairs = [
                str(item.get("pair"))
                for item in spatial_relationships.get("relationships", [])
                if isinstance(item, dict) and item.get("pair")
            ]
            distance_cooccurrence = run_distance_dependent_cooccurrence(
                dataset, pairs=relationship_pairs, params={"strict_engine": True}
            )
            region_figure = _render_region_stratified_heatmap(
                region_stratified_neighborhoods,
                output_dir / "region_stratified_neighborhoods.png",
            )
            if region_figure:
                region_stratified_neighborhoods["figure"] = region_figure
                figures.append(region_figure)
            cooccurrence_figure = _render_distance_cooccurrence_curves(
                distance_cooccurrence,
                output_dir / "distance_dependent_cooccurrence.png",
            )
            if cooccurrence_figure:
                distance_cooccurrence["figure"] = cooccurrence_figure
                figures.append(cooccurrence_figure)
        except Exception as exc:
            downstream_error = "%s: %s" % (type(exc).__name__, exc)
            analysis_backend_error = "; ".join(value for value in (analysis_backend_error, downstream_error) if value)
            gate["status"] = "blocked_analysis_backend"
            gate["blocking_reasons"].append("Validated spatial backend failed: %s" % downstream_error)
            gate["required_next_inputs"].append(
                "Repair the Scanpy/Squidpy environment and rerun; partial spatial outputs cannot support validated claims."
            )
            region_stratified_neighborhoods = {
                "status": "not_run",
                "reason": "Validated spatial backend failed: %s" % downstream_error,
                "regions": [],
                "pair_consistency": [],
            }
            distance_cooccurrence = {
                "status": "not_run",
                "reason": "Validated spatial backend failed: %s" % downstream_error,
                "curves": [],
            }
            spatial_relationships = build_spatial_relationship_summary(
                dataset=dataset,
                results=results,
                robustness=spatial_robustness,
                validated=False,
            )
        _write_json(output_dir / "region_stratified_neighborhoods.json", region_stratified_neighborhoods)
        _write_json(output_dir / "distance_dependent_cooccurrence.json", distance_cooccurrence)

    if gate["status"] == "validated_ready" and not readiness_only:
        relationship_figure = _render_spatial_relationship_heatmap(
            spatial_relationships,
            output_dir / "spatial_relationships_heatmap.png",
        )
        if relationship_figure:
            spatial_relationships["figure"] = relationship_figure
            figures.append(relationship_figure)

    analysis_scope["validated_claims_allowed"] = bool(
        analysis_scope["complete_section"] and gate["status"] == "validated_ready"
    )
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": dataset_path,
        "output_dir": str(output_dir),
        "status": gate["status"],
        "blocking_reasons": gate["blocking_reasons"],
        "required_next_inputs": gate["required_next_inputs"],
        "records_loaded": len(dataset.records),
        "analysis_scope": analysis_scope,
        "expression_layers": dataset.metadata.get("expression_layers", {}),
        "analysis_backend_error": analysis_backend_error,
        "features_loaded": len(dataset.genes),
        "cell_types": dataset.cell_types,
        "regions": sorted({record.region for record in dataset.records if record.region}),
        "cell_type_counts": dict(Counter(record.cell_type for record in dataset.records)),
        "region_counts": dict(Counter(record.region or "unassigned" for record in dataset.records)),
        "label_report": label_report.to_dict(),
        "region_report": region_report.to_dict(),
        "label_intake": intake_report.to_dict(),
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
        "descriptive_analysis": descriptive,
        "spatial_robustness": spatial_robustness,
        "spatial_relationships": spatial_relationships,
        "region_stratified_neighborhoods": region_stratified_neighborhoods,
        "distance_cooccurrence": distance_cooccurrence,
        "report_md": "" if readiness_only else str(output_dir / "validated_xenium_pilot_report.md"),
        "report_html": "" if readiness_only else str(output_dir / "validated_xenium_pilot_report.html"),
        "report_pdf": str(output_dir / "validated_xenium_pilot_report.pdf")
        if (not readiness_only and normalized_format in {"pdf", "both"})
        else "",
        "report_format": normalized_format,
        "report_path": ""
        if readiness_only
        else (
            str(output_dir / "validated_xenium_pilot_report.pdf")
            if normalized_format == "pdf"
            else str(output_dir / "validated_xenium_pilot_report.html")
        ),
        "readiness_only": readiness_only,
        "require_complete_section": require_complete_section,
        "run_record_path": "",
    }
    payload["claim_ledger"] = build_pilot_claim_ledger(payload, results)
    payload["claim_reliability"] = build_pilot_claim_reliability(payload, results)
    payload["claim_summary"] = claim_ledger_summary(payload["claim_ledger"])
    if readiness_only:
        _write_json(output_dir / "pilot_validation.json", payload)
        return payload
    planned_run_id = "mvp_%s_%s" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8])
    payload["run_record_path"] = str(output_dir / "runs" / ("%s.json" % planned_run_id))
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
    region_json = output_dir / "region_stratified_neighborhoods.json"
    cooccurrence_json = output_dir / "distance_dependent_cooccurrence.json"
    if region_json.exists():
        report_artifacts["region_stratified_neighborhoods"] = str(region_json)
    if cooccurrence_json.exists():
        report_artifacts["distance_dependent_cooccurrence"] = str(cooccurrence_json)
    run_record = StorageLayer(root=str(output_dir)).write_mvp_run_record(
        query=query,
        tool_trace=[{"tool_name": result.tool_name, "summary": result.summary, "metrics": result.metrics} for result in results],
        params={
            "workflow_type": "validated_xenium_pilot",
            "max_records": max_records,
            "min_label_coverage": min_label_coverage,
            "min_region_coverage": min_region_coverage,
            "allow_single_region": allow_single_region,
            "require_complete_section": require_complete_section,
            "review_max_records": review_max_records,
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
            readiness_only=True,
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
                "pilot_validation": str(output_dir / slug / "pilot_validation.json"),
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


def _run_descriptive_lane(dataset: SpatialDataset, output_dir: Path) -> Dict[str, Any]:
    """Label-free analysis: QC, clusters, per-cluster markers, cluster neighbourhoods.

    Every result here is a statement about data-derived groupings, never about
    named cell types, so it stands without expert annotation.
    """
    registry = build_mvp_registry()
    payload: Dict[str, Any] = {"status": "computed", "group_key": "cluster", "tools": []}
    # Stage timings: a full-section run takes minutes, and without per-stage
    # numbers there is no way to tell which stage to optimise.
    timings: Dict[str, float] = {}
    started = time.time()
    stage_start = time.time()
    try:
        clustering = registry.get("qc_and_cluster").run(
            dataset, {"resolution": 0.55, "random_state": 0, "strict_engine": True}
        )
    except Exception as exc:
        return {"status": "not_run", "reason": "Clustering failed: %s" % exc}
    timings["qc_and_cluster"] = round(time.time() - stage_start, 2)
    payload["tools"].append("qc_and_cluster")
    payload["cluster_counts"] = clustering.metrics.get("cluster_counts", {})
    payload["cluster_count"] = len(payload["cluster_counts"])
    payload["expression_qc"] = clustering.metrics.get("expression_qc", {})
    payload["clustering_method"] = clustering.metrics.get("method")
    payload["clustering_diagnostics"] = {
        "silhouette": clustering.metrics.get("silhouette"),
        "modularity": clustering.metrics.get("modularity"),
        "analyzed_cell_count": clustering.metrics.get("analyzed_cell_count"),
        "excluded_zero_feature_cell_count": clustering.metrics.get("excluded_zero_feature_cell_count", 0),
    }
    _write_json(output_dir / "descriptive_qc_and_cluster.json", clustering)

    for tool_name, params, key in (
        (
            "marker_detection",
            {"group_key": "cluster", "n_top": 25, "strict_engine": True},
            "markers_by_cluster",
        ),
        (
            "spatial_variable_genes",
            {
                "n_top": 15,
                "n_neighs": 6,
                "n_perms": 100,
                "random_state": 0,
                "strict_engine": True,
            },
            "spatial_genes",
        ),
        (
            "cell_neighborhood_enrichment",
            {
                "group_key": "cluster",
                "n_neighs": 6,
                "n_perms": 100,
                "random_state": 0,
                "strict_engine": True,
            },
            "cluster_neighborhood",
        ),
    ):
        stage_start = time.time()
        try:
            result = registry.get(tool_name).run(dataset, dict(params))
        except Exception as exc:
            timings[tool_name] = round(time.time() - stage_start, 2)
            payload[key] = {"status": "not_run", "reason": str(exc)}
            continue
        timings[tool_name] = round(time.time() - stage_start, 2)
        payload["tools"].append(tool_name)
        _write_json(output_dir / ("descriptive_%s.json" % tool_name), result)
        if tool_name == "marker_detection":
            payload[key] = {
                str(group): [str(row.get("gene")) for row in rows[:8] if isinstance(row, dict)]
                for group, rows in (result.metrics.get("markers_by_group") or {}).items()
            }
        elif tool_name == "spatial_variable_genes":
            payload[key] = {
                "engine": result.metrics.get("engine"),
                "method": result.metrics.get("method"),
                "n_perms": result.metrics.get("n_perms"),
                "multiple_testing": result.metrics.get("multiple_testing"),
                "significant_gene_count_top_n": result.metrics.get("significant_gene_count_top_n"),
                "significant_gene_count_all": result.metrics.get("significant_gene_count_all"),
                "screening": result.metrics.get("screening"),
                "top_genes": result.metrics.get("top_genes", [])[:15],
            }
        else:
            payload[key] = {
                "top_pairs": result.metrics.get("top_pairs", [])[:10],
                "engine": result.metrics.get("engine"),
            }
    # Empirically, cluster structure on a Xenium brain section is recovered at
    # >=6000 sampled cells (all 10 full-section clusters, ARI 0.90); 3000 cells
    # recovered only 8. Flag runs below that so a thin sample is not mistaken for
    # a complete picture.
    analyzed = int((payload.get("clustering_diagnostics") or {}).get("analyzed_cell_count") or len(dataset.records))
    if analyzed < MIN_CELLS_FOR_STABLE_CLUSTERS:
        payload["sampling_warning"] = (
            "Only %d cells were clustered. Cluster structure is typically incomplete below %d cells; "
            "rare populations may be missing or merged. Increase --max-cells for a fuller picture."
            % (analyzed, MIN_CELLS_FOR_STABLE_CLUSTERS)
        )
    payload["interpretation"] = (
        "Clusters are derived from measured expression, not from cell-type labels. Marker genes "
        "describe what distinguishes each cluster; naming clusters as cell types requires expert review."
    )
    stage_start = time.time()
    payload["figures"] = _write_descriptive_figures(dataset, payload, output_dir)
    timings["figures"] = round(time.time() - stage_start, 2)
    timings["total"] = round(time.time() - started, 2)
    payload["stage_seconds"] = timings
    return payload


def _cluster_assignments(dataset: SpatialDataset) -> Dict[str, str]:
    assignments = dataset.metadata.get(CLUSTER_ASSIGNMENT_KEY)
    return dict(assignments) if isinstance(assignments, dict) else {}


def _write_descriptive_figures(dataset: SpatialDataset, payload: Dict[str, Any], output_dir: Path) -> List[str]:
    """Cluster spatial map and marker heatmap for the label-free lane."""
    assignments = _cluster_assignments(dataset)
    if not assignments:
        return []
    figures = []
    spatial = _render_cluster_spatial_map(dataset, assignments, output_dir / "descriptive_cluster_map.png")
    if spatial:
        figures.append(spatial)
    markers = payload.get("markers_by_cluster")
    if isinstance(markers, dict) and markers:
        heatmap = _render_cluster_marker_heatmap(
            dataset, assignments, markers, output_dir / "descriptive_marker_heatmap.png"
        )
        if heatmap:
            figures.append(heatmap)
    return figures


def _render_cluster_spatial_map(dataset: SpatialDataset, assignments: Dict[str, str], path: Path) -> str:
    """Cells in tissue coordinates, coloured by data-derived cluster."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return ""
    clusters = sorted({value for value in assignments.values() if value}, key=_sort_cluster_key)
    if not clusters:
        return ""
    colors = {cluster: PALETTE[index % len(PALETTE)] for index, cluster in enumerate(clusters)}
    counts = Counter(assignments.get(record.cell_id or str(index), "") for index, record in enumerate(dataset.records))
    fig = plt.figure(figsize=(11.2, 6.0), dpi=180)
    ax = fig.add_axes([0.07, 0.10, 0.60, 0.80])
    legend_ax = fig.add_axes([0.70, 0.10, 0.28, 0.80])
    legend_ax.axis("off")
    ax.set_facecolor("#fbfbf7")
    for cluster in clusters:
        xs, ys = [], []
        for index, record in enumerate(dataset.records):
            if assignments.get(record.cell_id or str(index)) == cluster:
                xs.append(record.x)
                ys.append(record.y)
        ax.scatter(xs, ys, s=4.0, c=colors[cluster], alpha=0.75, linewidths=0)
    ax.set_title("Expression clusters in tissue space", fontsize=13, pad=8)
    ax.set_xlabel("spatial1 (microns)")
    ax.set_ylabel("spatial2 (microns)")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
        spine.set_color("#222222")
    for index, cluster in enumerate(clusters):
        y = 0.96 - index * (0.90 / max(len(clusters), 1))
        legend_ax.scatter([0.04], [y], s=40, c=colors[cluster], transform=legend_ax.transAxes)
        legend_ax.text(
            0.13, y, "cluster %s  (n=%d)" % (cluster, counts.get(cluster, 0)),
            fontsize=9, va="center", transform=legend_ax.transAxes,
        )
    fig.text(
        0.07, 0.02,
        "Clusters are data-derived expression groups, not cell-type calls.",
        fontsize=8.5, color="#5b6770",
    )
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def _render_cluster_marker_heatmap(
    dataset: SpatialDataset,
    assignments: Dict[str, str],
    markers_by_cluster: Dict[str, Any],
    path: Path,
    per_cluster: int = 3,
) -> str:
    """Mean expression of each cluster's top markers across all clusters."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return ""
    clusters = sorted({value for value in assignments.values() if value}, key=_sort_cluster_key)
    genes: List[str] = []
    for cluster in clusters:
        for gene in (markers_by_cluster.get(cluster) or [])[:per_cluster]:
            if gene and gene not in genes:
                genes.append(str(gene))
    if not clusters or not genes:
        return ""
    totals = {cluster: {gene: 0.0 for gene in genes} for cluster in clusters}
    counts = {cluster: 0 for cluster in clusters}
    for index, record in enumerate(dataset.records):
        cluster = assignments.get(record.cell_id or str(index), "")
        if cluster not in totals:
            continue
        counts[cluster] += 1
        for gene in genes:
            try:
                totals[cluster][gene] += float(record.genes.get(gene, 0.0))
            except (TypeError, ValueError):
                continue
    matrix = np.array(
        [[totals[cluster][gene] / max(counts[cluster], 1) for gene in genes] for cluster in clusters],
        dtype=float,
    )
    # Scale each gene to its own maximum so low-abundance markers stay visible.
    maxima = matrix.max(axis=0)
    maxima[maxima <= 0] = 1.0
    scaled = matrix / maxima

    fig_width = max(8.0, 0.34 * len(genes) + 3.0)
    fig_height = max(3.2, 0.42 * len(clusters) + 2.0)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=180)
    image = ax.imshow(scaled, aspect="auto", cmap="viridis", vmin=0.0, vmax=1.0)
    ax.set_xticks(range(len(genes)))
    ax.set_xticklabels(genes, rotation=90, fontsize=7)
    ax.set_yticks(range(len(clusters)))
    ax.set_yticklabels(["cluster %s" % cluster for cluster in clusters], fontsize=9)
    ax.set_title("Top marker genes per cluster (mean expression, scaled per gene)", fontsize=11, pad=10)
    fig.colorbar(image, ax=ax, fraction=0.02, pad=0.02, label="relative mean expression")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def _sort_cluster_key(value: str) -> Any:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _run_validated_tools(dataset: SpatialDataset, plan: List[Any]) -> List[ToolResult]:
    registry = build_mvp_registry()
    results = []
    for spec in plan:
        # marker_detection runs one-vs-rest across every reviewed cell type by
        # default, so no arbitrary pairwise group selection is imposed here.
        results.append(registry.get(spec.tool_name).run(dataset, dict(spec.params)))
    return results


def _analysis_scope(dataset: SpatialDataset) -> Dict[str, Any]:
    sampling = dict(dataset.metadata.get("sampling") or {})
    total = int(sampling.get("total_records") or dataset.metadata.get("n_obs_total") or len(dataset.records))
    loaded = len(dataset.records)
    complete = str(dataset.metadata.get("analysis_scope") or "").lower() == "full_section"
    if total > 0 and loaded < total:
        complete = False
    return {
        "scope": "full_section" if complete else "sampled",
        "complete_section": complete,
        "complete_section_requirement_met": complete,
        "loaded_records": loaded,
        "total_records": total,
        "fraction_loaded": round(loaded / float(max(total, 1)), 6),
        "sampling_method": sampling.get("method", "unknown"),
        "validated_claims_allowed": False,
    }


def _write_figures(dataset: SpatialDataset, output_dir: Path) -> List[str]:
    viz = VisualizationLayer()
    return [
        viz.render_distribution_svg(dataset, str(output_dir), []),
        viz.render_distribution_interactive_html(dataset, str(output_dir), []),
    ]


def _render_spatial_relationship_heatmap(summary: Dict[str, Any], path: Path) -> str:
    relationships = summary.get("relationships") or []
    if summary.get("status") != "computed" or not relationships:
        return ""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return ""

    labels = sorted(
        {
            str(value)
            for row in relationships
            for value in (row.get("left_cell_type"), row.get("right_cell_type"))
            if value
        }
    )
    if not labels:
        return ""
    index = {label: position for position, label in enumerate(labels)}
    matrix = np.full((len(labels), len(labels)), np.nan, dtype=float)
    for row in relationships:
        left = str(row.get("left_cell_type") or "")
        right = str(row.get("right_cell_type") or "")
        if left not in index or right not in index:
            continue
        value = float(row.get("zscore") or 0.0)
        matrix[index[left], index[right]] = value
        matrix[index[right], index[left]] = value

    finite = np.abs(matrix[np.isfinite(matrix)])
    limit = max(2.0, float(np.max(finite)) if finite.size else 2.0)
    side = min(12.0, max(6.5, 0.52 * len(labels) + 3.5))
    fig, ax = plt.subplots(figsize=(side, side * 0.86), dpi=180)
    image_artist = ax.imshow(matrix, cmap="coolwarm", vmin=-limit, vmax=limit, interpolation="nearest")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=55, ha="right", fontsize=8)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_title("Cell-Type Spatial Adjacency", fontsize=14, pad=14)
    ax.set_xlabel("Permutation z-score: red = enriched adjacency, blue = depleted adjacency", fontsize=9)
    if len(labels) <= 12:
        for row_index in range(len(labels)):
            for column_index in range(len(labels)):
                value = matrix[row_index, column_index]
                if np.isfinite(value):
                    ax.text(
                        column_index,
                        row_index,
                        "%.1f" % value,
                        ha="center",
                        va="center",
                        fontsize=7,
                        color="white" if abs(value) > limit * 0.55 else "#17202a",
                    )
    colorbar = fig.colorbar(image_artist, ax=ax, fraction=0.045, pad=0.04)
    colorbar.set_label("Neighborhood enrichment z-score", fontsize=9)
    fig.text(
        0.01,
        0.01,
        "Adjacency reflects the tested spatial graph and does not establish signaling, mechanism, or causation.",
        fontsize=8,
        color="#4b5563",
    )
    fig.tight_layout(rect=[0.02, 0.045, 1, 1])
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def _render_region_stratified_heatmap(summary: Dict[str, Any], path: Path) -> str:
    regions = summary.get("regions") or []
    pair_rows = summary.get("pair_consistency") or []
    if summary.get("status") != "computed" or not regions or not pair_rows:
        return ""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return ""
    region_names = [str(item.get("region")) for item in regions if item.get("region")]
    pair_names = [str(item.get("pair")) for item in pair_rows[:10] if item.get("pair")]
    if not region_names or not pair_names:
        return ""
    matrix = np.full((len(region_names), len(pair_names)), np.nan, dtype=float)
    region_index = {name: index for index, name in enumerate(region_names)}
    pair_index = {name: index for index, name in enumerate(pair_names)}
    for item in pair_rows[:10]:
        pair = str(item.get("pair") or "")
        if pair not in pair_index:
            continue
        for value in item.get("by_region") or []:
            region = str(value.get("region") or "")
            if region in region_index and value.get("zscore") is not None:
                matrix[region_index[region], pair_index[pair]] = float(value["zscore"])
    finite = np.abs(matrix[np.isfinite(matrix)])
    limit = max(2.0, float(np.max(finite)) if finite.size else 2.0)
    width = min(14.0, max(8.0, 0.85 * len(pair_names) + 3.0))
    height = min(10.0, max(4.8, 0.55 * len(region_names) + 2.8))
    fig, ax = plt.subplots(figsize=(width, height), dpi=180)
    artist = ax.imshow(matrix, cmap="coolwarm", vmin=-limit, vmax=limit, aspect="auto", interpolation="nearest")
    ax.set_xticks(range(len(pair_names)))
    ax.set_yticks(range(len(region_names)))
    ax.set_xticklabels([name.replace(" | ", " / ") for name in pair_names], rotation=55, ha="right", fontsize=8)
    ax.set_yticklabels(region_names, fontsize=8)
    ax.set_title("Region-Stratified Cell-Type Adjacency", fontsize=14, pad=12)
    ax.set_xlabel("Permutation z-score within each reviewed region", fontsize=9)
    if len(region_names) * len(pair_names) <= 80:
        for row_index in range(len(region_names)):
            for column_index in range(len(pair_names)):
                value = matrix[row_index, column_index]
                if np.isfinite(value):
                    ax.text(
                        column_index,
                        row_index,
                        "%.1f" % value,
                        ha="center",
                        va="center",
                        fontsize=7,
                        color="white" if abs(value) > limit * 0.55 else "#17202a",
                    )
    colorbar = fig.colorbar(artist, ax=ax, fraction=0.035, pad=0.03)
    colorbar.set_label("Within-region enrichment z-score", fontsize=9)
    fig.text(
        0.01,
        0.01,
        "Blank cells were not testable under the minimum cell-count criteria.",
        fontsize=8,
        color="#4b5563",
    )
    fig.tight_layout(rect=[0.02, 0.05, 1, 1])
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def _render_distance_cooccurrence_curves(summary: Dict[str, Any], path: Path) -> str:
    curves = summary.get("curves") or []
    if summary.get("status") != "computed" or not curves:
        return ""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return ""
    fig, ax = plt.subplots(figsize=(9.4, 5.8), dpi=180)
    palette = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b", "#7f7f7f"]
    for index, curve in enumerate(curves[:8]):
        points = curve.get("points") or []
        xs = [float(item["distance"]) for item in points if item.get("distance") is not None]
        ys = [float(item["cooccurrence_ratio"]) for item in points if item.get("cooccurrence_ratio") is not None]
        if not xs or len(xs) != len(ys):
            continue
        ax.plot(xs, ys, color=palette[index % len(palette)], linewidth=1.8, marker="o", markersize=2.8, label=str(curve.get("pair") or "pair"))
    ax.axhline(1.0, color="#4b5563", linewidth=1.0, linestyle="--")
    ax.set_title("Distance-Dependent Cell-Type Co-Occurrence", fontsize=14, pad=12)
    ax.set_xlabel("Distance threshold (%s)" % (summary.get("coordinate_units") or "dataset units"))
    ax.set_ylabel("Conditional co-occurrence ratio")
    ax.grid(True, color="#d1d5db", linewidth=0.6, alpha=0.65)
    ax.legend(frameon=False, fontsize=8, loc="best")
    fig.text(
        0.01,
        0.01,
        "Ratio 1 is the marginal-frequency baseline; curves are descriptive and do not provide permutation p-values.",
        fontsize=8,
        color="#4b5563",
    )
    fig.tight_layout(rect=[0.02, 0.05, 1, 1])
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


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
    scope = payload.get("analysis_scope") or {
        "scope": "unknown",
        "loaded_records": payload.get("records_loaded", 0),
        "total_records": payload.get("records_loaded", 0),
        "fraction_loaded": 1.0,
    }
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
        "- Analysis scope: `%s` (%s/%s cells; %.2f%%)"
        % (
            scope["scope"],
            scope["loaded_records"],
            scope["total_records"],
            100.0 * float(scope["fraction_loaded"]),
        ),
        "- QC expression source: `%s`"
        % payload.get("expression_layers", {}).get("source", "source layer unavailable"),
        "",
    ]
    lines.extend(_descriptive_markdown(payload))
    if payload["blocking_reasons"]:
        lines.extend(["## What Is Still Needed To Go Further", ""])
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
    relationship_summary = payload.get("spatial_relationships") or {}
    relationship_rows = _spatial_relationship_report_rows(payload)
    lines.extend(["## Spatial Relationships", "", "- Status: `%s`" % relationship_summary.get("status", "not_run")])
    if relationship_summary.get("method"):
        graph = relationship_summary.get("graph") or {}
        lines.extend(
            [
                "- Method: `%s`" % relationship_summary["method"],
                "- Primary graph: `n_neighs=%s`, `n_perms=%s`, `seed=%s`"
                % (graph.get("n_neighs"), graph.get("n_perms"), graph.get("random_state")),
            ]
        )
    if relationship_summary.get("figure"):
        lines.extend(["", "![Spatial relationship heatmap](%s)" % Path(relationship_summary["figure"]).name])
    if relationship_rows:
        lines.extend(
            [
                "",
                "| Cell-type pair | Direction | z-score | Pair stability | Nearest distance | Region overlap | Evidence status |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in relationship_rows:
            lines.append("| %s | %s | %s | %s | %s | %s | `%s` |" % row)
        interpretations = _spatial_relationship_interpretations(payload)
        if interpretations:
            lines.extend(["", "### Allowed Spatial Interpretation", ""])
            lines.extend("- %s" % value for value in interpretations)
    elif relationship_summary.get("reason"):
        lines.extend(["", relationship_summary["reason"]])
    for warning in relationship_summary.get("warnings") or []:
        lines.append("- Limitation: %s" % warning)
    lines.append("")

    region_summary = payload.get("region_stratified_neighborhoods") or {}
    region_rows = _region_stratified_report_rows(payload)
    lines.extend(
        [
            "## Region-Stratified Neighborhood Testing",
            "",
            "- Status: `%s`" % region_summary.get("status", "not_run"),
        ]
    )
    if "tested_region_count" in region_summary:
        lines.append(
            "- Tested regions: `%s`; skipped regions: `%s`"
            % (region_summary.get("tested_region_count", 0), region_summary.get("skipped_region_count", 0))
        )
    if region_summary.get("parameters", {}).get("min_abs_zscore") is not None:
        lines.append(
            "- Cross-region consistency threshold: `|z| >= %s` in at least two regions"
            % region_summary["parameters"]["min_abs_zscore"]
        )
    if region_summary.get("figure"):
        lines.extend(["", "![Region-stratified neighborhood heatmap](%s)" % Path(region_summary["figure"]).name])
    if region_rows:
        lines.extend(
            [
                "",
                "| Cell-type pair | Regions tested / supported | Direction agreement | Strongest region | Strongest |z| | Status |",
                "| --- | ---: | ---: | --- | ---: | --- |",
            ]
        )
        lines.extend("| %s | %s | %s | %s | %s | `%s` |" % row for row in region_rows)
    elif region_summary.get("reason"):
        lines.extend(["", str(region_summary["reason"])])
    for warning in region_summary.get("warnings") or []:
        lines.append("- Limitation: %s" % warning)
    lines.append("")

    cooccurrence_summary = payload.get("distance_cooccurrence") or {}
    cooccurrence_rows = _distance_cooccurrence_report_rows(payload)
    lines.extend(
        [
            "## Distance-Dependent Co-Occurrence",
            "",
            "- Status: `%s`" % cooccurrence_summary.get("status", "not_run"),
        ]
    )
    if cooccurrence_summary.get("status") == "computed":
        lines.append(
            "- Distance range: `0-%s %s` across `%s` thresholds; minimum `%s` cells per type"
            % (
                cooccurrence_summary.get("max_distance"),
                cooccurrence_summary.get("coordinate_units", "dataset units"),
                cooccurrence_summary.get("n_intervals"),
                cooccurrence_summary.get("min_cells_per_type", "not recorded"),
            )
        )
    if cooccurrence_summary.get("figure"):
        lines.extend(["", "![Distance-dependent co-occurrence curves](%s)" % Path(cooccurrence_summary["figure"]).name])
    if cooccurrence_rows:
        lines.extend(
            [
                "",
                "| Cell-type pair | Peak ratio | Peak distance | Short-range mean | Long-range mean |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        lines.extend("| %s | %s | %s | %s | %s |" % row for row in cooccurrence_rows)
    elif cooccurrence_summary.get("reason"):
        lines.extend(["", str(cooccurrence_summary["reason"])])
    for warning in cooccurrence_summary.get("warnings") or []:
        lines.append("- Limitation: %s" % warning)
    lines.append("")

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
    robustness_rows = _spatial_robustness_rows(payload)
    if robustness_rows:
        lines.extend(
            [
                "",
                "## Spatial Robustness Sweep",
                "",
                "The R component is measured by rerunning neighborhood enrichment across graph-size settings and comparing sign agreement plus top-K pair overlap.",
                "",
                "| Setting / metric | Value |",
                "| --- | --- |",
            ]
        )
        lines.extend("| %s | `%s` |" % (label, value) for label, value in robustness_rows)
        reason = payload.get("spatial_robustness", {}).get("reason")
        if reason:
            lines.extend(["", "Note: %s" % reason])
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
    robustness_rows = _spatial_robustness_rows(payload)
    robustness_html = ""
    if robustness_rows:
        robustness_body = "".join(
            "<tr><td>%s</td><td><code>%s</code></td></tr>" % (html.escape(label), html.escape(value))
            for label, value in robustness_rows
        )
        reason = payload.get("spatial_robustness", {}).get("reason")
        reason_html = "<p>%s</p>" % html.escape(str(reason)) if reason else ""
        robustness_html = (
            "<section><h2>Spatial Robustness Sweep</h2>"
            "<p>The R component is measured by rerunning neighborhood enrichment across graph-size settings and comparing sign agreement plus top-K pair overlap.</p>"
            "<table><tr><th>Setting / metric</th><th>Value</th></tr>%s</table>%s</section>"
            % (robustness_body, reason_html)
        )
    relationship_summary = payload.get("spatial_relationships") or {}
    relationship_rows = _spatial_relationship_report_rows(payload)
    relationship_body = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><code>%s</code></td></tr>"
        % tuple(html.escape(str(value)) for value in row)
        for row in relationship_rows
    )
    graph = relationship_summary.get("graph") or {}
    relationship_method = ""
    if relationship_summary.get("method"):
        relationship_method = (
            "<p>Method: <code>%s</code>. Primary graph: <code>n_neighs=%s</code>, "
            "<code>n_perms=%s</code>, <code>seed=%s</code>.</p>"
            % (
                html.escape(str(relationship_summary.get("method"))),
                html.escape(str(graph.get("n_neighs"))),
                html.escape(str(graph.get("n_perms"))),
                html.escape(str(graph.get("random_state"))),
            )
        )
    relationship_figure = ""
    if relationship_summary.get("figure"):
        figure_name = Path(str(relationship_summary["figure"])).name
        relationship_figure = '<div class="figure"><img src="%s" alt="Spatial relationship heatmap"></div>' % html.escape(figure_name)
    relationship_table = (
        "<table><tr><th>Cell-type pair</th><th>Direction</th><th>z-score</th><th>Pair stability</th>"
        "<th>Nearest distance</th><th>Region overlap</th><th>Evidence status</th></tr>%s</table>" % relationship_body
        if relationship_body
        else "<p>%s</p>" % html.escape(str(relationship_summary.get("reason") or "No relationship rows were produced."))
    )
    relationship_warnings = "".join(
        "<li>%s</li>" % html.escape(str(value)) for value in relationship_summary.get("warnings") or []
    )
    relationship_interpretations = "".join(
        "<li>%s</li>" % html.escape(value) for value in _spatial_relationship_interpretations(payload)
    )
    interpretation_html = (
        "<h3>Allowed Spatial Interpretation</h3><ul>%s</ul>" % relationship_interpretations
        if relationship_interpretations
        else ""
    )
    relationship_html = (
        "<section><h2>Spatial Relationships</h2><p>Status: <code>%s</code></p>%s%s%s%s<ul>%s</ul></section>"
        % (
            html.escape(str(relationship_summary.get("status") or "not_run")),
            relationship_method,
            relationship_figure,
            relationship_table,
            interpretation_html,
            relationship_warnings,
        )
    )
    region_summary = payload.get("region_stratified_neighborhoods") or {}
    region_rows = _region_stratified_report_rows(payload)
    region_body = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><code>%s</code></td></tr>"
        % tuple(html.escape(str(value)) for value in row)
        for row in region_rows
    )
    region_table = (
        "<table><tr><th>Cell-type pair</th><th>Regions tested / supported</th><th>Direction agreement</th>"
        "<th>Strongest region</th><th>Strongest |z|</th><th>Status</th></tr>%s</table>" % region_body
        if region_body
        else "<p>%s</p>" % html.escape(str(region_summary.get("reason") or "No region-stratified rows were produced."))
    )
    region_figure = ""
    if region_summary.get("figure"):
        figure_name = Path(str(region_summary["figure"])).name
        region_figure = '<div class="figure"><img src="%s" alt="Region-stratified neighborhood heatmap"></div>' % html.escape(figure_name)
    region_warnings = "".join(
        "<li>%s</li>" % html.escape(str(value)) for value in region_summary.get("warnings") or []
    )
    region_counts_html = ""
    if "tested_region_count" in region_summary:
        region_counts_html = " Tested regions: <code>%s</code>; skipped regions: <code>%s</code>." % (
            html.escape(str(region_summary.get("tested_region_count", 0))),
            html.escape(str(region_summary.get("skipped_region_count", 0))),
        )
    if region_summary.get("parameters", {}).get("min_abs_zscore") is not None:
        region_counts_html += " Consistency requires <code>|z| &gt;= %s</code> in at least two regions." % html.escape(
            str(region_summary["parameters"]["min_abs_zscore"])
        )
    region_html = (
        "<section><h2>Region-Stratified Neighborhood Testing</h2><p>Status: <code>%s</code>.%s</p>%s%s<ul>%s</ul></section>"
        % (
            html.escape(str(region_summary.get("status") or "not_run")),
            region_counts_html,
            region_figure,
            region_table,
            region_warnings,
        )
    )
    cooccurrence_summary = payload.get("distance_cooccurrence") or {}
    cooccurrence_rows = _distance_cooccurrence_report_rows(payload)
    cooccurrence_body = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
        % tuple(html.escape(str(value)) for value in row)
        for row in cooccurrence_rows
    )
    cooccurrence_table = (
        "<table><tr><th>Cell-type pair</th><th>Peak ratio</th><th>Peak distance</th>"
        "<th>Short-range mean</th><th>Long-range mean</th></tr>%s</table>" % cooccurrence_body
        if cooccurrence_body
        else "<p>%s</p>" % html.escape(str(cooccurrence_summary.get("reason") or "No co-occurrence curves were produced."))
    )
    cooccurrence_figure = ""
    if cooccurrence_summary.get("figure"):
        figure_name = Path(str(cooccurrence_summary["figure"])).name
        cooccurrence_figure = '<div class="figure"><img src="%s" alt="Distance-dependent co-occurrence curves"></div>' % html.escape(figure_name)
    cooccurrence_warnings = "".join(
        "<li>%s</li>" % html.escape(str(value)) for value in cooccurrence_summary.get("warnings") or []
    )
    cooccurrence_range_html = ""
    if cooccurrence_summary.get("status") == "computed":
        cooccurrence_range_html = " Distance range: <code>0-%s %s</code> across <code>%s</code> thresholds; minimum <code>%s</code> cells per type." % (
            html.escape(str(cooccurrence_summary.get("max_distance"))),
            html.escape(str(cooccurrence_summary.get("coordinate_units", "dataset units"))),
            html.escape(str(cooccurrence_summary.get("n_intervals"))),
            html.escape(str(cooccurrence_summary.get("min_cells_per_type", "not recorded"))),
        )
    cooccurrence_html = (
        "<section><h2>Distance-Dependent Co-Occurrence</h2><p>Status: <code>%s</code>.%s</p>%s%s<ul>%s</ul></section>"
        % (
            html.escape(str(cooccurrence_summary.get("status") or "not_run")),
            cooccurrence_range_html,
            cooccurrence_figure,
            cooccurrence_table,
            cooccurrence_warnings,
        )
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
    descriptive_html = _descriptive_html(payload)
    scope = payload.get("analysis_scope") or {}
    scope_html = (
        "<section><h2>Analysis Scope and Expression Layers</h2>"
        "<p>Scope: <code>%s</code> (%s/%s cells; %.2f%%). Final validated claims allowed: <code>%s</code>.</p>"
        "<p>Analysis layer: <code>%s</code><br>Source layer: <code>%s</code></p></section>"
        % (
            html.escape(str(scope.get("scope") or "unknown")),
            html.escape(str(scope.get("loaded_records") or 0)),
            html.escape(str(scope.get("total_records") or 0)),
            100.0 * float(scope.get("fraction_loaded") or 0.0),
            html.escape(str(scope.get("validated_claims_allowed", False)).lower()),
            html.escape(str(payload.get("expression_layers", {}).get("analysis") or "unknown")),
            html.escape(str(payload.get("expression_layers", {}).get("source") or "unknown")),
        )
    )
    content = """<!doctype html>
<html><head><meta charset="utf-8"><title>Validated Xenium Pilot</title>
<style>body{font-family:Arial,sans-serif;margin:32px;line-height:1.45;color:#1f2933}code{background:#f6f8fa;padding:1px 4px}section{margin:24px 0}li{margin:4px 0}.gallery{display:grid;grid-template-columns:minmax(280px,1fr);gap:18px;max-width:1100px}.figure{border:1px solid #d6dde5;padding:12px;background:#fff}.figure img{max-width:100%%;height:auto}table{border-collapse:collapse;min-width:380px}td,th{border:1px solid #d6dde5;padding:6px 8px;text-align:left}</style>
</head><body>
<h1>Validated Xenium Pilot</h1>
<p>Status: <code>%s</code></p>
<p>Dataset: <code>%s</code>. Loaded %d cells and %d features.</p>
%s
%s
<section><h2>Blocking Reasons</h2><ul>%s</ul></section>
<section><h2>Required Next Inputs</h2><ul>%s</ul></section>
<section><h2>Review Visualizations</h2><p>Generated for QA and expert review from current labels/clusters. These are not validated biological result figures until the gate passes.</p><div class="gallery">%s</div></section>
<section><h2>Current Label Summary</h2><table><tr><th>Label</th><th>Count</th></tr>%s</table></section>
<section><h2>Current Region Summary</h2><table><tr><th>Region</th><th>Count</th></tr>%s</table></section>
<section><h2>Typed Tool Plan</h2><p>Plan validation: <code>%s</code></p><ul>%s</ul></section>
<section><h2>Generated Templates</h2><ul><li><code>%s</code></li><li><code>%s</code></li></ul></section>
<section><h2>Tool Results</h2>%s</section>
%s
%s
%s
<section><h2>Claim Ledger</h2><ul>%s</ul></section>
<section><h2>Claim Reliability</h2><table><tr><th>Claim</th><th>Reliability</th><th>S</th><th>A</th><th>P</th><th>R</th><th>Interpretation</th></tr>%s</table><p><small>S = statistical strength, A = annotation quality, P = panel adequacy, R = spatial robustness. The current default combiner is weakest-link.</small></p></section>
%s
<section><h2>Limitations</h2><ul>%s</ul></section>
<section><h2>Run Record</h2><p><code>%s</code></p></section>
<section><h2>Claim Policy</h2><p>Validated biological claims require expert labels and user-provided regions. Weak labels remain software QA only.</p></section>
</body></html>""" % (
        html.escape(payload["status"]),
        html.escape(payload["dataset_path"]),
        payload["records_loaded"],
        payload["features_loaded"],
        scope_html,
        descriptive_html,
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
        relationship_html,
        region_html,
        cooccurrence_html,
        claims,
        reliability_rows or "<tr><td colspan=\"7\">No reliability records generated.</td></tr>",
        robustness_html,
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
    descriptive_sections = []
    descriptive = payload.get("descriptive_analysis") or {}
    if descriptive.get("status") == "computed":
        qc = descriptive.get("expression_qc") or {}
        diagnostics = descriptive.get("clustering_diagnostics") or {}
        diagnostic_rows = [
            ("Cells loaded", qc.get("n_cells", "-")),
            ("Features analyzed", qc.get("n_features", "-")),
            ("Median counts / cell", qc.get("median_total_counts", "-")),
            ("Median features / cell", qc.get("median_features_per_cell", "-")),
            ("Cells analyzed for clustering", diagnostics.get("analyzed_cell_count", "-")),
            ("Zero-feature cells excluded", diagnostics.get("excluded_zero_feature_cell_count", 0)),
            ("PCA silhouette", diagnostics.get("silhouette", "not computed")),
            ("Weighted graph modularity", diagnostics.get("modularity", "not computed")),
        ]
        cluster_rows = sorted(
            (descriptive.get("cluster_counts") or {}).items(), key=lambda item: -int(item[1])
        )
        marker_rows = [
            (str(cluster), ", ".join(str(gene) for gene in genes[:8]))
            for cluster, genes in sorted((descriptive.get("markers_by_cluster") or {}).items())
        ]
        spatial_gene_rows = [
            (str(item.get("gene")), item.get("morans_i"), item.get("pval_adj", "not available"))
            for item in (descriptive.get("spatial_genes") or {}).get("top_genes", [])[:12]
        ]
        neighborhood_rows = [
            (str(item.get("pair")), item.get("zscore"))
            for item in (descriptive.get("cluster_neighborhood") or {}).get("top_pairs", [])[:10]
        ]
        descriptive_sections = [
            PdfSection(
                title="Descriptive Analysis (no expert labels required)",
                paragraphs=[
                    "Cells are grouped by measured-expression clusters. Cluster identities are not cell-type claims.",
                    str(descriptive.get("interpretation") or ""),
                ],
                tables=[
                    PdfTable(headers=["QC / diagnostic", "Value"], rows=diagnostic_rows, column_widths=[3, 2]),
                    PdfTable(headers=["Cluster", "Cells"], rows=cluster_rows, column_widths=[2, 1]),
                ],
            ),
            PdfSection(
                title="Descriptive Cluster Evidence",
                tables=[
                    PdfTable(headers=["Cluster", "Top marker genes"], rows=marker_rows, column_widths=[1, 4]),
                    PdfTable(
                        headers=["Gene", "Moran's I", "Adjusted p-value"],
                        rows=spatial_gene_rows,
                        column_widths=[2, 1, 1.4],
                    ),
                    PdfTable(headers=["Cluster pair", "z-score"], rows=neighborhood_rows, column_widths=[3, 1]),
                ],
            ),
        ]
    sections = [
        PdfSection(
            title="Executive Summary",
            paragraphs=[
                "This report records the validation-gated Xenium workflow. Biological interpretation is released only when expert labels and user-provided regions pass coverage and diversity gates."
            ],
        ),
        *descriptive_sections,
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
    relationship_summary = payload.get("spatial_relationships") or {}
    relationship_rows = _spatial_relationship_report_rows(payload)
    relationship_paragraphs = ["Status: %s" % relationship_summary.get("status", "not_run")]
    graph = relationship_summary.get("graph") or {}
    if relationship_summary.get("method"):
        relationship_paragraphs.append(
            "Method: %s. Primary graph: n_neighs=%s, n_perms=%s, seed=%s."
            % (
                relationship_summary.get("method"),
                graph.get("n_neighs"),
                graph.get("n_perms"),
                graph.get("random_state"),
            )
        )
    elif relationship_summary.get("reason"):
        relationship_paragraphs.append(str(relationship_summary["reason"]))
    relationship_figures = []
    if relationship_summary.get("figure") and Path(str(relationship_summary["figure"])).exists():
        relationship_figures.append(
            PdfFigure(path=str(relationship_summary["figure"]), caption="Neighborhood enrichment z-score matrix")
        )
    relationship_tables = []
    if relationship_rows:
        relationship_tables.append(
            PdfTable(
                headers=["Pair", "Direction", "z", "Stability", "NN distance", "Region overlap", "Evidence"],
                rows=relationship_rows,
                column_widths=[2.0, 0.8, 0.6, 0.8, 1.0, 0.9, 1.5],
            )
        )
    sections.append(
        PdfSection(
            title="Spatial Relationships",
            paragraphs=relationship_paragraphs,
            bullets=_spatial_relationship_interpretations(payload) + list(relationship_summary.get("warnings") or []),
            tables=relationship_tables,
            figures=relationship_figures,
        )
    )
    region_summary = payload.get("region_stratified_neighborhoods") or {}
    region_rows = _region_stratified_report_rows(payload)
    region_figures = []
    if region_summary.get("figure") and Path(str(region_summary["figure"])).exists():
        region_figures.append(
            PdfFigure(path=str(region_summary["figure"]), caption="Within-region neighborhood enrichment z-scores")
        )
    region_tables = []
    if region_rows:
        region_tables.append(
            PdfTable(
                headers=["Pair", "Tested / supported", "Direction agreement", "Strongest region", "Strongest |z|", "Status"],
                rows=region_rows,
                column_widths=[2.0, 0.7, 1.1, 1.3, 0.8, 1.2],
            )
        )
    region_paragraphs = ["Status: %s." % region_summary.get("status", "not_run")]
    if "tested_region_count" in region_summary:
        region_paragraphs.append(
            "Tested regions: %s; skipped regions: %s."
            % (region_summary.get("tested_region_count", 0), region_summary.get("skipped_region_count", 0))
        )
    if region_summary.get("parameters", {}).get("min_abs_zscore") is not None:
        region_paragraphs.append(
            "Consistency requires |z| >= %s in at least two regions."
            % region_summary["parameters"]["min_abs_zscore"]
        )
    if region_summary.get("reason"):
        region_paragraphs.append(str(region_summary["reason"]))
    sections.append(
        PdfSection(
            title="Region-Stratified Neighborhood Testing",
            paragraphs=region_paragraphs,
            bullets=list(region_summary.get("warnings") or []),
            tables=region_tables,
            figures=region_figures,
        )
    )
    cooccurrence_summary = payload.get("distance_cooccurrence") or {}
    cooccurrence_rows = _distance_cooccurrence_report_rows(payload)
    cooccurrence_figures = []
    if cooccurrence_summary.get("figure") and Path(str(cooccurrence_summary["figure"])).exists():
        cooccurrence_figures.append(
            PdfFigure(path=str(cooccurrence_summary["figure"]), caption="Distance-dependent conditional co-occurrence ratios")
        )
    cooccurrence_tables = []
    if cooccurrence_rows:
        cooccurrence_tables.append(
            PdfTable(
                headers=["Pair", "Peak ratio", "Peak distance", "Short-range mean", "Long-range mean"],
                rows=cooccurrence_rows,
                column_widths=[2.2, 0.9, 1.1, 1.2, 1.2],
            )
        )
    cooccurrence_paragraphs = ["Status: %s." % cooccurrence_summary.get("status", "not_run")]
    if cooccurrence_summary.get("status") == "computed":
        cooccurrence_paragraphs.append(
            "Distance range: 0-%s %s across %s thresholds; minimum %s cells per type."
            % (
                cooccurrence_summary.get("max_distance"),
                cooccurrence_summary.get("coordinate_units", "dataset units"),
                cooccurrence_summary.get("n_intervals"),
                cooccurrence_summary.get("min_cells_per_type", "not recorded"),
            )
        )
    if cooccurrence_summary.get("reason"):
        cooccurrence_paragraphs.append(str(cooccurrence_summary["reason"]))
    sections.append(
        PdfSection(
            title="Distance-Dependent Co-Occurrence",
            paragraphs=cooccurrence_paragraphs,
            bullets=list(cooccurrence_summary.get("warnings") or []),
            tables=cooccurrence_tables,
            figures=cooccurrence_figures,
        )
    )
    sections.append(
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
        )
    )
    robustness_rows = _spatial_robustness_rows(payload)
    if robustness_rows:
        sections.append(
            PdfSection(
                title="Spatial Robustness Sweep",
                paragraphs=[
                    "The R component is measured by rerunning neighborhood enrichment across graph-size settings and comparing sign agreement plus top-K pair overlap."
                ],
                tables=[
                    PdfTable(
                        headers=["Setting / metric", "Value"],
                        rows=robustness_rows,
                        column_widths=[2, 3],
                    )
                ],
            )
        )
    sections.extend(
        [
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
            ("Analysis scope", payload.get("analysis_scope", {}).get("scope", "unknown")),
            (
                "Cells represented",
                "%s/%s"
                % (
                    payload.get("analysis_scope", {}).get("loaded_records", 0),
                    payload.get("analysis_scope", {}).get("total_records", 0),
                ),
            ),
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
        "| Dataset | Status | Labels | Regions | Readiness JSON |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in summary["datasets"]:
        lines.append(
            "| `%s` | `%s` | `%s` | `%s` | `%s` |"
            % (
                item["dataset_path"],
                item["status"],
                item["label_status"],
                item["region_status"],
                item.get("pilot_validation") or item.get("report_md") or "",
            )
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


def _spatial_relationship_report_rows(
    payload: Dict[str, Any],
) -> List[Tuple[str, str, str, str, str, str, str]]:
    summary = payload.get("spatial_relationships")
    if not isinstance(summary, dict) or summary.get("status") != "computed":
        return []
    rows = []
    for item in summary.get("relationships") or []:
        if not isinstance(item, dict):
            continue
        sign_agreement = item.get("sign_agreement")
        top_k_presence = item.get("top_k_presence")
        settings_present = int(item.get("settings_present") or 0)
        stability = (
            "sign %.2f; top-K %.2f (%d settings)"
            % (float(sign_agreement), float(top_k_presence), settings_present)
            if sign_agreement is not None and top_k_presence is not None
            else "sign %.2f (%d settings)" % (float(sign_agreement), settings_present)
            if sign_agreement is not None
            else "not established"
        )
        distance = item.get("median_bidirectional_nearest_distance")
        distance_text = (
            "%.3f %s" % (float(distance), item.get("coordinate_units") or "units")
            if distance is not None
            else "not available"
        )
        region_overlap = item.get("region_overlap")
        shared_regions = ", ".join(str(value) for value in item.get("shared_regions") or [])
        region_text = (
            "%.3f%s" % (float(region_overlap), " (%s)" % shared_regions if shared_regions else "")
            if region_overlap is not None
            else "not available"
        )
        rows.append(
            (
                str(item.get("pair") or "").replace("|", "/"),
                str(item.get("direction") or "indeterminate"),
                "%.4f" % float(item.get("zscore") or 0.0),
                stability,
                distance_text,
                region_text,
                str(item.get("evidence_status") or "weak_or_indeterminate"),
            )
        )
    return rows


def _spatial_relationship_interpretations(payload: Dict[str, Any]) -> List[str]:
    summary = payload.get("spatial_relationships")
    if not isinstance(summary, dict) or summary.get("status") != "computed":
        return []
    interpretations = []
    for item in summary.get("relationships") or []:
        if not isinstance(item, dict) or not item.get("allowed_interpretation"):
            continue
        interpretations.append("%s: %s" % (item.get("pair") or "Pair", item["allowed_interpretation"]))
    return interpretations


def _region_stratified_report_rows(
    payload: Dict[str, Any],
) -> List[Tuple[str, str, str, str, str, str]]:
    summary = payload.get("region_stratified_neighborhoods")
    if not isinstance(summary, dict) or summary.get("status") != "computed":
        return []
    rows = []
    for item in (summary.get("pair_consistency") or [])[:12]:
        if not isinstance(item, dict):
            continue
        rows.append(
            (
                str(item.get("pair") or "").replace("|", "/"),
                "%s / %s"
                % (
                    item.get("regions_tested") or 0,
                    item.get("supported_region_count", item.get("regions_tested") or 0),
                ),
                "%.3f" % float(item.get("direction_agreement") or 0.0),
                str(item.get("strongest_region") or "not available"),
                "%.3f" % float(item.get("strongest_abs_zscore") or 0.0),
                str(item.get("status") or "unknown"),
            )
        )
    return rows


def _distance_cooccurrence_report_rows(
    payload: Dict[str, Any],
) -> List[Tuple[str, str, str, str, str]]:
    summary = payload.get("distance_cooccurrence")
    if not isinstance(summary, dict) or summary.get("status") != "computed":
        return []
    units = str(summary.get("coordinate_units") or "units")
    rows = []
    for item in summary.get("curves") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            (
                str(item.get("pair") or "").replace("|", "/"),
                "%.3f" % float(item.get("peak_ratio") or 0.0),
                "%.3f %s" % (float(item.get("peak_distance") or 0.0), units),
                "%.3f" % float(item.get("short_range_mean_ratio") or 0.0),
                "%.3f" % float(item.get("long_range_mean_ratio") or 0.0),
            )
        )
    return rows


def _spatial_robustness_rows(payload: Dict[str, Any]) -> List[Tuple[str, str]]:
    if payload.get("status") != "validated_ready":
        return []
    sweep = payload.get("spatial_robustness")
    if not isinstance(sweep, dict):
        return []
    settings = sweep.get("requested_settings") or sweep.get("settings") or []
    rows = [
        ("Status", str(sweep.get("status") or "not_run")),
        ("Robustness score", "%.4f" % float(sweep.get("score") or 0.0)),
        ("Neighborhood graph sizes (n_neighs)", ", ".join(str(value) for value in settings) or "not recorded"),
        ("Permutations per setting", str(sweep.get("n_perms") if sweep.get("n_perms") is not None else "not recorded")),
        ("Random seed", str(sweep.get("random_state") if sweep.get("random_state") is not None else "not recorded")),
        ("Top-K pairs", str(sweep.get("top_k") if sweep.get("top_k") is not None else "not recorded")),
        ("Engines", ", ".join(str(value) for value in sweep.get("engines", [])) or "not recorded"),
    ]
    if sweep.get("mean_sign_agreement") is not None:
        rows.append(("Mean sign agreement", "%.4f" % float(sweep["mean_sign_agreement"])))
    if sweep.get("mean_topk_jaccard") is not None:
        rows.append(("Mean top-K Jaccard", "%.4f" % float(sweep["mean_topk_jaccard"])))
    if sweep.get("n_reference_pairs") is not None:
        rows.append(("Reference pairs evaluated", str(sweep["n_reference_pairs"])))
    return rows


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
    if payload.get("analysis_scope", {}).get("scope") != "full_section":
        items.append(
            "This run is a deterministic cell sample, not a complete-section analysis; final biological claims require a full-section rerun."
        )
    if payload.get("status") != "validated_ready":
        items.append(
            "Validation-gated biological tools were not run because required inputs are incomplete; "
            "the reported QC, expression clusters, cluster markers, spatial genes, and cluster neighborhoods are descriptive analyses only."
        )
    if payload.get("region_stratified_neighborhoods", {}).get("status") == "computed":
        items.append("Region-stratified tests are within-section analyses; biological generalization requires replicate sections or donors.")
    if payload.get("distance_cooccurrence", {}).get("status") == "computed":
        items.append("Distance-dependent co-occurrence curves are descriptive probability ratios and do not provide permutation significance tests.")
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


def _descriptive_markdown(payload: Dict[str, Any]) -> List[str]:
    """Label-free results, rendered before any refusal text."""
    descriptive = payload.get("descriptive_analysis") or {}
    if descriptive.get("status") != "computed":
        return []
    lines = [
        "## Descriptive Analysis (no expert labels required)",
        "",
        "These results group cells by data-derived expression clusters, so they stand "
        "without expert annotation. Cluster identities are not cell-type claims.",
        "",
    ]
    qc = descriptive.get("expression_qc") or {}
    if qc:
        lines.extend([
            "| QC metric | Value |",
            "| --- | ---: |",
            "| Cells | %s |" % qc.get("n_cells", "-"),
            "| Features | %s |" % qc.get("n_features", "-"),
            "| Median counts / cell | %s |" % qc.get("median_total_counts", "-"),
            "| Median features / cell | %s |" % qc.get("median_features_per_cell", "-"),
            "",
        ])
    counts = descriptive.get("cluster_counts") or {}
    if counts:
        lines.extend(["### Expression clusters (%s)" % (descriptive.get("clustering_method") or "leiden"), "",
                      "| Cluster | Cells |", "| --- | ---: |"])
        for cluster, count in sorted(counts.items(), key=lambda item: -int(item[1])):
            lines.append("| `%s` | %s |" % (cluster, count))
        lines.append("")
    diagnostics = descriptive.get("clustering_diagnostics") or {}
    if diagnostics:
        lines.extend(
            [
                "### Clustering diagnostics",
                "",
                "| Diagnostic | Value |",
                "| --- | ---: |",
                "| Cells analyzed | %s |" % diagnostics.get("analyzed_cell_count", "-"),
                "| Zero-feature cells excluded | %s |"
                % diagnostics.get("excluded_zero_feature_cell_count", 0),
                "| PCA silhouette | %s |" % diagnostics.get("silhouette", "not computed"),
                "| Weighted graph modularity | %s |" % diagnostics.get("modularity", "not computed"),
                "",
            ]
        )
    markers = descriptive.get("markers_by_cluster")
    if isinstance(markers, dict) and markers:
        lines.extend(["### Top markers per cluster (one-vs-rest)", "",
                      "| Cluster | Marker genes |", "| --- | --- |"])
        for cluster, genes in sorted(markers.items()):
            lines.append("| `%s` | %s |" % (cluster, ", ".join("`%s`" % gene for gene in genes[:6])))
        lines.append("")
    spatial_genes = descriptive.get("spatial_genes") or {}
    if spatial_genes.get("top_genes"):
        lines.extend(
            [
                "### Spatially autocorrelated genes",
                "",
                "Method: `%s`; permutations: `%s`; multiple testing: `%s`"
                % (
                    spatial_genes.get("method"),
                    spatial_genes.get("n_perms"),
                    spatial_genes.get("multiple_testing"),
                ),
                "",
                _spatial_screen_note(spatial_genes),
                "",
                "| Gene | Moran's I | Adjusted p-value |",
                "| --- | ---: | ---: |",
            ]
        )
        for item in spatial_genes["top_genes"][:12]:
            lines.append(
                "| `%s` | %s | %s |"
                % (item.get("gene"), item.get("morans_i"), item.get("pval_adj", "not available"))
            )
        lines.append("")
    neighborhood = descriptive.get("cluster_neighborhood")
    if isinstance(neighborhood, dict) and neighborhood.get("top_pairs"):
        lines.extend(["### Cluster spatial co-occurrence", "",
                      "| Cluster pair | z-score |", "| --- | ---: |"])
        for pair in neighborhood["top_pairs"][:8]:
            lines.append("| `%s` | %s |" % (pair.get("pair"), pair.get("zscore")))
        lines.append("")
    warning = descriptive.get("sampling_warning")
    if warning:
        lines.extend(["> **Sampling note:** %s" % warning, ""])
    stages = descriptive.get("stage_seconds") or {}
    if stages:
        lines.extend(["### Stage timings (seconds)", "", "| Stage | Seconds |", "| --- | ---: |"])
        for stage, seconds in sorted(stages.items(), key=lambda item: -float(item[1])):
            lines.append("| `%s` | %s |" % (stage, seconds))
        lines.append("")
    figures = descriptive.get("figures") or []
    if figures:
        lines.extend(["### Descriptive figures", ""])
        lines.extend("- `%s`" % Path(item).name for item in figures)
        lines.append("")
    lines.extend([descriptive.get("interpretation", ""), ""])
    return lines


def _descriptive_html(payload: Dict[str, Any]) -> str:
    """Render label-free results before validation blockers in the HTML report."""
    descriptive = payload.get("descriptive_analysis") or {}
    if descriptive.get("status") != "computed":
        return ""
    qc = descriptive.get("expression_qc") or {}
    diagnostics = descriptive.get("clustering_diagnostics") or {}
    qc_rows = [
        ("Cells loaded", qc.get("n_cells", "-")),
        ("Features analyzed", qc.get("n_features", "-")),
        ("Median counts / cell", qc.get("median_total_counts", "-")),
        ("Median features / cell", qc.get("median_features_per_cell", "-")),
        ("Cells analyzed for clustering", diagnostics.get("analyzed_cell_count", "-")),
        ("Zero-feature cells excluded", diagnostics.get("excluded_zero_feature_cell_count", 0)),
        ("PCA silhouette", diagnostics.get("silhouette", "not computed")),
        ("Weighted graph modularity", diagnostics.get("modularity", "not computed")),
    ]
    qc_table = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (html.escape(str(label)), html.escape(str(value)))
        for label, value in qc_rows
    )
    cluster_rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (html.escape(str(cluster)), html.escape(str(count)))
        for cluster, count in sorted(
            (descriptive.get("cluster_counts") or {}).items(), key=lambda item: -int(item[1])
        )
    )
    marker_rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>"
        % (html.escape(str(cluster)), html.escape(", ".join(str(gene) for gene in genes[:8])))
        for cluster, genes in sorted((descriptive.get("markers_by_cluster") or {}).items())
    )
    spatial_gene_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (
            html.escape(str(item.get("gene"))),
            html.escape(str(item.get("morans_i"))),
            html.escape(str(item.get("pval_adj", "not available"))),
        )
        for item in (descriptive.get("spatial_genes") or {}).get("top_genes", [])[:12]
    )
    neighborhood_rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>"
        % (html.escape(str(item.get("pair"))), html.escape(str(item.get("zscore"))))
        for item in (descriptive.get("cluster_neighborhood") or {}).get("top_pairs", [])[:10]
    )
    return (
        "<section><h2>Descriptive Analysis (no expert labels required)</h2>"
        "<p>Cells are grouped by measured-expression clusters. Cluster identities are not cell-type claims.</p>"
        "<h3>QC and clustering diagnostics</h3><table><tr><th>Metric</th><th>Value</th></tr>%s</table>"
        "<h3>Expression clusters (%s)</h3><table><tr><th>Cluster</th><th>Cells</th></tr>%s</table>"
        "<h3>Top markers per cluster</h3><table><tr><th>Cluster</th><th>Marker genes</th></tr>%s</table>"
        "<h3>Spatially autocorrelated genes</h3><table><tr><th>Gene</th><th>Moran's I</th><th>Adjusted p-value</th></tr>%s</table>"
        "<h3>Cluster spatial co-occurrence</h3><table><tr><th>Pair</th><th>z-score</th></tr>%s</table>"
        "%s"
        "<p>%s</p></section>"
        % (
            qc_table,
            html.escape(str(descriptive.get("clustering_method") or "leiden")),
            cluster_rows,
            marker_rows,
            spatial_gene_rows,
            neighborhood_rows,
            _descriptive_figures_html(descriptive),
            html.escape(str(descriptive.get("interpretation") or "")),
        )
    )


def _descriptive_figures_html(descriptive: Dict[str, Any]) -> str:
    figures = descriptive.get("figures") or []
    if not figures:
        return ""
    return (
        "<h3>Descriptive figures</h3><div class=\"gallery\">%s</div>"
        % "".join(_figure_html(item) for item in figures)
    )


def _spatial_screen_note(spatial_genes: Dict[str, Any]) -> str:
    """State the gene screen, so significance counts are not read as whole-panel."""
    screen = spatial_genes.get("screening") or {}
    if not screen:
        return ""
    return (
        "Screened before permutation testing: %s. Of %s panel genes, %s were detected and %s were "
        "tested; %s of the tested genes passed FDR <= 0.05. Adjusted p-values are corrected over the "
        "tested set and are conditional on this screen."
        % (
            screen.get("rule", "unknown rule"),
            screen.get("panel_genes", "?"),
            screen.get("detected_genes", "?"),
            screen.get("tested_genes", "?"),
            spatial_genes.get("significant_gene_count_all", "?"),
        )
    )
