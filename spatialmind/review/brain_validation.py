"""Brain annotation selection and a custodian-released, one-attempt external test.

File hashes and reservation files are procedural safeguards, not access control.
Human decisions and donor identities are never generated here.
"""

import csv
import json
import shutil
from pathlib import Path

from .annotation_benchmark import blinded_dataset, digest, metrics, write_csv, write_json
from .brain_readiness import validate_external_manifest, assignment_issues
from .development_protocol import validate_protocol
from spatialmind.ingestion import load_xenium, load_scrna
from spatialmind.schemas import SpatialDataset, SpotRecord, expression_feature_names
from spatialmind.tools.implementations import reference_label_transfer


def _rows(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    ids = [row.get("cell_id", "").strip() for row in rows]
    if not ids or any(not cell for cell in ids) or len(ids) != len(set(ids)):
        raise ValueError("Truth requires nonempty unique cell IDs.")
    return rows


def _empty_output(path):
    root = Path(path)
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a new empty output directory; validation artifacts cannot be overwritten.")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _predict(query, reference, params):
    if any(row.cell_type or row.region for row in query.records):
        raise ValueError("External queries must be label- and region-blind.")
    return reference_label_transfer(query, dict(params, reference_dataset=reference,
                                    min_shared_features=2, allow_incomplete_reference=True)).metrics["predictions"]


def select_brain_annotation(packet, staging, output_dir, donor_map=None, protocol_path=None):
    """Use staged training/validation only; never parse internal test truth."""
    packet, staging = Path(packet).resolve(), Path(staging).resolve()
    configuration = packet / "study_readiness.json"
    if not configuration.exists() or assignment_issues(json.loads(configuration.read_text())):
        return {"status": "blocked_awaiting_specialists", "test_scored": False,
                "blockers": ["Assign accepted, qualified human specialists in study_readiness.json."]}
    manifest = json.loads((staging / "staging_manifest.json").read_text())
    if (Path(manifest["source_packet"]).resolve() != packet or not manifest.get("source_review_hashes")
            or manifest.get("review_status", {}).get("status") != "ready_for_staging"
            or manifest.get("readiness_sha256") != digest(configuration)):
        raise ValueError("Staging must be tied to the exact reviewed packet.")
    for name, expected in manifest["source_review_hashes"].items():
        if digest(name) != expected:
            raise ValueError("Reviewed decisions changed after staging: " + name)
    protocol_sha256 = digest(protocol_path) if protocol_path is not None else None
    protocol = validate_protocol(protocol_path, packet)
    sources = json.loads((packet / "handoff_manifest.json").read_text())["datasets"]
    donors = {key: row["donor_id"] for key, row in protocol["development_donors"].items()}
    if donor_map is not None and donor_map != donors:
        raise ValueError("Donor map differs from the approved protocol evidence.")
    if donors and (set(donors) != set(sources) or any(not str(value).strip() for value in donors.values())):
        raise ValueError("Donor map must identify every development section; do not infer donor IDs from filenames.")
    groups, features, inputs = {"train": [], "validation": []}, set(), {}
    for key, info in sources.items():
        source = Path(info["source_dataset"])
        if source.is_file():
            source = source.parent
        matrix = source / "cell_feature_matrix.h5"
        inputs[str(matrix.resolve())] = digest(matrix)
        data = load_xenium(str(source), max_records=0, max_features_per_record=0)
        for split in groups:
            name = key + "/" + split + "_truth.csv"
            path = staging / name
            if digest(path) != manifest["files"].get(name):
                raise ValueError("Staged development truth changed: " + name)
            truth = _rows(path)
            lookup = {row["cell_id"]: row["expert_label"] for row in truth}
            selected = [row for row in data.records if row.cell_id in lookup]
            if len(selected) != len(lookup):
                raise ValueError("Development truth IDs do not match expression.")
            if split == "train":
                features.update(expression_feature_names(SpatialDataset(key, selected, "",
                                             metadata={"control_features": data.metadata.get("control_features", [])})))
            for row in selected:
                groups[split].append(SpotRecord(key, 0, 0, lookup[row.cell_id], dict(row.raw_genes or row.genes),
                                               cell_id=key + ":" + row.cell_id))
    train, val = groups["train"], groups["validation"]
    if len(train) < 15 or len(val) < 4 or len({row.cell_type for row in train}) < 2 or len(features) < 2:
        raise ValueError("Need at least 15 training cells, two classes/features and four validation cells.")
    if {row.cell_id for row in train} & {row.cell_id for row in val}:
        raise ValueError("Training and validation IDs overlap.")
    features = sorted(features)
    reference = SpatialDataset("brain-train", train, "", metadata={"organism": "human"})
    validation = blinded_dataset(SpatialDataset("validation", val, ""), [row.cell_id for row in val], features)
    for row in reference.records:
        row.genes = {gene: row.genes.get(gene, 0.0) for gene in features}
    truth_by_id = {row.cell_id: row.cell_type for row in val}
    trials, predictions = [], {}
    for k in protocol["candidate_neighbors"]:
        if k > len(train):
            raise ValueError("Prespecified neighbor count exceeds training cohort size.")
        for power in protocol["candidate_prior_powers"]:
            params = {"n_neighbors": k, "class_prior_power": power}
            rows = _predict(validation, reference, params)
            score = metrics([truth_by_id[row["cell_id"]] for row in rows], rows, protocol["confidence_threshold"])
            trials.append({"params": params, "validation": score})
            predictions[(k, power)] = rows
    winner = max(trials, key=lambda item: (item["validation"]["macro_f1"],
                                         -item["params"]["class_prior_power"], -item["params"]["n_neighbors"]))
    if digest(protocol_path) != protocol_sha256:
        raise ValueError("Development protocol changed during selection.")
    root = _empty_output(output_dir)
    shutil.copyfile(protocol_path, root / "development_protocol.json")
    write_json(root / "validation_results.json", {"selected": winner, "trials": trials})
    write_csv(root / "validation_predictions.csv", predictions[(winner["params"]["n_neighbors"], winner["params"]["class_prior_power"])])
    if (winner["validation"]["macro_f1"] < protocol["minimum_validation_macro_f1"]
            or winner["validation"]["coverage"] < protocol["minimum_validation_coverage"]):
        return {"status": "blocked_development_acceptance_thresholds", "validation": winner["validation"],
                "test_scored": False, "model_locked": False, "protocol_sha256": protocol_sha256}
    write_json(root / "training_reference.json", [{"cell_id": row.cell_id, "expert_label": row.cell_type,
                                                    "genes": row.genes} for row in reference.records])
    lock = {"status": "brain_validation_selected_not_externally_validated", "tool": "reference_label_transfer",
            "params": winner["params"], "confidence_threshold": protocol["confidence_threshold"], "features": features,
            "protocol_sha256": protocol_sha256,
            "reference_decision_sha256": protocol["reference_decision_sha256"],
            "reference_snapshot_sha256": protocol["reference_snapshot_sha256"],
            "development_donor_ids": sorted(set(map(str, donors.values()))), "source_donor_map": donors,
            "selection": "Validation macro-F1 only; lower prior power then smaller k breaks ties",
            "source_matrix_hashes": inputs, "review_hashes": manifest["source_review_hashes"],
            "staging_manifest_sha256": digest(staging / "staging_manifest.json"),
            "training_reference_sha256": digest(root / "training_reference.json"),
            "test_truth_opened": False, "test_scored": False,
            "caveat": "Spatial-block development, not donor-held-out performance. Validation was used for selection; "
                      "vote fractions are not calibrated confidence. Unknown donor identities block external testing."}
    write_json(root / "locked_model.json", lock)
    return dict(lock, model_lock=str((root / "locked_model.json").resolve()),
                model_lock_sha256=digest(root / "locked_model.json"), validation=winner["validation"])


def evaluate_external_once(model_lock, manifest_path, output_dir, custodian_id, expected_lock_sha256):
    """Reserve one attempt before prediction; parse sealed truth only afterwards."""
    lock_path, manifest_path = Path(model_lock).resolve(), Path(manifest_path).resolve()
    if digest(lock_path) != expected_lock_sha256:
        raise ValueError("Custodian release must name the exact locked model hash.")
    external = validate_external_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    lock = json.loads(lock_path.read_text())
    if lock["status"] != "brain_validation_selected_not_externally_validated":
        raise ValueError("Only the reviewed brain model selection can be externally tested.")
    if lock.get("protocol_sha256") and digest(lock_path.parent / "development_protocol.json") != lock["protocol_sha256"]:
        raise ValueError("Frozen development protocol changed.")
    if not custodian_id.strip() or custodian_id != manifest["custodian_id"]:
        raise ValueError("Release requires the recorded independent custodian.")
    if not lock["development_donor_ids"] or set(lock["development_donor_ids"]) != set(manifest["development_donor_ids"]):
        raise ValueError("Development donor identity is missing or differs from the sealed manifest.")
    protocol = json.loads((manifest_path.parent / manifest["evaluation_protocol"]).read_text())
    if protocol.get("model_lock_sha256") != expected_lock_sha256 or protocol.get("confidence_threshold") != lock["confidence_threshold"]:
        raise ValueError("The hashed protocol must prespecify this exact model and confidence threshold.")
    reference_path = lock_path.parent / "training_reference.json"
    if digest(reference_path) != lock["training_reference_sha256"]:
        raise ValueError("Frozen training reference changed.")
    with (lock_path.parent / "external_test_attempt.json").open("x") as stream:
        json.dump({"status": "reserved_no_retry", "model_lock_sha256": expected_lock_sha256,
                   "external_manifest_sha256": external["manifest_sha256"], "custodian_id": custodian_id}, stream)
    root = _empty_output(output_dir)
    reference_rows = json.loads(reference_path.read_text())
    reference = SpatialDataset("reference", [SpotRecord("reference", 0, 0, row["expert_label"], row["genes"],
                                 cell_id=row["cell_id"]) for row in reference_rows], "", metadata={"organism": "human"})
    expression = manifest_path.parent / manifest["expression_file"]
    if expression.name == "experiment.xenium" or expression.is_dir():
        source = load_xenium(str(expression), max_records=0, max_features_per_record=0)
    else:
        source = load_scrna(str(expression), max_records=0, keep_features=lock["features"],
                           expression_semantics=manifest.get("expression_semantics", "auto"))
    query = blinded_dataset(source, [row.cell_id for row in source.records], lock["features"])
    query.normalized = source.normalized
    query.metadata["source_value_semantics"] = source.metadata.get("source_value_semantics")
    if len(query.records) != len({row.cell_id for row in query.records}) or not query.records:
        raise ValueError("External expression has missing or duplicate cell IDs.")
    shared = set(source.genes) & set(lock["features"])
    import math
    minimum = protocol.get("min_shared_features")
    fraction = protocol.get("min_shared_fraction")
    if (not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 2
            or not isinstance(fraction, (int, float)) or not math.isfinite(fraction) or not 0 < fraction <= 1):
        raise ValueError("Prespecify min_shared_features >=2 and finite min_shared_fraction in (0,1].")
    if len(shared) < minimum or len(shared) / len(lock["features"]) < fraction:
        raise ValueError("External assay fails the prespecified panel-overlap threshold.")
    predictions = _predict(query, reference, lock["params"])
    write_csv(root / "predictions_before_truth_release.csv", predictions)
    # Neither model fitting nor hyperparameter selection accesses external truth.
    truth_rows = _rows(manifest_path.parent / manifest["truth_file"])
    from spatialmind.contracts.review import review_decision_issues
    if any(review_decision_issues(row) for row in truth_rows):
        raise ValueError("External truth requires explicit independent review evidence.")
    if any(row.get("donor_id") not in manifest["test_donor_ids"] for row in truth_rows):
        raise ValueError("External truth rows must identify their prespecified test donors.")
    with (manifest_path.parent / manifest["label_crosswalk"]).open(newline="") as stream:
        crosswalk_rows = list(csv.DictReader(stream))
    crosswalk = {row["source_label"]: row["target_label"] for row in crosswalk_rows}
    if len(crosswalk) != len(crosswalk_rows) or any(not value for value in crosswalk.values()):
        raise ValueError("Crosswalk source labels must be unique and targets nonempty.")
    truth = {row["cell_id"]: crosswalk[row["expert_label"]] for row in truth_rows}
    if set(truth) != {row["cell_id"] for row in predictions}:
        raise ValueError("External truth must exactly match predictions; no selective dropping.")
    score = metrics([truth[row["cell_id"]] for row in predictions], predictions, lock["confidence_threshold"])
    donors = {row["cell_id"]: row["donor_id"] for row in truth_rows}
    per_donor = {}
    for donor in manifest["test_donor_ids"]:
        rows = [row for row in predictions if donors[row["cell_id"]] == donor]
        if not rows:
            raise ValueError("A prespecified test donor has no matched truth rows.")
        per_donor[donor] = metrics([truth[row["cell_id"]] for row in rows], rows, lock["confidence_threshold"])
    result = {"status": "external_donor_tested_not_population_validated", "metrics": score, "per_donor": per_donor,
              "model_lock_sha256": expected_lock_sha256, "external_manifest_sha256": external["manifest_sha256"],
              "predictions_sha256": digest(root / "predictions_before_truth_release.csv"), "shared_features": len(shared),
              "test_donors": manifest["test_donor_ids"], "custodian_id": custodian_id,
              "caveat": "One-attempt procedural seal, not secure isolation. Few donors do not establish population generalization. "
                        "Cross-assay tests measure transfer, not Xenium spatial segmentation or ROI accuracy."}
    write_json(root / "external_evaluation.json", result)
    return result
