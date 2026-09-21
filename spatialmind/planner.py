"""LEGACY (v1). The reasoning layer for `SpatialMindAgent` only.

`LLMReasoningLayer` plans against `AlgorithmEngine`'s three tools. It is the only
place an LLM plans anything: every other path -- the agent loop, the Studio's
Ask surface, the pilot -- uses deterministic keyword routing or a fixed typed
plan, and validates the result with `validate_tool_plan` before execution.

That validator is what would make LLM planning safe to switch on for the v2
stack. Until then this module is reachable only through the legacy orchestrator,
and the LLM path stays off by default.

Do not extend this. Planning for the current stack lives in
`spatialmind.agent.runtime` (typed plans and validation) and
`spatialmind.app.planner` (routing and lanes).
"""

import re
from typing import Dict, Iterable, List, Optional, Tuple

from .llm import LLMProvider
from .schemas import AnalysisRequest, ExecutionPlan, ExecutionStep


CELL_TYPE_ALIASES = {
    "cd8": "CD8+ T cell",
    "cd8+": "CD8+ T cell",
    "t cell": "CD8+ T cell",
    "tumor": "Tumor cell",
    "cancer": "Tumor cell",
    "macrophage": "Macrophage",
    "myeloid": "Macrophage",
    "endothelial": "Endothelial cell",
    "vasculature": "Endothelial cell",
    "stroma": "Stromal cell",
    "fibroblast": "Stromal cell",
}

STOP_TOKENS = {
    "CD8",
    "SHOW",
    "TELL",
    "CELL",
    "CELLS",
    "SAMPLE",
    "RELATIVE",
    "SIGNIFICANT",
    "SPATIAL",
    "DISTRIBUTION",
}

ALLOWED_TOOLS = {
    "cell_type_distribution",
    "spatial_gene_expression",
    "cell_type_colocalization",
}

# The model names goals and reads entities out of the question. It does not
# order the steps, choose parameters or declare dependencies: those are derived
# here, identically for a model-supplied goal set and a rule-derived one. Asking
# for less is the point -- a smaller answer is a smaller thing to get wrong, and
# what is left is checkable in one line against ALLOWED_TOOLS.
PLANNER_SYSTEM_PROMPT = """You are the planning layer for SpatialMind, a spatial omics agent.
Return only a JSON object. Do not include markdown.

The JSON shape is:
{
  "sample_id": "BRCA_04 or empty string",
  "cell_types": ["canonical cell type names"],
  "genes": ["GENE_SYMBOL"],
  "wants_visualization": true,
  "wants_colocalization": false,
  "clarifications": ["short issue if needed"],
  "goals": ["cell_type_distribution", "cell_type_colocalization"]
}

`goals` is the set of analyses the question asks for. Name only what was asked.
Do not order them, do not supply parameters, and do not declare dependencies --
the planner derives all three. Use only these names:
- cell_type_distribution: map/count requested cell types.
- spatial_gene_expression: summarize requested genes.
- cell_type_colocalization: test whether two cell types share spatial bins.

Prefer canonical cell types such as CD8+ T cell, Tumor cell, Macrophage, Endothelial cell, and Stromal cell.
"""

# Goals that cannot run without another goal's output. The planner inserts the
# producer rather than trusting a caller -- model or rule -- to remember it.
GOAL_REQUIRES = {
    "cell_type_colocalization": ["cell_type_distribution"],
}

STEP_NAMES = {
    "cell_type_distribution": "Map cell-type distribution",
    "spatial_gene_expression": "Summarize spatial gene expression",
    "cell_type_colocalization": "Test cell-type co-localization",
}


def order_goals(goals: Iterable[str]) -> List[str]:
    """Insert missing producers and sort so they precede their consumers.

    The same job `spatialmind.app.planner.order_plan` does for the v2 registry,
    over a graph small enough to state in one dict. Asking for co-localization
    without the distribution it reads used to produce a step whose `depends_on`
    named a step that was not in the plan.
    """
    resolved: List[str] = []

    def add(name: str, seen: Tuple[str, ...] = ()) -> None:
        if name in resolved or name in seen or name not in ALLOWED_TOOLS:
            return
        for required in GOAL_REQUIRES.get(name, []):
            add(required, seen + (name,))
        resolved.append(name)

    for goal in dict.fromkeys(goals):
        add(goal)
    return resolved


def build_steps(request: AnalysisRequest, goals: Iterable[str]) -> List[ExecutionStep]:
    """The only place a step is constructed.

    Parameters come from the parsed request and dependencies from
    `GOAL_REQUIRES`, so a plan the model asked for and a plan the rules derived
    cannot differ in anything but which goals are in it. A model that supplied
    its own `bin_size` or `n_perms` would be changing the statistics with
    nothing downstream able to tell.
    """
    ordered = order_goals(goals)
    parameters = {
        "cell_type_distribution": lambda: {"cell_types": request.cell_types},
        "spatial_gene_expression": lambda: {"genes": request.genes},
        "cell_type_colocalization": lambda: {"cell_types": request.cell_types, "bin_size": 20.0},
    }
    steps: List[ExecutionStep] = []
    for goal in ordered:
        steps.append(
            ExecutionStep(
                name=STEP_NAMES[goal],
                tool=goal,
                parameters=parameters[goal](),
                depends_on=[STEP_NAMES[req] for req in GOAL_REQUIRES.get(goal, []) if req in ordered],
            )
        )
    return steps


def goals_from_payload(payload: Dict[str, object]) -> Tuple[List[str], List[str]]:
    """The goal names a model asked for, and the ones this build does not have.

    Rejections are returned rather than skipped. `_steps_from_llm_payload` used
    a bare `continue`, so a payload naming only tools that do not exist produced
    an empty plan and a run that reported success having done nothing -- the one
    outcome this project is built to refuse, and already fixed once in the v2
    planner as `unknown_tools()`.

    A payload carrying whole steps is read for its tool names only. Its
    parameters and `depends_on` are dropped on purpose; see `build_steps`.
    """
    raw = payload.get("goals")
    if not isinstance(raw, list) or not raw:
        raw = [item.get("tool") for item in (payload.get("steps") or []) if isinstance(item, dict)]
    goals: List[str] = []
    rejected: List[str] = []
    for name in raw or []:
        name = str(name or "").strip()
        if not name:
            continue
        if name in ALLOWED_TOOLS:
            if name not in goals:
                goals.append(name)
        elif name not in rejected:
            rejected.append(name)
    return goals, rejected


class LLMReasoningLayer:
    """Planning facade.

    By default this uses deterministic rules. When an LLM provider is injected,
    it asks the provider for structured JSON and validates the result against
    the local tool registry.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None) -> None:
        self.llm_provider = llm_provider

    def plan(self, prompt: str) -> ExecutionPlan:
        if self.llm_provider:
            try:
                return self._plan_with_llm(prompt)
            except Exception as exc:
                fallback = self._plan_with_rules(prompt)
                fallback.clarifications.append("LLM planning failed; used local rule-based planner: %s" % exc)
                return fallback
        return self._plan_with_rules(prompt)

    def _plan_with_rules(self, prompt: str) -> ExecutionPlan:
        request = self._parse_request(prompt)
        goals: List[str] = []
        if request.wants_visualization or request.cell_types:
            goals.append("cell_type_distribution")
        if request.genes:
            goals.append("spatial_gene_expression")
        if request.wants_colocalization:
            goals.append("cell_type_colocalization")
        steps = build_steps(request, goals)
        if not steps:
            steps.append(
                ExecutionStep(
                    name="Default spatial summary",
                    tool="cell_type_distribution",
                    parameters={"cell_types": []},
                )
            )

        clarifications = []
        if not request.sample_id:
            clarifications.append("No sample ID was detected; the first sample in the dataset will be used.")
        if request.wants_colocalization and len(request.cell_types) < 2:
            clarifications.append("Co-localization works best when two cell types are specified.")
        return ExecutionPlan(request=request, steps=steps, clarifications=clarifications)

    def _plan_with_llm(self, prompt: str) -> ExecutionPlan:
        payload = self.llm_provider.generate_plan_json(prompt, PLANNER_SYSTEM_PROMPT)
        rule_request = self._parse_request(prompt)
        request = AnalysisRequest(
            raw_text=prompt,
            sample_id=str(payload.get("sample_id") or rule_request.sample_id or ""),
            cell_types=_string_list(payload.get("cell_types")) or rule_request.cell_types,
            genes=[gene.upper() for gene in _string_list(payload.get("genes"))] or rule_request.genes,
            wants_visualization=bool(payload.get("wants_visualization", rule_request.wants_visualization)),
            wants_colocalization=bool(payload.get("wants_colocalization", rule_request.wants_colocalization)),
            wants_report=True,
        )
        goals, rejected = goals_from_payload(payload)
        clarifications = _string_list(payload.get("clarifications"))
        if rejected:
            # Named, never skipped: a caller has to be able to tell the
            # difference between "the model asked for nothing" and "the model
            # asked for something this build does not have".
            clarifications.append(
                "No tool named %s in this build; those goals were dropped."
                % ", ".join("`%s`" % name for name in rejected))
        steps = build_steps(request, goals)
        if not steps:
            fallback = self._plan_with_rules(prompt)
            fallback.clarifications.extend(clarifications)
            fallback.clarifications.append(
                "The model named no goal this build can run; used the local rule-based planner.")
            return fallback
        return ExecutionPlan(request=request, steps=steps, clarifications=clarifications)

    def _parse_request(self, prompt: str) -> AnalysisRequest:
        lowered = prompt.lower()
        sample_id = self._extract_sample_id(prompt)
        cell_types = self._extract_cell_types(lowered)
        genes = self._extract_genes(prompt)
        return AnalysisRequest(
            raw_text=prompt,
            sample_id=sample_id,
            cell_types=cell_types,
            genes=genes,
            wants_visualization=any(token in lowered for token in ["show", "plot", "map", "visual", "distribution"]),
            wants_colocalization=any(
                token in lowered
                for token in [
                    "co-local",
                    "colocal",
                    "near",
                    "relative to",
                    "enriched near",
                    "neighborhood",
                    "neighbourhood",
                    "spatial relationship",
                    "compare",
                ]
            ),
            wants_report=True,
        )

    def _extract_sample_id(self, prompt: str) -> str:
        match = re.search(r"\bsample\s+([A-Za-z0-9_.-]+)", prompt, flags=re.IGNORECASE)
        if match:
            return match.group(1).rstrip(".,;:")
        match = re.search(r"\b([A-Z]{2,}[_-]\d+[A-Z0-9_-]*)\b", prompt)
        return match.group(1) if match else ""

    def _extract_cell_types(self, lowered: str) -> List[str]:
        found = []
        for token, canonical in CELL_TYPE_ALIASES.items():
            if token in lowered and canonical not in found:
                found.append(canonical)
        return found

    def _extract_genes(self, prompt: str) -> List[str]:
        genes = []
        for token in re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", prompt):
            if token in STOP_TOKENS or "_" in token:
                continue
            if token not in genes:
                genes.append(token)
        return genes


def _string_list(value: object) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []
