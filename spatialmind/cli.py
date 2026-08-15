import argparse
import os
from pathlib import Path

from .agent import SpatialMindAgent
from .datasets import inspect_data_root, write_dataset_report
from .ingestion import infer_data_type
from .llm import build_llm_provider
from .pilot import run_pilot
from .storage import StorageLayer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SpatialMind spatial omics agent.")
    parser.add_argument("prompt", nargs="?", help="Natural-language spatial omics request.")
    parser.add_argument("--data", default="data/demo_spatial.csv", help="Path to a tidy spatial omics CSV file.")
    parser.add_argument("--out", default="outputs", help="Directory for run artifacts.")
    parser.add_argument("--memory", default=".spatialmind", help="Directory for JSON memory.")
    parser.add_argument("--inspect-data", action="store_true", help="Inspect dataset candidates instead of running the agent.")
    parser.add_argument("--inspect-out", default="outputs/dataset_report.json", help="Path for --inspect-data JSON report.")
    parser.add_argument("--replay-run-id", default="", help="Replay a stored run by run id using its provenance metadata.")
    parser.add_argument(
        "--llm-provider",
        default="local",
        choices=["local", "openai", "gpt", "anthropic", "claude"],
        help="Planner backend. local uses deterministic rules; openai/gpt and anthropic/claude call hosted APIs.",
    )
    parser.add_argument("--llm-model", default="", help="Hosted model name, for example gpt-4.1 or claude-sonnet-4-20250514.")
    parser.add_argument(
        "--report-format",
        default="html",
        choices=["html", "pdf", "both"],
        help="Report delivery format. PDF output retains an HTML source for auditability.",
    )
    parser.add_argument("--max-records", type=int, default=5000, help="Maximum cells loaded for Xenium review runs.")
    parser.add_argument("--full-section", action="store_true", help="Load all Xenium cells for final validated inference.")
    parser.add_argument("--review-max-records", type=int, default=5000, help="Rows written to Xenium review templates.")
    parser.add_argument("--min-label-coverage", type=float, default=0.7)
    parser.add_argument("--min-region-coverage", type=float, default=0.7)
    parser.add_argument("--allow-single-region", action="store_true")
    parser.add_argument(
        "--allow-sampled-validation",
        action="store_true",
        help="Development-only override for validated Xenium analysis on a sampled section.",
    )
    parser.add_argument(
        "--readiness-only",
        action="store_true",
        help="For Xenium, write a fast readiness JSON without building analysis artifacts.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.inspect_data:
        report_path = write_dataset_report(args.data, args.inspect_out)
        inspections = inspect_data_root(args.data)
        print("Dataset report: %s" % os.path.abspath(report_path))
        for item in inspections:
            status = "usable" if item.usable else "blocked"
            print("- %s [%s, %s]: %s" % (item.sample_id or item.path, status, item.readiness, item.data_type))
            if item.blockers:
                print("  blockers: %s" % "; ".join(item.blockers[:3]))
        return
    if args.replay_run_id:
        stored = StorageLayer(root=args.out).get_run(args.replay_run_id)
        if not stored.query or not stored.artifacts:
            parser.error("stored run does not include enough provenance to replay")
        data_path = ""
        try:
            import json

            with open(stored.provenance_path, encoding="utf-8") as handle:
                data_path = str(json.load(handle).get("source_path") or "")
        except Exception:
            data_path = ""
        if not data_path:
            parser.error("stored run has no source_path in provenance")
        provider = build_llm_provider(args.llm_provider, model=args.llm_model)
        agent = SpatialMindAgent(output_root=args.out, memory_root=args.memory, llm_provider=provider)
        run = agent.run(stored.query, data_path, report_format=args.report_format)
        print("Replayed run: %s" % run.run_id)
        _print_reports(run)
        return
    if not args.prompt:
        parser.error("prompt is required unless --inspect-data is used")
    if infer_data_type(args.data) in {"xenium_directory", "xenium_experiment_file"}:
        result = run_pilot(
            dataset_path=args.data,
            output_dir=Path(args.out),
            max_records=0 if args.full_section else args.max_records,
            min_label_coverage=args.min_label_coverage,
            min_region_coverage=args.min_region_coverage,
            allow_single_region=args.allow_single_region,
            report_format=args.report_format,
            readiness_only=args.readiness_only,
            require_complete_section=not args.allow_sampled_validation,
            review_max_records=args.review_max_records,
            query=args.prompt,
        )
        print("Xenium pilot status: %s" % result["status"])
        if result.get("report_path"):
            print("Report: %s" % os.path.abspath(str(result["report_path"])))
        print("Validation record: %s" % os.path.abspath(os.path.join(args.out, "pilot_validation.json")))
        if result.get("run_record_path"):
            print("Replay record: %s" % os.path.abspath(str(result["run_record_path"])))
        if result.get("blocking_reasons"):
            print("Blockers: %s" % "; ".join(result["blocking_reasons"]))
        return
    provider = build_llm_provider(args.llm_provider, model=args.llm_model)
    agent = SpatialMindAgent(output_root=args.out, memory_root=args.memory, llm_provider=provider)
    run = agent.run(args.prompt, args.data, report_format=args.report_format)
    print("Run ID: %s" % run.run_id)
    _print_reports(run)
    print("Provenance: %s" % os.path.abspath(run.provenance_path))
    for result in run.results:
        print("- %s: %s" % (result.tool_name, result.summary))


def _print_reports(run) -> None:
    paths = run.report_paths or {"primary": run.report_path}
    for report_type, path in paths.items():
        print("Report (%s): %s" % (report_type, os.path.abspath(path)))


if __name__ == "__main__":
    main()
