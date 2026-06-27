import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.review import DEFAULT_GLIOBLASTOMA_DATASET, build_reference_assist_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or gate tissue-matched reference-assist annotation.")
    parser.add_argument("--target", default=DEFAULT_GLIOBLASTOMA_DATASET, help="Target Xenium output directory.")
    parser.add_argument("--reference", default=None, help="Reviewed tissue-matched reference directory.")
    parser.add_argument("--out", default="outputs/glioblastoma_reference_assist", help="Reference-assist output directory.")
    parser.add_argument("--max-records", type=int, default=2500)
    parser.add_argument("--min-shared-features", type=int, default=20)
    args = parser.parse_args()

    result = build_reference_assist_report(
        target_path=args.target,
        output_dir=args.out,
        reference_path=args.reference,
        max_records=args.max_records,
        min_shared_features=args.min_shared_features,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
