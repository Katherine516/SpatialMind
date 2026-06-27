import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.storage import index_run_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Index SpatialMind run records into a local SQLite database.")
    parser.add_argument("--outputs-root", default="outputs")
    parser.add_argument("--db", default="outputs/spatialmind_runs.sqlite")
    args = parser.parse_args()
    result = index_run_records(args.outputs_root, args.db)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
