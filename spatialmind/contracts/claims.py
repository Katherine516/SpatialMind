from dataclasses import dataclass, field
from typing import Dict, List, Literal


ClaimType = Literal[
    "visual_pattern",
    "statistical_enrichment",
    "differential_expression",
    "spatial_colocalization",
    "cell_type_annotation",
    "causal_or_mechanistic",
]


REQUIRED_EVIDENCE: Dict[str, List[str]] = {
    "visual_pattern": ["figure"],
    "statistical_enrichment": ["p_adj", "effect_size", "test_name"],
    "differential_expression": ["logfc", "p_adj", "group_labels"],
    "spatial_colocalization": ["neighborhood_test", "zscore", "cell_labels"],
    "cell_type_annotation": ["annotation_method"],
    "causal_or_mechanistic": ["causal_module"],
}


@dataclass
class BiologicalClaim:
    claim_text: str
    claim_type: ClaimType
    evidence_refs: List[str] = field(default_factory=list)
    resolution: Literal["single_cell", "subcellular"] = "single_cell"
    confidence: Literal["low", "medium", "high"] = "low"
    allowed_wording: str = ""
    required_evidence: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.required_evidence:
            self.required_evidence = list(REQUIRED_EVIDENCE.get(self.claim_type, []))
        if not self.allowed_wording:
            self.allowed_wording = self.claim_text


@dataclass
class ClaimGroundingRule:
    claim_type: ClaimType
    missing_evidence_wording: str
    drop_if_missing: bool = False


GROUNDING_RULES: Dict[str, ClaimGroundingRule] = {
    "visual_pattern": ClaimGroundingRule("visual_pattern", "", drop_if_missing=True),
    "statistical_enrichment": ClaimGroundingRule(
        "statistical_enrichment", "The pattern appears present, but statistical enrichment is not established."
    ),
    "differential_expression": ClaimGroundingRule(
        "differential_expression", "Expression differs visually, but no supported differential-expression claim can be made."
    ),
    "spatial_colocalization": ClaimGroundingRule(
        "spatial_colocalization",
        "The cell types appear spatially near each other, but no valid neighborhood test confirms enrichment.",
    ),
    "cell_type_annotation": ClaimGroundingRule(
        "cell_type_annotation", "Cell-type labels should be treated as tentative because annotation evidence is incomplete."
    ),
    "causal_or_mechanistic": ClaimGroundingRule("causal_or_mechanistic", "", drop_if_missing=True),
}


def ground_claim(claim: BiologicalClaim, available_evidence: List[str]) -> BiologicalClaim:
    missing = [item for item in claim.required_evidence if item not in available_evidence]
    if not missing:
        claim.confidence = "high" if claim.confidence == "low" else claim.confidence
        claim.allowed_wording = claim.claim_text
        return claim
    rule = GROUNDING_RULES[claim.claim_type]
    if rule.drop_if_missing:
        claim.allowed_wording = ""
        claim.confidence = "low"
        return claim
    claim.allowed_wording = rule.missing_evidence_wording
    claim.confidence = "low"
    return claim
