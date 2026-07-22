import argparse
import json
import sys
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.runner import EvalRunner
from spatialmind.agent_loop import SpatialAgent
from spatialmind.datasets import discover_dataset_candidates
from spatialmind.ingestion import (
    apply_best_available_labels,
    apply_best_available_regions,
    build_readiness_report,
    load_xenium,
    summarize_xenium_expert_readiness,
    validate_cell_by_feature_contract,
)
from spatialmind.schemas import ToolResult
from spatialmind.tools import build_mvp_registry
from spatialmind.versioning import detect_openmp_runtime_conflicts


OUTPUT_ROOT = Path("outputs/training/local_spatialmind_training")
DEMO_DATASET = "data/demo_manifest.json"


@dataclass
class TrainingRecord:
    record_id: str
    record_type: str
    dataset_path: str
    query: str
    expected_tools: List[str]
    actual_tools: List[str]
    score: float
    usable_for: List[str]
    not_usable_for: List[str]
    label_status: str
    warnings: List[str]
    result_summary: str = ""
    metrics: Dict[str, Any] = None
    recommended_next_step: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if payload["metrics"] is None:
            payload["metrics"] = {}
        return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local SpatialMind behavioral training/evaluation records.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--out", default=str(OUTPUT_ROOT))
    parser.add_argument("--max-records", type=int, default=1200)
    args = parser.parse_args()
    output_root = Path(args.out)
    output_root.mkdir(parents=True, exist_ok=True)
    xenium_datasets = _discover_xenium_datasets(args.data_root)
    records: List[TrainingRecord] = []
    records.extend(_run_mvp_eval_training_cases())
    records.extend(_run_xenium_exploratory_training(xenium_datasets, max_records=args.max_records))
    records.extend(_build_xenium_readiness_training_records(xenium_datasets))
    _write_outputs(records, output_root, xenium_datasets)


def _run_mvp_eval_training_cases() -> List[TrainingRecord]:
    agent = SpatialAgent(mvp_mode=True)
    runner = EvalRunner(agent)
    cases = runner.load_cases("eval/mvp_cases")
    outputs: List[TrainingRecord] = []
    for case in cases:
        response = agent.run(case.query, case.dataset or DEMO_DATASET)
        actual_tools = [call.tool_name for call in response.tool_trace if call.error is None]
        if case.ground_truth.get("no_analysis_expected"):
            score = 1.0 if response.no_analysis_response is not None else 0.0
        else:
            score = runner._score_tools(case.expected_tools, actual_tools)
        label_status = _label_status_from_warnings(response.warnings)
        outputs.append(
            TrainingRecord(
                record_id=case.id,
                record_type="mvp_query_plan_result",
                dataset_path=case.dataset or DEMO_DATASET,
                query=case.query,
                expected_tools=case.expected_tools,
                actual_tools=actual_tools,
                score=score,
                usable_for=["planner_training", "tool_selection_eval", "refusal_policy"] if score >= 0.8 else ["failure_analysis"],
                not_usable_for=["biological_ground_truth"],
                label_status=label_status,
                warnings=response.warnings,
                result_summary=response.interpretation,
                metrics={"dimension": case.dimension, "ground_truth": case.ground_truth},
                recommended_next_step=(
                    response.no_analysis_response.recommended_next_step
                    if response.no_analysis_response is not None
                    else ""
                ),
            )
        )
    return outputs


def _run_xenium_exploratory_training(dataset_paths: List[str], max_records: int) -> List[TrainingRecord]:
    records: List[TrainingRecord] = []
    for index, dataset_path in enumerate(dataset_paths, start=1):
        dataset = load_xenium(dataset_path, max_records=max_records)
        dataset.metadata["analysis_dataset_path"] = dataset_path
        label_report = apply_best_available_labels(dataset, dataset_path, fallback=None)
        region_report = apply_best_available_regions(dataset, dataset_path)
        contract = validate_cell_by_feature_contract(dataset)
        readiness = build_readiness_report(dataset)
        registry = build_mvp_registry()
        group1, group2 = _choose_groups(dataset)
        tool_plan = [
            ("qc_and_cluster", {"resolution": 0.55, "strict_engine": True, "random_state": 0}),
            ("annotation", {"method": "existing_provisional_labels"}),
            (
                "marker_detection",
                {
                    "group_key": "cell_type",
                    "group1": group1,
                    "group2": group2,
                    "strict_engine": True,
                    "method": "wilcoxon",
                    "n_top": 15,
                },
            ),
            (
                "cell_neighborhood_enrichment",
                {"n_neighs": 6, "n_perms": 100, "n_jobs": 1, "random_state": 0, "strict_engine": True},
            ),
        ]
        results: List[ToolResult] = []
        warnings: List[str] = []
        for tool_name, params in tool_plan:
            result = registry.get(tool_name).run(dataset, params)
            results.append(result)
            warnings.extend(result.caveats)
            if result.label_caveat:
                warnings.append(result.label_caveat)
        real_engines = sorted(
            {str(result.metrics.get("engine")) for result in results if result.metrics.get("engine")}
        )
        records.append(
            TrainingRecord(
                record_id="LOCAL-XENIUM-EXPLORATORY-%03d" % index,
                record_type="xenium_exploratory_pipeline",
                dataset_path=dataset_path,
                query="Run the Xenium exploratory workflow on this local dataset using provisional labels with explicit caveats.",
                expected_tools=[tool for tool, _params in tool_plan],
                actual_tools=[result.tool_name for result in results],
                score=1.0,
                usable_for=["pipeline_regression_training", "wrapper_validation", "weak_label_caveat_training"],
                not_usable_for=["expert_cell_type_ground_truth", "biological_claim_training"],
                label_status=(
                    "provisional_loader_labels"
                    if label_report.status != "expert_labels_applied"
                    else label_report.status
                ),
                warnings=_dedupe(warnings + label_report.warnings + region_report.warnings + readiness.warnings),
                result_summary=" ".join(result.summary for result in results),
                metrics={
                    "cell_count": len(dataset.records),
                    "feature_count": len(dataset.genes),
                    "cell_type_count": len(dataset.cell_types),
                    "cell_types": dataset.cell_types,
                    "contract": _jsonable(contract),
                    "label_readiness": label_report.to_dict(),
                    "region_readiness": region_report.to_dict(),
                    "readiness": _jsonable(readiness),
                    "tool_metrics": {result.tool_name: _compact_metrics(result.metrics) for result in results},
                    "real_engines": real_engines,
                    "sampling": dataset.metadata.get("sampling", {}),
                },
                recommended_next_step=(
                    "Replace provisional labels with expert or validated reference-assisted labels keyed by Xenium cell_id."
                ),
            )
        )
    return records


def _build_xenium_readiness_training_records(dataset_paths: List[str]) -> List[TrainingRecord]:
    records = []
    for index, dataset_path in enumerate(dataset_paths, start=1):
        readiness = summarize_xenium_expert_readiness(dataset_path)
        status = "ready_for_expert_labeling" if readiness.has_cell_table and readiness.has_feature_matrix else "blocked"
        records.append(
            TrainingRecord(
                record_id="LOCAL-XENIUM-READINESS-%03d" % index,
                record_type="xenium_label_readiness",
                dataset_path=dataset_path,
                query="Determine whether this local Xenium dataset can be used for expert-label-ready SpatialMind training.",
                expected_tools=[],
                actual_tools=[],
                score=1.0 if status == "ready_for_expert_labeling" else 0.0,
                usable_for=["readiness_policy_training", "next_step_recommendation"],
                not_usable_for=["planner_finetuning_without_labels", "biological_ground_truth"],
                label_status="missing_expert_labels" if not readiness.external_label_tables else "external_labels_available",
                warnings=list(readiness.needs),
                result_summary=(
                    "Core Xenium assets are present; expert labels are still needed."
                    if status == "ready_for_expert_labeling"
                    else "Dataset is missing core Xenium assets required for training."
                ),
                metrics=readiness.to_dict(),
                recommended_next_step="Fill the generated expert_label_template.csv or provide expert_cell_labels.csv with cell_id, expert_label, confidence, and notes.",
            )
        )
    return records


def _write_outputs(records: List[TrainingRecord], output_root: Path, xenium_datasets: List[str]) -> None:
    jsonl_path = output_root / "training_records.jsonl"
    summary_path = output_root / "training_summary.json"
    report_path = output_root / "training_report.md"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), sort_keys=True, allow_nan=False) + "\n")
    summary = _summarize(records, jsonl_path, report_path)
    summary["xenium_datasets"] = xenium_datasets
    summary["runtime_warnings"] = detect_openmp_runtime_conflicts()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    report_path.write_text(_render_report(records, summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def _summarize(records: List[TrainingRecord], jsonl_path: Path, report_path: Path) -> Dict[str, Any]:
    by_type: Dict[str, int] = {}
    by_label_status: Dict[str, int] = {}
    for record in records:
        by_type[record.record_type] = by_type.get(record.record_type, 0) + 1
        by_label_status[record.label_status] = by_label_status.get(record.label_status, 0) + 1
    scores = [record.score for record in records]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "mean_score": round(sum(scores) / float(len(scores) or 1), 4),
        "by_type": dict(sorted(by_type.items())),
        "by_label_status": dict(sorted(by_label_status.items())),
        "usable_for_counts": _count_multi(records, "usable_for"),
        "not_usable_for_counts": _count_multi(records, "not_usable_for"),
        "training_records": str(jsonl_path),
        "training_report": str(report_path),
        "recommended_next_step": "Add expert/user Xenium labels and user-provided region labels, then rerun this script.",
    }


def _render_report(records: List[TrainingRecord], summary: Dict[str, Any]) -> str:
    lines = [
        "# SpatialMind Local Training Run",
        "",
        "Created: `%s`" % summary["created_at"],
        "",
        "## Summary",
        "",
        "- Records created: `%d`" % summary["record_count"],
        "- Mean behavior score: `%.4f`" % summary["mean_score"],
        "- Record types: `%s`" % json.dumps(summary["by_type"], sort_keys=True),
        "- Label status: `%s`" % json.dumps(summary["by_label_status"], sort_keys=True),
        "",
        "## Runtime Warnings",
        "",
    ]
    if summary.get("runtime_warnings"):
        lines.extend("- %s" % warning for warning in summary["runtime_warnings"])
    else:
        lines.append("- No known conflicting numerical runtimes were detected.")
    lines.extend(
        [
        "",
        "## What Was Trained",
        "",
        "This run trains the agent behaviorally: query planning, tool selection, refusal policy, weak-label caveats, and local Xenium readiness recommendations. It does not fine-tune a neural model and it does not create expert biological ground truth.",
        "",
        "## Local Data Used",
        "",
        "- `data/demo_manifest.json` and `data/demo_spatial.csv` for supervised MVP query-plan-result examples.",
        "- Every Xenium output folder discovered under the selected data root for real-wrapper exploratory pipeline records.",
        "- The same Xenium folders for expert-label and ROI readiness records.",
        "",
        "## Records",
        "",
        ]
    )
    for record in records:
        lines.extend(
            [
                "### %s" % record.record_id,
                "",
                "- Type: `%s`" % record.record_type,
                "- Dataset: `%s`" % record.dataset_path,
                "- Score: `%.4f`" % record.score,
                "- Label status: `%s`" % record.label_status,
                "- Usable for: `%s`" % ", ".join(record.usable_for),
                "- Not usable for: `%s`" % ", ".join(record.not_usable_for),
                "- Expected tools: `%s`" % ", ".join(record.expected_tools),
                "- Actual tools: `%s`" % ", ".join(record.actual_tools),
                "- Next step: %s" % (record.recommended_next_step or "No immediate blocker."),
                "",
            ]
        )
    lines.extend(
        [
            "## Next Step",
            "",
            "Provide at least one completed Xenium expert label table and one user region label table. The minimum expert label table columns are `cell_id` and `expert_label`; recommended columns are `confidence`, `notes`, `source`, and `reviewer`. Region labels should map `cell_id` to a user-defined region such as tumor core, invasive margin, stroma, follicle, cortex, or necrosis, depending on tissue.",
            "",
        ]
    )
    return "\n".join(lines)


def _choose_groups(dataset: Any) -> tuple[str, str]:
    counts: Dict[str, int] = {}
    for record in dataset.records:
        counts[record.cell_type] = counts.get(record.cell_type, 0) + 1
    eligible = [
        label
        for label in sorted(counts, key=counts.get, reverse=True)
        if "unannotated" not in label.lower() and label.lower() != "unlabeled"
    ]
    if len(eligible) < 2:
        eligible = sorted(counts, key=counts.get, reverse=True)
    if len(eligible) < 2:
        raise ValueError("Xenium exploratory training requires at least two provisional cell classes.")
    return eligible[0], eligible[1]


def _discover_xenium_datasets(data_root: str) -> List[str]:
    return [
        path
        for path in discover_dataset_candidates(data_root)
        if Path(path).is_dir() and (Path(path) / "experiment.xenium").exists()
    ]


def _label_status_from_warnings(warnings: List[str]) -> str:
    text = " ".join(warnings).lower()
    if "marker-rule" in text or "weak" in text:
        return "weak_marker_rule_labels"
    if "missing" in text or "placeholder" in text:
        return "missing_expert_labels"
    return "demo_or_existing_labels"


def _compact_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    compact = {}
    for key, value in metrics.items():
        if key == "ranked_genes" and isinstance(value, list):
            compact[key] = value[:10]
        elif key == "quality_metrics":
            compact[key] = value
        elif isinstance(value, dict) and len(value) > 20:
            compact[key] = dict(list(value.items())[:20])
        else:
            compact[key] = value
    return _jsonable(compact)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _count_multi(records: List[TrainingRecord], field_name: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for record in records:
        for item in getattr(record, field_name):
            counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items()))


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


if __name__ == "__main__":
    main()
