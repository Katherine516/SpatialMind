from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from .artifacts import ArrayRef, ImageRef, SegmentationRef, ShapesRef, TableArtifact
from .errors import ContractViolationError


Modality = Literal["transcriptomics", "proteomics", "image", "atac"]


@dataclass
class CoreSpatialObject:
    sample_id: str
    modality: Modality
    species: Literal["human", "mouse"] = "human"
    spatial_coords: Optional[ArrayRef] = None
    spatial_shapes: Optional[ShapesRef] = None
    feature_table: Optional[TableArtifact] = None
    image_table: Optional[ImageRef] = None
    measurement_layer: Optional[ArrayRef] = None
    assay_schema: Dict[str, object] = field(default_factory=dict)
    qc_passed: bool = False

    def validate_core(self) -> None:
        if not self.sample_id:
            raise ContractViolationError("CoreSpatialObject.sample_id is required.")
        if self.spatial_coords is None and self.spatial_shapes is None and self.image_table is None:
            raise ContractViolationError("CoreSpatialObject requires coordinates, shapes, or an image reference.")


@dataclass
class SpatialTranscriptomicsContract(CoreSpatialObject):
    counts_layer: Optional[ArrayRef] = None
    norm_layer: Optional[ArrayRef] = None
    gene_id_type: Literal["hgnc", "ensembl", "unknown"] = "unknown"

    def validate(self) -> None:
        self.validate_core()
        if self.spatial_coords is None:
            raise ContractViolationError("Transcriptomics data requires point spatial coordinates.")
        if self.counts_layer is None and self.measurement_layer is None:
            raise ContractViolationError("Transcriptomics data requires raw counts or a measurement layer.")


@dataclass
class SpatialProteomicsContract(CoreSpatialObject):
    marker_panel: List[str] = field(default_factory=list)
    intensity_normalization: str = "unknown"

    def validate(self) -> None:
        self.validate_core()
        if not self.marker_panel:
            raise ContractViolationError("Proteomics data requires a marker panel.")


@dataclass
class SpatialImageContract(CoreSpatialObject):
    channels: List[str] = field(default_factory=list)
    pyramid_levels: int = 1

    def validate(self) -> None:
        self.validate_core()
        if self.image_table is None:
            raise ContractViolationError("Image data requires an image reference.")


@dataclass
class SpatialATACContract(CoreSpatialObject):
    peak_set_ref: Optional[TableArtifact] = None
    fragment_file_ref: Optional[str] = None

    def validate(self) -> None:
        self.validate_core()
        if self.peak_set_ref is None:
            raise ContractViolationError("Spatial ATAC data requires a peak set reference.")


@dataclass
class CellByFeatureContract(CoreSpatialObject):
    assay_subtype: Literal["scrna", "scatac_gene_activity", "xenium_spatial_rna"] = "scrna"
    feature_type: Literal["gene_counts", "gene_activity", "targeted_panel"] = "gene_counts"
    n_features: int = 0
    is_targeted_panel: bool = False
    panel_name: Optional[str] = None
    resolution: Literal["single_cell", "subcellular"] = "single_cell"
    segmentation: Optional[SegmentationRef] = None

    def validate(self) -> None:
        if not self.sample_id:
            raise ContractViolationError("CellByFeatureContract.sample_id is required.")
        if self.n_features <= 0:
            raise ContractViolationError("CellByFeatureContract requires at least one feature.")
        if self.assay_subtype == "xenium_spatial_rna":
            if self.spatial_coords is None:
                raise ContractViolationError("Xenium contract requires spatial coordinates.")
            if self.resolution != "subcellular":
                raise ContractViolationError("Xenium contract must use resolution='subcellular'.")
            if not self.is_targeted_panel:
                raise ContractViolationError("Xenium contract must mark is_targeted_panel=True.")
        if self.assay_subtype == "scatac_gene_activity" and self.feature_type != "gene_activity":
            raise ContractViolationError("scATAC gene-activity contract must use feature_type='gene_activity'.")
