from pathlib import Path
from typing import Optional

from spatialmind.ingestion.pipeline import DataIngestionLayer
from spatialmind.schemas import SpatialDataset


def load_scrna(path: str, sample_id: Optional[str] = None) -> SpatialDataset:
    dataset = _load_matrix_like(path, sample_id=sample_id)
    dataset.modality = "scrna"
    dataset.coordinate_system = "embedding_or_index"
    dataset.metadata["assay_subtype"] = "scrna"
    dataset.metadata["feature_type"] = "gene_counts"
    dataset.metadata["resolution"] = "single_cell"
    dataset.metadata["is_targeted_panel"] = False
    dataset.processing_steps.append("Loaded as MVP scRNA cell-by-feature dataset.")
    return dataset


def _load_matrix_like(path: str, sample_id: Optional[str]) -> SpatialDataset:
    layer = DataIngestionLayer()
    suffix = Path(path).suffix.lower()
    if suffix == ".h5ad":
        return layer.load_h5ad(path, sample_id=sample_id)
    return layer.load(path, sample_id=sample_id)
