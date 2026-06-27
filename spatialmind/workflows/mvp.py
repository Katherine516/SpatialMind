from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    assay_subtype: str
    steps: List[str]
    optional_steps: List[str] = field(default_factory=list)
    honesty_flags: Dict[str, str] = field(default_factory=dict)


SCRNA_STANDALONE = WorkflowDefinition(
    name="SCRNA_LITE",
    assay_subtype="scrna",
    steps=["qc_and_cluster", "marker_detection"],
    optional_steps=[],
    honesty_flags={"resolution": "single_cell", "feature_type": "gene_counts"},
)

SCATAC_STANDALONE = WorkflowDefinition(
    name="SCATAC_LITE",
    assay_subtype="scatac_gene_activity",
    steps=["qc_and_cluster", "marker_detection"],
    honesty_flags={
        "resolution": "single_cell",
        "feature_type": "gene_activity",
        "label_caveat": "scATAC markers are accessibility-derived gene-activity markers, not measured expression.",
    },
)

XENIUM_STANDALONE = WorkflowDefinition(
    name="XENIUM_PRIMARY",
    assay_subtype="xenium_spatial_rna",
    steps=["qc_and_cluster", "annotation", "region_summary", "cell_neighborhood_enrichment"],
    honesty_flags={
        "resolution": "subcellular",
        "feature_type": "targeted_panel",
        "label_caveat": "Xenium targeted-panel absence means not measured, not unexpressed.",
    },
)

INTEGRATION_MODE = WorkflowDefinition(
    name="REFERENCE_ASSIST",
    assay_subtype="xenium_spatial_rna",
    steps=["qc_and_cluster", "marker_detection", "annotation"],
    honesty_flags={
        "resolution": "subcellular",
        "transfer": "Reference-assisted labels are predictions and require confidence caveats.",
        "feature_overlap": "Reference and target are aligned over shared features only.",
    },
)


def list_mvp_workflows() -> List[WorkflowDefinition]:
    return [SCRNA_STANDALONE, SCATAC_STANDALONE, XENIUM_STANDALONE, INTEGRATION_MODE]
