"""Scientific boundary regressions from the October 3 evaluation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import anndata as ad
import numpy as np
from scipy import sparse

from spatialmind.ingestion import DataIngestionLayer
from spatialmind.ingestion.contract import to_cell_by_feature_contract
from spatialmind.ingestion.pipeline import IngestionValidationError
from spatialmind.contracts import ContractViolationError
from spatialmind.schemas import SpatialDataset, SpotRecord, expression_feature_names
from spatialmind.tools import build_default_registry
from spatialmind.tools.exceptions import DataModalityError, MissingPreconditionError
from spatialmind.tools.implementations import (
    _dataset_to_anndata, _expression_qc_metrics, _screen_spatial_genes,
    clear_anndata_cache, spatial_variable_genes,
)
from spatialmind.viz.tables import _gene_rows


def fixture(n_cells=40, n_genes=60):
    rng = np.random.default_rng(31)
    return SpatialDataset("fixture", [
        SpotRecord("fixture", float(i % 8), float(i // 8), "A",
                   {"G%d" % j: float(v) for j, v in enumerate(rng.poisson(3, n_genes))},
                   cell_id=str(i)) for i in range(n_cells)
    ], "fixture", normalized=True)


class ModalityBoundaryTests(unittest.TestCase):
    def tearDown(self):
        clear_anndata_cache()

    def test_all_original_boundary_reproductions_pass(self):
        from scripts.audit_modality_boundaries import evaluate
        with tempfile.TemporaryDirectory() as root:
            checks = evaluate(Path(root))
        self.assertEqual(len(checks), 9)
        self.assertEqual([c["name"] for c in checks if c["status"] != "pass"], [])

    def test_direct_spatial_execution_rejects_index_coordinates(self):
        data = fixture()
        data.coordinate_system = "embedding_or_index"
        with self.assertRaises(MissingPreconditionError):
            build_default_registry().get("spatial_variable_genes").run(data, {})
        with self.assertRaises(MissingPreconditionError):
            spatial_variable_genes(data, {})
        self.assertNotIn("spatial", _dataset_to_anndata(data).obsm)

    def test_coordinate_change_invalidates_cached_anndata(self):
        data = fixture()
        self.assertIn("spatial", _dataset_to_anndata(data).obsm)
        data.coordinate_system = "embedding_or_index"
        self.assertNotIn("spatial", _dataset_to_anndata(data).obsm)

    def test_protein_cannot_enter_rna_tool(self):
        data = fixture()
        data.modality = "protein_imaging"
        with self.assertRaises(DataModalityError):
            build_default_registry().get("qc_and_cluster").run(data, {})

    def test_unknown_assay_does_not_default_to_rna(self):
        data = fixture()
        data.modality = "unknown_assay"
        with self.assertRaises(ContractViolationError):
            to_cell_by_feature_contract(data)

    def test_generic_spatial_table_does_not_become_xenium(self):
        contract = to_cell_by_feature_contract(fixture())
        self.assertEqual(contract.assay_subtype, "spatial_rna")
        self.assertFalse(contract.is_targeted_panel)
        self.assertEqual(contract.species, "unknown")

    def test_empty_biological_features_never_reintroduce_controls(self):
        data = fixture(1, 0)
        data.records[0].genes = {"NegControlProbe_1": 5., "TOTAL_COUNTS": 10.}
        self.assertEqual(expression_feature_names(data), [])
        with self.assertRaises(MissingPreconditionError):
            _dataset_to_anndata(data)

    def test_h5ad_rejects_requested_per_cell_cap(self):
        with self.assertRaises(IngestionValidationError):
            DataIngestionLayer().load_h5ad("not_read.h5ad", max_features_per_record=200)

    def test_h5ad_missing_spatial_positions_remain_nonspatial(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "reference.h5ad")
            a = ad.AnnData(sparse.csr_matrix([[1., 0.], [0., 2.]]))
            a.var_names = ["G1", "G2"]
            a.uns["spatialmind"] = {"expression_semantics": "raw_counts"}
            a.write_h5ad(path)
            data = DataIngestionLayer().load_h5ad(str(path), require_spatial=False)
        self.assertEqual(data.coordinate_system, "embedding_or_index")
        self.assertNotIn("spatial", _dataset_to_anndata(data).obsm)

    def test_wide_sparse_bridge_preserves_analysis_and_source_values(self):
        data = fixture(4, 1030)
        for row in data.records:
            row.raw_genes = {gene: value * 2 for gene, value in row.genes.items()}
        a = _dataset_to_anndata(data)
        self.assertTrue(sparse.isspmatrix_csr(a.X))
        self.assertTrue(sparse.isspmatrix_csr(a.layers["source_values"]))
        genes = expression_feature_names(data)
        expected = np.array([[r.genes[g] for g in genes] for r in data.records])
        np.testing.assert_array_equal(a.X.toarray(), expected)
        np.testing.assert_array_equal(a.layers["source_values"].toarray(), expected * 2)
        with patch.object(sparse.csr_matrix, "toarray", side_effect=AssertionError("QC must not densify")):
            qc = _expression_qc_metrics(a)
        self.assertEqual(qc["median_total_counts"], float(np.median((expected * 2).sum(axis=1))))

    def test_reference_inventory_does_not_infer_approval_from_counts_layer(self):
        from spatialmind.ingestion.reference_readiness import inspect_reference
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "reference.h5ad")
            a = ad.AnnData(sparse.csr_matrix([[1., 0.], [0., 2.]]))
            a.layers["counts"] = a.X.copy()
            a.obs["donor_id"] = ["d1", "d2"]
            a.obs["cell_type"] = ["A", "B"]
            a.write_h5ad(path)
            result = inspect_reference(str(path))
        self.assertEqual(result["matrix_shape"], [2, 2])
        self.assertEqual(result["candidate_count_layers"], ["counts"])
        self.assertEqual(result["candidate_donor_columns"], ["donor_id"])
        self.assertFalse(result["training_ready"])
        self.assertIsNone(result["required_evidence"]["expression_semantics"])

    def test_reference_inventory_records_unreadable_files(self):
        from spatialmind.ingestion.reference_readiness import build_reference_inventory
        result = build_reference_inventory(["/missing_reference.h5ad"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertFalse(result["training_ready"])

    def test_sparse_ingestion_does_not_densify_rows(self):
        from spatialmind.ingestion.pipeline import _matrix_row_to_features
        row = sparse.csr_matrix(([1., 2.], ([0, 0], [0, 9999])), shape=(1, 10000))
        with patch.object(sparse.csr_matrix, "toarray", side_effect=AssertionError("Do not densify")):
            features = _matrix_row_to_features(row, ["G%d" % i for i in range(10000)], 0)
        self.assertEqual(features, {"G0": 1., "G9999": 2.})


class SpatialTestingFamilyTests(unittest.TestCase):
    def test_top_n_and_legacy_screen_cap_cannot_change_test_family(self):
        a = ad.AnnData(np.ones((40, 80)))
        for n_top in (1, 10, 60):
            screen = _screen_spatial_genes(None, a, {"screen_candidates": 3}, n_top, 0)
            self.assertEqual(len(screen["tested_genes"]), 80)
            self.assertEqual(screen["report"]["method"], "detection_filter_only")

    def test_detection_filter_does_not_relax_when_empty(self):
        a = ad.AnnData(np.ones((4, 3)))
        screen = _screen_spatial_genes(None, a, {"min_detected_cells": 10}, 2, 0)
        self.assertEqual(screen["tested_genes"], [])
        self.assertEqual(len(screen["screened_out_genes"]), 3)

    def test_full_family_backend_parity_and_complete_export(self):
        import squidpy as sq
        data = fixture()
        params = {"strict_engine": True, "n_top": 3, "n_perms": 19, "n_neighs": 3, "random_state": 0}
        result = spatial_variable_genes(data, params)
        metrics = result.metrics
        self.assertEqual(len(metrics["top_genes"]), 3)
        self.assertEqual(len(metrics["all_tested_genes"]), 60)
        a = _dataset_to_anndata(data)
        sq.gr.spatial_neighbors(a, coord_type="generic", n_neighs=3)
        expected = sq.gr.spatial_autocorr(a, mode="moran", genes=list(a.var_names), n_perms=19,
            two_tailed=True, corr_method="fdr_bh", seed=0, copy=True, n_jobs=1,
            backend="threading", show_progress_bar=False)
        for row in metrics["all_tested_genes"]:
            self.assertAlmostEqual(row["pval_adj"], expected.loc[row["gene"], row["pval_adj_source"]], places=7)
        rows = list(_gene_rows({}, {"spatial_variable_genes": metrics}))
        self.assertEqual(len(rows), 60)
        self.assertTrue(all(row["tested"] == "true" for row in rows))
        from spatialmind.pilot.xenium import _descriptive_html
        report = _descriptive_html({"descriptive_analysis": {"status": "computed", "spatial_genes": metrics}})
        self.assertIn("Coordinate-independent", report)
        self.assertIn("Tested all 60 eligible genes", report)


if __name__ == "__main__":
    unittest.main()
