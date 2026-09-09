#!/usr/bin/env python3
"""Calibrate claim reliability against controls that are actually run.

`S_statistical` ships with the caveat "heuristic until calibrated against
ground-truth positive/negative controls". The existing null controls in
`train_claim_reliability_local.py` do not supply them: they write a sentence
describing a permutation, score it against the *unpermuted* payload, and label
it 0. That fits a label to a claim's wording, not to its evidence.

This runs the controls. One section is loaded once; each variant reassigns cell
labels in memory and re-runs `cell_neighborhood_enrichment`, so the z-scores the
scorer reads are the ones that labelling actually produced.

  positive  two real cell-type names interleaved in stripes -- the pair is
            adjacent by construction
  negative  the same labels permuted among cells -- composition preserved,
            association destroyed

Scope, stated plainly: this calibrates whether the score separates real spatial
structure from a permutation null. It does not calibrate whether a biological
claim is true. That still needs a reviewed claim-truth table, and
`prepare_claim_reliability_review_packet` remains the route to one.

    python scripts/calibrate_claim_reliability.py --out outputs/claim_calibration
"""

from pathlib import Path
from typing import Any, Dict, List
import argparse
import json
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_SECTION = ROOT / "outputs" / "workflow_demo_20260826" / "05_reviewed_section"
FEATURES = ["S_statistical", "A_annotation", "P_panel", "R_spatial_robustness"]


def build_payload(dataset, variant, records_loaded: int) -> Dict[str, Any]:
    """The payload shape `score_claim_reliability` reads, for one variant."""
    features = sorted({name for record in dataset.records[:200] for name in record.genes})
    applied = sorted({record.cell_type for record in dataset.records if record.cell_type})
    matched = sum(1 for record in dataset.records if record.cell_type)
    return {
        "records_loaded": records_loaded,
        "features_loaded": len(features),
        "cell_types": applied,
        "contract": {
            "panel_name": str(dataset.metadata.get("panel_name") or "unknown"),
            "n_features": len(features),
            "feature_names": features,
        },
        "label_report": {
            "status": "expert_labels_applied",
            "matched_cells": matched,
            "total_records": len(dataset.records),
        },
    }


def run_variant(dataset, registry, variant, params: Dict[str, Any]) -> Dict[str, Any]:
    from spatialmind.methods.reliability import score_claim_reliability

    for record in dataset.records:
        record.cell_type = variant.labels.get(record.cell_id or "", "")

    started = time.time()
    result = registry.get("cell_neighborhood_enrichment").run(dataset, dict(params))
    seconds = round(time.time() - started, 2)

    claim = {
        "claim_ref": variant.name,
        "claim_text": "Cells labelled %s are spatially adjacent to cells labelled %s."
                      % (variant.implanted_pair[0] or "type A", variant.implanted_pair[1] or "type B"),
        "claim_type": "spatial_colocalization",
        "status": "supported",
        "evidence_refs": ["cell_neighborhood_enrichment"],
        "allowed_wording": "",
    }
    payload = build_payload(dataset, variant, len(dataset.records))
    scored = score_claim_reliability(claim, payload, [result])
    return {
        "record_id": variant.name,
        "arm": variant.arm,
        "truth_label": variant.truth_label,
        "seed": variant.seed,
        "label_coverage": variant.label_coverage,
        "construction": variant.meta.get("construction"),
        "reliability": scored.reliability,
        "components": {
            "S_statistical": scored.S_statistical,
            "A_annotation": scored.A_annotation,
            "P_panel": scored.P_panel,
            "R_spatial_robustness": scored.R_spatial_robustness,
        },
        "tool_seconds": seconds,
        "tool_summary": result.summary,
    }


def component_separation(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-component means by arm. A component that does not move cannot inform a fit."""
    out = {}
    for name in FEATURES:
        pos = [r["components"][name] for r in rows if r["truth_label"] == 1]
        neg = [r["components"][name] for r in rows if r["truth_label"] == 0]
        mean_pos = sum(pos) / len(pos) if pos else 0.0
        mean_neg = sum(neg) / len(neg) if neg else 0.0
        out[name] = {
            "mean_positive": round(mean_pos, 4),
            "mean_negative": round(mean_neg, 4),
            "separation": round(mean_pos - mean_neg, 4),
            "varies": bool(len({round(v, 6) for v in pos + neg}) > 1),
        }
    return out


def auroc(labels: List[int], scores: List[float]) -> float:
    pairs = [(s, l) for s, l in zip(scores, labels)]
    pos = [s for s, l in pairs if l == 1]
    neg = [s for s, l in pairs if l == 0]
    if not pos or not neg:
        return 0.0
    wins = sum((1.0 if p > n else 0.5 if p == n else 0.0) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate claim reliability on run controls.")
    parser.add_argument("--section", default=str(DEFAULT_SECTION))
    parser.add_argument("--out", default="outputs/claim_calibration")
    parser.add_argument("--max-records", type=int, default=6000)
    parser.add_argument("--n-perms", type=int, default=200)
    parser.add_argument("--stripe-microns", type=float, default=60.0)
    args = parser.parse_args()

    from spatialmind.ingestion import load_xenium
    from spatialmind.methods.reliability import (
        build_control_grid, fit_claim_reliability_calibration, summarize_grid,
    )
    from spatialmind.tools import build_default_registry

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading %s" % args.section)
    started = time.time()
    dataset = load_xenium(args.section, max_records=args.max_records)
    print("  %d cells, %.1fs" % (len(dataset.records), time.time() - started))

    from spatialmind.ingestion import apply_best_available_labels
    apply_best_available_labels(dataset, args.section, fallback=None)
    real_labels = [record.cell_type for record in dataset.records]
    present = sorted({label for label in real_labels if label})
    # Two real, well-populated names so the arms share a label vocabulary.
    counts = {label: real_labels.count(label) for label in present}
    pair = tuple(sorted(counts, key=lambda label: -counts[label])[:2])
    if len(pair) < 2:
        print("This section has fewer than two labels; cannot build a positive control.")
        return 1
    print("  implant pair: %s / %s" % pair)

    cell_ids = [record.cell_id or "" for record in dataset.records]
    xs = [record.x for record in dataset.records]
    ys = [record.y for record in dataset.records]
    variants = build_control_grid(cell_ids, xs, ys, real_labels,
                                  stripe_microns=args.stripe_microns, pair=pair)
    print("  grid: %s" % summarize_grid(variants))

    registry = build_default_registry()
    params = {"n_neighs": 6, "n_perms": args.n_perms, "random_state": 0,
              "include_all_pairs": True, "strict_engine": True}

    rows: List[Dict[str, Any]] = []
    print("\nRunning %d control variants" % len(variants))
    for index, variant in enumerate(variants, start=1):
        row = run_variant(dataset, registry, variant, params)
        rows.append(row)
        print("  %2d/%d %-22s truth=%d  S=%.3f A=%.3f  reliability=%.3f  (%.1fs)"
              % (index, len(variants), variant.name, row["truth_label"],
                 row["components"]["S_statistical"], row["components"]["A_annotation"],
                 row["reliability"], row["tool_seconds"]))

    separation = component_separation(rows)
    print("\nCOMPONENT SEPARATION (positive mean - negative mean)")
    for name, stats in separation.items():
        print("  %-24s pos=%.3f neg=%.3f  sep=%+.3f  %s"
              % (name, stats["mean_positive"], stats["mean_negative"], stats["separation"],
                 "" if stats["varies"] else "constant - cannot inform the fit"))

    labels = [row["truth_label"] for row in rows]
    weakest = [row["reliability"] for row in rows]
    print("\nWeakest-link AUROC against the controls: %.4f" % auroc(labels, weakest))

    training = [{"reviewed_truth_label": row["truth_label"], "use_for_calibration": "yes",
                 "components": row["components"]} for row in rows]
    model = fit_claim_reliability_calibration(training)
    print("Calibration: %s" % model.get("status"))
    if model.get("status") == "fit":
        print("  training AUROC : %.4f" % model["training_auroc"])
        print("  records        : %d (%d positive, %d negative)"
              % (model["record_count"], model["positive_count"], model["negative_count"]))
        for name, weight in model["weights"].items():
            print("  weight %-24s %+.4f" % (name, weight))
    else:
        print("  reason: %s" % model.get("reason", ""))

    report = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "section": str(args.section),
        "cells": len(dataset.records),
        "implant_pair": list(pair),
        "params": {"n_perms": args.n_perms, "stripe_microns": args.stripe_microns,
                   "max_records": args.max_records},
        "grid": summarize_grid(variants),
        "rows": rows,
        "component_separation": separation,
        "weakest_link_auroc": auroc(labels, weakest),
        "calibration_model": model,
        "scope": (
            "Calibrated against permutation-null and stripe-implant controls. Measures separation of "
            "real spatial structure from a null. Does NOT measure whether a biological claim is true; "
            "that requires a reviewed claim-truth table."
        ),
    }
    (out_dir / "claim_calibration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nWrote %s" % (out_dir / "claim_calibration.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
