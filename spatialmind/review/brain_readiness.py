"""Ordered acquisition gates for a specialist-reviewed brain validation study."""

import json
from datetime import datetime, timezone
from pathlib import Path

from .annotation_benchmark import digest, write_json

ROLES = ("brain_single_cell_specialist", "neuropathologist")
BIOSTUDIES = "https://www.ebi.ac.uk/biostudies/api/v1/studies/S-BSST2273"


def initialize(packet):
    root = Path(packet).resolve()
    handoff = json.loads((root / "handoff_manifest.json").read_text())
    config = {
        "schema_version": 1,
        "reviewers": {role: {"reviewer_id": "", "accepted_assignment": False,
                              "qualification_evidence": ""} for role in ROLES},
        "images": {key: {"required": True, "evidence_manifest": ""} for key in handoff["datasets"]},
        "external_test": {
            "candidate_accession": "S-BSST2273", "manifest": "",
            "status": "candidate_only_not_acquired_or_verified",
        },
        "model_lock": "",
        "notes": "No reviewers available. No decisions, donor independence, or image pairing inferred by software.",
    }
    path = root / "study_readiness.json"
    if path.exists():
        raise ValueError("Readiness configuration already exists; refusing to overwrite assignments.")
    write_json(path, config)
    return config


def assignment_issues(config):
    issues = []
    for role in ROLES:
        row = config.get("reviewers", {}).get(role, {})
        if not (str(row.get("reviewer_id", "")).strip()
                and row.get("accepted_assignment") is True
                and str(row.get("qualification_evidence", "")).strip()):
            issues.append("Assign and obtain acceptance from a qualified " + role)
    return issues


def assign(packet, role, reviewer_id, qualification_evidence):
    if role not in ROLES or not reviewer_id.strip() or not qualification_evidence.strip():
        raise ValueError("A supported role, real reviewer ID and qualification evidence are required.")
    root = Path(packet)
    path = root / "study_readiness.json"
    config = json.loads(path.read_text())
    config["reviewers"][role] = {
        "reviewer_id": reviewer_id.strip(), "qualification_evidence": qualification_evidence,
        "accepted_assignment": True, "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(path, config)
    return config["reviewers"][role]


def _resolve(root, name):
    path = Path(name)
    return path if path.is_absolute() else root / path


def _verify_files(root, files):
    if not files:
        raise ValueError("No immutable input hashes supplied")
    for name, expected in files.items():
        path = _resolve(root, name)
        if not path.is_file() or digest(path) != expected:
            raise ValueError("Missing or changed evidence: " + name)


def validate_image_evidence(path, dataset_path, reviewer_id):
    """Check an explicitly pixel-to-micron affine transform on unused landmarks.

    This does not infer section identity or replace a pathologist's visual QC.
    Xenium Explorer CSV matrices must first be converted to the declared convention.
    """
    import numpy as np

    path = Path(path)
    evidence = json.loads(path.read_text())
    _verify_files(path.parent, evidence.get("files", {}))
    if evidence.get("modality") not in {"H&E", "IHC", "IF"}:
        raise ValueError("H&E, IHC or IF evidence required; DAPI alone is not a substitute")
    if Path(evidence.get("dataset_path", "")).resolve() != Path(dataset_path).resolve():
        raise ValueError("Image evidence belongs to a different dataset")
    if not reviewer_id or evidence.get("reviewer_id") != reviewer_id:
        raise ValueError("Image pairing requires the assigned neuropathologist")
    for key in ("same_section_confirmed", "visual_alignment_approved"):
        if evidence.get(key) is not True:
            raise ValueError("Missing human confirmation: " + key)
    if not evidence.get("pairing_evidence") or not evidence.get("threshold_rationale"):
        raise ValueError("Section pairing evidence and a prespecified tolerance rationale are required")
    if evidence.get("transform_convention") != "image_pixel_xy_to_xenium_micron_xy_column_vector":
        raise ValueError("Unknown transform direction or units")
    image = evidence.get("image_file", "")
    experiment = str(Path(dataset_path).resolve() / "experiment.xenium")
    hashed_paths = {str(_resolve(path.parent, p).resolve()) for p in evidence["files"]}
    if str(_resolve(path.parent, image).resolve()) not in hashed_paths or experiment not in hashed_paths:
        raise ValueError("Image and exact Xenium experiment must both be hashed")
    from tifffile import TiffFile
    with TiffFile(_resolve(path.parent, image)) as tif:
        height, width = tif.pages[0].imagelength, tif.pages[0].imagewidth
    matrix = np.asarray(evidence.get("matrix"), dtype=float)
    if (matrix.shape != (3, 3) or not np.isfinite(matrix).all()
            or not np.allclose(matrix[2], [0, 0, 1]) or abs(np.linalg.det(matrix[:2, :2])) < 1e-12):
        raise ValueError("A finite nonsingular 3x3 affine matrix is required")
    points = evidence.get("landmarks", [])
    groups = {}
    for group, minimum in (("fit", 3), ("check", 3)):
        rows = [row for row in points if row.get("use") == group]
        xy = np.asarray([row["image_xy_px"] for row in rows], dtype=float)
        target = np.asarray([row["xenium_xy_um"] for row in rows], dtype=float)
        if len(rows) < minimum or xy.shape != (len(rows), 2) or target.shape != xy.shape:
            raise ValueError("At least three fit and three independent check landmarks are required")
        if not np.isfinite(xy).all() or not np.isfinite(target).all():
            raise ValueError("Landmarks must be finite")
        if np.any(xy < 0) or np.any(xy[:, 0] >= width) or np.any(xy[:, 1] >= height):
            raise ValueError("Landmarks fall outside the image")
        if np.linalg.matrix_rank(np.c_[xy, np.ones(len(xy))]) != 3:
            raise ValueError("Landmarks must not be collinear")
        groups[group] = (xy, target)
    if set(map(tuple, groups["fit"][0])) & set(map(tuple, groups["check"][0])):
        raise ValueError("Check landmarks must not reuse fitting landmarks")
    xy, target = groups["check"]
    errors = np.linalg.norm((np.c_[xy, np.ones(len(xy))] @ matrix.T)[:, :2] - target, axis=1)
    tolerance = float(evidence["max_check_error_um"])
    if not np.isfinite(tolerance) or tolerance <= 0 or errors.max() > tolerance:
        raise ValueError("Independent landmark residual exceeds the prespecified tolerance")
    return {"status": "recorded_evidence_passed", "check_landmarks": len(xy),
            "median_error_um": float(np.median(errors)), "max_error_um": float(errors.max()),
            "manifest_sha256": digest(path)}


def validate_external_manifest(path):
    path = Path(path)
    data = json.loads(path.read_text())
    _verify_files(path.parent, data.get("files", {}))
    required = ("source_url", "license", "label_provenance", "independence_evidence",
                "custodian_id", "organism", "tissue", "assay", "label_crosswalk", "evaluation_protocol")
    if any(not data.get(key) for key in required):
        raise ValueError("External donor provenance, crosswalk and evaluation protocol are incomplete")
    if data["organism"].lower() not in {"human", "homo sapiens"} or data["tissue"].lower() not in {"brain", "glioblastoma"}:
        raise ValueError("This study requires a human brain external donor")
    for field in ("donor_independence_confirmed", "labels_independent_of_this_agent", "test_labels_sealed"):
        if data.get(field) is not True:
            raise ValueError("External test not verified: " + field)
    train, test = set(data.get("development_donor_ids", [])), set(data.get("test_donor_ids", []))
    if not train or not test or train & test or any(not str(x).strip() for x in train | test):
        raise ValueError("Nonempty disjoint donor IDs and evidence are required; different sections are not independent donors")
    for field in ("expression_file", "truth_file", "label_crosswalk", "evaluation_protocol"):
        if data.get(field) not in data["files"]:
            raise ValueError(field + " must be a hashed file")
    return {"status": "recorded_provenance_passed", "assay": data["assay"],
            "test_donors": len(test), "manifest_sha256": digest(path)}


def acquire_candidate_catalog(output_dir):
    """Fetch repository metadata only, never unseal external test labels."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "S-BSST2273_repository_metadata.json"
    if path.exists():
        raise ValueError("Catalog already exists; use a new directory to retain acquisition history")
    import requests
    response = requests.get(BIOSTUDIES, timeout=45)
    response.raise_for_status()
    data = response.json()
    if data.get("accno") != "S-BSST2273":
        raise ValueError("Unexpected BioStudies accession")
    write_json(path, data)
    result = {"source": BIOSTUDIES, "retrieved_at": datetime.now(timezone.utc).isoformat(),
              "metadata_sha256": digest(path), "status": "metadata_only_not_test_data",
              "files": [{"path": row["path"], "bytes": row["size"], "attributes": row.get("attributes", [])}
                        for row in data["section"]["files"]],
              "blockers": ["Donor identity and non-overlap require confirmation",
                           "Panel overlap and label granularity require pre-test assessment",
                           "Annotated Seurat RDS must be converted without leaking truth into model selection",
                           "Published computational annotations are not automatically independent assay truth"]}
    write_json(root / "acquisition_status.json", result)
    return result


def readiness(packet):
    from .specialist_handoff import validate_handoff

    root = Path(packet).resolve()
    config = json.loads((root / "study_readiness.json").read_text())
    handoff = json.loads((root / "handoff_manifest.json").read_text())
    steps = [{"step": 1, "name": "Assign specialists", "blockers": assignment_issues(config)}]
    image_issues, images = [], {}
    reviewer = config["reviewers"]["neuropathologist"]["reviewer_id"]
    for key, info in handoff["datasets"].items():
        request = config.get("images", {}).get(key, {})
        manifest = request.get("evidence_manifest")
        if not manifest:
            image_issues.append(key + ": missing matched registered H&E/IHC evidence")
            continue
        try:
            images[key] = validate_image_evidence(_resolve(root, manifest), info["source_dataset"], reviewer)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            image_issues.append(key + ": " + str(exc))
    steps.append({"step": 2, "name": "Obtain and verify registered images", "blockers": image_issues, "images": images})
    external_issues, external = [], {}
    manifest = config.get("external_test", {}).get("manifest")
    if not manifest:
        external_issues.append("No acquired, provenance-verified, sealed external donor")
    else:
        try:
            external = validate_external_manifest(_resolve(root, manifest))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            external_issues.append(str(exc))
    steps.append({"step": 3, "name": "Freeze independent external test", "blockers": external_issues, "external": external})
    review = validate_handoff(root)
    model_issues = []
    if review["status"] != "ready_for_staging":
        model_issues.append("Complete specialist-reviewed brain training/validation labels and regions")
    # No automatic evaluation: one external test must be released by its custodian
    # only after training/validation selection and a frozen protocol are verified.
    model_issues.append("Brain model selection and custodian-controlled external evaluation are not yet performed")
    steps.append({"step": 4, "name": "Improve rare classes, lock model, evaluate once", "blockers": model_issues})
    prior_blocked = False
    for step in steps:
        step["status"] = "blocked_by_previous_step" if prior_blocked else ("needs_input" if step["blockers"] else "ready")
        prior_blocked |= bool(step["blockers"])
    result = {"status": "not_externally_validated", "steps": steps, "specialist_review": review,
              "caveat": "Checks validate recorded evidence, not qualifications or biological truth. File sealing is procedural, not access control."}
    write_json(root / "ordered_readiness_report.json", result)
    return result
