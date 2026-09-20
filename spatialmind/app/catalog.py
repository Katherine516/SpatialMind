"""Dataset discovery and a cheap cell index for the Studio app.

The review surface needs three things per cell: an id, a coordinate, and a
group to assign a label to. It needs none of the expression matrix. Loading the
full 540-gene panel just to answer "which cell ids are inside this rectangle"
costs minutes and gigabytes; reading ``cells.parquet`` plus the 10x cluster
table costs a few seconds, so that is what the index does. Expression is loaded
only when a tool actually runs.
"""

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import json
import time

from ..ingestion import (
    infer_data_type,
    list_xenium_cluster_methods,
    load_xenium_analysis_clusters,
)

XENIUM_TYPES = {"xenium_directory", "xenium_experiment_file"}
DEFAULT_CLUSTER_METHOD = "gene_expression_graphclust"
# A section is ~40k cells. Drawing every one of them is neither faster to send
# nor more readable on a 1200px canvas, so the client gets a sample and the
# server keeps the full index for resolving selections.
DEFAULT_DISPLAY_CELLS = 18000


def resolve_xenium_root(path: Path) -> Path:
    """`experiment.xenium` is a manifest; the bundle is its parent directory."""
    return path.parent if str(path).lower().endswith(".xenium") else path


def dataset_id_for(root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]
    slug = "".join(ch if ch.isalnum() else "-" for ch in path.name.lower()).strip("-")
    return "%s-%s" % (slug[:40] or "dataset", digest)


# Vendor scaffolding in a bundle name that carries no information for a reader:
# every Xenium folder has it, so it only pushes the part that differs off-screen.
NAME_NOISE = (
    "Xenium_V1_", "Xenium_", "_With_Addon_outs", "_With_Addon", "_Addon_outs",
    "_section_outs", "_Top_outs", "_outs",
)


def pretty_name(raw: str) -> str:
    """A readable dataset name: `Human Brain Glioblastoma`, not the folder name.

    Folder names run to 54 characters of boilerplate. Truncating one mid-word
    hides the only part that identifies it, so the noise is dropped first and
    the full name stays available underneath.
    """
    name = raw
    for suffix in NAME_NOISE:
        if suffix.startswith("_") and name.endswith(suffix):
            name = name[: -len(suffix)]
        elif not suffix.startswith("_") and name.startswith(suffix):
            name = name[len(suffix):]
    if name.lower().endswith(".h5ad"):
        name = name[: -len(".h5ad")]
    name = name.replace("_", " ").replace("-", " ").strip()
    name = " ".join(part for part in name.split() if part)
    return name or raw


@dataclass
class DatasetEntry:
    dataset_id: str
    name: str
    path: str
    relative_path: str
    data_type: str
    reviewable: bool

    @property
    def display_name(self) -> str:
        return pretty_name(self.name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "display_name": self.display_name,
            "path": self.path,
            "relative_path": self.relative_path,
            "data_type": self.data_type,
            "reviewable": self.reviewable,
        }



# Tables that stand alone as a dataset. A `.csv.gz` inside a Xenium bundle is
# excluded by `_inside_dataset`, not by its name.
TABULAR_SUFFIXES = {".csv", ".tsv"}
VISIUM_MARKERS = ("filtered_feature_bc_matrix.h5", "spatial")


def _is_tabular(candidate: Path) -> bool:
    name = candidate.name.lower()
    if name.endswith(".gz"):
        name = name[:-3]
    return Path(name).suffix in TABULAR_SUFFIXES


def _looks_like_visium_dir(candidate: Path) -> bool:
    try:
        present = {child.name for child in candidate.iterdir()}
    except OSError:
        return False
    return all(marker in present for marker in VISIUM_MARKERS)


def _inside_dataset(candidate: Path, seen: set) -> bool:
    """True when this path sits inside a dataset already catalogued."""
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    for parent in resolved.parents:
        if parent in seen:
            return True
    return False


def discover_datasets(data_root: str) -> List[DatasetEntry]:
    """Find analysable datasets under ``data_root``.

    Xenium bundles are reviewable; other supported formats are listed but cannot
    drive the review/gate flow, and say so rather than being hidden.
    """
    root = Path(data_root).expanduser().resolve()
    if not root.exists():
        return []
    entries: List[DatasetEntry] = []
    seen: set = set()

    for candidate in sorted(root.rglob("*")):
        if candidate.name.startswith("."):
            continue
        if _inside_dataset(candidate, seen):
            # A Xenium bundle's own cells.csv.gz is not a second dataset.
            continue
        if candidate.is_dir():
            if (candidate / "experiment.xenium").exists() or _looks_like_visium_dir(candidate):
                resolved = candidate.resolve()
            elif candidate.suffix.lower() == ".zarr":
                resolved = candidate.resolve()
            else:
                continue
        elif candidate.suffix.lower() in {".h5ad", ".xenium"}:
            resolved = resolve_xenium_root(candidate).resolve()
        elif _is_tabular(candidate):
            # An uploaded table is a dataset in its own right. Listing only
            # .h5ad and Xenium meant a user could upload a CSV, get a success
            # message, and never see it again.
            resolved = candidate.resolve()
        else:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            data_type = infer_data_type(str(resolved))
        except Exception:
            data_type = "unknown"
        entries.append(
            DatasetEntry(
                dataset_id=dataset_id_for(root, resolved),
                name=resolved.name,
                path=str(resolved),
                relative_path=_relative(root, resolved),
                data_type=data_type,
                reviewable=data_type in XENIUM_TYPES,
            )
        )
    return entries


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


@dataclass
class CellIndex:
    """Cell ids, coordinates and cluster assignments for one Xenium bundle."""

    dataset_path: str
    cell_ids: List[str]
    xs: List[float]
    ys: List[float]
    clusters: List[str]
    counts: List[float]
    cluster_method: str
    cluster_methods: List[str] = field(default_factory=list)
    built_seconds: float = 0.0

    @property
    def n_cells(self) -> int:
        return len(self.cell_ids)

    def bounds(self) -> Dict[str, float]:
        if not self.xs:
            return {"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0}
        return {
            "x_min": min(self.xs),
            "x_max": max(self.xs),
            "y_min": min(self.ys),
            "y_max": max(self.ys),
        }

    def cluster_sizes(self) -> Dict[str, int]:
        sizes: Dict[str, int] = {}
        for cluster in self.clusters:
            sizes[cluster] = sizes.get(cluster, 0) + 1
        return dict(sorted(sizes.items(), key=_cluster_sort_key))

    def ids_in_cluster(self, cluster: str) -> List[str]:
        target = str(cluster)
        return [cid for cid, value in zip(self.cell_ids, self.clusters) if value == target]

    def ids_in_rect(self, x0: float, y0: float, x1: float, y1: float) -> List[str]:
        lo_x, hi_x = (x0, x1) if x0 <= x1 else (x1, x0)
        lo_y, hi_y = (y0, y1) if y0 <= y1 else (y1, y0)
        return [
            cid
            for cid, x, y in zip(self.cell_ids, self.xs, self.ys)
            if lo_x <= x <= hi_x and lo_y <= y <= hi_y
        ]

    def display_sample(self, limit: int = DEFAULT_DISPLAY_CELLS) -> Dict[str, Any]:
        """Every Nth cell, so the drawn map keeps the section's real density."""
        total = self.n_cells
        step = 1 if total <= limit else (total // limit) + 1
        idx = list(range(0, total, step))
        return {
            "step": step,
            "indices": idx,
            "cell_ids": [self.cell_ids[i] for i in idx],
            "x": [round(self.xs[i], 2) for i in idx],
            "y": [round(self.ys[i], 2) for i in idx],
            "cluster": [self.clusters[i] for i in idx],
        }


def _cluster_sort_key(item: Tuple[str, int]) -> Tuple[int, Any]:
    value = item[0]
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, value)


def build_cell_index(dataset_path: str, cluster_method: str = "") -> CellIndex:
    started = time.time()
    root = resolve_xenium_root(Path(dataset_path))
    cell_ids, xs, ys, counts = _read_cell_table(root)

    methods = list_xenium_cluster_methods(str(root))
    method = cluster_method or (DEFAULT_CLUSTER_METHOD if DEFAULT_CLUSTER_METHOD in methods else (methods[0] if methods else ""))
    lookup = load_xenium_analysis_clusters(str(root), method=method) if method else {}
    # A cell with no 10x cluster is still a real cell. Calling it "unclustered"
    # keeps it selectable and countable instead of dropping it from coverage.
    clusters = [lookup.get(cid, "unclustered") for cid in cell_ids]

    return CellIndex(
        dataset_path=str(root),
        cell_ids=cell_ids,
        xs=xs,
        ys=ys,
        clusters=clusters,
        counts=counts,
        cluster_method=method or "none",
        cluster_methods=methods,
        built_seconds=round(time.time() - started, 2),
    )


def _read_cell_table(root: Path) -> Tuple[List[str], List[float], List[float], List[float]]:
    parquet = root / "cells.parquet"
    if parquet.exists():
        try:
            return _read_cell_parquet(parquet)
        except Exception:
            pass  # fall through to the CSV, which every bundle ships
    for name in ("cells.csv.gz", "cells.csv"):
        candidate = root / name
        if candidate.exists():
            return _read_cell_csv(candidate)
    raise FileNotFoundError("No cell table (cells.parquet / cells.csv.gz) under %s" % root)


def _read_cell_parquet(path: Path) -> Tuple[List[str], List[float], List[float], List[float]]:
    import pandas as pd

    frame = pd.read_parquet(path)
    ids = [_decode_id(value) for value in frame["cell_id"].tolist()]
    xs = [float(v) for v in frame["x_centroid"].tolist()]
    ys = [float(v) for v in frame["y_centroid"].tolist()]
    counts_col = "transcript_counts" if "transcript_counts" in frame.columns else None
    counts = [float(v) for v in frame[counts_col].tolist()] if counts_col else [0.0] * len(ids)
    return ids, xs, ys, counts


def _read_cell_csv(path: Path) -> Tuple[List[str], List[float], List[float], List[float]]:
    import csv
    import gzip

    opener = gzip.open if path.suffix == ".gz" else open
    ids: List[str] = []
    xs: List[float] = []
    ys: List[float] = []
    counts: List[float] = []
    with opener(str(path), "rt", newline="") as handle:  # type: ignore[operator]
        for row in csv.DictReader(handle):
            ids.append(_decode_id(row.get("cell_id", "")))
            xs.append(_as_float(row.get("x_centroid")))
            ys.append(_as_float(row.get("y_centroid")))
            counts.append(_as_float(row.get("transcript_counts")))
    return ids, xs, ys, counts


def _decode_id(value: Any) -> str:
    """Xenium parquet stores cell ids as bytes; the CSVs store them as text."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    return str(value).strip().strip('"').strip("'")


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class IndexCache:
    """Keeps a few built indexes in memory; building one costs seconds."""

    def __init__(self, max_entries: int = 3) -> None:
        self._entries: Dict[str, CellIndex] = {}
        self._order: List[str] = []
        self._max = max_entries
        self._lock = RLock()

    def get(self, dataset_path: str, cluster_method: str = "") -> CellIndex:
        key = "%s::%s" % (dataset_path, cluster_method)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._order.remove(key)
                self._order.append(key)
                return cached
        index = build_cell_index(dataset_path, cluster_method=cluster_method)
        with self._lock:
            self._entries[key] = index
            self._order.append(key)
            while len(self._order) > self._max:
                self._entries.pop(self._order.pop(0), None)
        return index

    def invalidate(self, dataset_path: Optional[str] = None) -> None:
        with self._lock:
            if dataset_path is None:
                self._entries.clear()
                self._order.clear()
                return
            for key in [k for k in self._order if k.startswith("%s::" % dataset_path)]:
                self._entries.pop(key, None)
                self._order.remove(key)


# Control probes are named by prefix in every Xenium panel file; they are not
# genes and offering one as "a gene to overlay" is a bug the user cannot see.
CONTROL_PREFIXES = ("negcontrol", "blank", "antisense", "unassigned", "deprecated")


def panel_genes(dataset_path: str) -> List[str]:
    """Measured gene symbols for a Xenium bundle, in panel order.

    Read so the app can check a gene a user typed against what the slide
    actually measured. On a targeted assay that check is the difference between
    "not expressed" and "not looked for".
    """
    path = Path(dataset_path)
    candidate = path / "gene_panel.json" if path.is_dir() else path.parent / "gene_panel.json"
    if not candidate.exists():
        return []
    try:
        with open(candidate, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    names: List[str] = []
    for target in ((payload.get("payload") or {}).get("targets") or []):
        if not isinstance(target, dict):
            continue
        data = (target.get("type") or {}).get("data") or {}
        name = str(data.get("name") or "").strip()
        if not name or name.lower().startswith(CONTROL_PREFIXES):
            continue
        if name not in names:
            names.append(name)
    return names
