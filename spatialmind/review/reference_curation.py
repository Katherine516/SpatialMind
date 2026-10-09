"""Source-backed reference decisions; software never supplies human approval."""

import hashlib
import json
import re
from pathlib import Path

from spatialmind.contracts.review import review_decision_issues
from spatialmind.ingestion.identity import file_sha256


def _key(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def _review_fields():
    return {"review_status": "pending", "reviewer_id": "", "reviewed_at": "",
            "confidence": None, "evidence_ref": ""}


def prepare_reference_review(audit_path, output):
    """Keep source facts separate from blank decisions; omit mismatched species."""
    output = Path(output)
    if output.exists():
        raise ValueError("Use a new review directory; never overwrite curator decisions.")
    audit = json.loads(Path(audit_path).read_text())
    if audit.get("errors"):
        raise ValueError("Resolve source audit errors first.")
    refs, labels, donors = [], [], {}
    excluded = []
    for source in audit["references"]:
        if not source.get("species_matches_target"):
            excluded.append({"path": source["path"], "species": source.get("species"), "reason": "species mismatch or ambiguity"})
            continue
        version, collection = source.get("dataset_version_url"), source.get("collection")
        if not version or not collection:
            raise ValueError("Version and collection evidence are required before preparing a crosswalk.")
        ref = _key(version)
        refs.append(dict(_review_fields(), reference_id=ref, source_path=source["path"],
            source_version_url=version, collection=collection, species=source["species"],
            expression_layer=source.get("candidate_layer"), expression_semantics=source.get("candidate_semantics"),
            assay="", label_provenance="", gene_mapping_policy="", license_evidence=""))
        for label in source["label_counts"]:
            labels.append(dict(_review_fields(), reference_id=ref, source_label=label,
                source_label_count=source["label_counts"][label], target_label="", cell_ontology_id="",
                ontology_exception_reason="", malignant_state="unresolved", state_evidence="", use_for_training=False))
        for donor in source["donor_counts"]:
            donors[collection, donor] = dict(_review_fields(), collection=collection, source_donor_id=donor,
                canonical_donor_id="", identity_evidence="", development_role="unassigned")
    snapshot = {"references": refs, "source_labels": [dict(reference_id=r["reference_id"], source_label=r["source_label"])
                for r in labels], "source_donors": [dict(collection=r["collection"], source_donor_id=r["source_donor_id"])
                for r in donors.values()], "excluded": excluded, "audit_sha256": file_sha256(audit_path)}
    decisions = {"schema_version": 1, "references": refs, "label_crosswalk": labels,
        "donors": list(donors.values()), "donor_alias_review": dict(_review_fields(), method_and_scope=""),
        "notice": "Source annotations are not expert Xenium truth. No review or donor independence is inferred."}
    output.mkdir(parents=True)
    (output / "source_snapshot.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    decisions["source_snapshot_sha256"] = file_sha256(output / "source_snapshot.json")
    (output / "reference_decisions.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    (output / "REVIEW_GUIDE.md").write_text(
        "# Reference Curation Review\n\n"
        "All decisions are pending. Do not mark reviewed unless a real person examined the evidence.\n\n"
        "1. Confirm each source version, assay, expression layer/semantics, label provenance, gene mapping and license evidence.\n"
        "2. Map every source label to a lineage label and Cell Ontology ID, or record why no suitable ID applies. "
        "Keep malignant/nonmalignant/uncertain state separate, with state-specific evidence. "
        "An astrocyte ontology term does not establish benignity. Exclude unresolved mappings from training.\n"
        "3. Verify donor aliases within and across collections using source evidence. "
        "Fill canonical_donor_id and train/validation/internal_test/exclude roles; one person cannot cross roles. "
        "A source donor string or different collection alone is insufficient. Document the global alias review.\n"
        "4. For each decision record reviewer_id, ISO reviewed_at, evidence_ref, confidence and review_status. "
        "Source snapshots are frozen; changed versions require a new packet.\n\n"
        "The earlier metadata audit inspected all-donor label summaries. Internal test drafts are not sealed external tests. "
        "This packet cannot replace expert_cell_labels.csv or cell_regions.csv for Xenium.\n", encoding="utf-8")
    return validate_reference_review(output)


def validate_reference_review(packet):
    packet = Path(packet)
    decisions = json.loads((packet / "reference_decisions.json").read_text())
    source = json.loads((packet / "source_snapshot.json").read_text())
    issues = []
    if file_sha256(packet / "source_snapshot.json") != decisions.get("source_snapshot_sha256"):
        issues.append("Frozen reference source snapshot changed")

    def unique(rows, fields, expected, name):
        keys = [tuple(row.get(f) for f in fields) for row in rows]
        wanted = {tuple(row.get(f) for f in fields) for row in expected}
        if len(keys) != len(set(keys)) or set(keys) != wanted:
            issues.append(name + ": source membership changed or duplicated")

    def reviewed(row, identity, scope):
        problems = review_decision_issues(dict(row, expert_label=identity))
        if problems:
            issues.append(scope + ": " + ", ".join(problems))

    refs = decisions.get("references", [])
    labels = decisions.get("label_crosswalk", [])
    donors = decisions.get("donors", [])
    unique(refs, ["reference_id"], source["references"], "References")
    unique(labels, ["reference_id", "source_label"], source["source_labels"], "Labels")
    unique(donors, ["collection", "source_donor_id"], source["source_donors"], "Donors")
    expected_refs = {r["reference_id"]: r for r in source["references"]}
    for row in refs:
        scope = "Reference " + str(row.get("reference_id"))[:12]
        reviewed(row, row.get("source_version_url", ""), scope)
        expected = expected_refs.get(row.get("reference_id"), {})
        if any(row.get(f) != expected.get(f) for f in ("source_version_url", "species", "collection")):
            issues.append(scope + ": source identity/species changed")
        if any(not str(row.get(f) or "").strip() for f in ("assay", "label_provenance", "gene_mapping_policy", "license_evidence", "expression_layer")):
            issues.append(scope + ": source evidence incomplete")
        if row.get("assay") not in {"scRNA", "snRNA"} or row.get("expression_semantics") not in {"raw_counts", "log_normalized"}:
            issues.append(scope + ": unsupported assay or expression semantics")
    active_labels = 0
    for row in labels:
        scope = "Label " + str(row.get("source_label"))
        reviewed(row, row.get("source_label", ""), scope)
        if type(row.get("use_for_training")) is not bool:
            issues.append(scope + ": use_for_training must be boolean")
        if not row.get("use_for_training"):
            continue
        active_labels += 1
        if not str(row.get("target_label", "")).strip():
            issues.append(scope + ": missing target lineage")
        if not re.fullmatch(r"CL:\d{7}", str(row.get("cell_ontology_id", ""))) and not row.get("ontology_exception_reason"):
            issues.append(scope + ": ontology mapping or exception rationale required")
        if row.get("malignant_state") not in {"malignant", "nonmalignant", "uncertain"} or not row.get("state_evidence"):
            issues.append(scope + ": separate state assessment and evidence required")
        if any(term in str(row.get("source_label", "")).lower() for term in ("malignant", "neoplastic")) and row.get("malignant_state") == "nonmalignant":
            issues.append(scope + ": malignant source cannot silently become a nonmalignant lineage")
    if not active_labels:
        issues.append("No reviewed mappings selected for training")
    canonical_roles = {}
    for row in donors:
        scope = "Donor " + str(row.get("source_donor_id"))
        reviewed(row, row.get("source_donor_id", ""), scope)
        canonical = str(row.get("canonical_donor_id", "")).strip()
        role = row.get("development_role")
        if not canonical or canonical.lower() in {"unknown", "none", "unassigned"} or not row.get("identity_evidence"):
            issues.append(scope + ": canonical identity and source evidence required")
        if role not in {"train", "validation", "internal_test", "exclude"}:
            issues.append(scope + ": assign a development role")
        canonical_roles.setdefault(canonical, set()).add(role)
    if any(len(roles - {"exclude"}) > 1 for roles in canonical_roles.values()):
        issues.append("Canonical donor crosses development partitions")
    alias = decisions.get("donor_alias_review", {})
    reviewed(alias, "donor alias audit", "Cross-study donor audit")
    if not alias.get("method_and_scope"):
        issues.append("Cross-study donor audit requires a method and scope")
    return {"status": "recorded_curation_complete" if not issues else "blocked_reference_curation",
        "blockers": issues, "references": len(refs), "label_mappings": len(labels), "donor_entries": len(donors),
        "decision_sha256": file_sha256(packet / "reference_decisions.json"),
        "source_snapshot_sha256": file_sha256(packet / "source_snapshot.json"),
        "biological_validation": False,
        "caveat": "Checks validate recorded evidence, not reviewer authenticity, ontology correctness or donor independence."}
