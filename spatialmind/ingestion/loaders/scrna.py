from pathlib import Path
from typing import Optional

from spatialmind.ingestion.pipeline import DataIngestionLayer
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


def _load_matrix_like(path: str, sample_id: Optional[str], max_records: int = 5000) -> SpatialDataset:
    layer = DataIngestionLayer()
    suffix = Path(path).suffix.lower()
    if suffix == ".h5ad":
        # Dissociated scRNA has no spatial coordinates; that must not block loading.
        return layer.load_h5ad(path, sample_id=sample_id, max_records=max_records, require_spatial=False)
    return layer.load(path, sample_id=sample_id)
