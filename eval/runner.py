import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

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
    forbidden_tools_run: List[str] = field(default_factory=list)


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
            # A case can now assert what must *not* have run. Scoring only the
            # tools that were expected cannot fail when the wrong tool also runs,
            # and cannot notice a scaffold executing at all.
            forbidden = set(case.ground_truth.get("forbidden_tools") or [])
            trespass = sorted(forbidden & set(actual_tools))
            if trespass:
                score = 0.0
            if case.ground_truth.get("no_scaffold_expected"):
                ran_scaffolds = sorted(set(actual_tools) & _scaffold_names())
                if ran_scaffolds:
                    score = 0.0
                    trespass = trespass + ran_scaffolds
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
                    forbidden_tools_run=trespass,
                )
            )
        summary = self._summary(results)
        invariants = check_suite_invariants()
        summary["invariants_passed"] = all(item["passed"] for item in invariants)
        summary["invariants_failed"] = [item["name"] for item in invariants if not item["passed"]]
        return {
            "summary": summary,
            "invariants": invariants,
            "results": [asdict(result) for result in results],
        }

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


def _scaffold_names() -> set:
    from spatialmind.tools import build_default_registry

    return {tool.name for tool in build_default_registry().list_all() if tool.capability == "unavailable"}


def check_suite_invariants() -> List[Dict[str, object]]:
    """Properties of the system the query cases cannot reach.

    Every case here drives the *router* and asserts on which tools it chose. Both
    bugs that reached a shipped build lived elsewhere: scaffold detection failed
    inside the registry when the app was frozen, and the gate was enforced by the
    Studio's UI rather than by its API. A suite that only scores tool selection
    could not have caught either, which is the real reason it scored 1.0000 every
    run while those bugs were live.
    """
    from spatialmind.gatekeeper import gated_tool_names
    from spatialmind.tools import build_default_registry

    registry = build_default_registry()
    checks: List[Dict[str, object]] = []
    # Tools that really are scaffolds today. If one is genuinely implemented, this
    # check fires and a human updates the list -- implementing a scaffold should
    # be a noticed event, not a silent one.
    known_scaffolds = {"cnv_inference", "ligand_receptor_analysis", "spatial_deconvolution"}

    # Asserting that no tool marked unavailable is plannable proves nothing:
    # list_plannable() filters *by* that field, so the check cannot fail however
    # broken detection is. What can fail is whether detection still recognises a
    # tool that really is a scaffold. When inspect.getsource stopped working
    # inside the frozen app, every scaffold silently became "validated" -- and a
    # tautological check would have stayed green through it.
    by_name = {t.name: t for t in registry.list_all()}
    undetected = sorted(
        name for name in known_scaffolds
        if name in by_name and by_name[name].capability != "unavailable"
    )
    checks.append({
        "name": "scaffolds_are_detected",
        "passed": not undetected,
        "detail": "%d of %d registered tools detected as scaffolds"
                  % (len(_scaffold_names()), len(registry.list_all())),
        "offenders": undetected,
    })

    # Same trap as above: both to_anthropic_tools() and _scaffold_names() derive
    # from `capability`, so comparing them can never disagree. Name the tools.
    offered = {t["name"] for t in registry.to_anthropic_tools()}
    leaked = sorted(known_scaffolds & offered)
    checks.append({
        "name": "no_scaffold_in_llm_schemas",
        "passed": not leaked,
        "detail": "%d tools offered to a model, %d of them known scaffolds"
                  % (len(offered), len(leaked)),
        "offenders": leaked,
    })

    # Scaffolds are excluded: gating a tool that can never run is moot, and
    # counting them hides the number that matters. If the gate stops recognising
    # these specific tools it has lost its grip and they become freely runnable.
    must_be_gated = {"annotation", "region_summary", "neighborhood_enrichment"}
    plannable_gated = set(gated_tool_names([t.name for t in registry.list_plannable()]))
    ungated = sorted(must_be_gated - plannable_gated)
    checks.append({
        "name": "gatekeeper_recognises_gated_tools",
        "passed": not ungated,
        "detail": "%d of %d plannable tools require the gate; core gated set %s"
                  % (len(plannable_gated), len(registry.list_plannable()),
                     "intact" if not ungated else "BROKEN"),
        "offenders": ungated,
    })

    undocumented = [t.name for t in registry.list_plannable() if not t.preconditions]
    checks.append({
        "name": "plannable_tools_declare_preconditions",
        "passed": not undocumented,
        "detail": "%d plannable tools without preconditions" % len(undocumented),
        "offenders": undocumented,
    })

    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SpatialMind eval cases.")
    parser.add_argument(
        "--cases",
        default=None,
        help="Case directory. Defaults to eval/mvp_cases with --mvp, otherwise eval/test_cases.",
    )
    parser.add_argument("--data", default="data/demo_manifest.json")
    parser.add_argument("--out", default="outputs/eval_report.json")
    parser.add_argument("--mvp", action="store_true", help="Run against the current MVP agent/tool policy.")
    args = parser.parse_args()

    # `--cases` picks the cases; `--mvp` picks the agent policy. They are
    # independent flags, so `--cases eval/mvp_cases` without `--mvp` ran the MVP
    # cases against the legacy registry and reported 2/13, mean 0.205 -- a score
    # that looks exactly like a regression and is not one. The two are checked
    # against each other rather than silently mismatched.
    case_directory = _case_directory(args.cases, args.mvp)
    _refuse_policy_mismatch(parser, case_directory, args.mvp)

    runner = EvalRunner(SpatialAgent(mvp_mode=args.mvp))
    cases = runner.load_cases(case_directory)
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
    print("Suite invariants:")
    for item in report["invariants"]:
        print("  [%s] %-38s %s" % ("ok" if item["passed"] else "FAIL", item["name"], item["detail"]))
    trespassers = [r for r in report["results"] if r.get("forbidden_tools_run")]
    if trespassers:
        print("Forbidden tools ran in %d case(s):" % len(trespassers))
        for r in trespassers:
            print("  %s ran %s" % (r["id"], ", ".join(r["forbidden_tools_run"])))
    if not report["summary"]["invariants_passed"] or trespassers:
        raise SystemExit(1)


def _refuse_policy_mismatch(parser, case_directory: str, mvp_mode: bool) -> None:
    """Refuse a case set that does not match the agent policy selected."""
    looks_mvp = "mvp" in os.path.basename(os.path.normpath(case_directory)).lower()
    if looks_mvp and not mvp_mode:
        parser.error(
            "%s holds MVP cases but --mvp was not given, so they would run against the legacy "
            "registry and score as failures. Add --mvp, or point --cases at a legacy case set."
            % case_directory
        )
    if mvp_mode and not looks_mvp:
        parser.error(
            "--mvp selects the MVP agent policy, but %s does not look like an MVP case set. "
            "Drop --mvp, or point --cases at eval/mvp_cases." % case_directory
        )


def _case_directory(requested: Optional[str], mvp_mode: bool) -> str:
    if requested:
        return requested
    return "eval/mvp_cases" if mvp_mode else "eval/test_cases"


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
