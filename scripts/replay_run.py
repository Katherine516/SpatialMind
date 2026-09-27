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
    parser.add_argument("--report-format", default="html", choices=["html", "pdf", "both"])
    args = parser.parse_args()

    if args.replay:
        result = replay_run_record(args.record, output_dir=args.out or None, verify_only=False)
        if result.get("status") == "verified_studio_replay_ready":
            from spatialmind.app.server import Studio, make_plan_worker
            from spatialmind.app.jobs import Job
            from spatialmind.contracts import ToolCallSpec
            studio = Studio(data_root=str(Path(result["dataset_path"]).parent),
                            output_root=result["replay_output_dir"])
            entry = next(row for row in studio.refresh_datasets()
                         if Path(row["path"]).resolve() == Path(result["dataset_path"]).resolve())
            params = result["params"]
            job = Job(job_id="replay", kind="plan", label=result["query"],
                      dataset_id=entry["dataset_id"], dataset_path=entry["path"])
            plan = [ToolCallSpec(**spec) for spec in params["effective_plan"]]
            payload = make_plan_worker(studio, entry["dataset_id"], params["tools"], params["overrides"],
                                       params["max_records"], effective_plan=plan)(job)
            result.update(status="replayed", replay_status=payload["delivery_status"],
                          replay_report=payload.get("report_paths", {}).get("html"))
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
                report_format=args.report_format,
                require_complete_section=params["require_complete_section"],
                review_max_records=params["review_max_records"],
                query=result["query"],
            )
            result["status"] = "replayed"
            result["replay_status"] = rerun.get("status")
            result["replay_report"] = rerun.get("report_path")
    else:
        result = verify_run_record(args.record).to_dict()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
