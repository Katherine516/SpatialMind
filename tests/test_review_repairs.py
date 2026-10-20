"""Regression tests for the October reliability review; fixtures are synthetic."""
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spatialmind.app.plan_report import build_markdown, lane_for_payload
from spatialmind.storage.run_store import StorageLayer, snapshot_inputs
from spatialmind.storage.replay import replay_run_record, verify_run_record


class ProvenanceRepairs(unittest.TestCase):
    def test_manifest_and_alternate_review_tables_are_content_hashed(self):
        from spatialmind.ingestion.loaders.xenium import xenium_analysis_inputs
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "experiment.xenium"
            manifest.write_text("{}")
            table = root / "cell_annotations.tsv"
            table.write_text("cell_id\tlabel\nc1\tA\n")
            inputs = xenium_analysis_inputs(str(manifest))
            self.assertEqual(inputs[0], str(manifest))
            self.assertIn(str(root.resolve()), inputs)
            self.assertIn(str(table.resolve()), inputs)
            before = snapshot_inputs(inputs)
            table.write_text("cell_id\tlabel\nc1\tB\n")
            self.assertNotEqual(snapshot_inputs(inputs), before)

    def test_mutation_is_invalid_even_after_source_is_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "counts.txt"
            source.write_text("12")
            before = snapshot_inputs([str(source)])
            source.write_text("34")
            with self.assertRaisesRegex(RuntimeError, "Inputs changed"):
                StorageLayer(temp).write_mvp_run_record(
                    query="test", tool_trace=[], params={}, input_files=[str(source)],
                    input_snapshot=before, run_id="mutation")
            path = Path(temp) / "runs/mutation.json"
            record = json.loads(path.read_text())
            self.assertEqual(record["input_file_md5"], before)
            source.write_text("12")
            self.assertEqual(verify_run_record(str(path)).status, "failed")
            self.assertEqual(replay_run_record(str(path), verify_only=False)["status"],
                             "blocked_verification_failed")

    def test_unchanged_snapshot_verifies(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "counts.txt"
            source.write_text("12")
            record = StorageLayer(temp).write_mvp_run_record(
                query="test", tool_trace=[], params={}, input_files=[str(source)],
                input_snapshot=snapshot_inputs([str(source)]))
            self.assertEqual(verify_run_record(record.run_record_path).status, "verified")

    def test_pilot_captures_before_loader_not_after_it(self):
        from scripts.smoke_test_macos_app import make_dataset
        from spatialmind.pilot import xenium
        import h5py

        with tempfile.TemporaryDirectory() as temp:
            bundle = make_dataset(Path(temp) / "data")
            out = Path(temp) / "run"
            before = snapshot_inputs([str(bundle)])
            loader = xenium.load_xenium

            def mutate(*args, **kwargs):
                dataset = loader(*args, **kwargs)
                with h5py.File(bundle / "cell_feature_matrix.h5", "r+") as handle:
                    handle["matrix/data"][0] += 1000
                return dataset

            with patch.object(xenium, "load_xenium", side_effect=mutate), \
                 patch.object(xenium, "_write_review_figures", return_value=[]), \
                 patch.object(xenium, "_run_descriptive_lane", return_value={"status": "not_run"}):
                with self.assertRaisesRegex(RuntimeError, "Inputs changed"):
                    xenium.run_pilot(str(bundle), out, max_records=0, review_artifacts=False)
            record_path = next((out / "runs").glob("*.json"))
            self.assertEqual(json.loads(record_path.read_text())["input_file_md5"], before)
            self.assertEqual(verify_run_record(str(record_path)).status, "failed")
            self.assertFalse((out / "validated_xenium_pilot_report.html").exists())

    def test_pilot_preserves_descriptive_trace_figures_and_pdf_parity(self):
        from scripts.smoke_test_macos_app import make_dataset
        from spatialmind.pilot import xenium

        with tempfile.TemporaryDirectory() as temp:
            bundle = make_dataset(Path(temp) / "data")
            out = Path(temp) / "run"
            out.mkdir()
            figure = out / "descriptive_cluster_map.png"
            figure.write_bytes(b"synthetic-figure-hash-fixture")
            descriptive = {"status": "computed", "figures": [str(figure)],
                           "tool_trace": [{"tool_name": "qc_and_cluster", "lane": "descriptive",
                                           "params": {"random_state": 0}}]}
            with patch.object(xenium, "_write_review_figures", return_value=[]), \
                 patch.object(xenium, "_run_descriptive_lane", return_value=descriptive):
                payload = xenium.run_pilot(str(bundle), out, max_records=0, review_artifacts=False)
            record = json.loads(Path(payload["run_record_path"]).read_text())
            self.assertIn(str(figure), record["figure_md5"])
            self.assertEqual(record["tool_trace"][0]["params"], {"random_state": 0})
            self.assertIn("descriptive_cluster_map", Path(payload["report_html"]).read_text())
            with patch.object(xenium, "write_pdf_report") as writer:
                xenium._write_pilot_pdf_report(out / "report.pdf", payload, [])
            sections = writer.call_args.args[2]
            pdf_paths = [fig.path for section in sections for fig in section.figures]
            self.assertIn(str(figure), pdf_paths)


class ReportLaneRepairs(unittest.TestCase):
    def test_partial_review_cannot_promote_cluster_run(self):
        payload = {"label_report": {"status": "expert_labels_applied"},
                   "gate": {"status": "blocked_missing_validation_inputs"},
                   "results": [{"tool": "qc_and_cluster", "metrics": {}}]}
        self.assertEqual(lane_for_payload(payload), "descriptive")
        self.assertNotIn("**validated-lane**", build_markdown(payload))

    def test_open_gate_alone_does_not_promote_clustering(self):
        self.assertEqual(lane_for_payload({"gate": {"status": "validated_ready"},
                         "results": [{"tool": "qc_and_cluster", "metrics": {}}]}), "descriptive")

    def test_reviewed_results_and_gate_are_both_required(self):
        payload = {"gate": {"status": "validated_ready"},
                   "results": [{"metrics": {"reviewed_only": True}}]}
        self.assertEqual(lane_for_payload(payload), "validated")
        self.assertIn("remain descriptive", build_markdown(payload))
        self.assertEqual(lane_for_payload(payload, {"status": "blocked"}), "descriptive")


class ConditionalNullRepairs(unittest.TestCase):
    def test_all_permutations_match_explicit_focal_exclusion(self):
        import numpy as np
        from scipy.sparse import csr_matrix
        from spatialmind.tools.spatial_statistics import _conditional_lag

        z = np.array([-2., -1., 0., 1., 2.])
        weights = np.array([[0, .2, .8, 0, 0], [.3, 0, .7, 0, 0],
                            [0, 0, 0, .5, .5], [.1, 0, 0, 0, .9], [.4, .6, 0, 0, 0]])
        draws = []
        for ordering in itertools.permutations(range(len(z))):
            permutation = np.array(ordering)
            actual = _conditional_lag(csr_matrix(weights), z, permutation)
            expected = []
            for focal in range(len(z)):
                fixed = permutation.copy()
                location = int(np.where(fixed == focal)[0][0])
                fixed[focal], fixed[location] = fixed[location], fixed[focal]
                expected.append(weights[focal] @ z[fixed])
                self.assertNotIn(focal, fixed[np.flatnonzero(weights[focal])])
            np.testing.assert_allclose(actual, expected, atol=1e-12)
            draws.append(z * actual)
        np.testing.assert_allclose(np.mean(draws, axis=0), -z*z/(len(z)-1), atol=1e-12)

    def test_isolated_cell_has_zero_lag(self):
        import numpy as np
        from scipy.sparse import csr_matrix
        from spatialmind.tools.spatial_statistics import _conditional_lag
        np.testing.assert_equal(_conditional_lag(csr_matrix((3, 3)), np.array([-1., 0., 1.]),
                                                np.array([2, 0, 1])), np.zeros(3))


class ReplayRepairs(unittest.TestCase):
    def test_replay_uses_dataset_identity_not_sorted_sidecar_order(self):
        with tempfile.TemporaryDirectory() as temp:
            dataset = Path(temp) / "z_dataset"
            sidecar = Path(temp) / "a_labels.csv"
            dataset.write_text("fixture")
            sidecar.write_text("fixture")
            record = StorageLayer(temp).write_mvp_run_record(
                query="test", tool_trace=[], input_files=[str(dataset), str(sidecar)],
                params={"workflow_type": "validated_xenium_pilot", "dataset_path": str(dataset)})
            self.assertEqual(replay_run_record(record.run_record_path, verify_only=False)["dataset_path"],
                             str(dataset))

    def test_all_pilot_configuration_is_preserved_including_zero_and_false(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input"
            source.write_text("fixture")
            params = {"workflow_type": "validated_xenium_pilot", "max_records": 0,
                      "min_label_coverage": 0.0, "min_region_coverage": 0.0,
                      "allow_single_region": True, "require_complete_section": False,
                      "review_max_records": 0, "report_format": "both",
                      "acknowledge_low_coverage": True, "review_artifacts": False}
            record = StorageLayer(temp).write_mvp_run_record(
                query="fixture", tool_trace=[], params=params, input_files=[str(source)])
            actual = replay_run_record(record.run_record_path, verify_only=False)["params"]
            self.assertEqual(actual, {k: v for k, v in params.items() if k != "workflow_type"})

    def test_cli_inherits_format_and_safety_flags(self):
        from scripts import replay_run
        result = {"status": "verified_replay_ready", "dataset_path": "fixture", "query": "test",
                  "replay_output_dir": "unused", "params": {
                      "max_records": 0, "min_label_coverage": 0., "min_region_coverage": 0.,
                      "allow_single_region": True, "require_complete_section": False,
                      "review_max_records": 0, "report_format": "both",
                      "acknowledge_low_coverage": True, "review_artifacts": False}}
        with patch("sys.argv", ["replay_run.py", "fixture.json", "--replay"]), \
             patch.object(replay_run, "replay_run_record", return_value=result), \
             patch("spatialmind.pilot.run_pilot", return_value={}) as pilot, patch("builtins.print"):
            replay_run.main()
        self.assertEqual(pilot.call_args.kwargs["report_format"], "both")
        self.assertTrue(pilot.call_args.kwargs["acknowledge_low_coverage"])
        self.assertFalse(pilot.call_args.kwargs["review_artifacts"])


class InstallationRepairs(unittest.TestCase):
    def test_standard_install_uses_the_shared_constraints(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn("-c packaging/constraints.txt", (root / "requirements.txt").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
