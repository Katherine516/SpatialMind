from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

from ...schemas import SpatialDataset


@dataclass
class FusedDataset:
    dataset: SpatialDataset
    modalities_present: List[str]
    fusion_method: Dict[str, str]
    shared_cells_n: Optional[int]
    fusion_quality_score: Optional[float]
    warnings: List[str] = field(default_factory=list)


class ModalityFuser:
    supported_pairs = [
        ("scrna", "visium"),
        ("visium", "he_image"),
        ("imc", "visium"),
        ("visium", "atac"),
        ("codex", "he_image"),
    ]

    def fuse(self, datasets: List[Tuple[str, SpatialDataset]]) -> FusedDataset:
        if not datasets:
            raise ValueError("At least one dataset is required for fusion.")
        modalities = [modality for modality, _ in datasets]
        primary = datasets[0][1]
        methods: Dict[str, str] = {}
        warnings: List[str] = []
        for modality in modalities:
            methods[modality] = "identity" if modality == modalities[0] else "registered_scaffold"
        for left, right in zip(modalities, modalities[1:]):
            if (left, right) not in self.supported_pairs and (right, left) not in self.supported_pairs:
                warnings.append("No production fusion method registered for %s + %s." % (left, right))
        return FusedDataset(
            dataset=primary,
            modalities_present=modalities,
            fusion_method=methods,
            shared_cells_n=None,
            fusion_quality_score=None,
            warnings=warnings or ["Fusion scaffold created; production alignment not yet run."],
        )
