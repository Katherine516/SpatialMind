import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.review import DEFAULT_GLIOBLASTOMA_DATASET, build_glioblastoma_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or gate a glioblastoma-specific benchmark from reviewed labels.")
    parser.add_argument("--data", default=DEFAULT_GLIOBLASTOMA_DATASET, help="Glioblastoma Xenium output directory.")
    parser.add_argument("--out", default="outputs/glioblastoma_benchmark", help="Benchmark output directory.")
    parser.add_argument("--max-records", type=int, default=2500)
    parser.add_argument("--min-label-coverage", type=float, default=0.7)
    parser.add_argument("--min-region-coverage", type=float, default=0.7)
    args = parser.parse_args()

    result = build_glioblastoma_benchmark(
        dataset_path=args.data,
        output_dir=args.out,
        max_records=args.max_records,
        min_label_coverage=args.min_label_coverage,
        min_region_coverage=args.min_region_coverage,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
