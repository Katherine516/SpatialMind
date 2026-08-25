from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from spatialmind.contracts import MethodCitation, ResourceProfile
from spatialmind.schemas import SpatialDataset, ToolResult

from . import implementations


ToolCallable = Callable[[SpatialDataset, Dict[str, object]], ToolResult]
MVP_TOOL_NAMES = [
    "qc_and_cluster",
    "annotation",
    "marker_detection",
    "spatial_variable_genes",
    "feature_overlay",
    "region_summary",
    "cell_neighborhood_enrichment",
]


CAPABILITY_STATES = ("validated", "descriptive", "experimental", "unavailable")
# Capabilities a planner may select from; scaffolds are excluded.
PLANNABLE_CAPABILITIES = ("validated", "descriptive", "experimental")


def _is_scaffold(func: Any) -> bool:
    """True when the tool body only returns a registered scaffold placeholder."""
    try:
        import inspect

        source = inspect.getsource(func)
    except (OSError, TypeError):
        return False
    return "_scaffold_result(" in source


@dataclass
class SpatialTool:
    name: str
    description: str
    when_to_use: str
    when_not_to_use: str
    input_schema: Dict[str, object]
    output_schema: Dict[str, object]
    preconditions: List[str]
    estimated_runtime: str
    callable: ToolCallable
    resource_profile: Optional[ResourceProfile] = None
    citation: Optional[MethodCitation] = None
    # validated    : real backend, allowed to support biological claims
    # descriptive  : real backend, describes data-derived groups only
    # experimental : real method, not yet trusted for claims
    # unavailable  : registered scaffold; must never be planned or presented as usable
    capability: str = "validated"

    def __post_init__(self) -> None:
        if self.capability == "validated" and _is_scaffold(self.callable):
            # A scaffold returns a placeholder rather than doing the work. Marking
            # it automatically keeps the registry honest even if a caller forgets.
            self.capability = "unavailable"
        if self.capability not in CAPABILITY_STATES:
            raise ValueError("Unknown capability %r for tool %s" % (self.capability, self.name))
        if self.resource_profile is None:
            self.resource_profile = _resource_profile_from_runtime(self.estimated_runtime)
        if self.citation is None:
            self.citation = _default_citation(self.name)

    def run(self, dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
        result = self.callable(dataset, params)
        return implementations.attach_quality_metrics(result, dataset, params)


class ToolRegistry:
    def __init__(self, tools: List[SpatialTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> SpatialTool:
        if name not in self._tools:
            raise KeyError("Unknown tool: %s" % name)
        return self._tools[name]

    def list_plannable(self) -> List[SpatialTool]:
        """Tools a planner may choose. Excludes unavailable scaffolds."""
        return [tool for tool in self.list_all() if tool.capability in PLANNABLE_CAPABILITIES]

    def capability_summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for tool in self.list_all():
            counts[tool.capability] = counts.get(tool.capability, 0) + 1
        return counts

    def list_all(self) -> List[SpatialTool]:
        return [self._tools[name] for name in sorted(self._tools.keys())]

    def to_anthropic_tools(self, plannable_only: bool = True) -> List[Dict[str, object]]:
        """Tool schemas for an LLM. Scaffolds are hidden by default so a model
        cannot select a tool that does no work."""
        return [
            {
                "name": tool.name,
                "description": "%s When to use: %s When not to use: %s"
                % (tool.description, tool.when_to_use, tool.when_not_to_use),
                "input_schema": tool.input_schema,
            }
            for tool in (self.list_plannable() if plannable_only else self.list_all())
        ]

    def citations(self) -> Dict[str, MethodCitation]:
        return {tool.name: tool.citation for tool in self.list_all() if tool.citation is not None}

    def check_preconditions(self, tool_name: str, dataset: SpatialDataset) -> List[str]:
        tool = self.get(tool_name)
        unmet = []
        for precondition in tool.preconditions:
            lowered = precondition.lower()
            if "cell-type labels" in lowered and not dataset.cell_types:
                unmet.append(precondition)
            if "normalized counts" in lowered and not dataset.normalized:
                unmet.append(precondition)
            if "protein matrix" in lowered and dataset.modality not in {"multiplexed_protein", "protein_imaging"}:
                unmet.append(precondition)
            if "atac" in lowered and dataset.modality not in {"scatac", "spatial_atac", "chromatin_accessibility"}:
                unmet.append(precondition)
            if "image input" in lowered and dataset.modality not in {"morphology_image", "he_image"}:
                unmet.append(precondition)
            if "region labels" in lowered and not any(record.region for record in dataset.records):
                unmet.append(precondition)
            if "multiple samples" in lowered:
                unmet.append(precondition)
            if "spatial coords" in lowered:
                bounds = dataset.bounds()
                if bounds["max_x"] == bounds["min_x"] and bounds["max_y"] == bounds["min_y"]:
                    unmet.append(precondition)
        return unmet


def build_default_registry() -> ToolRegistry:
    return build_full_registry()


def build_mvp_registry() -> ToolRegistry:
    return ToolRegistry([tool for tool in _mvp_tools()])


def build_full_registry() -> ToolRegistry:
    tools = [
            SpatialTool(
                name="qc_and_cluster",
                description="Run per-assay QC and Leiden-style clustering on any MVP cell-by-feature matrix.",
                when_to_use="Use as the first step in scRNA, scATAC, and Xenium standalone workflows.",
                when_not_to_use="Do not use for direct co-localization; use cell_neighborhood_enrichment after annotation.",
                input_schema=_object_schema({"resolution": {"type": "number", "default": 0.5}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts"],
                estimated_runtime="medium 1-10min",
                callable=implementations.qc_and_cluster,
            ),
            SpatialTool(
                name="annotation",
                description="Annotate cell clusters or reuse existing labels with assay-aware caveats.",
                when_to_use="Use after qc_and_cluster or when labels are needed for downstream workflows.",
                when_not_to_use="Do not treat scATAC annotation as measured RNA expression.",
                input_schema=_object_schema({"method": {"type": "string", "default": "existing_labels"}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts"],
                estimated_runtime="fast <1min",
                callable=implementations.annotation,
            ),
            SpatialTool(
                name="feature_overlay",
                description="Overlay a measured feature, gene activity score, or targeted-panel feature on embedding or tissue.",
                when_to_use="Use for single-feature visualization in any MVP assay.",
                when_not_to_use="Do not claim panel-absent Xenium genes are unexpressed.",
                input_schema=_object_schema({"feature": {"type": "string"}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts"],
                estimated_runtime="fast <1min",
                callable=implementations.feature_overlay,
            ),
            SpatialTool(
                name="marker_detection",
                description="Detect cluster/group markers using adjusted-p-value outputs; scATAC markers are gene-activity markers only.",
                when_to_use="Use for scRNA/scATAC lite marker analysis and MVP marker/DE requests.",
                when_not_to_use="Do not use to infer motif activity or causal regulation.",
                input_schema=_object_schema(
                    {
                        "group_key": {"type": "string", "default": "cell_type"},
                        "group1": {"type": "string"},
                        "group2": {"type": "string"},
                    }
                ),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts"],
                estimated_runtime="fast <1min",
                callable=implementations.marker_detection,
            ),
            SpatialTool(
                name="motif_tf_activity",
                description="Estimate TF motif/activity patterns from scATAC gene-activity or peak features.",
                when_to_use="Use for scATAC standalone analysis and regulatory-driver questions.",
                when_not_to_use="Do not use on RNA data; use annotation or differential_expression instead.",
                input_schema=_object_schema({"method": {"type": "string", "default": "chromvar_style"}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires ATAC peak matrix"],
                estimated_runtime="medium 1-10min",
                callable=implementations.motif_tf_activity,
            ),
            SpatialTool(
                name="cell_neighborhood_enrichment",
                description="Run cell-level neighborhood enrichment for Xenium spatial RNA.",
                when_to_use="Use for Xenium co-location and adjacency questions after labels exist.",
                when_not_to_use="Do not use on non-spatial scRNA/scATAC references.",
                input_schema=_object_schema(
                    {
                        "n_neighs": {"type": "integer", "default": 6},
                        "n_perms": {"type": "integer", "default": 250},
                        "random_state": {"type": "integer", "default": 0},
                        "include_all_pairs": {"type": "boolean", "default": True},
                    }
                ),
                output_schema=_tool_result_schema(),
                preconditions=["requires cell-type labels", "requires spatial coords"],
                estimated_runtime="medium 1-10min",
                callable=implementations.cell_neighborhood_enrichment,
            ),
            SpatialTool(
                name="region_summary",
                description="Summarize cell types, feature means, and QC information for user-provided Xenium regions.",
                when_to_use="Use for Xenium region questions after the user supplies region labels.",
                when_not_to_use="Do not use for image-derived or polygon-derived regions in the MVP.",
                input_schema=_object_schema({"top_n_features": {"type": "integer", "default": 8}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires region labels"],
                estimated_runtime="fast <1min",
                callable=implementations.region_summary,
            ),
            SpatialTool(
                name="reference_label_transfer",
                description="Transfer labels from a scRNA/scATAC reference onto Xenium over shared features with confidence.",
                when_to_use="Use only in integration mode when a labeled reference and Xenium target share enough features.",
                when_not_to_use="Do not use when shared features are too few; request a matched reference.",
                input_schema=_object_schema({"reference_features": {"type": "array", "items": {"type": "string"}}, "min_shared_features": {"type": "integer", "default": 5}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts"],
                estimated_runtime="medium 1-10min",
                callable=implementations.reference_label_transfer,
            ),
            SpatialTool(
                name="cell_type_annotation",
                description="Assign or validate cell-type labels for each spot or cell.",
                when_to_use="Use when the user asks what cell types are present or where specific cell types are.",
                when_not_to_use="Do not use when the query is only about gene-level differential expression.",
                input_schema=_object_schema({"method": {"type": "string", "default": "existing_labels"}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts"],
                estimated_runtime="fast <1min",
                callable=implementations.cell_type_annotation,
            ),
            SpatialTool(
                name="spatial_deconvolution",
                description="Estimate cell-type proportions for each spot or region.",
                when_to_use="Use when the user wants abundance maps or proportions from mixed Visium spots.",
                when_not_to_use="Do not use when spot/cell-level labels are already sufficient.",
                input_schema=_object_schema({"method": {"type": "string", "default": "label_proportions"}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts", "requires cell-type labels"],
                estimated_runtime="slow >10min",
                callable=implementations.spatial_deconvolution,
            ),
            SpatialTool(
                name="spatial_variable_genes",
                description="Identify genes with spatially structured expression.",
                when_to_use="Use when the user asks which genes vary across tissue space.",
                when_not_to_use="Do not use for group-vs-group differential expression.",
                input_schema=_object_schema({"n_top": {"type": "integer", "default": 50}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts", "requires spatial coords"],
                estimated_runtime="medium 1-10min",
                callable=implementations.spatial_variable_genes,
            ),
            SpatialTool(
                name="neighborhood_enrichment",
                description="Test which cell-type pairs are spatial neighbors or co-localized.",
                when_to_use="Use for clustering, co-localization, neighborhoods, or spatial organization of cell types.",
                when_not_to_use="Do not use to compare gene expression between conditions.",
                input_schema=_object_schema({"radius": {"type": "number", "default": 18.0}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires cell-type labels", "requires spatial coords"],
                estimated_runtime="medium 1-10min",
                callable=implementations.neighborhood_enrichment,
            ),
            SpatialTool(
                name="ligand_receptor_analysis",
                description="Predict cell-cell communication through ligand-receptor co-expression.",
                when_to_use="Use for signaling, crosstalk, or communication questions.",
                when_not_to_use="Do not use for simple spatial visualization.",
                input_schema=_object_schema({"db": {"type": "string", "default": "cellchat"}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires cell-type labels", "requires spatial coords", "requires normalized counts"],
                estimated_runtime="slow >10min",
                callable=implementations.ligand_receptor_analysis,
            ),
            SpatialTool(
                name="trajectory_inference",
                description="Compute pseudotime-like progression values anchored to tissue space.",
                when_to_use="Use for trajectory, differentiation, development, or state transition questions.",
                when_not_to_use="Do not use for static co-localization questions.",
                input_schema=_object_schema({"root_cell_type": {"type": "string"}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts", "requires spatial coords"],
                estimated_runtime="medium 1-10min",
                callable=implementations.trajectory_inference,
            ),
            SpatialTool(
                name="spatial_clustering",
                description="Find unsupervised spatial tissue domains.",
                when_to_use="Use when the user asks to discover tissue domains, regions, or structures.",
                when_not_to_use="Do not use when the user asks for known cell-type locations.",
                input_schema=_object_schema({"resolution": {"type": "number", "default": 0.5}}),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts", "requires spatial coords"],
                estimated_runtime="medium 1-10min",
                callable=implementations.spatial_clustering,
            ),
            SpatialTool(
                name="differential_expression",
                description="Find genes upregulated between two groups.",
                when_to_use="Use for 'upregulated in X vs Y' questions.",
                when_not_to_use="Do not use for spatially variable gene discovery.",
                input_schema=_object_schema(
                    {
                        "group_key": {"type": "string", "default": "cell_type"},
                        "group1": {"type": "string"},
                        "group2": {"type": "string"},
                    }
                ),
                output_schema=_tool_result_schema(),
                preconditions=["requires normalized counts"],
                estimated_runtime="fast <1min",
                callable=implementations.differential_expression,
            ),
    ]
    tools.extend(_v2_tools())
    return ToolRegistry(tools)


def _mvp_tools() -> List[SpatialTool]:
    full = build_full_registry()
    return [full.get(name) for name in MVP_TOOL_NAMES]


def _v2_tools() -> List[SpatialTool]:
    return [
        SpatialTool(
            name="cnv_inference",
            description="Infer copy number variation from expression to identify aneuploid or malignant cells.",
            when_to_use="Use for cancer datasets when malignant cells are not defined by a trusted marker panel.",
            when_not_to_use="Do not use instead of tumor_niche_analysis; run cnv_inference first, then tumor_niche_analysis.",
            input_schema=_object_schema({"ref_normal_key": {"type": "string"}, "normal_ref_count": {"type": "integer", "default": 0}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires normalized counts"],
            estimated_runtime="slow >10min",
            callable=implementations.cnv_inference,
        ),
        SpatialTool(
            name="tumor_niche_analysis",
            description="Characterize tumor microenvironment composition, exclusion, fibroblast density, and vascular proximity.",
            when_to_use="Use after tumor or malignant labels exist and the user asks about tumor niche or microenvironment structure.",
            when_not_to_use="Do not use for malignant-cell discovery; use cnv_inference first when tumor labels are missing.",
            input_schema=_object_schema({"tumor_label": {"type": "string"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires cell-type labels", "requires spatial coords"],
            estimated_runtime="medium 1-10min",
            callable=implementations.tumor_niche_analysis,
        ),
        SpatialTool(
            name="protein_coexpression",
            description="Compute pairwise protein marker co-expression and marker modules for IMC/CODEX data.",
            when_to_use="Use for protein imaging marker panels when the question asks about protein co-expression.",
            when_not_to_use="Do not use for RNA gene expression; use spatial_variable_genes or differential_expression instead.",
            input_schema=_object_schema({"markers": {"type": "array", "items": {"type": "string"}}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires protein matrix"],
            estimated_runtime="fast <1min",
            callable=implementations.protein_coexpression,
        ),
        SpatialTool(
            name="cell_phenotyping_spatial",
            description="Assign protein-imaging phenotypes from marker intensity patterns and map them spatially.",
            when_to_use="Use for IMC/CODEX phenotyping and spatial phenotype maps.",
            when_not_to_use="Do not use for RNA annotation; use cell_type_annotation instead.",
            input_schema=_object_schema({"panel_type": {"type": "string", "default": "immune"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires protein matrix", "requires spatial coords"],
            estimated_runtime="medium 1-10min",
            callable=implementations.cell_phenotyping_spatial,
        ),
        SpatialTool(
            name="pathway_activity",
            description="Infer pathway activity scores such as MAPK, PI3K, TGFb, and immune signaling per cell or spot.",
            when_to_use="Use when the question asks about pathway activation or signaling state maps.",
            when_not_to_use="Do not use for ligand-receptor pair inference; use spatial_communication_flow or ligand_receptor_analysis.",
            input_schema=_object_schema({"resource": {"type": "string", "default": "progeny"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires normalized counts"],
            estimated_runtime="medium 1-10min",
            callable=implementations.pathway_activity,
        ),
        SpatialTool(
            name="transcription_factor_activity",
            description="Infer transcription factor activity from target gene expression networks.",
            when_to_use="Use when the user asks about regulatory drivers or TF activity across tissue.",
            when_not_to_use="Do not use for ATAC motif enrichment; use motif_enrichment_spatial after chromatin_accessibility_spatial.",
            input_schema=_object_schema({"network": {"type": "string", "default": "collectri"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires normalized counts"],
            estimated_runtime="medium 1-10min",
            callable=implementations.transcription_factor_activity,
        ),
        SpatialTool(
            name="spatial_communication_flow",
            description="Run consensus directional ligand-receptor communication analysis with cross-method confidence scores.",
            when_to_use="Use for high-confidence cell-cell communication questions requiring multi-method consensus.",
            when_not_to_use="Do not use for simple ligand/receptor marker inspection; use ligand_receptor_analysis for a lighter analysis.",
            input_schema=_object_schema({"method": {"type": "string", "default": "liana"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires cell-type labels", "requires spatial coords", "requires normalized counts"],
            estimated_runtime="slow >10min",
            callable=implementations.spatial_communication_flow,
        ),
        SpatialTool(
            name="niche_differential_analysis",
            description="Compare expression within matched spatial niches across conditions.",
            when_to_use="Use when the user asks for treated-vs-control or condition comparisons within spatial niches.",
            when_not_to_use="Do not use for ordinary group differential expression; use differential_expression instead.",
            input_schema=_object_schema({"niche_key": {"type": "string"}, "condition_key": {"type": "string"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires normalized counts", "requires region labels"],
            estimated_runtime="medium 1-10min",
            callable=implementations.niche_differential_analysis,
        ),
        SpatialTool(
            name="chromatin_accessibility_spatial",
            description="Identify differentially accessible chromatin regions by spatial region or cluster.",
            when_to_use="Use for spatial ATAC data and peak accessibility questions.",
            when_not_to_use="Do not use for RNA gene expression; use spatial_variable_genes or differential_expression.",
            input_schema=_object_schema({"peak_matrix": {"type": "string"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires ATAC peak matrix", "requires spatial coords"],
            estimated_runtime="medium 1-10min",
            callable=implementations.chromatin_accessibility_spatial,
        ),
        SpatialTool(
            name="motif_enrichment_spatial",
            description="Find enriched TF motifs in differentially accessible peaks per spatial region.",
            when_to_use="Use after chromatin_accessibility_spatial when the user asks what TF motifs explain DA peaks.",
            when_not_to_use="Do not use directly on RNA expression; use transcription_factor_activity for RNA-derived TF activity.",
            input_schema=_object_schema({"da_peaks_key": {"type": "string"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires ATAC peak matrix"],
            estimated_runtime="medium 1-10min",
            callable=implementations.motif_enrichment_spatial,
        ),
        SpatialTool(
            name="multi_sample_comparison",
            description="Compare a spatial metric across multiple samples or conditions with sample-level statistics.",
            when_to_use="Use for cohort or condition comparisons across multiple spatial datasets.",
            when_not_to_use="Do not use for one sample; use the matching single-sample tool such as neighborhood_enrichment.",
            input_schema=_object_schema({"metric": {"type": "string"}, "group_key": {"type": "string"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires multiple samples"],
            estimated_runtime="medium 1-10min",
            callable=implementations.multi_sample_comparison,
        ),
        SpatialTool(
            name="tissue_segmentation",
            description="Segment cells or tissue regions from H&E or immunofluorescence images.",
            when_to_use="Use when image-only data needs cell masks or coordinates before spatial analysis.",
            when_not_to_use="Do not use when segmentation is already provided by Xenium/CODEX; use existing cell boundaries.",
            input_schema=_object_schema({"model": {"type": "string", "default": "cellpose"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires image input"],
            estimated_runtime="slow >10min",
            callable=implementations.tissue_segmentation,
        ),
        SpatialTool(
            name="spatial_gene_programs",
            description="Decompose spatial expression into interpretable co-expressed gene programs.",
            when_to_use="Use when the user asks about gene modules, programs, or spatial expression factors.",
            when_not_to_use="Do not use for single-gene maps; use expression_overlay visualization or spatial_gene_expression.",
            input_schema=_object_schema({"n_programs": {"type": "integer", "default": 10}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires normalized counts", "requires spatial coords"],
            estimated_runtime="medium 1-10min",
            callable=implementations.spatial_gene_programs,
        ),
        SpatialTool(
            name="cell_abundance_heatmap_regions",
            description="Quantify cell-type or marker abundance within manually or automatically defined tissue regions.",
            when_to_use="Use when the user asks for abundance by tumor core, margin, stroma, or other region labels.",
            when_not_to_use="Do not use for free-form co-localization; use neighborhood_enrichment for pairwise adjacency.",
            input_schema=_object_schema({"region_annotations": {"type": "string"}}),
            output_schema=_tool_result_schema(),
            preconditions=["requires cell-type labels", "requires region labels"],
            estimated_runtime="fast <1min",
            callable=implementations.cell_abundance_heatmap_regions,
        ),
    ]


def _object_schema(properties: Dict[str, object]) -> Dict[str, object]:
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _tool_result_schema() -> Dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "metrics": {"type": "object"},
            "quality_metrics": {"type": "object"},
            "caveats": {"type": "array", "items": {"type": "string"}},
        },
    }


def _resource_profile_from_runtime(estimated_runtime: str) -> ResourceProfile:
    if estimated_runtime.startswith("slow"):
        return ResourceProfile(runtime="slow", memory="high", gpu_required=False, internet_required=False)
    if estimated_runtime.startswith("medium"):
        return ResourceProfile(runtime="medium", memory="medium", gpu_required=False, internet_required=False)
    return ResourceProfile(runtime="fast", memory="low", gpu_required=False, internet_required=False)


def _default_citation(tool_name: str) -> MethodCitation:
    citations = {
        "differential_expression": MethodCitation(
            method_name="Scanpy rank_genes_groups",
            paper_citation="Wolf, Angerer, and Theis, Genome Biology 2018",
            documentation_url="https://scanpy.readthedocs.io/",
            default_params={"method": "wilcoxon", "group_key": "cell_type"},
        ),
        "marker_detection": MethodCitation(
            method_name="Scanpy rank_genes_groups marker detection",
            paper_citation="Wolf, Angerer, and Theis, Genome Biology 2018",
            documentation_url="https://scanpy.readthedocs.io/",
            default_params={"method": "wilcoxon", "group_key": "cell_type"},
        ),
        "qc_and_cluster": MethodCitation(
            method_name="Per-assay QC + Leiden clustering",
            paper_citation="Wolf, Angerer, and Theis, Genome Biology 2018; Traag et al., Scientific Reports 2019",
            documentation_url="https://scanpy.readthedocs.io/",
            default_params={"resolution": 0.5},
        ),
        "annotation": MethodCitation(
            method_name="CellTypist/marker annotation or existing-label validation",
            paper_citation="Dominguez Conde et al., Science 2022",
            documentation_url="https://celltypist.readthedocs.io/",
            default_params={"method": "existing_labels"},
        ),
        "feature_overlay": MethodCitation(
            method_name="Feature overlay",
            paper_citation="SpatialMind MVP renderer over measured feature values",
            documentation_url="",
            default_params={},
        ),
        "motif_tf_activity": MethodCitation(
            method_name="chromVAR-style motif/TF activity",
            paper_citation="Schep et al., Nature Methods 2017",
            documentation_url="https://greenleaflab.github.io/chromVAR/",
            default_params={"method": "chromvar_style"},
        ),
        "cell_neighborhood_enrichment": MethodCitation(
            method_name="Squidpy neighborhood enrichment",
            paper_citation="Palla et al., Nature Methods 2022",
            documentation_url="https://squidpy.readthedocs.io/",
            default_params={"n_perms": 100, "n_neighs": 6},
        ),
        "region_summary": MethodCitation(
            method_name="User-region composition and feature summary",
            paper_citation="SpatialMind MVP region summary over user-provided labels",
            documentation_url="",
            default_params={"top_n_features": 8},
        ),
        "reference_label_transfer": MethodCitation(
            method_name="Reference label transfer over shared features",
            paper_citation="Scanpy ingest/scANVI-style label transfer",
            documentation_url="https://scanpy.readthedocs.io/",
            default_params={"min_shared_features": 5},
        ),
        "spatial_clustering": MethodCitation(
            method_name="Scanpy neighbors + Leiden",
            paper_citation="Wolf, Angerer, and Theis, Genome Biology 2018; Traag et al., Scientific Reports 2019",
            documentation_url="https://scanpy.readthedocs.io/",
            default_params={"resolution": 0.5},
        ),
        "spatial_variable_genes": MethodCitation(
            method_name="Scanpy highly_variable_genes",
            paper_citation="Wolf, Angerer, and Theis, Genome Biology 2018",
            documentation_url="https://scanpy.readthedocs.io/",
            default_params={"n_top": 50},
        ),
        "neighborhood_enrichment": MethodCitation(
            method_name="Squidpy neighborhood enrichment",
            paper_citation="Palla et al., Nature Methods 2022",
            documentation_url="https://squidpy.readthedocs.io/",
            default_params={"n_perms": 100, "n_neighs": 6},
        ),
        "cell_type_annotation": MethodCitation(
            method_name="CellTypist or existing-label annotation",
            paper_citation="Dominguez Conde et al., Science 2022",
            documentation_url="https://celltypist.readthedocs.io/",
            default_params={"method": "existing_labels"},
        ),
        "spatial_deconvolution": MethodCitation(
            method_name="Cell2location-style deconvolution scaffold",
            paper_citation="Kleshchevnikov et al., Nature Biotechnology 2022",
            documentation_url="https://cell2location.readthedocs.io/",
            default_params={"method": "label_proportions"},
        ),
        "cnv_inference": MethodCitation(
            method_name="inferCNVpy-style expression CNV inference",
            paper_citation="inferCNVpy documentation and method references",
            documentation_url="https://infercnvpy.readthedocs.io/",
            default_params={},
        ),
        "pathway_activity": MethodCitation(
            method_name="decoupler pathway activity",
            paper_citation="Badia-i-Mompel et al., Bioinformatics Advances 2022",
            documentation_url="https://decoupler-py.readthedocs.io/",
            default_params={},
        ),
    }
    return citations.get(
        tool_name,
        MethodCitation(
            method_name=tool_name,
            paper_citation="SpatialMind prototype wrapper; cite the configured backend when enabled.",
            documentation_url="",
            default_params={},
        ),
    )
