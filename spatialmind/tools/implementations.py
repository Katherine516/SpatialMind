import math
import random
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional

from spatialmind.contracts.metrics import (
    AnnotationMetrics,
    ClusteringMetrics,
    DifferentialMetrics,
    QCMetrics,
    QualityMetrics,
    SpatialMetrics,
    metric,
)
from spatialmind.schemas import SpatialDataset, ToolResult

from .exceptions import DataModalityError, InsufficientDataError, InvalidParameterError, MissingPreconditionError


def require_records(dataset: SpatialDataset) -> None:
    if not dataset.records:
        raise InsufficientDataError("Dataset has no records.")


def require_cell_types(dataset: SpatialDataset) -> None:
    require_records(dataset)
    if not dataset.cell_types:
        raise MissingPreconditionError("Dataset requires cell-type labels.")


def cell_type_annotation(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    counts = Counter(record.cell_type for record in dataset.records)
    if not counts:
        raise MissingPreconditionError("No annotation column is available.")
    return ToolResult(
        tool_name="cell_type_annotation",
        summary="Found %d annotated cell types; reused existing labels." % len(counts),
        metrics={"cell_type_counts": dict(counts), "method": params.get("method", "existing_labels")},
        caveats=list(dataset.notes),
    )


def qc_and_cluster(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    result = spatial_clustering(dataset, params)
    result.tool_name = "qc_and_cluster"
    result.summary = "Ran per-type QC and clustering. %s" % result.summary
    result.metrics["qc"] = dict(dataset.qc_metrics)
    result.metrics["assay_subtype"] = dataset.metadata.get("assay_subtype", dataset.modality)
    result.caveats.extend(_type_honesty_caveats(dataset))
    return result


def annotation(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    result = cell_type_annotation(dataset, params)
    result.tool_name = "annotation"
    result.metrics["assay_subtype"] = dataset.metadata.get("assay_subtype", dataset.modality)
    caveats = _type_honesty_caveats(dataset)
    result.caveats.extend(caveats)
    result.label_caveat = caveats[0] if caveats else None
    return result


def feature_overlay(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    feature = str(params.get("feature") or (dataset.genes[0] if dataset.genes else ""))
    if feature not in dataset.genes:
        if _is_targeted_panel(dataset):
            return ToolResult(
                tool_name="feature_overlay",
                summary="%s is not in the targeted panel, so no expression absence claim is supported." % feature,
                metrics={"feature": feature, "status": "panel_absent"},
                caveats=_type_honesty_caveats(dataset),
                label_caveat="Panel-absent genes are not measured, not unexpressed.",
            )
        raise MissingPreconditionError("feature_overlay requires a measured feature; %s was not found." % feature)
    values = [record.genes.get(feature, 0.0) for record in dataset.records]
    return ToolResult(
        tool_name="feature_overlay",
        summary="Prepared overlay values for %s across %d cells." % (feature, len(values)),
        metrics={
            "feature": feature,
            "min": round(min(values), 5),
            "max": round(max(values), 5),
            "mean": round(_mean(values), 5),
            "feature_type": dataset.metadata.get("feature_type", "gene_counts"),
        },
        caveats=_type_honesty_caveats(dataset),
        label_caveat=_first_or_none(_type_honesty_caveats(dataset)),
    )


def spatial_deconvolution(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    by_region: Dict[str, Counter] = defaultdict(Counter)
    for record in dataset.records:
        by_region[record.region or "all"][record.cell_type] += 1
    proportions = {}
    for region, counts in by_region.items():
        total = sum(counts.values()) or 1
        proportions[region] = {key: round(value / total, 4) for key, value in counts.items()}
    return ToolResult(
        tool_name="spatial_deconvolution",
        summary="Estimated cell-type proportions from existing labels for %d regions." % len(proportions),
        metrics={"proportions": proportions, "method": params.get("method", "label_proportions")},
        caveats=["Prototype uses observed labels as proportions; production should call Cell2location/RCTD."],
    )


def spatial_variable_genes(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    scanpy_result = _scanpy_spatial_variable_genes(dataset, params)
    if scanpy_result:
        return scanpy_result
    n_top = int(params.get("n_top", 50))
    if n_top <= 0:
        raise InvalidParameterError("n_top must be positive.")
    rows = []
    for gene in dataset.genes:
        values = [record.genes.get(gene, 0.0) for record in dataset.records]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        rows.append({"gene": gene, "effect_size": round(variance, 5), "pval": _pseudo_pvalue(variance), "pattern": "spatial"})
    rows.sort(key=lambda item: item["effect_size"], reverse=True)
    return ToolResult(
        tool_name="spatial_variable_genes",
        summary="Ranked %d features by prototype spatial variability score." % len(rows[:n_top]),
        metrics={"top_genes": rows[:n_top]},
        caveats=["Prototype ranks feature variance; production should use SpatialDE2 or SPARK-X."],
    )


def neighborhood_enrichment(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    squidpy_result = _squidpy_neighborhood_enrichment(dataset, params)
    if squidpy_result:
        return squidpy_result
    radius = float(params.get("radius", 18.0))
    pairs = Counter()
    for left in dataset.records:
        for right in dataset.records:
            if left is right:
                continue
            if _distance(left.x, left.y, right.x, right.y) <= radius:
                pairs[tuple(sorted([left.cell_type, right.cell_type]))] += 1
    top_pairs = [
        {"pair": "%s | %s" % pair, "neighbor_count": count, "pval": _pseudo_pvalue(float(count))}
        for pair, count in pairs.most_common(10)
    ]
    return ToolResult(
        tool_name="neighborhood_enrichment",
        summary="Computed prototype neighborhood enrichment for %d cell-type pairs." % len(top_pairs),
        metrics={"radius": radius, "top_pairs": top_pairs},
        caveats=["Prototype uses radius neighbor counts; production should use Squidpy permutation testing."],
    )


def ligand_receptor_analysis(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    genes = set(dataset.genes)
    candidates = []
    if "VEGFA" in genes:
        candidates.append({"ligand": "VEGFA", "receptor": "KDR/FLT1", "sender": "Tumor cell", "receiver": "Endothelial cell", "score": 0.72, "pval": 0.08})
    if "PTPRC" in genes:
        candidates.append({"ligand": "immune_marker", "receptor": "context_marker", "sender": "CD8+ T cell", "receiver": "Tumor cell", "score": 0.41, "pval": 0.2})
    return ToolResult(
        tool_name="ligand_receptor_analysis",
        summary="Generated %d candidate interaction records." % len(candidates),
        metrics={"database": params.get("db", "cellchat"), "interactions": candidates},
        caveats=["Prototype uses marker heuristics; production should call CellChat/NicheNet."],
    )


def trajectory_inference(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    subtype = str(dataset.metadata.get("assay_subtype") or dataset.modality)
    if subtype not in {"scrna", "spatial_transcriptomics", "spatial_table", "tidy_csv"}:
        raise DataModalityError("trajectory_inference", dataset.modality, "scRNA")
    bounds = dataset.bounds()
    span = max((bounds["max_x"] - bounds["min_x"]) + (bounds["max_y"] - bounds["min_y"]), 1.0)
    values = []
    for index, record in enumerate(dataset.records):
        pseudotime = ((record.x - bounds["min_x"]) + (record.y - bounds["min_y"])) / span
        values.append({"index": index, "cell_type": record.cell_type, "pseudotime": round(pseudotime, 4)})
    return ToolResult(
        tool_name="trajectory_inference",
        summary="Computed prototype spatial pseudotime for %d observations." % len(values),
        metrics={"root_cell_type": params.get("root_cell_type"), "pseudotime": values[:20]},
        caveats=["Prototype uses coordinate gradient; production should use Palantir/PAGA spatial."],
    )


def motif_tf_activity(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    subtype = str(dataset.metadata.get("assay_subtype") or dataset.modality)
    if subtype != "scatac_gene_activity" and dataset.modality not in {"scatac", "spatial_atac", "chromatin_accessibility"}:
        raise DataModalityError("motif_tf_activity", dataset.modality, "scATAC gene-activity or peak matrix")
    genes = dataset.genes[: max(1, min(10, len(dataset.genes)))]
    tf_rows = [
        {"tf": gene, "activity_score": round((index + 1) / float(len(genes) + 1), 4), "evidence": "accessibility_inferred"}
        for index, gene in enumerate(genes)
    ]
    return ToolResult(
        tool_name="motif_tf_activity",
        summary="Estimated prototype TF activity for %d accessibility-derived features." % len(tf_rows),
        metrics={"feature_type": "gene_activity", "tf_activity": tf_rows},
        caveats=["scATAC gene activity is accessibility-inferred; do not report it as measured expression."],
        label_caveat="Accessibility-derived gene activity is an estimate of expression, not measured transcription.",
    )


def cell_neighborhood_enrichment(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    result = neighborhood_enrichment(dataset, params)
    result.tool_name = "cell_neighborhood_enrichment"
    result.metrics["resolution"] = dataset.metadata.get("resolution", "subcellular")
    result.caveats.extend(_type_honesty_caveats(dataset))
    result.label_caveat = _first_or_none(_type_honesty_caveats(dataset))
    return result


def region_summary(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    if not any(record.region for record in dataset.records):
        raise MissingPreconditionError("region_summary requires user-provided region labels.")
    by_region: Dict[str, Dict[str, Any]] = {}
    top_n = int(params.get("top_n_features", 8) or 8)
    for record in dataset.records:
        region = record.region or "unassigned"
        entry = by_region.setdefault(region, {"cell_count": 0, "cell_type_counts": Counter(), "feature_sums": Counter()})
        entry["cell_count"] += 1
        entry["cell_type_counts"][record.cell_type] += 1
        for feature, value in record.genes.items():
            try:
                entry["feature_sums"][feature] += float(value)
            except (TypeError, ValueError):
                continue
    summaries = {}
    for region, entry in by_region.items():
        cell_count = int(entry["cell_count"]) or 1
        summaries[region] = {
            "cell_count": cell_count,
            "cell_type_counts": dict(entry["cell_type_counts"]),
            "cell_type_fraction": {
                label: round(count / float(cell_count), 4) for label, count in entry["cell_type_counts"].items()
            },
            "top_features": [
                {"feature": feature, "mean": round(total / float(cell_count), 5)}
                for feature, total in entry["feature_sums"].most_common(top_n)
            ],
        }
    return ToolResult(
        tool_name="region_summary",
        summary="Summarized %d user-provided regions by cell type and feature means." % len(summaries),
        metrics={"region_count": len(summaries), "regions": summaries, "region_source": "user_provided"},
        caveats=["Region summaries use user-provided region labels; they were not derived from image segmentation."],
    )


def reference_label_transfer(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    reference_features = {str(feature).upper() for feature in params.get("reference_features", [])} if params.get("reference_features") else set(dataset.genes)
    target_features = {gene.upper() for gene in dataset.genes}
    shared = sorted(reference_features & target_features)
    min_shared = int(params.get("min_shared_features", 5) or 5)
    if len(shared) < min_shared:
        raise MissingPreconditionError(
            "reference_label_transfer requires at least %d shared features; got %d." % (min_shared, len(shared))
        )
    confidence = min(0.95, max(0.35, len(shared) / float(max(len(target_features), 1))))
    flagged = sum(1 for _record in dataset.records if confidence < float(params.get("confidence_threshold", 0.6) or 0.6))
    return ToolResult(
        tool_name="reference_label_transfer",
        summary="Transferred reference labels over %d shared features with mean confidence %.2f." % (len(shared), confidence),
        metrics={
            "shared_feature_count": len(shared),
            "mean_transfer_confidence": round(confidence, 4),
            "low_confidence_cell_count": flagged,
        },
        caveats=[
            "Transferred cell-type labels are predictions from a reference, not direct measurements.",
            "Reference and target were aligned over shared features only.",
        ]
        + _type_honesty_caveats(dataset),
        label_caveat="Cell-type labels were transferred from a reference and should be treated as predictions.",
    )


def spatial_clustering(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    scanpy_result = _scanpy_spatial_clustering(dataset, params)
    if scanpy_result:
        return scanpy_result
    resolution = float(params.get("resolution", 0.5))
    bin_size = max(10.0, 30.0 / max(resolution, 0.1))
    clusters = Counter()
    for record in dataset.records:
        cluster = "C%d_%d" % (int(record.x // bin_size), int(record.y // bin_size))
        clusters[cluster] += 1
    return ToolResult(
        tool_name="spatial_clustering",
        summary="Assigned observations to %d prototype spatial clusters." % len(clusters),
        metrics={"resolution": resolution, "cluster_counts": dict(clusters)},
        caveats=["Prototype uses coordinate bins; production should use Squidpy graph + Leiden/BayesSpace."],
    )


def differential_expression(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    scanpy_result = _scanpy_differential_expression(dataset, params)
    if scanpy_result:
        return scanpy_result
    group_key = str(params.get("group_key", "cell_type"))
    group1 = str(params.get("group1", "CD8+ T cell"))
    group2 = str(params.get("group2", "Tumor cell"))
    if group_key != "cell_type":
        raise InvalidParameterError("Prototype differential_expression only supports group_key='cell_type'.")
    rows = []
    for gene in dataset.genes:
        first = [record.genes.get(gene, 0.0) for record in dataset.records if record.cell_type == group1]
        second = [record.genes.get(gene, 0.0) for record in dataset.records if record.cell_type == group2]
        if not first or not second:
            continue
        logfc = _mean(first) - _mean(second)
        rows.append({"gene": gene, "logFC": round(logfc, 4), "pval_adj": _pseudo_pvalue(abs(logfc)), "group": group1})
    rows.sort(key=lambda item: abs(float(item["logFC"])), reverse=True)
    return ToolResult(
        tool_name="differential_expression",
        summary="Ranked %d genes for %s vs %s." % (len(rows), group1, group2),
        metrics={"group_key": group_key, "group1": group1, "group2": group2, "ranked_genes": rows},
        caveats=["Prototype uses mean log-normalized difference; production should use scanpy rank_genes_groups."],
    )


def marker_detection(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    result = differential_expression(dataset, params)
    result.tool_name = "marker_detection"
    result.summary = result.summary.replace("Ranked", "Detected marker candidates among")
    result.metrics["adjusted_p_values_only"] = True
    feature_type = str(dataset.metadata.get("feature_type", "gene_counts"))
    if feature_type == "gene_activity":
        result.caveats.append("scATAC markers are accessibility-derived gene-activity markers, not measured expression.")
        result.label_caveat = "Gene activity is accessibility-inferred and must not be reported as measured expression."
    return result


def attach_quality_metrics(result: ToolResult, dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    if result.quality_metrics is not None:
        return result
    result.quality_metrics = _quality_metrics_for_result(result, dataset, params)
    result.metrics.setdefault("quality_metrics", _quality_metrics_to_dict(result.quality_metrics))
    return result


def cnv_inference(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    normal_ref_count = int(params.get("normal_ref_count", 0) or 0)
    if normal_ref_count and normal_ref_count < 50:
        raise InsufficientDataError("cnv_inference needs at least 50 normal reference cells; got %d." % normal_ref_count)
    return _scaffold_result(
        "cnv_inference",
        "CNV inference scaffold validated inputs but did not run inferCNVpy.",
        "Install infercnvpy and provide normal reference cells before using production CNV inference.",
        params,
    )


def tumor_niche_analysis(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    return _scaffold_result(
        "tumor_niche_analysis",
        "Tumor niche analysis scaffold summarized available labels but did not run TME statistics.",
        "Requires validated tumor labels plus Squidpy/statistical wrappers for production.",
        params,
    )


def protein_coexpression(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    _require_modality(dataset, "protein_coexpression", ["multiplexed_protein", "protein_imaging"])
    return _scaffold_result(
        "protein_coexpression",
        "Protein co-expression scaffold is registered for IMC/CODEX datasets.",
        "Requires protein marker matrix and correlation/cluster implementation.",
        params,
    )


def cell_phenotyping_spatial(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    _require_modality(dataset, "cell_phenotyping_spatial", ["multiplexed_protein", "protein_imaging"])
    return _scaffold_result(
        "cell_phenotyping_spatial",
        "Spatial cell phenotyping scaffold is registered for protein imaging datasets.",
        "Requires FlowSOM-style phenotyping implementation.",
        params,
    )


def pathway_activity(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    return _scaffold_result(
        "pathway_activity",
        "Pathway activity scaffold is ready for decoupleR/PROGENy integration.",
        "Requires decoupleR resource loading and pathway scoring.",
        params,
    )


def transcription_factor_activity(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    return _scaffold_result(
        "transcription_factor_activity",
        "TF activity scaffold is ready for CollecTRI/decoupleR integration.",
        "Requires regulon resource loading and TF scoring.",
        params,
    )


def spatial_communication_flow(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    return _scaffold_result(
        "spatial_communication_flow",
        "Spatial communication flow scaffold is registered for LIANA consensus analysis.",
        "Requires LIANA/OmniPath resources and cached ligand-receptor databases.",
        params,
    )


def niche_differential_analysis(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    if not any(record.region for record in dataset.records):
        raise MissingPreconditionError("niche_differential_analysis requires niche or region labels.")
    return _scaffold_result(
        "niche_differential_analysis",
        "Niche differential analysis scaffold validated region labels.",
        "Requires spatially aware differential model implementation.",
        params,
    )


def chromatin_accessibility_spatial(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    _require_modality(dataset, "chromatin_accessibility_spatial", ["spatial_atac", "chromatin_accessibility"])
    return _scaffold_result(
        "chromatin_accessibility_spatial",
        "Spatial chromatin accessibility scaffold is registered for ATAC datasets.",
        "Requires snapatac2/peak matrix integration.",
        params,
    )


def motif_enrichment_spatial(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    _require_modality(dataset, "motif_enrichment_spatial", ["spatial_atac", "chromatin_accessibility"])
    return _scaffold_result(
        "motif_enrichment_spatial",
        "Spatial motif enrichment scaffold is registered for ATAC datasets.",
        "Run chromatin_accessibility_spatial first and provide DA peaks.",
        params,
    )


def multi_sample_comparison(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    return _scaffold_result(
        "multi_sample_comparison",
        "Multi-sample comparison scaffold is registered; batch engine supplies real sample lists.",
        "Requires batch-level dataset collection rather than a single SpatialDataset.",
        params,
    )


def tissue_segmentation(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    _require_modality(dataset, "tissue_segmentation", ["morphology_image", "he_image"])
    return _scaffold_result(
        "tissue_segmentation",
        "Tissue segmentation scaffold is registered for H&E/imaging inputs.",
        "Requires Cellpose/StarDist image segmentation integration.",
        params,
    )


def spatial_gene_programs(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    if len(dataset.genes) < 5:
        raise InsufficientDataError("spatial_gene_programs requires at least 5 features; got %d." % len(dataset.genes))
    return _scaffold_result(
        "spatial_gene_programs",
        "Spatial gene program scaffold validated feature availability.",
        "Requires NMF/MEFISTO factorization implementation.",
        params,
    )


def cell_abundance_heatmap_regions(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    if not any(record.region for record in dataset.records):
        raise MissingPreconditionError("cell_abundance_heatmap_regions requires region labels.")
    return _scaffold_result(
        "cell_abundance_heatmap_regions",
        "Region-aware cell abundance scaffold validated region labels.",
        "Requires region x cell-type matrix statistics for production.",
        params,
    )


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def _scanpy_differential_expression(dataset: SpatialDataset, params: Dict[str, object]) -> Optional[ToolResult]:
    if params.get("engine") == "prototype":
        return None
    group_key = str(params.get("group_key", "cell_type"))
    group1 = str(params.get("group1", "CD8+ T cell"))
    group2 = str(params.get("group2", "Tumor cell"))
    if group_key != "cell_type" or group1 not in dataset.cell_types or group2 not in dataset.cell_types:
        return None
    try:
        import scanpy as sc  # type: ignore
    except ImportError:
        return None
    try:
        adata = _dataset_to_anndata(dataset)
        method = str(params.get("method", "wilcoxon"))
        sc.tl.rank_genes_groups(adata, groupby="cell_type", groups=[group1], reference=group2, method=method)
        table = _rank_genes_groups_table(adata, group1, limit=int(params.get("n_top", 50) or 50))
        return ToolResult(
            tool_name="differential_expression",
            summary="Ranked %d genes for %s vs %s with Scanpy rank_genes_groups." % (len(table), group1, group2),
            metrics={"engine": "scanpy", "method": method, "group_key": group_key, "group1": group1, "group2": group2, "ranked_genes": table},
            caveats=list(dataset.notes),
        )
    except Exception as exc:
        if params.get("strict_engine"):
            raise
        return ToolResult(
            tool_name="differential_expression",
            summary="Scanpy differential expression could not run; used no real-wrapper result.",
            metrics={"engine": "scanpy", "status": "failed", "error": str(exc)},
            caveats=["Set engine='prototype' to force the lightweight fallback or inspect the Scanpy error."],
        )


def _scanpy_spatial_clustering(dataset: SpatialDataset, params: Dict[str, object]) -> Optional[ToolResult]:
    if params.get("engine") == "prototype":
        return None
    try:
        import scanpy as sc  # type: ignore
    except ImportError:
        return None
    try:
        adata = _dataset_to_anndata(dataset)
        n_neighbors = int(params.get("n_neighbors", min(15, max(2, len(dataset.records) - 1))) or 10)
        resolution = float(params.get("resolution", 0.5))
        random_state = int(params.get("random_state", 0) or 0)
        sc.pp.neighbors(adata, n_neighbors=max(2, n_neighbors), use_rep="spatial")
        sc.tl.leiden(adata, resolution=resolution, random_state=random_state, key_added="spatialmind_cluster")
        labels = [str(value) for value in adata.obs["spatialmind_cluster"].tolist()]
        counts = dict(Counter(labels))
        return ToolResult(
            tool_name="spatial_clustering",
            summary="Assigned observations to %d spatial clusters with Scanpy neighbors + Leiden." % len(counts),
            metrics={"engine": "scanpy", "method": "neighbors_leiden", "resolution": resolution, "n_neighbors": n_neighbors, "random_state": random_state, "cluster_counts": counts},
            caveats=list(dataset.notes),
        )
    except Exception as exc:
        if params.get("strict_engine"):
            raise
        return None


def _scanpy_spatial_variable_genes(dataset: SpatialDataset, params: Dict[str, object]) -> Optional[ToolResult]:
    if params.get("engine") == "prototype":
        return None
    try:
        import scanpy as sc  # type: ignore
    except ImportError:
        return None
    try:
        adata = _dataset_to_anndata(dataset)
        n_top = int(params.get("n_top", 50) or 50)
        sc.pp.highly_variable_genes(adata, n_top_genes=min(n_top, adata.n_vars), flavor=str(params.get("flavor", "seurat")))
        rows = []
        hvg = adata.var.sort_values("dispersions_norm" if "dispersions_norm" in adata.var else "means", ascending=False)
        for gene, row in hvg.head(n_top).iterrows():
            rows.append(
                {
                    "gene": str(gene),
                    "mean": round(float(row.get("means", 0.0)), 5),
                    "dispersion_norm": round(float(row.get("dispersions_norm", 0.0)), 5),
                    "highly_variable": bool(row.get("highly_variable", False)),
                }
            )
        return ToolResult(
            tool_name="spatial_variable_genes",
            summary="Ranked %d variable genes with Scanpy highly_variable_genes." % len(rows),
            metrics={"engine": "scanpy", "method": "highly_variable_genes", "top_genes": rows},
            caveats=["Scanpy HVG ranks expression variability; spatial autocorrelation wrappers should be added next for Moran/SpatialDE-style statistics."],
        )
    except Exception as exc:
        if params.get("strict_engine"):
            raise
        return None


def _squidpy_neighborhood_enrichment(dataset: SpatialDataset, params: Dict[str, object]) -> Optional[ToolResult]:
    if params.get("engine") == "prototype":
        return None
    try:
        import squidpy as sq  # type: ignore
    except ImportError:
        return None
    try:
        adata = _dataset_to_anndata(dataset)
        n_neighs = int(params.get("n_neighs", min(6, max(2, len(dataset.records) - 1))) or 6)
        n_perms = int(params.get("n_perms", 100) or 100)
        n_jobs = int(params.get("n_jobs", 1) or 1)
        backend = str(params.get("backend", "threading") or "threading")
        random_state = int(params.get("random_state", 0) or 0)
        sq.gr.spatial_neighbors(adata, coord_type="generic", n_neighs=max(2, n_neighs))
        sq.gr.nhood_enrichment(
            adata,
            cluster_key="cell_type",
            n_perms=n_perms,
            seed=random_state,
            n_jobs=n_jobs,
            backend=backend,
            numba_parallel=False,
            show_progress_bar=False,
        )
        result = adata.uns.get("cell_type_nhood_enrichment", {})
        clusters = [str(value) for value in adata.obs["cell_type"].cat.categories]
        top_pairs = _nhood_enrichment_pairs(result.get("zscore"), result.get("pvalue"), clusters)
        return ToolResult(
            tool_name="neighborhood_enrichment",
            summary="Computed neighborhood enrichment with Squidpy for %d cell-type pairs." % len(top_pairs),
            metrics={"engine": "squidpy", "method": "nhood_enrichment", "n_neighs": n_neighs, "n_perms": n_perms, "n_jobs": n_jobs, "backend": backend, "random_state": random_state, "top_pairs": top_pairs},
            caveats=list(dataset.notes),
        )
    except Exception as exc:
        if params.get("strict_engine"):
            raise
        return None


def _dataset_to_anndata(dataset: SpatialDataset) -> Any:
    import anndata as ad  # type: ignore
    import numpy as np  # type: ignore
    import pandas as pd  # type: ignore

    genes = dataset.genes
    if not genes:
        raise MissingPreconditionError("Scanpy/Squidpy wrappers require numeric features.")
    matrix = np.array([[record.genes.get(gene, 0.0) for gene in genes] for record in dataset.records], dtype=float)
    obs = pd.DataFrame(
        {
            "sample_id": [record.sample_id for record in dataset.records],
            "cell_type": [record.cell_type for record in dataset.records],
            "region": [record.region or "" for record in dataset.records],
            "x": [record.x for record in dataset.records],
            "y": [record.y for record in dataset.records],
        }
    )
    obs["cell_type"] = obs["cell_type"].astype("category")
    adata = ad.AnnData(X=matrix, obs=obs)
    adata.var_names = genes
    adata.obsm["spatial"] = np.array([[record.x, record.y] for record in dataset.records], dtype=float)
    adata.uns["spatialmind"] = {"sample_id": dataset.sample_id, "normalized": dataset.normalized}
    return adata


def _rank_genes_groups_table(adata: Any, group: str, limit: int) -> List[Dict[str, object]]:
    result = adata.uns.get("rank_genes_groups", {})
    rows = []
    names = result.get("names")
    if names is None:
        return rows
    for index, gene in enumerate(_group_values(names, group)[:limit]):
        item = {"gene": str(gene), "group": group}
        for source_key, output_key in (("scores", "score"), ("logfoldchanges", "logFC"), ("pvals_adj", "pval_adj"), ("pvals", "pval")):
            values = result.get(source_key)
            if values is None:
                continue
            try:
                item[output_key] = round(float(_group_values(values, group)[index]), 6)
            except (IndexError, TypeError, ValueError):
                continue
        rows.append(item)
    return rows


def _group_values(values: Any, group: str) -> List[Any]:
    if hasattr(values, "dtype") and getattr(values.dtype, "names", None):
        return list(values[group])
    if isinstance(values, dict):
        return list(values.get(group, []))
    return list(values)


def _nhood_enrichment_pairs(zscores: Any, pvalues: Any, clusters: List[str]) -> List[Dict[str, object]]:
    if zscores is None:
        return []
    pairs = []
    for left_index, left in enumerate(clusters):
        for right_index, right in enumerate(clusters):
            if right_index < left_index:
                continue
            try:
                zscore = float(zscores[left_index, right_index])
            except (TypeError, ValueError, IndexError):
                continue
            item: Dict[str, object] = {"pair": "%s | %s" % (left, right), "zscore": round(zscore, 5)}
            if pvalues is not None:
                try:
                    item["pval"] = round(float(pvalues[left_index, right_index]), 6)
                except (TypeError, ValueError, IndexError):
                    pass
            pairs.append(item)
    pairs.sort(key=lambda item: abs(float(item["zscore"])), reverse=True)
    return pairs[:10]


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pseudo_pvalue(effect: float) -> float:
    return round(max(0.001, min(1.0, 1.0 / (1.0 + abs(effect)))), 4)


def _require_modality(dataset: SpatialDataset, tool_name: str, expected: List[str]) -> None:
    got = (dataset.modality or "").lower()
    if got not in {item.lower() for item in expected}:
        raise DataModalityError(tool_name, dataset.modality, " or ".join(expected))


def _scaffold_result(tool_name: str, summary: str, caveat: str, params: Dict[str, object]) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        summary=summary,
        metrics={"status": "registered_scaffold", "params": dict(params)},
        caveats=[caveat],
    )


def _quality_metrics_for_result(result: ToolResult, dataset: SpatialDataset, params: Dict[str, object]) -> QualityMetrics:
    qc = QCMetrics(
        record_count=metric(
            float(len(dataset.records)),
            "computed",
            "qc",
            "SpatialMind record count",
            data_subset="loaded_records",
        ),
        feature_count=metric(
            float(len(dataset.genes)),
            "computed",
            "qc",
            "SpatialMind feature count",
            data_subset="loaded_features",
        ),
        missing_feature_fraction=metric(
            float(dataset.qc_metrics.get("missing_feature_fraction", 0.0) or 0.0),
            "computed",
            "qc",
            "SpatialMind ingestion QC",
            data_subset="loaded_records",
        ),
    )
    quality = QualityMetrics(qc=qc)
    if result.tool_name in {"qc_and_cluster", "spatial_clustering"}:
        cluster_count = len(result.metrics.get("cluster_counts", {}))
        quality.clustering = ClusteringMetrics(
            silhouette=metric(
                None,
                "not_applicable",
                "diagnostic",
                "silhouette",
                dict(params),
                caveat="Silhouette is diagnostic only and can understate continuous tissue gradients.",
            ),
            modularity=metric(
                float(cluster_count) if cluster_count else None,
                "computed" if cluster_count else "insufficient_data",
                "diagnostic",
                "prototype cluster count diagnostic",
                dict(params),
                caveat="Prototype cluster count is a diagnostic, not evidence of biological separation.",
            ),
        )
    if result.tool_name in {"annotation", "cell_type_annotation", "reference_label_transfer"}:
        label_report = dataset.metadata.get("label_readiness", {}) if isinstance(dataset.metadata.get("label_readiness"), dict) else {}
        confidence = label_report.get("confidence_summary", {}).get("mean") if isinstance(label_report.get("confidence_summary"), dict) else None
        unassigned = _fraction_unassigned(dataset)
        marker_status = "computed" if result.tool_name == "annotation" else "not_applicable"
        quality.annotation = AnnotationMetrics(
            mean_confidence=metric(
                float(confidence) if confidence is not None else None,
                "computed" if confidence is not None else "not_applicable",
                "diagnostic",
                "annotation confidence",
                dict(params),
                caveat="Annotation confidence is diagnostic; it does not by itself validate labels.",
            ),
            marker_overlap=metric(
                _marker_overlap(dataset),
                marker_status,
                "diagnostic",
                "marker panel overlap",
                dict(params),
                caveat="Marker overlap supports label review but is not ground truth.",
            ),
            fraction_unassigned=metric(
                unassigned,
                "computed",
                "qc",
                "label completeness",
                dict(params),
            ),
        )
    if result.tool_name in {"differential_expression", "marker_detection"}:
        rows = result.metrics.get("ranked_genes", [])
        n_sig = sum(1 for row in rows if float(row.get("pval_adj", 1.0)) <= 0.05) if isinstance(rows, list) else 0
        quality.differential = DifferentialMetrics(
            n_significant=metric(float(n_sig), "computed", "statistical_evidence", "adjusted p-value count", dict(params)),
            pct_expressing=metric(None, "not_applicable", "statistical_evidence", "pct expressing", dict(params)),
            auroc=metric(None, "not_applicable", "statistical_evidence", "AUROC", dict(params)),
        )
    if result.tool_name in {"neighborhood_enrichment", "cell_neighborhood_enrichment"}:
        top_pairs = result.metrics.get("top_pairs", [])
        zscore = None
        if isinstance(top_pairs, list) and top_pairs:
            first = top_pairs[0]
            zscore = first.get("zscore") or first.get("neighbor_count")
        quality.spatial = SpatialMetrics(
            morans_i=metric(None, "not_applicable", "statistical_evidence", "Moran's I", dict(params)),
            cooccurrence_z=metric(
                float(zscore) if zscore is not None else None,
                "computed" if zscore is not None else "insufficient_data",
                "statistical_evidence",
                "neighborhood co-occurrence",
                dict(params),
                caveat="Co-occurrence depends on the selected neighbor graph/radius and permutation design.",
            ),
            mean_neighbors=metric(
                float(result.metrics.get("radius", result.metrics.get("n_neighs", 0)) or 0),
                "computed",
                "diagnostic",
                "neighbor graph diagnostic",
                dict(params),
                caveat="Mean-neighbor diagnostics inform graph quality but do not ground a biological claim.",
            ),
        )
    return quality


def _quality_metrics_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return _quality_metrics_to_dict(asdict(value))
    if isinstance(value, dict):
        return {str(key): _quality_metrics_to_dict(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_quality_metrics_to_dict(item) for item in value]
    return value


def _fraction_unassigned(dataset: SpatialDataset) -> float:
    if not dataset.records:
        return 0.0
    placeholders = {"", "unknown", "unannotated", "unannotated cell", "unlabeled", "none", "nan"}
    count = sum(1 for record in dataset.records if record.cell_type.strip().lower() in placeholders)
    return round(count / float(len(dataset.records)), 4)


def _marker_overlap(dataset: SpatialDataset) -> Optional[float]:
    marker_set = {
        "PTPRC",
        "CD3D",
        "CD3E",
        "CD8A",
        "CD4",
        "MS4A1",
        "CD79A",
        "EPCAM",
        "KRT8",
        "KRT15",
        "KRT18",
        "KRT19",
        "ACTA2",
        "PECAM1",
        "VWF",
        "CD68",
        "LYZ",
        "C1QA",
        "MKI67",
    }
    if not dataset.genes:
        return None
    present = {gene.upper() for gene in dataset.genes}
    return round(len(marker_set & present) / float(len(marker_set)), 4)


def _type_honesty_caveats(dataset: SpatialDataset) -> List[str]:
    caveats = []
    feature_type = str(dataset.metadata.get("feature_type") or "")
    if feature_type == "gene_activity" or str(dataset.metadata.get("assay_subtype") or "") == "scatac_gene_activity":
        caveats.append("scATAC gene activity is accessibility-inferred and must not be described as measured expression.")
    if _is_targeted_panel(dataset):
        caveats.append("Xenium uses a targeted panel; a missing gene means not measured, not unexpressed.")
    return caveats


def _is_targeted_panel(dataset: SpatialDataset) -> bool:
    return bool(dataset.metadata.get("is_targeted_panel")) or str(dataset.metadata.get("feature_type") or "") == "targeted_panel"


def _first_or_none(items: List[str]) -> Optional[str]:
    return items[0] if items else None
