"""Recorded review evidence shared by ingestion, Studio and specialist handoffs."""

from datetime import datetime
from math import isfinite


ANATOMICAL_BASES = {"morphology", "registered_histology", "registered_ihc"}
REGION_BASES = ANATOMICAL_BASES | {"user_roi"}


def review_decision_issues(row, region=False, anatomical=False):
    """Validate recorded provenance, not a person's credentials or biological truth."""
    value = row.get("region" if region else "expert_label", "")
    confidence = row.get("region_confidence" if region else "confidence", "")
    reviewer = row.get("region_reviewer_id", "") if region else ""
    reviewer = str(reviewer or row.get("reviewer_id", "")).strip()
    date = row.get("region_reviewed_at", "") if region else ""
    date = str(date or row.get("reviewed_at", "")).strip()
    issues = []
    if str(row.get("review_status", "")).strip().lower() not in {"reviewed", "approved"}:
        issues.append("not_approved")
    if not str(value).strip() or str(value).strip().lower() in {
        "unknown", "uncertain", "unreviewed", "unlabeled", "unannotated", "unknown cell", "unannotated cell", "unlabeled cell"
    }:
        issues.append("unresolved_identity")
    if not reviewer or reviewer.lower().startswith("unidentified"):
        issues.append("missing_reviewer")
    if not str(row.get("evidence_ref", "")).strip():
        issues.append("missing_evidence")
    try:
        datetime.fromisoformat(date.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        issues.append("invalid_reviewed_at")
    try:
        number = float(confidence)
        if not isfinite(number) or not 0 <= number <= 1:
            raise ValueError()
    except (TypeError, ValueError):
        issues.append("invalid_confidence")
    if region and row.get("region_basis") not in (ANATOMICAL_BASES if anatomical else REGION_BASES):
        issues.append("invalid_region_basis")
    return issues
