"""Prepare reference decisions, portable sparse caches and a gated brain protocol."""

import argparse
import html
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spatialmind.review.reference_curation import prepare_reference_review, validate_reference_review
from spatialmind.review.development_protocol import prepare_protocol, ordered_preflight
from spatialmind.storage.reference_matrix import export_reference_matrix, verify_reference_cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-references")
    prepare.add_argument("--audit", required=True)
    prepare.add_argument("--out", required=True)
    validate = commands.add_parser("validate-references")
    validate.add_argument("--reference-packet", required=True)
    cache = commands.add_parser("cache")
    cache.add_argument("--source", required=True)
    cache.add_argument("--out", required=True)
    cache.add_argument("--layer", required=True)
    cache.add_argument("--semantics", choices=["raw_counts", "log_normalized"], required=True)
    cache.add_argument("--donor", action="append", required=True)
    cache.add_argument("--features-json", help="Optional JSON array of measured gene symbols; default preserves all features.")
    cache.add_argument("--max-cells", type=int)
    cache.add_argument("--chunk-rows", type=int, default=128)
    verify = commands.add_parser("verify-cache")
    verify.add_argument("--cache", required=True)
    protocol = commands.add_parser("prepare-protocol")
    protocol.add_argument("--packet", required=True)
    protocol.add_argument("--reference-packet", required=True)
    protocol.add_argument("--out", required=True)
    status = commands.add_parser("status")
    status.add_argument("--packet", required=True)
    status.add_argument("--reference-packet", required=True)
    status.add_argument("--protocol", required=True)
    status.add_argument("--out", required=True, help="New directory for JSON and HTML readiness reports.")
    args = parser.parse_args()
    if args.command == "prepare-references":
        result = prepare_reference_review(args.audit, args.out)
    elif args.command == "validate-references":
        result = validate_reference_review(args.reference_packet)
    elif args.command == "cache":
        features = json.loads(Path(args.features_json).read_text()) if args.features_json else None
        result = export_reference_matrix(args.source, args.out, args.layer, args.semantics,
                                         args.donor, features, args.max_cells, args.chunk_rows)
    elif args.command == "verify-cache":
        result = verify_reference_cache(args.cache)
    elif args.command == "prepare-protocol":
        result = prepare_protocol(args.packet, args.reference_packet, args.out)
    else:
        output = Path(args.out)
        if output.exists():
            parser.error("Use a new status output directory.")
        result = ordered_preflight(args.reference_packet, args.packet, args.protocol)
        output.mkdir(parents=True)
        (output / "readiness.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        review = result["specialist_review"]["datasets"]
        rows = "".join("<tr><td>%s</td><td>%d</td><td>%d</td><td>%d</td></tr>" % (
            html.escape(k), r["cohort_cells"], r["accepted_labels"], r["accepted_regions"]) for k, r in review.items())
        blockers = result["specialist_assignments"] + result["protocol_blockers"] + result["reference_curation"]["blockers"]
        blockers += [key + ": " + message for key, cohort in review.items() for message in cohort["blockers"]]
        body = "".join("<li>" + html.escape(message) + "</li>" for message in blockers)
        (output / "readiness.html").write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Brain validation readiness</title><style>body{font:16px system-ui;max-width:1050px;margin:32px auto;padding:16px;line-height:1.5}'
            'table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ccc;text-align:left}li{overflow-wrap:anywhere}</style>'
            '<h1>Brain validation readiness</h1><p>' + html.escape(result["status"]) + '</p>'
            '<p>No training or external evaluation performed. No expert approval inferred.</p>'
            '<table><tr><th>Cohort</th><th>Cells</th><th>Accepted labels</th><th>Accepted regions</th></tr>' + rows + '</table>'
            '<h2>Required Evidence</h2><ul>' + body + '</ul></html>', encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))
    if args.command in {"validate-references", "status"} and result["status"].startswith("blocked"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
