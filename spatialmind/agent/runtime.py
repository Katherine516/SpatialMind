from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from spatialmind.contracts import PlanValidationError, ToolCallSpec
from spatialmind.schemas import SpatialDataset, ToolResult
from spatialmind import gatekeeper
from spatialmind.tools.grouping import GROUPED_TOOLS, normalize_group_key
from spatialmind.tools.exceptions import MissingPreconditionError, ToolExecutionError, InvalidParameterError


MVP_TOOL_OUTPUTS: Dict[str, List[str]] = {
    "qc_and_cluster": ["clustering", "qc"],
    "annotation": ["annotation"],
    "marker_detection": ["markers", "differential_evidence"],
    "spatial_variable_genes": ["spatial_genes", "spatial_evidence"],
    "feature_overlay": ["figure"],
    "region_summary": ["region_summary"],
    "cell_neighborhood_enrichment": ["neighborhood_test", "spatial_evidence"],
    "spatial_clustering": ["clustering"],
    "cell_type_annotation": ["annotation"],
}


DEFAULT_XENIUM_INPUTS = ["normalized_counts", "spatial_coords", "targeted_panel", "segmentation"]


def check_execution_gate(dataset_path, plan, gate=None, dataset=None):
    """Check effective calls, including inserted dependencies, not just user intent."""
    return gatekeeper.require_gate_open(
        dataset_path, [spec.tool_name for spec in plan], dataset=dataset, gate=gate,
        overrides={spec.tool_name: spec.params for spec in plan},
    )


def effective_tool_call(spec):
    """Resolve execution policy without mutating the proposed call."""
    params = dict(spec.params)
    if spec.tool_name in GROUPED_TOOLS | {"qc_and_cluster", "spatial_clustering", "spatial_variable_genes"}:
        if params.get("engine") == "prototype" or params.get("strict_engine") is False:
            raise InvalidParameterError("Studio/pilot scientific runs require real backends; prototype fallback is not allowed.")
        params["strict_engine"] = True
    if spec.tool_name in GROUPED_TOOLS:
        params["group_key"] = normalize_group_key(params)
    return ToolCallSpec(spec.tool_name, params, requires=spec.dependency_keys())


def execute_tool_step(dataset, spec, registry, dataset_path=None, gate=None):
    """Policy-enforcing execution boundary shared by all supported entry points."""
    effective = effective_tool_call(spec)
    params = effective.params
    tool = registry.get(spec.tool_name)
    if tool.capability == "unavailable":
        raise ToolExecutionError("%s is unavailable." % spec.tool_name)
    check_execution_gate(dataset_path or dataset.source_path, [effective], gate, dataset)
    unmet = registry.check_preconditions(spec.tool_name, dataset)
    if unmet:
        raise MissingPreconditionError("%s: %s" % (spec.tool_name, "; ".join(unmet)))
    result = tool.run(dataset, params)
    result.metrics["execution_policy"] = {
        "boundary": "agent.runtime.execute_tool_step",
        "effective_parameters": {key: value for key, value in params.items() if key != "reference_dataset"},
    }
    return result


@dataclass
class PlanValidationReport:
    status: str
    available_outputs: List[str]
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "valid"


@dataclass
class LoopAction:
    kind: str
    tool_name: Optional[str] = None
    param_override: Optional[Dict[str, object]] = None
    rationale: str = ""


@dataclass
class RunContext:
    session_id: str
    dataset: SpatialDataset
    max_iterations: int = 8
    cost_budget: float = 10.0
    completed_outputs: List[str] = field(default_factory=list)
    history: List[Dict[str, object]] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    cost_used: float = 0.0

    def record_result(self, spec: ToolCallSpec, result: ToolResult, cost: float = 1.0) -> None:
        self.tool_results.append(result)
        self.history.append(
            {
                "tool_name": spec.tool_name,
                "requires": spec.dependency_keys(),
                "result_summary": result.summary,
                "result_metrics": result.metrics,
            }
        )
        self.cost_used += cost
        for output in MVP_TOOL_OUTPUTS.get(spec.tool_name, []):
            if output not in self.completed_outputs:
                self.completed_outputs.append(output)

    def over_budget(self) -> bool:
        return self.cost_used >= self.cost_budget

    def no_progress(self) -> bool:
        if len(self.history) < 2:
            return False
        return self.history[-1].get("result_summary") == self.history[-2].get("result_summary")


def build_xenium_mvp_plan(include_marker_detection: bool = True) -> List[ToolCallSpec]:
    steps = [
        ToolCallSpec(
            "qc_and_cluster",
            {"resolution": 0.55, "random_state": 0, "strict_engine": True},
            requires=["normalized_counts"],
        ),
        ToolCallSpec("annotation", {"method": "expert_label_table"}, requires=["clustering", "expert_labels"]),
    ]
    if include_marker_detection:
        steps.append(
            ToolCallSpec(
                "marker_detection",
                {"group_key": "cell_type", "n_top": 25, "strict_engine": True},
                requires=["annotation"],
            )
        )
    steps.extend(
        [
            ToolCallSpec(
                "spatial_variable_genes",
                {
                    "n_top": 50,
                    "n_neighs": 6,
                    "n_perms": 250,
                    "random_state": 0,
                    "strict_engine": True,
                },
                requires=["normalized_counts", "spatial_coords"],
            ),
            ToolCallSpec("region_summary", {"top_n_features": 10}, requires=["annotation", "user_regions"]),
            ToolCallSpec(
                "cell_neighborhood_enrichment",
                {
                    "n_neighs": 6,
                    "n_perms": 250,
                    "random_state": 0,
                    "include_all_pairs": True,
                    "strict_engine": True,
                },
                requires=["annotation", "spatial_coords"],
            ),
        ]
    )
    return steps


def validate_tool_plan(
    plan: Sequence[ToolCallSpec],
    available_inputs: Optional[Iterable[str]] = None,
    registry_tool_names: Optional[Iterable[str]] = None,
) -> PlanValidationReport:
    available = list(dict.fromkeys(available_inputs or []))
    allowed_tools = set(registry_tool_names or [])
    errors: List[str] = []
    for index, spec in enumerate(plan):
        if allowed_tools and spec.tool_name not in allowed_tools:
            errors.append("Step %d uses unknown tool `%s`." % (index + 1, spec.tool_name))
        missing = [key for key in spec.dependency_keys() if key not in available]
        if missing:
            errors.append("Step %d `%s` is missing required outputs: %s." % (index + 1, spec.tool_name, ", ".join(missing)))
        for output in MVP_TOOL_OUTPUTS.get(spec.tool_name, []):
            if output not in available:
                available.append(output)
    return PlanValidationReport(
        status="valid" if not errors else "invalid",
        available_outputs=available,
        errors=errors,
    )


def require_valid_tool_plan(
    plan: Sequence[ToolCallSpec],
    available_inputs: Optional[Iterable[str]] = None,
    registry_tool_names: Optional[Iterable[str]] = None,
) -> PlanValidationReport:
    report = validate_tool_plan(plan, available_inputs=available_inputs, registry_tool_names=registry_tool_names)
    if not report.ok:
        raise PlanValidationError("; ".join(report.errors))
    return report
