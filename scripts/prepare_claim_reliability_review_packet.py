import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.review import prepare_claim_reliability_review_packet, write_claim_truth_validation_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or validate a claim-level reliability review packet.")
    parser.add_argument("--out", default="outputs/claim_reliability_review_packet")
    parser.add_argument("--max-records", type=int, default=800)
    parser.add_argument("--validate-truth", default="", help="Optional completed spatial_claim_truth CSV to validate.")
    args = parser.parse_args()

    if args.validate_truth:
        result = write_claim_truth_validation_report(args.validate_truth, output_dir=args.out)
    else:
        result = prepare_claim_reliability_review_packet(output_dir=args.out, max_records=args.max_records)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
