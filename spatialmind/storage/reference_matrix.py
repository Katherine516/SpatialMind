"""Chunked CSR H5AD caches with exact source identities and bounded readback QA."""

import json
import os
import tempfile
from pathlib import Path

from spatialmind.ingestion.identity import file_sha256, observation_id, verified_cache_manifest
from spatialmind.ingestion.h5ad_access import select_matrix, column_values, scalar


def export_reference_matrix(source, output, expression_layer, expression_semantics,
                            allowed_donors, features=None, max_cells=None, chunk_rows=128):
    """Export selected source rows without SpotRecord dictionaries or dense atlas copies.

    This cache does not approve reference labels. Sampling takes the first eligible
    rows, without consulting labels; it is a technical check, not class balancing.
    """
    import anndata as ad
    import h5py
    import numpy as np
    import pandas as pd
    from scipy import sparse
    from spatialmind.ingestion.loaders.scrna import _h5_gene_names

    source, output = Path(source), Path(output)
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    if output.exists() or manifest_path.exists():
        raise ValueError("Cache output or manifest exists; use a new path.")
    if chunk_rows < 1 or (max_cells is not None and max_cells < 1):
        raise ValueError("Chunk size and optional cell limit must be positive.")
    donors_wanted = set(allowed_donors)
    if not donors_wanted or any(not str(d).strip() for d in donors_wanted):
        raise ValueError("Explicit nonempty development donor IDs are required.")
    before = source.stat()
    source_sha = file_sha256(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=".h5ad", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with h5py.File(source, "r") as handle:
            matrix, var, layer, semantics = select_matrix(handle, expression_layer, expression_semantics)
            if scalar(handle, "uns/spatialmind/source_content_sha256"):
                raise ValueError("Export from the original source, not an already derived reference cache.")
            symbols = _h5_gene_names(var)
            index_key = var.attrs.get("_index", "_index")
            if isinstance(index_key, bytes):
                index_key = index_key.decode()
            feature_ids = column_values(var, index_key)
            if len(feature_ids) != len(symbols) or len(set(feature_ids)) != len(feature_ids):
                raise ValueError("Source features require unique stable IDs.")
            wanted = None if features is None else {str(f).upper() for f in features}
            cols = np.asarray([i for i, s in enumerate(symbols) if wanted is None or s.upper() in wanted], dtype=int)
            if not len(cols):
                raise ValueError("No measured features overlap the requested panel.")
            # Retain unique feature IDs even when symbols collide in a whole atlas.
            # Downstream symbol-based transfer must still reject ambiguous symbols.
            obs = handle["obs"]
            donors = column_values(obs, "donor_id")
            if not donors_wanted <= set(donors):
                raise ValueError("Requested donors are absent or donor metadata is missing.")
            rows = [i for i, d in enumerate(donors) if d in donors_wanted]
            if max_cells is not None:
                rows = rows[:max_cells]
            key = obs.attrs.get("_index", "_index")
            if isinstance(key, bytes):
                key = key.decode()
            ids = column_values(obs, key, rows)
            if len(ids) != len(rows) or len(set(ids)) != len(ids) or any(not s.strip() for s in ids):
                raise ValueError("Selected source cell IDs must be unique and nonempty.")
            shape = tuple(matrix.attrs["shape"]) if isinstance(matrix, h5py.Group) else matrix.shape
            if shape != (len(donors), len(symbols)):
                raise ValueError("Matrix shape does not match donor and feature metadata.")
            if isinstance(matrix, h5py.Group) and matrix.attrs.get("encoding-type") not in {"csr_matrix", b"csr_matrix"}:
                raise ValueError("Only CSR or dense sources are supported; CSC requires explicit conversion.")
            species = str(scalar(handle, "uns/organism", ""))
            declarations = set(column_values(obs, "organism", rows)) - {""}
            if species:
                declarations.add(species)
            if len(declarations) != 1:
                raise ValueError("Unambiguous source organism is required.")
            species = declarations.pop()
            stable = [observation_id(source_sha, s) for s in ids]
            frame = pd.DataFrame({"source_cell_id": ids, "source_row": rows,
                                  "donor_id": [donors[i] for i in rows]}, index=stable)
            for column in ("cell_type", "cell_type_ontology_term_id", "disease"):
                values = column_values(obs, column, rows)
                if values:
                    frame[column] = values
            variables = pd.DataFrame({"feature_name": [symbols[i] for i in cols]},
                                     index=[feature_ids[i] for i in cols])
            stub = ad.AnnData(sparse.csr_matrix((len(rows), len(cols)), dtype=np.float64), obs=frame, var=variables)
            stub.uns["organism"] = species
            stub.uns["spatialmind"] = {"expression_semantics": semantics,
                "source_content_sha256": source_sha, "source_expression_layer": layer,
                "identity_scheme": "source_sha256_and_original_cell_id_v1", "curation_status": "unapproved_cache"}
            stub.write_h5ad(temporary)
            del stub
            total_nnz, value_sum, max_nnz = 0, 0.0, 0
            with h5py.File(temporary, "r+") as target:
                x = target["X"]
                del x["data"], x["indices"], x["indptr"]
                x.create_dataset("indptr", (len(rows) + 1,), dtype="i8")
                values_out = x.create_dataset("data", (0,), maxshape=(None,), dtype="f8", chunks=True, compression="gzip")
                indices_out = x.create_dataset("indices", (0,), maxshape=(None,), dtype="i8", chunks=True, compression="gzip")
                for begin in range(0, len(rows), chunk_rows):
                    parts = []
                    for row in rows[begin:begin + chunk_rows]:
                        if isinstance(matrix, h5py.Group):
                            left, right = map(int, matrix["indptr"][row:row + 2])
                            if left < 0 or right < left or right > len(matrix["data"]) or right > len(matrix["indices"]):
                                raise ValueError("Invalid CSR row pointers.")
                            values, indices = matrix["data"][left:right], matrix["indices"][left:right]
                            if np.any(indices < 0) or np.any(indices >= shape[1]) or len(set(indices)) != len(indices):
                                raise ValueError("Invalid or duplicate CSR feature indices.")
                            block = sparse.csr_matrix((values, indices, [0, len(values)]), shape=(1, shape[1]))
                        else:
                            block = sparse.csr_matrix(matrix[row:row + 1, :])
                        vals = block.data
                        if not np.isfinite(vals).all() or np.any(vals < 0):
                            raise ValueError("Expression must be finite and nonnegative before projection.")
                        if semantics == "raw_counts" and not np.allclose(vals, np.round(vals), rtol=0, atol=1e-6):
                            raise ValueError("Declared counts contain fractional values.")
                        # Reject integers that cannot be represented exactly in the cache dtype.
                        if np.any(vals > 2 ** 53):
                            raise ValueError("Values exceed exact float64 count representation.")
                        parts.append(block[:, cols].astype(np.float64))
                    batch = sparse.vstack(parts, format="csr")
                    batch.eliminate_zeros()
                    batch.sort_indices()
                    end = total_nnz + batch.nnz
                    values_out.resize((end,)); indices_out.resize((end,))
                    values_out[total_nnz:end], indices_out[total_nnz:end] = batch.data, batch.indices
                    x["indptr"][begin:begin + batch.shape[0] + 1] = batch.indptr + total_nnz
                    # Exact bounded readback parity; no full matrix is materialised.
                    if (not np.array_equal(values_out[total_nnz:end], batch.data)
                            or not np.array_equal(indices_out[total_nnz:end], batch.indices)
                            or not np.array_equal(x["indptr"][begin:begin + batch.shape[0] + 1], batch.indptr + total_nnz)):
                        raise ValueError("Cache readback differs from selected source values.")
                    total_nnz = end
                    value_sum += float(batch.sum())
                    max_nnz = max(max_nnz, batch.nnz)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("Source changed during hashing/export.")
        manifest = {"schema_version": 1, "status": "technical_cache_verified_not_curated",
            "source_content_sha256": source_sha, "source_locator": str(source.resolve()),
            "expression_layer": layer, "expression_semantics": semantics, "species": species,
            "identity_scheme": "source_sha256_and_original_cell_id_v1", "cache_file": output.name,
            "cache_sha256": file_sha256(temporary), "shape": [len(rows), len(cols)], "nnz": total_nnz,
            "selected_value_sum": value_sum, "readback_parity": "exact_selected_values_indices_and_row_pointers",
            "allowed_donors": sorted(donors_wanted), "selected_donors": sorted(set(frame["donor_id"])),
            "sampling": "first eligible source rows; no label-based selection", "chunk_rows": chunk_rows,
            "max_chunk_nnz": max_nnz, "training_ready": False,
            "limits": "Source/observation identity is byte-version bound, not cross-study biological identity. Metadata is O(cells + features); matrix working memory is chunk bounded."}
        # Hard-link publication is exclusive and never overwrites another writer.
        os.link(temporary, output)
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, allow_nan=False)
        return manifest
    finally:
        temporary.unlink(missing_ok=True)


def verify_reference_cache(path):
    """Verify a relocated cache against its adjacent content manifest."""
    return verified_cache_manifest(path)
