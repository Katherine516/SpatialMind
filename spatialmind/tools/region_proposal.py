"""Draft tissue regions for a reviewer to accept, correct, or throw away.

The gate requires `cell_regions.csv` before any validated region claim, and the
agent offered no way to produce one beyond a cell map to draw on. Every region
tool in the codebase *consumes* regions a human drew; nothing proposed any. That
made "no reviewed regions" the most common reason a run stayed blocked, and the
agent had nothing to say about it.

This proposes them, under the contract label transfer already established:
the output is `cell_regions_candidate.csv` with `review_status=needs_expert_review`
and an empty `region` column the reviewer fills. It is not `cell_regions.csv`,
the gate does not read it, and no proposal here can become a reviewed region
without a human writing one.

Two sources, because they answer different questions:

  `spatial_domain`  Leiden on a graph built from position as well as expression.
                    Partitions the whole section into contiguous domains -- the
                    shape a reviewer usually wants, since regions should tile.
  `lisa_hotspot`    High-high patches of a spatially variable gene. Not a
                    partition: it marks where one gene's expression is locally
                    concentrated, which is the better starting point when the
                    interesting structure is a focus rather than a layer.

Both are data-derived groupings and neither names a tissue. A domain is
`domain_3`, never `white matter` -- naming it is the expert judgement the gate
exists to require.
"""

import csv
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from spatialmind.schemas import SpatialDataset

CANDIDATE_FILENAME = "cell_regions_candidate.csv"
CANDIDATE_FIELDS = [
    "cell_id",
    "x",
    "y",
    "candidate_region",
    "candidate_source",
    "confidence",
    "region",
    "region_confidence",
    "reviewer_id",
    "review_status",
    "notes",
]

# A proposal covering a handful of cells is noise a reviewer has to wade through
# rather than a region. Domains below this are merged into `unassigned` and the
# count is reported.
MIN_CELLS_PER_PROPOSED_REGION = 100

# A reviewer names regions by hand, so the proposal has to be at a scale a person
# will actually work through. Measured on a 19,968-cell brain section: resolution
# 0.4 gives 30 domains, 0.2 gives 21, 0.05 gives 8 covering 99.3% of cells. Eight
# is a tissue map someone will name; thirty is a chore they will abandon. The
# reviewer can always split a domain; they cannot easily merge thirty.
DEFAULT_DOMAIN_RESOLUTION = 0.05


def propose_regions(
    dataset: SpatialDataset,
    params: Optional[Dict[str, object]] = None,
) -> Dict[str, Any]:
    """Partition the section into spatial domains, as review candidates.

    Uses `qc_and_cluster(cluster_on="spatial")`, which has been implemented since
    the spatial-clustering work and reachable only by passing a parameter nobody
    passed. The clustering itself is unchanged; what is new is treating its output
    as a region draft and giving it the review contract.
    """
    from .implementations import CLUSTER_ASSIGNMENT_KEY, qc_and_cluster

    params = dict(params or {})
    resolution = float(params.get("resolution", DEFAULT_DOMAIN_RESOLUTION) or DEFAULT_DOMAIN_RESOLUTION)
    # An explicit 0 lifts the floor; `or DEFAULT` would discard it, because 0 is
    # falsy. See `_number` in spatial_statistics for the same bug found by a test.
    raw_min = params.get("min_cells", MIN_CELLS_PER_PROPOSED_REGION)
    min_cells = int(MIN_CELLS_PER_PROPOSED_REGION if raw_min is None else raw_min)

    # Clustering writes assignments onto the dataset, and a region proposal must
    # not silently replace the expression clusters the rest of the run reports.
    preserved = dict(dataset.metadata.get(CLUSTER_ASSIGNMENT_KEY) or {})
    try:
        result = qc_and_cluster(dataset, {
            "cluster_on": "spatial",
            "resolution": resolution,
            "random_state": int(params.get("random_state", 0) or 0),
            "n_neighs": int(params.get("n_neighs", 12) or 12),
            "strict_engine": bool(params.get("strict_engine", False)),
        })
    except Exception as exc:  # noqa: BLE001 - reported, not raised: a failed proposal must not fail a run
        if params.get("strict_engine"):
            raise
        return {"status": "not_computed", "reason": "Spatial-domain clustering failed: %s" % exc, "regions": []}
    assignments = dict(dataset.metadata.get(CLUSTER_ASSIGNMENT_KEY) or {})
    if preserved:
        dataset.metadata[CLUSTER_ASSIGNMENT_KEY] = preserved
    else:
        dataset.metadata.pop(CLUSTER_ASSIGNMENT_KEY, None)

    if not assignments:
        return {"status": "not_computed", "reason": "Spatial clustering produced no assignments.", "regions": []}

    counts = Counter(assignments.values())
    kept = {name for name, count in counts.items() if count >= min_cells}
    proposals: Dict[str, str] = {}
    for cell_id, domain in assignments.items():
        proposals[cell_id] = "domain_%s" % domain if domain in kept else ""

    covered = sum(1 for value in proposals.values() if value)
    rows = [
        {"candidate_region": "domain_%s" % name, "n_cells": int(count),
         "fraction": round(count / max(len(dataset.records), 1), 4)}
        for name, count in sorted(counts.items(), key=lambda item: -item[1])
        if name in kept
    ]
    return {
        "status": "computed",
        "source": "spatial_domain",
        "method": "leiden_on_spatially_weighted_graph",
        "resolution": resolution,
        "min_cells": min_cells,
        "proposed_region_count": len(rows),
        "dropped_small_domains": int(len(counts) - len(kept)),
        "covered_cells": covered,
        "coverage": round(covered / max(len(dataset.records), 1), 4),
        "regions": rows,
        "assignments": proposals,
        "clustering_summary": result.summary,
        "review_caveat": (
            "These are data-derived spatial domains, not tissue regions. They are named "
            "domain_N and never by anatomy; assigning a name, merging domains, or rejecting "
            "them is the expert step the validation gate requires."
        ),
    }


def hotspot_regions(lisa: Dict[str, Any], min_cells: int = MIN_CELLS_PER_PROPOSED_REGION) -> Dict[str, Any]:
    """Turn LISA high-high patches into region candidates, one per gene.

    A hotspot is not a partition -- most cells belong to no hotspot, and a cell can
    be a hotspot for two genes at once. First gene wins on a tie, and the overlap
    count is reported so a reviewer can see when two genes are marking the same
    structure rather than two different ones.
    """
    per_cell = (lisa or {}).get("per_cell") or {}
    genes = [row for row in (lisa or {}).get("genes") or [] if row.get("status") == "computed"]
    if not per_cell or not genes:
        return {"status": "not_computed", "reason": "No local Moran's I result to build regions from.", "regions": []}

    assignments: Dict[str, str] = {}
    overlaps = 0
    counts: Counter = Counter()
    for cell_id, values in per_cell.items():
        hits = [row["gene"] for row in genes if values.get("lisa_%s" % row["gene"]) == "high-high"]
        if not hits:
            assignments[cell_id] = ""
            continue
        if len(hits) > 1:
            overlaps += 1
        name = "hotspot_%s" % hits[0]
        assignments[cell_id] = name
        counts[name] += 1

    kept = {name for name, count in counts.items() if count >= min_cells}
    for cell_id, name in list(assignments.items()):
        if name and name not in kept:
            assignments[cell_id] = ""
    rows = [{"candidate_region": name, "n_cells": int(count)}
            for name, count in sorted(counts.items(), key=lambda item: -item[1]) if name in kept]
    covered = sum(1 for value in assignments.values() if value)
    return {
        "status": "computed" if rows else "insufficient_data",
        "source": "lisa_hotspot",
        "method": "local_morans_i_high_high_patches",
        "min_cells": min_cells,
        "proposed_region_count": len(rows),
        "cells_in_multiple_hotspots": overlaps,
        "covered_cells": covered,
        "coverage": round(covered / max(len(assignments), 1), 4),
        "regions": rows,
        "assignments": assignments,
        "review_caveat": (
            "Hotspots mark where one gene's expression is locally concentrated. They do not tile "
            "the section, they can overlap, and they are named after the gene rather than after "
            "any tissue structure."
        ),
    }


def write_region_candidates(
    dataset: SpatialDataset,
    proposals: List[Dict[str, Any]],
    output_dir: Path,
    max_rows: int = 0,
) -> Dict[str, Any]:
    """Write `cell_regions_candidate.csv`, deliberately not `cell_regions.csv`.

    The filename is the safety property. `cell_regions.csv` is the reviewer's
    file and the only one the gate reads; a proposal that wrote there would turn
    a data-derived grouping into gate-clearing evidence, which is the one thing
    this whole subsystem must not do. The `region` column is left empty for the
    reviewer to fill, exactly as `expert_cell_labels_candidate.csv` does.
    """
    usable = [item for item in proposals if item and item.get("status") == "computed" and item.get("assignments")]
    if not usable:
        return {"status": "not_written", "reason": "No usable region proposals.", "path": ""}

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / CANDIDATE_FILENAME
    limit = len(dataset.records) if max_rows <= 0 else min(max_rows, len(dataset.records))
    written = 0
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        for index, record in enumerate(dataset.records[:limit]):
            cell_id = record.cell_id or str(index)
            candidate, source = "", ""
            for item in usable:
                value = (item.get("assignments") or {}).get(cell_id, "")
                if value:
                    candidate, source = value, str(item.get("source") or "")
                    break
            writer.writerow({
                "cell_id": cell_id,
                "x": round(float(record.x), 4),
                "y": round(float(record.y), 4),
                "candidate_region": candidate,
                "candidate_source": source,
                "confidence": "",
                "region": "",
                "region_confidence": "",
                "reviewer_id": "",
                "review_status": "needs_expert_review",
                "notes": "",
            })
            written += 1
    return {
        "status": "written",
        "path": str(path),
        "rows": written,
        "sources": [str(item.get("source")) for item in usable],
        "instruction": (
            "Fill `region` and `reviewer_id`, then save as `cell_regions.csv` inside the Xenium "
            "folder. This file is never read by the validation gate."
        ),
    }
