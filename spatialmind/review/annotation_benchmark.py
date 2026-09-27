"""Label-blind, spatially held-out evaluation of the production transfer tool."""

import csv
import hashlib
import html
import json
from collections import Counter
from pathlib import Path

from spatialmind.ingestion import load_xenium
from spatialmind.schemas import SpatialDataset, SpotRecord, expression_feature_names
from spatialmind.tools.implementations import reference_label_transfer


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def write_csv(path, rows):
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["cell_id"])
        writer.writeheader()
        writer.writerows(rows)


def spatial_split(records, bins=6, buffer_um=50.0, seed=42):
    """Split whole coordinate blocks before looking at labels; buffer all split pairs."""
    import numpy as np
    from scipy.spatial import cKDTree

    if bins < 3 or buffer_um < 0:
        raise ValueError("At least three bins per axis and a nonnegative buffer are required.")
    ids = [record.cell_id for record in records]
    if not records or not all(ids) or len(set(ids)) != len(ids):
        raise ValueError("Nonempty records with unique cell IDs are required.")
    xy = np.asarray([(record.x, record.y) for record in records], dtype=float)
    if not np.isfinite(xy).all():
        raise ValueError("Coordinates must be finite.")
    extent = np.maximum(np.ptp(xy, axis=0), 1.0)
    tile = np.minimum(((xy - xy.min(axis=0)) / extent * bins).astype(int), bins - 1)
    units = ["x%d_y%d" % tuple(value) for value in tile]
    unique = sorted(set(units), key=lambda unit: hashlib.sha256((str(seed) + unit).encode()).hexdigest())
    if len(unique) < 6:
        raise ValueError("At least six occupied blocks are required.")
    n_holdout = max(2, len(unique) // 5)
    assignments = dict(zip(unique, ["test"] * n_holdout + ["validation"] * n_holdout
                           + ["train"] * (len(unique) - 2 * n_holdout)))
    names = np.asarray([assignments[unit] for unit in units])
    nearest = np.zeros(len(records))
    for split in ("train", "validation", "test"):
        mask = names == split
        nearest[mask] = cKDTree(xy[~mask]).query(xy[mask], k=1)[0]
    return [{"cell_id": record.cell_id, "block": units[i], "split": str(names[i]),
             "included": bool(nearest[i] >= buffer_um),
             "nearest_other_split_um": float(nearest[i]), "x": record.x, "y": record.y}
            for i, record in enumerate(records)]


def blinded_dataset(dataset, ids, features, labels=None):
    """Construct a fresh expression-only input, never copy source metadata or labels."""
    selected = set(ids)
    records = []
    for record in dataset.records:
        if record.cell_id not in selected:
            continue
        counts = record.raw_genes or record.genes
        genes = {gene: float(counts.get(gene, 0.0)) for gene in features}
        records.append(SpotRecord(sample_id="benchmark", x=0.0, y=0.0,
                                  cell_id=record.cell_id, genes=genes,
                                  cell_type=(labels or {}).get(record.cell_id, "")))
    return SpatialDataset(sample_id="benchmark", records=records, source_path="",
                          metadata={"organism": dataset.metadata.get("organism", "")})


def predict(query, reference, k):
    if any(record.cell_type or record.region for record in query.records):
        raise ValueError("Prediction queries must be label- and region-blind.")
    if set(r.cell_id for r in query.records) & set(r.cell_id for r in reference.records):
        raise ValueError("Reference and query cell IDs overlap.")
    return reference_label_transfer(query, {
        "reference_dataset": reference, "n_neighbors": k, "min_shared_features": 2,
        # Missing classes are measured as failures, not silently removed from evaluation.
        "allow_incomplete_reference": True,
    }).metrics["predictions"]


def metrics(truth, predictions, threshold=0.6):
    import numpy as np
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support

    if not truth or len(truth) != len(predictions):
        raise ValueError("Truth and predictions must have the same nonzero length.")
    names = sorted(set(truth) | {row["predicted_label"] for row in predictions})
    raw = [row["predicted_label"] for row in predictions]
    accepted = [float(row["confidence"]) >= threshold for row in predictions]
    output = [label if keep else "__abstain__" for label, keep in zip(raw, accepted)]
    precision, recall, f1, support = precision_recall_fscore_support(
        truth, raw, labels=names, zero_division=0)
    _, _, abstain_f1, _ = precision_recall_fscore_support(truth, output, labels=names, zero_division=0)
    selected = [index for index, keep in enumerate(accepted) if keep]
    present = support > 0
    return {
        "n_cells": len(truth), "accuracy": float(accuracy_score(truth, raw)),
        "macro_f1": float(np.mean(f1)),
        "balanced_accuracy": float(np.mean(recall[present])),
        "weighted_f1": float(np.average(f1, weights=support)),
        "coverage": len(selected) / len(truth), "abstention_rate": 1 - len(selected) / len(truth),
        "selective_accuracy": (sum(truth[i] == raw[i] for i in selected) / len(selected) if selected else None),
        "macro_f1_with_abstention": float(np.mean(abstain_f1)),
        "per_class": [{"label": name, "support": int(support[i]), "precision": float(precision[i]),
                       "recall": float(recall[i]), "f1": float(f1[i])} for i, name in enumerate(names)],
    }


def block_interval(truth, predictions, blocks, seed=42, repeats=200):
    """Within-section block bootstrap; does not estimate between-donor uncertainty."""
    import numpy as np
    from sklearn.metrics import accuracy_score, f1_score

    unique = sorted(set(blocks))
    if len(unique) < 2:
        return {"status": "unavailable", "reason": "Fewer than two test blocks"}
    indices = {block: [i for i, name in enumerate(blocks) if name == block] for block in unique}
    labels = sorted(set(truth) | {row["predicted_label"] for row in predictions})
    rng = np.random.RandomState(seed)
    values = []
    for _ in range(repeats):
        chosen = [i for block in rng.choice(unique, len(unique), replace=True) for i in indices[block]]
        y = [truth[i] for i in chosen]
        p = [predictions[i]["predicted_label"] for i in chosen]
        values.append([accuracy_score(y, p), f1_score(y, p, labels=labels, average="macro", zero_division=0)])
    bounds = np.percentile(values, [2.5, 97.5], axis=0)
    return {"status": "computed", "unit": "spatial_block_within_one_section", "blocks": len(unique),
            "repeats": repeats, "accuracy_95_percentile": bounds[:, 0].tolist(),
            "macro_f1_95_percentile": bounds[:, 1].tolist()}


def run_annotation_benchmark(dataset_path, output_dir, max_records=20000, bins=6, buffer_um=50.0, seed=42):
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a new empty output directory; frozen benchmark artifacts are never overwritten.")
    if max_records < 100:
        raise ValueError("Use at least 100 input cells.")
    source = Path(dataset_path).resolve()
    required = [source / "expert_cell_labels.csv", source / "cell_feature_matrix.h5"]
    required += [path for path in (source / "cells.csv.gz", source / "cells.csv", source / "experiment.xenium") if path.exists()]
    hashes = {str(path): digest(path) for path in required}
    dataset = load_xenium(str(source), max_records=max_records, max_features_per_record=0)
    if dataset.coordinate_system not in {"micron", "microns", "micrometer", "um"}:
        raise ValueError("Spatial buffer requires verified micron coordinates: %s" % dataset.coordinate_system)
    splits = spatial_split(dataset.records, bins, buffer_um, seed)
    with (source / "expert_cell_labels.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = [row["cell_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate cell IDs in truth table.")
    truth = {row["cell_id"]: row["expert_label"].strip() for row in rows
             if row.get("expert_label", "").strip() and row.get("reviewer_id", "").strip()}
    groups = {split: [row["cell_id"] for row in splits if row["included"] and row["split"] == split
                      and row["cell_id"] in truth] for split in ("train", "validation", "test")}
    if any(len(value) < 30 for value in groups.values()):
        raise ValueError("Each split needs at least 30 labeled cells after buffering.")
    # Features are fixed by the training expression, not chosen from test associations.
    train_ids = set(groups["train"])
    train_source = SpatialDataset("train", [r for r in dataset.records if r.cell_id in train_ids], "",
                                  metadata={"control_features": dataset.metadata.get("control_features", [])})
    features = expression_feature_names(train_source)
    reference = blinded_dataset(dataset, groups["train"], features, {key: truth[key] for key in groups["train"]})
    if len(reference.cell_types) < 2:
        raise ValueError("Training split needs at least two classes.")
    root.mkdir(parents=True, exist_ok=True)
    policy = {"status": "internal_spatial_holdout_not_independent_donor_validation", "source_hashes": hashes,
              "seed": seed, "max_records": max_records, "bins": bins, "buffer_um": buffer_um,
              "features": features, "candidate_k": [5, 15], "confidence_threshold": 0.6,
              "selection": "highest validation macro-F1; smaller k breaks ties; no test tuning",
              "split_counts": {key: len(value) for key, value in groups.items()},
              "buffer_excluded": sum(not row["included"] for row in splits),
              "unlabeled_retained_not_scored": sum(row["included"] and row["cell_id"] not in truth for row in splits),
              "retained_cells": len(dataset.records)}
    write_csv(root / "split_manifest.csv", splits)
    write_json(root / "protocol.json", policy)
    vault = root / "evaluator_only"
    vault.mkdir()
    for split, values in groups.items():
        write_csv(vault / (split + "_truth.csv"), [{"cell_id": key, "expert_label": truth[key]} for key in values])
    validation = blinded_dataset(dataset, groups["validation"], features)
    val_truth = [truth[r.cell_id] for r in validation.records]
    trials = []
    for k in policy["candidate_k"]:
        print("Validation transfer k=%d (%d train, %d validation cells)" % (k, len(reference.records), len(val_truth)), flush=True)
        scores = metrics(val_truth, predict(validation, reference, k))
        trials.append({"k": k, "metrics": scores})
    winner = max(trials, key=lambda trial: (trial["metrics"]["macro_f1"], -trial["k"]))
    write_json(root / "locked_model_selection.json", {"k": winner["k"], "trials": trials})
    query = blinded_dataset(dataset, groups["test"], features)
    print("Locked k=%d; predicting test cells without labels" % winner["k"], flush=True)
    predictions = predict(query, reference, winner["k"])
    write_csv(root / "test_predictions.csv", predictions)
    y = [truth[record.cell_id] for record in query.records]
    block_by_id = {row["cell_id"]: row["block"] for row in splits}
    scores = metrics(y, predictions)
    majority = Counter(record.cell_type for record in reference.records).most_common(1)[0][0]
    baseline = metrics(y, [{"predicted_label": majority, "confidence": 1.0} for _ in y])
    unknown = sorted(set(y) - set(reference.cell_types))
    partition_ids = {key: set(values) for key, values in groups.items()}
    partition_blocks = {key: {row["block"] for row in splits if row["cell_id"] in partition_ids[key]}
                        for key in groups}
    pairs = [("train", "validation"), ("train", "test"), ("validation", "test")]
    id_overlap = sum(len(partition_ids[a] & partition_ids[b]) for a, b in pairs)
    block_overlap = sum(len(partition_blocks[a] & partition_blocks[b]) for a, b in pairs)
    if id_overlap or block_overlap:
        raise RuntimeError("Split leakage detected.")
    report = {"protocol": policy, "selected_k": winner["k"], "test": scores,
              "majority_train_baseline": baseline,
              "test_classes_absent_from_training": unknown,
              "unsupported_test_cells": sum(label in unknown for label in y),
              "block_bootstrap": block_interval(y, predictions, [block_by_id[r.cell_id] for r in query.records], seed),
              "leakage_checks": {"overlapping_cell_ids": id_overlap, "overlapping_spatial_blocks": block_overlap,
                                 "prediction_label_metadata_present": any(r.cell_type or r.region for r in query.records)
                                 or any(key != "organism" for key in query.metadata), "test_used_for_selection": False},
              "limitations": ["One section, one donor: not external or condition-level validation.",
                              "Published labels may include expression-assisted annotation; not independent assay truth.",
                              "Spatial blocks and a buffer reduce adjacency leakage but do not remove section-level dependence.",
                              "Vote fractions are not calibrated confidence; abstention threshold is fixed at 0.6.",
                              "Only cells with published labels are scored; unlabeled cells are not an evaluated unknown class.",
                              "The evaluator-only folder is a logical separation, not an access-control sandbox."]}
    if any(digest(path) != value for path, value in hashes.items()):
        raise RuntimeError("Source inputs changed during benchmark; results must not be accepted.")
    write_json(root / "evaluation.json", report)
    write_csv(root / "per_class_metrics.csv", scores["per_class"])
    _figures(root, y, predictions, splits)
    _report(root, report)
    artifacts = sorted(path for path in root.rglob("*") if path.is_file())
    write_json(root / "artifact_hashes.json", {str(path.relative_to(root)): digest(path) for path in artifacts})
    return report


def _figures(root, truth, predictions, splits):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from sklearn.metrics import confusion_matrix

    labels = sorted(set(truth) | {p["predicted_label"] for p in predictions})
    matrix = confusion_matrix(truth, [p["predicted_label"] for p in predictions], labels=labels)
    normalized = matrix / np.maximum(matrix.sum(axis=1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(normalized, vmin=0, vmax=1, cmap="viridis")
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=90, fontsize=8)
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels, fontsize=8)
    ax.set(xlabel="Predicted label", ylabel="Published label", title="Held-out test: row-normalized confusion")
    fig.colorbar(im, ax=ax, label="Fraction of true class")
    fig.tight_layout(); fig.savefig(root / "confusion_matrix.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 8))
    for split, color in (("train", "#287c8e"), ("validation", "#bd4d72"), ("test", "#649431"), ("buffer", "#c7c7c7")):
        rows = [r for r in splits if (r["included"] and r["split"] == split) or (not r["included"] and split == "buffer")]
        ax.scatter([r["x"] for r in rows], [r["y"] for r in rows], s=1, color=color, label=split, rasterized=True)
    ax.set(xlabel="x (microns)", ylabel="y (microns)", title="Frozen spatial split; gray cells excluded by buffer")
    ax.set_aspect("equal"); ax.invert_yaxis(); ax.legend(markerscale=5)
    fig.tight_layout(); fig.savefig(root / "spatial_split.png", dpi=150); plt.close(fig)


def _report(root, report):
    scores = report["test"]
    rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (html.escape(key), html.escape(str(value)))
                   for key, value in scores.items() if key != "per_class")
    limitations = "".join("<li>%s</li>" % html.escape(value) for value in report["limitations"])
    content = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>SpatialMind held-out annotation benchmark</title><style>
body{font:16px/1.6 system-ui;margin:32px auto;padding:0 20px;max-width:1050px;color:#222}table{border-collapse:collapse;width:100%%}
td{padding:7px;border-bottom:1px solid #ccc}img{max-width:100%%}h1{font-size:28px}</style>
<h1>Held-out Annotation Benchmark</h1><p><strong>Internal spatial holdout. Not independent donor validation.</strong></p>
<p>Existing distance-weighted reference transfer; k=%d selected on validation only. Test labels and regions were absent from predictor inputs.</p>
<p>Train/validation/test: %s. Spatial buffer: %g microns. Confidence threshold: 0.6 (uncalibrated vote fraction).</p>
<h2>Test Metrics</h2><table>%s</table><p>Training-majority baseline accuracy: %.4f; macro-F1: %.4f.</p>
<h2>Uncertainty</h2><pre>%s</pre><h2>Split and Errors</h2><img src="spatial_split.png" alt="Spatial split map">
<img src="confusion_matrix.png" alt="Row normalized confusion matrix"><h2>Interpretation Limits</h2><ul>%s</ul>
<p><a href="evaluation.json">Full metrics</a> | <a href="per_class_metrics.csv">Per-class metrics</a> | <a href="protocol.json">Frozen protocol</a></p></html>""" % (
        report["selected_k"], html.escape(str(report["protocol"]["split_counts"])), report["protocol"]["buffer_um"], rows,
        report["majority_train_baseline"]["accuracy"], report["majority_train_baseline"]["macro_f1"],
        html.escape(json.dumps(report["block_bootstrap"], indent=2)), limitations)
    (root / "report.html").write_text(content)
