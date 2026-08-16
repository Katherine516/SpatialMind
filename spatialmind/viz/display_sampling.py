"""Deterministic spatial downsampling for display artifacts.

Analysis runs on every cell. Display is a different constraint: browsers and SVG
renderers degrade badly past a few tens of thousands of DOM nodes, and a
full-section Xenium run embeds one node per cell. A 378k-cell section would
produce a self-contained viewer of well over 100 MB that no browser opens
usefully.

These helpers cap what is *drawn* while preserving spatial coverage, so the
picture still represents the whole section. They never change what was analysed,
and callers are expected to state the cap in the artifact itself.
"""

from math import ceil, sqrt
from typing import Any, Dict, List, Sequence, Tuple

DEFAULT_DISPLAY_CAP = 20000


def downsample_for_display(
    records: Sequence[Any],
    max_points: int = DEFAULT_DISPLAY_CAP,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Return ``(subset, info)`` capped at ``max_points``, preserving coverage.

    Cells are binned onto a square spatial grid and drawn round-robin from the
    bins, so dense and sparse regions both survive the cut instead of the cut
    following file order. Deterministic: no RNG, and the same input always
    yields the same subset.
    """
    total = len(records)
    info: Dict[str, Any] = {
        "total_records": total,
        "displayed_records": total,
        "display_capped": False,
        "max_points": int(max_points),
        "method": "all",
    }
    if max_points <= 0 or total <= max_points:
        return list(records), info

    xs = [float(getattr(record, "x", 0.0) or 0.0) for record in records]
    ys = [float(getattr(record, "y", 0.0) or 0.0) for record in records]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    # Aim for a handful of cells per bin so round-robin spreads across the tissue.
    bins_per_axis = max(1, int(ceil(sqrt(max_points / 4.0))))

    buckets: Dict[Tuple[int, int], List[int]] = {}
    for index, (x, y) in enumerate(zip(xs, ys)):
        bx = min(bins_per_axis - 1, int((x - min_x) / span_x * bins_per_axis))
        by = min(bins_per_axis - 1, int((y - min_y) / span_y * bins_per_axis))
        buckets.setdefault((bx, by), []).append(index)

    ordered_keys = sorted(buckets)
    selected: List[int] = []
    depth = 0
    # Round-robin across bins until the cap is reached.
    while len(selected) < max_points:
        added = False
        for key in ordered_keys:
            bucket = buckets[key]
            if depth < len(bucket):
                selected.append(bucket[depth])
                added = True
                if len(selected) >= max_points:
                    break
        if not added:
            break
        depth += 1

    selected.sort()
    info.update(
        {
            "displayed_records": len(selected),
            "display_capped": True,
            "method": "spatial_grid_round_robin",
            "bins_per_axis": bins_per_axis,
        }
    )
    return [records[index] for index in selected], info


def display_caption(info: Dict[str, Any]) -> str:
    """One-line statement of the cap, for embedding in the artifact."""
    if not info.get("display_capped"):
        return ""
    return (
        "Showing %s of %s cells (spatially even subsample for display; analysis used all cells)."
        % (f"{info.get('displayed_records', 0):,}", f"{info.get('total_records', 0):,}")
    )
