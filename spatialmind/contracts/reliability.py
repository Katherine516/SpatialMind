from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from spatialmind.contracts.metrics import MetricProvenance


ReliabilityStatus = Literal["computed", "blocked", "not_applicable", "not_fit"]
ReliabilityMethod = Literal["weakest_link", "calibrated"]


@dataclass
class ReliabilityComponent:
    """One interpretable component of a claim-level reliability score."""

    name: str
    score: float
    status: ReliabilityStatus
    evidence: List[str] = field(default_factory=list)
    caveat: str = ""


@dataclass
class ClaimReliability:
    """Reliability score for one claim, decomposed into v12 failure modes."""

    claim_ref: str
    claim_type: str
    S_statistical: float
    A_annotation: float
    P_panel: float
    R_spatial_robustness: float
    reliability: float
    method: ReliabilityMethod
    status: ReliabilityStatus
    components: Dict[str, ReliabilityComponent]
    provenance: MetricProvenance
    interpretation: str
    calibration_model: Optional[Dict[str, object]] = None

