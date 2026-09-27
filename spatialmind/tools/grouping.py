"""Shared grouping and per-cell review scope for analysis and presentation."""
from dataclasses import replace
from typing import Any, Dict

from spatialmind.schemas import SpatialDataset
from .exceptions import InvalidParameterError

CLUSTER_GROUPINGS = {"cluster", "leiden", "clusters", "leiden_cluster"}
GROUPED_TOOLS = {"marker_detection", "differential_expression", "neighborhood_enrichment",
                 "cell_neighborhood_enrichment"}
LABEL_TOOLS = GROUPED_TOOLS | {"annotation", "cell_type_annotation", "region_summary"}


def normalize_group_key(params: Dict[str, Any]) -> str:
    key = str(params.get("group_key") or params.get("group_by") or "cell_type").lower()
    if key in CLUSTER_GROUPINGS:
        return "cluster"
    if key == "cell_type":
        return key
    raise InvalidParameterError("Unknown grouping %r; use cell_type or cluster." % key)


def cell_is_reviewed(dataset: SpatialDataset, record: Any, kind: str = "label") -> bool:
    table = dataset.metadata.get("reviewed_cell_%ss" % kind) or {}
    value = table.get(str(record.cell_id or ""))
    current = record.cell_type if kind == "label" else record.region
    return bool(value and value.get(kind) == current)


def reviewed_view(dataset: SpatialDataset, tool_name: str, params: Dict[str, Any]) -> SpatialDataset:
    """Restrict biological tools, never expression clustering, to matched review rows.

    Legacy tables without review provenance remain exploratory. An explicit
    empty review map means no cells were reviewed, not all cells.
    """
    if tool_name not in LABEL_TOOLS:
        return dataset
    if tool_name in GROUPED_TOOLS and normalize_group_key(params) == "cluster":
        return dataset
    if "reviewed_cell_labels" not in dataset.metadata:
        return dataset
    records = [record for record in dataset.records if cell_is_reviewed(dataset, record)
               and (tool_name != "region_summary" or cell_is_reviewed(dataset, record, "region"))]
    return replace(dataset, records=records, metadata=dict(dataset.metadata), notes=list(dataset.notes))
