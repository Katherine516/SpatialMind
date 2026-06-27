import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..contracts import NoAnalysisResponse
from ..ingestion import DataIngestionLayer
from ..ingestion.readiness import build_readiness_report
from ..schemas import SpatialDataset, ToolResult
from ..tools import ToolRegistry, build_default_registry, build_mvp_registry
from ..tools.exceptions import ToolExecutionError
from .grounding import ClaimGroundingChecker


TOOL_DEPS = {
    "tumor_niche_analysis": ["cell_type_annotation"],
    "neighborhood_enrichment": ["cell_type_annotation"],
    "ligand_receptor_analysis": ["cell_type_annotation"],
    "motif_enrichment_spatial": ["chromatin_accessibility_spatial"],
    "niche_differential_analysis": ["spatial_clustering"],
    "spatial_communication_flow": ["cell_type_annotation"],
    "cnv_inference": [],
}

MODALITY_PROMPTS = {
    "spatial_transcriptomics": "Data is spatial transcriptomics. Use RNA tools; deconvolution depends on spot vs cell resolution.",
    "annotated_expression": "Data is AnnData-like expression with spatial coordinates. Validate annotation and gene naming before statistics.",
    "multiplexed_protein": "Data is protein imaging. Prefer protein_coexpression and cell_phenotyping_spatial over RNA tools.",
    "spatial_atac": "Data is chromatin accessibility. Use chromatin_accessibility_spatial and motif_enrichment_spatial.",
    "morphology_image": "Data is image-only morphology. Use tissue_segmentation before molecular spatial tools.",
}


@dataclass
class ToolCall:
    tool_name: str
    params: Dict[str, object]
    result: Optional[ToolResult]
    duration_seconds: float
    error: Optional[str] = None


@dataclass
class AgentResponse:
    session_id: str
    query: str
    tool_trace: List[ToolCall]
    result: Any
    interpretation: str
    clarification_needed: bool
    clarification_question: Optional[str]
    warnings: List[str] = field(default_factory=list)
    viz_paths: List[str] = field(default_factory=list)
    no_analysis_response: Optional[NoAnalysisResponse] = None


class SpatialAgent:
    """Phase-2 agent loop over the Phase-1 tool registry.

    This is a deterministic ReAct-style loop for local development. Hosted LLM
    planning can be added behind the planner boundary without changing the
    response contract expected by the eval harness.
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        ingestion: Optional[DataIngestionLayer] = None,
        mvp_mode: bool = False,
    ) -> None:
        self.mvp_mode = mvp_mode
        self.registry = registry or (build_mvp_registry() if mvp_mode else build_default_registry())
        self.ingestion = ingestion or DataIngestionLayer()
        self.grounding = ClaimGroundingChecker()

    def run(self, query: str, dataset_id: str, session_id: Optional[str] = None) -> AgentResponse:
        session = session_id or str(uuid.uuid4())
        if not dataset_id:
            return AgentResponse(
                session_id=session,
                query=query,
                tool_trace=[],
                result=None,
                interpretation="I need a dataset before I can run spatial analysis.",
                clarification_needed=True,
                clarification_question="Which dataset should I analyze?",
                warnings=[],
            )
        if self._query_is_ambiguous(query):
            return AgentResponse(
                session_id=session,
                query=query,
                tool_trace=[],
                result=None,
                interpretation="The query is underspecified.",
                clarification_needed=True,
                clarification_question="Which cell type, gene, or spatial metric should I focus on?",
                warnings=[],
            )

        dataset = self.ingestion.load(dataset_id)
        if self.mvp_mode:
            self._apply_mvp_query_assay_hints(query, dataset)
        planned = self._resolve_dependencies(self._plan_tools(query))
        readiness = build_readiness_report(dataset)
        blocked = self._blocked_by_readiness(planned, readiness)
        if blocked:
            reasons = ["%s: %s" % (item.workflow, item.reason) for item in blocked]
            no_analysis = NoAnalysisResponse(
                blocking_reasons=reasons,
                recommended_next_step=self._recommended_next_step(blocked),
                query=query,
                dataset_id=dataset_id,
            )
            return AgentResponse(
                session_id=session,
                query=query,
                tool_trace=[],
                result=no_analysis,
                interpretation="I cannot run this analysis yet because the dataset is not ready. %s"
                % no_analysis.recommended_next_step,
                clarification_needed=False,
                clarification_question=None,
                warnings=reasons + readiness.warnings,
                no_analysis_response=no_analysis,
            )
        tool_trace: List[ToolCall] = []
        warnings: List[str] = []
        for tool_name, params in planned:
            unmet = self.registry.check_preconditions(tool_name, dataset)
            if unmet:
                warning = "%s skipped because preconditions are unmet: %s" % (tool_name, "; ".join(unmet))
                warnings.append(warning)
                tool_trace.append(ToolCall(tool_name, params, None, 0.0, error=warning))
                continue
            tool = self.registry.get(tool_name)
            if tool.estimated_runtime.startswith("slow"):
                warnings.append("%s is estimated as %s; prototype ran a lightweight substitute." % (tool_name, tool.estimated_runtime))
            started = time.monotonic()
            try:
                result = tool.run(dataset, params)
                duration = time.monotonic() - started
                tool_trace.append(ToolCall(tool_name, params, result, round(duration, 4)))
                warnings.extend(result.caveats)
            except ToolExecutionError as exc:
                duration = time.monotonic() - started
                warnings.append(str(exc))
                tool_trace.append(ToolCall(tool_name, params, None, round(duration, 4), error=str(exc)))

        successful = [call.result for call in tool_trace if call.result is not None]
        interpretation = self.grounding.soften_interpretation(self._interpret(query, successful, warnings), successful)
        return AgentResponse(
            session_id=session,
            query=query,
            tool_trace=tool_trace,
            result=successful[-1] if successful else None,
            interpretation=interpretation,
            clarification_needed=False,
            clarification_question=None,
            warnings=_dedupe(warnings),
            viz_paths=[],
        )

    def _build_system_prompt(self) -> str:
        lines = [
            "You are SpatialMind, a spatial omics analysis agent.",
            "Always choose tools from the registry; never invent statistics.",
            "Check preconditions before executing tools.",
            "Flag uncertainty and caveats in plain language.",
            "Never claim significance unless a statistical test result exists.",
            "Available tools:",
        ]
        for tool in self.registry.list_all():
            lines.append("- %s: %s Use: %s Avoid: %s" % (tool.name, tool.description, tool.when_to_use, tool.when_not_to_use))
        return "\n".join(lines)

    def _build_modality_context(self, dataset: SpatialDataset) -> str:
        return MODALITY_PROMPTS.get(dataset.modality, "Data modality is not recognized; require stricter precondition checks.")

    def _check_preconditions(self, planned_tools: List[str], dataset: SpatialDataset) -> List[str]:
        issues = []
        for tool_name in planned_tools:
            issues.extend(self.registry.check_preconditions(tool_name, dataset))
        return issues

    def _query_is_ambiguous(self, query: str) -> bool:
        lowered = query.lower().strip()
        return lowered in {"analyze this", "run analysis", "look at this", "what do you see"}

    def _plan_tools(self, query: str) -> List[tuple[str, Dict[str, object]]]:
        if self.mvp_mode:
            return self._plan_mvp_tools(query)
        lowered = query.lower()
        planned: List[tuple[str, Dict[str, object]]] = []
        wants_deconvolution = any(token in lowered for token in ["deconvolution", "proportion", "abundance"])
        if not wants_deconvolution and any(
            token in lowered for token in ["where", "show", "map", "visual", "cell type", "t cell", "cd8", "tumor"]
        ):
            planned.append(("cell_type_annotation", {"method": "existing_labels"}))
        if any(token in lowered for token in ["near", "co-local", "colocal", "neighborhood", "enrichment"]):
            planned.append(("neighborhood_enrichment", {"radius": 18.0}))
        if any(token in lowered for token in ["spatially variable", "variable genes", "vary across", "svg"]):
            planned.append(("spatial_variable_genes", {"n_top": 25}))
        if wants_deconvolution:
            planned.append(("spatial_deconvolution", {"method": "label_proportions"}))
        if any(token in lowered for token in ["ligand", "receptor", "signaling", "crosstalk", "communicate"]):
            planned.append(("ligand_receptor_analysis", {"db": "cellchat"}))
        if any(token in lowered for token in ["trajectory", "pseudotime", "differentiation"]):
            planned.append(("trajectory_inference", {"root_cell_type": _first_cell_type_hint(lowered)}))
        if any(token in lowered for token in ["cluster", "domain", "tissue domain", "discover spatial"]):
            planned.append(("spatial_clustering", {"resolution": 0.5}))
        if any(token in lowered for token in ["differential", "upregulated", "downregulated", " vs "]):
            planned.append(
                (
                    "differential_expression",
                    {"group_key": "cell_type", "group1": "CD8+ T cell", "group2": "Tumor cell"},
                )
            )
        if not planned:
            planned.append(("cell_type_annotation", {"method": "existing_labels"}))
        return planned

    def _plan_mvp_tools(self, query: str) -> List[tuple[str, Dict[str, object]]]:
        lowered = query.lower()
        if any(
            token in lowered
            for token in ["deconvolution", "ligand", "receptor", "pathway", "cnv", "trajectory", "pseudotime", "lineage", "motif", "chromvar"]
        ):
            return [("deferred_v1_workflow", {})]
        if any(token in lowered for token in ["transfer", "reference", "label transfer"]):
            return [
                ("qc_and_cluster", {"resolution": 0.5}),
                ("marker_detection", {"group_key": "cell_type", "group1": "CD8+ T cell", "group2": "Tumor cell"}),
                ("annotation", {"method": "reference_assist"}),
            ]
        planned: List[tuple[str, Dict[str, object]]] = [("qc_and_cluster", {"resolution": 0.5})]
        if any(token in lowered for token in ["annotate", "cell type", "label"]):
            planned.append(("annotation", {"method": "existing_labels"}))
        if any(token in lowered for token in ["marker", "differential", "upregulated", "de ", "tf", "accessibility"]):
            planned.append(
                (
                    "marker_detection",
                    {"group_key": "cell_type", "group1": "CD8+ T cell", "group2": "Tumor cell"},
                )
            )
        if any(token in lowered for token in ["region", "regions", "tumor core", "margin", "stroma"]):
            planned.append(("region_summary", {"top_n_features": 8}))
        if any(token in lowered for token in ["near", "co-located", "colocated", "neighborhood", "adjacent"]):
            planned.append(("cell_neighborhood_enrichment", {"n_neighs": 6}))
        if any(token in lowered for token in ["overlay", "show gene", "feature"]):
            planned.append(("feature_overlay", {}))
        return _dedupe_planned(planned)

    def _resolve_dependencies(self, planned: List[tuple[str, Dict[str, object]]]) -> List[tuple[str, Dict[str, object]]]:
        resolved: List[tuple[str, Dict[str, object]]] = []
        seen = set()
        params_by_tool = {tool_name: params for tool_name, params in planned}
        for tool_name, params in planned:
            for dependency in TOOL_DEPS.get(tool_name, []):
                if dependency not in seen:
                    resolved.append((dependency, params_by_tool.get(dependency, {"method": "existing_labels"})))
                    seen.add(dependency)
            if tool_name not in seen:
                resolved.append((tool_name, params))
                seen.add(tool_name)
        return resolved

    def _blocked_by_readiness(self, planned: List[tuple[str, Dict[str, object]]], readiness: Any) -> List[Any]:
        blocked = []
        seen = set()
        for tool_name, _params in planned:
            workflow = TOOL_TO_WORKFLOW.get(tool_name, tool_name)
            if workflow in seen:
                continue
            seen.add(workflow)
            if not self.mvp_mode and workflow in {"spatial_deconvolution", "deferred_v1_workflow"}:
                continue
            status = readiness.workflow_status(workflow)
            if status.status == "blocked":
                blocked.append(status)
        return blocked

    def _recommended_next_step(self, blocked: List[Any]) -> str:
        reasons = " ".join(item.reason.lower() for item in blocked)
        if "cell-type" in reasons or "labels" in reasons:
            return "Run or provide cell-type annotation, then rerun the requested workflow."
        if "normalized" in reasons:
            return "Run ingestion normalization/QC first, then approve the dataset for analysis."
        if "coordinates" in reasons:
            return "Provide spatial coordinates or a supported spatial file format before analysis."
        if "protein" in reasons:
            return "Use a proteomics-compatible workflow or provide a protein marker matrix."
        return "Resolve the listed readiness blockers and rerun the analysis."

    def _apply_mvp_query_assay_hints(self, query: str, dataset: SpatialDataset) -> None:
        lowered = query.lower()
        if "xenium" in lowered:
            dataset.modality = "xenium_spatial_rna"
            dataset.metadata["assay_subtype"] = "xenium_spatial_rna"
            dataset.metadata["feature_type"] = "targeted_panel"
            dataset.metadata["resolution"] = "subcellular"
            dataset.metadata["is_targeted_panel"] = True
        elif "scatac" in lowered or "atac" in lowered:
            dataset.modality = "scatac"
            dataset.metadata["assay_subtype"] = "scatac_gene_activity"
            dataset.metadata["feature_type"] = "gene_activity"
            dataset.metadata["resolution"] = "single_cell"
        elif "scrna" in lowered or "single-cell rna" in lowered:
            dataset.modality = "scrna"
            dataset.metadata["assay_subtype"] = "scrna"
            dataset.metadata["feature_type"] = "gene_counts"
            dataset.metadata["resolution"] = "single_cell"

    def _interpret(self, query: str, results: List[ToolResult], warnings: List[str]) -> str:
        if not results:
            return "No tools completed successfully, so I cannot support a biological conclusion yet."
        sentences = [result.summary for result in results]
        if any("pval" in str(result.metrics).lower() or "p_value" in str(result.metrics).lower() for result in results):
            sentences.append("Any significance language should be read from the reported p-values, not inferred from the plot alone.")
        if warnings:
            sentences.append("Caveats: %s" % "; ".join(_dedupe(warnings)[:3]))
        return " ".join(sentences)


def _first_cell_type_hint(lowered_query: str) -> Optional[str]:
    if "cd8" in lowered_query or "t cell" in lowered_query:
        return "CD8+ T cell"
    if "tumor" in lowered_query:
        return "Tumor cell"
    return None


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _dedupe_planned(planned: List[tuple[str, Dict[str, object]]]) -> List[tuple[str, Dict[str, object]]]:
    seen = set()
    result = []
    for tool_name, params in planned:
        if tool_name not in seen:
            seen.add(tool_name)
            result.append((tool_name, params))
    return result


TOOL_TO_WORKFLOW = {
    "cell_type_annotation": "spatial_visualization",
    "spatial_deconvolution": "spatial_deconvolution",
    "spatial_variable_genes": "spatial_variable_genes",
    "neighborhood_enrichment": "neighborhood_enrichment",
    "ligand_receptor_analysis": "neighborhood_enrichment",
    "trajectory_inference": "spatial_clustering",
    "spatial_clustering": "spatial_clustering",
    "differential_expression": "differential_expression",
    "marker_detection": "marker_detection",
    "cnv_inference": "cnv_inference",
    "tumor_niche_analysis": "neighborhood_enrichment",
    "protein_coexpression": "protein_coexpression",
    "cell_phenotyping_spatial": "protein_coexpression",
    "chromatin_accessibility_spatial": "chromatin_accessibility_spatial",
    "motif_enrichment_spatial": "chromatin_accessibility_spatial",
    "niche_differential_analysis": "niche_differential_analysis",
    "qc_and_cluster": "qc_and_cluster",
    "annotation": "annotation",
    "feature_overlay": "feature_overlay",
    "motif_tf_activity": "motif_tf_activity",
    "cell_neighborhood_enrichment": "cell_neighborhood_enrichment",
    "region_summary": "region_summary",
    "reference_label_transfer": "reference_label_transfer",
    "deferred_v1_workflow": "deferred_v1_workflow",
}
