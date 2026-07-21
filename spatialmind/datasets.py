import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .ingestion import (
    DataIngestionLayer,
    IngestionConfig,
    apply_best_available_labels,
    apply_best_available_regions,
    infer_data_type,
)


@dataclass
class DatasetInspection:
    path: str
    data_type: str
    usable: bool
    readiness: str
    record_count: int = 0
    feature_count: int = 0
    cell_type_count: int = 0
    modality: str = "unknown"
    sample_id: str = ""
    supported_workflows: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    metadata: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "data_type": self.data_type,
            "usable": self.usable,
            "readiness": self.readiness,
            "record_count": self.record_count,
            "feature_count": self.feature_count,
            "cell_type_count": self.cell_type_count,
            "modality": self.modality,
            "sample_id": self.sample_id,
            "supported_workflows": self.supported_workflows,
            "blockers": self.blockers,
            "notes": self.notes,
            "metadata": self.metadata,
        }


def discover_dataset_candidates(root: str) -> List[str]:
    candidates: List[str] = []
    for current, dirs, files in os.walk(root):
        names = set(files)
        if "experiment.xenium" in names or "cells.csv.gz" in names or "cell_feature_matrix.h5" in names:
            candidates.append(current)
            dirs[:] = []
            continue
        for filename in files:
            lower = filename.lower()
            if lower.endswith((".h5ad", ".zarr", ".csv", ".tsv", ".csv.gz")):
                candidates.append(os.path.join(current, filename))
            elif lower.endswith(".json") and _looks_like_analysis_manifest(os.path.join(current, filename)):
                candidates.append(os.path.join(current, filename))
    return sorted(set(candidates))


def inspect_dataset(path: str, config: Optional[IngestionConfig] = None) -> DatasetInspection:
    data_type = infer_data_type(path)
    config = config or IngestionConfig(min_counts=0, min_genes=0, max_records=1000)
    try:
        layer = DataIngestionLayer()
        is_xenium = data_type in {"xenium_directory", "xenium_experiment_file"}
        if is_xenium:
            dataset = layer.load_xenium_directory(path, max_records=config.max_records)
            label_report = apply_best_available_labels(dataset, path, fallback=None)
            region_report = apply_best_available_regions(dataset, path)
        elif data_type == "h5ad_anndata":
            dataset = layer.load_h5ad(
                path,
                annotation_key=config.annotation_key,
                max_records=config.max_records,
                max_features_per_record=config.max_features_per_record,
            )
        else:
            dataset = layer.load(path)
    except Exception as exc:
        return DatasetInspection(
            path=path,
            data_type=data_type,
            usable=False,
            readiness="blocked",
            blockers=[str(exc)],
            notes=["The path is discoverable but cannot be loaded by the current adapter."],
        )

    supported = ["qc_summary", "spatial_scatter", "spatial_clustering"]
    blockers: List[str] = []
    if dataset.cell_types and dataset.cell_types != ["Unannotated"] and dataset.cell_types != ["Unannotated cell"]:
        supported.extend(["cell_type_distribution", "neighborhood_enrichment"])
    else:
        blockers.append("No biological cell-type labels are available yet.")
    if dataset.genes and not _only_xenium_summary_features(dataset.genes):
        supported.extend(["expression_overlay", "spatial_variable_genes", "differential_expression"])
    else:
        blockers.append("Gene-level expression is unavailable or limited to Xenium summary counts.")
    if data_type in {"xenium_directory", "xenium_experiment_file"}:
        gene_matrix = dataset.metadata.get("gene_matrix", {})
        if dataset.metadata.get("xenium_files", {}).get("cell_feature_matrix_h5") and not gene_matrix.get("available"):
            blockers.append("cell_feature_matrix.h5 is present but its gene matrix was not loaded; inspect ingestion warnings.")
        if label_report.status != "expert_labels_applied":
            blockers.append("No reviewed expert/reference cell labels are available; current labels are exploratory only.")
        if region_report.status != "user_regions_applied":
            blockers.append("No reviewed user ROI/tissue regions are available.")

    readiness = "ready_for_agent" if not blockers else "partially_ready"
    return DatasetInspection(
        path=path,
        data_type=data_type,
        usable=True,
        readiness=readiness,
        record_count=len(dataset.records),
        feature_count=len(dataset.genes),
        cell_type_count=len(dataset.cell_types),
        modality=dataset.modality,
        sample_id=dataset.sample_id,
        supported_workflows=sorted(set(supported)),
        blockers=blockers,
        notes=list(dataset.notes),
        metadata={
            "source_path": dataset.source_path,
            "coordinate_system": dataset.coordinate_system,
            "qc_metrics": dataset.qc_metrics,
            "dataset_metadata": dataset.metadata,
            "label_readiness": label_report.to_dict() if is_xenium else None,
            "region_readiness": region_report.to_dict() if is_xenium else None,
        },
    )


def inspect_data_root(root: str) -> List[DatasetInspection]:
    return [inspect_dataset(path) for path in discover_dataset_candidates(root)]


def write_dataset_report(root: str, out_path: str) -> str:
    inspections = [item.to_dict() for item in inspect_data_root(root)]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump({"root": root, "datasets": inspections}, handle, indent=2)
    return out_path


def _only_xenium_summary_features(genes: List[str]) -> bool:
    summary_features = {"TRANSCRIPT_COUNTS", "TOTAL_COUNTS", "CELL_AREA", "NUCLEUS_AREA"}
    return bool(genes) and set(genes).issubset(summary_features)


def _looks_like_analysis_manifest(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return False
    return isinstance(payload, dict) and isinstance(payload.get("sources"), list) and bool(payload["sources"])
