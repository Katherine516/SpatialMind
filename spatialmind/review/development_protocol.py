"""Prespecified, human-approved annotation development without external truth access."""

import json
import math
from pathlib import Path

from spatialmind.contracts.review import review_decision_issues
from spatialmind.ingestion.identity import file_sha256
from .reference_curation import validate_reference_review


def prepare_protocol(packet, reference_packet, output):
    packet, reference_packet, output = Path(packet).resolve(), Path(reference_packet).resolve(), Path(output)
    if output.exists():
        raise ValueError("Protocol exists; do not overwrite a prespecified study.")
    sources = json.loads((packet / "handoff_manifest.json").read_text())["datasets"]
    protocol = {"schema_version": 1, "status": "draft_not_approved",
        "review_status": "pending", "reviewer_id": "", "reviewed_at": "", "evidence_ref": "", "confidence": None,
        "reference_review_packet": str(reference_packet), "reference_decision_sha256": "",
        "reference_snapshot_sha256": "", "handoff_manifest_sha256": file_sha256(packet / "handoff_manifest.json"),
        "development_donors": {key: {"donor_id": "", "review_status": "pending", "reviewer_id": "",
                                     "reviewed_at": "", "evidence_ref": "", "confidence": None} for key in sources},
        "candidate_neighbors": [5, 15], "candidate_prior_powers": [0.0, 0.25, 0.5, 1.0],
        "confidence_threshold": 0.6, "selection_metric": "macro_f1",
        "tie_break": "lower_prior_power_then_smaller_k", "minimum_validation_macro_f1": None,
        "minimum_validation_coverage": None, "threshold_rationale": "",
        "evaluation_scope": "within_section_spatial_block_development_not_independent_donor_validation",
        "external_test_policy": "separate_verified_donor_custodian_release_after_model_lock",
        "notice": "Draft values are not a power analysis. Approve thresholds before selection; never adjust them using external test results."}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    return protocol


def validate_protocol(path, packet):
    if path is None:
        raise ValueError("A prespecified approved development protocol is required.")
    path, packet = Path(path), Path(packet)
    plan = json.loads(path.read_text())
    if review_decision_issues(dict(plan, expert_label="development protocol")):
        raise ValueError("Development protocol requires identified human approval and evidence.")
    if plan.get("status") != "approved_before_selection":
        raise ValueError("Confirm approval before model selection, not after observing results.")
    if plan.get("handoff_manifest_sha256") != file_sha256(packet / "handoff_manifest.json"):
        raise ValueError("Protocol is tied to a different or changed review cohort.")
    ref = Path(plan["reference_review_packet"])
    if not ref.is_absolute():
        ref = path.parent / ref
    curation = validate_reference_review(ref)
    if curation["status"] != "recorded_curation_complete":
        raise ValueError("Reference curation is incomplete.")
    if (plan.get("reference_decision_sha256") != curation["decision_sha256"]
            or plan.get("reference_snapshot_sha256") != curation["source_snapshot_sha256"]):
        raise ValueError("Approved protocol must bind the exact reference decisions and source snapshot.")
    if plan.get("selection_metric") != "macro_f1" or plan.get("tie_break") != "lower_prior_power_then_smaller_k":
        raise ValueError("Unsupported prespecified selection rule.")
    if plan.get("evaluation_scope") != "within_section_spatial_block_development_not_independent_donor_validation":
        raise ValueError("The current selector is spatial-block development, not donor-held-out validation.")
    if plan.get("external_test_policy") != "separate_verified_donor_custodian_release_after_model_lock":
        raise ValueError("External testing must remain a separate custodian-released step.")
    for field in ("candidate_neighbors", "candidate_prior_powers"):
        values = plan.get(field)
        if not isinstance(values, list) or not values or len(values) > 20:
            raise ValueError("A bounded nonempty candidate grid is required.")
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Candidate parameters must be finite numbers.")
            if field == "candidate_neighbors" and (not isinstance(value, int) or not 1 <= value <= 100):
                raise ValueError("Neighbors must be integers in [1,100].")
            if field == "candidate_prior_powers" and not 0 <= value <= 1:
                raise ValueError("Prior powers must lie in [0,1].")
        if len(set(values)) != len(values):
            raise ValueError("Duplicate candidates are not permitted.")
    for field in ("confidence_threshold", "minimum_validation_macro_f1", "minimum_validation_coverage"):
        value = plan.get(field)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 < value <= 1:
            raise ValueError("Prespecify finite nonzero thresholds in (0,1].")
    if not str(plan.get("threshold_rationale", "")).strip():
        raise ValueError("Acceptance thresholds require a scientific rationale.")
    sources = json.loads((packet / "handoff_manifest.json").read_text())["datasets"]
    donors = plan.get("development_donors", {})
    if set(donors) != set(sources):
        raise ValueError("Every development section needs a source-verified donor.")
    for key, row in donors.items():
        if review_decision_issues(dict(row, expert_label=row.get("donor_id", ""))):
            raise ValueError("Development donor evidence is incomplete: " + key)
    return plan


def ordered_preflight(reference_packet, packet, protocol):
    """Report blockers without staging truth, fitting models or opening external truth."""
    from .brain_readiness import assignment_issues
    from .specialist_handoff import validate_handoff

    reference = validate_reference_review(reference_packet)
    root = Path(packet)
    config_path = root / "study_readiness.json"
    assignments = assignment_issues(json.loads(config_path.read_text()) if config_path.exists() else {})
    review = validate_handoff(root)
    protocol_issues = []
    try:
        validate_protocol(protocol, root)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        protocol_issues.append(str(exc))
    ready = reference["status"] == "recorded_curation_complete" and not assignments and review["status"] == "ready_for_staging" and not protocol_issues
    return {"status": "ready_for_reviewed_development" if ready else "blocked_missing_review_evidence",
        "reference_curation": reference, "specialist_assignments": assignments, "specialist_review": review,
        "protocol_blockers": protocol_issues, "training_performed": False, "external_test_scored": False,
        "next_action": "Complete real reference and Xenium specialist decisions, then approve the prespecified protocol."}
