import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from spatialmind.review.annotation_benchmark import digest, write_csv, write_json
from spatialmind.review.brain_readiness import (
    initialize, assign, assignment_issues, readiness, validate_image_evidence,
    validate_external_manifest, acquire_candidate_catalog,
)
from spatialmind.review.specialist_handoff import validate_handoff
from spatialmind.review.rare_class_selection import select_rare_class_policy
from spatialmind.tools.annotation_priors import reweight_votes


class BrainReadinessTests(unittest.TestCase):
    def packet(self, root):
        folder = root / "brain"
        folder.mkdir()
        cohort = [{"cell_id": str(i), "x": "0", "y": str(i)} for i in range(3)]
        write_json(folder / "frozen_cohort.json", cohort)
        write_csv(folder / "benchmark_split_manifest.csv", [dict(row, proposed_spatial_block=str(i), provisional_split=s)
                  for i, (row, s) in enumerate(zip(cohort, ("train", "validation", "test")))])
        write_csv(folder / "expert_cell_labels_for_review.csv", [dict(row, expert_label="astrocyte", confidence="0.9",
                  reviewer_id="specialist", reviewed_at="2026-09-27", review_status="reviewed", evidence_ref="panel") for row in cohort])
        write_csv(folder / "cell_regions_for_review.csv", [dict(row, region="region", region_confidence="0.9",
                  region_reviewer_id="pathologist", region_reviewed_at="2026-09-27", review_status="reviewed",
                  evidence_ref="image", region_basis="morphology") for row in cohort])
        write_json(root / "handoff_manifest.json", {"datasets": {"brain": {"source_dataset": str(root / "dataset"),
                   "immutable_files": {name: digest(folder / name) for name in ("frozen_cohort.json", "benchmark_split_manifest.csv")}}}})
        initialize(root)

    def test_unassigned_roles_block_staging_and_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.packet(root)
            result = readiness(root)
            self.assertEqual(result["steps"][0]["status"], "needs_input")
            self.assertTrue(all(s["status"] == "blocked_by_previous_step" for s in result["steps"][1:]))
            with self.assertRaises(ValueError):
                validate_handoff(root, root / "final")
            self.assertFalse((root / "final").exists())

    def test_recorded_assignments_match_decision_reviewers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.packet(root)
            assign(root, "brain_single_cell_specialist", "wrong", "institutional profile")
            assign(root, "neuropathologist", "pathologist", "institutional profile")
            self.assertIn("Cell label reviewer differs from assigned specialist", validate_handoff(root)["datasets"]["brain"]["blockers"])
            assign(root, "brain_single_cell_specialist", "specialist", "institutional profile")
            self.assertEqual(validate_handoff(root)["status"], "ready_for_staging")

    def test_configuration_cannot_be_reinitialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.packet(root)
            with self.assertRaises(ValueError):
                initialize(root)

    def image(self, root):
        import tifffile
        dataset = root / "dataset"
        dataset.mkdir()
        (dataset / "experiment.xenium").write_text("{}")
        tifffile.imwrite(root / "histology.ome.tif", np.zeros((16, 16), dtype=np.uint8))
        files = {str(p): digest(p) for p in (root / "histology.ome.tif", dataset / "experiment.xenium")}
        points = [{"use": role, "image_xy_px": point, "xenium_xy_um": point}
                  for role, values in (("fit", [[0, 0], [0, 10], [10, 0]]), ("check", [[2, 2], [2, 8], [8, 2]])) for point in values]
        data = {"files": files, "image_file": str(root / "histology.ome.tif"), "dataset_path": str(dataset),
                "modality": "H&E", "reviewer_id": "pathologist", "same_section_confirmed": True,
                "visual_alignment_approved": True, "pairing_evidence": "slide ledger", "threshold_rationale": "test only",
                "transform_convention": "image_pixel_xy_to_xenium_micron_xy_column_vector", "matrix": np.eye(3).tolist(),
                "landmarks": points, "max_check_error_um": 2}
        path = root / "image_manifest.json"
        write_json(path, data)
        return path, dataset, data

    def test_affine_check_uses_independent_landmarks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, dataset, data = self.image(Path(tmp))
            self.assertEqual(validate_image_evidence(path, dataset, "pathologist")["max_error_um"], 0)
            data["landmarks"][-1]["xenium_xy_um"] = [100, 100]
            write_json(path, data)
            with self.assertRaisesRegex(ValueError, "residual"):
                validate_image_evidence(path, dataset, "pathologist")

    def test_image_rejects_wrong_specimen_units_dapi_and_reused_landmarks(self):
        for mutation in ("dataset_path", "transform_convention", "modality", "reuse"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                path, dataset, data = self.image(Path(tmp))
                if mutation == "reuse":
                    data["landmarks"][-1]["image_xy_px"] = [0, 0]
                else:
                    data[mutation] = {"dataset_path": "/different", "transform_convention": "inverse", "modality": "DAPI"}[mutation]
                write_json(path, data)
                with self.assertRaises(ValueError):
                    validate_image_evidence(path, dataset, "pathologist")

    def test_image_changed_after_review_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, dataset, data = self.image(Path(tmp))
            (dataset / "experiment.xenium").write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                validate_image_evidence(path, dataset, "pathologist")

    def external(self, root):
        files = {}
        for name in ("counts.h5", "truth.csv", "crosswalk.csv", "protocol.json"):
            (root / name).write_text("fixture")
            files[name] = digest(root / name)
        data = {"files": files, "source_url": "https://example.org/study", "license": "CC0", "label_provenance": "authors",
                "independence_evidence": "donor ledger", "custodian_id": "custodian", "organism": "human", "tissue": "brain",
                "assay": "Xenium", "label_crosswalk": "crosswalk.csv", "evaluation_protocol": "protocol.json",
                "expression_file": "counts.h5", "truth_file": "truth.csv", "donor_independence_confirmed": True,
                "labels_independent_of_this_agent": True, "test_labels_sealed": True,
                "development_donor_ids": ["train_donor"], "test_donor_ids": ["external_donor"]}
        path = root / "external.json"
        write_json(path, data)
        return path, data

    def test_external_rejects_shared_donor_and_unsealed_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, data = self.external(Path(tmp))
            self.assertEqual(validate_external_manifest(path)["test_donors"], 1)
            for key, value in (("test_donor_ids", ["train_donor"]), ("test_labels_sealed", False)):
                changed = dict(data, **{key: value})
                write_json(path, changed)
                with self.assertRaises(ValueError):
                    validate_external_manifest(path)

    def test_catalog_never_downloads_test_labels(self):
        with tempfile.TemporaryDirectory() as tmp, patch("requests.get") as get:
            get.return_value.json.return_value = {"accno": "S-BSST2273", "section": {"files": [{"path": "large.tar.gz", "size": 1000000000}]}}
            result = acquire_candidate_catalog(tmp)
            self.assertEqual(result["status"], "metadata_only_not_test_data")
            self.assertEqual(get.call_count, 1)
            self.assertFalse((Path(tmp) / "large.tar.gz").exists())


class RareClassTests(unittest.TestCase):
    def test_zero_prior_preserves_existing_probabilities(self):
        votes = np.array([[0.7, 0.3]])
        np.testing.assert_array_equal(reweight_votes(votes, ["A", "B"], ["A"] * 9 + ["B"], 0), votes)

    def test_prior_uses_training_support_and_cannot_invent_neighbor_classes(self):
        votes = reweight_votes([[0.7, 0.3], [1, 0]], ["A", "B"], ["A"] * 9 + ["B"], 1)
        self.assertGreater(votes[0, 1], votes[0, 0])
        np.testing.assert_array_equal(votes[1], [1, 0])

    def test_invalid_prior_inputs_rejected(self):
        for power in (-1, 2, float("nan")):
            with self.assertRaises(ValueError):
                reweight_votes([[0.7, 0.3]], ["A", "B"], ["A", "B"], power)
        with self.assertRaises(ValueError):
            reweight_votes([[0.7, 0.3]], ["A", "B"], ["A"], 0.5)

    def test_selection_never_requires_a_test_truth_file(self):
        import h5py
        from scipy.sparse import csc_matrix
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            vault = root / "evaluator_only"
            vault.mkdir()
            ids = [str(i) for i in range(40)]
            counts = csc_matrix([[10 if i % 2 else 0 for i in range(40)], [0 if i % 2 else 10 for i in range(40)]])
            matrix = root / "matrix.h5"
            with h5py.File(matrix, "w") as h:
                g = h.create_group("matrix")
                for key in ("data", "indices", "indptr", "shape"):
                    g[key] = getattr(counts, key)
                g["features/name"] = np.asarray([b"g1", b"g2"])
                g["barcodes"] = np.asarray([x.encode() for x in ids])
            write_json(root / "protocol.json", {"features": ["G1", "G2"], "source_hashes": {str(matrix): digest(matrix)}})
            write_csv(root / "split_manifest.csv", [{"cell_id": x, "block": "train" if i < 30 else "validation",
                      "split": "train" if i < 30 else "validation", "included": True} for i, x in enumerate(ids)])
            for group, members in (("train", ids[:30]), ("validation", ids[30:])):
                write_csv(vault / (group + "_truth.csv"), [{"cell_id": x, "expert_label": "A" if int(x) % 2 else "B"} for x in members])
            write_json(root / "artifact_hashes.json", {str(p.relative_to(root)): digest(p) for p in root.rglob("*") if p.is_file()})
            result = select_rare_class_policy(root, matrix, root / "out")
            self.assertEqual(result["selected_power"], 0)
            self.assertEqual(result["selected"]["accuracy"], 1)
            self.assertFalse((vault / "test_truth.csv").exists())
            with self.assertRaises(ValueError):
                select_rare_class_policy(root, matrix, root / "out")

    def test_production_tool_exposes_opt_in_and_preserves_default(self):
        from spatialmind.schemas import SpatialDataset, SpotRecord
        from spatialmind.tools.implementations import reference_label_transfer
        reference = SpatialDataset("ref", [SpotRecord("ref", 0, 0, "A" if i < 9 else "B",
                       {"G1": 2, "G2": 1}, cell_id=str(i)) for i in range(10)], "")
        query = SpatialDataset("query", [SpotRecord("query", 0, 0, "", {"G1": 2, "G2": 1}, cell_id="q")], "")
        params = {"reference_dataset": reference, "min_shared_features": 2, "n_neighbors": 10, "allow_incomplete_reference": True}
        default = reference_label_transfer(query, params)
        zero = reference_label_transfer(query, dict(params, class_prior_power=0))
        corrected = reference_label_transfer(query, dict(params, class_prior_power=0.5))
        self.assertEqual(default.metrics["predictions"], zero.metrics["predictions"])
        self.assertEqual(corrected.metrics["class_prior_power"], 0.5)
        self.assertLess(corrected.metrics["predictions"][0]["confidence"], default.metrics["predictions"][0]["confidence"])


if __name__ == "__main__":
    unittest.main()
