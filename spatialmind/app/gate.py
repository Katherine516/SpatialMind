"""Gate evaluation for the Studio, using the real `pilot_gate`.

The gate is the product. Reimplementing its six conditions here so the UI could
answer faster would let the screen and the pipeline drift apart, and the screen
would be the one users believe. So this builds a coordinates-only dataset --
no expression -- applies the real label and region readers to it, and calls
`pilot_gate` itself.
"""

from typing import Any, Dict, List

from ..ingestion import (
    apply_best_available_labels,
    apply_best_available_regions,
    summarize_xenium_expert_readiness,
)
from ..pilot import pilot_gate
from ..schemas import SpatialDataset, SpotRecord
from .catalog import CellIndex


def light_dataset(index: CellIndex, sample_id: str) -> SpatialDataset:
    """Every cell, no genes. Enough for labels, regions and the gate."""
    records: List[SpotRecord] = [
        SpotRecord(sample_id=sample_id, x=x, y=y, cell_type="", genes={}, cell_id=cell_id)
        for cell_id, x, y in zip(index.cell_ids, index.xs, index.ys)
    ]
    dataset = SpatialDataset(
        sample_id=sample_id,
        records=records,
        source_path=index.dataset_path,
        modality="xenium_spatial_rna",
        coordinate_system="microns",
    )
    dataset.metadata.update(
        {
            "assay_subtype": "xenium_spatial_rna",
            "is_targeted_panel": True,
            "analysis_scope": "full_section",
            "analysis_dataset_path": index.dataset_path,
            "sampling": {"total_records": index.n_cells, "scanned_records": index.n_cells, "method": "all"},
        }
    )
    return dataset


def evaluate(
    index: CellIndex,
    sample_id: str,
    min_label_coverage: float = 0.7,
    min_region_coverage: float = 0.7,
    allow_single_region: bool = False,
) -> Dict[str, Any]:
    dataset = light_dataset(index, sample_id)
    path = index.dataset_path
    label_report = apply_best_available_labels(dataset, path, fallback=None)
    region_report = apply_best_available_regions(dataset, path)
    assets = summarize_xenium_expert_readiness(path)
    gate = pilot_gate(
        dataset=dataset,
        asset_readiness=assets.to_dict(),
        label_report=label_report.to_dict(),
        region_report=region_report.to_dict(),
        min_label_coverage=min_label_coverage,
        min_region_coverage=min_region_coverage,
        allow_single_region=allow_single_region,
    )
    labels = sorted({r.cell_type for r in dataset.records if r.cell_type and "unannotated" not in r.cell_type.lower()})
    regions = sorted({r.region for r in dataset.records if r.region})
    return {
        "status": gate["status"],
        "blocking_reasons": gate["blocking_reasons"],
        "required_next_inputs": gate["required_next_inputs"],
        "label_coverage": gate["label_coverage"],
        "region_coverage": gate["region_coverage"],
        "min_label_coverage": min_label_coverage,
        "min_region_coverage": min_region_coverage,
        "cell_classes": labels,
        "regions": regions,
        "asset_readiness": assets.to_dict(),
        "label_report": label_report.to_dict(),
        "region_report": region_report.to_dict(),
        "checks": _checks(gate, assets.to_dict(), labels, regions, index),
        "scope": {
            "scope": "full_section",
            "total_records": index.n_cells,
            "loaded_records": index.n_cells,
            "sampling_method": "all",
        },
    }


def _checks(
    gate: Dict[str, Any],
    assets: Dict[str, Any],
    labels: List[str],
    regions: List[str],
    index: CellIndex,
) -> List[Dict[str, Any]]:
    """The six conditions, each paired with the action that clears it."""
    asset_keys = ("has_cell_table", "has_feature_matrix", "has_morphology", "has_boundaries")
    assets_ok = all(assets.get(key) for key in asset_keys)
    missing = [key.replace("has_", "").replace("_", " ") for key in asset_keys if not assets.get(key)]
    label_cov = float(gate.get("label_coverage") or 0.0)
    region_cov = float(gate.get("region_coverage") or 0.0)
    return [
        {
            "id": "assets",
            "ok": assets_ok,
            "title": "Core assets present",
            "detail": "Cell table, feature matrix, morphology and boundaries resolved."
            if assets_ok
            else "Missing: %s." % ", ".join(missing),
            "action": "" if assets_ok else "Re-export the bundle from the instrument with all outputs.",
        },
        {
            "id": "labels",
            "ok": label_cov >= 0.7,
            "title": "Expert labels applied at 70% or more",
            "detail": "Coverage %.1f%% of %s cells." % (label_cov * 100, format(index.n_cells, ",")),
            "action": "Assign reviewed labels in Review Studio; writes expert_cell_labels.csv.",
        },
        {
            "id": "regions",
            "ok": region_cov >= 0.7,
            "title": "User regions applied at 70% or more",
            "detail": "Coverage %.1f%% of %s cells." % (region_cov * 100, format(index.n_cells, ",")),
            "action": "Draw regions in Review Studio; writes cell_regions.csv.",
        },
        {
            "id": "classes",
            "ok": len(labels) >= 2,
            "title": "At least two biological cell classes",
            "detail": "%d reviewed %s." % (len(labels), "class" if len(labels) == 1 else "classes"),
            "action": "Marker and neighbourhood validation need a contrast.",
        },
        {
            "id": "regions_count",
            "ok": len(regions) >= 2,
            "title": "At least two user-defined regions",
            "detail": "%d reviewed %s." % (len(regions), "region" if len(regions) == 1 else "regions"),
            "action": "A region summary needs something to compare against.",
        },
        {
            "id": "scope",
            "ok": True,
            "title": "Complete-section scope",
            "detail": "full_section, %s of %s cells indexed."
            % (format(index.n_cells, ","), format(index.n_cells, ",")),
            "action": "",
        },
    ]
