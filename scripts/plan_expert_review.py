"""Plan an expert review that will actually open the validation gate.

The gate needs labels covering a fraction of the cells a run *loads*, and runs
load a deterministic subsample. A review file built from a different selection --
for example a stratified benchmark packet -- can therefore be labelled perfectly
and still leave the gate shut, because few of its cells appear in the run.

This writes review files aligned to the exact run you intend, says how many cells
must be labelled, and checks any label files you already have against that run.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.ingestion import load_xenium, write_expert_label_template, write_region_label_template


def _label_ids(path):
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            return [row.get("cell_id", "") for row in csv.DictReader(handle)]
    except (OSError, csv.Error):
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a gate-opening expert review.")
    parser.add_argument("data", help="Xenium output folder or experiment.xenium file.")
    parser.add_argument("--out", default="outputs/review_plan", help="Where to write aligned review files.")
    parser.add_argument("--max-cells", type=int, default=500, help="Cells the validated run will load.")
    parser.add_argument("--min-coverage", type=float, default=0.7, help="Gate coverage requirement.")
    parser.add_argument("--check", nargs="*", default=[], help="Existing label CSVs to test against this run.")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dataset = load_xenium(args.data, max_records=args.max_cells)
    loaded = [record.cell_id for record in dataset.records]
    needed = int(len(loaded) * args.min_coverage) + 1

    label_file = write_expert_label_template(
        dataset, str(out / "expert_cell_labels_TEMPLATE.csv"), max_rows=args.max_cells, dataset_path=args.data
    )
    region_file = write_region_label_template(
        dataset, str(out / "cell_regions_TEMPLATE.csv"), max_rows=args.max_cells, dataset_path=args.data
    )

    print("Review plan for a run loading %d cells\n" % len(loaded))
    print("  Label at least %d of %d cells (%.0f%% coverage) in BOTH files:" % (needed, len(loaded), args.min_coverage * 100))
    print("    %s" % label_file)
    print("    %s" % region_file)
    print("\n  Then copy the completed files into the dataset folder as:")
    print("    %s" % os.path.join(args.data, "expert_cell_labels.csv"))
    print("    %s" % os.path.join(args.data, "cell_regions.csv"))
    print("\n  Also required: at least 2 distinct cell classes and 2 distinct regions.")

    checks = []
    if args.check:
        print("\nChecking existing label files against this run:")
        loaded_set = set(loaded)
        for path in args.check:
            ids = _label_ids(path)
            overlap = sum(1 for cell_id in ids if cell_id in loaded_set)
            coverage = overlap / float(max(len(loaded), 1))
            verdict = "opens the gate" if coverage >= args.min_coverage else "WILL NOT open the gate"
            print("  %s\n     %d rows, %d present in this run -> %.1f%% coverage: %s"
                  % (path, len(ids), overlap, coverage * 100, verdict))
            if coverage < args.min_coverage and ids:
                print("     Labelling every row of this file still leaves the gate shut for this run size.")
            checks.append({"path": path, "rows": len(ids), "present": overlap,
                           "coverage": round(coverage, 4), "opens_gate": coverage >= args.min_coverage})

    (out / "review_plan.json").write_text(json.dumps({
        "dataset_path": args.data,
        "run_loads_cells": len(loaded),
        "min_coverage": args.min_coverage,
        "cells_to_label": needed,
        "label_template": label_file,
        "region_template": region_file,
        "checked_files": checks,
    }, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
