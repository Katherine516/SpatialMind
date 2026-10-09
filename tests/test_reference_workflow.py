"""Synthetic correctness fixtures only, never real biological validation."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import anndata as ad
import h5py
import numpy as np
import pandas as pd
from scipy import sparse

from spatialmind.ingestion import load_scrna, load_scrna_reference_set
from spatialmind.ingestion.reference_readiness import audit_reference_panel, SCHEMA_SOURCE
from spatialmind.storage.reference_matrix import export_reference_matrix, verify_reference_cache
from spatialmind.ingestion.identity import file_sha256, observation_id
from spatialmind.review.reference_curation import prepare_reference_review, validate_reference_review
from spatialmind.review.development_protocol import prepare_protocol, validate_protocol


class ReferenceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.h5ad"
        self.values = np.array([[1., 0., 2.], [3., 4., 0.], [0., 5., 6.], [1., 1., 2.]])
        self.data = ad.AnnData(sparse.csr_matrix(self.values),
            obs=pd.DataFrame({"donor_id": ["a", "a", "b", "c"], "cell_type": ["astrocyte", "malignant cell", "astrocyte", "astrocyte"]},
                             index=["c0", "c1", "c2", "c3"]),
            var=pd.DataFrame({"feature_name": ["G1", "G2", "G3"]}, index=["e1", "e2", "e3"]))
        self.data.uns.update(organism="Homo sapiens", schema_reference=SCHEMA_SOURCE,
            citation="Collection: https://cellxgene.cziscience.com/collections/fixture Dataset: https://datasets.cellxgene.cziscience.com/fixture.h5ad")
        self.data.write_h5ad(self.source)

    def cache(self, **kwargs):
        return export_reference_matrix(self.source, self.root / "cache.h5ad", "X", "raw_counts", ["a"], **kwargs)

    def test_sparse_cache_preserves_exact_values_and_ids(self):
        result = self.cache(chunk_rows=1)
        actual = ad.read_h5ad(self.root / "cache.h5ad")
        self.assertTrue(sparse.issparse(actual.X))
        np.testing.assert_array_equal(actual.X.toarray(), self.values[:2])
        self.assertEqual(actual.obs_names.tolist(), [observation_id(file_sha256(self.source), s) for s in ["c0", "c1"]])
        self.assertEqual(actual.var_names.tolist(), ["e1", "e2", "e3"])
        self.assertEqual(result["shape"], [2, 3])
        self.assertEqual(result["max_chunk_nnz"], 2)
        self.assertFalse(result["training_ready"])

    def test_cache_relocation_does_not_change_identity(self):
        self.cache()
        moved = self.root / "moved"; moved.mkdir()
        for file in self.root.glob("cache.h5ad*"):
            shutil.copy2(file, moved / file.name)
        verify_reference_cache(moved / "cache.h5ad")
        first = load_scrna(str(self.root / "cache.h5ad"), expression_layer="X", expression_semantics="raw_counts")
        second = load_scrna(str(moved / "cache.h5ad"), expression_layer="X", expression_semantics="raw_counts")
        self.assertEqual([r.cell_id for r in first.records], [r.cell_id for r in second.records])
        self.assertEqual({p["source_cell_id"] for p in first.metadata["observation_provenance"].values()}, {"c0", "c1"})
        with self.assertRaisesRegex(ValueError, "overlap"):
            load_scrna_reference_set([str(self.root / "cache.h5ad"), str(moved / "cache.h5ad")], expression_layer="X", expression_semantics="raw_counts")

    def test_auto_cache_loading_checks_manifest(self):
        self.cache()
        data = load_scrna(str(self.root / "cache.h5ad"))
        self.assertEqual(data.metadata["identity_scheme"], "source_sha256_and_original_cell_id_v1")
        (self.root / "cache.h5ad.manifest.json").unlink()
        with self.assertRaises(OSError):
            load_scrna(str(self.root / "cache.h5ad"))

    def test_wide_cache_stays_sparse_without_dense_conversion(self):
        matrix = sparse.random(300, 10000, density=.002, random_state=0, format="csr")
        matrix.data[:] = 2
        data = ad.AnnData(matrix, obs=pd.DataFrame({"donor_id": ["a"] * 300}, index=[str(i) for i in range(300)]))
        data.uns["organism"] = "Homo sapiens"
        data.write_h5ad(self.source)
        with patch.object(sparse.csr_matrix, "toarray", side_effect=AssertionError("dense conversion")):
            result = self.cache(chunk_rows=8)
        actual = ad.read_h5ad(self.root / "cache.h5ad")
        self.assertEqual((actual.X - matrix).nnz, 0)
        self.assertLess(result["max_chunk_nnz"], result["nnz"])

    def test_copied_raw_source_cannot_be_counted_twice(self):
        duplicate = self.root / "duplicate.h5ad"; shutil.copy2(self.source, duplicate)
        with self.assertRaisesRegex(ValueError, "overlap"):
            load_scrna_reference_set([str(self.source), str(duplicate)], expression_layer="X", expression_semantics="raw_counts")

    def test_projection_retains_measured_zero_feature(self):
        result = self.cache(features=["G2"], max_cells=1)
        actual = ad.read_h5ad(self.root / "cache.h5ad")
        self.assertEqual(result["shape"], [1, 1])
        self.assertEqual(result["nnz"], 0)
        self.assertEqual(actual.var["feature_name"].tolist(), ["G2"])

    def test_dense_source_and_raw_own_var_are_supported(self):
        self.data.X = self.values
        self.data.raw = self.data.copy()
        self.data = self.data[:, :1].copy()
        self.data.write_h5ad(self.source)
        export_reference_matrix(self.source, self.root / "raw.h5ad", "raw.X", "raw_counts", ["a"], chunk_rows=1)
        np.testing.assert_array_equal(ad.read_h5ad(self.root / "raw.h5ad").X.toarray(), self.values[:2])

    def test_invalid_data_outside_panel_still_refuses(self):
        for value in (-1, np.nan, .5):
            with self.subTest(value=value):
                self.data.X = sparse.csr_matrix(self.values)
                self.data.X[0, 0] = value
                self.data.write_h5ad(self.source)
                with self.assertRaises(ValueError):
                    self.cache(features=["G2"])
                self.assertFalse((self.root / "cache.h5ad").exists())

    def test_missing_donors_empty_projection_and_overwrite_refuse(self):
        with self.assertRaises(ValueError):
            export_reference_matrix(self.source, self.root / "cache.h5ad", "X", "raw_counts", ["absent"])
        with self.assertRaises(ValueError):
            self.cache(features=["absent"])
        self.cache()
        with self.assertRaises(ValueError):
            self.cache()

    def test_tampered_cache_and_forged_cell_identity_refuse(self):
        self.cache()
        with h5py.File(self.root / "cache.h5ad", "r+") as f:
            f["obs/_index"][0] = "forged"
        with self.assertRaises(ValueError):
            verify_reference_cache(self.root / "cache.h5ad")
        with self.assertRaises(ValueError):
            load_scrna(str(self.root / "cache.h5ad"), expression_layer="X", expression_semantics="raw_counts")

    def review_packet(self):
        audit = self.root / "audit.json"
        audit.write_text(json.dumps(audit_reference_panel([str(self.source)])))
        folder = self.root / "references"
        prepare_reference_review(audit, folder)
        return folder

    def reviewed(self, folder):
        path = folder / "reference_decisions.json"
        rows = json.loads(path.read_text())
        approved = dict(review_status="reviewed", reviewer_id="synthetic-reviewer", reviewed_at="2026-10-03",
                        evidence_ref="synthetic fixture only", confidence=.9)
        for row in rows["references"]:
            row.update(approved, assay="scRNA", label_provenance="fixture", gene_mapping_policy="fixture", license_evidence="fixture")
        for row in rows["label_crosswalk"]:
            row.update(approved, target_label=row["source_label"], ontology_exception_reason="synthetic fixture only",
                       malignant_state="malignant" if row["source_label"] == "malignant cell" else "nonmalignant",
                       state_evidence="synthetic fixture only", use_for_training=True)
        for row, role in zip(rows["donors"], ["train", "validation", "internal_test"]):
            row.update(approved, canonical_donor_id=row["source_donor_id"], identity_evidence="fixture", development_role=role)
        rows["donor_alias_review"].update(approved, method_and_scope="synthetic fixture only")
        path.write_text(json.dumps(rows))
        return rows

    def test_pending_review_never_becomes_ready(self):
        folder = self.review_packet()
        report = validate_reference_review(folder)
        self.assertEqual(report["status"], "blocked_reference_curation")
        self.assertEqual(report["label_mappings"], 2)
        self.assertFalse(report["biological_validation"])

    def test_complete_synthetic_recorded_evidence_passes_not_biology(self):
        folder = self.review_packet(); self.reviewed(folder)
        self.assertEqual(validate_reference_review(folder)["status"], "recorded_curation_complete")

    def test_alias_overlap_malignancy_and_removed_mapping_refuse(self):
        folder = self.review_packet()
        for change in ("alias", "state", "membership"):
            with self.subTest(change=change):
                rows = self.reviewed(folder)
                if change == "alias":
                    rows["donors"][1]["canonical_donor_id"] = rows["donors"][0]["canonical_donor_id"]
                elif change == "state":
                    next(r for r in rows["label_crosswalk"] if r["source_label"] == "malignant cell")["malignant_state"] = "nonmalignant"
                else:
                    rows["label_crosswalk"].pop()
                (folder / "reference_decisions.json").write_text(json.dumps(rows))
                self.assertTrue(validate_reference_review(folder)["blockers"])

    def protocol(self):
        folder = self.review_packet(); self.reviewed(folder)
        packet = self.root / "brain"; packet.mkdir()
        (packet / "handoff_manifest.json").write_text(json.dumps({"datasets": {"brain": {}}}))
        path = self.root / "protocol.json"
        plan = prepare_protocol(packet, folder, path)
        approved = dict(review_status="approved", reviewer_id="synthetic-reviewer", reviewed_at="2026-10-03",
                        evidence_ref="synthetic fixture only", confidence=.9)
        plan.update(approved, status="approved_before_selection", threshold_rationale="synthetic fixture only",
                    minimum_validation_macro_f1=.5, minimum_validation_coverage=.5,
                    reference_decision_sha256=file_sha256(folder / "reference_decisions.json"),
                    reference_snapshot_sha256=file_sha256(folder / "source_snapshot.json"))
        plan["development_donors"]["brain"].update(approved, donor_id="synthetic-brain")
        path.write_text(json.dumps(plan))
        return path, packet, plan

    def test_protocol_requires_review_hashes_and_prespecified_thresholds(self):
        path, packet, plan = self.protocol()
        self.assertEqual(validate_protocol(path, packet)["candidate_neighbors"], [5, 15])
        for field, bad in [("minimum_validation_macro_f1", None), ("confidence_threshold", float("nan")),
                           ("candidate_neighbors", [True]), ("reference_decision_sha256", "changed"),
                           ("status", "draft_not_approved")]:
            with self.subTest(field=field):
                mutated = dict(plan); mutated[field] = bad
                path.write_text(json.dumps(mutated))
                with self.assertRaises(ValueError):
                    validate_protocol(path, packet)

    def test_missing_protocol_blocks_before_any_model_fit(self):
        from spatialmind.review.brain_validation import select_brain_annotation
        from test_reviewed_validation import ReviewedValidationTests
        helper = ReviewedValidationTests()
        packet, staging, _ = helper.packet(self.root)
        with patch("spatialmind.review.brain_validation.load_xenium") as loader:
            with self.assertRaisesRegex(ValueError, "protocol"):
                select_brain_annotation(packet, staging, self.root / "model")
            loader.assert_not_called()
        self.assertFalse((self.root / "model").exists())


if __name__ == "__main__":
    unittest.main()
