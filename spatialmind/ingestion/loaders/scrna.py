from pathlib import Path
from typing import Optional, Sequence

from spatialmind.ingestion.pipeline import DataIngestionLayer, IngestionValidationError
from spatialmind.schemas import SpatialDataset


def load_scrna(path: str, sample_id: Optional[str] = None, max_records: int = 5000) -> SpatialDataset:
    dataset = _load_matrix_like(path, sample_id=sample_id, max_records=max_records)
    dataset.modality = "scrna"
    dataset.coordinate_system = "embedding_or_index"
    dataset.metadata["assay_subtype"] = "scrna"
    dataset.metadata["feature_type"] = "gene_counts"
    dataset.metadata["resolution"] = "single_cell"
    dataset.metadata["is_targeted_panel"] = False
    dataset.processing_steps.append("Loaded as MVP scRNA cell-by-feature dataset.")
    return dataset


def load_scrna_reference_set(
    paths: Sequence[str],
    sample_id: Optional[str] = None,
    max_records_per_file: int = 5000,
) -> SpatialDataset:
    """Concatenate several scRNA files into one labelled reference.

    Atlases are often distributed one cell class per file (CELLxGENE splits the
    Siletti adult human brain atlas by supercluster), and a single-class file
    cannot support label transfer. Loading several and combining them produces a
    usable multi-class reference.

    Refuses to mix organisms, since cross-species gene symbols collide once
    uppercased.
    """
    if not paths:
        raise IngestionValidationError("load_scrna_reference_set requires at least one reference path.")
    datasets = [load_scrna(path, max_records=max_records_per_file) for path in paths]
    organisms = {str(item.metadata.get("organism") or "").strip().lower() for item in datasets}
    organisms.discard("")
    if len(organisms) > 1:
        raise IngestionValidationError(
            "Reference files span multiple organisms (%s); combine same-species references only."
            % ", ".join(sorted(organisms))
        )
    combined = datasets[0]
    if len(datasets) > 1:
        for extra in datasets[1:]:
            combined.records.extend(extra.records)
        combined.sources = [source for item in datasets for source in item.sources]
    combined.sample_id = sample_id or combined.sample_id
    combined.metadata["reference_file_count"] = len(datasets)
    combined.metadata["reference_paths"] = [str(path) for path in paths]
    combined.metadata["reference_cell_classes"] = combined.cell_types
    combined.processing_steps.append(
        "Combined %d scRNA reference files into one labelled reference." % len(datasets)
    )
    return combined


def _load_matrix_like(path: str, sample_id: Optional[str], max_records: int = 5000) -> SpatialDataset:
    layer = DataIngestionLayer()
    suffix = Path(path).suffix.lower()
    if suffix == ".h5ad":
        # Dissociated scRNA has no spatial coordinates; that must not block loading.
        return layer.load_h5ad(path, sample_id=sample_id, max_records=max_records, require_spatial=False)
    return layer.load(path, sample_id=sample_id)
