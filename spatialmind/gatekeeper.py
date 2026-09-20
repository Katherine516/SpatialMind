"""One place that decides whether a tool may run, for every execution path.

The gate is the product's central guarantee: no biological claim without expert
labels and reviewed regions. It was enforced on one of four paths. `run_pilot`
checked it, `SpatialAgent` checked readiness but not the gate, the Studio's API
accepted a gate-blocked tool and only its UI declined to send one, and
`SpatialMindAgent` never checked at all. Both shipped entry points route a Xenium
bundle to `run_pilot`, so in practice it receives only non-Xenium data -- where
the gate cannot be evaluated anyway. The residual risk was a direct library call:
`DataIngestionLayer.load` accepts a Xenium directory, so `SpatialMindAgent().run`
on a real section was ungated for anyone who reached past the entry points.

A guarantee enforced by convention in three places and by code in one is not a
guarantee. This module is the code. Every executor calls `require_gate_open`
before it runs anything, and callers cannot opt out by forgetting.

It deliberately sits at the bottom of the import graph -- ingestion, tools,
schemas, contracts and nothing else -- so `agent`, `api`, `batch`, `pilot` and
`app` can all reach it without a cycle. `pilot_gate` lives here for the same
reason: it used to sit in `pilot.xenium`, which imports `agent.runtime`, so any
agent-layer caller would have closed a loop.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence
import os

from .schemas import SpatialDataset

# Grouping a tool by cluster keeps it descriptive: it then describes data-derived
# groups and never names a cell type, which is exactly what the gate protects.
CLUSTER_GROUPINGS = {"leiden", "cluster", "clusters", "leiden_cluster"}

# The registry's preconditions understate `annotation`: it reads the reviewed
# label table but only declares "requires normalized counts". Every other gated
# tool is detected from its preconditions rather than named here.
ALWAYS_LABEL_GATED = {"annotation"}

# `AlgorithmEngine` is a separate three-tool registry used by the legacy
# orchestrator. Its tools are not in `ToolRegistry`, so preconditions cannot
# classify them, but two of them name cell types and are therefore gated.
LEGACY_LABEL_GATED = {"cell_type_distribution", "cell_type_colocalization"}

# The reviewed-coverage thresholds the gate applies unless a caller lowers them.
# Named here because they were literal `0.7` defaults in six signatures across
# three layers, and a report that states the threshold it used has to read the
# same number the gate applied.
DEFAULT_MIN_LABEL_COVERAGE = 0.7
DEFAULT_MIN_REGION_COVERAGE = 0.7

# Below this, a coverage threshold stops being a relaxed standard and becomes no
# standard at all: at 0.0, two labelled cells clear the gate on a 24,406-cell
# section and the run reports `validated_ready`. Lowering past this needs an
# explicit acknowledgement from the caller, and the report says so wherever it
# names the threshold.
MIN_COVERAGE_FLOOR = 0.2


class CoverageFloorError(ValueError):
    """Raised when a caller lowers a coverage threshold past `MIN_COVERAGE_FLOOR`.

    Not a gate refusal -- the gate has not been evaluated yet. This is a refusal
    to *configure* the gate into something that cannot refuse, which is a caller
    error and belongs at the entry point rather than in the run's blockers.
    """

    def __init__(self, kind: str, requested: float, floor: float = MIN_COVERAGE_FLOOR) -> None:
        self.kind = kind
        self.requested = requested
        self.floor = floor
        super().__init__(
            "min_%s_coverage=%.3f is below the %.2f floor: at that threshold a handful of rows "
            "clears the gate on a whole section. Pass acknowledge_low_coverage=True "
            "(CLI: --acknowledge-low-coverage) to proceed; the report will state it."
            % (kind, requested, floor)
        )


def enforce_coverage_floor(
    min_label_coverage: float,
    min_region_coverage: float,
    acknowledge_low_coverage: bool = False,
) -> None:
    """Refuse a threshold low enough that the gate could not refuse anything."""
    if acknowledge_low_coverage:
        return
    if min_label_coverage < MIN_COVERAGE_FLOOR:
        raise CoverageFloorError("label", float(min_label_coverage))
    if min_region_coverage < MIN_COVERAGE_FLOOR:
        raise CoverageFloorError("region", float(min_region_coverage))


class GateBlockedError(RuntimeError):
    """Raised when a gated tool is asked to run before the gate opens."""

    def __init__(self, gate: Dict[str, Any], gated_tools: Sequence[str]) -> None:
        self.gate = gate
        self.gated_tools = list(gated_tools)
        reasons = gate.get("blocking_reasons") or ["Gate is not open."]
        super().__init__(
            "%s cannot run until the validation gate opens: %s"
            % (", ".join(self.gated_tools), " ".join(reasons))
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": "gate_blocked",
            "gated_tools": self.gated_tools,
            "status": self.gate.get("status"),
            "blocking_reasons": self.gate.get("blocking_reasons", []),
            "required_next_inputs": self.gate.get("required_next_inputs", []),
        }


def requires_labels(tool: Any, params: Optional[Dict[str, Any]] = None) -> bool:
    """True when this call would make a claim about named cell types."""
    params = params or {}
    grouping = str(params.get("group_key") or params.get("group_by") or "").lower()
    if grouping in CLUSTER_GROUPINGS:
        return False
    name = getattr(tool, "name", str(tool))
    if name in ALWAYS_LABEL_GATED or name in LEGACY_LABEL_GATED:
        return True
    return any("cell-type label" in str(text).lower() for text in getattr(tool, "preconditions", ()))


def requires_regions(tool: Any) -> bool:
    return any("region label" in str(text).lower() for text in getattr(tool, "preconditions", ()))


def gated_tool_names(
    tool_names: Iterable[str],
    overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[str]:
    """Which of these tools, called this way, need the gate open."""
    from .tools import build_default_registry

    overrides = overrides or {}
    registry = build_default_registry()
    known = {tool.name: tool for tool in registry.list_all()}
    gated: List[str] = []
    for name in tool_names:
        params = overrides.get(name, {})
        tool = known.get(name)
        if tool is None:
            # Not in the registry: the legacy engine's tools are classified by
            # name, and anything else unknown is treated as gated rather than
            # waved through. An unrecognised tool is not evidence of safety.
            if name in LEGACY_LABEL_GATED:
                gated.append(name)
            continue
        if requires_labels(tool, params) or requires_regions(tool):
            gated.append(name)
    return gated


def is_xenium_bundle(dataset_path: str) -> bool:
    root = dataset_path[:-len(os.path.basename(dataset_path))] if dataset_path.lower().endswith(".xenium") else dataset_path
    return os.path.isdir(root) and any(
        os.path.exists(os.path.join(root, name))
        for name in ("experiment.xenium", "cell_feature_matrix.h5")
    )


def evaluate_gate(
    dataset: SpatialDataset,
    dataset_path: str,
    min_label_coverage: float = 0.7,
    min_region_coverage: float = 0.7,
    allow_single_region: bool = False,
) -> Dict[str, Any]:
    """Apply the reviewed tables to `dataset`, then run the gate over them."""
    from .ingestion import (
        apply_best_available_labels,
        apply_best_available_regions,
        summarize_xenium_expert_readiness,
    )

    label_report = apply_best_available_labels(dataset, dataset_path, fallback=None)
    region_report = apply_best_available_regions(dataset, dataset_path)
    assets = summarize_xenium_expert_readiness(dataset_path)
    gate = pilot_gate(
        dataset=dataset,
        asset_readiness=assets.to_dict(),
        label_report=label_report.to_dict(),
        region_report=region_report.to_dict(),
        min_label_coverage=min_label_coverage,
        min_region_coverage=min_region_coverage,
        allow_single_region=allow_single_region,
    )
    gate["label_report"] = label_report.to_dict()
    gate["region_report"] = region_report.to_dict()
    gate["asset_readiness"] = assets.to_dict()
    return gate


def require_gate_open(
    dataset_path: str,
    tool_names: Iterable[str],
    dataset: Optional[SpatialDataset] = None,
    gate: Optional[Dict[str, Any]] = None,
    overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    min_label_coverage: float = 0.7,
    min_region_coverage: float = 0.7,
    allow_single_region: bool = False,
) -> Dict[str, Any]:
    """Permit or refuse this run. Raises `GateBlockedError` when it must refuse.

    Returns a decision dict the caller records. Three outcomes:

      `not_required`       no gated tool in the plan. The descriptive lane must
                           stay runnable on an unreviewed section; that is the
                           whole reason it exists.
      `gate_not_evaluated` gated tools on data the gate cannot assess. Permitted,
                           and carries a caveat the caller must surface.
      `validated_ready`    gated tools, gate open.

    Anything else raises `GateBlockedError`.
    """
    names = list(tool_names)
    gated = gated_tool_names(names, overrides)
    if not gated:
        return {"status": "not_required", "gated_tools": [], "tools": names}

    if not is_xenium_bundle(dataset_path):
        # The gate's six conditions are Xenium assets. On other data it cannot be
        # evaluated at all -- which is not the same as passing, and must not be
        # allowed to look like passing. Refusing outright would instead make the
        # gate assay-lock the whole system: the legacy demo path and any future
        # modality would be unusable for reasons of format, not of evidence.
        # So: permit, and hand back a status the caller has to record.
        return {
            "status": "gate_not_evaluated",
            "gated_tools": gated,
            "tools": names,
            "caveat": (
                "%s is not a Xenium bundle, so the validation gate could not be evaluated. "
                "These results are not gate-validated and must not be reported as though they were."
                % dataset_path
            ),
        }

    if gate is None:
        # Callers that already hold a gate evaluation pass it in rather than pay
        # for a second one; the Studio computes it from its cell index in under a
        # second and would otherwise reload the expression matrix here.
        if dataset is None:
            raise ValueError("require_gate_open needs a loaded dataset or a precomputed gate.")
        gate = evaluate_gate(
            dataset, dataset_path,
            min_label_coverage=min_label_coverage,
            min_region_coverage=min_region_coverage,
            allow_single_region=allow_single_region,
        )
    if gate.get("status") != "validated_ready":
        raise GateBlockedError(gate, gated)
    gate["gated_tools"] = gated
    gate["tools"] = names
    return gate


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    ordered = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
def build_gate_evidence(
    gate: Dict[str, Any],
    label_report: Dict[str, Any],
    region_report: Dict[str, Any],
    min_label_coverage: float,
    min_region_coverage: float,
    allow_single_region: bool = False,
    acknowledge_low_coverage: bool = False,
) -> Dict[str, Any]:
    """The numbers the gate decided on, in one place a report can print.

    The gate already computed all of this and the payload carried none of it, so
    the report's Limitations section said "expert_labels_applied" whether the
    reviewer covered 99.8% of the section or 0.01% of it -- the same sentence,
    with the distinguishing number sitting one dict away. Coverage without the
    threshold it was judged against is only half the fact, so both travel here,
    together with whether the threshold was the default.
    """
    lowered = [
        name
        for name, used, default in (
            ("label", float(min_label_coverage), DEFAULT_MIN_LABEL_COVERAGE),
            ("region", float(min_region_coverage), DEFAULT_MIN_REGION_COVERAGE),
        )
        if used < default
    ]
    return {
        "label_status": str(label_report.get("status") or "unknown"),
        "label_coverage": gate.get("label_coverage"),
        "label_matched_cells": int(label_report.get("matched_cells") or 0),
        "label_review_decisions": int(label_report.get("review_decisions") or 0),
        "label_total_records": int(label_report.get("total_records") or 0),
        "min_label_coverage": float(min_label_coverage),
        "region_status": str(region_report.get("status") or "unknown"),
        "region_coverage": gate.get("region_coverage"),
        "region_matched_cells": int(region_report.get("matched_cells") or 0),
        "region_review_decisions": int(region_report.get("review_decisions") or 0),
        "region_total_records": int(region_report.get("total_records") or 0),
        "min_region_coverage": float(min_region_coverage),
        "reviewed_cell_classes": list(gate.get("reviewed_cell_classes") or []),
        "reviewed_regions": list(gate.get("reviewed_regions") or []),
        "reviewed_basis": dict(gate.get("reviewed_basis") or {}),
        "default_min_label_coverage": DEFAULT_MIN_LABEL_COVERAGE,
        "default_min_region_coverage": DEFAULT_MIN_REGION_COVERAGE,
        "thresholds_lowered": lowered,
        "allow_single_region": bool(allow_single_region),
        "acknowledge_low_coverage": bool(acknowledge_low_coverage),
        "coverage_floor": MIN_COVERAGE_FLOOR,
        "below_coverage_floor": [
            name
            for name, used in (("label", float(min_label_coverage)), ("region", float(min_region_coverage)))
            if used < MIN_COVERAGE_FLOOR
        ],
    }


def pilot_gate(
    dataset: SpatialDataset,
    asset_readiness: Dict[str, Any],
    label_report: Dict[str, Any],
    region_report: Dict[str, Any],
    min_label_coverage: float,
    min_region_coverage: float,
    allow_single_region: bool,
) -> Dict[str, Any]:
    blockers: List[str] = []
    required: List[str] = []
    for key, name in [
        ("has_cell_table", "Xenium cell table"),
        ("has_feature_matrix", "Xenium feature matrix"),
        ("has_morphology", "morphology image metadata"),
        ("has_boundaries", "cell/nucleus boundaries"),
    ]:
        if not asset_readiness.get(key):
            blockers.append("Missing %s." % name)
            required.append("Provide %s." % name)

    total = max(int(label_report.get("total_records") or len(dataset.records)), 1)
    label_coverage = float(label_report.get("matched_cells") or 0) / float(total)
    if label_report.get("status") != "expert_labels_applied":
        blockers.append("Expert cell labels were not applied.")
        required.append("Add `expert_cell_labels.csv` with `cell_id,expert_label,confidence,notes` to the Xenium folder.")
    elif label_coverage < min_label_coverage:
        blockers.append("Expert label coverage %.3f is below required %.3f." % (label_coverage, min_label_coverage))
        required.append("Increase expert label coverage or lower the explicit threshold.")

    region_total = max(int(region_report.get("total_records") or len(dataset.records)), 1)
    region_coverage = float(region_report.get("matched_cells") or 0) / float(region_total)
    if region_report.get("status") != "user_regions_applied":
        blockers.append("User-provided region labels were not applied.")
        required.append("Add `cell_regions.csv` with `cell_id,region,region_confidence,notes` to the Xenium folder.")
    elif region_coverage < min_region_coverage:
        blockers.append("Region label coverage %.3f is below required %.3f." % (region_coverage, min_region_coverage))
        required.append("Increase region label coverage or lower the explicit threshold.")

    # Conditions 4 and 5 count what the *reviewer* supplied, which is not the
    # same as what is on the records. By the time the gate runs, the loader has
    # already filled `cell_type` with marker-rule guesses and `region` with a
    # section-wide placeholder, so reading the records made both conditions pass
    # on the loader's own output: one reviewed cell in a 24,406-cell section
    # counted as six biological classes and two user regions. The Studio never
    # had the bug because its gate dataset carries no loader labels at all --
    # which is why the two paths reported different blockers for one section.
    #
    # `reviewed_labels`/`reviewed_regions` are the distinct values the reviewed
    # table actually applied. An older report that predates those fields has
    # neither, so fall back to the record scan rather than blocking a rerun of a
    # stored run; the fallback is named in the payload so it cannot pass silently.
    labels, labels_basis = _reviewed_values(
        label_report, "reviewed_labels", dataset, "cell_type", drop_substring="unannotated"
    )
    if len(labels) < 2:
        blockers.append(
            "At least two biological cell labels are required for marker/neighborhood validation; "
            "the reviewed label table supplies %d." % len(labels)
        )
        required.append("Provide at least two reviewed biological cell classes.")

    regions, regions_basis = _reviewed_values(region_report, "reviewed_regions", dataset, "region")
    if not allow_single_region and len(regions) < 2:
        blockers.append(
            "At least two user-defined regions are required for a validated region summary pilot; "
            "the reviewed region table supplies %d." % len(regions)
        )
        required.append("Provide at least two reviewed tissue/ROI regions.")

    return {
        "status": "validated_ready" if not blockers else "blocked_missing_validation_inputs",
        "blocking_reasons": _dedupe(blockers),
        "required_next_inputs": _dedupe(required),
        "label_coverage": round(label_coverage, 4),
        "region_coverage": round(region_coverage, 4),
        "reviewed_cell_classes": sorted(labels),
        "reviewed_regions": sorted(regions),
        "reviewed_basis": {"labels": labels_basis, "regions": regions_basis},
    }


def _reviewed_values(
    report: Dict[str, Any],
    key: str,
    dataset: SpatialDataset,
    attribute: str,
    drop_substring: str = "",
) -> tuple:
    """Distinct values the reviewer supplied, and how we know.

    Returns ``(values, basis)`` where basis is ``reviewed_table`` when the report
    carried them and ``record_scan_fallback`` when it did not -- the latter
    includes whatever the loader put on the records, so a caller that sees it
    must not treat the count as reviewer-supplied.
    """
    listed = report.get(key)
    if isinstance(listed, list):
        values = {str(item).strip() for item in listed if str(item).strip()}
        if drop_substring:
            values = {item for item in values if drop_substring not in item.lower()}
        return values, "reviewed_table"
    values = {
        str(getattr(record, attribute, "") or "").strip()
        for record in dataset.records
        if str(getattr(record, attribute, "") or "").strip()
    }
    if drop_substring:
        values = {item for item in values if drop_substring not in item.lower()}
    return values, "record_scan_fallback"



# Instrument-level QC from metrics_summary.csv. These are the first numbers a
# wet-lab scientist checks, and they were parsed at ingestion but never reported.
