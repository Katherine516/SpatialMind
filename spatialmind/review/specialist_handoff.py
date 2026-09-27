"""Prepare and validate specialist decisions without promoting machine drafts to truth."""

import csv
import json
import math
import shutil
from datetime import datetime
from pathlib import Path

from .annotation_benchmark import digest, write_csv, write_json


def _read(path):
    with Path(path).open(newline="") as stream:
        return list(csv.DictReader(stream))


def prepare_handoff(existing_packet, output_dir):
    source, root = Path(existing_packet).resolve(), Path(output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a new empty handoff directory; existing review decisions must not be overwritten.")
    summary = json.loads((source / "brain_benchmark_packet_summary.json").read_text())
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"source_packet": str(source), "datasets": {}, "status": "awaiting_specialist_review"}
    for key in summary["datasets"]:
        original, destination = source / key, root / key
        destination.mkdir()
        labels = _read(original / "expert_cell_labels_for_review.csv")
        regions = _read(original / "cell_regions_for_review.csv")
        # Preserve existing decisions verbatim, but keep automated suggestions out
        # of the first-pass worksheet. Original evidence stays in a separate file.
        write_csv(destination / "candidate_evidence.csv", labels)
        label_fields = ["cell_id", "x", "y", "expert_label", "cl_id", "secondary_state", "confidence",
                        "reviewer_id", "reviewed_at", "review_status", "evidence_ref", "notes"]
        region_fields = ["cell_id", "x", "y", "region", "region_confidence", "region_reviewer_id",
                         "region_reviewed_at", "review_status", "region_basis", "evidence_ref", "notes"]
        write_csv(destination / "expert_cell_labels_for_review.csv",
                  [{field: row.get(field, "") for field in label_fields} for row in labels])
        write_csv(destination / "cell_regions_for_review.csv",
                  [{field: row.get(field, "") for field in region_fields} for row in regions])
        copied = {}
        for name in ("benchmark_split_manifest.csv", "expert_review_viewer.html", "spatial_distribution.svg", "cluster_marker_summary.csv"):
            if (original / name).exists():
                shutil.copy2(original / name, destination / name)
                copied[name] = digest(destination / name)
        cohort = [{"cell_id": row["cell_id"], "x": row["x"], "y": row["y"]} for row in labels]
        write_json(destination / "frozen_cohort.json", cohort)
        copied["frozen_cohort.json"] = digest(destination / "frozen_cohort.json")
        manifest["datasets"][key] = {"cohort_cells": len(cohort), "immutable_files": copied,
                                      "source_dataset": summary["datasets"][key].get("dataset_path", "")}
    write_json(root / "handoff_manifest.json", manifest)
    (root / "REVIEW_INSTRUCTIONS.md").write_text(
        "# Specialist Brain Review Handoff\n\n"
        "Status: awaiting specialist review. No final labels or anatomical regions have been manufactured.\n\n"
        "## Roles and sequence\n\n"
        "1. A brain single-cell specialist reviews cell identity from expression, panel coverage, segmentation and morphology. "
        "A neuropathologist reviews anatomical boundaries and pathology. One qualified person may cover both roles.\n"
        "2. First fill the decision sheets without candidate labels. The separate candidate_evidence.csv is for a second pass. "
        "Expression-assisted review is not independent assay ground truth; document the evidence actually used.\n"
        "3. Record expert_label, confidence (0-1), reviewer_id, reviewed_at (ISO date), evidence_ref and review_status=reviewed or approved. "
        "Use CL IDs where appropriate; malignant state is not established by an astrocyte ontology term. "
        "Do not force an uncertain identity: leave its status uncertain.\n"
        "4. Review cell_regions_for_review.csv against registered images. Record region, region_confidence, "
        "region_reviewer_id, region_reviewed_at, review_status, region_basis and evidence_ref. "
        "Allowed anatomical evidence bases: morphology, registered_histology, registered_ihc. "
        "Evidence references should identify image/slide and ROI or polygon. Domain composition is not anatomical evidence.\n"
        "5. DAPI alone may not establish cortical layers, infiltration, necrosis or malignancy. Request registered H&E/IHC "
        "and a neuropathologist when needed. Keep unsupported regions uncertain; do not rename spatial blocks as anatomy.\n"
        "6. Arrange a blinded second review of ambiguous cases and a prespecified random subset; adjudicate disagreements "
        "before freezing truth. Reviewer credentials and evidence correctness require human verification.\n\n"
        "## Validation and staging\n\n"
        "Run `.venv/bin/python scripts/manage_brain_specialist_review.py validate --packet " + str(root) + "`. "
        "The command refuses invalid or incomplete provenance and requires at least 90% jointly accepted rows in every split. "
        "Only then can `--export-to <new-directory>` stage expert_cell_labels.csv, cell_regions.csv, and truth splits. "
        "Nothing is copied into data/ automatically. Cohort review covers only selected cells, not the whole section; "
        "it cannot unlock a full-section readiness gate by itself.\n\n"
        "Keep the frozen cohort and split files unchanged. Report section-level dependence; these are not independent donor splits.\n"
    )
    return validate_handoff(str(root))


def _accepted(row, region=False):
    fields = (("region", "region_confidence", "region_reviewer_id", "region_reviewed_at") if region else
              ("expert_label", "confidence", "reviewer_id", "reviewed_at"))
    if row.get("review_status", "").strip().lower() not in {"reviewed", "approved"}:
        return False
    if any(not row.get(field, "").strip() for field in fields + ("evidence_ref",)):
        return False
    if row[fields[0]].strip().lower() in {"unknown", "uncertain", "unreviewed", "unlabeled"}:
        return False
    try:
        confidence = float(row[fields[1]])
        datetime.fromisoformat(row[fields[3]].replace("Z", "+00:00"))
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            return False
    except ValueError:
        return False
    return not region or row.get("region_basis") in {"morphology", "registered_histology", "registered_ihc"}


def validate_handoff(packet_dir, export_to=None):
    root = Path(packet_dir)
    manifest = json.loads((root / "handoff_manifest.json").read_text())
    reports, ready = {}, {}
    for key, info in manifest["datasets"].items():
        folder = root / key
        issues = []
        for name, expected in info["immutable_files"].items():
            if not (folder / name).is_file() or digest(folder / name) != expected:
                issues.append("Frozen artifact changed: " + name)
        cohort = json.loads((folder / "frozen_cohort.json").read_text())
        expected_rows = {row["cell_id"]: row for row in cohort}
        labels, regions = _read(folder / "expert_cell_labels_for_review.csv"), _read(folder / "cell_regions_for_review.csv")
        for name, rows in (("labels", labels), ("regions", regions)):
            ids = [row["cell_id"] for row in rows]
            if len(ids) != len(set(ids)) or set(ids) != set(expected_rows):
                issues.append(name + ": duplicate, missing or extra cell IDs")
            if any(row.get(axis) != expected_rows.get(row["cell_id"], {}).get(axis) for row in rows for axis in ("x", "y")):
                issues.append(name + ": frozen coordinates changed")
        label_map = {row["cell_id"]: row for row in labels if _accepted(row)}
        region_map = {row["cell_id"]: row for row in regions if _accepted(row, region=True)}
        joint = set(label_map) & set(region_map) & set(expected_rows)
        invalid_decisions = sum(row.get("review_status", "").lower() in {"approved", "reviewed"}
                                and not _accepted(row, region=is_region)
                                for rows, is_region in ((labels, False), (regions, True)) for row in rows)
        if invalid_decisions:
            issues.append("%d claimed reviewed decisions have missing/invalid evidence or provenance" % invalid_decisions)
        splits = _read(folder / "benchmark_split_manifest.csv")
        split_ids = [row["cell_id"] for row in splits]
        if set(split_ids) != set(expected_rows) or len(split_ids) != len(set(split_ids)):
            issues.append("Split membership does not exactly match cohort")
        block_splits = {}
        for row in splits:
            block_splits.setdefault(row["proposed_spatial_block"], set()).add(row["provisional_split"])
        if any(len(values) > 1 for values in block_splits.values()):
            issues.append("A spatial block crosses splits")
        coverage = {}
        for split in ("train", "validation", "test"):
            members = {row["cell_id"] for row in splits if row["provisional_split"] == split}
            coverage[split] = len(members & joint) / len(members) if members else 0.0
            if coverage[split] < 0.9:
                issues.append(split + ": fewer than 90% jointly accepted decisions")
        reports[key] = {"status": "ready_for_staging" if not issues else "awaiting_specialist_review",
                        "cohort_cells": len(cohort), "accepted_labels": len(label_map), "accepted_regions": len(region_map),
                        "jointly_accepted": len(joint), "joint_coverage_by_split": coverage, "blockers": issues}
        ready[key] = (label_map, region_map, joint, splits)
    result = {"status": "ready_for_staging" if reports and all(not r["blockers"] for r in reports.values()) else "awaiting_specialist_review",
              "datasets": reports, "human_verification_required": "Software validates recorded decisions, not reviewer qualifications or biological truth."}
    write_json(root / "specialist_validation.json", result)
    if export_to:
        if result["status"] != "ready_for_staging":
            raise ValueError("Specialist review is incomplete; no final files were exported.")
        output = Path(export_to)
        if output.exists() and any(output.iterdir()):
            raise ValueError("Staging directory must be empty.")
        for key, (labels, regions, joint, splits) in ready.items():
            destination = output / key
            destination.mkdir(parents=True, exist_ok=True)
            split_map = {row["cell_id"]: row["provisional_split"] for row in splits}
            label_rows, region_rows, truth_rows = [], [], []
            for cell_id in sorted(joint):
                label, region = labels[cell_id], regions[cell_id]
                label_rows.append(dict(label, assignment_scope="specialist_cell_review", source=str(root.resolve())))
                region_rows.append(dict(region, confidence=region["region_confidence"], reviewer_id=region["region_reviewer_id"],
                                        reviewed_at=region["region_reviewed_at"], assignment_scope="specialist_anatomical_review", source=str(root.resolve())))
                truth_rows.append({"cell_id": cell_id, "expert_label": label["expert_label"], "region": region["region"], "split": split_map[cell_id]})
            write_csv(destination / "expert_cell_labels.csv", label_rows)
            write_csv(destination / "cell_regions.csv", region_rows)
            for split in ("train", "validation", "test"):
                write_csv(destination / (split + "_truth.csv"), [row for row in truth_rows if row["split"] == split])
        write_json(output / "staging_manifest.json", {"review_status": result, "source_packet": str(root.resolve()),
                                                     "files": {str(p.relative_to(output)): digest(p) for p in output.rglob("*.csv")}})
    return result
