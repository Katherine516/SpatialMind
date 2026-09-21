"""Turn a filled region naming sheet into the bundle's `cell_regions.csv`.

    python scripts/apply_region_naming.py \
        --data data/Xenium_Breast_Cancer_Rep1_Janesick2023 \
        --sheet outputs/region_review/region_naming_sheet.csv \
        --regions data/Xenium_Breast_Cancer_Rep1_Janesick2023/cell_regions.csv \
        --reviewer "Dr Name, DAPI morphology review, 2026-09-19"

`--reviewer` is required and is written into every row. The gate counts a
reviewed region table and cannot read who wrote it; that column is the only
place the difference between a pathologist and a script survives into the
report, and the report prints it.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.review.regions import apply_region_naming


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a filled region naming sheet.")
    parser.add_argument("--data", required=True, help="Xenium output directory.")
    parser.add_argument("--sheet", required=True, help="The filled region_naming_sheet.csv.")
    parser.add_argument("--regions", default="",
                        help="The domain table the sheet names. Defaults to cell_regions.csv.")
    parser.add_argument("--reviewer", required=True,
                        help="Who made these calls, e.g. 'Dr Name, DAPI morphology review, 2026-09-19'.")
    parser.add_argument("--out", default="",
                        help="Where to write. Defaults to cell_regions.csv inside --data, which "
                             "replaces whatever is there.")
    parser.add_argument("--dry-run", action="store_true", help="Report and write nothing.")
    args = parser.parse_args()

    regions = args.regions or str(Path(args.data) / "cell_regions.csv")
    target = args.out
    if args.dry_run:
        import tempfile

        target = str(Path(tempfile.mkdtemp()) / "cell_regions.csv")

    result = apply_region_naming(
        dataset_path=args.data,
        naming_sheet=args.sheet,
        region_table=regions,
        reviewer_id=args.reviewer,
        output_path=target or None,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") != "written":
        raise SystemExit(2)
    if result["domains_left_blank"]:
        print("\n%d domain(s) were left blank and their cells are not in the table: %s"
              % (len(result["domains_left_blank"]), ", ".join(result["domains_left_blank"])))
        print("Coverage of assigned cells is %.1f%%; the gate default needs 70%%."
              % (100 * result["coverage_of_assigned"]))
    if args.dry_run:
        print("\n--dry-run: written to a temp file, the bundle is untouched.")


if __name__ == "__main__":
    main()
