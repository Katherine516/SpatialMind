"""Biological replication checks for condition-level comparisons.

Cells within one tissue section are not independent biological replicates. A
healthy-versus-disease difference computed from one section per condition is
pseudoreplication: the apparent sample size is the cell count, but the real
sample size is one donor per group, so nothing about the conditions can be
generalized no matter how many cells were measured.

This module reports what replication actually exists so condition-level claims
can be refused rather than silently produced.
"""

from typing import Any, Dict, List, Mapping, Sequence

# One section per condition supports description of those sections only.
MIN_SECTIONS_PER_CONDITION = 2
MIN_DONORS_PER_CONDITION = 2


def assess_condition_replication(
    sections_by_condition: Mapping[str, Sequence[Mapping[str, Any]]],
    min_sections: int = MIN_SECTIONS_PER_CONDITION,
    min_donors: int = MIN_DONORS_PER_CONDITION,
) -> Dict[str, Any]:
    """Decide whether condition-level inference is supported by the design.

    ``sections_by_condition`` maps a condition label to the sections observed for
    it; each section carries at least ``section_id`` and optionally ``donor_id``.
    """
    conditions: Dict[str, Any] = {}
    blockers: List[str] = []
    required: List[str] = []

    for condition, sections in sorted(sections_by_condition.items()):
        section_ids = sorted({str(item.get("section_id") or "") for item in sections if item.get("section_id")})
        donor_ids = sorted({str(item.get("donor_id") or "") for item in sections if item.get("donor_id")})
        cells = sum(int(item.get("cell_count") or 0) for item in sections)
        conditions[condition] = {
            "section_count": len(section_ids),
            "donor_count": len(donor_ids),
            "sections": section_ids,
            "donors": donor_ids,
            "cell_count": cells,
        }
        if len(section_ids) < min_sections:
            blockers.append(
                "Condition '%s' has %d section(s); condition-level inference needs at least %d."
                % (condition, len(section_ids), min_sections)
            )
            required.append("Add independent sections for condition '%s'." % condition)
        if donor_ids and len(donor_ids) < min_donors:
            blockers.append(
                "Condition '%s' has %d donor(s); generalizing beyond this donor needs at least %d."
                % (condition, len(donor_ids), min_donors)
            )
            required.append("Add independent donors for condition '%s'." % condition)
        if not donor_ids:
            required.append("Record donor_id for condition '%s' so replication can be assessed." % condition)

    if len(conditions) < 2:
        blockers.append("A condition comparison needs at least two conditions; got %d." % len(conditions))

    supported = not blockers
    return {
        "supports_condition_inference": supported,
        "status": "replicated" if supported else "pseudoreplicated",
        "conditions": conditions,
        "blockers": _dedupe(blockers),
        "required_next_inputs": _dedupe(required),
        "unit_of_analysis": "section" if supported else "cells_within_one_section_per_condition",
        "allowed_interpretation": (
            "Differences may be described at the condition level, with section-aware or pseudobulk statistics."
            if supported
            else "Differences describe the specific sections measured and cannot be attributed to the "
            "conditions. Cells within a section are not independent biological replicates."
        ),
        "recommended_statistics": (
            "Aggregate to one value per section (pseudobulk) and test across sections."
            if supported
            else "No condition-level test is valid at this design; report per-section descriptive summaries only."
        ),
    }


def _dedupe(items: Sequence[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
