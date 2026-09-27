"""Regression cases discovered by the September 27 adversarial audit."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from spatialmind.schemas import SpatialDataset, SpotRecord, ToolResult
from spatialmind.app import planner, plan_report
from spatialmind.app.server import make_plan_worker
from spatialmind.gatekeeper import GateBlockedError, gated_tool_names
from spatialmind.ingestion.labels import apply_external_label_table, apply_external_region_table
from spatialmind.tools import build_default_registry
from spatialmind.tools.grouping import reviewed_view
from spatialmind.tools.implementations import resolve_group_labels
from spatialmind.methods.reliability.scoring import _statistical_component, _spatial_robustness_component


def dataset():
    return SpatialDataset(sample_id="test", source_path="fixture", normalized=True,
                          records=[SpotRecord("test", i, i * 2, "A" if i < 2 else "B", {"GFAP": i + 1},
                                              region="r", cell_id=str(i)) for i in range(4)],
                          metadata={"cluster_assignments": {str(i): str(i % 2) for i in range(4)}})


def claim(direction="enrichment"):
    return {"claim_type": "spatial_colocalization", "spatial_target": {
        "tool": "cell_neighborhood_enrichment", "pair": ["A", "B"], "direction": direction}}


def statistic(pairs, count=100, target=None):
    return _statistical_component(target or claim(), [ToolResult("cell_neighborhood_enrichment", "test",
                                 metrics={"tested_pair_count": count, "top_pairs": pairs})])


class ExecutionBoundaryTests(unittest.TestCase):
    def test_executor_rejects_prototype_fallback(self):
        from spatialmind.agent.runtime import execute_tool_step
        from spatialmind.contracts import ToolCallSpec
        from spatialmind.tools.exceptions import InvalidParameterError
        with self.assertRaises(InvalidParameterError):
            execute_tool_step(dataset(), ToolCallSpec("qc_and_cluster", {"engine": "prototype"}), build_default_registry())

    def test_pairwise_cluster_markers_use_cluster_assignments(self):
        from spatialmind.tools.implementations import differential_expression
        result = differential_expression(dataset(), {"group_key": "leiden", "group1": "0", "group2": "1", "strict_engine": True})
        self.assertEqual(result.metrics["engine"], "scanpy")
        self.assertEqual(result.metrics["group_key"], "cluster")

    def test_default_marker_plan_requires_labels(self):
        specs = planner.build_plan(["marker_detection"])
        self.assertEqual([s.tool_name for s in specs], ["qc_and_cluster", "annotation", "marker_detection"])
        self.assertIn("marker_detection", gated_tool_names(["marker_detection"]))

    def test_annotation_override_never_bypasses_gate(self):
        for alias in ("cluster", "leiden", "clusters", "leiden_cluster"):
            self.assertEqual(gated_tool_names(["annotation"], {"annotation": {"group_key": alias}}), ["annotation"])

    def test_cluster_plan_has_no_annotation_dependency(self):
        for alias in ("cluster", "leiden", "clusters", "leiden_cluster"):
            override = {"marker_detection": {"group_key": alias}}
            specs = planner.build_plan(["marker_detection"], override)
            self.assertEqual([s.tool_name for s in specs], ["qc_and_cluster", "marker_detection"])
            self.assertEqual(specs[-1].params["group_key"], "cluster")
            self.assertEqual(gated_tool_names([s.tool_name for s in specs], override), [])

    def test_direct_worker_refuses_before_loading(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "experiment.xenium").write_text("{}")
            studio = SimpleNamespace(entry=lambda _: SimpleNamespace(path=root, reviewable=True),
                                     gate=lambda _: {"status": "blocked_missing_validation_inputs"})
            with patch("spatialmind.app.server.load_xenium") as load:
                with self.assertRaises(GateBlockedError):
                    make_plan_worker(studio, "x", ["marker_detection"], {}, 100)(SimpleNamespace())
                load.assert_not_called()

    def test_all_group_aliases_resolve_same_assignments(self):
        for alias in ("cluster", "leiden", "clusters", "leiden_cluster"):
            self.assertEqual(resolve_group_labels(dataset(), {"group_key": alias}), (["0", "1", "0", "1"], "cluster"))

    def test_unknown_group_is_rejected(self):
        from spatialmind.tools.exceptions import InvalidParameterError
        with self.assertRaises(InvalidParameterError):
            resolve_group_labels(dataset(), {"group_key": "typo"})

    def test_figure_legend_uses_clusters_not_provisional_names(self):
        from matplotlib.axes import Axes
        labels = []
        original = Axes.legend
        def capture(ax, *args, **kwargs):
            labels.extend(handle.get_label() for handle in kwargs.get("handles", []))
            return original(ax, *args, **kwargs)
        with tempfile.TemporaryDirectory() as root, patch.object(Axes, "legend", capture):
            figures = plan_report.write_figures(dataset(), {}, Path(root))
        self.assertEqual(len(figures), 1)
        self.assertEqual(labels, ["0", "1"])


class ReviewScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = dataset()
        labels = Path(self.temp.name, "labels.csv")
        labels.write_text("cell_id,expert_label,reviewer_id\n0,A,reviewer\n2,B,reviewer\n")
        self.report = apply_external_label_table(self.data, str(labels))

    def test_same_spelling_does_not_confer_review(self):
        labels, _ = resolve_group_labels(self.data, {})
        self.assertEqual(labels, ["A", "", "B", ""])

    def test_report_counts_only_matched_cells(self):
        self.assertEqual(self.report.label_counts, {"A": 1, "B": 1})
        self.assertEqual(self.report.matched_cells, 2)

    def test_all_biological_tools_receive_reviewed_cells_only(self):
        for name in ("annotation", "marker_detection", "cell_neighborhood_enrichment", "differential_expression"):
            tool = build_default_registry().get(name)
            with patch.object(tool, "callable", return_value=ToolResult(name, "test")) as run:
                result = tool.run(self.data, {})
            self.assertEqual([r.cell_id for r in run.call_args[0][0].records], ["0", "2"])
            self.assertEqual(result.metrics["excluded_unreviewed_cell_count"], 2)

    def test_descriptive_groups_keep_all_cells(self):
        self.assertIs(reviewed_view(self.data, "marker_detection", {"group_key": "cluster"}), self.data)

    def test_region_summary_uses_intersection_of_reviewed_cells(self):
        regions = Path(self.temp.name, "regions.csv")
        regions.write_text("cell_id,region\n0,r\n1,r\n")
        apply_external_region_table(self.data, str(regions))
        scoped = reviewed_view(self.data, "region_summary", {})
        self.assertEqual([r.cell_id for r in scoped.records], ["0"])

    def test_changed_label_does_not_keep_old_review_status(self):
        self.data.records[0].cell_type = "changed"
        self.assertEqual(resolve_group_labels(self.data, {})[0][0], "")


class ClaimBindingTests(unittest.TestCase):
    def test_nonfinite_statistic_does_not_become_full_support(self):
        for value in (float("nan"), float("inf")):
            self.assertEqual(statistic([{"pair": "A | B", "zscore": value}]).score, 0)

    def test_wrong_tool_cannot_support_claim(self):
        target = claim()
        target["spatial_target"]["tool"] = "other_tool"
        self.assertEqual(statistic([{"pair": "A | B", "zscore": 8}], target=target).score, 0)

    def test_pilot_emits_bound_pair_claims(self):
        from spatialmind.pilot.claims import build_pilot_claim_ledger
        result = ToolResult("cell_neighborhood_enrichment", "test", metrics={
            "engine": "squidpy", "tested_pair_count": 3, "top_pairs": [{"pair": "A | B", "zscore": 8}]})
        ledger = build_pilot_claim_ledger({"status": "validated_ready"}, [result])
        bound = [row for row in ledger if row.get("spatial_target")]
        self.assertEqual(len(bound), 1)
        self.assertEqual(bound[0]["spatial_target"]["pair"], ["A", "B"])
        self.assertEqual(bound[0]["status"], "supported")

    def test_unrelated_pair_cannot_inflate_claim(self):
        rows = [{"pair": "A | B", "zscore": 0}, {"pair": "C | D", "zscore": 8}]
        self.assertEqual(statistic(rows).score, 0)

    def test_opposite_direction_cannot_support_enrichment(self):
        self.assertEqual(statistic([{"pair": "A | B", "zscore": -8}]).score, 0)

    def test_matching_direction_has_evidence(self):
        self.assertEqual(statistic([{"pair": "B | A", "zscore": 8}]).score, 1)

    def test_raw_p_is_adjusted_over_test_family(self):
        self.assertEqual(statistic([{"pair": "A | B", "pvalue": 0.01}], target=claim("association")).score, 0)

    def test_zero_adjusted_p_is_not_missing(self):
        self.assertEqual(statistic([{"pair": "A | B", "pval_adj": 0}], target=claim("association")).score, 1)

    def test_unbound_claim_is_blocked(self):
        result = statistic([{"pair": "A | B", "zscore": 8}], target={"claim_type": "spatial_colocalization"})
        self.assertEqual(result.status, "blocked")

    def test_scope_mismatch_has_no_support(self):
        target = claim()
        target["spatial_target"]["region"] = "tumor_core"
        self.assertEqual(statistic([{"pair": "A | B", "zscore": 8}], target=target).score, 0)

    def test_no_sweep_means_no_robustness_proxy(self):
        self.assertEqual(_spatial_robustness_component(claim(), {}, []).score, 0)

    def test_unrelated_pair_sweep_cannot_support_target(self):
        sweep = {"status": "computed", "score": 1, "pair_stability": [{"pair": "C | D", "sign_agreement": 1}]}
        self.assertEqual(_spatial_robustness_component(claim(), {"spatial_robustness": sweep}, []).score, 0)

    def test_pair_sweep_penalizes_missing_settings(self):
        sweep = {"status": "computed", "settings": [6, 10, 15], "pair_stability": [
            {"pair": "A | B", "settings_present": 2, "sign_agreement": 1, "top_k_presence": 1}]}
        self.assertAlmostEqual(_spatial_robustness_component(claim(), {"spatial_robustness": sweep}, []).score, 2/3, places=4)


class DeliveryBoundaryTests(unittest.TestCase):
    def test_studio_record_hashes_outputs_and_prepares_replay(self):
        from spatialmind.storage import StorageLayer
        from spatialmind.storage.replay import verify_run_record, replay_run_record
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "input.txt")
            source.write_text("input")
            artifact = Path(root, "report.html")
            artifact.write_text("report")
            record = StorageLayer(root).write_mvp_run_record(
                "test", [], {"workflow_type": "studio_plan"}, [str(source)], artifacts={"report": str(artifact)})
            self.assertEqual(verify_run_record(record.run_record_path).status, "verified")
            self.assertEqual(replay_run_record(record.run_record_path, verify_only=False)["status"], "verified_studio_replay_ready")
            artifact.write_text("tampered")
            self.assertEqual(verify_run_record(record.run_record_path).status, "failed")

    def test_partial_delivery_is_not_a_successful_job(self):
        from spatialmind.app.jobs import JobRunner, Job
        runner = JobRunner()
        job = Job("test", "plan", "test", "dataset", "path")
        runner._run(job, lambda _: {"delivery_status": "partial"})
        self.assertEqual(job.state, "failed")
        self.assertIsNotNone(job.result)

    def test_inventory_does_not_assert_execution_or_todays_date(self):
        from scripts.check_doc_numbers import expected_lines
        lines = expected_lines(dict(tests=1, legacy_cases=2, mvp_cases=3, contracts=4, hidden=18, registered=30, plannable=12))
        inventory = next(value for value in lines.values() if value.startswith("Inventory counts:"))
        self.assertNotIn("passed", inventory)
        self.assertNotIn("Last verified", " ".join(lines.values()))


if __name__ == "__main__":
    unittest.main()
