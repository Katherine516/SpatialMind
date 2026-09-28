"""Prepare a specialist handoff or stage explicitly reviewed cohort decisions."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spatialmind.review.specialist_handoff import prepare_handoff, validate_handoff
from spatialmind.review.brain_readiness import initialize, assign, readiness, acquire_candidate_catalog, ROLES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--existing-packet", required=True)
    prepare.add_argument("--out", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--packet", required=True)
    validate.add_argument("--export-to", help="New staging directory, never the raw data folder.")
    initialize_parser = commands.add_parser("initialize-study")
    initialize_parser.add_argument("--packet", required=True)
    status = commands.add_parser("readiness")
    status.add_argument("--packet", required=True)
    assignment = commands.add_parser("assign")
    assignment.add_argument("--packet", required=True)
    assignment.add_argument("--role", choices=ROLES, required=True)
    assignment.add_argument("--reviewer-id", required=True)
    assignment.add_argument("--qualification-evidence", required=True)
    assignment.add_argument("--accepted", action="store_true", required=True,
                            help="Record only after the named person accepts; does not contact anyone.")
    catalog = commands.add_parser("acquire-catalog")
    catalog.add_argument("--out", required=True, help="Fetch external candidate metadata, not test labels.")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_handoff(args.existing_packet, args.out)
    elif args.command == "validate":
        result = validate_handoff(args.packet, args.export_to)
    elif args.command == "initialize-study":
        result = initialize(args.packet)
    elif args.command == "readiness":
        result = readiness(args.packet)
    elif args.command == "assign":
        result = assign(args.packet, args.role, args.reviewer_id, args.qualification_evidence)
    else:
        result = acquire_candidate_catalog(args.out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
