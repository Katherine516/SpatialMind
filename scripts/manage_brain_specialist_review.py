"""Prepare a specialist handoff or stage explicitly reviewed cohort decisions."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spatialmind.review.specialist_handoff import prepare_handoff, validate_handoff


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--existing-packet", required=True)
    prepare.add_argument("--out", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--packet", required=True)
    validate.add_argument("--export-to", help="New staging directory, never the raw data folder.")
    args = parser.parse_args()
    result = (prepare_handoff(args.existing_packet, args.out) if args.command == "prepare"
              else validate_handoff(args.packet, args.export_to))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
