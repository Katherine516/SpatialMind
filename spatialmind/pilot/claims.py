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
            # Declared explicitly, because the default for `visual_pattern` is
            # `["figure"]` -- a token only `feature_overlay` emits, and which has
            # nothing to do with a region summary. `evidence_refs` was never read
            # by `ground_claim`, so this claim silently required a figure that the
            # validated plan does not produce and was dropped in every validated
            # run ever made, with regions applied and region_summary.json on disk.
            required_evidence=["region_summary"],
            resolution="subcellular",
            confidence="medium",
        ),
    ]
    from spatialmind.methods.reliability.scoring import _statistical_component, _evidence_strength
    for result in results:
        if result.tool_name != "cell_neighborhood_enrichment":
            continue
        for pair in (result.metrics.get("top_pairs") or [])[:10]:
            names = str(pair.get("pair") or "").split("|")
            z = pair.get("zscore")
            if len(names) != 2 or z is None or z == 0:
                continue
            names = [name.strip() for name in names]
            direction = "enrichment" if z > 0 else "depletion"
            target = {"tool": result.tool_name, "pair": names, "direction": direction}
            target.update({key: result.metrics[key] for key in ("graph_family", "n_neighs", "radius") if key in result.metrics})
            claims.append(BiologicalClaim(
                claim_text="%s and %s show neighborhood %s under the tested spatial graph (z=%.3f); this is not a causal claim."
                           % (names[0], names[1], direction, z),
                claim_type="spatial_colocalization", spatial_target=target,
                evidence_refs=["%s:%s" % (result.tool_name, pair["pair"])],
                resolution="subcellular", confidence="medium",
            ))
    grounded = ClaimGroundingChecker().ground(claims, results)
    ledger = []
    for claim in grounded:
        item = asdict(claim)
        item["status"] = "supported" if claim.allowed_wording else "dropped"
        if item.get("spatial_target") and _statistical_component(item, results).score < _evidence_strength(0.05):
            item["status"] = "dropped"
            item["allowed_wording"] = ""
            item["missing_inputs"] = ["Pair-specific adjusted statistical support at alpha=0.05."]
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
