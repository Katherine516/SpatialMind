import math
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from spatialmind.schemas import SpatialDataset, ToolResult


def build_spatial_relationship_summary(
    dataset: SpatialDataset,
    results: List[ToolResult],
    robustness: Dict[str, Any],
    validated: bool,
    max_pairs_per_direction: int = 6,
) -> Dict[str, Any]:
    """Combine graph enrichment, scale sensitivity, distance, and region context.

    The output is deliberately descriptive. It reports spatial adjacency evidence,
    not molecular interaction, signaling, or causation.
    """
    if not validated:
        return {
            "status": "not_run",
            "reason": "Spatial relationships require expert-reviewed cell labels and user-reviewed regions.",
            "relationships": [],
            "warnings": [_relationship_warning()],
        }

    result = next(
        (
            item
            for item in results
            if item.tool_name in {"cell_neighborhood_enrichment", "neighborhood_enrichment"}
        ),
        None,
    )
    if result is None:
        return {
            "status": "not_computed",
            "reason": "No neighborhood-enrichment result was produced.",
            "relationships": [],
            "warnings": [_relationship_warning()],
        }

    metrics = result.metrics or {}
    engine = str(metrics.get("engine") or "prototype")
    pairs = metrics.get("all_pairs") or metrics.get("top_pairs") or []
    if engine != "squidpy" or not any(isinstance(item, dict) and item.get("zscore") is not None for item in pairs):
        return {
            "status": "not_computed",
            "reason": "Validated spatial relationships require Squidpy permutation z-scores; a prototype result is not sufficient.",
            "method": engine,
            "relationships": [],
            "warnings": [_relationship_warning()],
        }

    counts = Counter(record.cell_type for record in dataset.records)
    stability_by_pair = {
        str(item.get("pair")): item
        for item in robustness.get("pair_stability", [])
        if isinstance(item, dict) and item.get("pair")
    }
    region_profiles = _region_profiles(dataset)
    rows: List[Dict[str, Any]] = []
    for item in pairs:
        if not isinstance(item, dict) or item.get("pair") is None or item.get("zscore") is None:
            continue
        pair = str(item["pair"])
        parsed = _parse_pair(pair)
        if parsed is None:
            continue
        left, right = parsed
        try:
            zscore = float(item["zscore"])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(zscore):
            continue
        stability = stability_by_pair.get(pair, {})
        region_overlap, shared_regions = _region_overlap(left, right, region_profiles)
        left_count = int(counts.get(left, 0))
        right_count = int(counts.get(right, 0))
        direction = "enriched" if zscore > 0 else "depleted" if zscore < 0 else "indeterminate"
        evidence_status = _evidence_status(
            direction=direction,
            zscore=zscore,
            minimum_count=min(left_count, right_count),
            robustness=robustness,
            pair_stability=stability,
        )
        row: Dict[str, Any] = {
            "pair": pair,
            "left_cell_type": left,
            "right_cell_type": right,
            "direction": direction,
            "zscore": round(zscore, 4),
            "left_cell_count": left_count,
            "right_cell_count": right_count,
            "minimum_cell_count": min(left_count, right_count),
            "median_bidirectional_nearest_distance": _median_nearest_distance(dataset, left, right),
            "coordinate_units": dataset.coordinate_system or "dataset_coordinate_units",
            "region_overlap": region_overlap,
            "shared_regions": shared_regions,
            "settings_present": int(stability.get("settings_present") or 0),
            "sign_agreement": stability.get("sign_agreement"),
            "top_k_presence": stability.get("top_k_presence"),
            "evidence_status": evidence_status,
            "allowed_interpretation": _allowed_interpretation(left, right, direction, evidence_status),
        }
        if item.get("pval") is not None:
            row["pvalue"] = item.get("pval")
        rows.append(row)

    enriched = sorted((row for row in rows if row["zscore"] > 0), key=lambda row: row["zscore"], reverse=True)
    depleted = sorted((row for row in rows if row["zscore"] < 0), key=lambda row: row["zscore"])
    selected = enriched[:max_pairs_per_direction] + depleted[:max_pairs_per_direction]
    return {
        "status": "computed" if selected else "insufficient_data",
        "reason": "" if selected else "No finite neighborhood-enrichment pairs were available.",
        "method": "Squidpy permutation neighborhood enrichment",
        "graph": {
            "n_neighs": metrics.get("n_neighs"),
            "n_perms": metrics.get("n_perms"),
            "random_state": metrics.get("random_state"),
        },
        "cell_count": len(dataset.records),
        "cell_type_count": len(counts),
        "tested_pair_count": int(metrics.get("tested_pair_count") or len(pairs)),
        "reported_pair_count": len(selected),
        "robustness_score": robustness.get("score") if robustness.get("status") == "computed" else None,
        "relationships": selected,
        "warnings": [
            _relationship_warning(),
            "Global enrichment can reflect shared tissue-region occupancy; region overlap is shown as context, not as an adjustment.",
            "Nearest-cell distance is descriptive and should not be compared across datasets without harmonized coordinate units and sampling density.",
        ],
    }


def _evidence_status(
    direction: str,
    zscore: float,
    minimum_count: int,
    robustness: Dict[str, Any],
    pair_stability: Dict[str, Any],
) -> str:
    effect_supported = abs(zscore) >= 2.0
    count_supported = minimum_count >= 20
    global_supported = robustness.get("status") == "computed" and float(robustness.get("score") or 0.0) >= 0.6
    pair_supported = (
        int(pair_stability.get("settings_present") or 0) >= 2
        and float(pair_stability.get("sign_agreement") or 0.0) >= 0.8
        and float(pair_stability.get("top_k_presence") or 0.0) >= 0.5
    )
    if direction in {"enriched", "depleted"} and effect_supported and count_supported and global_supported and pair_supported:
        return "stable_%s" % direction
    if direction in {"enriched", "depleted"} and effect_supported:
        return "%s_sensitivity_limited" % direction
    return "weak_or_indeterminate"


def _allowed_interpretation(left: str, right: str, direction: str, evidence_status: str) -> str:
    if evidence_status.startswith("stable_"):
        comparison = "more" if direction == "enriched" else "fewer"
        return (
            "%s and %s have %s graph adjacencies than expected under label permutations, "
            "with direction stable across tested graph sizes."
            % (left, right, comparison)
        )
    if "sensitivity_limited" in evidence_status:
        comparison = "more" if direction == "enriched" else "fewer"
        return (
            "%s and %s have %s graph adjacencies than expected at the primary graph setting, "
            "but the relationship did not satisfy all stability and support criteria."
            % (left, right, comparison)
        )
    return "No stable graph-adjacency relationship is supported for %s and %s." % (left, right)


def _region_profiles(dataset: SpatialDataset) -> Dict[str, Dict[str, float]]:
    counts: Dict[str, Counter] = defaultdict(Counter)
    for record in dataset.records:
        if record.region:
            counts[record.cell_type][record.region] += 1
    profiles: Dict[str, Dict[str, float]] = {}
    for cell_type, region_counts in counts.items():
        total = float(sum(region_counts.values()))
        if total:
            profiles[cell_type] = {region: count / total for region, count in region_counts.items()}
    return profiles


def _region_overlap(
    left: str,
    right: str,
    profiles: Dict[str, Dict[str, float]],
) -> Tuple[Optional[float], List[str]]:
    left_profile = profiles.get(left)
    right_profile = profiles.get(right)
    if not left_profile or not right_profile:
        return None, []
    regions = sorted(set(left_profile) | set(right_profile))
    shared = [(region, min(left_profile.get(region, 0.0), right_profile.get(region, 0.0))) for region in regions]
    shared.sort(key=lambda item: item[1], reverse=True)
    overlap = sum(value for _region, value in shared)
    return round(overlap, 4), [region for region, value in shared[:3] if value > 0]


def _median_nearest_distance(dataset: SpatialDataset, left: str, right: str) -> Optional[float]:
    left_points = [(record.x, record.y) for record in dataset.records if record.cell_type == left]
    right_points = [(record.x, record.y) for record in dataset.records if record.cell_type == right]
    if not left_points or not right_points:
        return None
    try:
        from scipy.spatial import cKDTree  # type: ignore
    except ImportError:
        return None
    if left == right:
        if len(left_points) < 2:
            return None
        distances, _indices = cKDTree(left_points).query(left_points, k=2)
        values = [float(row[1]) for row in distances]
        return round(float(median(values)), 4) if values else None
    left_to_right, _ = cKDTree(right_points).query(left_points, k=1)
    right_to_left, _ = cKDTree(left_points).query(right_points, k=1)
    directional = [float(median(left_to_right)), float(median(right_to_left))]
    return round(sum(directional) / 2.0, 4)


def _parse_pair(pair: str) -> Optional[Tuple[str, str]]:
    values = pair.split(" | ", 1)
    if len(values) != 2 or not values[0] or not values[1]:
        return None
    return values[0], values[1]


def _relationship_warning() -> str:
    return "Spatial adjacency is not evidence of ligand-receptor signaling, physical contact, mechanism, or causation."
