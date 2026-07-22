from typing import List

from spatialmind.contracts import DatasetReadinessReport, WorkflowReadiness
from spatialmind.schemas import SpatialDataset


CELL_LABEL_PLACEHOLDERS = {"", "unknown", "unannotated", "unannotated cell", "none", "nan"}


def build_readiness_report(dataset: SpatialDataset) -> DatasetReadinessReport:
    """Score which workflows are scientifically supportable for a dataset."""

    has_records = len(dataset.records) > 0
    has_coords = _has_spatial_coordinates(dataset)
    has_features = len(dataset.genes) > 0
    has_cell_labels = _has_cell_type_labels(dataset)
    has_regions = any(record.region for record in dataset.records)
    has_user_regions = _has_user_region_labels(dataset)
    label_status = _label_readiness_status(dataset)
    has_weak_labels = label_status in {"weak_marker_rule_labels", "missing_expert_labels"}
    has_multiple_samples = len({record.sample_id for record in dataset.records}) > 1
    modality = dataset.modality
    assay_subtype = str(dataset.metadata.get("assay_subtype") or "")
    is_scrna = modality == "scrna" or assay_subtype == "scrna"
    is_scatac = modality == "scatac" or assay_subtype == "scatac_gene_activity"
    is_xenium = modality in {"xenium_spatial_rna", "spatial_transcriptomics"} or assay_subtype == "xenium_spatial_rna"
    is_rna = modality in {"scrna", "xenium_spatial_rna", "spatial_transcriptomics", "annotated_expression", "spatial_table", "tidy_csv"} or assay_subtype in {"scrna", "xenium_spatial_rna"}
    is_protein = modality in {"multiplexed_protein", "protein_imaging"}
    is_atac = modality in {"scatac", "spatial_atac", "chromatin_accessibility"} or assay_subtype == "scatac_gene_activity"
    has_matrix = bool(dataset.metadata.get("gene_matrix", {}).get("available")) or has_features

    workflows: List[WorkflowReadiness] = [
        _workflow("spatial_visualization", has_records and has_coords, "coordinates available", "no spatial coordinates"),
        _workflow("gene_expression_overlay", has_features and has_coords, "features and coordinates available", "missing expression/features or coordinates"),
        _workflow(
            "spatial_clustering",
            has_features and has_coords and dataset.normalized,
            "normalized features and coordinates available",
            "requires normalized features and spatial coordinates",
        ),
        _workflow(
            "neighborhood_enrichment",
            has_cell_labels and has_coords,
            (
                "provisional cell labels and coordinates are available; results are exploratory"
                if has_weak_labels
                else "reviewed cell-type labels and coordinates available"
            ),
            "no usable cell-type labels; run annotation first",
            partial=has_weak_labels,
        ),
        _workflow(
            "differential_expression",
            has_features and has_cell_labels and dataset.normalized,
            (
                "normalized features and provisional group labels are available; results are exploratory"
                if has_weak_labels
                else "normalized features and reviewed group labels available"
            ),
            "requires normalized features and biological group labels",
            partial=has_weak_labels,
        ),
        _workflow(
            "marker_detection",
            has_features and dataset.normalized,
            "normalized feature matrix available for adjusted marker detection",
            "requires normalized features",
            partial=is_scatac,
        ),
        _workflow(
            "spatial_variable_genes",
            is_rna and has_matrix and has_coords,
            "RNA matrix/features and coordinates available",
            "requires spatial transcriptomics features and coordinates",
        ),
        _workflow(
            "spatial_deconvolution",
            False,
            "RNA matrix available; external scRNA reference still recommended",
            "deconvolution is deferred to v1.0 for the MVP",
        ),
        _workflow(
            "cnv_inference",
            is_rna and has_matrix,
            "RNA expression available; normal reference may be auto-selected",
            "requires transcriptomics expression matrix",
            partial=not has_regions,
        ),
        _workflow(
            "protein_coexpression",
            is_protein and has_features,
            "protein marker intensities available",
            "requires multiplex protein marker matrix",
        ),
        _workflow(
            "chromatin_accessibility_spatial",
            is_atac and has_features,
            "spatial chromatin accessibility features available",
            "requires spatial ATAC peak or fragment features",
        ),
        _workflow(
            "qc_and_cluster",
            has_records and has_features,
            "cell-by-feature matrix available",
            "requires a cell-by-feature matrix",
        ),
        _workflow(
            "annotation",
            has_records and has_features,
            "cell-by-feature matrix available for marker or model annotation",
            "requires a cell-by-feature matrix",
            partial=is_scatac,
        ),
        _workflow(
            "feature_overlay",
            has_records and has_features,
            "features are available for embedding or spatial overlay",
            "requires feature values",
        ),
        _workflow(
            "trajectory_inference",
            False,
            "trajectory inference is deferred to v0.5",
            "trajectory inference is deferred to v0.5 for the MVP",
        ),
        _workflow(
            "motif_tf_activity",
            False,
            "motif/TF activity is deferred to v0.5",
            "motif/TF activity is deferred to v0.5; MVP scATAC supports gene-activity marker detection only",
        ),
        _workflow(
            "cell_neighborhood_enrichment",
            is_xenium and has_cell_labels and has_coords,
            "Xenium cell labels and subcellular coordinates available",
            "cell-neighborhood enrichment requires Xenium labels and coordinates",
            partial=has_weak_labels,
        ),
        _workflow(
            "region_summary",
            is_xenium and has_user_regions,
            "user-provided region labels available",
            "region_summary requires user-provided region labels",
        ),
        _workflow(
            "reference_label_transfer",
            False,
            "full reference label transfer is deferred to v0.5",
            "full reference label transfer is deferred to v0.5; MVP supports reference-assisted annotation only",
        ),
        _workflow(
            "deferred_v1_workflow",
            False,
            "",
            "requested workflow is deferred to v1.0 in the MVP scope",
        ),
        _workflow(
            "niche_differential_analysis",
            has_multiple_samples and has_cell_labels,
            "multiple samples and labels available",
            "requires multiple samples plus cell-type labels",
            partial=has_weak_labels,
        ),
    ]

    warnings = list(dataset.notes)
    if not has_cell_labels:
        warnings.append("Cell-type labels are missing or only placeholder values.")
    if has_weak_labels:
        warnings.append("Current cell labels are weak or missing; expert/user labels or validated reference-assisted labels are needed for strong biological claims.")
    if has_regions and not has_user_regions:
        warnings.append("Detected region metadata is not marked as user-provided; region_summary remains blocked.")
    if not dataset.normalized:
        warnings.append("Dataset is not marked normalized; statistical workflows may be blocked.")
    if is_scatac:
        warnings.append("scATAC gene activity is accessibility-inferred and must not be described as measured expression.")
    if is_xenium:
        warnings.append("Xenium is a targeted panel; panel-absent genes are not measured, not unexpressed.")
    return DatasetReadinessReport(
        sample_id=dataset.sample_id,
        modality=dataset.modality,
        workflows=workflows,
        warnings=_dedupe(warnings),
        qc_passed=bool(dataset.qc_metrics.get("record_count", len(dataset.records)) > 0),
    )


def _workflow(
    name: str,
    ready: bool,
    ready_reason: str,
    blocked_reason: str,
    partial: bool = False,
) -> WorkflowReadiness:
    if ready and partial:
        return WorkflowReadiness(workflow=name, status="partial", reason=ready_reason)
    if ready:
        return WorkflowReadiness(workflow=name, status="ready", reason=ready_reason)
    return WorkflowReadiness(workflow=name, status="blocked", reason=blocked_reason)


def _has_spatial_coordinates(dataset: SpatialDataset) -> bool:
    if not dataset.records:
        return False
    bounds = dataset.bounds()
    return bounds["max_x"] != bounds["min_x"] or bounds["max_y"] != bounds["min_y"]


def _has_cell_type_labels(dataset: SpatialDataset) -> bool:
    labels = {label.strip().lower() for label in dataset.cell_types}
    return bool(labels) and not labels.issubset(CELL_LABEL_PLACEHOLDERS)


def _label_readiness_status(dataset: SpatialDataset) -> str:
    label_readiness = dataset.metadata.get("label_readiness")
    if isinstance(label_readiness, dict):
        return str(label_readiness.get("status") or "")
    return ""


def _has_user_region_labels(dataset: SpatialDataset) -> bool:
    regions = {str(record.region).strip() for record in dataset.records if record.region}
    if not regions:
        return False
    if dataset.metadata.get("region_label_source") == "user_provided":
        return True
    if len(regions) > 1 and dataset.source_path.endswith((".csv", ".tsv", ".json")):
        return True
    return False


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
