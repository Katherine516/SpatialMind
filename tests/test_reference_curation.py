"""Explicit reference layers, donor isolation and non-approving curation tools."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

from spatialmind.ingestion import load_scrna, load_scrna_reference_set
from spatialmind.ingestion.loaders.scrna import read_h5ad_subsample
from spatialmind.ingestion.pipeline import IngestionValidationError
from spatialmind.ingestion.h5ad_access import column_values
from spatialmind.ingestion.reference_readiness import audit_reference_panel, SCHEMA_SOURCE
from spatialmind.ingestion.reference_splits import plan_donor_splits


class ReferenceCurationTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name, "reference.h5ad")
        self.counts = np.array([[5., 1., 3.], [4., 2., 1.], [1., 8., 2.], [1., 7., 3.]])
        self.a = ad.AnnData(sparse.csr_matrix(self.counts),
            obs=pd.DataFrame({"donor_id": pd.Categorical(["d1", "d1", "d2", "d3"]),
                              "cell_type": pd.Categorical(["A", "B", "test_label", "validation_label"])},
                             index=["c0", "c1", "c2", "c3"]),
            var=pd.DataFrame({"feature_name": ["G1", "G2", "G3"]}, index=["e1", "e2", "e3"]))
        self.a.uns["organism"] = "Homo sapiens"
        self.a.uns["schema_reference"] = SCHEMA_SOURCE
        self.a.uns["citation"] = "Collection: https://cellxgene.cziscience.com/collections/fixture"
        self.a.raw = self.a.copy()
        self.a.X = sparse.csr_matrix(np.log1p(self.counts))
        self.a.uns["log1p"] = {"base": None}
        self.a.write_h5ad(self.path)

    def load(self, **kwargs):
        return load_scrna(str(self.path), expression_layer="raw.X", expression_semantics="raw_counts", **kwargs)

    def test_raw_selection_uses_matching_raw_var(self):
        self.a = self.a[:, :2].copy()
        self.a.write_h5ad(self.path)
        data = self.load(max_records=4)
        self.assertEqual(set(data.genes), {"G1", "G2", "G3"})
        self.assertEqual(data.records[0].raw_genes, {"G1": 5., "G2": 1., "G3": 3.})
        self.assertEqual(data.metadata["expression_layer"], "raw/X")
        self.assertFalse(data.normalized)

    def test_X_can_be_chosen_without_reading_raw_values(self):
        data = load_scrna(str(self.path), expression_layer="X", expression_semantics="log_normalized")
        self.assertTrue(data.normalized)
        self.assertAlmostEqual(data.records[0].genes["G1"], np.log1p(5.))

    def test_named_layer_selection_is_explicit(self):
        self.a.layers["custom_counts"] = sparse.csr_matrix(self.counts * 2)
        self.a.write_h5ad(self.path)
        data = load_scrna(str(self.path), expression_layer="layers/custom_counts", expression_semantics="raw_counts")
        self.assertEqual(data.records[0].genes["G1"], 10.)

    def test_raw_name_alone_does_not_establish_counts(self):
        with self.assertRaises(IngestionValidationError):
            read_h5ad_subsample(str(self.path), expression_layer="raw.X")

    def test_fractional_X_cannot_be_declared_counts(self):
        with self.assertRaisesRegex(IngestionValidationError, "fractional"):
            load_scrna(str(self.path), expression_layer="X", expression_semantics="raw_counts")

    def test_missing_explicit_layer_cannot_fall_back(self):
        with self.assertRaises(IngestionValidationError):
            load_scrna(str(self.path), expression_layer="layers/absent", expression_semantics="raw_counts")

    def test_read_failure_never_bypasses_donor_or_layer_selection(self):
        with patch("spatialmind.ingestion.loaders.scrna.read_h5ad_subsample", side_effect=OSError("read failed")), \
                patch("spatialmind.ingestion.loaders.scrna.DataIngestionLayer.load_h5ad") as fallback:
            with self.assertRaisesRegex(OSError, "read failed"):
                self.load(allowed_donors=["d1"])
            fallback.assert_not_called()

    def test_directory_reference_cannot_ignore_donor_selection(self):
        from spatialmind.review.glioblastoma import _load_reference_dataset

        with patch("spatialmind.review.glioblastoma.load_xenium") as reader:
            result = _load_reference_dataset(self.root.name, max_records=4, allowed_donors=["d1"])
            self.assertIsNone(result[0])
            self.assertFalse(result[1])
            self.assertEqual(result[2], "blocked_unsupported_reference_selection")
            reader.assert_not_called()

    def test_uns_species_survives_streaming(self):
        self.a.uns["organism"] = "Mus musculus"
        self.a.write_h5ad(self.path)
        self.assertEqual(self.load().metadata["organism"], "Mus musculus")

    def test_donor_filter_precedes_label_reads_and_sampling(self):
        reads = []
        def capture(group, name, rows=None):
            if name == "cell_type":
                reads.append(list(rows) if rows is not None else None)
            return column_values(group, name, rows)
        with patch("spatialmind.ingestion.h5ad_access.column_values", side_effect=capture):
            data = self.load(allowed_donors=["d1"], max_records=1)
        self.assertEqual(reads, [[0, 1]])
        self.assertEqual(data.metadata["donor_ids"], ["d1"])
        self.assertEqual(len(data.records), 1)
        self.assertNotIn(data.records[0].cell_type, {"test_label", "validation_label"})
        self.assertEqual(data.metadata["observation_provenance"][data.records[0].cell_id]["donor_id"], "d1")

    def test_unknown_or_empty_donor_selection_refuses(self):
        for donors in ([], ["missing"], [""]):
            with self.subTest(donors=donors), self.assertRaises(IngestionValidationError):
                self.load(allowed_donors=donors)

    def test_zero_panel_overlap_never_returns_full_matrix(self):
        with self.assertRaisesRegex(IngestionValidationError, "no overlap"):
            self.load(keep_features=["missing"])

    def test_small_file_projection_uses_same_streaming_path(self):
        data = self.load(keep_features=["G1"], allowed_donors=["d1"])
        self.assertEqual(data.genes, ["G1"])
        self.assertEqual(data.metadata["read_strategy"], "h5py_subsample")

    def test_selected_duplicate_symbols_are_refused(self):
        self.a.raw = None
        self.a.X = sparse.csr_matrix(self.counts)
        self.a.var["feature_name"] = ["G1", "g1", "G3"]
        self.a.write_h5ad(self.path)
        with self.assertRaisesRegex(IngestionValidationError, "collide"):
            load_scrna(str(self.path), expression_layer="X", expression_semantics="raw_counts", keep_features=["G1"])
        data = load_scrna(str(self.path), expression_layer="X", expression_semantics="raw_counts", keep_features=["G3"])
        self.assertEqual(data.genes, ["G3"])

    def test_reference_set_namespaces_ids_and_preserves_origins(self):
        other = Path(self.root.name, "second.h5ad")
        self.a.uns["version"] = "distinct synthetic source"
        self.a.write_h5ad(other)
        data = load_scrna_reference_set([str(self.path), str(other)], expression_layer="raw.X",
                                       expression_semantics="raw_counts", allowed_donors=["d1"])
        self.assertEqual(len({r.cell_id for r in data.records}), 4)
        self.assertEqual({v["source_cell_id"] for v in data.metadata["observation_provenance"].values()}, {"c0", "c1"})
        self.assertEqual(data.metadata["donor_ids"], ["d1"])

    def test_same_file_cannot_be_combined_twice(self):
        with self.assertRaisesRegex(IngestionValidationError, "more than once"):
            load_scrna_reference_set([str(self.path), str(self.path)])

    def test_profile_retains_pending_status_and_detects_overlap(self):
        other = Path(self.root.name, "second.h5ad")
        self.a.write_h5ad(other)
        audit = audit_reference_panel([str(self.path), str(other)])
        self.assertFalse(audit["training_ready"])
        self.assertEqual(len(audit["donor_overlap_pairs"]), 1)
        reference = audit["references"][0]
        self.assertEqual(reference["candidate_layer"], "raw/X")
        self.assertEqual(reference["donor_counts"], {"d1": 2, "d2": 1, "d3": 1})
        self.assertFalse(reference["training_ready"])

    def test_mouse_reference_fails_human_eligibility(self):
        self.a.uns["organism"] = "Mus musculus"
        self.a.write_h5ad(self.path)
        audit = audit_reference_panel([str(self.path)])
        self.assertFalse(audit["references"][0]["species_matches_target"])
        with self.assertRaises(ValueError):
            plan_donor_splits(audit, "https://cellxgene.cziscience.com/collections/fixture")

    def test_donor_plan_is_disjoint_and_never_approved(self):
        audit = audit_reference_panel([str(self.path)])
        plan = plan_donor_splits(audit, "https://cellxgene.cziscience.com/collections/fixture")
        sets = [set(donors) for donors in plan["donors_by_role"].values()]
        self.assertEqual(sum(map(len, sets)), len(set.union(*sets)))
        self.assertFalse(plan["approved"])
        self.assertFalse(plan["external_test"])
        self.assertFalse(plan["test_scored"])
        self.assertEqual(plan, plan_donor_splits(audit, plan["collection"]))


if __name__ == "__main__":
    unittest.main()
