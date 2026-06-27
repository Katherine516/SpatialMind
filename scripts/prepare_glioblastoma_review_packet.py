import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.review import DEFAULT_GLIOBLASTOMA_DATASET, prepare_glioblastoma_review_packet


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a glioblastoma expert-review packet.")
    parser.add_argument("--data", default=DEFAULT_GLIOBLASTOMA_DATASET, help="Glioblastoma Xenium output directory.")
    parser.add_argument("--out", default="outputs/glioblastoma_expert_review_packet", help="Review packet output directory.")
    parser.add_argument("--max-records", type=int, default=2500)
    parser.add_argument("--pilot-out", default="outputs/xenium_brain_glioblastoma_pilot")
    args = parser.parse_args()

    result = prepare_glioblastoma_review_packet(
        dataset_path=args.data,
        output_dir=args.out,
        max_records=args.max_records,
        pilot_output_dir=args.pilot_out,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
