"""Engineering fixtures only; these tests do not measure brain biological accuracy."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spatialmind.review.annotation_benchmark import digest, write_json, write_csv
from spatialmind.review.brain_readiness import initialize, assign
from spatialmind.review.specialist_handoff import validate_handoff
from spatialmind.review.brain_validation import select_brain_annotation, evaluate_external_once
from spatialmind.review.claim_calibration import evaluate_reviewed_calibration, probability_metrics
from spatialmind.review.claim_truth import validate_claim_truth_table
from spatialmind.schemas import SpatialDataset, SpotRecord


class ReviewedValidationTests(unittest.TestCase):
    def claims(self):
        return [dict(record_id=split + str(i), reviewed_truth_label=str(i % 2), use_for_calibration="yes",
                     reviewer_id="fixture-reviewer", review_status="reviewed", reviewed_at="2026-09-30",
                     truth_basis="synthetic correctness fixture, not biology", source_citation="fixture:claim",
                     donor_id="synthetic-" + split, split=split, calibration_scope="biological_claim",
                     S_statistical=str(.8 if i % 2 else .2), A_annotation="0.9", P_panel="0.8", R_spatial_robustness="0.8")
                for split in ("train", "validation", "test") for i in range(6)]

    def test_reviewed_donor_split_reports_actual_heldout_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truth.csv"
            write_csv(path, self.claims())
            result = evaluate_reviewed_calibration(path)
            self.assertEqual(result["status"], "donor_heldout_evaluated_not_production_validated")
            self.assertEqual(result["model"]["record_count"], 6)
            self.assertEqual(result["metrics"]["test"]["records"], 6)
            self.assertIn("brier_score", result["metrics"]["test"])
            self.assertIn("ece_10_bins", result["metrics"]["test"])

    def test_donor_overlap_missing_identity_and_controls_block_calibration(self):
        for mutation in ("overlap", "missing", "control", "candidate", "component", "citation"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                rows = self.claims()
                if mutation == "overlap":
                    rows[-1]["donor_id"] = "synthetic-train"
                else:
                    key, value = {"missing": ("donor_id", ""), "control": ("calibration_scope", "null_control"),
                                  "candidate": ("review_status", "candidate"), "component": ("S_statistical", "nan"),
                                  "citation": ("source_citation", "")}[mutation]
                    rows[0][key] = value
                path = Path(tmp) / "truth.csv"
                write_csv(path, rows)
                result = evaluate_reviewed_calibration(path)
                self.assertEqual(result["status"], "blocked")
                self.assertFalse(result["test_scored"])

    def test_duplicate_claim_ids_cannot_train(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = self.claims(); rows[-1]["record_id"] = rows[0]["record_id"]
            path = Path(tmp) / "truth.csv"; write_csv(path, rows)
            self.assertEqual(validate_claim_truth_table(str(path))["status"], "blocked")

    def test_probability_metric_includes_probability_one_in_last_bin(self):
        score = probability_metrics([{"reviewed_truth_label": 0, "calibrated_reliability": 0},
                                     {"reviewed_truth_label": 1, "calibrated_reliability": 1}])
        self.assertEqual(score["brier_score"], 0)
        self.assertEqual(score["ece_10_bins"], 0)
        self.assertEqual(sum(row["count"] for row in score["calibration_curve"]), 2)

    def packet(self, root):
        packet, source = root / "packet", root / "source"
        folder = packet / "brain"; folder.mkdir(parents=True)
        source.mkdir(); (source / "cell_feature_matrix.h5").write_text("synthetic hashed placeholder")
        cohort = [dict(cell_id=str(i), x=str(i), y="0") for i in range(60)]
        labels = [dict(row, expert_label="A" if i % 2 else "B", confidence="0.9", review_status="reviewed",
                       reviewer_id="fixture-specialist", reviewed_at="2026-09-30", evidence_ref="fixture:markers")
                  for i, row in enumerate(cohort)]
        regions = [dict(row, region="synthetic-roi", region_confidence="0.9", review_status="reviewed",
                       region_reviewer_id="fixture-pathologist", region_reviewed_at="2026-09-30",
                       evidence_ref="fixture:image", region_basis="morphology") for row in cohort]
        write_json(folder / "frozen_cohort.json", cohort)
        write_csv(folder / "expert_cell_labels_for_review.csv", labels)
        write_csv(folder / "cell_regions_for_review.csv", regions)
        write_csv(folder / "benchmark_split_manifest.csv", [dict(row, proposed_spatial_block=str(i // 20),
                  provisional_split=("train", "validation", "test")[i // 20]) for i, row in enumerate(cohort)])
        write_json(packet / "handoff_manifest.json", {"datasets": {"brain": {"source_dataset": str(source),
                   "immutable_files": {name: digest(folder / name) for name in ("frozen_cohort.json", "benchmark_split_manifest.csv")}}}})
        initialize(packet)
        assign(packet, "brain_single_cell_specialist", "fixture-specialist", "synthetic test role only")
        assign(packet, "neuropathologist", "fixture-pathologist", "synthetic test role only")
        staging = root / "staging"; validate_handoff(packet, staging)
        data = SpatialDataset("brain", [SpotRecord("brain", i, 0, "unused-label", {"G1": 100 if i % 2 else 1,
                    "G2": 1 if i % 2 else 100}, cell_id=str(i)) for i in range(60)], str(source))
        return packet, staging, data

    def select(self, root):
        packet, staging, data = self.packet(root)
        # The selection needs no internal test-truth file.
        (staging / "brain" / "test_truth.csv").unlink()
        with patch("spatialmind.review.brain_validation.load_xenium", return_value=data):
            return select_brain_annotation(packet, staging, root / "model", {"brain": "synthetic-development"})

    def test_model_selection_uses_only_development_and_freezes_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); result = self.select(root)
            self.assertFalse(result["test_truth_opened"])
            self.assertFalse(result["test_scored"])
            self.assertEqual(result["validation"]["n_cells"], 20)
            self.assertEqual(len(json.loads((root / "model" / "training_reference.json").read_text())), 20)
            self.assertEqual(result["model_lock_sha256"], digest(result["model_lock"]))

    def test_unassigned_specialists_do_not_create_training_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); write_json(root / "study_readiness.json", {"reviewers": {}})
            result = select_brain_annotation(root, root / "missing", root / "model")
            self.assertEqual(result["status"], "blocked_awaiting_specialists")
            self.assertFalse((root / "model").exists())

    def test_changed_review_after_staging_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); packet, staging, data = self.packet(root)
            (packet / "brain" / "expert_cell_labels_for_review.csv").write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed after staging"):
                select_brain_annotation(packet, staging, root / "model")

    def external(self, root, selection):
        folder = root / "external"; folder.mkdir()
        (folder / "counts.h5ad").write_text("synthetic expression placeholder")
        write_csv(folder / "truth.csv", [dict(cell_id=str(i), expert_label="A" if i % 2 else "B", confidence="0.9",
                  review_status="reviewed", reviewer_id="fixture-independent", reviewed_at="2026-09-30",
                  evidence_ref="fixture:external", donor_id="synthetic-external") for i in range(6)])
        write_csv(folder / "crosswalk.csv", [{"source_label": name, "target_label": name} for name in ("A", "B")])
        write_json(folder / "protocol.json", {"model_lock_sha256": selection["model_lock_sha256"],
                   "confidence_threshold": .6, "min_shared_features": 2, "min_shared_fraction": 1})
        names = ("counts.h5ad", "truth.csv", "crosswalk.csv", "protocol.json")
        write_json(folder / "manifest.json", {"source_url": "https://example.org/synthetic", "license": "test fixture",
                   "label_provenance": "synthetic", "independence_evidence": "synthetic only", "custodian_id": "fixture-custodian",
                   "organism": "human", "tissue": "brain", "assay": "synthetic", "expression_file": "counts.h5ad",
                   "truth_file": "truth.csv", "label_crosswalk": "crosswalk.csv", "evaluation_protocol": "protocol.json",
                   "development_donor_ids": ["synthetic-development"], "test_donor_ids": ["synthetic-external"],
                   "donor_independence_confirmed": True, "labels_independent_of_this_agent": True, "test_labels_sealed": True,
                   "files": {name: digest(folder / name) for name in names}})
        data = SpatialDataset("external", [SpotRecord("external", 0, 0, "leaky-label", {"G1": 100 if i % 2 else 1,
                              "G2": 1 if i % 2 else 100}, cell_id=str(i)) for i in range(6)], "")
        return folder / "manifest.json", data

    def test_custodian_release_predicts_blind_and_refuses_a_second_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); selection = self.select(root); manifest, data = self.external(root, selection)
            with patch("spatialmind.review.brain_validation.load_scrna", return_value=data):
                result = evaluate_external_once(selection["model_lock"], manifest, root / "result",
                                                 "fixture-custodian", selection["model_lock_sha256"])
            self.assertEqual(result["metrics"]["n_cells"], 6)
            self.assertTrue((root / "result" / "predictions_before_truth_release.csv").exists())
            with self.assertRaises(FileExistsError):
                evaluate_external_once(selection["model_lock"], manifest, root / "retry",
                                        "fixture-custodian", selection["model_lock_sha256"])

    def test_wrong_custodian_or_lock_hash_cannot_reserve_a_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); selection = self.select(root); manifest, _ = self.external(root, selection)
            for who, sha in (("wrong", selection["model_lock_sha256"]), ("fixture-custodian", "wrong")):
                with self.assertRaises(ValueError):
                    evaluate_external_once(selection["model_lock"], manifest, root / "result", who, sha)
            self.assertFalse((root / "model" / "external_test_attempt.json").exists())


if __name__ == "__main__":
    unittest.main()
