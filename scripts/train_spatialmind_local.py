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


OUTPUT_ROOT = Path("outputs/training/local_spatialmind_training")
DEMO_DATASET = "data/demo_manifest.json"
BREAST_XENIUM = "data/Human_Breast_Biomarkers_S1_Top_outs"
LOCAL_XENIUM_DATASETS = [
    "data/Human_Breast_Biomarkers_S1_Top_outs",
    "data/Xenium lymph/Xenium_V1_hLymphNode_nondiseased_section_outs",
    "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs",
    "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs",
]


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
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    records: List[TrainingRecord] = []
    records.extend(_run_mvp_eval_training_cases())
    records.extend(_run_breast_xenium_weak_label_training())
    records.extend(_build_xenium_readiness_training_records())
    _write_outputs(records)


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


def _run_breast_xenium_weak_label_training() -> List[TrainingRecord]:
    dataset = load_xenium(BREAST_XENIUM, max_records=2500)
    dataset.metadata["analysis_dataset_path"] = BREAST_XENIUM
    label_report = apply_best_available_labels(dataset, BREAST_XENIUM, fallback="breast_marker_rule")
    region_report = apply_best_available_regions(dataset, BREAST_XENIUM)
    contract = validate_cell_by_feature_contract(dataset)
    readiness = build_readiness_report(dataset)
    registry = build_mvp_registry()
    group1, group2 = _choose_groups(dataset)
    tool_plan = [
        ("qc_and_cluster", {"resolution": 0.55, "engine": "prototype"}),
        ("annotation", {"method": "marker_rule_v0"}),
        ("marker_detection", {"group_key": "cell_type", "group1": group1, "group2": group2, "engine": "prototype", "n_top": 15}),
        ("cell_neighborhood_enrichment", {"radius": 35.0, "engine": "prototype"}),
    ]
    results: List[ToolResult] = []
    warnings: List[str] = []
    for tool_name, params in tool_plan:
        result = registry.get(tool_name).run(dataset, params)
        results.append(result)
        warnings.extend(result.caveats)
        if result.label_caveat:
            warnings.append(result.label_caveat)
    return [
        TrainingRecord(
            record_id="LOCAL-XENIUM-BREAST-WEAK-001",
            record_type="xenium_weak_label_pipeline",
            dataset_path=BREAST_XENIUM,
            query="Run the v7 Xenium MVP workflow on the local breast dataset using the best currently available labels.",
            expected_tools=[tool for tool, _params in tool_plan],
            actual_tools=[result.tool_name for result in results],
            score=1.0,
            usable_for=["pipeline_regression_training", "visualization_training", "weak_label_caveat_training"],
            not_usable_for=["expert_cell_type_ground_truth", "biological_claim_training"],
            label_status=label_report.status,
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
            },
            recommended_next_step="Replace marker-rule labels with expert or validated reference-assisted labels keyed by Xenium cell_id.",
        )
    ]


def _build_xenium_readiness_training_records() -> List[TrainingRecord]:
    records = []
    for index, dataset_path in enumerate(LOCAL_XENIUM_DATASETS, start=1):
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


def _write_outputs(records: List[TrainingRecord]) -> None:
    jsonl_path = OUTPUT_ROOT / "training_records.jsonl"
    summary_path = OUTPUT_ROOT / "training_summary.json"
    report_path = OUTPUT_ROOT / "training_report.md"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
    summary = _summarize(records, jsonl_path, report_path)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
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
        "## What Was Trained",
        "",
        "This run trains the agent behaviorally: query planning, tool selection, refusal policy, weak-label caveats, and local Xenium readiness recommendations. It does not fine-tune a neural model and it does not create expert biological ground truth.",
        "",
        "## Local Data Used",
        "",
        "- `data/demo_manifest.json` and `data/demo_spatial.csv` for supervised MVP query-plan-result examples.",
        "- `data/Human_Breast_Biomarkers_S1_Top_outs` for a weak-label Xenium MVP pipeline record.",
        "- Four local Xenium folders for expert-label readiness records.",
        "",
        "## Records",
        "",
    ]
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
    first = "CD8+_T_Cells" if "CD8+_T_Cells" in counts else max(counts, key=counts.get)
    second = "Invasive_Tumor" if "Invasive_Tumor" in counts else sorted(counts, key=counts.get, reverse=True)[-1]
    if first == second and len(counts) > 1:
        second = sorted(counts, key=counts.get, reverse=True)[1]
    return first, second


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
