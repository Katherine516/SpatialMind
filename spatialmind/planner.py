import re
from typing import Dict, List, Optional

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
  "steps": [
    {
      "name": "short step name",
      "tool": "cell_type_distribution | spatial_gene_expression | cell_type_colocalization",
      "parameters": {"cell_types": ["..."], "genes": ["..."], "bin_size": 20.0},
      "depends_on": ["optional prior step name"]
    }
  ]
}

Use only these tools:
- cell_type_distribution: map/count requested cell types.
- spatial_gene_expression: summarize requested genes.
- cell_type_colocalization: test whether two cell types share spatial bins.

Prefer canonical cell types such as CD8+ T cell, Tumor cell, Macrophage, Endothelial cell, and Stromal cell.
"""


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
        steps: List[ExecutionStep] = []
        if request.wants_visualization or request.cell_types:
            steps.append(
                ExecutionStep(
                    name="Map cell-type distribution",
                    tool="cell_type_distribution",
                    parameters={"cell_types": request.cell_types},
                )
            )
        if request.genes:
            steps.append(
                ExecutionStep(
                    name="Summarize spatial gene expression",
                    tool="spatial_gene_expression",
                    parameters={"genes": request.genes},
                )
            )
        if request.wants_colocalization:
            steps.append(
                ExecutionStep(
                    name="Test cell-type co-localization",
                    tool="cell_type_colocalization",
                    parameters={"cell_types": request.cell_types, "bin_size": 20.0},
                    depends_on=["Map cell-type distribution"],
                )
            )
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
        steps = self._steps_from_llm_payload(payload, request)
        if not steps:
            return self._plan_with_rules(prompt)
        clarifications = _string_list(payload.get("clarifications"))
        return ExecutionPlan(request=request, steps=steps, clarifications=clarifications)

    def _steps_from_llm_payload(self, payload: Dict[str, object], request: AnalysisRequest) -> List[ExecutionStep]:
        steps = []
        for item in payload.get("steps", []):
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool", ""))
            if tool not in ALLOWED_TOOLS:
                continue
            parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
            parameters = dict(parameters)
            if tool in ("cell_type_distribution", "cell_type_colocalization"):
                parameters["cell_types"] = _string_list(parameters.get("cell_types")) or request.cell_types
            if tool == "spatial_gene_expression":
                parameters["genes"] = [gene.upper() for gene in _string_list(parameters.get("genes"))] or request.genes
            steps.append(
                ExecutionStep(
                    name=str(item.get("name") or tool.replace("_", " ").title()),
                    tool=tool,
                    parameters=parameters,
                    depends_on=_string_list(item.get("depends_on")),
                )
            )
        return steps

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
            wants_colocalization=any(token in lowered for token in ["co-local", "colocal", "near", "relative to", "enriched near"]),
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
