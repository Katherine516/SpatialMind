import csv
import gzip
import io
import os
import tarfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..schemas import NON_EXPRESSION_FEATURE_NAMES, SpatialDataset


CELL_ID_KEYS = ("cell_id", "cell", "barcode", "cell_barcode", "spot_id", "id")
LABEL_KEYS = ("expert_label", "cell_type", "celltype", "annotation", "cell_label", "label", "predicted_label")
CONFIDENCE_KEYS = ("confidence", "score", "probability", "prediction_score", "label_confidence")
REGION_KEYS = ("region", "region_label", "tissue_region", "roi", "compartment", "zone", "area")
REGION_CONFIDENCE_KEYS = ("region_confidence", "confidence", "score", "probability")
LABEL_TABLE_NAMES = (
    "expert_cell_labels.csv",
    "expert_cell_labels.tsv",
    "cell_labels.csv",
    "cell_labels.tsv",
    "cell_annotations.csv",
    "cell_annotations.tsv",
    "annotations.csv",
    "annotations.tsv",
    "labels.csv",
    "labels.tsv",
)
REGION_TABLE_NAMES = (
    "cell_regions.csv",
    "cell_regions.tsv",
    "region_labels.csv",
    "region_labels.tsv",
    "cell_region_labels.csv",
    "cell_region_labels.tsv",
    "expert_region_labels.csv",
    "expert_region_labels.tsv",
    "regions.csv",
    "regions.tsv",
)
MARKER_EVIDENCE_FEATURES = (
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
    "GFAP",
    "AQP4",
    "MBP",
)
NON_BIOLOGICAL_FEATURES = NON_EXPRESSION_FEATURE_NAMES


@dataclass
class LabelApplicationReport:
    status: str
    method: str
    source_path: Optional[str] = None
    matched_cells: int = 0
    total_records: int = 0
    label_counts: Dict[str, int] = field(default_factory=dict)
    confidence_summary: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RegionApplicationReport:
    status: str
    method: str
    source_path: Optional[str] = None
    matched_cells: int = 0
    total_records: int = 0
    region_counts: Dict[str, int] = field(default_factory=dict)
    confidence_summary: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class XeniumExpertReadiness:
    dataset_path: str
    has_cell_table: bool
    has_feature_matrix: bool
    has_morphology: bool
    has_boundaries: bool
    has_10x_analysis_clusters: bool
    cluster_methods: List[str]
    external_label_tables: List[str]
    external_region_tables: List[str]
    ready_for_expert_label_mvp: bool
    ready_for_region_summary_mvp: bool
    needs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class XeniumLabelIntakeReport:
    dataset_path: str
    status: str
    loaded_records: int
    loaded_features: int
    label_status: str
    region_status: str
    label_table: Optional[str]
    region_table: Optional[str]
    label_coverage: float
    region_coverage: float
    biological_label_count: int
    user_region_count: int
    label_counts: Dict[str, int] = field(default_factory=dict)
    region_counts: Dict[str, int] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    required_next_inputs: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    ready_for_validated_pilot: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def discover_label_tables(dataset_path: str, extra_paths: Optional[Iterable[str]] = None) -> List[str]:
    paths: List[Path] = []
    root = _resolve_xenium_path(Path(dataset_path))
    for name in LABEL_TABLE_NAMES:
        paths.append(root / name)
        paths.append(root / "labels" / name)
        paths.append(root / "annotations" / name)
    for pattern in ("*label*.csv", "*label*.tsv", "*annotation*.csv", "*annotation*.tsv"):
        paths.extend(root.glob(pattern))
        if (root / "labels").exists():
            paths.extend((root / "labels").glob(pattern))
        if (root / "annotations").exists():
            paths.extend((root / "annotations").glob(pattern))
    if extra_paths:
        paths.extend(Path(path) for path in extra_paths)
    unique = []
    seen = set()
    for path in paths:
        if path.exists() and path.is_file():
            resolved = str(path)
            if resolved not in seen:
                unique.append(resolved)
                seen.add(resolved)
    return unique


def discover_region_label_tables(dataset_path: str, extra_paths: Optional[Iterable[str]] = None) -> List[str]:
    paths: List[Path] = []
    root = _resolve_xenium_path(Path(dataset_path))
    for name in REGION_TABLE_NAMES:
        paths.append(root / name)
        paths.append(root / "regions" / name)
        paths.append(root / "annotations" / name)
    for pattern in ("*region*.csv", "*region*.tsv", "*roi*.csv", "*roi*.tsv"):
        paths.extend(root.glob(pattern))
        if (root / "regions").exists():
            paths.extend((root / "regions").glob(pattern))
        if (root / "annotations").exists():
            paths.extend((root / "annotations").glob(pattern))
    if extra_paths:
        paths.extend(Path(path) for path in extra_paths)
    unique = []
    seen = set()
    for path in paths:
        if path.exists() and path.is_file():
            resolved = str(path)
            if resolved not in seen:
                unique.append(resolved)
                seen.add(resolved)
    return unique


def apply_external_label_table(
    dataset: SpatialDataset,
    label_path: str,
    cell_id_key: Optional[str] = None,
    label_key: Optional[str] = None,
    confidence_key: Optional[str] = None,
    method: str = "expert_label_table",
) -> LabelApplicationReport:
    rows = _read_label_table(label_path)
    if not rows:
        report = LabelApplicationReport(status="blocked", method=method, source_path=label_path, total_records=len(dataset.records))
        report.warnings.append("Label table is empty.")
        _store_label_report(dataset, report)
        return report
    keys = rows[0].keys()
    resolved_cell_key = cell_id_key or _choose_key(keys, CELL_ID_KEYS)
    resolved_label_key = label_key or _choose_key(keys, LABEL_KEYS)
    resolved_confidence_key = confidence_key or _choose_key(keys, CONFIDENCE_KEYS)
    if not resolved_cell_key or not resolved_label_key:
        report = LabelApplicationReport(status="blocked", method=method, source_path=label_path, total_records=len(dataset.records))
        report.warnings.append("Label table requires a cell-id column and a label column.")
        _store_label_report(dataset, report)
        return report

    label_by_cell: Dict[str, str] = {}
    confidence_by_cell: Dict[str, float] = {}
    for row in rows:
        cell_id = _normalize_cell_id(row.get(resolved_cell_key, ""))
        label = str(row.get(resolved_label_key, "")).strip()
        if not cell_id or not label:
            continue
        label_by_cell[cell_id] = label
        if resolved_confidence_key:
            try:
                confidence_by_cell[cell_id] = float(row.get(resolved_confidence_key, ""))
            except (TypeError, ValueError):
                pass

    matched = 0
    confidences: List[float] = []
    for record in dataset.records:
        cell_id = _normalize_cell_id(record.cell_id or "")
        label = label_by_cell.get(cell_id)
        if not label:
            continue
        record.cell_type = label
        matched += 1
        if cell_id in confidence_by_cell:
            confidences.append(confidence_by_cell[cell_id])

    status = "expert_labels_applied" if matched else "blocked"
    report = LabelApplicationReport(
        status=status,
        method=method,
        source_path=label_path,
        matched_cells=matched,
        total_records=len(dataset.records),
        label_counts=dict(Counter(record.cell_type for record in dataset.records)),
        confidence_summary=_confidence_summary(confidences),
    )
    if matched < len(dataset.records):
        report.warnings.append("Matched labels for %d/%d loaded cells." % (matched, len(dataset.records)))
    if not matched:
        report.warnings.append("No loaded cell IDs matched the label table.")
    _store_label_report(dataset, report)
    if matched:
        dataset.notes.append("Applied external cell labels from %s to %d/%d loaded cells." % (label_path, matched, len(dataset.records)))
    return report


def apply_external_region_table(
    dataset: SpatialDataset,
    region_path: str,
    cell_id_key: Optional[str] = None,
    region_key: Optional[str] = None,
    confidence_key: Optional[str] = None,
    method: str = "user_region_table",
) -> RegionApplicationReport:
    rows = _read_label_table(region_path)
    if not rows:
        report = RegionApplicationReport(status="blocked", method=method, source_path=region_path, total_records=len(dataset.records))
        report.warnings.append("Region table is empty.")
        _store_region_report(dataset, report)
        return report
    keys = rows[0].keys()
    resolved_cell_key = cell_id_key or _choose_key(keys, CELL_ID_KEYS)
    resolved_region_key = region_key or _choose_key(keys, REGION_KEYS)
    resolved_confidence_key = confidence_key or _choose_key(keys, REGION_CONFIDENCE_KEYS)
    if not resolved_cell_key or not resolved_region_key:
        report = RegionApplicationReport(status="blocked", method=method, source_path=region_path, total_records=len(dataset.records))
        report.warnings.append("Region table requires a cell-id column and a region column.")
        _store_region_report(dataset, report)
        return report

    region_by_cell: Dict[str, str] = {}
    confidence_by_cell: Dict[str, float] = {}
    for row in rows:
        cell_id = _normalize_cell_id(row.get(resolved_cell_key, ""))
        region = str(row.get(resolved_region_key, "")).strip()
        if not cell_id or not region:
            continue
        region_by_cell[cell_id] = region
        if resolved_confidence_key:
            try:
                confidence_by_cell[cell_id] = float(row.get(resolved_confidence_key, ""))
            except (TypeError, ValueError):
                pass

    matched = 0
    confidences: List[float] = []
    for record in dataset.records:
        cell_id = _normalize_cell_id(record.cell_id or "")
        region = region_by_cell.get(cell_id)
        if not region:
            continue
        record.region = region
        matched += 1
        if cell_id in confidence_by_cell:
            confidences.append(confidence_by_cell[cell_id])

    status = "user_regions_applied" if matched else "blocked"
    report = RegionApplicationReport(
        status=status,
        method=method,
        source_path=region_path,
        matched_cells=matched,
        total_records=len(dataset.records),
        region_counts=dict(Counter(record.region or "unassigned" for record in dataset.records)),
        confidence_summary=_confidence_summary(confidences),
    )
    if matched < len(dataset.records):
        report.warnings.append("Matched regions for %d/%d loaded cells." % (matched, len(dataset.records)))
    if not matched:
        report.warnings.append("No loaded cell IDs matched the region table.")
    _store_region_report(dataset, report)
    if matched:
        dataset.metadata["region_label_source"] = "user_provided"
        dataset.notes.append("Applied user-provided region labels from %s to %d/%d loaded cells." % (region_path, matched, len(dataset.records)))
    return report


def apply_best_available_regions(
    dataset: SpatialDataset,
    dataset_path: str,
    extra_region_paths: Optional[Iterable[str]] = None,
) -> RegionApplicationReport:
    region_tables = discover_region_label_tables(dataset_path, extra_region_paths)
    for region_table in region_tables:
        report = apply_external_region_table(dataset, region_table)
        if report.matched_cells:
            return report
    report = RegionApplicationReport(
        status="missing_user_regions",
        method="none",
        total_records=len(dataset.records),
        region_counts=dict(Counter(record.region or "unassigned" for record in dataset.records)),
        warnings=["No user-provided region label table was found."],
    )
    _store_region_report(dataset, report)
    return report


def apply_breast_marker_rule_labels(dataset: SpatialDataset) -> LabelApplicationReport:
    changed = 0
    for record in dataset.records:
        genes = record.genes
        old_label = record.cell_type
        label = old_label
        if label == "T/NK cell":
            label = "CD8+_T_Cells" if genes.get("CD8A", 0.0) >= genes.get("CD4", 0.0) else "CD4+_T_Cells"
        elif label == "B cell":
            label = "B_Cells"
        elif label == "Myeloid cell":
            label = "Macrophages_2" if genes.get("CD68", 0.0) + genes.get("C1QA", 0.0) > genes.get("LYZ", 0.0) else "Macrophages_1"
        elif label == "Fibroblast/Stromal cell":
            label = "Myoepi_ACTA2+" if genes.get("ACTA2", 0.0) > 0 else "Stromal"
        elif label == "Epithelial/Tumor-like cell":
            label = "Prolif_Invasive_Tumor" if genes.get("MKI67", 0.0) > 0 else "Invasive_Tumor"
            if genes.get("KRT15", 0.0) > 0:
                label = "Myoepi_KRT15+"
        elif label == "Endothelial cell":
            label = "Endothelial"
        elif label == "Unannotated cell":
            label = "Unlabeled"
        record.cell_type = label
        if label != old_label:
            changed += 1
    report = LabelApplicationReport(
        status="weak_marker_rule_labels",
        method="marker_rule_v0_breast_reference_names",
        matched_cells=changed,
        total_records=len(dataset.records),
        label_counts=dict(Counter(record.cell_type for record in dataset.records)),
        warnings=[
            "Marker-rule labels are not expert-confirmed.",
            "Use these labels for MVP visualization only; replace with expert labels or validated reference transfer before biological interpretation.",
        ],
    )
    _store_label_report(dataset, report)
    dataset.notes.append("Cell labels are conservative marker-rule labels for MVP visualization; validate before biological interpretation.")
    return report


def apply_best_available_labels(
    dataset: SpatialDataset,
    dataset_path: str,
    extra_label_paths: Optional[Iterable[str]] = None,
    fallback: Optional[str] = None,
) -> LabelApplicationReport:
    label_tables = discover_label_tables(dataset_path, extra_label_paths)
    for label_table in label_tables:
        report = apply_external_label_table(dataset, label_table)
        if report.matched_cells:
            return report
    if fallback == "breast_marker_rule":
        return apply_breast_marker_rule_labels(dataset)
    report = LabelApplicationReport(
        status="missing_expert_labels",
        method="none",
        total_records=len(dataset.records),
        label_counts=dict(Counter(record.cell_type for record in dataset.records)),
        warnings=["No external expert or reference-transferred label table was found."],
    )
    _store_label_report(dataset, report)
    return report


def validate_xenium_label_intake(
    dataset_path: str,
    max_records: int = 5000,
    min_label_coverage: float = 0.7,
    min_region_coverage: float = 0.7,
    min_biological_labels: int = 2,
    min_user_regions: int = 2,
    allow_single_region: bool = False,
    extra_label_paths: Optional[Iterable[str]] = None,
    extra_region_paths: Optional[Iterable[str]] = None,
) -> XeniumLabelIntakeReport:
    from .loaders import load_xenium

    dataset = load_xenium(dataset_path, max_records=max_records)
    label_report = apply_best_available_labels(dataset, dataset_path, extra_label_paths=extra_label_paths, fallback=None)
    region_report = apply_best_available_regions(dataset, dataset_path, extra_region_paths=extra_region_paths)
    readiness = summarize_xenium_expert_readiness(dataset_path)
    return build_xenium_label_intake_report(
        dataset=dataset,
        dataset_path=dataset_path,
        label_report=label_report,
        region_report=region_report,
        asset_readiness=readiness,
        min_label_coverage=min_label_coverage,
        min_region_coverage=min_region_coverage,
        min_biological_labels=min_biological_labels,
        min_user_regions=min_user_regions,
        allow_single_region=allow_single_region,
    )


def build_xenium_label_intake_report(
    dataset: SpatialDataset,
    dataset_path: str,
    label_report: LabelApplicationReport,
    region_report: RegionApplicationReport,
    asset_readiness: XeniumExpertReadiness,
    min_label_coverage: float = 0.7,
    min_region_coverage: float = 0.7,
    min_biological_labels: int = 2,
    min_user_regions: int = 2,
    allow_single_region: bool = False,
) -> XeniumLabelIntakeReport:
    blockers: List[str] = []
    required: List[str] = []
    warnings: List[str] = []
    for present, name in [
        (asset_readiness.has_cell_table, "Xenium cell table"),
        (asset_readiness.has_feature_matrix, "Xenium feature matrix"),
        (asset_readiness.has_morphology, "morphology image metadata"),
        (asset_readiness.has_boundaries, "cell/nucleus boundaries"),
    ]:
        if not present:
            blockers.append("Missing %s." % name)
            required.append("Provide %s." % name)

    total_labels = max(int(label_report.total_records or len(dataset.records)), 1)
    total_regions = max(int(region_report.total_records or len(dataset.records)), 1)
    label_coverage = float(label_report.matched_cells or 0) / float(total_labels)
    region_coverage = float(region_report.matched_cells or 0) / float(total_regions)

    if label_report.status != "expert_labels_applied":
        blockers.append("Expert cell labels were not applied.")
        required.append("Place `expert_cell_labels.csv` in the Xenium folder with `cell_id,expert_label,confidence,notes`.")
    elif label_coverage < min_label_coverage:
        blockers.append("Expert label coverage %.3f is below required %.3f." % (label_coverage, min_label_coverage))
        required.append("Increase expert label coverage or lower the explicit validation threshold.")
    elif not label_report.confidence_summary:
        warnings.append("Expert label confidence was not provided; pilot can run, but review confidence is recommended.")

    biological_labels = {
        record.cell_type
        for record in dataset.records
        if record.cell_type and record.cell_type.lower() not in {"unannotated", "unannotated cell", "unlabeled", "unknown"}
    }
    biological_label_count = len(biological_labels) if label_report.status == "expert_labels_applied" else 0
    if biological_label_count < min_biological_labels:
        blockers.append("Only %d biological label classes were validated; at least %d are required." % (biological_label_count, min_biological_labels))
        required.append("Provide at least %d reviewed biological cell classes." % min_biological_labels)

    if region_report.status != "user_regions_applied":
        blockers.append("User-provided region labels were not applied.")
        required.append("Place `cell_regions.csv` in the Xenium folder with `cell_id,region,region_confidence,notes`.")
    elif region_coverage < min_region_coverage:
        blockers.append("Region label coverage %.3f is below required %.3f." % (region_coverage, min_region_coverage))
        required.append("Increase region label coverage or lower the explicit validation threshold.")
    elif not region_report.confidence_summary:
        warnings.append("Region confidence was not provided; pilot can run, but ROI confidence is recommended.")

    user_regions = {record.region for record in dataset.records if record.region}
    user_region_count = len(user_regions) if region_report.status == "user_regions_applied" else 0
    if not allow_single_region and user_region_count < min_user_regions:
        blockers.append("Only %d user region classes were validated; at least %d are required." % (user_region_count, min_user_regions))
        required.append("Provide at least %d reviewed tissue or ROI regions." % min_user_regions)

    status = "validated_ready" if not blockers else "blocked_label_intake"
    return XeniumLabelIntakeReport(
        dataset_path=dataset_path,
        status=status,
        loaded_records=len(dataset.records),
        loaded_features=len(dataset.genes),
        label_status=label_report.status,
        region_status=region_report.status,
        label_table=label_report.source_path,
        region_table=region_report.source_path,
        label_coverage=round(label_coverage, 4),
        region_coverage=round(region_coverage, 4),
        biological_label_count=biological_label_count,
        user_region_count=user_region_count,
        label_counts=dict(label_report.label_counts),
        region_counts=dict(region_report.region_counts),
        blockers=_dedupe(blockers),
        required_next_inputs=_dedupe(required),
        warnings=_dedupe(warnings + label_report.warnings + region_report.warnings),
        ready_for_validated_pilot=status == "validated_ready",
    )


def summarize_xenium_expert_readiness(dataset_path: str) -> XeniumExpertReadiness:
    root = _resolve_xenium_path(Path(dataset_path))
    has_cell_table = any((root / name).exists() for name in ("cells.csv.gz", "cells.csv", "cells.parquet"))
    has_feature_matrix = any((root / name).exists() for name in ("cell_feature_matrix.h5", "cell_feature_matrix.zarr.zip", "cell_feature_matrix.tar.gz"))
    has_morphology = (
        any((root / name).exists() for name in ("morphology.ome.tif", "morphology_focus.ome.tif", "morphology_mip.ome.tif"))
        or (root / "morphology_focus").exists()
    )
    has_boundaries = any(
        (root / name).exists()
        for name in ("cell_boundaries.csv.gz", "cell_boundaries.parquet", "nucleus_boundaries.csv.gz", "nucleus_boundaries.parquet")
    )
    label_tables = discover_label_tables(dataset_path)
    region_tables = discover_region_label_tables(dataset_path)
    cluster_methods = list_xenium_cluster_methods(dataset_path)
    has_clusters = bool(cluster_methods)
    needs = []
    if not label_tables:
        needs.append("Expert cell label table or validated reference-transfer output keyed by Xenium cell_id.")
    if not has_feature_matrix:
        needs.append("Xenium cell_feature_matrix.h5 or equivalent gene matrix.")
    if not has_morphology:
        needs.append("Morphology image metadata for tissue-context visualization.")
    if not has_boundaries:
        needs.append("Cell/nucleus boundaries for segmentation-aware review.")
    if not has_clusters:
        needs.append("10x analysis clusters or generated clustering for label-review support.")
    if not region_tables:
        needs.append("User-provided region label table keyed by Xenium cell_id for region_summary.")
    return XeniumExpertReadiness(
        dataset_path=dataset_path,
        has_cell_table=has_cell_table,
        has_feature_matrix=has_feature_matrix,
        has_morphology=has_morphology,
        has_boundaries=has_boundaries,
        has_10x_analysis_clusters=has_clusters,
        cluster_methods=cluster_methods,
        external_label_tables=label_tables,
        external_region_tables=region_tables,
        ready_for_expert_label_mvp=has_cell_table and has_feature_matrix and bool(label_tables),
        ready_for_region_summary_mvp=has_cell_table and bool(region_tables),
        needs=needs,
    )


def write_expert_label_template(
    dataset: SpatialDataset,
    output_path: str,
    max_rows: int = 5000,
    dataset_path: Optional[str] = None,
) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    graph_clusters = load_xenium_analysis_clusters(dataset_path) if dataset_path else {}
    fieldnames = [
        "cell_id",
        "x",
        "y",
        "current_label",
        "graph_cluster",
        "top_features",
        "marker_evidence",
        "expert_label",
        "confidence",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in dataset.records[:max_rows]:
            cell_id = record.cell_id or ""
            writer.writerow(
                {
                    "cell_id": cell_id,
                    "x": "%.4f" % record.x,
                    "y": "%.4f" % record.y,
                    "current_label": record.cell_type,
                    "graph_cluster": graph_clusters.get(cell_id, ""),
                    "top_features": _top_feature_summary(record.genes),
                    "marker_evidence": _marker_evidence(record.genes),
                    "expert_label": "",
                    "confidence": "",
                    "notes": "",
                }
            )
    return str(path)


def write_region_label_template(
    dataset: SpatialDataset,
    output_path: str,
    max_rows: int = 5000,
    dataset_path: Optional[str] = None,
) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    graph_clusters = load_xenium_analysis_clusters(dataset_path) if dataset_path else {}
    fieldnames = [
        "cell_id",
        "x",
        "y",
        "current_label",
        "current_region",
        "graph_cluster",
        "top_features",
        "region",
        "region_confidence",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in dataset.records[:max_rows]:
            cell_id = record.cell_id or ""
            writer.writerow(
                {
                    "cell_id": cell_id,
                    "x": "%.4f" % record.x,
                    "y": "%.4f" % record.y,
                    "current_label": record.cell_type,
                    "current_region": record.region or "",
                    "graph_cluster": graph_clusters.get(cell_id, ""),
                    "top_features": _top_feature_summary(record.genes),
                    "region": "",
                    "region_confidence": "",
                    "notes": "",
                }
            )
    return str(path)


def list_xenium_cluster_methods(dataset_path: str) -> List[str]:
    root = _resolve_xenium_path(Path(dataset_path))
    methods = []
    extracted = root / "analysis" / "clustering"
    if extracted.exists():
        for path in extracted.glob("*/clusters.csv"):
            methods.append(path.parent.name)
    archive = root / "analysis.tar.gz"
    if archive.exists():
        try:
            with tarfile.open(archive, "r:gz") as handle:
                for name in handle.getnames():
                    if "/clustering/" not in name or not name.endswith("/clusters.csv"):
                        continue
                    parts = name.split("/")
                    if len(parts) >= 4:
                        methods.append(parts[-2])
        except tarfile.TarError:
            pass
    return sorted(set(methods))


def load_xenium_analysis_clusters(
    dataset_path: Optional[str],
    method: str = "gene_expression_graphclust",
) -> Dict[str, str]:
    if not dataset_path:
        return {}
    root = _resolve_xenium_path(Path(dataset_path))
    extracted = root / "analysis" / "clustering" / method / "clusters.csv"
    rows: List[Dict[str, str]] = []
    if extracted.exists():
        rows = _read_csv_file(str(extracted))
    else:
        archive = root / "analysis.tar.gz"
        member = "analysis/clustering/%s/clusters.csv" % method
        if archive.exists():
            rows = _read_csv_member(archive, member)
    if not rows:
        return {}
    cell_key = _choose_key(rows[0].keys(), ("barcode", "cell_id", "cell", "id"))
    cluster_key = _choose_key(rows[0].keys(), ("cluster", "graph_cluster", "kmeans_cluster"))
    if not cell_key or not cluster_key:
        return {}
    clusters = {}
    for row in rows:
        cell_id = _normalize_cell_id(row.get(cell_key, ""))
        cluster = str(row.get(cluster_key, "")).strip()
        if cell_id and cluster:
            clusters[cell_id] = cluster
    return clusters


def _store_label_report(dataset: SpatialDataset, report: LabelApplicationReport) -> None:
    dataset.metadata["label_readiness"] = report.to_dict()
    dataset.metadata["annotation_strategy"] = report.method


def _store_region_report(dataset: SpatialDataset, report: RegionApplicationReport) -> None:
    dataset.metadata["region_label_readiness"] = report.to_dict()


def _read_label_table(path: str) -> List[Dict[str, str]]:
    delimiter = "\t" if path.endswith(".tsv") else ","
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def _read_csv_file(path: str) -> List[Dict[str, str]]:
    with open(path, "r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_csv_member(archive: Path, member: str) -> List[Dict[str, str]]:
    try:
        with tarfile.open(archive, "r:gz") as handle:
            extracted = handle.extractfile(member)
            if extracted is None:
                return []
            with io.TextIOWrapper(extracted, encoding="utf-8", newline="") as text:
                return list(csv.DictReader(text))
    except (tarfile.TarError, KeyError):
        return []


def _choose_key(keys: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    by_lower = {str(key).lower(): str(key) for key in keys}
    for candidate in candidates:
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return None


def _normalize_cell_id(value: str) -> str:
    return str(value).strip().strip('"').strip("'")


def _resolve_xenium_path(path: Path) -> Path:
    if str(path).lower().endswith(".xenium"):
        return path.parent
    return path


def _confidence_summary(values: List[float]) -> Dict[str, float]:
    if not values:
        return {}
    return {
        "min": round(min(values), 4),
        "mean": round(sum(values) / len(values), 4),
        "max": round(max(values), 4),
    }


def _has_10x_analysis_clusters(root: Path) -> bool:
    return bool(list_xenium_cluster_methods(str(root)))


def _top_feature_summary(features: Dict[str, float], limit: int = 8) -> str:
    pairs = []
    for name, value in features.items():
        if name in NON_BIOLOGICAL_FEATURES:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            pairs.append((numeric, name))
    pairs.sort(reverse=True)
    return ";".join("%s=%.3g" % (name, value) for value, name in pairs[:limit])


def _marker_evidence(features: Dict[str, float]) -> str:
    values = []
    for marker in MARKER_EVIDENCE_FEATURES:
        value = features.get(marker)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            values.append("%s=%.3g" % (marker, numeric))
    return ";".join(values)


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
