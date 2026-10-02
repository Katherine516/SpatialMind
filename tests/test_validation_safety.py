"""Negative and round-trip tests for the evidence boundaries found in review."""

import csv
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from spatialmind.app import review
from spatialmind.contracts.review import review_decision_issues
from spatialmind.gatekeeper import pilot_gate
from spatialmind.ingestion.labels import apply_external_label_table, apply_external_region_table
from spatialmind.methods.replication import assess_condition_replication
from spatialmind.schemas import SpatialDataset, SpotRecord


def approved(cell_id="0", **extra):
    return dict(cell_id=cell_id, expert_label="astrocyte", confidence="0.9", reviewer_id="fixture-reviewer",
                review_status="approved", reviewed_at="2026-09-30T12:00:00Z", evidence_ref="fixture:markers", **extra)


def write_rows(path, rows):
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ValidationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = SpatialDataset("fixture", [SpotRecord("fixture", i, 0, "guess", {"GFAP": 2},
                                                            cell_id=str(i)) for i in range(100)], str(self.root))

    def test_candidate_tables_cannot_open_gate(self):
        labels, regions = [], []
        for i in range(100):
            row = approved(str(i)); row.update(expert_label="astrocyte" if i < 50 else "microglial cell",
                                              review_status="candidate", reviewer_id="")
            labels.append(row)
            regions.append(dict(row, region="r1" if i < 50 else "r2", region_confidence="0.9", region_basis="user_roi"))
        write_rows(self.root / "labels.csv", labels); write_rows(self.root / "regions.csv", regions)
        lr = apply_external_label_table(self.dataset, str(self.root / "labels.csv"))
        rr = apply_external_region_table(self.dataset, str(self.root / "regions.csv"))
        assets = dict.fromkeys(["has_cell_table", "has_feature_matrix", "has_morphology", "has_boundaries"], True)
        gate = pilot_gate(self.dataset, assets, lr.to_dict(), rr.to_dict(), .7, .7, False)
        self.assertNotEqual(gate["status"], "validated_ready")
        self.assertEqual(lr.matched_cells, 0)
        self.assertEqual(lr.rejected_rows, 100)
        self.assertFalse(lr.to_dict()["labels_are_reviewed"])

    def test_canonical_existing_label_tool_is_always_gated(self):
        from spatialmind.gatekeeper import gated_tool_names
        for params in ({}, {"method": "existing_labels"}, {"group_key": "cluster"}):
            self.assertEqual(gated_tool_names(["cell_type_annotation"], {"cell_type_annotation": params}),
                             ["cell_type_annotation"])

    def test_approved_rows_apply_and_carry_evidence(self):
        write_rows(self.root / "labels.csv", [approved()])
        result = apply_external_label_table(self.dataset, str(self.root / "labels.csv"))
        self.assertEqual(result.matched_cells, 1)
        self.assertEqual(self.dataset.metadata["reviewed_cell_labels"]["0"]["evidence_ref"], "fixture:markers")

    def test_invalid_review_evidence_is_rejected(self):
        for field, value in (("confidence", "nan"), ("confidence", "2"), ("reviewed_at", "yesterday"),
                             ("evidence_ref", ""), ("reviewer_id", "unidentified (SpatialMind Studio)")):
            row = approved(); row[field] = value
            self.assertTrue(review_decision_issues(row), (field, value))

    def test_duplicate_ids_do_not_resolve_by_last_row(self):
        write_rows(self.root / "labels.csv", [approved(), approved()])
        self.assertEqual(apply_external_label_table(self.dataset, str(self.root / "labels.csv")).matched_cells, 0)

    def test_studio_preserves_extra_columns_and_versions_original(self):
        path = self.root / "expert_cell_labels.csv"
        rows = [approved("0", cl_id="CL:0000127", custom_evidence="a"),
                approved("1", cl_id="CL:0000127", custom_evidence="b")]
        write_rows(path, rows)
        before = path.read_bytes()
        review.assign(str(self.root), "labels", ["0"], "astrocyte", reviewer_id="fixture-reviewer",
                      evidence_ref="fixture:recheck")
        loaded = review.read_table(str(self.root), "labels")
        self.assertEqual({key: loaded["1"][key] for key in rows[1]}, rows[1])
        self.assertEqual(loaded["0"]["cl_id"], "CL:0000127")
        revisions = self.root / ".spatialmind_review_history" / path.stem
        self.assertEqual(next(revisions.glob("*.csv")).read_bytes(), before)
        self.assertEqual(json.loads(next(revisions.glob("*.json")).read_text())["operation"], "save")

    def test_unidentified_studio_assignments_remain_candidates(self):
        review.assign(str(self.root), "labels", ["0"], "astrocyte")
        self.assertEqual(review.coverage(str(self.root), "labels", ["0"])["coverage"], 0)
        self.assertEqual(review.read_table(str(self.root), "labels")["0"]["review_status"], "candidate")

    def test_missing_or_partial_donor_metadata_blocks_inference(self):
        for sections in ([{"section_id": "a"}, {"section_id": "b"}],
                         [{"section_id": "a", "donor_id": "d1"}, {"section_id": "b", "donor_id": "d2"},
                          {"section_id": "c"}]):
            result = assess_condition_replication({"healthy": sections, "gbm": sections})
            self.assertFalse(result["supports_condition_inference"])

    def test_h5ad_log_expression_is_not_transformed_twice(self):
        import anndata as ad
        import numpy as np
        from spatialmind.ingestion.pipeline import DataIngestionLayer
        a = ad.AnnData(X=np.log1p(np.array([[1000., 9000.], [2000., 8000.], [4000., 6000.]])))
        a.var_names = ["GFAP", "AQP4"]; a.obsm["spatial"] = np.array([[0., 0.], [1., 1.], [2., 2.]])
        a.uns["log1p"] = {"base": None}
        path = self.root / "normalized.h5ad"; a.write_h5ad(path)
        result = DataIngestionLayer().load_h5ad(str(path), backed=False)
        np.testing.assert_allclose([result.records[0].genes[g] for g in a.var_names], a.X[0])
        self.assertEqual(result.metadata["source_value_semantics"], "log_normalized")
        self.assertFalse(result.metadata["raw_counts_available"])

    def test_h5ad_unknown_semantics_requires_confirmation(self):
        import anndata as ad
        import numpy as np
        from spatialmind.ingestion.pipeline import DataIngestionLayer, IngestionValidationError
        a = ad.AnnData(X=np.array([[1., 2.], [2., 1.], [3., 1.]]))
        a.var_names = ["GFAP", "AQP4"]; a.obsm["spatial"] = np.array([[0., 0.], [1., 1.], [2., 2.]])
        path = self.root / "unknown.h5ad"; a.write_h5ad(path)
        with self.assertRaises(IngestionValidationError):
            DataIngestionLayer().load_h5ad(str(path), backed=False)
        result = DataIngestionLayer().load_h5ad(str(path), backed=False, expression_semantics="raw_counts")
        self.assertTrue(result.metadata["raw_counts_available"])

    def test_invalid_matrix_values_cannot_hide_in_filtered_features(self):
        from spatialmind.ingestion.pipeline import _matrix_row_to_features, IngestionValidationError
        for value in (float("nan"), float("inf"), -1):
            with self.assertRaises(IngestionValidationError):
                _matrix_row_to_features([100, value], ["G1", "G2"], 1)

    def test_non_natural_log_expression_is_refused(self):
        from spatialmind.ingestion.expression import resolve_expression_semantics
        with self.assertRaisesRegex(ValueError, "log bases"):
            resolve_expression_semantics(has_log1p=True, log_base=2)

    def test_failed_audit_write_leaves_the_original_table_unchanged(self):
        path = self.root / "expert_cell_labels.csv"
        write_rows(path, [approved()]); original = path.read_bytes()
        with patch.object(Path, "write_text", side_effect=OSError("fixture: journal failed")):
            with self.assertRaises(review.ReviewWriteError):
                review.assign(str(self.root), "labels", ["0"], "changed", reviewer_id="fixture-reviewer",
                              evidence_ref="fixture:recheck")
        self.assertEqual(path.read_bytes(), original)

    def test_nonfinite_or_out_of_range_coverage_is_refused(self):
        from spatialmind.gatekeeper import validate_coverage_thresholds
        for threshold in (float("nan"), float("inf"), -1, 2):
            with self.assertRaises(ValueError):
                validate_coverage_thresholds(threshold, .7)

    def test_raw_and_log_normalized_references_give_equivalent_transfer(self):
        import copy
        import math
        from spatialmind.tools.implementations import reference_label_transfer
        reference = SpatialDataset("ref", [SpotRecord("ref", 0, 0, "A" if i % 2 else "B",
                    {"G1": 100 if i % 2 else 1, "G2": 1 if i % 2 else 100}, cell_id="r" + str(i)) for i in range(20)], "")
        query = SpatialDataset("query", [SpotRecord("q", 0, 0, "", {"G1": 90, "G2": 2}, cell_id="q")], "")
        logged = copy.deepcopy(reference)
        for row in logged.records:
            total = sum(row.genes.values())
            row.genes = {gene: math.log1p(value / total * 10000) for gene, value in row.genes.items()}
        logged.normalized = True; logged.metadata["source_value_semantics"] = "log_normalized"
        params = {"min_shared_features": 2, "n_neighbors": 5}
        raw = reference_label_transfer(copy.deepcopy(query), dict(params, reference_dataset=reference))
        log = reference_label_transfer(copy.deepcopy(query), dict(params, reference_dataset=logged))
        self.assertEqual(raw.metrics["predictions"][0]["predicted_label"], log.metrics["predictions"][0]["predicted_label"])
        self.assertAlmostEqual(raw.metrics["predictions"][0]["confidence"], log.metrics["predictions"][0]["confidence"])


if __name__ == "__main__":
    unittest.main()
