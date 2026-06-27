from pathlib import Path
from typing import Optional

from spatialmind.ingestion.pipeline import DataIngestionLayer
from spatialmind.schemas import SpatialDataset


def load_scatac(path: str, sample_id: Optional[str] = None, feature_type: str = "gene_activity") -> SpatialDataset:
    layer = DataIngestionLayer()
    suffix = Path(path).suffix.lower()
    dataset = layer.load_h5ad(path, sample_id=sample_id) if suffix == ".h5ad" else layer.load(path, sample_id=sample_id)
    dataset.modality = "scatac"
    dataset.coordinate_system = "embedding_or_index"
    dataset.metadata["assay_subtype"] = "scatac_gene_activity"
    dataset.metadata["feature_type"] = feature_type
    dataset.metadata["resolution"] = "single_cell"
    dataset.metadata["is_targeted_panel"] = False
    dataset.notes.append("scATAC gene activity is accessibility-inferred and must not be described as measured expression.")
    dataset.processing_steps.append("Loaded as MVP scATAC cell-by-feature dataset.")
    return dataset
