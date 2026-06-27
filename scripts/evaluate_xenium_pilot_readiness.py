import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.pilot import scan_pilot_readiness


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a validated Xenium pilot readiness scorecard.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--out", default="outputs/xenium_pilot_scorecard")
    parser.add_argument("--max-records", type=int, default=1200)
    args = parser.parse_args()

    dataset_paths = _find_xenium_dirs(Path(args.data_root))
    summary = scan_pilot_readiness(dataset_paths, Path(args.out), max_records=args.max_records)
    print(json.dumps(summary, indent=2, sort_keys=True))


def _find_xenium_dirs(root: Path) -> list[str]:
    candidates = []
    for path in root.rglob("*"):
        if path.is_dir() and (path / "experiment.xenium").exists() and ((path / "cells.csv.gz").exists() or (path / "cells.csv").exists()):
            candidates.append(str(path))
    return sorted(candidates)


if __name__ == "__main__":
    main()
