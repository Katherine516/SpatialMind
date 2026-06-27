import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.governance import build_dataset_governance_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a dataset governance manifest template for local data.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--out", default="outputs/governance/dataset_governance_manifest.json")
    args = parser.parse_args()
    manifest = build_dataset_governance_manifest(args.data_root, args.out)
    print(json.dumps({"status": manifest["status"], "records": len(manifest["records"]), "path": args.out}, indent=2))


if __name__ == "__main__":
    main()
