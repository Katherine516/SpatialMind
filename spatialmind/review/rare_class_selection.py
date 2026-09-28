"""Validation-only selection on an existing frozen Xenium annotation benchmark."""

import csv
import html
import json
from collections import Counter
from pathlib import Path

from .annotation_benchmark import digest, metrics, write_csv, write_json
from spatialmind.tools.annotation_priors import reweight_votes


def _truth(path):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = [row["cell_id"] for row in rows]
    if not ids or len(ids) != len(set(ids)) or any(not row["expert_label"].strip() for row in rows):
        raise ValueError("Nonempty uniquely identified reviewed labels are required")
    return rows


def select_rare_class_policy(benchmark_dir, matrix_path, output_dir):
    import h5py
    import numpy as np
    from scipy.sparse import csc_matrix
    from sklearn.neighbors import KNeighborsClassifier

    source, root, matrix_path = Path(benchmark_dir), Path(output_dir), Path(matrix_path).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a new empty output directory; selection artifacts cannot be overwritten")
    hashes = json.loads((source / "artifact_hashes.json").read_text())
    names = ["protocol.json", "split_manifest.csv", "evaluator_only/train_truth.csv", "evaluator_only/validation_truth.csv"]
    for name in names:
        if digest(source / name) != hashes.get(name):
            raise ValueError("Frozen development artifact changed: " + name)
    protocol = json.loads((source / "protocol.json").read_text())
    if digest(matrix_path) != protocol["source_hashes"].get(str(matrix_path)):
        raise ValueError("Expression matrix differs from the frozen source")
    train = _truth(source / names[2])
    validation = _truth(source / names[3])
    with (source / "split_manifest.csv").open(newline="") as stream:
        split_rows = list(csv.DictReader(stream))
    split = {row["cell_id"]: row for row in split_rows}
    if len(split) != len(split_rows):
        raise ValueError("Duplicate split IDs")
    for group, rows in (("train", train), ("validation", validation)):
        if any(split.get(row["cell_id"], {}).get("split") != group
               or str(split[row["cell_id"]]["included"]).lower() != "true" for row in rows):
            raise ValueError("Development truth violates frozen split or buffer")
    blocks = [{split[row["cell_id"]]["block"] for row in rows} for rows in (train, validation)]
    if blocks[0] & blocks[1]:
        raise ValueError("Training and validation blocks overlap")
    features = protocol["features"]
    if len(features) != len(set(features)):
        raise ValueError("Duplicated feature names")
    with h5py.File(matrix_path, "r") as handle:
        group = handle["matrix"]
        decode = lambda value: value.decode() if isinstance(value, bytes) else str(value)
        genes = [decode(x).upper() for x in group["features/name"][:]]
        cells = [decode(x) for x in group["barcodes"][:]]
        if len(cells) != len(set(cells)) or len(genes) != len(set(genes)):
            raise ValueError("Ambiguous matrix feature or cell IDs")
        gene_index, cell_index = {x: i for i, x in enumerate(genes)}, {x: i for i, x in enumerate(cells)}
        expression = csc_matrix((group["data"][:], group["indices"][:], group["indptr"][:]), shape=tuple(group["shape"][:]))
    def matrix(rows):
        values = expression[:, [cell_index[row["cell_id"]] for row in rows]][[gene_index[g] for g in features], :].T.toarray().astype(float)
        if not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError("Expected finite nonnegative counts")
        return np.log1p(values / np.maximum(values.sum(axis=1, keepdims=True), 1) * 1e4)
    x_train, x_val = matrix(train), matrix(validation)
    y_train, y_val = [r["expert_label"] for r in train], [r["expert_label"] for r in validation]
    counts = Counter(y_train)
    if len(counts) < 2 or len(train) < 15:
        raise ValueError("At least two training classes and 15 training cells are required")
    rare = sorted(label for label, count in counts.items() if count < 100)
    root.mkdir(parents=True, exist_ok=True)
    selection_protocol = {
        "scope": "internal_development_validation_only_not_external_or_brain_validation",
        "candidate_prior_powers": [0.0, 0.25, 0.5, 1.0], "n_neighbors": 15,
        "selection": "highest validation macro-F1; lower prior power breaks ties",
        "rare_definition": "fewer than 100 cells in training only", "rare_classes": rare,
        "confidence_threshold": 0.6, "features": features,
        "source_matrix": str(matrix_path), "matrix_sha256": digest(matrix_path),
        "development_hashes": {name: hashes[name] for name in names},
        "test_truth_opened": False, "test_scored": False,
    }
    write_json(root / "selection_protocol.json", selection_protocol)
    classifier = KNeighborsClassifier(n_neighbors=15, weights="distance")
    print("Fitting training cells and predicting validation once; no test labels opened.", flush=True)
    classifier.fit(x_train, y_train)
    base = classifier.predict_proba(x_val)
    trials, predictions = [], {}
    for power in selection_protocol["candidate_prior_powers"]:
        votes = reweight_votes(base, classifier.classes_, y_train, power)
        rows = [{"cell_id": row["cell_id"], "predicted_label": str(classifier.classes_[np.argmax(votes[i])]),
                 "confidence": round(float(votes[i].max()), 4)} for i, row in enumerate(validation)]
        score = metrics(y_val, rows)
        rare_scores = [row["f1"] for row in score["per_class"] if row["label"] in rare and row["support"] > 0]
        score["rare_macro_f1_supported_in_validation"] = float(np.mean(rare_scores)) if rare_scores else None
        score["rare_classes_absent_from_validation"] = sorted(set(rare) - set(y_val))
        trials.append({"class_prior_power": power, "validation": score})
        predictions[power] = rows
    winner = max(trials, key=lambda trial: (trial["validation"]["macro_f1"], -trial["class_prior_power"]))
    lock = {"tool": "reference_label_transfer", "params": {"n_neighbors": 15, "class_prior_power": winner["class_prior_power"]},
            "reference": "Only the frozen training IDs/labels and expression features in selection_protocol.json",
            "protocol_sha256": digest(root / "selection_protocol.json"),
            "status": "validation_selected_not_promoted_no_external_test", "requires_expert_review": True}
    write_json(root / "locked_selection.json", lock)
    write_json(root / "validation_results.json", {"selected": winner, "trials": trials})
    write_csv(root / "validation_predictions.csv", predictions[winner["class_prior_power"]])
    write_csv(root / "selected_per_class.csv", winner["validation"]["per_class"])
    table = "".join("<tr><td>%.2f</td><td>%.4f</td><td>%.4f</td><td>%s</td></tr>" % (
        row["class_prior_power"], row["validation"]["accuracy"], row["validation"]["macro_f1"],
        ("%.4f" % row["validation"]["rare_macro_f1_supported_in_validation"]
         if row["validation"]["rare_macro_f1_supported_in_validation"] is not None else "N/A")) for row in trials)
    (root / "report.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Rare-class development experiment</title>'
        '<style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:16px}td,th{padding:10px;border-bottom:1px solid #ccc;text-align:left}</style>'
        '<h1>Rare-class development experiment</h1><p>Internal breast-section validation only. Not brain validation, '
        'not an external test, and not a production model promotion.</p>'
        '<p>Training: %d cells. Validation: %d cells. Selected prior power: %.2f.</p>' % (len(train), len(validation), winner["class_prior_power"])
        + '<table><tr><th>Prior power</th><th>Accuracy</th><th>Macro-F1</th><th>Rare-class macro-F1</th></tr>' + table + '</table>'
        + '<p>Rare classes are defined by training support &lt;100; absent validation classes are not estimable. '
        'Hyperparameters were selected on this validation set, so these are optimistic selection metrics, not unbiased accuracy estimates. '
        'Adjusted vote fractions are not calibrated confidence. No test was evaluated.</p><p>Rare classes: '
        + html.escape(", ".join(rare)) + '</p></html>')
    write_json(root / "artifact_hashes.json", {p.name: digest(p) for p in root.iterdir() if p.is_file()})
    return {"selected_power": winner["class_prior_power"], "baseline": trials[0]["validation"], "selected": winner["validation"], "status": lock["status"]}
