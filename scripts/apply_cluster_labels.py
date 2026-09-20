"""Expand a filled cluster worksheet into `expert_cell_labels.csv`.

    python scripts/apply_cluster_labels.py \
        --run outputs/brain_healthy_review \
        --worksheet outputs/brain_healthy_review/cluster_label_worksheet.csv \
        --reviewer "Dr Name, marker review, 2026-09-19" \
        --out "data/.../Healthy_outs/expert_cell_labels.csv"

Every row records `assignment_scope=cluster:<id>`, so the gate's
`review_decisions` counts the calls that were made -- four -- rather than the
17,909 cells they covered. That number is what the reliability caveat prints on
every claim, and a table written without it would turn four judgements into
seventeen thousand apparent ones.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.review.sizing import apply_cluster_labels


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a filled cluster label worksheet.")
    parser.add_argument("--run", required=True, help="The descriptive run directory.")
    parser.add_argument("--worksheet", default="",
                        help="Filled worksheet. Defaults to cluster_label_worksheet.csv in --run.")
    parser.add_argument("--reviewer", required=True,
                        help="Who made these calls, e.g. 'Dr Name, marker review, 2026-09-19'.")
    parser.add_argument("--out", required=True,
                        help="Where to write expert_cell_labels.csv, normally inside the bundle.")
    parser.add_argument("--dry-run", action="store_true", help="Report and write nothing.")
    args = parser.parse_args()

    worksheet = args.worksheet or str(Path(args.run) / "cluster_label_worksheet.csv")
    target = args.out
    if args.dry_run:
        import tempfile

        target = str(Path(tempfile.mkdtemp()) / "expert_cell_labels.csv")

    result = apply_cluster_labels(args.run, worksheet, args.reviewer, target)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") != "written":
        raise SystemExit(2)

    if not result["meets_two_class_minimum"]:
        print("\nThe gate needs at least two distinct classes; this worksheet names %d."
              % result["distinct_classes"])
    print("\nCoverage of clustered cells: %.1f%% (the gate default needs 70%%)."
          % (100 * result["coverage_of_clustered"]))
    if result["clusters_left_blank"]:
        print("Left blank: %s" % ", ".join(result["clusters_left_blank"]))
    if args.dry_run:
        print("\n--dry-run: written to a temp file; nothing in the bundle changed.")


if __name__ == "__main__":
    main()
