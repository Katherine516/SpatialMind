"""Run the production annotation tool on a frozen, buffered spatial holdout."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spatialmind.review.annotation_benchmark import run_annotation_benchmark


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/Xenium_Breast_Cancer_Rep1_Janesick2023")
    parser.add_argument("--out", required=True, help="New empty directory; frozen outputs cannot be overwritten.")
    parser.add_argument("--max-records", type=int, default=20000)
    parser.add_argument("--bins", type=int, default=6)
    parser.add_argument("--buffer-um", type=float, default=50.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    result = run_annotation_benchmark(args.data, args.out, args.max_records, args.bins, args.buffer_um, args.seed)
    print(json.dumps({key: value for key, value in result.items() if key != "protocol"}, indent=2))


if __name__ == "__main__":
    main()
