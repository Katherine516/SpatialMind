"""Create a non-approved, donor-disjoint reference development plan."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spatialmind.ingestion.reference_splits import plan_donor_splits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    output = Path(args.out)
    if output.exists():
        parser.error("Choose a new output path; never overwrite a donor plan.")
    result = plan_donor_splits(json.loads(Path(args.audit).read_text()), args.collection, args.seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "donor_count", "donors_by_role", "training_ready", "test_scored")}, indent=2))


if __name__ == "__main__":
    main()
