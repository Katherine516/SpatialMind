"""Draft collection-wide donor assignments; never an external test or approval."""

import hashlib
from typing import Any, Dict


def plan_donor_splits(audit: Dict[str, Any], collection: str, seed: int = 0) -> Dict[str, Any]:
    if not collection:
        raise ValueError("Choose one documented collection; filenames do not establish study identity.")
    refs = [r for r in audit.get("references", []) if r.get("collection") == collection]
    if not refs or any(not r.get("species_matches_target") for r in refs):
        raise ValueError("The collection is missing or has a species mismatch.")
    invalid = {"", "unknown", "nan", "none", "na", "n/a"}
    donors = set()
    for ref in refs:
        counts = ref.get("donor_counts") or {}
        if not counts or any(str(d).strip().lower() in invalid for d in counts):
            raise ValueError("Every observation requires a documented donor before drafting splits.")
        donors.update(counts)
    if len(donors) < 3:
        raise ValueError("Need at least three donors for a train/validation/test draft; this is not a power calculation.")
    ranked = sorted(donors, key=lambda d: hashlib.sha256((str(seed) + "|" + collection + "|" + d).encode()).hexdigest())
    heldout = max(1, len(ranked) // 5)
    roles = {"test": ranked[:heldout], "validation": ranked[heldout:heldout * 2], "train": ranked[heldout * 2:]}
    members = []
    for ref in refs:
        members.append({"path": ref["path"], "dataset_version_url": ref.get("dataset_version_url"),
                        "expression_layer_candidate": ref.get("candidate_layer"),
                        "allowed_donors_by_role": {role: sorted(set(ids) & set(ref["donor_counts"])) for role, ids in roles.items()},
                        "cells_by_role": {role: sum(ref["donor_counts"].get(d, 0) for d in ids) for role, ids in roles.items()}})
    return {"status": "draft_internal_donor_split", "approved": False, "training_ready": False,
            "collection": collection, "seed": seed, "donor_count": len(donors),
            "donors_by_role": {role: sorted(ids) for role, ids in roles.items()}, "references": members,
            "basis": "Deterministic donor hash only; no labels or expression used to choose partitions",
            "external_test": False, "test_scored": False,
            "blockers": ["Curator must verify donor aliases, source identities and expression-layer evidence.",
                         "Review class/region representation using development partitions only.",
                         "This is an internal atlas split, not independent Xenium expert truth or an acquired external donor."]}
