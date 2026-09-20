"""Compile the analysis kernels before anyone asks for an analysis.

scanpy's clustering and Moran's I kernels are numba-jitted with `cache=True`,
which in a checkout writes to the virtualenv's `__pycache__` and works silently.
It does not survive freezing: a PyInstaller module's `__file__` points into the
bundled archive rather than at a file on disk, numba cannot build the source
stamp its cache index needs, and caching is disabled without saying so. Pointing
`NUMBA_CACHE_DIR` somewhere writable does not fix it -- measured, and the
directory stays empty -- because the problem is the source stamp, not the
destination.

So the compilation cannot be avoided or reused. It can be moved. Running the
same tools once over a tiny synthetic section compiles exactly the
specialisations a real section needs -- same functions, same float64 signatures --
and doing that on a background thread while the window is up spends it against
time the person is reading their dataset list rather than waiting on a progress
bar.

Measured on the healthy brain section, cold: first analysis 72.5s. With this,
30.1s, against 32.1s of background work that overlaps the user's own.
"""

from typing import Any, Dict, List, Optional
import logging
import os
import threading
import time

# Deliberately small: the point is to compile, not to compute. 120 cells over 12
# genes is enough to reach every kernel and takes no measurable time itself.
WARMUP_CELLS = 120
WARMUP_GENES = 12

_started = threading.Lock()
_done = False


def disabled() -> bool:
    return bool(os.environ.get("SPATIALMIND_NO_WARMUP"))


def _synthetic_dataset():
    from ..schemas import SpatialDataset, SpotRecord

    genes = ["WARMUP_G%d" % index for index in range(WARMUP_GENES)]
    records = [
        SpotRecord(
            "warmup",
            float(index % 12),
            float(index // 12),
            "a" if index % 2 else "b",
            {gene: float((index + position) % 5 + 1) for position, gene in enumerate(genes)},
            cell_id="warmup-%d" % index,
        )
        for index in range(WARMUP_CELLS)
    ]
    return SpatialDataset(
        sample_id="warmup", records=records, source_path="warmup",
        modality="spatial_transcriptomics", coordinate_system="microns",
    )


# The two tools that carry the compilation: clustering pulls in the neighbour
# graph and Leiden, spatial_variable_genes pulls in Moran's I. Permutations are
# cut to the minimum -- they are what the kernels do, not what compiles them.
WARMUP_PLAN: List[Dict[str, Any]] = [
    {"tool": "qc_and_cluster",
     "params": {"resolution": 0.55, "random_state": 0, "strict_engine": True}},
    {"tool": "spatial_variable_genes",
     "params": {"n_top": 8, "n_neighs": 6, "n_perms": 10, "random_state": 0, "strict_engine": True}},
]


def warm_kernels() -> Dict[str, Any]:
    """Run the plan over synthetic data. Returns what happened, for the log."""
    from ..tools import build_default_registry
    from ..tools.implementations import clear_anndata_cache

    started = time.time()
    registry = build_default_registry()
    compiled, skipped = [], []
    for step in WARMUP_PLAN:
        try:
            # The cache is keyed on the live dataset, and the synthetic one is
            # discarded each time; clearing keeps a warmup matrix from being the
            # entry a real run finds.
            clear_anndata_cache()
            registry.get(step["tool"]).run(_synthetic_dataset(), dict(step["params"]))
            compiled.append(step["tool"])
        except Exception as exc:
            # A warmup that cannot run is a slower first analysis, never a
            # failure: the real run will compile what this one did not.
            skipped.append("%s (%s)" % (step["tool"], str(exc)[:80]))
    clear_anndata_cache()
    return {"seconds": round(time.time() - started, 1), "compiled": compiled, "skipped": skipped}


def start_background_warmup() -> Optional[threading.Thread]:
    """Kick the warmup off once, on a daemon thread. Returns it, or None."""
    global _done
    if disabled():
        logging.info("kernel warmup disabled by SPATIALMIND_NO_WARMUP")
        return None
    with _started:
        if _done:
            return None
        _done = True

    def run() -> None:
        try:
            outcome = warm_kernels()
            logging.info(
                "kernel warmup finished in %.1fs (compiled: %s%s)",
                outcome["seconds"], ", ".join(outcome["compiled"]) or "nothing",
                "; skipped: " + "; ".join(outcome["skipped"]) if outcome["skipped"] else "",
            )
        except Exception:
            logging.exception("kernel warmup failed; the first analysis will compile instead")

    thread = threading.Thread(target=run, name="numba-warmup", daemon=True)
    thread.start()
    return thread
