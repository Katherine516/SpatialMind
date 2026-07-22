import argparse
import os

from .agent import SpatialMindAgent
from .datasets import inspect_data_root, write_dataset_report
from .llm import build_llm_provider
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
