from dataclasses import dataclass, field
from typing import Dict, Literal, Optional


MetricStatus = Literal["computed", "not_applicable", "failed", "skipped_due_to_size", "insufficient_data"]
MetricRole = Literal["diagnostic", "statistical_evidence", "qc"]


@dataclass
class MetricProvenance:
    method: str
    parameters: Dict[str, object] = field(default_factory=dict)
    data_subset: str = "all_cells"
    random_seed: int = 42
    library_version: str = "spatialmind-prototype"


@dataclass
class Metric:
    value: Optional[float]
    status: MetricStatus
    role: MetricRole
    provenance: MetricProvenance
    interpretation_caveat: Optional[str] = None


@dataclass
class ClusteringMetrics:
    silhouette: Metric
    modularity: Metric


@dataclass
class AnnotationMetrics:
    mean_confidence: Metric
    marker_overlap: Metric
    fraction_unassigned: Metric


@dataclass
class DifferentialMetrics:
    n_significant: Metric
    pct_expressing: Metric
    auroc: Metric


@dataclass
class SpatialMetrics:
    morans_i: Metric
    cooccurrence_z: Metric
    mean_neighbors: Metric


@dataclass
class QCMetrics:
    record_count: Metric
    feature_count: Metric
    missing_feature_fraction: Metric


@dataclass
class QualityMetrics:
    qc: QCMetrics
    clustering: Optional[ClusteringMetrics] = None
    annotation: Optional[AnnotationMetrics] = None
    differential: Optional[DifferentialMetrics] = None
    spatial: Optional[SpatialMetrics] = None


def metric(
    value: Optional[float],
    status: MetricStatus,
    role: MetricRole,
    method: str,
    parameters: Optional[Dict[str, object]] = None,
    data_subset: str = "all_cells",
    caveat: Optional[str] = None,
) -> Metric:
    return Metric(
        value=value,
        status=status,
        role=role,
        provenance=MetricProvenance(
            method=method,
            parameters=parameters or {},
            data_subset=data_subset,
        ),
        interpretation_caveat=caveat,
    )
