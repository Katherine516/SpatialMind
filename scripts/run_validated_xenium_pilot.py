import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.pilot import DEFAULT_DATASET, DEFAULT_OUTPUT, run_pilot


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or qualify a validated Xenium pilot workflow.")
    parser.add_argument("--data", default=DEFAULT_DATASET, help="Xenium output directory.")
    parser.add_argument("--out", default=DEFAULT_OUTPUT, help="Output directory.")
    parser.add_argument("--max-records", type=int, default=5000)
    parser.add_argument("--min-label-coverage", type=float, default=0.7)
    parser.add_argument("--min-region-coverage", type=float, default=0.7)
    parser.add_argument("--allow-single-region", action="store_true")
    parser.add_argument(
        "--report-format",
        default="html",
        choices=["html", "pdf", "both"],
        help="Report delivery format. PDF output retains HTML as an auditable source.",
    )
    parser.add_argument(
        "--readiness-only",
        action="store_true",
        help="Write only pilot_validation.json; skip templates, figures, reports, validated tools, and the run record.",
    )
    args = parser.parse_args()

    result = run_pilot(
        dataset_path=args.data,
        output_dir=Path(args.out),
        max_records=args.max_records,
        min_label_coverage=args.min_label_coverage,
        min_region_coverage=args.min_region_coverage,
        allow_single_region=args.allow_single_region,
        report_format=args.report_format,
        readiness_only=args.readiness_only,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
