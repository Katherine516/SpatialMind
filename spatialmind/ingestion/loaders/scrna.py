import os
import random
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from spatialmind.ingestion.pipeline import DataIngestionLayer, IngestionValidationError
from spatialmind.schemas import SpatialDataset, SpotRecord


def load_scrna(
    path: str,
    sample_id: Optional[str] = None,
    max_records: int = 5000,
    keep_features: Optional[Sequence[str]] = None,
    expression_semantics: str = "auto",
    expression_layer: str = "auto",
    allowed_donors: Optional[Sequence[str]] = None,
) -> SpatialDataset:
    dataset = _load_matrix_like(
        path, sample_id=sample_id, max_records=max_records, keep_features=keep_features,
        expression_semantics=expression_semantics, expression_layer=expression_layer,
        allowed_donors=allowed_donors,
    )
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
    keep_features: Optional[Sequence[str]] = None,
    progress: Optional[Callable[[str], None]] = None,
    expression_semantics: str = "auto",
    expression_layer: str = "auto",
    allowed_donors: Optional[Sequence[str]] = None,
) -> SpatialDataset:
    """Concatenate several scRNA files into one labelled reference.

    Atlases are often distributed one cell class per file (CELLxGENE splits the
    Siletti adult human brain atlas by supercluster), and a single-class file
    cannot support label transfer. Loading several and combining them produces a
    usable multi-class reference.

    Refuses to mix organisms, since cross-species gene symbols collide once
    uppercased.

    `max_records_per_file` is per file, and the atlas case this function exists
    for is exactly where that multiplies: seven superclusters at 30,000 each is
    210,000 reference cells, not 30,000. Callers should say so in their help text.

    `keep_features` is the target panel. Passing it restricts each reference row
    to genes the transfer can use, which is the difference between this finishing
    and not on a multi-file atlas. `progress` receives one line per file, because
    a job with no output for an hour is indistinguishable from a hung one.
    """
    if not paths:
        raise IngestionValidationError("load_scrna_reference_set requires at least one reference path.")
    if len({str(Path(path).resolve()) for path in paths}) != len(paths):
        raise IngestionValidationError("The same reference file cannot be included more than once.")
    datasets = []
    for index, path in enumerate(paths, start=1):
        if progress:
            progress("reference %d/%d: reading %s" % (index, len(paths), Path(path).name))
        item = load_scrna(path, max_records=max_records_per_file, keep_features=keep_features,
                          expression_semantics=expression_semantics, expression_layer=expression_layer,
                          allowed_donors=allowed_donors)
        if progress:
            progress(
                "reference %d/%d: %s -> %d cells, %d classes"
                % (index, len(paths), Path(path).name, len(item.records), len(item.cell_types))
            )
        datasets.append(item)
    organisms = {str(item.metadata.get("organism") or "").strip().lower() for item in datasets}
    organisms.discard("")
    if len(organisms) > 1:
        raise IngestionValidationError(
            "Reference files span multiple organisms (%s); combine same-species references only."
            % ", ".join(sorted(organisms))
        )
    semantics = {item.metadata.get("source_value_semantics") for item in datasets}
    if len(semantics) > 1:
        raise IngestionValidationError("Reference expression semantics differ; supply consistently processed references.")
    combined = datasets[0]
    if len(datasets) > 1:
        provenance = {}
        for path, item in zip(paths, datasets):
            from spatialmind.ingestion.identity import file_sha256, observation_id
            cached = item.metadata.get("identity_scheme") == "source_sha256_and_original_cell_id_v1"
            source_sha = item.metadata.get("source_content_sha256") if cached else file_sha256(path)
            old_provenance = item.metadata.get("observation_provenance") or {}
            for record in item.records:
                original = record.cell_id
                record.cell_id = original if cached else observation_id(source_sha, original)
                if record.cell_id in provenance:
                    raise IngestionValidationError("Reference source observations overlap, including copied files or overlapping caches.")
                origin = old_provenance.get(original) or {"source_cell_id": original}
                provenance[record.cell_id] = dict(origin, source_path=str(Path(path).resolve()),
                                                 source_content_sha256=source_sha)
        for extra in datasets[1:]:
            combined.records.extend(extra.records)
        combined.sources = [source for item in datasets for source in item.sources]
        combined.metadata["observation_provenance"] = provenance
        combined.metadata["identity_namespace"] = "source_sha256_and_original_cell_id_v1; portable, byte-version bound"
        combined.metadata["donor_ids"] = sorted({donor for item in datasets for donor in item.metadata.get("donor_ids", [])})
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


def _load_matrix_like(
    path: str,
    sample_id: Optional[str],
    max_records: int = 5000,
    keep_features: Optional[Sequence[str]] = None,
    expression_semantics: str = "auto",
    expression_layer: str = "auto",
    allowed_donors: Optional[Sequence[str]] = None,
) -> SpatialDataset:
    layer = DataIngestionLayer()
    suffix = Path(path).suffix.lower()
    if suffix == ".h5ad":
        # A large atlas has to be streamed. anndata's backed mode covers X only,
        # so opening one whose layers dwarf X kills the process, and the fallback
        # is a full in-memory read -- worse. Read the wanted rows through h5py.
        stream = (expression_layer != "auto" or allowed_donors is not None or keep_features is not None
                  or os.path.getsize(path) >= LARGE_H5AD_BYTES)
        if not stream:
            import h5py
            from spatialmind.ingestion.h5ad_access import scalar
            with h5py.File(path, "r") as handle:
                stream = scalar(handle, "uns/spatialmind/identity_scheme") == "source_sha256_and_original_cell_id_v1"
        if stream:
            return read_h5ad_subsample(
                path, max_records=max_records, sample_id=sample_id, keep_features=keep_features,
                expression_semantics=expression_semantics, expression_layer=expression_layer,
                allowed_donors=allowed_donors,
            )
        # Dissociated scRNA has no spatial coordinates; that must not block loading.
        return layer.load_h5ad(path, sample_id=sample_id, max_records=max_records, require_spatial=False,
                               expression_semantics=expression_semantics)
    if expression_layer != "auto" or allowed_donors is not None:
        raise IngestionValidationError("Explicit layer/donor selection requires H5AD input.")
    return layer.load(path, sample_id=sample_id)


def read_h5ad_subsample(
    path: str,
    max_records: int = 5000,
    sample_id: Optional[str] = None,
    seed: int = 0,
    keep_features: Optional[Sequence[str]] = None,
    expression_semantics: str = "auto",
    expression_layer: str = "auto",
    allowed_donors: Optional[Sequence[str]] = None,
) -> SpatialDataset:
    """Read a bounded row sample from a large `.h5ad` without materialising it.

    anndata's backed mode covers `X` only. `layers`, `raw` and `obsm` are read
    eagerly, so opening an atlas whose layers total 37 GB uncompressed kills the
    process before a single cell is sampled -- and `_open_h5ad` then falls back
    to a full in-memory read, which is worse. The Core GBmap reference is 7.6 GB
    on disk and over 54 GB expanded; it could not be loaded at all.

    Reading wanted rows through h5py supports explicit X, raw.X (with its own
    var), or named layers without materialising unused matrices. Auto selection
    prefers a named counts layer, then X. Donor selection precedes label reads
    and seeded class-stratified sampling; class coverage remains bounded by the
    sample size, and this is not a donor-balanced sampling strategy.

    `keep_features` restricts each row to the genes the caller can actually use.
    Label transfer intersects the reference against a ~320-gene Xenium panel and
    discards the rest, but every row was first materialised as a Python dict over
    all ~58,000 reference genes -- 2,300 `int()`/`float()` conversions per cell,
    for values thrown away immediately. Filtering before the dict is built
    measured 5.3x faster on the row loop and cuts per-record memory about 180x,
    which is what took a seven-file atlas from not finishing to finishing.
    """
    import h5py
    import numpy as np
    from spatialmind.ingestion.h5ad_access import select_matrix, scalar, column_values

    with h5py.File(path, "r") as handle:
        try:
            matrix, var, matrix_path, semantics = select_matrix(handle, expression_layer, expression_semantics)
        except ValueError as exc:
            raise IngestionValidationError(str(exc)) from exc
        gene_names = _h5_gene_names(var)
        # Column mask for the wanted genes, matched case-insensitively because
        # panel and atlas symbols differ only in case often enough to matter.
        keep_mask = None
        if keep_features is not None:
            wanted = {str(name).strip().upper() for name in keep_features if str(name).strip()}
            keep_mask = np.array([str(name).upper() in wanted for name in gene_names], dtype=bool)
            if not keep_mask.any():
                raise IngestionValidationError("Requested feature panel has no overlap with the selected reference layer.")
        selected_names = [name for i, name in enumerate(gene_names) if keep_mask is None or keep_mask[i]]
        if len({name.upper() for name in selected_names}) != len(selected_names):
            raise IngestionValidationError("Selected reference feature symbols collide; supply a curated unique mapping.")
        obs = handle["obs"]
        index_key = obs.attrs.get("_index", "_index")
        if isinstance(index_key, bytes):
            index_key = index_key.decode()
        if index_key not in obs:
            raise IngestionValidationError("Reference requires observation identifiers.")
        total = len(obs[index_key])
        shape = matrix.attrs.get("shape") if isinstance(matrix, h5py.Group) else matrix.shape
        if tuple(shape) != (total, len(gene_names)):
            raise IngestionValidationError("Selected expression layer does not match obs and its own var.")
        donors = column_values(obs, "donor_id")
        eligible = list(range(total))
        if allowed_donors is not None:
            wanted_donors = {str(value).strip() for value in allowed_donors}
            if not wanted_donors or "" in wanted_donors or not donors:
                raise IngestionValidationError("Donor selection requires nonempty donor IDs and obs/donor_id.")
            absent = wanted_donors - set(donors)
            if absent:
                raise IngestionValidationError("Requested donors absent from reference: %s" % sorted(absent))
            eligible = [i for i, donor in enumerate(donors) if donor in wanted_donors]
        label_key = next((k for k in ("cell_type", "celltype", "cell_type_ontology_term_id") if k in obs), None)
        # Read no labels from excluded donors, including before stratification.
        eligible_labels = column_values(obs, label_key, eligible) if label_key else []
        limit = len(eligible) if max_records <= 0 else min(max_records, len(eligible))
        local_rows = _stratified_rows(eligible_labels, len(eligible), limit, seed)
        rows = [eligible[i] for i in local_rows]
        labels = [eligible_labels[i] for i in local_rows] if eligible_labels else [""] * len(rows)
        cell_ids = column_values(obs, index_key, rows)
        if len(set(cell_ids)) != len(cell_ids) or any(not value.strip() for value in cell_ids):
            raise IngestionValidationError("Selected reference observation IDs must be unique and nonempty.")
        organism = str(scalar(handle, "uns/organism", ""))
        obs_organisms = column_values(obs, "organism", rows)
        declared_species = {value for value in obs_organisms if value}
        if organism:
            declared_species.add(organism)
        if len(declared_species) > 1:
            raise IngestionValidationError("Reference contains conflicting organism declarations.")
        organism = next(iter(declared_species), "")
        selected_donors = [donors[row] if donors else "" for row in rows]
        source_sha = scalar(handle, "uns/spatialmind/source_content_sha256", "")
        identity_scheme = scalar(handle, "uns/spatialmind/identity_scheme", "")
        original_ids = column_values(obs, "source_cell_id", rows) if source_sha else cell_ids
        source_rows = [int(value) for value in column_values(obs, "source_row", rows)] if source_sha and "source_row" in obs else rows
        if source_sha and identity_scheme == "source_sha256_and_original_cell_id_v1":
            from spatialmind.ingestion.identity import observation_id, verified_cache_manifest
            cache_manifest = verified_cache_manifest(path)
            if cache_manifest["source_content_sha256"] != source_sha:
                raise IngestionValidationError("Cache source provenance differs from its manifest.")
            if len(original_ids) != len(cell_ids) or cell_ids != [observation_id(source_sha, value) for value in original_ids]:
                raise IngestionValidationError("Portable cache observation identity does not match its source provenance.")
        if isinstance(matrix, h5py.Group) and matrix.attrs.get("encoding-type") not in {"csr_matrix", b"csr_matrix"}:
            raise IngestionValidationError("Streaming H5AD requires CSR or dense expression; convert CSC explicitly.")
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
                    if not np.isfinite(vals).all() or np.any(vals < 0):
                        raise IngestionValidationError("Expression must be finite and nonnegative before panel filtering.")
                    if semantics == "raw_counts" and not np.allclose(vals, np.round(vals), rtol=0, atol=1e-6):
                        raise IngestionValidationError("Declared raw counts contain fractional values.")
                    if np.any(cols < 0) or np.any(cols >= len(gene_names)) or len(set(cols)) != len(cols):
                        raise IngestionValidationError("CSR row requires unique, in-range feature indices.")
                    if keep_mask is not None:
                        # Vectorised select, then one dict over what survives.
                        in_range = cols < len(gene_names)
                        cols, vals = cols[in_range], vals[in_range]
                        selected = keep_mask[cols]
                        cols, vals = cols[selected], vals[selected]
                        genes = {
                            gene_names[c]: v
                            for c, v in zip(cols.tolist(), vals.tolist())
                            if v != 0.0
                        }
                    else:
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
                        cell_type=labels[position],
                        genes=genes,
                        raw_genes=dict(genes),
                        cell_id=cell_ids[position],
                    )
                )
        else:
            for position, row in enumerate(rows):
                values = np.asarray(matrix[row, :])
                if not np.isfinite(values).all() or np.any(values < 0):
                    raise IngestionValidationError("Expression must be finite and nonnegative before panel filtering.")
                if semantics == "raw_counts" and not np.allclose(values, np.round(values), rtol=0, atol=1e-6):
                    raise IngestionValidationError("Declared raw counts contain fractional values.")
                if keep_mask is not None:
                    columns = np.nonzero(keep_mask & (values != 0.0))[0]
                else:
                    columns = np.nonzero(values != 0.0)[0]
                genes = {
                    gene_names[i]: float(values[i])
                    for i in columns.tolist()
                    if i < len(gene_names)
                }
                records.append(
                    SpotRecord(
                        sample_id=sample,
                        x=float(position),
                        y=0.0,
                        cell_type=labels[position],
                        genes=genes,
                        raw_genes=dict(genes),
                        cell_id=cell_ids[position],
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
        "organism": organism,
        "sampling": {"total_records": total, "eligible_records": len(eligible), "scanned_records": len(rows),
                     "method": "donor_filtered_then_stratified_by_class", "seed": seed},
        "read_strategy": "h5py_subsample",
        "source_value_semantics": semantics,
        "raw_counts_available": semantics == "raw_counts",
        "raw_count_layer": matrix_path if semantics == "raw_counts" else None,
        "expression_layer": matrix_path,
        "measured_feature_names": gene_names,
        "selected_feature_names": selected_names,
        "feature_projection": "requested panel; source remains unchanged on disk" if keep_mask is not None else "all features",
        "allowed_donors": list(allowed_donors) if allowed_donors is not None else None,
        "source_content_sha256": source_sha,
        "identity_scheme": identity_scheme,
        "donor_ids": sorted(set(selected_donors) - {""}),
        "observation_provenance": {cell: {"source_cell_id": original, "donor_id": donor, "source_row": source_row, "loaded_row": row}
                                   for cell, original, donor, source_row, row in zip(cell_ids, original_ids, selected_donors, source_rows, rows)},
    })
    if any(not np.isfinite(value) or value < 0 for record in records for value in record.genes.values()):
        raise IngestionValidationError("Counts and log-normalized expression must be finite and nonnegative.")
    dataset.normalized = semantics == "log_normalized"
    dataset.processing_steps.append(
        "Read %d of %d cells through h5py from %s; excluded donor labels and other matrices were not read."
        % (len(records), total, matrix_path)
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
