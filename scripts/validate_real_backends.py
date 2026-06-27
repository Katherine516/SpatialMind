import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from spatialmind.ingestion import DataIngestionLayer
from spatialmind.schemas import SpatialDataset
from spatialmind.tools.implementations import (
    differential_expression,
    neighborhood_enrichment,
    spatial_clustering,
    spatial_variable_genes,
)


ToolCase = Tuple[str, Callable[[SpatialDataset, Dict[str, object]], Any], Dict[str, object]]


def _run_tool_case(dataset: SpatialDataset, case: ToolCase) -> Dict[str, object]:
    name, func, params = case
    try:
        result = func(dataset, params)
    except Exception as exc:
        return {
            "tool": name,
            "status": "failed",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
    return {
        "tool": name,
        "status": "passed",
        "engine": result.metrics.get("engine"),
        "summary": result.summary,
        "metric_keys": sorted(result.metrics.keys()),
    }


def main() -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/spatialmind_mpl")
    output_path = Path("outputs/backend_validation.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    layer = DataIngestionLayer()
    demo = layer.load_csv("data/demo_spatial.csv", sample_id="BRCA_04")

    cases: List[ToolCase] = [
        (
            "differential_expression",
            differential_expression,
            {"group1": "CD8+ T cell", "group2": "Tumor cell", "strict_engine": True, "n_top": 5},
        ),
        ("spatial_clustering", spatial_clustering, {"resolution": 0.5, "strict_engine": True, "n_neighbors": 4}),
        ("spatial_variable_genes", spatial_variable_genes, {"n_top": 5, "strict_engine": True}),
        (
            "neighborhood_enrichment",
            neighborhood_enrichment,
            {"n_neighs": 4, "n_perms": 10, "n_jobs": 1, "random_state": 0, "strict_engine": True},
        ),
    ]
    validations = [_run_tool_case(demo, case) for case in cases]

    xenium_path = "data/Xenium lymph/Xenium_V1_hLymphNode_nondiseased_section_outs"
    xenium = layer.load_xenium_directory(xenium_path, max_records=30, max_features_per_record=25)
    payload = {
        "validations": validations,
        "xenium": {
            "sample_id": xenium.sample_id,
            "records": len(xenium.records),
            "features": len(xenium.genes),
            "cell_types": xenium.cell_types,
            "gene_matrix": xenium.metadata.get("gene_matrix", {}),
        },
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
