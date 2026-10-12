"""Reproduce cross-modality boundary gaps without changing scientific inputs.

This is an audit, not a biological benchmark. Synthetic fixtures only establish
software behavior; corrected boundaries should pass without biological claims.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def evaluate(root):
    import anndata as ad
    import numpy as np
    from spatialmind.agent.runtime import execute_tool_step
    from spatialmind.contracts import ToolCallSpec
    from spatialmind.ingestion import DataIngestionLayer
    from spatialmind.ingestion.contract import to_cell_by_feature_contract
    from spatialmind.schemas import SpatialDataset, SpotRecord, expression_feature_names
    from spatialmind.storage.replay import verify_run_record
    from spatialmind.tools import build_default_registry
    from spatialmind.tools.fusion.fuser import ModalityFuser

    layer = DataIngestionLayer()
    registry = build_default_registry()
    checks = []

    def record(name, expected, observed, passed):
        checks.append({"name": name, "expected": expected, "observed": observed,
                       "status": "pass" if passed else "finding"})

    # An index is a valid placeholder for reference transfer, never tissue space.
    indexed = SpatialDataset(
        "nonspatial", [SpotRecord("nonspatial", float(i), 0., "A" if i < 20 else "B",
                                  {"G1": float(i % 5), "G2": float(i % 7)}, cell_id=str(i))
                       for i in range(40)], str(root / "nonspatial.h5ad"),
        modality="scrna", coordinate_system="embedding_or_index", normalized=True,
    )
    unmet = registry.check_preconditions("spatial_variable_genes", indexed)
    record("nonspatial_coordinate_precondition", "Reject index-only coordinates", unmet, bool(unmet))
    try:
        result = execute_tool_step(indexed, ToolCallSpec("spatial_variable_genes", {
            "n_top": 2, "n_neighs": 3, "n_perms": 19, "random_state": 0,
        }), registry)
        observed = {"tool": result.tool_name, "engine": result.metrics.get("engine"),
                    "summary": result.summary, "caveats": result.caveats}
        record("nonspatial_runtime", "Reject spatial analysis of index coordinates", observed, False)
    except Exception as exc:
        record("nonspatial_runtime", "Reject spatial analysis of index coordinates",
               {"exception": type(exc).__name__, "message": str(exc)}, bool(unmet))

    values = np.tile(np.arange(1, 302, dtype=np.float32), (4, 1))
    matrix = ad.AnnData(values)
    matrix.var_names = ["G%d" % i for i in range(301)]
    matrix.obsm["spatial"] = np.array([[0., 0.], [1., 1.], [2., 0.], [3., 1.]])
    matrix.uns["spatialmind"] = {"expression_semantics": "raw_counts"}
    path = root / "whole_transcriptome.h5ad"
    matrix.write_h5ad(path)
    default = layer.load_h5ad(str(path))
    complete = layer.load_h5ad(str(path), max_features_per_record=0)
    record("h5ad_default_feature_preservation", "Preserve 301 input genes before scientific feature selection", {
        "input_features": 301, "default_features": len(default.genes),
        "explicit_unlimited_features": len(complete.genes),
        "input_row_sum": float(values[0].sum()),
        "default_source_row_sum": sum(default.records[0].raw_genes.values()),
        "complete_source_row_sum": sum(complete.records[0].raw_genes.values()),
        "default_normalized_G300": default.records[0].genes["G300"],
        "complete_normalized_G300": complete.records[0].genes["G300"],
    }, len(default.genes) == 301)

    protein_path = root / "codex_intensities.csv"
    with protein_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sample_id", "x", "y", "cell_type", "CD3", "CD20"])
        writer.writeheader()
        for i in range(4):
            writer.writerow({"sample_id": "protein", "x": i, "y": i % 2,
                             "cell_type": "Unannotated", "CD3": 100, "CD20": 200})
    protein = layer.load_csv(str(protein_path), data_type="multiplex_imaging_csv")
    record("protein_preprocessing", "Require explicit intensity semantics; do not silently apply RNA normalization", {
        "modality": protein.modality, "source": protein.records[0].raw_genes,
        "analysis": protein.records[0].genes, "steps": protein.processing_steps,
    }, protein.records[0].genes == protein.records[0].raw_genes)
    contract = to_cell_by_feature_contract(protein)
    record("protein_contract", "Preserve proteomics modality", {
        "modality": contract.modality, "assay_subtype": contract.assay_subtype,
        "feature_type": contract.feature_type,
    }, contract.modality == "proteomics")

    thin = SpatialDataset("thin", [SpotRecord("thin", 0., 0., "", {
        "G1": 1., "NegControlProbe_1": 20., "TOTAL_COUNTS": 21.,
    })], "fixture")
    genes = expression_feature_names(thin)
    record("one_gene_control_exclusion", "Only G1, or reject insufficient expression features", genes, genes == ["G1"])

    artifact = root / "artifact.txt"
    artifact.write_text("audit artifact", encoding="utf-8")
    record_path = root / "run.json"
    record_path.write_text(json.dumps({
        "run_id": "audit", "input_file_md5": {},
        "table_md5": {str(artifact): hashlib.md5(artifact.read_bytes()).hexdigest()},
        "artifact_md5": {"unresolvable_artifact": "0" * 32}, "artifact_paths": {},
    }), encoding="utf-8")
    verification = verify_run_record(str(record_path))
    record("incomplete_replay_verification", "Do not report fully verified when an artifact hash has no path", {
        "status": verification.status, "warnings": verification.warnings,
        "checks": len(verification.checks),
    }, verification.status != "verified")

    second = SpatialDataset("other", [SpotRecord("other", 100., 100., "", {"G1": 2.})], "other")
    fused = ModalityFuser().fuse([("scrna", indexed), ("visium", second)])
    record("unimplemented_fusion_metrics", "No measured alignment/shared-cell score before alignment", {
        "shared_cells_n": fused.shared_cells_n, "fusion_quality_score": fused.fusion_quality_score,
        "fusion_method": fused.fusion_method, "warnings": fused.warnings,
    }, fused.fusion_quality_score is None and fused.shared_cells_n is None)

    scaffold_names = [tool.name for tool in registry.list_all() if tool.capability == "unavailable"]
    selectable = {tool.name for tool in registry.list_plannable()}
    record("scaffold_planning_exclusion", "No unavailable tool is plannable", {
        "registered": len(registry.list_all()), "plannable": len(selectable),
        "unavailable": len(scaffold_names), "leaked": sorted(selectable.intersection(scaffold_names)),
    }, not selectable.intersection(scaffold_names))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="spatialmind_modality_audit_") as directory:
        checks = evaluate(Path(directory))
    payload = {
        "scope": "Synthetic boundary audit; not annotation accuracy or biological validation",
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "seconds": round(time.monotonic() - started, 3), "checks": checks,
        "findings": sum(row["status"] == "finding" for row in checks),
        "passes": sum(row["status"] == "pass" for row in checks),
    }
    (out / "modality_boundary_audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 1 if payload["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
