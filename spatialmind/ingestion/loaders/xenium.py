from pathlib import Path
from typing import List, Optional

from spatialmind.ingestion.pipeline import DataIngestionLayer
from spatialmind.schemas import SpatialDataset


def xenium_analysis_inputs(path: str, extra_paths: Optional[List[str]] = None) -> List[str]:
    """Read-set paths for pre-ingestion provenance, including alternate review tables."""
    from spatialmind.ingestion.pipeline import _resolve_xenium_input_path
    from spatialmind.ingestion.labels import discover_label_tables, discover_region_label_tables

    root = Path(_resolve_xenium_input_path(path))
    if Path(path).is_dir() and Path(path).resolve() == root:
        root = Path(path)
    candidates = [path, str(root)]
    candidates.extend(discover_label_tables(str(root), extra_paths))
    candidates.extend(discover_region_label_tables(str(root), extra_paths))
    # These supported input variants otherwise receive only directory size hashes.
    for name in ("cells.csv", "cells.parquet.gz", "analysis.zip"):
        if (root / name).is_file():
            candidates.append(str(root / name))
    candidates.extend(str(item) for item in sorted((root / "analysis").rglob("clusters.csv")))
    return list(dict.fromkeys(candidates))


def load_xenium(
    path: str,
    sample_id: Optional[str] = None,
    max_records: int = 5000,
    max_features_per_record: int = 0,
) -> SpatialDataset:
    # max_features_per_record=0 keeps the full targeted panel per cell. Per-cell
    # top-N truncation drops mid/low-expression genes to implicit zeros, which
    # distorts PCA/clustering and marker ranking; the sampled matrix stays bounded
    # by max_records x panel size, so full-panel loading is the analysis default.
    dataset = DataIngestionLayer().load_xenium_directory(
        path,
        sample_id=sample_id,
        max_records=max_records,
        max_features_per_record=max_features_per_record,
    )
    dataset.modality = "xenium_spatial_rna"
    dataset.coordinate_system = "microns"
    dataset.metadata["assay_subtype"] = "xenium_spatial_rna"
    dataset.metadata["feature_type"] = "targeted_panel"
    dataset.metadata["resolution"] = "subcellular"
    dataset.metadata["is_targeted_panel"] = True
    dataset.metadata.setdefault("panel_name", _panel_name(dataset))
    # experiment.xenium reports panel_organism; carried so cross-species label
    # transfer can be refused rather than silently performed.
    dataset.metadata.setdefault("organism", str(dataset.metadata.get("panel_organism") or ""))
    dataset.notes.append("Xenium uses a targeted panel; a missing gene means not measured, not unexpressed.")
    dataset.processing_steps.append("Loaded as MVP Xenium spatial RNA dataset with micron coordinates.")
    return dataset


def _panel_name(dataset: SpatialDataset) -> str:
    panel = dataset.metadata.get("gene_panel") or {}
    if isinstance(panel, dict):
        name = panel.get("name") or panel.get("panel_name")
        if name:
            return str(name)
    return "Xenium targeted panel"
