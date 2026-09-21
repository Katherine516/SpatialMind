"""Spatial statistics beyond "is this pattern real": where is it, and at what scale.

The agent could already decide whether a spatial pattern survives a permutation
null and a graph-size perturbation. It could not say *where* the pattern is. Every
statistic it computed was global -- one number per gene, one z-score per cell-type
pair, for the whole section -- so a report could rank genes and never draw a map.

This module adds the local and point-pattern half, following the taxonomy in
Nucleic Acids Res 53(17) gkaf870 (*pasta*): lattice methods for continuous marks
(gene expression), point-pattern methods for categorical marks (cell types), and
the pitfalls that make each of them lie.

Four of those pitfalls are load-bearing here, because each one produced a wrong
answer on real local data before it was handled:

1. **Binary marks and continuous marks do not share a scale.** Moran's I for a
   one-hot cell type peaked at 0.038 on a section where the top gene reached
   0.309. Reported in one table they suggest cell types are ten times less
   organised than genes, which is a property of the mark, not the tissue.
2. **Rare populations produce confident nonsense.** A T/NK population of twelve
   cells returned I = 0.025 at p = 0.04. `MIN_CELLS_FOR_AUTOCORRELATION` exists
   for that measurement, not in the abstract.
3. **Ripley's default window is the bounding box.** On a 3,993-cell section with a
   median nearest-neighbour distance of 39.5 um, squidpy tests radii out to
   3,819 um -- half the bounding-box diagonal -- against a null that fills the
   empty space around an irregular section. Every cell type came back
   "dispersed", including ones that visibly cluster. So `ripley_cell_types`
   computes its own radius ceiling from the data and reports the window it used.
4. **Local statistics are per-location, so they are a multiple-testing problem.**
   One test per cell, tens of thousands of cells. BH correction is not optional
   and the corrected count is what gets reported.

Everything here is descriptive. A LISA hotspot is a candidate region, not a
region: nothing in this module may satisfy the gate, and the per-cell-type
autocorrelation is gated precisely because it names cell types.
"""

from collections import Counter
from math import erfc, sqrt
from typing import Any, Dict, List, Optional, Tuple

from spatialmind.schemas import SpatialDataset

from .exceptions import MissingPreconditionError

# Below this a population's autocorrelation is driven by where a handful of cells
# happened to land. Measured: 12 T/NK cells scored I = 0.025 at p = 0.04 on a
# section where that population has no coherent spatial structure to speak of.
MIN_CELLS_FOR_AUTOCORRELATION = 50

# Local statistics are computed per cell, so a 20,000-cell section is 20,000
# tests per gene. Genes are capped so a run does not spend its budget here, and
# the cap is reported rather than assumed.
DEFAULT_LISA_GENES = 8

# A permutation p-value cannot go below 1/(n_perms + 1), and BH over one test per
# cell then multiplies that floor by n/rank. At 99 permutations on 4,000 cells the
# smallest reachable adjusted p is 0.01 x 4000 = 40 for the top-ranked cell, so
# *nothing* can clear alpha 0.05 and every gene reports zero hotspots -- which is
# exactly what the first run produced. 999 permutations puts the floor at 0.001
# and makes the test able to detect anything at all.
DEFAULT_LISA_PERMUTATIONS = 999

# Local statistics need a bigger neighbourhood than global ones, and the
# difference is not small. Measured on a 19,968-cell section at the same
# permutation budget: MOG, an oligodendrocyte marker that forms visible
# white-matter tracts, returned 0 hotspot cells at k=6, 284 at k=12 and 704 at
# k=18. Six neighbours of sparse counts is mostly zeros, so nothing survives the
# null; the global statistics pool over the whole section and do not have that
# problem. Deliberately different from the global default of 6, and reported with
# the result so the choice is visible.
DEFAULT_LISA_NEIGHBORS = 18

# Ripley radii are capped at this multiple of the median nearest-neighbour
# distance. Cell-cell interaction and local tissue architecture live within a few
# neighbour distances; beyond that the statistic is dominated by the shape of the
# section rather than by anything biological.
RIPLEY_RADIUS_NEIGHBOR_MULTIPLE = 12.0

# Expected cells per bin when sizing the tissue window. The mask is estimated
# from the same points it will be tested against, so a bin left empty by chance
# is a hole punched in solid tissue -- and the simulated null is then confined to
# bins the real points happened to occupy, which makes a genuinely uniform
# population read as dispersed.
#
# Measured on 700 uniform points in a 400x400 um square: at 0.4 points per bin
# the mask recovered 36% of the true area, at 1.8 it recovered 83%, and at 7 it
# was exact. Sizing by nearest-neighbour distance instead gave ~2 per bin, which
# was the first version and was biased.
#
# Kept at 4 rather than 8 because the filling pass below removes chance holes,
# and smaller bins resolve thin structures better -- the two requirements pull
# against each other and filling buys about one size step. Measured: a square at
# 17 um bins recovered 72% of its area unfilled and 87% filled; at 25 um, 93% and
# 98%.
TISSUE_BIN_TARGET_CELLS = 4.0

# Minimum |L(r) - E[L(r)]| / r for a verdict of clustered or dispersed. L has
# units of distance, so dividing by the radius gives "the effective neighbourhood
# radius is X% wider than complete spatial randomness" -- dimensionless, and
# comparable between populations and sections.
#
# Needed because the envelope alone is not a finding. With thousands of cells the
# simulated envelope is extremely narrow, so any systematic bias of a fraction of
# a micron puts 97% of radii outside it: a uniform-on-a-ring control came back
# "clustered" on a deviation of 0.7 um at r = 25 um, next to a real clump at
# 28.9 um. That is the p-value cliff this codebase already fixed once in
# `_evidence_strength`, in a different statistic -- significance without effect
# size is not a result.
RIPLEY_MIN_RELATIVE_DEVIATION = 0.05


def tissue_window(coordinates: Any, bin_size: float) -> Dict[str, Any]:
    """An occupancy mask of the section, and its area.

    A tissue section is not its convex hull. Cortex is concave, ventricles and
    tears are holes, and a hull drawn round any of them encloses empty space. The
    CSR null has to be simulated where cells could actually be, or the comparison
    measures the shape of the section rather than the arrangement of the cells
    inside it -- a population confined to a concave arm of tissue reads as
    clustered simply because the hull let the null spread into space no cell
    could occupy.

    A square-bin occupancy mask rather than an alpha shape: it needs no extra
    dependency, it represents holes natively, and its area is exact by
    construction rather than an artefact of a tuning parameter.
    """
    import numpy as np  # type: ignore

    coordinates = np.asarray(coordinates, dtype=float)
    origin = coordinates.min(axis=0)
    indices = np.floor((coordinates - origin) / bin_size).astype(int)
    occupied = {(int(ix), int(iy)) for ix, iy in indices}

    # Fill bins that are empty but almost surrounded. An empty bin with six or
    # more occupied neighbours is a gap the sampling left in solid tissue, not a
    # ventricle: a real hole is many bins wide and its interior has no occupied
    # neighbours at all. Without this the bins have to be large enough that
    # chance emptiness is negligible, and large bins cannot follow a thin
    # structure -- filling is what lets the bins be small enough to resolve one.
    filled = 0
    candidates = {
        (x + dx, y + dy)
        for (x, y) in occupied
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
    } - occupied
    for cell in candidates:
        x, y = cell
        neighbours = sum(
            (x + dx, y + dy) in occupied
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            if (dx, dy) != (0, 0)
        )
        if neighbours >= 6:
            occupied.add(cell)
            filled += 1
    keys = np.array(sorted(occupied), dtype=float)
    return {
        "origin": origin,
        "bin_size": float(bin_size),
        "bins": keys,
        "occupied_bins": len(occupied),
        "filled_bins": filled,
        "area": float(len(occupied)) * bin_size * bin_size,
    }


def _window_bin_size(area: float, count: int, median_nearest: float) -> float:
    """Bin side giving `TISSUE_BIN_TARGET_CELLS` cells per bin at this density.

    Floored at the median nearest-neighbour distance: a bin smaller than the
    typical cell spacing cannot be reliably occupied whatever the density says.
    """
    import numpy as np  # type: ignore

    if area <= 0 or count <= 0:
        return max(median_nearest, 1e-9)
    side = float(np.sqrt(TISSUE_BIN_TARGET_CELLS * area / count))
    return max(side, median_nearest, 1e-9)


def sample_in_window(window: Dict[str, Any], count: int, rng: Any) -> Any:
    """`count` points spread uniformly over the occupied region.

    Uniform over the *mask*, not over its bounding box or hull: a bin is drawn at
    random and a point placed uniformly inside it, so density is flat across the
    tissue and zero everywhere else.
    """
    import numpy as np  # type: ignore

    bins = window["bins"]
    size = window["bin_size"]
    chosen = bins[rng.integers(0, len(bins), size=count)]
    jitter = rng.random((count, 2))
    return window["origin"] + (chosen + jitter) * size


def besag_l(coordinates: Any, radii: Any, area: float) -> Any:
    """Besag's L at each radius, on the estimator squidpy uses.

    No edge correction, deliberately. The observed pattern and every simulation
    are measured with the identical estimator in the identical window, so the
    edge bias is common to both and cancels in the comparison -- which is the
    same argument that makes the simulated envelope the right reference in the
    first place. An uncorrected statistic against a correctly simulated null is
    honest; a corrected statistic against a null simulated in the wrong window is
    not.
    """
    import numpy as np  # type: ignore
    from scipy.spatial import cKDTree  # type: ignore

    coordinates = np.asarray(coordinates, dtype=float)
    n = len(coordinates)
    if n < 2 or area <= 0:
        return np.zeros(len(radii), dtype=float)
    tree = cKDTree(coordinates)
    # count_neighbors over the tree against itself returns ordered pairs and
    # includes each point with itself, so subtracting n leaves 2x the unordered
    # pairs within r -- which is the numerator the estimator wants.
    counts = np.asarray(tree.count_neighbors(tree, np.asarray(radii, dtype=float)), dtype=float)
    ordered_pairs = np.maximum(counts - n, 0.0)
    intensity = n / area
    k_estimate = (ordered_pairs / n) / intensity
    return np.sqrt(k_estimate / np.pi)


def _expression_adata(dataset: SpatialDataset) -> Any:
    """AnnData with the same normalisation every other expression tool applies.

    `qc_and_cluster`, `marker_detection` and `spatial_variable_genes` all guard
    with `if not dataset.normalized: normalize_total + log1p`. The local and
    bivariate statistics here did not, so on a dataset that arrives un-normalised
    -- an H5AD of raw counts, say -- the report would show global Moran's I on
    log-normalised expression and local Moran's I on raw counts, for the same
    genes, with nothing saying they disagreed. `load_xenium` normalises, so the
    two agreed in practice and the inconsistency was invisible.
    """
    from .implementations import _dataset_to_anndata

    adata = _dataset_to_anndata(dataset)
    if not dataset.normalized:
        import scanpy as sc  # type: ignore

        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
    return adata


def _neighbor_graph(sq: Any, adata: Any, n_neighs: int, radius: Optional[float]) -> Dict[str, Any]:
    """Build the weight matrix, and say which family it came from.

    The paper's flagged unknown: contiguity, distance-band and kNN graphs give
    different answers and there is no consensus guidance for spatial omics. The
    agent already measures sensitivity across kNN sizes; `radius` adds the second
    family so the sweep can vary the *kind* of graph and not only its density.
    """
    if radius is not None and float(radius) > 0:
        sq.gr.spatial_neighbors(adata, coord_type="generic", radius=float(radius), delaunay=False)
        isolated = int((adata.obsp["spatial_connectivities"].getnnz(axis=1) == 0).sum())
        return {
            "family": "distance_band",
            "radius": float(radius),
            "n_neighs": None,
            # A distance band leaves sparse regions with no neighbours at all,
            # which a kNN graph never does. Those cells contribute nothing and
            # the count has to be visible, or the effective sample size is
            # silently smaller than the cell count.
            "isolated_cells": isolated,
        }
    sq.gr.spatial_neighbors(adata, coord_type="generic", n_neighs=int(n_neighs))
    return {"family": "knn", "radius": None, "n_neighs": int(n_neighs), "isolated_cells": 0}


def _reviewed_filter(
    labels: List[str],
    counts: Any,
    params: Dict[str, object],
    group_key: str,
) -> Any:
    """Which groups a cell-type statistic may report, and what it excluded.

    A partially reviewed section carries both: the classes a reviewer supplied,
    and the loader's marker-rule guesses on every cell the reviewer did not
    reach. Grouping by `record.cell_type` mixes them, so a validated run listed
    `Unannotated cell` and `Neural/Glial cell` beside atlas-transferred classes
    in a table headed "Cell-Type ...", with nothing to tell them apart. That is
    the conflation the gate exists to prevent, arriving after the gate had
    already opened.

    When the caller passes the reviewed set, only those groups are reported and
    the rest are counted. Grouping by cluster passes nothing, because a cluster
    is not a cell type and there is nothing to filter against.
    """
    reviewed = params.get("reviewed_labels")
    if group_key != "cell_type" or not reviewed:
        return None, 0
    allowed = {str(name) for name in reviewed}
    excluded = sum(count for name, count in counts.items() if name not in allowed)
    return allowed, int(excluded)


def cell_type_spatial_autocorrelation(
    dataset: SpatialDataset,
    params: Optional[Dict[str, object]] = None,
) -> Dict[str, Any]:
    """Moran's I per cell type: does this population form patches, or scatter?

    Neighbourhood enrichment answers "does A sit near B". This answers "does A sit
    near A", which is the question a pathologist usually asks first and which the
    agent could not previously answer at all.

    Each type is one-hot encoded and run through the same spatial graph the
    enrichment test uses, so the two are directly comparable to each other -- and
    deliberately not comparable to the gene-level Moran's I, which is computed on
    a continuous mark with a much higher ceiling.
    """
    from .implementations import _dataset_to_anndata, resolve_group_labels

    params = dict(params or {})
    try:
        import squidpy as sq  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError(
                "Cell-type spatial autocorrelation requires Squidpy in strict mode."
            ) from exc
        return {"status": "not_computed", "reason": "Squidpy is not installed: %s" % exc, "groups": []}

    labels, group_key = resolve_group_labels(dataset, params)
    counts = Counter(label for label in labels if label)
    min_cells = int(_number(params, "min_cells", MIN_CELLS_FOR_AUTOCORRELATION))
    allowed, unreviewed_cells = _reviewed_filter(labels, counts, params, group_key)
    testable = sorted(
        name for name, count in counts.items()
        if count >= min_cells and (allowed is None or name in allowed)
    )
    skipped = sorted(
        ({"group": name, "n_cells": count,
          "reason": "not in the reviewed label table" if (allowed is not None and name not in allowed)
                    else "fewer than %d cells" % min_cells}
         for name, count in counts.items()
         if count < min_cells or (allowed is not None and name not in allowed)),
        key=lambda row: -row["n_cells"],
    )
    if len(testable) < 2:
        return {
            "status": "insufficient_data",
            "reason": "At least two groups with %d or more cells are required; %d qualify."
                      % (min_cells, len(testable)),
            "group_key": group_key,
            "min_cells": min_cells,
            "groups": [],
            "skipped_groups": skipped,
        }

    n_neighs = max(2, int(params.get("n_neighs", 6) or 6))
    n_perms = max(10, int(params.get("n_perms", 100) or 100))
    random_state = int(params.get("random_state", 0) or 0)
    radius = params.get("radius")

    # Raw adata is correct here: every column this reads is a 0/1 group indicator
    # built below, so expression normalisation cannot affect the result.
    adata = _dataset_to_anndata(dataset)
    indicator_names = []
    for name in testable:
        column = "spatialmind_ind_%s" % name
        adata.obs[column] = [1.0 if label == name else 0.0 for label in labels]
        indicator_names.append(column)

    graph = _neighbor_graph(sq, adata, n_neighs, radius if radius is None else float(radius))
    frame = sq.gr.spatial_autocorr(
        adata,
        mode="moran",
        attr="obs",
        genes=indicator_names,
        n_perms=n_perms,
        seed=random_state,
        copy=True,
        n_jobs=1,
        # squidpy's default parallel backend spawns processes, which needs a real
        # __main__ and dies inside a worker or a frozen app. The rest of the
        # codebase already pins threading for the same reason.
        backend="threading",
        show_progress_bar=False,
    )

    rows: List[Dict[str, Any]] = []
    for column, record in frame.iterrows():
        name = str(column).replace("spatialmind_ind_", "")
        rows.append({
            "group": name,
            "n_cells": int(counts.get(name, 0)),
            "morans_i": _round(record.get("I")),
            "pval_norm": _round(_first(record, ("pval_norm",)), 6),
            "pval_sim": _round(_first(record, ("pval_sim", "pval_z_sim")), 6),
            "pval_adj": _round(_first(record, ("pval_norm_fdr_bh", "pval_sim_fdr_bh")), 6),
            "interpretation": _autocorrelation_phrase(record.get("I")),
        })
    rows.sort(key=lambda row: (row["morans_i"] is None, -(row["morans_i"] or 0.0)))

    return {
        "status": "computed",
        "method": "moranI_on_group_indicator",
        "group_key": group_key,
        "graph": graph,
        "n_perms": n_perms,
        "random_state": random_state,
        "min_cells": min_cells,
        "reviewed_only": allowed is not None,
        "unreviewed_cells": unreviewed_cells,
        "multiple_testing": "benjamini_hochberg",
        "tested_group_count": len(rows),
        "groups": rows,
        "skipped_groups": skipped,
        # Stated in the payload rather than left to the report, because the
        # comparison is the thing a reader makes by reflex.
        "scale_caveat": (
            "Moran's I on a binary group indicator is not on the same scale as Moran's I on "
            "continuous gene expression and the two must not be compared. A one-hot mark has a "
            "much lower ceiling: on a section where the strongest gene reached 0.31, the "
            "strongest cell type reached 0.04."
        ),
    }


def local_moran_hotspots(
    dataset: SpatialDataset,
    genes: List[str],
    params: Optional[Dict[str, object]] = None,
) -> Dict[str, Any]:
    """Local Moran's I per cell, classified on the Moran scatter plot.

    Global Moran's I says a gene is spatially structured. This says where: each
    cell is labelled `high-high` (high expression among high neighbours),
    `low-low`, or one of the two spatial-outlier classes. Those labels are the
    per-cell map the report never had, and the high-high patches are candidate
    regions for a reviewer to accept or reject.

    Computed directly rather than through a library, because the two things that
    matter -- the weight matrix and the multiple-testing correction -- are already
    decided elsewhere in this module and should not be re-decided by a dependency.
    """
    params = dict(params or {})
    genes = [str(gene) for gene in genes if str(gene)]
    if not genes:
        return {"status": "insufficient_data", "reason": "No genes were supplied.", "genes": []}
    try:
        import numpy as np  # type: ignore
        import squidpy as sq  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError("Local Moran's I requires NumPy and Squidpy in strict mode.") from exc
        return {"status": "not_computed", "reason": "NumPy/Squidpy not installed: %s" % exc, "genes": []}

    max_genes = max(1, int(params.get("max_genes", DEFAULT_LISA_GENES) or DEFAULT_LISA_GENES))
    genes = genes[:max_genes]
    n_neighs = max(2, int(params.get("n_neighs", DEFAULT_LISA_NEIGHBORS) or DEFAULT_LISA_NEIGHBORS))
    radius = params.get("radius")
    alpha = float(params.get("alpha", 0.05) or 0.05)

    adata = _expression_adata(dataset)
    available = {str(name).upper(): str(name) for name in adata.var_names}
    resolved = [available[gene.upper()] for gene in genes if gene.upper() in available]
    missing = [gene for gene in genes if gene.upper() not in available]
    if not resolved:
        return {
            "status": "insufficient_data",
            "reason": "None of the requested genes are in the measured panel.",
            "missing_genes": missing,
            "genes": [],
        }

    graph = _neighbor_graph(sq, adata, n_neighs, radius if radius is None else float(radius))
    weights = adata.obsp["spatial_connectivities"].astype(float)
    # Row-standardise: each cell's neighbourhood is a mean, so a cell with more
    # neighbours does not get more weight purely for being in a dense area.
    degrees = np.asarray(weights.sum(axis=1)).ravel()
    degrees[degrees == 0] = 1.0
    cell_ids = [record.cell_id or str(index) for index, record in enumerate(dataset.records)]

    gene_rows: List[Dict[str, Any]] = []
    per_cell: Dict[str, Dict[str, Any]] = {}
    for gene in resolved:
        values = np.asarray(adata[:, gene].X, dtype=float).ravel()
        spread = float(values.std())
        if spread <= 0:
            gene_rows.append({"gene": gene, "status": "constant_expression", "hotspot_cells": 0})
            continue
        z = (values - float(values.mean())) / spread
        lag = np.asarray(weights @ z).ravel() / degrees
        local_i = z * lag

        # Conditional randomisation: hold this cell's own value fixed and permute
        # the rest, which is the null local Moran's I is defined against. A global
        # permutation would test a different, easier hypothesis.
        #
        # Scored as a z-score against the simulated null rather than as a count of
        # exceedances, because a counted permutation p cannot fall below
        # 1/(n_perms + 1) and BH over one test per cell multiplies that floor by
        # the cell count. Measured: at 999 permutations on 3,993 cells the
        # smallest reachable adjusted p was 1.0, so every gene reported zero
        # hotspots -- not because there were none, but because the test could not
        # express one. The z-score has no floor, so FDR is meaningful at this
        # scale. This is esda's `p_z_sim`, and the standard way the statistic is
        # reported for exactly this reason.
        rng = np.random.default_rng(int(params.get("random_state", 0) or 0))
        n_perms = max(99, int(params.get("n_perms", DEFAULT_LISA_PERMUTATIONS) or DEFAULT_LISA_PERMUTATIONS))
        total = np.zeros(len(z), dtype=float)
        total_squares = np.zeros(len(z), dtype=float)
        for _ in range(n_perms):
            shuffled = rng.permutation(z)
            null_local = z * (np.asarray(weights @ shuffled).ravel() / degrees)
            total += null_local
            total_squares += null_local * null_local
        null_mean = total / n_perms
        null_var = np.maximum(total_squares / n_perms - null_mean * null_mean, 0.0)
        null_sd = np.sqrt(null_var)
        # A cell whose null has no spread cannot be distinguished from it.
        usable = null_sd > 0
        zscores = np.zeros(len(z), dtype=float)
        zscores[usable] = (local_i[usable] - null_mean[usable]) / null_sd[usable]
        pvalues = np.ones(len(z), dtype=float)
        pvalues[usable] = np.array([erfc(abs(value) / sqrt(2.0)) for value in zscores[usable]])
        adjusted = _benjamini_hochberg(pvalues)

        quadrant = np.where(
            z > 0,
            np.where(lag > 0, "high-high", "high-low"),
            np.where(lag > 0, "low-high", "low-low"),
        )
        significant = adjusted <= alpha
        classes = np.where(significant, quadrant, "not-significant")
        counts = Counter(classes.tolist())
        gene_rows.append({
            "gene": gene,
            "status": "computed",
            "n_perms": int(n_perms),
            "max_abs_z": _round(float(np.max(np.abs(zscores))), 3),
            "cells_without_null_spread": int(np.sum(~usable)),
            "hotspot_cells": int(counts.get("high-high", 0)),
            "coldspot_cells": int(counts.get("low-low", 0)),
            "outlier_cells": int(counts.get("high-low", 0) + counts.get("low-high", 0)),
            "not_significant_cells": int(counts.get("not-significant", 0)),
            "hotspot_fraction": _round(float(counts.get("high-high", 0)) / max(len(z), 1)),
        })
        for index, cell_id in enumerate(cell_ids):
            per_cell.setdefault(cell_id, {})["lisa_%s" % gene] = str(classes[index])
            per_cell[cell_id]["lisa_%s_i" % gene] = _round(float(local_i[index]))
            per_cell[cell_id]["lisa_%s_padj" % gene] = _round(float(adjusted[index]), 6)

    return {
        "status": "computed" if gene_rows else "insufficient_data",
        "method": "local_morans_i_conditional_permutation",
        "graph": graph,
        "alpha": alpha,
        "n_perms": max(99, int(params.get("n_perms", DEFAULT_LISA_PERMUTATIONS) or DEFAULT_LISA_PERMUTATIONS)),
        "multiple_testing": "benjamini_hochberg_per_gene",
        "significance_basis": "conditional_randomisation_z_score",
        "permutation_note": (
            "Significance comes from a z-score against the conditional-randomisation null, not "
            "from counting exceedances. A counted permutation p cannot fall below 1/(n_perms + 1), "
            "and BH over one test per cell multiplies that floor by the cell count -- at 999 "
            "permutations on 4,000 cells nothing could reach alpha 0.05 and every gene reported "
            "zero hotspots. The z-score has no floor."
        ),
        "genes": gene_rows,
        "missing_genes": missing,
        "per_cell": per_cell,
        "interpretation": (
            "high-high marks a cell whose own expression and its neighbours' are both high; "
            "low-low both low. Local Moran's I is large in both cases, so the class matters as "
            "much as the value. high-low and low-high are spatial outliers, not hotspots."
        ),
    }


def ripley_cell_types(
    dataset: SpatialDataset,
    params: Optional[Dict[str, object]] = None,
) -> Dict[str, Any]:
    """Besag's L for each cell type, over radii the tissue can actually support.

    The point-pattern counterpart to neighbourhood enrichment: does a population
    cluster, disperse, or sit at complete spatial randomness, and at what scale.

    Computed here rather than through `squidpy.gr.ripley` for two reasons, both
    of which silently produced wrong verdicts when this used squidpy:

    1. squidpy simulates its CSR null inside the convex hull of all cells. A
       section is not its hull -- cortex is concave, ventricles are holes -- so
       the null was free to spread where no cell could be.
    2. `n_observations` defaults to 1000, so every group was compared against a
       1,000-point null whatever its own size. Besag's L depends on n, so a
       19,839-cell population and an 825-cell one were scored against the same
       envelope, and the comparison meant nothing. Here each group's envelope is
       simulated at that group's own cell count.

    Squidpy's default radius ceiling is half the bounding-box diagonal, which on a
    real section is two orders of magnitude past any interaction distance -- and
    the CSR null fills the bounding rectangle including the empty space around an
    irregular section. Run that way it reported every cell type in a healthy brain
    as dispersed. So the ceiling is derived from the observed nearest-neighbour
    distance, and both the cap and the reason are reported with the result.
    """
    from .implementations import _dataset_to_anndata, resolve_group_labels

    params = dict(params or {})
    try:
        import numpy as np  # type: ignore
        from scipy.spatial import cKDTree  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError("Ripley's L requires NumPy and SciPy in strict mode.") from exc
        return {"status": "not_computed", "reason": "NumPy/SciPy not installed: %s" % exc, "groups": []}

    labels, group_key = resolve_group_labels(dataset, params)
    counts = Counter(label for label in labels if label)
    min_cells = int(_number(params, "min_cells", MIN_CELLS_FOR_AUTOCORRELATION))
    if len([name for name, count in counts.items() if count >= min_cells]) < 1:
        return {
            "status": "insufficient_data",
            "reason": "No group has %d or more cells." % min_cells,
            "group_key": group_key,
            "groups": [],
        }

    coordinates = np.asarray([[record.x, record.y] for record in dataset.records], dtype=float)
    if len(coordinates) < 3:
        return {"status": "insufficient_data", "reason": "Fewer than three cells.", "groups": []}
    nearest, _indices = cKDTree(coordinates).query(coordinates, k=2)
    median_nearest = float(np.median(nearest[:, 1]))
    multiple = float(params.get("radius_neighbor_multiple", RIPLEY_RADIUS_NEIGHBOR_MULTIPLE)
                     or RIPLEY_RADIUS_NEIGHBOR_MULTIPLE)
    spans = [float(value) for value in np.ptp(coordinates, axis=0) if float(value) > 0]
    bbox_ceiling = 0.25 * min(spans) if spans else median_nearest * multiple
    max_dist = float(params.get("max_distance") or min(median_nearest * multiple, bbox_ceiling))
    default_max = 0.5 * float(np.hypot(*(np.ptp(coordinates, axis=0)))) if spans else max_dist
    if not np.isfinite(max_dist) or max_dist <= 0:
        return {"status": "insufficient_data", "reason": "No positive radius range.", "groups": []}

    n_steps = max(10, int(params.get("n_steps", 40) or 40))
    n_simulations = max(20, int(params.get("n_simulations", 100) or 100))
    min_effect = _number(params, "min_relative_deviation", RIPLEY_MIN_RELATIVE_DEVIATION)
    radii = np.linspace(0.0, max_dist, n_steps)

    # The observation window. squidpy draws its CSR points inside the convex hull
    # of all cells -- better than a bounding box, and still not the tissue: cortex
    # is concave, ventricles and tears are holes, and a hull round any of them
    # encloses space no cell could occupy. A population confined to a concave arm
    # then reads as clustered because the null was free to spread where the cells
    # were not.
    hull_area = None
    try:
        from scipy.spatial import ConvexHull  # type: ignore

        hull_area = float(ConvexHull(coordinates).volume)
    except Exception:  # noqa: BLE001 - the hull is a first area estimate and a contrast
        hull_area = None
    # Two passes: size the bins from the hull's area, then re-size from the mask
    # the first pass produced, which is closer to the truth for a concave section.
    reference_area = hull_area or float(np.prod(np.ptp(coordinates, axis=0)))
    bin_size = _window_bin_size(reference_area, len(coordinates), median_nearest)
    window = tissue_window(coordinates, bin_size)
    bin_size = _window_bin_size(window["area"], len(coordinates), median_nearest)
    window = tissue_window(coordinates, bin_size)

    rng = np.random.default_rng(int(params.get("random_state", 0) or 0))
    by_group: Dict[str, Any] = {}
    allowed, unreviewed_cells = _reviewed_filter(labels, counts, params, group_key)
    for name in sorted({label for label in labels if label}):
        if int(counts.get(name, 0)) < min_cells:
            continue
        if allowed is not None and name not in allowed:
            continue
        subset = coordinates[np.asarray([label == name for label in labels], dtype=bool)]
        observed = besag_l(subset, radii, window["area"])
        # The null is simulated at this group's own cell count, inside this
        # window. Simulating once for all groups would compare a 20,000-cell
        # population against the same envelope as an 800-cell one.
        simulated = np.vstack([
            besag_l(sample_in_window(window, len(subset), rng), radii, window["area"])
            for _ in range(n_simulations)
        ])
        by_group[name] = {
            "observed": observed,
            "upper": np.quantile(simulated, 0.975, axis=0),
            "lower": np.quantile(simulated, 0.025, axis=0),
            "median": np.median(simulated, axis=0),
        }
    if not by_group:
        return {"status": "insufficient_data", "reason": "No group met the cell-count floor.", "groups": []}

    rows: List[Dict[str, Any]] = []
    for name, curves in by_group.items():
        n_cells = int(counts.get(str(name), 0))
        bins = radii
        observed = curves["observed"]
        expected = curves["median"]
        upper = curves["upper"]
        lower = curves["lower"]
        deviation = observed - expected
        # r = 0 is degenerate (L is 0 for every pattern), so it is excluded from
        # the peak search rather than counted as agreement with CSR.
        usable = bins > 0
        if not usable.any():
            continue
        above = float(np.mean(observed[usable] > upper[usable]))
        below = float(np.mean(observed[usable] < lower[usable]))
        # Deviation as a fraction of the radius: how much wider or narrower the
        # effective neighbourhood is than under CSR.
        relative = np.zeros_like(deviation)
        np.divide(deviation, bins, out=relative, where=bins > 0)
        effect = float(np.max(np.abs(relative[usable]))) if usable.any() else 0.0
        outside_envelope = above >= 0.5 or below >= 0.5
        if not outside_envelope:
            verdict = "scale_dependent" if (above > 0.0 or below > 0.0) else "consistent_with_csr"
        elif effect < min_effect:
            # Outside the envelope everywhere, but by a margin too small to mean
            # anything. At this cell count the envelope is narrow enough that a
            # sub-micron bias clears it.
            verdict = "consistent_with_csr"
        elif above >= 0.5:
            verdict = "clustered"
        else:
            verdict = "dispersed"

        peak = peak_deviation_index(deviation, usable, verdict)
        rows.append({
            "group": str(name),
            "n_cells": n_cells,
            "peak_deviation": _round(float(deviation[peak]), 3),
            "peak_radius_um": _round(float(bins[peak]), 2),
            # True when the pattern crosses the envelope in both directions, so a
            # single peak cannot represent it and the scale matters.
            "deviation_sign_varies": bool(above > 0.0 and below > 0.0),
            "mean_deviation": _round(float(np.mean(deviation[usable])), 3),
            "radii_above_envelope": _round(above, 3),
            "radii_below_envelope": _round(below, 3),
            "relative_effect": _round(effect, 4),
            "verdict": verdict,
        })
    rows.sort(key=lambda row: -abs(row["peak_deviation"] or 0.0))

    return {
        "status": "computed" if rows else "insufficient_data",
        "method": "besag_L_vs_simulated_csr_envelope",
        "reference": "median of the simulated CSR envelope in the same window (not the theoretical L(r) = r line)",
        "group_key": group_key,
        "n_simulations": n_simulations,
        "n_steps": n_steps,
        "min_cells": min_cells,
        "reviewed_only": allowed is not None,
        "unreviewed_cells": unreviewed_cells,
        "median_nearest_neighbor_um": _round(median_nearest, 2),
        "max_distance_um": _round(max_dist, 2),
        "default_max_distance_um": _round(default_max, 2),
        "radius_rule": (
            "Radii are capped at %.1f x the median nearest-neighbour distance (%.1f um). "
            "squidpy's default is sqrt(area/2), which on this section is %.0f um -- beyond any "
            "interaction scale, where the statistic measures the shape of the section rather "
            "than the arrangement of cells within it."
            % (multiple, median_nearest, default_max)
        ),
        "window": "tissue_occupancy_mask",
        "window_bin_um": _round(bin_size, 2),
        "window_area_um2": _round(window["area"], 1),
        "window_occupied_bins": window["occupied_bins"],
        "window_filled_bins": window.get("filled_bins", 0),
        "window_resolution_note": (
            "The mask resolves structure down to about one bin (%.0f um). A feature thinner than "
            "two bins is over-covered, so its area is overestimated and a uniform population "
            "inside it can read as clustered -- an annulus 30 um wide measured 147%% of its true "
            "area at 17 um bins. Bin size is set by the cell density, which is what decides how "
            "small a bin can be before emptiness is chance rather than tissue."
            % bin_size
        ),
        "convex_hull_area_um2": _round(hull_area, 1) if hull_area else None,
        "window_area_fraction_of_hull": (
            _round(window["area"] / hull_area, 4) if hull_area else None
        ),
        "window_rule": (
            "The CSR null is simulated inside an occupancy mask of %d bins of %.0f um "
            "(%.0f um2), not inside the convex hull (%s um2) that squidpy uses. A section is not "
            "its hull: cortex is concave, ventricles and tears are holes, and a null free to "
            "spread into space no cell could occupy makes any population confined to a concave "
            "arm read as clustered. Each group's envelope is simulated at that group's own cell "
            "count, so a large population is not compared against a small one's null."
            % (window["occupied_bins"], bin_size, window["area"],
               ("%.0f" % hull_area) if hull_area else "unavailable")
        ),
        "min_relative_deviation": min_effect,
        "verdict_rule": (
            "A verdict of clustered or dispersed needs the observed curve outside the simulated "
            "envelope for at least half the radii AND a peak deviation of at least %.0f%% of the "
            "radius. The envelope alone is not enough: at thousands of cells it is narrow enough "
            "that a sub-micron systematic bias clears it, and a uniform control then reads as "
            "clustered." % (100 * min_effect)
        ),
        "estimator_note": (
            "Besag's L with no edge correction, applied identically to the observed pattern and "
            "to every simulation in the same window, so the edge bias is common to both and "
            "cancels in the comparison."
        ),
        "groups": rows,
    }


def bivariate_spatial_correlation(
    dataset: SpatialDataset,
    pairs: List[Tuple[str, str]],
    params: Optional[Dict[str, object]] = None,
) -> Dict[str, Any]:
    """Lee's L for named gene pairs: do these two co-vary *in space*?

    Marker detection can say two genes are high in the same cluster. It cannot say
    their expression fields overlap spatially, which is a different claim and the
    one people usually mean. Deliberately restricted to pairs a caller names --
    all-against-all on a 319-gene panel is 50,000 tests that nobody asked for, and
    Lee's L values are not comparable across pairs measured on different scales.
    """
    params = dict(params or {})
    pairs = [(str(a), str(b)) for a, b in pairs if str(a) and str(b)]
    if not pairs:
        return {"status": "not_run", "reason": "No gene pairs were requested.", "pairs": []}
    try:
        import numpy as np  # type: ignore
        import squidpy as sq  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError("Lee's L requires NumPy and Squidpy in strict mode.") from exc
        return {"status": "not_computed", "reason": "NumPy/Squidpy not installed: %s" % exc, "pairs": []}

    adata = _expression_adata(dataset)
    available = {str(name).upper(): str(name) for name in adata.var_names}
    graph = _neighbor_graph(sq, adata, max(2, int(params.get("n_neighs", 6) or 6)),
                            params.get("radius") if params.get("radius") is None else float(params["radius"]))
    weights = adata.obsp["spatial_connectivities"].astype(float)
    degrees = np.asarray(weights.sum(axis=1)).ravel()
    degrees[degrees == 0] = 1.0

    rows: List[Dict[str, Any]] = []
    for first, second in pairs:
        if first.upper() not in available or second.upper() not in available:
            rows.append({
                "gene_a": first, "gene_b": second, "status": "gene_not_in_panel",
                "lees_l": None,
            })
            continue
        x = _standardise(np.asarray(adata[:, available[first.upper()]].X, dtype=float).ravel())
        y = _standardise(np.asarray(adata[:, available[second.upper()]].X, dtype=float).ravel())
        if x is None or y is None:
            rows.append({"gene_a": first, "gene_b": second, "status": "constant_expression", "lees_l": None})
            continue
        lag_x = np.asarray(weights @ x).ravel() / degrees
        lag_y = np.asarray(weights @ y).ravel() / degrees
        lees_l = float(np.sum(lag_x * lag_y) / len(x))
        rows.append({
            "gene_a": first,
            "gene_b": second,
            "status": "computed",
            "lees_l": _round(lees_l),
            "pearson_r": _round(float(np.corrcoef(x, y)[0, 1])),
            "interpretation": (
                "spatially co-varying" if lees_l > 0.05 else
                "spatially anti-correlated" if lees_l < -0.05 else
                "no spatial co-variation"
            ),
        })
    return {
        "status": "computed",
        "method": "lees_l",
        "graph": graph,
        "pairs": rows,
        "comparability_caveat": (
            "Lee's L depends on the expression scale of both genes, so values are not comparable "
            "between pairs. Compare a pair against its own Pearson r -- a high Pearson with a low "
            "L means the genes covary per cell but not across space."
        ),
    }


def peak_deviation_index(deviation: Any, usable: Any, verdict: str) -> int:
    """Index of the deviation that represents `verdict`, not the largest in size.

    Taking argmax of |deviation| does not represent the verdict: measured on a
    real section, a myeloid population with 82% of its radii *below* the CSR
    envelope -- dispersed on every reading -- reported its peak as +0.5, because
    one small positive excursion happened to have the largest magnitude. The row
    then read "dispersed" beside a positive number, which is the same
    contradiction the envelope reference was introduced to remove, surviving one
    level further down in the peak selection.

    Extracted so the selection can be tested on the deviation curve that produced
    that row. The end-to-end test could not: no synthetic point pattern it
    generated mixed the signs the way real tissue does, so it passed against the
    broken version too.
    """
    import numpy as np  # type: ignore

    masked = np.where(usable, np.asarray(deviation, dtype=float), np.nan)
    if verdict == "clustered":
        candidates = np.where(masked > 0, masked, np.nan)
    elif verdict == "dispersed":
        candidates = np.where(masked < 0, -masked, np.nan)
    else:
        candidates = np.abs(masked)
    if np.all(np.isnan(candidates)):
        # No excursion in the verdict's direction: fall back to the largest in
        # magnitude rather than raising, and the sign still tells the reader the
        # peak disagrees with the majority.
        candidates = np.abs(masked)
    return int(np.nanargmax(candidates))


def _standardise(values: Any) -> Any:
    import numpy as np  # type: ignore

    spread = float(values.std())
    if spread <= 0:
        return None
    return (values - float(values.mean())) / spread


def _benjamini_hochberg(pvalues: Any) -> Any:
    """BH-adjusted p-values. Local statistics are one test per cell, so this is
    not a refinement -- without it a 20,000-cell section reports a thousand
    'significant' hotspots at alpha 0.05 by construction."""
    import numpy as np  # type: ignore

    pvalues = np.asarray(pvalues, dtype=float)
    n = len(pvalues)
    order = np.argsort(pvalues)
    ranked = pvalues[order] * n / (np.arange(n) + 1.0)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    adjusted = np.empty(n, dtype=float)
    adjusted[order] = np.clip(ranked, 0.0, 1.0)
    return adjusted


def _autocorrelation_phrase(value: Any) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "not computed"
    if score > 0.02:
        return "forms spatial patches"
    if score < -0.02:
        return "more evenly spread than chance"
    return "close to spatially random"


def _first(record: Any, keys: Tuple[str, ...]) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _number(params: Dict[str, object], key: str, default: float) -> float:
    """A numeric parameter, honouring an explicit zero.

    `params.get(key, default) or default` is the idiom used throughout this
    codebase and it silently discards a zero, because 0 is falsy. For most knobs
    that is harmless -- a permutation count of 0 is clamped anyway. For the ones
    where zero *means* something it is a bug: `min_cells=0` asks for the
    population floor to be lifted and `min_relative_deviation=0` asks for the
    effect-size floor to be lifted, and both silently kept their defaults. A test
    that set the threshold to 0 and asserted it was 0 is what found this.
    """
    value = params.get(key, default)
    if value is None:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _round(value: Any, digits: int = 4) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return round(number, digits)
