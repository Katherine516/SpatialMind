"""Select an opt-in prior correction on frozen training/validation data only."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spatialmind.review.rare_class_selection import select_rare_class_policy

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(select_rare_class_policy(args.benchmark, args.matrix, args.out), indent=2))
