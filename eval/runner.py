import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List

from spatialmind.agent_loop import SpatialAgent


@dataclass
class TestCase:
    id: str
    tier: int
    query: str
    dataset: str
    expected_tools: List[str] = field(default_factory=list)
    expected_params: Dict[str, object] = field(default_factory=dict)
    ground_truth: Dict[str, object] = field(default_factory=dict)
    dimension: str = "tool_selection"
    notes: str = ""


@dataclass
class EvalResult:
    id: str
    passed: bool
    score: float
    expected_tools: List[str]
    actual_tools: List[str]
    dimension: str
    warnings: List[str] = field(default_factory=list)
    modality: str = "unknown"


class EvalRunner:
    def __init__(self, agent: SpatialAgent) -> None:
        self.agent = agent

    def load_cases(self, directory: str) -> List[TestCase]:
        cases = []
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith((".yaml", ".yml", ".json")):
                continue
            with open(os.path.join(directory, filename), encoding="utf-8") as handle:
                payload = json.loads(handle.read())
            cases.append(TestCase(**payload))
        return cases

    def run(self, cases: List[TestCase], default_data: str = "") -> Dict[str, object]:
        results = []
        for case in cases:
            dataset = case.dataset or default_data
            response = self.agent.run(case.query, dataset_id=dataset)
            actual_tools = [call.tool_name for call in response.tool_trace if call.error is None]
            if case.ground_truth.get("no_analysis_expected"):
                score = 1.0 if getattr(response, "no_analysis_response", None) is not None else 0.0
            else:
                score = self._score_tools(case.expected_tools, actual_tools)
            results.append(
                EvalResult(
                    id=case.id,
                    passed=score >= 0.8,
                    score=score,
                    expected_tools=case.expected_tools,
                    actual_tools=actual_tools,
                    dimension=case.dimension,
                    warnings=response.warnings,
                    modality=_infer_modality(case.dataset),
                )
            )
        summary = self._summary(results)
        return {"summary": summary, "results": [asdict(result) for result in results]}

    def _score_tools(self, expected: List[str], actual: List[str]) -> float:
        if not expected:
            return 1.0
        expected_set = set(expected)
        actual_set = set(actual)
        precision = len(expected_set & actual_set) / float(len(actual_set) or 1)
        recall = len(expected_set & actual_set) / float(len(expected_set) or 1)
        if precision + recall == 0:
            return 0.0
        return round((2 * precision * recall) / (precision + recall), 4)

    def _summary(self, results: List[EvalResult]) -> Dict[str, object]:
        by_dimension: Dict[str, List[float]] = {}
        by_modality: Dict[str, int] = {}
        by_tool: Dict[str, int] = {}
        for result in results:
            by_dimension.setdefault(result.dimension, []).append(result.score)
            by_modality[result.modality] = by_modality.get(result.modality, 0) + 1
            for tool in result.actual_tools:
                by_tool[tool] = by_tool.get(tool, 0) + 1
        return {
            "case_count": len(results),
            "pass_count": sum(1 for result in results if result.passed),
            "mean_score": round(sum(result.score for result in results) / float(len(results) or 1), 4),
            "by_dimension": {
                key: round(sum(values) / float(len(values) or 1), 4) for key, values in sorted(by_dimension.items())
            },
            "coverage": {
                "by_modality": dict(sorted(by_modality.items())),
                "by_tool": dict(sorted(by_tool.items())),
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SpatialMind eval cases.")
    parser.add_argument("--cases", default="eval/test_cases")
    parser.add_argument("--data", default="data/demo_manifest.json")
    parser.add_argument("--out", default="outputs/eval_report.json")
    parser.add_argument("--mvp", action="store_true", help="Run against the current MVP agent/tool policy.")
    args = parser.parse_args()

    runner = EvalRunner(SpatialAgent(mvp_mode=args.mvp))
    cases = runner.load_cases(args.cases)
    for case in cases:
        if not case.dataset:
            case.dataset = args.data
    report = runner.run(cases, default_data=args.data)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print("Eval cases: %d" % report["summary"]["case_count"])
    print("Passed: %d" % report["summary"]["pass_count"])
    print("Mean score: %.4f" % report["summary"]["mean_score"])


def _infer_modality(dataset: str) -> str:
    lowered = dataset.lower()
    if "xenium" in lowered or "merfish" in lowered:
        return "merfish_xenium"
    if "codex" in lowered or "imc" in lowered:
        return "protein_imaging"
    if "atac" in lowered:
        return "spatial_atac"
    if "visium" in lowered or "brca" in lowered or "demo" in lowered:
        return "visium_like"
    return "unknown"


if __name__ == "__main__":
    main()
