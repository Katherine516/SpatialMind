from dataclasses import asdict
from typing import Any, Dict, List

from spatialmind.agent.grounding import ClaimGroundingChecker
from spatialmind.contracts import BiologicalClaim
from spatialmind.methods.reliability import build_claim_reliability_table
from spatialmind.schemas import ToolResult


def build_pilot_claim_ledger(payload: Dict[str, Any], results: List[ToolResult]) -> List[Dict[str, Any]]:
    """Create an auditable claim ledger for the validated Xenium pilot."""
    status = payload.get("status", "")
    if status != "validated_ready":
        return [
            {
                "claim_text": "Validated Xenium biological interpretation is blocked until expert cell labels and user regions are supplied.",
                "claim_type": "cell_type_annotation",
                "status": "refused",
                "allowed_wording": "",
                "confidence": "low",
                "evidence_refs": [],
                "missing_inputs": list(payload.get("required_next_inputs") or []),
            },
            {
                "claim_text": "The local Xenium folder contains core assets suitable for expert-label preparation.",
                "claim_type": "visual_pattern",
                "status": "supported_non_biological_readiness",
                "allowed_wording": "Core Xenium assets are present; biological claims remain blocked.",
                "confidence": "medium",
                "evidence_refs": ["asset_readiness", "contract"],
                "missing_inputs": list(payload.get("required_next_inputs") or []),
            },
        ]

    claims = [
        BiologicalClaim(
            claim_text="Expert-reviewed cell labels are available for the loaded Xenium cells.",
            claim_type="cell_type_annotation",
            evidence_refs=["annotation_method"],
            resolution="subcellular",
            confidence="medium",
        ),
        BiologicalClaim(
            claim_text="User-provided tissue regions support per-region cell-type and feature summaries.",
            claim_type="visual_pattern",
            evidence_refs=["region_summary"],
            resolution="subcellular",
            confidence="medium",
        ),
        BiologicalClaim(
            claim_text="Cell-type neighborhood enrichment can support cell-level spatial co-localization claims when adjusted statistics are present.",
            claim_type="spatial_colocalization",
            evidence_refs=["neighborhood_test", "zscore", "cell_labels"],
            resolution="subcellular",
            confidence="medium",
        ),
    ]
    grounded = ClaimGroundingChecker().ground(claims, results)
    ledger = []
    for claim in grounded:
        item = asdict(claim)
        item["status"] = "supported" if claim.allowed_wording else "dropped"
        ledger.append(item)
    return ledger


def claim_ledger_summary(ledger: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in ledger:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def build_pilot_claim_reliability(payload: Dict[str, Any], results: List[ToolResult]) -> List[Dict[str, Any]]:
    return build_claim_reliability_table(payload, results, method="weakest_link")
