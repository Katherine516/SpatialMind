"""Technical smoke test on draft training donors, never a trained model or test score."""

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spatialmind.ingestion import load_scrna
from spatialmind.ingestion.pipeline import _read_h5_feature_names, _read_h5_control_features


def main():
    import h5py

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--donor-plan", required=True)
    parser.add_argument("--target-matrix", required=True, help="Xenium cell_feature_matrix.h5; metadata only.")
    parser.add_argument("--max-records", type=int, default=64)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.max_records < 1:
        parser.error("Technical smoke tests require a positive sample limit.")
    output = Path(args.out)
    if output.exists():
        parser.error("Use a new output path.")
    plan = json.loads(Path(args.donor_plan).read_text())
    if plan.get("status") != "draft_internal_donor_split":
        parser.error("Expected an explicit draft donor plan.")
    with h5py.File(args.target_matrix, "r") as handle:
        names = _read_h5_feature_names(handle["matrix"])
        controls, _, _ = _read_h5_control_features(handle["matrix"], names)
        panel = [name for name in names if name not in set(controls)]
    rows = []
    for reference in plan["references"]:
        started = time.monotonic()
        entry = {"path": reference["path"]}
        try:
            donors = reference["allowed_donors_by_role"]["train"]
            forbidden = set(plan["donors_by_role"]["validation"]) | set(plan["donors_by_role"]["test"])
            if set(donors) & forbidden or not donors:
                raise ValueError("Training donors overlap held-out roles or are empty.")
            layer = reference["expression_layer_candidate"]
            if not layer:
                raise ValueError("No source-supported count-layer candidate.")
            data = load_scrna(reference["path"], max_records=args.max_records, keep_features=panel,
                              expression_layer=layer, expression_semantics="raw_counts", allowed_donors=donors)
            if set(data.metadata["donor_ids"]) & forbidden:
                raise ValueError("Loaded a held-out donor.")
            entry.update({"status": "loaded", "cells": len(data.records), "species": data.metadata["organism"],
                          "layer": data.metadata["expression_layer"], "donors_loaded": data.metadata["donor_ids"],
                          "shared_measured_features": len(data.metadata["selected_feature_names"]),
                          "detected_features": len(data.genes), "label_classes_in_training_sample": len(data.cell_types)})
        except (ValueError, OSError) as exc:
            entry.update({"status": "blocked", "reason": str(exc)})
        entry["seconds"] = round(time.monotonic() - started, 3)
        rows.append(entry)
    result = {"scope": "Technical layer/donor/panel reading check; declared raw semantics use the draft source evidence, not expert approval",
              "source_plan": args.donor_plan, "target_panel_features": len(panel), "references": rows,
              "training_performed": False, "test_scored": False, "biological_accuracy": None}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 1 if any(row["status"] != "loaded" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
