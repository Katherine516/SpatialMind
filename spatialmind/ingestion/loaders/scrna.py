import os
import random
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spatialmind.ingestion.pipeline import DataIngestionLayer, IngestionValidationError
from spatialmind.schemas import SpatialDataset, SpotRecord


def load_scrna(path: str, sample_id: Optional[str] = None, max_records: int = 5000) -> SpatialDataset:
    dataset = _load_matrix_like(path, sample_id=sample_id, max_records=max_records)
    dataset.modality = "scrna"
    dataset.coordinate_system = "embedding_or_index"
    dataset.metadata["assay_subtype"] = "scrna"
    dataset.metadata["feature_type"] = "gene_counts"
    dataset.metadata["resolution"] = "single_cell"
    dataset.metadata["is_targeted_panel"] = False
    dataset.processing_steps.append("Loaded as MVP scRNA cell-by-feature dataset.")
    return dataset


def load_scrna_reference_set(
    paths: Sequence[str],
    sample_id: Optional[str] = None,
    max_records_per_file: int = 5000,
) -> SpatialDataset:
    """Concatenate several scRNA files into one labelled reference.

    Atlases are often distributed one cell class per file (CELLxGENE splits the
    Siletti adult human brain atlas by supercluster), and a single-class file
    cannot support label transfer. Loading several and combining them produces a
    usable multi-class reference.

    Refuses to mix organisms, since cross-species gene symbols collide once
    uppercased.
    """
    if not paths:
        raise IngestionValidationError("load_scrna_reference_set requires at least one reference path.")
    datasets = [load_scrna(path, max_records=max_records_per_file) for path in paths]
    organisms = {str(item.metadata.get("organism") or "").strip().lower() for item in datasets}
    organisms.discard("")
    if len(organisms) > 1:
        raise IngestionValidationError(
            "Reference files span multiple organisms (%s); combine same-species references only."
            % ", ".join(sorted(organisms))
        )
    combined = datasets[0]
    if len(datasets) > 1:
        for extra in datasets[1:]:
            combined.records.extend(extra.records)
        combined.sources = [source for item in datasets for source in item.sources]
    combined.sample_id = sample_id or combined.sample_id
    combined.metadata["reference_file_count"] = len(datasets)
    combined.metadata["reference_paths"] = [str(path) for path in paths]
    combined.metadata["reference_cell_classes"] = combined.cell_types
    combined.processing_steps.append(
        "Combined %d scRNA reference files into one labelled reference." % len(datasets)
    )
    return combined


# Above this, anndata's eager read of layers/raw is the difference between a
# usable reference and a killed process. The Core GBmap atlas is 7.6 GB on disk
# and over 54 GB expanded.
LARGE_H5AD_BYTES = 2 * 1024 ** 3


def _load_matrix_like(path: str, sample_id: Optional[str], max_records: int = 5000) -> SpatialDataset:
    layer = DataIngestionLayer()
    suffix = Path(path).suffix.lower()
    if suffix == ".h5ad":
        # A large atlas has to be streamed. anndata's backed mode covers X only,
        # so opening one whose layers dwarf X kills the process, and the fallback
        # is a full in-memory read -- worse. Read the wanted rows through h5py.
        try:
            if os.path.getsize(path) >= LARGE_H5AD_BYTES:
                return read_h5ad_subsample(path, max_records=max_records, sample_id=sample_id)
        except OSError:
            pass
        # Dissociated scRNA has no spatial coordinates; that must not block loading.
        return layer.load_h5ad(path, sample_id=sample_id, max_records=max_records, require_spatial=False)
    return layer.load(path, sample_id=sample_id)


def read_h5ad_subsample(
    path: str,
    max_records: int = 5000,
    sample_id: Optional[str] = None,
    seed: int = 0,
) -> SpatialDataset:
    """Read a bounded row sample from a large `.h5ad` without materialising it.

    anndata's backed mode covers `X` only. `layers`, `raw` and `obsm` are read
    eagerly, so opening an atlas whose layers total 37 GB uncompressed kills the
    process before a single cell is sampled -- and `_open_h5ad` then falls back
    to a full in-memory read, which is worse. The Core GBmap reference is 7.6 GB
    on disk and over 54 GB expanded; it could not be loaded at all.

    Reading the rows we actually want through h5py never touches `layers` or
    `raw`. The draw is seeded and stratified by class, so a reference contributes
    the same cells on every run and every class it declares is present in the
    sample -- see `_stratified_rows` for why proportional sampling is the wrong
    choice here.
    """
    import h5py
    import numpy as np

    with h5py.File(path, "r") as handle:
        gene_names = _h5_gene_names(handle["var"])
        cell_ids = _h5_string_index(handle["obs"])
        labels = _h5_categorical(handle["obs"], ("cell_type", "celltype", "cell_type_ontology_term_id"))
        organism = _h5_categorical(handle["obs"], ("organism",))

        total = len(cell_ids)
        limit = total if max_records <= 0 else min(max_records, total)
        rows = _stratified_rows(labels, total, limit, seed)

        matrix = handle["X"]
        records: List[SpotRecord] = []
        sample = sample_id or Path(path).stem
        if isinstance(matrix, h5py.Group):
            # CSR: slice each wanted row through indptr rather than reading all.
            indptr = matrix["indptr"]
            data = matrix["data"]
            indices = matrix["indices"]
            for position, row in enumerate(rows):
                start, end = int(indptr[row]), int(indptr[row + 1])
                if end <= start:
                    genes: Dict[str, float] = {}
                else:
                    cols = indices[start:end]
                    vals = data[start:end]
                    genes = {
                        gene_names[int(c)]: float(v)
                        for c, v in zip(cols, vals)
                        if int(c) < len(gene_names) and float(v) != 0.0
                    }
                records.append(
                    SpotRecord(
                        sample_id=sample,
                        x=float(position),
                        y=0.0,
                        cell_type=labels[row] if row < len(labels) else "",
                        genes=genes,
                        raw_genes=dict(genes),
                        cell_id=cell_ids[row] if row < len(cell_ids) else "cell_%d" % row,
                    )
                )
        else:
            for position, row in enumerate(rows):
                values = np.asarray(matrix[row, :])
                genes = {
                    gene_names[i]: float(v)
                    for i, v in enumerate(values)
                    if float(v) != 0.0 and i < len(gene_names)
                }
                records.append(
                    SpotRecord(
                        sample_id=sample,
                        x=float(position),
                        y=0.0,
                        cell_type=labels[row] if row < len(labels) else "",
                        genes=genes,
                        raw_genes=dict(genes),
                        cell_id=cell_ids[row] if row < len(cell_ids) else "cell_%d" % row,
                    )
                )

    dataset = SpatialDataset(
        sample_id=sample,
        records=records,
        source_path=path,
        modality="scrna",
        coordinate_system="embedding_or_index",
    )
    dataset.metadata.update({
        "assay_subtype": "scrna",
        "feature_type": "gene_counts",
        "is_targeted_panel": False,
        "organism": (organism[0] if organism else ""),
        "sampling": {"total_records": total, "scanned_records": len(rows), "method": "stratified_by_class", "seed": seed},
        "read_strategy": "h5py_subsample",
    })
    dataset.processing_steps.append(
        "Read %d of %d cells stratified by class through h5py; layers and raw were not touched."
        % (len(records), total)
    )
    return dataset


def _stratified_rows(labels: List[str], total: int, limit: int, seed: int) -> List[int]:
    """Row indices covering every class, not just the common ones.

    A proportional draw is the wrong sample for a reference. Label transfer votes
    over the classes the reference *contains*, so a class missing from the sample
    is a class the transfer can never assign -- and the preflight, which reads the
    file's declared categories rather than the sample, will have promised it.

    That gap is not hypothetical: a seeded draw of 6,000 from the 338,564-cell
    GBmap atlas missed neurons entirely, and the transfer refused an incomplete
    reference for a lineage the file demonstrably carries. Filling each class in
    turn keeps rare ones present at the cost of their true proportions, which
    matters far less to a neighbour vote than their absence does.
    """
    rng = random.Random(seed)
    if limit >= total:
        return list(range(total))
    if not labels or len(labels) < total:
        return sorted(rng.sample(range(total), limit))

    by_class: Dict[str, List[int]] = {}
    for index, label in enumerate(labels):
        by_class.setdefault(label or "", []).append(index)
    for members in by_class.values():
        rng.shuffle(members)

    chosen: List[int] = []
    classes = sorted(by_class)
    cursor = {name: 0 for name in classes}
    # Round-robin so every class contributes before any class contributes twice.
    while len(chosen) < limit:
        progressed = False
        for name in classes:
            if len(chosen) >= limit:
                break
            position = cursor[name]
            members = by_class[name]
            if position < len(members):
                chosen.append(members[position])
                cursor[name] = position + 1
                progressed = True
        if not progressed:
            break
    return sorted(chosen)


def _h5_gene_names(var_group) -> List[str]:
    """Gene symbols, preferring `feature_name` over the index.

    CELLxGENE keys `var` by Ensembl ID and puts symbols in `feature_name`. A
    Xenium panel is symbols, so reading the index gives an overlap of zero --
    and a transfer over no shared features is not an error that announces
    itself, it is a confident answer computed from nothing.
    """
    for column in ("feature_name", "gene_symbols", "symbol", "gene_name"):
        names = _h5_categorical(var_group, (column,))
        if names:
            return names
    return _h5_string_index(var_group)


def _h5_string_index(group) -> List[str]:
    """The `_index` column of an h5ad obs/var group, decoded."""
    import h5py

    key = group.attrs.get("_index", "_index")
    if isinstance(key, bytes):
        key = key.decode()
    node = group.get(key)
    if node is None:
        return []
    values = node[:] if not isinstance(node, h5py.Group) else node["categories"][:]
    return [v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v) for v in values]


def _h5_categorical(group, candidates) -> List[str]:
    """Decode a categorical obs column to plain strings."""
    import h5py

    for name in candidates:
        node = group.get(name)
        if node is None:
            continue
        if isinstance(node, h5py.Group) and "categories" in node and "codes" in node:
            cats = [c.decode("utf-8", "replace") if isinstance(c, bytes) else str(c) for c in node["categories"][:]]
            codes = node["codes"][:]
            return [cats[c] if 0 <= c < len(cats) else "" for c in codes]
        values = node[:]
        return [v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v) for v in values]
    return []
