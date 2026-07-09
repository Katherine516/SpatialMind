"""Typed boundary contracts for the SpatialMind layer architecture.

The current runtime still supports the older dataclasses in ``spatialmind.schemas``.
This package is the forward-facing contract surface described by the layer plan:
objects here are serializable, dependency-light, and safe to pass between layers.
"""

from .artifacts import ArrayRef, ImageRef, SegmentationRef, ShapesRef, SpatialDataArtifact, TableArtifact
from .citations import MethodCitation
from .claims import BiologicalClaim, ClaimGroundingRule, ground_claim
from .errors import ContractViolationError, PlanValidationError, SpatialMindError, SpatialToolError
from .memory import MemoryItem
from .metrics import (
    AnnotationMetrics,
    ClusteringMetrics,
    DifferentialMetrics,
    Metric,
    MetricProvenance,
    QCMetrics,
    QualityMetrics,
    SpatialMetrics,
    metric,
)
from .plan import ExecutionPlan, NoAnalysisResponse, ToolCallSpec
from .reports import DatasetReadinessReport, IngestionReport, WorkflowReadiness
from .reliability import ClaimReliability, ReliabilityComponent
from .response import AgentResponse, VizArtifact
from .spatial_data import (
    CoreSpatialObject,
    CellByFeatureContract,
    SpatialATACContract,
    SpatialImageContract,
    SpatialProteomicsContract,
    SpatialTranscriptomicsContract,
)
from .tool_io import ResourceProfile, ToolErrorInfo, ToolResult

__all__ = [
    "AgentResponse",
    "ArrayRef",
    "BiologicalClaim",
    "CellByFeatureContract",
    "ClaimGroundingRule",
    "ClaimReliability",
    "ContractViolationError",
    "CoreSpatialObject",
    "DatasetReadinessReport",
    "DifferentialMetrics",
    "ExecutionPlan",
    "ImageRef",
    "IngestionReport",
    "MemoryItem",
    "AnnotationMetrics",
    "ClusteringMetrics",
    "MethodCitation",
    "Metric",
    "MetricProvenance",
    "NoAnalysisResponse",
    "PlanValidationError",
    "QCMetrics",
    "QualityMetrics",
    "ResourceProfile",
    "ReliabilityComponent",
    "SegmentationRef",
    "ShapesRef",
    "SpatialATACContract",
    "SpatialDataArtifact",
    "SpatialImageContract",
    "SpatialMindError",
    "SpatialProteomicsContract",
    "SpatialMetrics",
    "SpatialToolError",
    "SpatialTranscriptomicsContract",
    "TableArtifact",
    "ToolCallSpec",
    "ToolErrorInfo",
    "ToolResult",
    "VizArtifact",
    "WorkflowReadiness",
    "ground_claim",
    "metric",
]
