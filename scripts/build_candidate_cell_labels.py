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

from spatialmind.ingestion import load_scrna_reference_set, load_xenium
from spatialmind.ingestion.labels import MARKER_EVIDENCE_FEATURES, NON_BIOLOGICAL_FEATURES
from spatialmind.tools.exceptions import MissingPreconditionError
from spatialmind.tools.implementations import (
    assess_reference_lineage_coverage,
    describe_lineage_coverage,
    lineage_for_label,
    reference_label_transfer,
)

CANDIDATE_FIELDS = [
    "cell_id",
    "x",
    "y",
    "candidate_label",
    "candidate_source",
    "confidence",
    "distant_from_reference",
    "marker_lineage",
    "marker_disagreement",
    "lineage_absent_from_reference",
    "review_priority",
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


def _h5ad_header(path):
    """Read organism, cell classes, and gene symbols from an h5ad header only.

    Deliberately avoids loading the expression matrix so a multi-gigabyte
    reference can be screened in seconds before committing to a full run.
    """
    import h5py

    def text(value):
        return value.decode() if isinstance(value, bytes) else str(value)

    with h5py.File(path, "r") as handle:
        organism = ""
        for key in ("organism", "organism_ontology_term_id"):
            if key in handle.get("uns", {}):
                try:
                    organism = text(handle["uns"][key][()])
                    break
                except Exception:
                    continue
        classes = []
        if "obs" in handle and "cell_type" in handle["obs"]:
            node = handle["obs"]["cell_type"]
            if isinstance(node, h5py.Group) and "categories" in node:
                classes = [text(value) for value in node["categories"][:]]
        genes = []
        if "var" in handle:
            for column in ("feature_name", "gene_symbols", "_index"):
                if column not in handle["var"]:
                    continue
                node = handle["var"][column]
                try:
                    values = node["categories"][:] if isinstance(node, h5py.Group) else node[:]
                except Exception:
                    continue
                genes = [text(value) for value in values]
                if genes and not genes[0].upper().startswith("ENS"):
                    break
        shape = None
        if "X" in handle and isinstance(handle["X"], h5py.Group):
            shape = list(handle["X"].attrs.get("shape", []))
    return {"organism": organism, "classes": classes, "genes": genes, "shape": shape}


def _inspect_references(args) -> bool:
    # Larger than the panel check needs, because the lineage-coverage check below
    # counts cells per lineage: a 300-cell sample leaves minor populations under
    # the evidence floor and reports a missing lineage as absent.
    target = load_xenium(args.data, max_records=min(args.max_records, 3000))
    panel = {gene.upper() for gene in target.genes}
    target_organism = str(target.metadata.get("organism") or "").strip()
    print("TARGET   %s" % args.data)
    print("         organism=%s  panel_genes=%d  cells_sampled=%d\n"
          % (target_organism or "unknown", len(panel), len(target.records)))

    all_classes, organisms, ok = set(), set(), True
    for path in args.reference:
        try:
            header = _h5ad_header(path)
        except Exception as exc:
            print("REFERENCE %s\n         UNREADABLE: %s\n" % (path, exc))
            ok = False
            continue
        genes = {gene.upper() for gene in header["genes"]}
        overlap = len(genes & panel)
        all_classes.update(header["classes"])
        if header["organism"]:
            organisms.add(header["organism"].strip().lower())
        print("REFERENCE %s" % path)
        print("         organism=%s  cells=%s  classes=%d  panel_overlap=%d"
              % (header["organism"] or "unknown",
                 header["shape"][0] if header["shape"] else "?",
                 len(header["classes"]), overlap))
        if header["classes"]:
            print("         classes: %s" % ", ".join(header["classes"][:6]) + (" ..." if len(header["classes"]) > 6 else ""))
        print()

    print("=" * 62)
    verdict = []
    if target_organism and organisms and {target_organism.lower()} != organisms:
        known = {"human": {"human", "homo sapiens"}, "mouse": {"mouse", "mus musculus"}}
        target_key = next((k for k, v in known.items() if target_organism.lower() in v), target_organism.lower())
        ref_keys = {next((k for k, v in known.items() if o in v), o) for o in organisms}
        if ref_keys != {target_key}:
            verdict.append("BLOCKED: species mismatch (target=%s, reference=%s)" % (target_key, ", ".join(sorted(ref_keys))))
            ok = False
    if len(all_classes) < 2:
        verdict.append("BLOCKED: %d cell class(es) across all references; KNN needs at least 2. "
                       "Supply more files via --reference a.h5ad b.h5ad ..." % len(all_classes))
        ok = False

    # Panel overlap says the two datasets share genes. It says nothing about
    # whether the reference can *name* what is in this tissue, which is the
    # failure the vote fraction cannot express.
    reference_lineages = {lineage_for_label(label) for label in all_classes}
    reference_lineages.discard("")
    coverage = assess_reference_lineage_coverage(target, reference_lineages)
    print("LINEAGE COVERAGE")
    print("         reference names : %s" % (", ".join(sorted(reference_lineages)) or "no recognised lineage"))
    detected = coverage["target_lineage_counts"]
    print("         target detected : %s" % (", ".join("%s=%d" % item for item in detected.items()) or "none"))
    print("         %s" % describe_lineage_coverage(coverage))
    print()
    if coverage["status"] == "inadequate":
        verdict.append(
            "BLOCKED: reference cannot name %d lineage(s) present in this tissue (%s). "
            "Add reference classes covering them, or pass allow_incomplete_reference=True to transfer anyway."
            % (len(coverage["uncovered_lineages"]), ", ".join(coverage["uncovered_lineages"]))
        )
        ok = False
    elif coverage["status"] == "partial":
        verdict.append(
            "WARNING: reference cannot name %s; those cells will still be labelled, at high confidence."
            % ", ".join(coverage["uncovered_lineages"])
        )

    if ok:
        verdict.append("USABLE: %d combined cell classes." % len(all_classes))
    for line in verdict:
        print(line)
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Build candidate cell labels for expert review.")
    parser.add_argument("--data", required=True, help="Xenium output directory or experiment.xenium file.")
    parser.add_argument("--out", default="outputs/candidate_labels", help="Output directory.")
    parser.add_argument("--reference", nargs="+", default=None,
                        help="One or more labelled references (.h5ad/.csv). Multiple files are combined, "
                             "which is required for atlases split one cell class per file.")
    parser.add_argument("--inspect", action="store_true",
                        help="Preflight only: report organism, classes, and panel overlap; write nothing.")
    parser.add_argument("--max-records", type=int, default=2500)
    parser.add_argument("--n-neighbors", type=int, default=15)
    parser.add_argument("--min-shared-features", type=int, default=20)
    parser.add_argument("--confidence-threshold", type=float, default=0.6)
    parser.add_argument("--reference-max-records", type=int, default=5000, help="Reference cells sampled for KNN.")
    parser.add_argument("--allow-cross-species", action="store_true", help="Only for pre-mapped orthologs.")
    parser.add_argument(
        "--allow-incomplete-reference",
        action="store_true",
        help="Transfer even when the reference has no class for lineages present in the target. Those cells "
             "still get a label, so review the lineage_absent_from_reference flags.",
    )
    args = parser.parse_args()

    if args.inspect:
        if not args.reference:
            parser.error("--inspect requires --reference")
        sys.exit(0 if _inspect_references(args) else 1)

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
        reference = load_scrna_reference_set(args.reference, max_records_per_file=args.reference_max_records)
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
                    "allow_incomplete_reference": args.allow_incomplete_reference,
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
                "high_review_priority_count": result.metrics.get("high_review_priority_count"),
                "marker_disagreement_count": result.metrics.get("marker_disagreement_count"),
                "lineage_absent_from_reference_count": result.metrics.get("lineage_absent_from_reference_count"),
                "reference_lineages": result.metrics.get("reference_lineages"),
                "lineage_coverage": result.metrics.get("lineage_coverage"),
                "platform_shift_ratio": result.metrics.get("platform_shift_ratio"),
                "reference_label_class_count": len(reference_labels),
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
                    "distant_from_reference": (prediction or {}).get("distant_from_reference", ""),
                    "marker_lineage": (prediction or {}).get("marker_lineage", ""),
                    "marker_disagreement": (prediction or {}).get("marker_disagreement", ""),
                    "lineage_absent_from_reference": (prediction or {}).get("lineage_absent_from_reference", ""),
                    "review_priority": (prediction or {}).get("review_priority", ""),
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
