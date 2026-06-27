from typing import Optional

from spatialmind.ingestion.pipeline import DataIngestionLayer
from spatialmind.schemas import SpatialDataset


def load_xenium(path: str, sample_id: Optional[str] = None, max_records: int = 5000) -> SpatialDataset:
    dataset = DataIngestionLayer().load_xenium_directory(path, sample_id=sample_id, max_records=max_records)
    dataset.modality = "xenium_spatial_rna"
    dataset.coordinate_system = "microns"
    dataset.metadata["assay_subtype"] = "xenium_spatial_rna"
    dataset.metadata["feature_type"] = "targeted_panel"
    dataset.metadata["resolution"] = "subcellular"
    dataset.metadata["is_targeted_panel"] = True
    dataset.metadata.setdefault("panel_name", _panel_name(dataset))
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
