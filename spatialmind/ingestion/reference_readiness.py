"""Bounded metadata inspection for reference curation, never automatic approval."""

from pathlib import Path
from typing import Any, Dict, Iterable
from collections import Counter
from itertools import combinations
import re

from .h5ad_access import scalar, column_values

SCHEMA_SOURCE = "https://github.com/chanzuckerberg/single-cell-curation/blob/main/schema/7.1.0/schema.md"


def _matrix_profile(node, max_values=4096):
    """Sample bounded stored values across rows, never infer semantics from them."""
    import h5py
    import numpy as np

    shape = tuple(node.shape) if isinstance(node, h5py.Dataset) else tuple(node.attrs["shape"])
    encoding = str(node.attrs.get("encoding-type", "dense"))
    values = []
    if len(shape) != 2 or min(shape) == 0:
        return {"shape": list(shape), "sampled_values": 0, "status": "empty"}
    rows = np.unique(np.linspace(0, shape[0] - 1, min(64, shape[0]), dtype=int))
    for row in rows:
        budget = min(64, max_values - len(values))
        if budget <= 0:
            break
        if isinstance(node, h5py.Group):
            if node.attrs.get("encoding-type") not in {"csr_matrix", b"csr_matrix"}:
                return {"shape": list(shape), "status": "unsupported_encoding", "encoding": encoding}
            start, end = map(int, node["indptr"][row:row + 2])
            values.extend(node["data"][start:min(end, start + budget)].tolist())
        else:
            values.extend(node[row, :min(shape[1], budget)].tolist())
    array = np.asarray(values, dtype=float)
    finite = np.isfinite(array)
    valid = array[finite]
    return {"shape": list(map(int, shape)), "encoding": encoding, "sampled_values": len(values),
            "nonfinite_values": int((~finite).sum()), "negative_values": int((valid < 0).sum()),
            "integer_like_fraction": float(np.mean(np.isclose(valid, np.round(valid), rtol=0, atol=1e-6))) if valid.size else None,
            "sample_min": float(valid.min()) if valid.size else None,
            "sample_max": float(valid.max()) if valid.size else None,
            "scope": "At most 64 stored values from each of 64 evenly spaced rows; not a complete validation"}


def profile_reference(path: str, target_species="Homo sapiens") -> Dict[str, Any]:
    """Source metadata, donor counts and bounded layer evidence for human curation."""
    import h5py
    from .loaders.scrna import _h5_gene_names

    result = inspect_reference(path)
    with h5py.File(path, "r") as handle:
        citation = str(scalar(handle, "uns/citation", ""))
        urls = re.findall(r"https?://[^\s]+", citation)
        collection = next((url for url in urls if "/collections/" in url), "")
        version = next((url for url in urls if "datasets.cellxgene.cziscience.com/" in url), "")
        species = str(scalar(handle, "uns/organism", ""))
        obs_species = set(column_values(handle["obs"], "organism")) - {""}
        if not species and len(obs_species) == 1:
            species = next(iter(obs_species))
        donors = Counter(column_values(handle["obs"], "donor_id"))
        labels = Counter(column_values(handle["obs"], "cell_type"))
        matrices = {}
        for key in ["X"] + (["raw/X"] if "raw/X" in handle else []) + ["layers/" + k for k in handle.get("layers", {})]:
            matrices[key] = _matrix_profile(handle[key])
            var = handle["raw/var"] if key == "raw/X" else handle["var"]
            symbols = _h5_gene_names(var)
            matrices[key]["duplicate_casefolded_symbols"] = len(symbols) - len({s.upper() for s in symbols})
        schema = str(scalar(handle, "uns/schema_reference", ""))
        candidate = "raw/X" if "raw/X" in handle else "X"
        profile = matrices[candidate]
        supported = schema == SCHEMA_SOURCE and profile.get("integer_like_fraction") == 1.0 and not profile.get("negative_values") and not profile.get("nonfinite_values")
        result.update({
            "title": str(scalar(handle, "uns/title", "")), "species": species,
            "species_matches_target": bool(species) and species == target_species and not (obs_species - {species}),
            "source_citation": citation, "source_urls": urls, "collection": collection,
            "dataset_version_url": version, "schema_reference": schema,
            "matrix_profiles": matrices, "donor_counts": dict(sorted(donors.items())),
            "label_counts": dict(sorted(labels.items())),
            "disease_counts": dict(Counter(column_values(handle["obs"], "disease"))),
            "candidate_layer": candidate if supported else None,
            "candidate_semantics": "raw_counts" if supported else None,
            "candidate_basis": "Declared CELLxGENE 7.1.0 raw-layer convention plus bounded numeric consistency; curator confirmation still required" if supported else "Insufficient schema/numeric evidence",
        })
        if not result["species_matches_target"]:
            result["blockers"].append("Species mismatch or missing/conflicting species; exclude from direct human reference transfer.")
        result["required_evidence"]["source_accession_or_url"] = version or None
        result["required_evidence"]["species"] = species or None
    return result


def audit_reference_panel(paths: Iterable[str], target_species="Homo sapiens") -> Dict[str, Any]:
    references, errors = [], []
    for path in paths:
        try:
            references.append(profile_reference(path, target_species))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    overlaps = []
    for left, right in combinations(references, 2):
        shared = sorted((set(left["donor_counts"]) & set(right["donor_counts"])) - {"", "unknown", "nan"})
        if shared:
            overlaps.append({"left": left["path"], "right": right["path"], "shared_donor_ids": shared,
                             "same_collection": bool(left["collection"]) and left["collection"] == right["collection"],
                             "interpretation": "Do not split these donor IDs across training and testing; confirm aliases across studies."})
    return {"schema_version": 2, "scope": "Reference curation evidence, not approval or a benchmark",
            "target_species": target_species, "references": references, "errors": errors,
            "donor_overlap_pairs": overlaps, "training_ready": False,
            "independence_caveat": "Different donor strings or collections do not establish biological independence; a source-backed cross-study donor map is required."}


def inspect_reference(path: str) -> Dict[str, Any]:
    import h5py

    source = Path(path)
    with h5py.File(source, "r") as handle:
        matrix = handle.get("X")
        if matrix is None:
            raise ValueError("Reference has no X matrix: %s" % source)
        shape = matrix.shape if isinstance(matrix, h5py.Dataset) else matrix.attrs.get("shape")
        if shape is None or len(shape) != 2:
            raise ValueError("Reference has no recognizable matrix shape: %s" % source)
        obs = handle.get("obs")
        columns = list(obs.keys()) if obs is not None else []
        layers = list(handle["layers"].keys()) if "layers" in handle else []
        labels = [k for k in columns if k.lower() in {
            "cell_type", "celltype", "annotation", "cell_type_ontology_term_id", "subclass", "supercluster"}]
        donors = [k for k in columns if k.lower() in {"donor_id", "donor", "subject_id", "individual"}]
        count_layers = [k for k in layers if k in {"counts", "raw_counts"}]
        return {
            "path": str(source), "file_bytes": source.stat().st_size,
            "matrix_shape": [int(v) for v in shape],
            "matrix_encoding": str(matrix.attrs.get("encoding-type", "dense")),
            "candidate_label_columns": labels, "candidate_donor_columns": donors,
            "candidate_count_layers": count_layers, "has_raw_object": "raw" in handle,
            "has_log1p_metadata": "uns/log1p" in handle,
            "status": "pending_curation", "training_ready": False,
            "required_evidence": {
                "source_accession_or_url": None, "dataset_version": None,
                "species": None, "tissue_and_condition": None,
                "expression_layer": None, "expression_semantics": None,
                "expression_semantics_source": None, "gene_identifier_mapping": None,
                "label_column": None, "label_provenance": None,
                "label_ontology_crosswalk": None, "donor_column": None,
                "donor_overlap_audit": None, "development_or_sealed_test_role": None,
                "license_and_allowed_use": None, "curator_id": None,
            },
            "blockers": ["Expression layer and preprocessing require source-confirmed semantics.",
                         "Reference labels are not independent Xenium expert decisions.",
                         "Donor-disjoint development and test membership must be verified."]
                        + ([] if labels else ["No standard label column was found."])
                        + ([] if donors else ["No standard donor column was found."]),
        }


def build_reference_inventory(paths: Iterable[str]) -> Dict[str, Any]:
    records, errors = [], []
    for path in paths:
        try:
            records.append(inspect_reference(path))
        except (OSError, ValueError, TypeError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {"schema_version": 1, "scope": "Metadata only; no matrix validation, donor verification or biological approval",
            "references": records, "errors": errors,
            "training_ready": False,
            "next_action": "Curate source evidence and donor identities before choosing an expression layer or training."}
