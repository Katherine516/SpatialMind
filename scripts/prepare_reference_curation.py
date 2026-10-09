"""Prepare an unapproved reference inventory; --audit adds bounded numeric samples."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spatialmind.ingestion.reference_readiness import build_reference_inventory, audit_reference_panel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data")
    parser.add_argument("--out", required=True)
    parser.add_argument("--audit", action="store_true", help="Include donor overlap and bounded layer/source evidence; never approves training.")
    args = parser.parse_args()
    output = Path(args.out)
    if output.exists():
        parser.error("Output exists; choose a new path to preserve any curation decisions.")
    paths = sorted(Path(args.data).rglob("*.h5ad"))
    if not paths:
        parser.error("No H5AD references found.")
    result = (audit_reference_panel if args.audit else build_reference_inventory)(str(path) for path in paths)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"references": len(result["references"]), "errors": result["errors"],
                      "training_ready": False, "out": str(output)}, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
