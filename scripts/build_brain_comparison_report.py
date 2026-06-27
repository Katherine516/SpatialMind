import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.review import DEFAULT_GLIOBLASTOMA_DATASET, DEFAULT_HEALTHY_BRAIN_DATASET, build_brain_comparison_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare healthy brain and glioblastoma only after both are validated.")
    parser.add_argument("--healthy", default=DEFAULT_HEALTHY_BRAIN_DATASET, help="Healthy brain Xenium output directory.")
    parser.add_argument("--glioblastoma", default=DEFAULT_GLIOBLASTOMA_DATASET, help="Glioblastoma Xenium output directory.")
    parser.add_argument("--out", default="outputs/brain_comparison", help="Comparison output directory.")
    parser.add_argument("--max-records", type=int, default=2500)
    args = parser.parse_args()

    result = build_brain_comparison_report(
        healthy_path=args.healthy,
        glioblastoma_path=args.glioblastoma,
        output_dir=args.out,
        max_records=args.max_records,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
