from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


@dataclass
class ArrayRef:
    artifact_id: str
    path: str
    shape: List[int]
    dtype: str = "float32"
    md5: str = ""


@dataclass
class ShapesRef:
    artifact_id: str
    path: str
    format: Literal["geojson", "parquet", "zarr", "mask"] = "geojson"
    md5: str = ""


@dataclass
class SegmentationRef:
    artifact_id: str
    path: str
    format: Literal["csv", "parquet", "zarr", "mask"] = "csv"
    coordinate_units: Literal["microns", "pixels"] = "microns"
    md5: str = ""


@dataclass
class ImageRef:
    artifact_id: str
    path: str
    format: Literal["ome-tiff", "tiff", "png", "jpeg", "zarr"] = "ome-tiff"
    channels: List[str] = field(default_factory=list)
    md5: str = ""


@dataclass
class SpatialDataArtifact:
    artifact_id: str
    path: str
    format: Literal["zarr", "h5ad", "json"] = "json"
    md5: str = ""


@dataclass
class TableArtifact:
    artifact_id: str
    path: str
    format: Literal["parquet", "csv", "json"] = "json"
    table_schema: Dict[str, str] = field(default_factory=dict)
    md5: Optional[str] = None
