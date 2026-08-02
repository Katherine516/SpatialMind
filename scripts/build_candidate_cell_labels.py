"""Produce candidate cell labels for expert review.

Two supported routes:

1. Reference transfer (``--reference``): k-nearest-neighbour transfer from a
   labelled scRNA reference (``.h5ad`` or tabular) onto the Xenium target.
2. Marker evidence only (no ``--reference``): the loader's conservative
   marker-rule labels plus per-cell marker evidence.

Both routes write ``expert_cell_labels_candidate.csv``, which is a REVIEW DRAFT.
It is not an expert label file. A reviewer must check the rows, correct them,
fill ``reviewer_id``, and save the result as ``expert_cell_labels.csv`` inside
the Xenium output folder before the validated pilot will use it.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.ingestion import load_scrna, load_xenium
from spatialmind.ingestion.labels import MARKER_EVIDENCE_FEATURES, NON_BIOLOGICAL_FEATURES
from spatialmind.tools.exceptions import MissingPreconditionError
from spatialmind.tools.implementations import reference_label_transfer

CANDIDATE_FIELDS = [
    "cell_id",
    "x",
    "y",
    "candidate_label",
    "candidate_source",
    "confidence",
    "marker_evidence",
    "top_features",
    "expert_label",
    "reviewer_id",
    "review_status",
    "notes",
]


def _marker_evidence(genes):
    values = []
    for marker in MARKER_EVIDENCE_FEATURES:
        value = genes.get(marker)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            values.append("%s=%.3g" % (marker, numeric))
    return ";".join(values)


def _top_features(genes, limit=8):
    pairs = []
    for name, value in genes.items():
        if name in NON_BIOLOGICAL_FEATURES:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            pairs.append((numeric, name))
    pairs.sort(reverse=True)
    return ";".join("%s=%.3g" % (name, value) for value, name in pairs[:limit])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build candidate cell labels for expert review.")
    parser.add_argument("--data", required=True, help="Xenium output directory or experiment.xenium file.")
    parser.add_argument("--out", default="outputs/candidate_labels", help="Output directory.")
    parser.add_argument("--reference", default=None, help="Labelled reference (.h5ad or .csv) for KNN transfer.")
    parser.add_argument("--max-records", type=int, default=2500)
    parser.add_argument("--n-neighbors", type=int, default=15)
    parser.add_argument("--min-shared-features", type=int, default=20)
    parser.add_argument("--confidence-threshold", type=float, default=0.6)
    parser.add_argument("--reference-max-records", type=int, default=5000, help="Reference cells sampled for KNN.")
    parser.add_argument("--allow-cross-species", action="store_true", help="Only for pre-mapped orthologs.")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dataset = load_xenium(args.data, max_records=args.max_records)

    predictions = {}
    summary = {
        "dataset_path": args.data,
        "records_loaded": len(dataset.records),
        "features_loaded": len(dataset.genes),
        "reference_path": args.reference,
    }

    if args.reference:
        reference = load_scrna(args.reference, max_records=args.reference_max_records)
        reference_labels = sorted({record.cell_type for record in reference.records if record.cell_type})
        try:
            result = reference_label_transfer(
                dataset,
                {
                    "reference_dataset": reference,
                    "min_shared_features": args.min_shared_features,
                    "n_neighbors": args.n_neighbors,
                    "confidence_threshold": args.confidence_threshold,
                    "allow_cross_species": args.allow_cross_species,
                },
            )
        except MissingPreconditionError as exc:
            # A refusal is a valid outcome, not a crash. Report it cleanly so the
            # user sees what to fix instead of a stack trace.
            blocked = {
                "status": "blocked_unusable_reference",
                "dataset_path": args.data,
                "reference_path": args.reference,
                "reference_organism": reference.metadata.get("organism", ""),
                "target_organism": dataset.metadata.get("organism", ""),
                "reference_label_classes": reference_labels,
                "reason": str(exc),
                "no_candidate_file_written": True,
            }
            (out / "candidate_label_summary.json").write_text(
                json.dumps(blocked, indent=2, sort_keys=True), encoding="utf-8"
            )
            print("BLOCKED: %s" % exc)
            print("\nNo candidate label file was written. Summary: %s" % (out / "candidate_label_summary.json"))
            return
        predictions = {item["cell_id"]: item for item in result.metrics.get("predictions", [])}
        summary.update(
            {
                "candidate_source": "reference_transfer",
                "reference_cell_count": result.metrics.get("reference_cell_count"),
                "reference_label_classes": reference_labels,
                "shared_feature_count": result.metrics.get("shared_feature_count"),
                "mean_transfer_confidence": result.metrics.get("mean_transfer_confidence"),
                "low_confidence_cell_count": result.metrics.get("low_confidence_cell_count"),
                "predicted_label_counts": result.metrics.get("predicted_label_counts"),
                "tool_summary": result.summary,
                "caveats": result.caveats,
            }
        )
    else:
        summary.update(
            {
                "candidate_source": "marker_rule_weak_labels",
                "caveats": [
                    "Marker-rule labels are weak heuristics, not reference predictions.",
                    "They exist to prioritise review, not to stand in for expert annotation.",
                ],
            }
        )

    candidate_path = out / "expert_cell_labels_candidate.csv"
    with candidate_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        for index, record in enumerate(dataset.records):
            cell_id = record.cell_id or str(index)
            prediction = predictions.get(cell_id)
            writer.writerow(
                {
                    "cell_id": cell_id,
                    "x": "%.4f" % record.x,
                    "y": "%.4f" % record.y,
                    "candidate_label": (prediction or {}).get("predicted_label", record.cell_type or ""),
                    "candidate_source": summary["candidate_source"],
                    "confidence": (prediction or {}).get("confidence", ""),
                    "marker_evidence": _marker_evidence(record.genes),
                    "top_features": _top_features(record.genes),
                    "expert_label": "",
                    "reviewer_id": "",
                    "review_status": "needs_expert_review",
                    "notes": "",
                }
            )

    summary["candidate_csv"] = str(candidate_path)
    summary["candidate_label_counts"] = dict(
        Counter(
            (predictions.get(record.cell_id or str(index), {}) or {}).get("predicted_label", record.cell_type or "")
            for index, record in enumerate(dataset.records)
        )
    )
    summary["status"] = "awaiting_expert_review"
    summary["important_boundary"] = (
        "This file is a review draft. Candidate labels are predictions or heuristics, never expert truth. "
        "Complete expert_label and reviewer_id, then save as expert_cell_labels.csv in the Xenium folder."
    )
    (out / "candidate_label_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True)[:2000])


if __name__ == "__main__":
    main()
