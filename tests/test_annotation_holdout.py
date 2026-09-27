import csv
import json
import tempfile
import unittest
from pathlib import Path

from spatialmind.schemas import SpatialDataset, SpotRecord, NON_GENE_FEATURE_TYPES, expression_feature_names
from spatialmind.review.annotation_benchmark import (
    blinded_dataset, spatial_split, predict, metrics, block_interval, digest, write_csv, write_json,
    run_annotation_benchmark,
)
from spatialmind.review.specialist_handoff import _accepted, validate_handoff


class AnnotationHoldoutTests(unittest.TestCase):
    def dataset(self):
        return SpatialDataset("secret", [SpotRecord("secret", x * 100, y * 100, "truth",
               {"G1": x + 1, "G2": y + 1}, region="secret_region", cell_id="%s_%s" % (x, y))
               for x in range(12) for y in range(12)], "secret_path",
               metadata={"reviewed_cell_labels": {"0_0": "truth"}, "organism": "human"})

    def test_blinding_removes_labels_regions_metadata_and_source_paths(self):
        data = self.dataset()
        query = blinded_dataset(data, ["0_0", "0_1"], ["G1", "G2"])
        self.assertEqual(query.source_path, "")
        self.assertEqual(query.metadata, {"organism": "human"})
        self.assertTrue(all(not r.cell_type and r.region is None and r.x == 0 for r in query.records))
        self.assertEqual(data.records[0].cell_type, "truth")

    def test_reference_only_gets_requested_training_labels(self):
        data = blinded_dataset(self.dataset(), ["0_0", "0_1"], ["G1"], {"0_0": "A", "1_1": "leak"})
        self.assertEqual([r.cell_type for r in data.records], ["A", ""])

    def test_blocks_are_disjoint_and_splitting_is_label_independent(self):
        data = self.dataset()
        first = spatial_split(data.records, buffer_um=150)
        for r in data.records:
            r.cell_type = "changed"
        self.assertEqual(first, spatial_split(data.records, buffer_um=150))
        blocks = {}
        for row in first:
            blocks.setdefault(row["block"], set()).add(row["split"])
            if row["included"]:
                self.assertGreaterEqual(row["nearest_other_split_um"], 150)
        self.assertTrue(all(len(splits) == 1 for splits in blocks.values()))
        self.assertTrue(any(not row["included"] for row in first))

    def test_rejects_duplicate_or_missing_cell_ids(self):
        records = self.dataset().records
        with self.assertRaises(ValueError):
            spatial_split(records + [records[0]])
        records[0].cell_id = ""
        with self.assertRaises(ValueError):
            spatial_split(records)

    def test_prediction_rejects_truth_or_overlap(self):
        data = self.dataset()
        with self.assertRaises(ValueError):
            predict(data, data, 5)
        query = blinded_dataset(data, ["0_0"], ["G1"])
        with self.assertRaises(ValueError):
            predict(query, query, 5)

    def test_predictions_invariant_to_hidden_labels(self):
        data = self.dataset()
        ids = [r.cell_id for r in data.records[:24]]
        reference = blinded_dataset(data, ids, ["G1", "G2"], {key: "A" if i < 12 else "B" for i, key in enumerate(ids)})
        query_ids = [r.cell_id for r in data.records[24:30]]
        first = predict(blinded_dataset(data, query_ids, ["G1", "G2"]), reference, 3)
        for record in data.records:
            record.cell_type = "arbitrary_test_truth"
        second = predict(blinded_dataset(data, query_ids, ["G1", "G2"]), reference, 3)
        self.assertEqual(first, second)

    def test_abstention_keeps_rejected_cells_in_denominator(self):
        result = metrics(["A", "B"], [{"predicted_label": "A", "confidence": 0.9}, {"predicted_label": "A", "confidence": 0.4}])
        self.assertEqual(result["accuracy"], 0.5)
        self.assertEqual(result["coverage"], 0.5)
        self.assertEqual(result["selective_accuracy"], 1.0)
        self.assertEqual(result["balanced_accuracy"], 0.5)

    def test_unsupported_truth_class_is_counted(self):
        result = metrics(["A", "absent"], [{"predicted_label": "A", "confidence": 1}] * 2)
        self.assertEqual(next(r for r in result["per_class"] if r["label"] == "absent")["recall"], 0)

    def test_all_abstain_is_not_reported_as_perfect(self):
        result = metrics(["A"], [{"predicted_label": "A", "confidence": 0.1}])
        self.assertIsNone(result["selective_accuracy"])
        self.assertEqual(result["macro_f1_with_abstention"], 0)

    def test_bootstrap_refuses_one_independent_block(self):
        result = block_interval(["A"], [{"predicted_label": "A"}], ["one"])
        self.assertEqual(result["status"], "unavailable")

    def test_frozen_output_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "protocol.json").write_text("{}")
            with self.assertRaises(ValueError):
                run_annotation_benchmark("unused", folder)

    def test_legacy_blank_codewords_are_declared_controls(self):
        import h5py
        from spatialmind.ingestion.pipeline import _read_h5_control_features
        self.assertIn("blank codeword", NON_GENE_FEATURE_TYPES)
        with tempfile.TemporaryDirectory() as folder:
            with h5py.File(str(Path(folder) / "fixture.h5"), "w") as handle:
                matrix = handle.create_group("matrix")
                matrix.create_group("features").create_dataset("feature_type", data=[b"Gene Expression", b"Blank Codeword", b"Negative Control Probe", b"Gene Expression"])
                controls, _, source = _read_h5_control_features(matrix, ["G1", "BLANK_01", "N1", "G2"])
                self.assertEqual(set(controls), {"BLANK_01", "N1"})
                self.assertEqual(source, "declared_feature_type")
        data = SpatialDataset("x", [SpotRecord("x", 0, 0, "", {"G1": 1, "G2": 1, "BLANK_01": 1, "N1": 1})], "", metadata={"control_features": controls})
        self.assertEqual(expression_feature_names(data), ["G1", "G2"])


class SpecialistHandoffTests(unittest.TestCase):
    def decision(self, region=False):
        if region:
            return {"region": "synthetic_region", "region_confidence": "0.9", "region_reviewer_id": "synthetic_fixture",
                    "region_reviewed_at": "2026-09-27", "review_status": "reviewed", "region_basis": "registered_histology", "evidence_ref": "fixture_slide:roi_1"}
        return {"expert_label": "synthetic_class", "confidence": "0.9", "reviewer_id": "synthetic_fixture",
                "reviewed_at": "2026-09-27", "review_status": "reviewed", "evidence_ref": "fixture_marker_panel"}

    def fixture(self, root):
        folder = root / "brain"
        folder.mkdir()
        cohort = [{"cell_id": str(i), "x": str(i), "y": "0"} for i in range(30)]
        write_json(folder / "frozen_cohort.json", cohort)
        splits = [{"cell_id": str(i), "proposed_spatial_block": str(i // 10), "provisional_split": ["train", "validation", "test"][i // 10]} for i in range(30)]
        write_csv(folder / "benchmark_split_manifest.csv", splits)
        write_csv(folder / "expert_cell_labels_for_review.csv", [dict(row, **self.decision()) for row in cohort])
        write_csv(folder / "cell_regions_for_review.csv", [dict(row, **self.decision(True)) for row in cohort])
        write_json(root / "handoff_manifest.json", {"datasets": {"brain": {"immutable_files": {name: digest(folder / name) for name in ("frozen_cohort.json", "benchmark_split_manifest.csv")}}}})
        return folder

    def test_candidate_with_reviewer_name_is_not_reviewed(self):
        row = self.decision()
        row["review_status"] = "candidate"
        self.assertFalse(_accepted(row))

    def test_regions_require_anatomical_evidence(self):
        row = self.decision(True)
        row["region_basis"] = "composition"
        self.assertFalse(_accepted(row, True))

    def test_rejects_missing_evidence_invalid_date_and_nan_confidence(self):
        for field, value in (("evidence_ref", ""), ("reviewed_at", "someday"), ("confidence", "nan")):
            row = self.decision()
            row[field] = value
            self.assertFalse(_accepted(row))

    def test_valid_recorded_decisions_stage_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "packet"; root.mkdir()
            self.fixture(root)
            output = Path(tmp) / "staged"
            result = validate_handoff(root, output)
            self.assertEqual(result["status"], "ready_for_staging")
            self.assertTrue((output / "brain/expert_cell_labels.csv").exists())
            self.assertTrue((output / "brain/cell_regions.csv").exists())
            self.assertTrue((output / "brain/test_truth.csv").exists())

    def test_frozen_split_tampering_blocks_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "packet"; root.mkdir()
            folder = self.fixture(root)
            with (folder / "benchmark_split_manifest.csv").open("a") as stream:
                stream.write("99,0,test\n")
            with self.assertRaises(ValueError):
                validate_handoff(root, Path(tmp) / "staged")
            self.assertFalse((Path(tmp) / "staged").exists())

    def test_low_coverage_in_one_split_blocks_even_when_overall_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "packet"; root.mkdir()
            folder = self.fixture(root)
            with (folder / "expert_cell_labels_for_review.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            for row in rows[:2]:
                row["review_status"] = "needs_review"
            write_csv(folder / "expert_cell_labels_for_review.csv", rows)
            result = validate_handoff(root)
            self.assertEqual(result["status"], "awaiting_specialist_review")
            self.assertEqual(result["datasets"]["brain"]["joint_coverage_by_split"]["train"], 0.8)


if __name__ == "__main__":
    unittest.main()
