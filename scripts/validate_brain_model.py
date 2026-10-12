"""Select on specialist-reviewed development data or release one external test."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spatialmind.review.brain_validation import select_brain_annotation, evaluate_external_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select")
    select.add_argument("--packet", required=True)
    select.add_argument("--staging", required=True)
    select.add_argument("--out", required=True)
    select.add_argument("--donor-map", help="JSON section-key to independently verified donor-ID mapping.")
    select.add_argument("--protocol", required=True, help="Human-approved, prespecified development protocol.")
    test = commands.add_parser("external-test")
    test.add_argument("--model-lock", required=True)
    test.add_argument("--manifest", required=True)
    test.add_argument("--out", required=True)
    test.add_argument("--custodian-id", required=True)
    test.add_argument("--expected-lock-sha256", required=True)
    args = parser.parse_args()
    if args.command == "select":
        donors = json.loads(Path(args.donor_map).read_text()) if args.donor_map else None
        result = select_brain_annotation(args.packet, args.staging, args.out, donors, args.protocol)
    else:
        result = evaluate_external_once(args.model_lock, args.manifest, args.out,
                                        args.custodian_id, args.expected_lock_sha256)
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["status"].startswith("blocked"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
