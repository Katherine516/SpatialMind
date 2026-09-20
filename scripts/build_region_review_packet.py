"""Render this section's spatial domains on tissue, for a pathologist to name.

    python scripts/build_region_review_packet.py \
        --data data/Xenium_Breast_Cancer_Rep1_Janesick2023 \
        --regions data/Xenium_Breast_Cancer_Rep1_Janesick2023/cell_regions.csv \
        --out outputs/region_review

Blinded by default: cell composition is not shown. These domains were named from
their own composition in the first place, so naming them from it again would
reproduce the circularity the packet exists to remove. `--unblind` is for a
second pass, after names are written.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.review.regions import build_region_review_packet


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a pathologist region-naming packet.")
    parser.add_argument("--data", required=True, help="Xenium output directory.")
    parser.add_argument("--regions", default="",
                        help="Region table to review. Defaults to cell_regions.csv in the bundle, "
                             "then cell_regions_candidate.csv in --candidates-from.")
    parser.add_argument("--candidates-from", default="",
                        help="A descriptive-lane output directory holding cell_regions_candidate.csv.")
    parser.add_argument("--out", required=True, help="Packet output directory.")
    parser.add_argument("--unblind", action="store_true",
                        help="Show cell composition. For a second pass only; the page says so.")
    parser.add_argument("--max-dimension", type=int, default=3000,
                        help="Morphology pyramid level to decode, by largest edge in pixels.")
    args = parser.parse_args()

    regions = args.regions
    if not regions:
        for candidate in (Path(args.data) / "cell_regions.csv",
                          Path(args.candidates_from or args.out) / "cell_regions_candidate.csv"):
            if candidate.exists():
                regions = str(candidate)
                break
    if not regions:
        raise SystemExit(
            "No region table found. Run the descriptive lane to produce "
            "cell_regions_candidate.csv, or pass --regions.")

    manifest = build_region_review_packet(
        dataset_path=args.data,
        region_table=regions,
        output_dir=args.out,
        blinded=not args.unblind,
        max_dimension=args.max_dimension,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print("\nOpen %s, write a name per domain, then:" % manifest["page"])
    print("  python scripts/apply_region_naming.py \\")
    print("      --data %s --sheet %s \\" % (args.data, manifest["naming_sheet"]))
    print("      --regions %s --reviewer 'Dr Name, H&E/DAPI review, 2026-09-19'" % regions)


if __name__ == "__main__":
    main()
