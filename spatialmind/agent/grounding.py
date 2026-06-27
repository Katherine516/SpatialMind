from typing import Iterable, List

from spatialmind.contracts import BiologicalClaim, ground_claim
from spatialmind.schemas import ToolResult


class ClaimGroundingChecker:
    """MVP grounding rules for type- and resolution-aware interpretation."""

    def ground(self, claims: Iterable[BiologicalClaim], results: Iterable[ToolResult]) -> List[BiologicalClaim]:
        evidence = self._available_evidence(results)
        grounded = []
        caveats = self._label_caveats(results)
        for claim in claims:
            checked = ground_claim(claim, evidence)
            if checked.allowed_wording:
                checked.allowed_wording = self._apply_honesty_caveats(checked.allowed_wording, caveats)
            grounded.append(checked)
        return grounded

    def soften_interpretation(self, interpretation: str, results: Iterable[ToolResult]) -> str:
        lowered = interpretation.lower()
        evidence = self._available_evidence(results)
        text = interpretation
        if ("significant" in lowered or "enriched" in lowered) and not {"p_adj", "effect_size"}.issubset(set(evidence)):
            text += " Statistical significance should be treated as provisional because adjusted p-value and effect size evidence are incomplete."
        caveats = self._label_caveats(results)
        if caveats:
            text += " " + " ".join(caveats)
        if "expressed" in text.lower() and "gene_activity" in evidence:
            text = text.replace(" expressed", " accessibility-inferred")
            text += " scATAC-derived values are accessibility-inferred, not measured expression."
        return text

    def _available_evidence(self, results: Iterable[ToolResult]) -> List[str]:
        evidence = []
        for result in results:
            metrics = result.metrics or {}
            serialized = str(metrics).lower()
            if "pval_adj" in serialized or "p_adj" in serialized:
                evidence.append("p_adj")
            if "effect_size" in serialized or "zscore" in serialized or "logfc" in serialized:
                evidence.append("effect_size")
            if "zscore" in serialized or result.tool_name in {"neighborhood_enrichment", "cell_neighborhood_enrichment"}:
                evidence.extend(["neighborhood_test", "zscore", "cell_labels"])
            if result.tool_name in {"differential_expression", "marker_detection"}:
                evidence.extend(["logfc", "group_labels"])
            if result.tool_name in {"annotation", "cell_type_annotation", "reference_label_transfer"}:
                evidence.append("annotation_method")
            if result.tool_name in {"feature_overlay"}:
                evidence.append("figure")
            if metrics.get("feature_type") == "gene_activity":
                evidence.append("gene_activity")
        return sorted(set(evidence))

    def _label_caveats(self, results: Iterable[ToolResult]) -> List[str]:
        caveats = []
        for result in results:
            if result.label_caveat:
                caveats.append(result.label_caveat)
            for caveat in result.caveats:
                if "targeted panel" in caveat or "accessibility-inferred" in caveat or "transferred" in caveat:
                    caveats.append(caveat)
        return _dedupe(caveats)

    def _apply_honesty_caveats(self, text: str, caveats: List[str]) -> str:
        if not caveats:
            return text
        return "%s Caveat: %s" % (text, " ".join(caveats))


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
