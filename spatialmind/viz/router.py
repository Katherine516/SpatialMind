from dataclasses import dataclass
from typing import Dict, List


@dataclass
class VizSpec:
    name: str
    modalities: List[str]
    output_type: str
    requires_scalebar: bool = False
    shows_effect_size: bool = False


class VizRouter:
    """Registry for visualization route specifications.

    The dependency-light implementation returns a route specification. Concrete
    renderers can be swapped in per modality as Plotly/Matplotlib/Vitessce are
    added.
    """

    def __init__(self) -> None:
        self._specs = {
            spec.name: spec
            for spec in [
                VizSpec("umap_clusters", ["scrna", "scatac", "xenium_spatial_rna", "spatial_transcriptomics"], "embedding"),
                VizSpec("marker_dotplot", ["scrna", "scatac", "xenium_spatial_rna", "spatial_transcriptomics"], "statistics", False, True),
                VizSpec("feature_grid", ["scrna", "scatac", "xenium_spatial_rna", "spatial_transcriptomics"], "spatial", True, True),
                VizSpec("qc_summary", ["scrna", "scatac", "xenium_spatial_rna", "spatial_transcriptomics"], "summary"),
                VizSpec("qc_violins", ["scrna", "scatac", "xenium_spatial_rna", "spatial_transcriptomics"], "statistics"),
                VizSpec("trajectory_plot", ["scrna"], "embedding"),
                VizSpec("tf_activity_heatmap", ["scatac", "spatial_atac"], "matrix", False, True),
                VizSpec("spatial_celltype_map", ["xenium_spatial_rna", "spatial_transcriptomics"], "spatial", True),
                VizSpec("region_summary_plot", ["xenium_spatial_rna", "spatial_transcriptomics"], "statistics", False, True),
                VizSpec("metrics_summary", ["scrna", "scatac", "xenium_spatial_rna", "spatial_transcriptomics"], "summary", False, True),
                VizSpec("transfer_confidence_map", ["xenium_spatial_rna", "spatial_transcriptomics"], "spatial", True),
                VizSpec("spatial_scatter", ["visium", "merfish", "xenium", "spatial_transcriptomics"], "spatial", True),
                VizSpec("expression_overlay", ["visium", "merfish", "xenium", "spatial_transcriptomics"], "spatial", True),
                VizSpec("neighborhood_clustermap", ["rna", "xenium_spatial_rna", "spatial_transcriptomics"], "matrix", False, True),
                VizSpec("spatial_gene_program_map", ["visium", "spatial_transcriptomics"], "spatial", True),
                VizSpec("trajectory_umap_spatial", ["rna", "spatial_transcriptomics"], "embedding", True),
                VizSpec("volcano_plot", ["rna", "spatial_transcriptomics"], "statistics", False, True),
                VizSpec("protein_composite_image", ["imc", "codex", "multiplexed_protein"], "image", True),
                VizSpec("cell_phenotype_map", ["imc", "codex", "multiplexed_protein"], "spatial", True),
                VizSpec("protein_coexpression_heatmap", ["imc", "codex", "multiplexed_protein"], "matrix", False, True),
                VizSpec("accessibility_spatial_map", ["atac", "spatial_atac"], "spatial", True),
                VizSpec("motif_enrichment_dotplot", ["atac", "spatial_atac"], "statistics", False, True),
                VizSpec("multi_sample_composition", ["batch"], "statistics", False, True),
                VizSpec("cnv_heatmap", ["tumor", "spatial_transcriptomics"], "matrix", False, True),
                VizSpec("tumor_microenvironment_summary", ["tumor", "spatial_transcriptomics"], "summary", True, True),
                VizSpec("cell_abundance_heatmap_regions", ["spatial_transcriptomics", "multiplexed_protein"], "matrix", False, True),
            ]
        }

    def list_specs(self) -> List[VizSpec]:
        return [self._specs[name] for name in sorted(self._specs)]

    def choose(self, tool_name: str, modality: str) -> VizSpec:
        mapping: Dict[str, str] = {
            "cell_type_annotation": "spatial_scatter",
            "qc_and_cluster": "umap_clusters",
            "annotation": "umap_clusters",
            "marker_detection": "marker_dotplot",
            "feature_overlay": "feature_grid",
            "region_summary": "region_summary_plot",
            "motif_tf_activity": "tf_activity_heatmap",
            "cell_neighborhood_enrichment": "neighborhood_clustermap",
            "reference_label_transfer": "transfer_confidence_map",
            "spatial_deconvolution": "multi_sample_composition",
            "spatial_variable_genes": "expression_overlay",
            "neighborhood_enrichment": "neighborhood_clustermap",
            "differential_expression": "volcano_plot",
            "protein_coexpression": "protein_coexpression_heatmap",
            "cell_phenotyping_spatial": "cell_phenotype_map",
            "cnv_inference": "cnv_heatmap",
            "tumor_niche_analysis": "tumor_microenvironment_summary",
            "motif_enrichment_spatial": "motif_enrichment_dotplot",
            "cell_abundance_heatmap_regions": "cell_abundance_heatmap_regions",
            "trajectory_inference": "trajectory_plot",
        }
        name = mapping.get(tool_name, "spatial_scatter")
        spec = self._specs[name]
        normalized = modality.lower()
        if normalized and normalized not in {item.lower() for item in spec.modalities}:
            return self._specs["spatial_scatter"]
        return spec
