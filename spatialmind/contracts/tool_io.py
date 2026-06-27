from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from .artifacts import SpatialDataArtifact, TableArtifact
from .metrics import QualityMetrics


@dataclass
class ResourceProfile:
    runtime: Literal["fast", "medium", "slow"]
    memory: Literal["low", "medium", "high"]
    gpu_required: bool = False
    internet_required: bool = False


@dataclass
class ToolErrorInfo:
    error_type: str
    message: str
    remediation: Optional[str] = None


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    updated_dataset_ref: Optional[SpatialDataArtifact] = None
    table_ref: Optional[TableArtifact] = None
    scalar_results: Dict[str, float] = field(default_factory=dict)
    metrics: Optional[QualityMetrics] = None
    label_caveat: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    error: Optional[ToolErrorInfo] = None
    runtime_seconds: float = 0.0
