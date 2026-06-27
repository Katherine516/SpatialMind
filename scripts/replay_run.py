import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.storage import replay_run_record, verify_run_record


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify or replay a SpatialMind run record.")
    parser.add_argument("record", help="Path to an MVP run record JSON.")
    parser.add_argument("--out", default="", help="Replay output directory.")
    parser.add_argument("--replay", action="store_true", help="Rerun supported workflows after hash verification.")
    args = parser.parse_args()

    if args.replay:
        result = replay_run_record(args.record, output_dir=args.out or None, verify_only=False)
        if result.get("status") == "verified_replay_ready":
            from spatialmind.pilot import run_pilot

            params = result["params"]
            rerun = run_pilot(
                result["dataset_path"],
                output_dir=Path(result["replay_output_dir"]),
                max_records=params["max_records"],
                min_label_coverage=params["min_label_coverage"],
                min_region_coverage=params["min_region_coverage"],
                allow_single_region=params["allow_single_region"],
            )
            result["status"] = "replayed"
            result["replay_status"] = rerun.get("status")
            result["replay_report"] = rerun.get("report_html")
    else:
        result = verify_run_record(args.record).to_dict()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
