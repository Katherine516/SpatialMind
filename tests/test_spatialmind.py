import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eval.runner import EvalRunner
from spatialmind.agent import SpatialMindAgent
from spatialmind.agent_loop import SpatialAgent
from spatialmind.datasets import discover_dataset_candidates, inspect_dataset
from spatialmind.governance import build_dataset_governance_manifest
from spatialmind.ingestion import (
    BatchIngestionConfig,
    BatchIngestionPipeline,
    DataFormat,
    DataIngestionLayer,
    DataIngestionPipeline,
    IngestionConfig,
    SampleConfig,
    UnsupportedRawDataError,
    load_scatac,
    load_scrna,
    infer_data_type,
    summarize_supported_raw_data_types,
    build_readiness_report,
    apply_external_label_table,
    apply_external_region_table,
    build_xenium_label_intake_report,
    LabelApplicationReport,
    RegionApplicationReport,
    summarize_xenium_expert_readiness,
    validate_cell_by_feature_contract,
    write_expert_label_template,
    write_region_label_template,
    XeniumExpertReadiness,
)
from spatialmind.llm import StaticLLMProvider
from spatialmind.memory import LongTermMemory, SessionMemory
from spatialmind.memory import PriorType, UserPriorStore
from spatialmind.agent import build_xenium_mvp_plan, validate_tool_plan
from spatialmind.planner import LLMReasoningLayer
from spatialmind.promotion.local import build_local_promotion_report
from spatialmind.viz import QCReportBuilder, VisualizationLayer, VizRouter
from spatialmind.storage import StorageLayer
from spatialmind.storage import index_run_records, verify_run_record
from spatialmind.tools import MVP_TOOL_NAMES, build_default_registry, build_mvp_registry
from spatialmind.tools.exceptions import MissingPreconditionError
from spatialmind.tools.fusion import ModalityFuser
from spatialmind.tools.implementations import feature_overlay, marker_detection, reference_label_transfer
from spatialmind.workflows import INTEGRATION_MODE, SCATAC_STANDALONE, SCRNA_STANDALONE, XENIUM_STANDALONE
from spatialmind.contracts import BiologicalClaim, CellByFeatureContract, CoreSpatialObject, ground_claim
from spatialmind.schemas import SpatialDataset, SpotRecord
from spatialmind.pilot import build_pilot_claim_ledger, pilot_gate


ROOT = os.path.dirname(os.path.dirname(__file__))
DEMO = os.path.join(ROOT, "data", "demo_spatial.csv")
MANIFEST = os.path.join(ROOT, "data", "demo_manifest.json")
XENIUM_LYMPH = os.path.join(ROOT, "data", "Xenium lymph", "Xenium_V1_hLymphNode_nondiseased_section_outs")


class PlannerTests(unittest.TestCase):
    def test_plans_colocalization_request(self):
        plan = LLMReasoningLayer().plan(
            "Show CD8+ T cells relative to tumor cells in sample BRCA_04 and test co-localization."
        )
        self.assertEqual(plan.request.sample_id, "BRCA_04")
        self.assertIn("CD8+ T cell", plan.request.cell_types)
        self.assertIn("Tumor cell", plan.request.cell_types)
        self.assertIn("cell_type_colocalization", [step.tool for step in plan.steps])

    def test_accepts_valid_llm_plan(self):
        provider = StaticLLMProvider(
            {
                "sample_id": "BRCA_04",
                "cell_types": ["CD8+ T cell", "Tumor cell"],
                "genes": [],
                "wants_visualization": True,
                "wants_colocalization": True,
                "steps": [
                    {
                        "name": "LLM co-localization",
                        "tool": "cell_type_colocalization",
                        "parameters": {"cell_types": ["CD8+ T cell", "Tumor cell"]},
                    }
                ],
            }
        )
        plan = LLMReasoningLayer(llm_provider=provider).plan("Check sample BRCA_04")
        self.assertEqual(plan.steps[0].name, "LLM co-localization")
        self.assertEqual(plan.steps[0].tool, "cell_type_colocalization")


class IngestionTests(unittest.TestCase):
    def test_loads_and_normalizes_demo_data(self):
        dataset = DataIngestionLayer().load_csv(DEMO, sample_id="BRCA_04")
        self.assertEqual(dataset.sample_id, "BRCA_04")
        self.assertTrue(dataset.normalized)
        self.assertIn("CD8A", dataset.genes)
        self.assertIn("Tumor cell", dataset.cell_types)
        self.assertEqual(dataset.qc_metrics["record_count"], 20)
        self.assertIn("Applied library-size normalization", " ".join(dataset.processing_steps))

    def test_loads_manifest_with_source_metadata(self):
        dataset = DataIngestionLayer().load(MANIFEST, sample_id="BRCA_04")
        self.assertEqual(dataset.sample_id, "BRCA_04")
        self.assertEqual(dataset.source_path, MANIFEST)
        self.assertEqual(len(dataset.sources), 2)
        self.assertIn("project", dataset.metadata)
        self.assertTrue(any(source.data_type == "pathology_image" for source in dataset.sources))

    def test_summarizes_supported_raw_types(self):
        summaries = summarize_supported_raw_data_types()
        self.assertTrue(any(item["data_type"] == "h5ad_anndata" for item in summaries))
        self.assertEqual(infer_data_type("example.h5ad"), "h5ad_anndata")

    def test_unsupported_raw_type_has_guidance(self):
        real_import = __import__

        def block_anndata(name, *args, **kwargs):
            if name == "anndata":
                raise ImportError("anndata intentionally unavailable for this test")
            return real_import(name, *args, **kwargs)

        with self.assertRaises(UnsupportedRawDataError) as error:
            with patch("builtins.__import__", side_effect=block_anndata):
                DataIngestionLayer().load("sample.h5ad")
        self.assertIn("requires anndata", str(error.exception))

    def test_loads_xenium_directory_metadata(self):
        dataset = DataIngestionLayer().load_xenium_directory(XENIUM_LYMPH, max_records=10)
        self.assertEqual(dataset.modality, "spatial_transcriptomics")
        self.assertEqual(len(dataset.records), 10)
        self.assertIn("TRANSCRIPT_COUNTS", dataset.genes)
        self.assertTrue(dataset.metadata["xenium_files"]["cell_feature_matrix_h5"])
        self.assertTrue(dataset.metadata["xenium_files"]["experiment_xenium"])
        self.assertIn("xenium_explorer_assets", dataset.metadata)
        self.assertIn("gene_matrix", dataset.metadata)
        self.assertEqual(dataset.metadata["gene_matrix"]["loader"], "h5py_10x_csc_v1")

    def test_loads_xenium_experiment_file_entrypoint(self):
        experiment_path = os.path.join(XENIUM_LYMPH, "experiment.xenium")
        self.assertEqual(infer_data_type(experiment_path), "xenium_experiment_file")
        dataset = DataIngestionLayer().load(experiment_path)
        self.assertEqual(dataset.modality, "spatial_transcriptomics")
        self.assertEqual(len(dataset.records), 5000)
        self.assertEqual(dataset.source_path, experiment_path)
        self.assertEqual(dataset.sources[0].data_type, "xenium_experiment_file")
        self.assertTrue(dataset.metadata["xenium_files"]["experiment_xenium"])
        self.assertTrue(dataset.metadata["xenium_explorer_assets"]["analysis_summary_filepath"]["exists"])

    def test_discovers_and_inspects_xenium_datasets(self):
        candidates = discover_dataset_candidates(os.path.join(ROOT, "data"))
        self.assertIn(XENIUM_LYMPH, candidates)
        inspection = inspect_dataset(XENIUM_LYMPH)
        self.assertTrue(inspection.usable)
        self.assertEqual(inspection.readiness, "partially_ready")
        self.assertIn("spatial_scatter", inspection.supported_workflows)
        self.assertTrue(any("cell_feature_matrix.h5" in blocker for blocker in inspection.blockers))

    def test_pipeline_returns_report(self):
        dataset, report = DataIngestionPipeline().ingest(
            Path(DEMO),
            IngestionConfig(format=DataFormat.TIDY_CSV, sample_id="BRCA_04", min_counts=0),
        )
        self.assertEqual(dataset.sample_id, "BRCA_04")
        self.assertEqual(report.format_detected, DataFormat.TIDY_CSV)
        self.assertEqual(report.errors, [])

    def test_batch_ingestion_pipeline_harmonizes_gene_space(self):
        datasets, report = BatchIngestionPipeline().ingest_batch(
            BatchIngestionConfig(
                samples=[
                    SampleConfig(path=Path(DEMO), sample_id="BRCA_04", format=DataFormat.TIDY_CSV),
                    SampleConfig(path=Path(DEMO), sample_id="BRCA_04", format=DataFormat.TIDY_CSV),
                ]
            )
        )
        self.assertEqual(len(datasets), 2)
        self.assertGreater(report.harmonized_gene_count, 0)

    def test_readiness_report_blocks_label_dependent_workflow_without_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "unannotated.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("sample_id,x,y,cell_type,CD8A,EPCAM\n")
                for index in range(10):
                    handle.write("S1,%s,%s,Unannotated,%s,%s\n" % (index, index + 1, index + 2, index + 3))
            dataset = DataIngestionLayer().load_csv(path, sample_id="S1")
            report = build_readiness_report(dataset)
            self.assertEqual(report.workflow_status("spatial_visualization").status, "ready")
            self.assertEqual(report.workflow_status("neighborhood_enrichment").status, "blocked")

    def test_mvp_loaders_set_cell_by_feature_subtypes(self):
        scrna = load_scrna(DEMO, sample_id="BRCA_04")
        scatac = load_scatac(DEMO, sample_id="BRCA_04")
        self.assertEqual(validate_cell_by_feature_contract(scrna).assay_subtype, "scrna")
        scatac_contract = validate_cell_by_feature_contract(scatac)
        self.assertEqual(scatac_contract.assay_subtype, "scatac_gene_activity")
        self.assertEqual(scatac_contract.feature_type, "gene_activity")

    def test_external_label_table_overrides_loaded_cell_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "cells.csv")
            with open(data_path, "w", encoding="utf-8") as handle:
                handle.write("sample_id,cell_id,x,y,cell_type,CD8A\n")
                handle.write("S1,c1,1,2,Unannotated,3\n")
                handle.write("S1,c2,2,3,Unannotated,4\n")
            label_path = os.path.join(tmp, "expert_cell_labels.csv")
            with open(label_path, "w", encoding="utf-8") as handle:
                handle.write("cell_id,expert_label,confidence\n")
                handle.write("c1,T cell,0.91\n")
                handle.write("c2,Tumor cell,0.87\n")
            dataset = DataIngestionLayer().load_csv(data_path, sample_id="S1")
            report = apply_external_label_table(dataset, label_path)
            self.assertEqual(report.status, "expert_labels_applied")
            self.assertEqual(report.matched_cells, 2)
            self.assertEqual(sorted(dataset.cell_types), ["T cell", "Tumor cell"])
            self.assertEqual(dataset.metadata["annotation_strategy"], "expert_label_table")

    def test_external_region_table_applies_user_regions(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "cells.csv")
            with open(data_path, "w", encoding="utf-8") as handle:
                handle.write("sample_id,cell_id,x,y,cell_type,CD8A\n")
                handle.write("S1,c1,1,2,T cell,3\n")
                handle.write("S1,c2,2,3,Tumor cell,4\n")
            region_path = os.path.join(tmp, "cell_regions.csv")
            with open(region_path, "w", encoding="utf-8") as handle:
                handle.write("cell_id,region,region_confidence\n")
                handle.write("c1,stroma,0.8\n")
                handle.write("c2,tumor_core,0.9\n")
            dataset = DataIngestionLayer().load_csv(data_path, sample_id="S1")
            report = apply_external_region_table(dataset, region_path)
            self.assertEqual(report.status, "user_regions_applied")
            self.assertEqual(report.matched_cells, 2)
            self.assertEqual(sorted({record.region for record in dataset.records}), ["stroma", "tumor_core"])
            self.assertEqual(dataset.metadata["region_label_source"], "user_provided")

    def test_xenium_expert_readiness_reports_missing_labels_but_existing_clusters(self):
        readiness = summarize_xenium_expert_readiness(XENIUM_LYMPH)
        self.assertTrue(readiness.has_cell_table)
        self.assertTrue(readiness.has_feature_matrix)
        self.assertTrue(readiness.has_10x_analysis_clusters)
        self.assertIn("gene_expression_graphclust", readiness.cluster_methods)
        self.assertFalse(readiness.external_label_tables)
        self.assertTrue(any("Expert cell label table" in item for item in readiness.needs))

    def test_expert_label_template_includes_cluster_and_marker_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "cells.csv")
            with open(data_path, "w", encoding="utf-8") as handle:
                handle.write("sample_id,cell_id,x,y,cell_type,CD8A,EPCAM\n")
                handle.write("S1,c1,1,2,Unannotated,3,4\n")
            cluster_dir = os.path.join(tmp, "analysis", "clustering", "gene_expression_graphclust")
            os.makedirs(cluster_dir)
            with open(os.path.join(cluster_dir, "clusters.csv"), "w", encoding="utf-8") as handle:
                handle.write("Barcode,Cluster\n")
                handle.write("c1,7\n")
            dataset = DataIngestionLayer().load_csv(data_path, sample_id="S1")
            template = write_expert_label_template(dataset, os.path.join(tmp, "expert_label_template.csv"), dataset_path=tmp)
            with open(template, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("graph_cluster", content)
            self.assertIn("marker_evidence", content)
            self.assertIn(",7,", content)
            self.assertIn("CD8A=", content)

    def test_region_label_template_includes_region_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "cells.csv")
            with open(data_path, "w", encoding="utf-8") as handle:
                handle.write("sample_id,cell_id,x,y,cell_type,region,CD8A\n")
                handle.write("S1,c1,1,2,T cell,old_region,3\n")
            dataset = DataIngestionLayer().load_csv(data_path, sample_id="S1")
            template = write_region_label_template(dataset, os.path.join(tmp, "region_label_template.csv"), dataset_path=tmp)
            with open(template, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("current_region", content)
            self.assertIn("region_confidence", content)
            self.assertIn("old_region", content)

    def test_xenium_label_intake_report_passes_validated_inputs(self):
        dataset = SpatialDataset(
            sample_id="X1",
            source_path="xenium",
            modality="xenium_spatial_rna",
            records=[
                SpotRecord("X1", 0.0, 0.0, "T cell", {"CD8A": 1.0}, region="stroma", cell_id="c1"),
                SpotRecord("X1", 1.0, 1.0, "Tumor cell", {"EPCAM": 1.0}, region="tumor_core", cell_id="c2"),
            ],
        )
        report = build_xenium_label_intake_report(
            dataset=dataset,
            dataset_path="xenium",
            label_report=LabelApplicationReport(
                status="expert_labels_applied",
                method="expert_label_table",
                source_path="expert_cell_labels.csv",
                matched_cells=2,
                total_records=2,
                label_counts={"T cell": 1, "Tumor cell": 1},
                confidence_summary={"mean": 0.9},
            ),
            region_report=RegionApplicationReport(
                status="user_regions_applied",
                method="user_region_table",
                source_path="cell_regions.csv",
                matched_cells=2,
                total_records=2,
                region_counts={"stroma": 1, "tumor_core": 1},
                confidence_summary={"mean": 0.9},
            ),
            asset_readiness=XeniumExpertReadiness(
                dataset_path="xenium",
                has_cell_table=True,
                has_feature_matrix=True,
                has_morphology=True,
                has_boundaries=True,
                has_10x_analysis_clusters=True,
                cluster_methods=["gene_expression_graphclust"],
                external_label_tables=["expert_cell_labels.csv"],
                external_region_tables=["cell_regions.csv"],
                ready_for_expert_label_mvp=True,
                ready_for_region_summary_mvp=True,
            ),
        )
        self.assertEqual(report.status, "validated_ready")
        self.assertTrue(report.ready_for_validated_pilot)
        self.assertEqual(report.label_coverage, 1.0)
        self.assertEqual(report.region_coverage, 1.0)

    def test_xenium_label_intake_report_blocks_missing_inputs(self):
        dataset = SpatialDataset(
            sample_id="X1",
            source_path="xenium",
            modality="xenium_spatial_rna",
            records=[SpotRecord("X1", 0.0, 0.0, "Unannotated cell", {"CD8A": 1.0}, cell_id="c1")],
        )
        report = build_xenium_label_intake_report(
            dataset=dataset,
            dataset_path="xenium",
            label_report=LabelApplicationReport(status="missing_expert_labels", method="none", total_records=1),
            region_report=RegionApplicationReport(status="missing_user_regions", method="none", total_records=1),
            asset_readiness=XeniumExpertReadiness(
                dataset_path="xenium",
                has_cell_table=True,
                has_feature_matrix=True,
                has_morphology=True,
                has_boundaries=True,
                has_10x_analysis_clusters=True,
                cluster_methods=[],
                external_label_tables=[],
                external_region_tables=[],
                ready_for_expert_label_mvp=False,
                ready_for_region_summary_mvp=False,
            ),
        )
        self.assertEqual(report.status, "blocked_label_intake")
        self.assertFalse(report.ready_for_validated_pilot)
        self.assertTrue(any("Expert cell labels" in item for item in report.blockers))
        self.assertTrue(any("User-provided region labels" in item for item in report.blockers))


class ToolRegistryTests(unittest.TestCase):
    def test_default_registry_keeps_full_scaffold_and_anthropic_schema(self):
        registry = build_default_registry()
        self.assertGreaterEqual(len(registry.list_all()), 22)
        anthropic_tools = registry.to_anthropic_tools()
        self.assertTrue(any(tool["name"] == "neighborhood_enrichment" for tool in anthropic_tools))
        self.assertTrue(any(tool["name"] == "cnv_inference" for tool in anthropic_tools))

    def test_registry_exposes_resource_profiles_and_method_citations(self):
        registry = build_default_registry()
        tool = registry.get("neighborhood_enrichment")
        self.assertEqual(tool.resource_profile.runtime, "medium")
        self.assertIn("Squidpy", tool.citation.method_name)

    def test_mvp_registry_exposes_only_v7_named_tools(self):
        registry = build_mvp_registry()
        names = [tool.name for tool in registry.list_all()]
        self.assertEqual(sorted(names), sorted(MVP_TOOL_NAMES))
        self.assertEqual(
            sorted(names),
            sorted(
                [
                    "qc_and_cluster",
                    "annotation",
                    "marker_detection",
                    "feature_overlay",
                    "region_summary",
                    "cell_neighborhood_enrichment",
                ]
            ),
        )
        self.assertNotIn("differential_expression", names)
        self.assertNotIn("trajectory_inference", names)
        self.assertNotIn("motif_tf_activity", names)
        self.assertNotIn("reference_label_transfer", names)
        self.assertNotIn("cnv_inference", names)
        self.assertNotIn("ligand_receptor_analysis", names)

    def test_mvp_tool_results_include_v7_quality_metrics(self):
        dataset = DataIngestionLayer().load_csv(DEMO, sample_id="BRCA_04")
        result = build_mvp_registry().get("marker_detection").run(
            dataset,
            {"group_key": "cell_type", "group1": "CD8+ T cell", "group2": "Tumor cell"},
        )
        self.assertIsNotNone(result.quality_metrics)
        self.assertEqual(result.quality_metrics.differential.n_significant.role, "statistical_evidence")
        self.assertIn("quality_metrics", result.metrics)

    def test_mvp_honesty_tools_caveat_panel_and_transfer(self):
        dataset = DataIngestionLayer().load_csv(DEMO, sample_id="BRCA_04")
        dataset.metadata["is_targeted_panel"] = True
        dataset.metadata["feature_type"] = "targeted_panel"
        result = feature_overlay(dataset, {"feature": "NOT_IN_PANEL"})
        self.assertEqual(result.metrics["status"], "panel_absent")
        self.assertIn("not measured", result.label_caveat)
        with self.assertRaises(MissingPreconditionError):
            reference_label_transfer(dataset, {"reference_features": ["A"], "min_shared_features": 5})


class WorkflowTests(unittest.TestCase):
    def test_v7_workflow_compositions_match_mvp_plan(self):
        self.assertEqual(SCRNA_STANDALONE.name, "SCRNA_LITE")
        self.assertEqual(SCRNA_STANDALONE.steps, ["qc_and_cluster", "marker_detection"])
        self.assertEqual(SCATAC_STANDALONE.name, "SCATAC_LITE")
        self.assertEqual(SCATAC_STANDALONE.steps, ["qc_and_cluster", "marker_detection"])
        self.assertEqual(XENIUM_STANDALONE.name, "XENIUM_PRIMARY")
        self.assertEqual(
            XENIUM_STANDALONE.steps,
            ["qc_and_cluster", "annotation", "region_summary", "cell_neighborhood_enrichment"],
        )
        self.assertEqual(INTEGRATION_MODE.name, "REFERENCE_ASSIST")
        self.assertEqual(INTEGRATION_MODE.steps, ["qc_and_cluster", "marker_detection", "annotation"])

    def test_v7_region_summary_requires_user_regions(self):
        dataset = DataIngestionLayer().load_csv(DEMO, sample_id="BRCA_04")
        dataset.metadata["region_label_source"] = "user_provided"
        result = build_mvp_registry().get("region_summary").run(dataset, {"top_n_features": 3})
        self.assertEqual(result.tool_name, "region_summary")
        self.assertIn("region_count", result.metrics)
        self.assertIsNotNone(result.quality_metrics)


class ValidatedPilotTests(unittest.TestCase):
    def test_v11_xenium_tool_plan_validates_dependencies(self):
        plan = build_xenium_mvp_plan()
        valid = validate_tool_plan(
            plan,
            available_inputs=["normalized_counts", "spatial_coords", "targeted_panel", "segmentation", "expert_labels", "user_regions"],
            registry_tool_names=MVP_TOOL_NAMES,
        )
        self.assertTrue(valid.ok)
        invalid = validate_tool_plan(
            [plan[1], plan[0]],
            available_inputs=["normalized_counts", "spatial_coords", "expert_labels", "user_regions"],
            registry_tool_names=MVP_TOOL_NAMES,
        )
        self.assertFalse(invalid.ok)
        self.assertIn("missing required outputs", invalid.errors[0])

    def test_pilot_gate_blocks_without_expert_labels_and_regions(self):
        dataset = SpatialDataset(
            sample_id="X1",
            source_path="xenium",
            modality="xenium_spatial_rna",
            records=[
                SpotRecord("X1", 0.0, 0.0, "T cell", {"CD8A": 1.0}, cell_id="c1"),
                SpotRecord("X1", 1.0, 1.0, "Tumor cell", {"EPCAM": 1.0}, cell_id="c2"),
            ],
        )
        gate = pilot_gate(
            dataset=dataset,
            asset_readiness={
                "has_cell_table": True,
                "has_feature_matrix": True,
                "has_morphology": True,
                "has_boundaries": True,
            },
            label_report={"status": "missing_expert_labels", "matched_cells": 0, "total_records": 2},
            region_report={"status": "missing_user_regions", "matched_cells": 0, "total_records": 2},
            min_label_coverage=0.7,
            min_region_coverage=0.7,
            allow_single_region=False,
        )
        self.assertEqual(gate["status"], "blocked_missing_validation_inputs")
        self.assertTrue(any("Expert cell labels" in item for item in gate["blocking_reasons"]))
        self.assertTrue(any("region labels" in item for item in gate["blocking_reasons"]))

    def test_pilot_gate_passes_with_validated_inputs(self):
        dataset = SpatialDataset(
            sample_id="X1",
            source_path="xenium",
            modality="xenium_spatial_rna",
            records=[
                SpotRecord("X1", 0.0, 0.0, "T cell", {"CD8A": 1.0}, region="stroma", cell_id="c1"),
                SpotRecord("X1", 1.0, 1.0, "Tumor cell", {"EPCAM": 1.0}, region="tumor_core", cell_id="c2"),
            ],
        )
        gate = pilot_gate(
            dataset=dataset,
            asset_readiness={
                "has_cell_table": True,
                "has_feature_matrix": True,
                "has_morphology": True,
                "has_boundaries": True,
            },
            label_report={"status": "expert_labels_applied", "matched_cells": 2, "total_records": 2},
            region_report={"status": "user_regions_applied", "matched_cells": 2, "total_records": 2},
            min_label_coverage=0.7,
            min_region_coverage=0.7,
            allow_single_region=False,
        )
        self.assertEqual(gate["status"], "validated_ready")
        self.assertEqual(gate["blocking_reasons"], [])

    def test_blocked_pilot_claim_ledger_refuses_biology(self):
        payload = {
            "status": "blocked_missing_validation_inputs",
            "required_next_inputs": ["Add expert_cell_labels.csv", "Add cell_regions.csv"],
            "asset_readiness": {"has_cell_table": True},
            "contract": {"assay_subtype": "xenium_spatial_rna"},
        }
        ledger = build_pilot_claim_ledger(payload, [])
        self.assertEqual(ledger[0]["status"], "refused")
        self.assertEqual(ledger[0]["allowed_wording"], "")
        self.assertIn("expert", " ".join(ledger[0]["missing_inputs"]).lower())

    def test_local_promotion_report_summarizes_available_gap_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = os.path.join(tmp, "data")
            os.makedirs(data_root)
            demo_path = os.path.join(data_root, "demo.csv")
            with open(demo_path, "w", encoding="utf-8") as handle:
                handle.write("sample_id,x,y,cell_type,CD8A\n")
                handle.write("S1,1,2,T cell,3\n")
            report = build_local_promotion_report(data_root, os.path.join(tmp, "promotion"), max_records=10)
            self.assertEqual(report["xenium_dataset_count"], 0)
            statuses = {item["name"]: item["status"] for item in report["gap_status"]}
            self.assertEqual(statuses["Xenium raw data ingestion"], "missing")
            self.assertIn("LLM API planner", statuses)
            self.assertTrue(os.path.exists(os.path.join(tmp, "promotion", "local_promotion_report.md")))


class SpatialAgentTests(unittest.TestCase):
    def test_agent_returns_tool_trace(self):
        response = SpatialAgent().run("Are CD8+ T cells near tumor cells?", MANIFEST)
        self.assertFalse(response.clarification_needed)
        self.assertIn("cell_type_annotation", [call.tool_name for call in response.tool_trace])
        self.assertIn("neighborhood_enrichment", [call.tool_name for call in response.tool_trace])

    def test_agent_detects_ambiguity(self):
        response = SpatialAgent().run("Analyze this", MANIFEST)
        self.assertTrue(response.clarification_needed)
        self.assertEqual(response.tool_trace, [])

    def test_agent_refuses_blocked_readiness_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "unannotated.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("sample_id,x,y,cell_type,CD8A,EPCAM\n")
                for index in range(10):
                    handle.write("S1,%s,%s,Unannotated,%s,%s\n" % (index, index + 1, index + 2, index + 3))
            response = SpatialAgent().run("Are T cells near tumor cells?", path)
            self.assertIsNotNone(response.no_analysis_response)
            self.assertEqual(response.tool_trace, [])
            self.assertIn("cell-type annotation", response.no_analysis_response.recommended_next_step.lower())

    def test_mvp_agent_refuses_deferred_v1_workflow(self):
        response = SpatialAgent(mvp_mode=True).run("Run deconvolution on this dataset", MANIFEST)
        self.assertIsNotNone(response.no_analysis_response)
        self.assertEqual(response.tool_trace, [])
        self.assertIn("deferred", response.no_analysis_response.blocking_reasons[0])


class ContractTests(unittest.TestCase):
    def test_contracts_are_importable_and_claim_grounding_softens_unsupported_claims(self):
        core = CoreSpatialObject(sample_id="S1", modality="transcriptomics", qc_passed=True)
        self.assertEqual(core.sample_id, "S1")
        claim = BiologicalClaim(
            claim_text="CD8 T cells are significantly enriched near tumor cells.",
            claim_type="spatial_colocalization",
        )
        grounded = ground_claim(claim, available_evidence=["figure"])
        self.assertIn("no valid neighborhood test", grounded.allowed_wording)

    def test_cell_by_feature_contract_requires_xenium_coordinates(self):
        contract = CellByFeatureContract(
            sample_id="X1",
            modality="transcriptomics",
            assay_subtype="xenium_spatial_rna",
            feature_type="targeted_panel",
            n_features=10,
            is_targeted_panel=True,
            resolution="subcellular",
            qc_passed=True,
        )
        with self.assertRaises(Exception):
            contract.validate()


class MemoryTests(unittest.TestCase):
    def test_session_and_long_term_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_memory = SessionMemory(root=os.path.join(tmp, "sessions"))
            context = session_memory.append_message("s1", MANIFEST, "user", "Show T cells")
            self.assertEqual(context.session_id, "s1")
            self.assertEqual(len(session_memory.get("s1").conversation_history), 1)

            long_term = LongTermMemory(root=tmp)
            long_term.store(MANIFEST, "Show tumor cells", ["cell_type_annotation"], "Tumor cells were present.", "run/report.html")
            self.assertEqual(len(long_term.search("tumor", dataset_id=MANIFEST)), 1)

            priors = UserPriorStore(root=tmp)
            priors.upsert("u1", PriorType.CELL_TYPE_ALIAS, "CD8+", "Use CD8A and CD8B markers.")
            self.assertEqual(len(priors.search("u1", "CD8 marker")), 1)


class V2ScaffoldTests(unittest.TestCase):
    def test_qc_report_builder_viz_router_and_fusion_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, report = DataIngestionPipeline().ingest(
                Path(DEMO),
                IngestionConfig(format=DataFormat.TIDY_CSV, sample_id="BRCA_04", min_counts=0),
            )
            qc_path = QCReportBuilder().build(dataset, report, tmp)
            self.assertTrue(os.path.exists(qc_path))
            with open(qc_path, encoding="utf-8") as handle:
                qc_content = handle.read()
            self.assertIn("Metric Distributions", qc_content)
            self.assertIn("Spatial QC Overlay", qc_content)
            self.assertIn("Filtration Waterfall", qc_content)
            self.assertEqual(VizRouter().choose("differential_expression", dataset.modality).name, "spatial_scatter")
            self.assertEqual(VizRouter().choose("marker_detection", dataset.modality).name, "spatial_scatter")
            self.assertEqual(VizRouter().choose("region_summary", "spatial_transcriptomics").name, "region_summary_plot")
            fused = ModalityFuser().fuse([("visium", dataset)])
            self.assertIn("visium", fused.modalities_present)

    def test_cluster_style_spatial_svg_has_axes_and_legend(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = DataIngestionLayer().load_csv(DEMO, sample_id="BRCA_04")
            svg_path = VisualizationLayer().render_distribution_svg(dataset, tmp, [])
            with open(svg_path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn(">Cluster<", content)
            self.assertIn(">spatial1<", content)
            self.assertIn(">spatial2<", content)
            self.assertIn("Tumor cell", content)


class EvalHarnessTests(unittest.TestCase):
    def test_eval_runner_loads_cases_and_scores(self):
        runner = EvalRunner(SpatialAgent())
        cases = runner.load_cases(os.path.join(ROOT, "eval", "test_cases"))
        self.assertEqual(len(cases), 15)
        report = runner.run(cases[:2])
        self.assertEqual(report["summary"]["case_count"], 2)
        self.assertGreaterEqual(report["summary"]["mean_score"], 0.5)


class AgentTests(unittest.TestCase):
    def test_agent_creates_report_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = SpatialMindAgent(output_root=os.path.join(tmp, "outputs"), memory_root=os.path.join(tmp, "memory"))
            run = agent.run(
                "Show me CD8+ T cells relative to tumor cells in sample BRCA_04 and test co-localization.",
                DEMO,
            )
            self.assertTrue(os.path.exists(run.report_path))
            self.assertTrue(os.path.exists(run.provenance_path))
            self.assertTrue(os.path.exists(os.path.join(os.path.dirname(run.report_path), "spatial_distribution_interactive.html")))
            self.assertTrue(any(result.tool_name == "cell_type_colocalization" for result in run.results))
            stored = StorageLayer(root=os.path.join(tmp, "outputs")).get_run(run.run_id)
            self.assertEqual(stored.run_id, run.run_id)
            self.assertTrue(stored.provenance_hash)
            self.assertTrue(any(path.endswith(".html") for path in StorageLayer(root=os.path.join(tmp, "outputs")).list_figures(run.run_id)))

    def test_storage_writes_mvp_run_record_with_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = os.path.join(tmp, "input.txt")
            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("input")
            record = StorageLayer(root=tmp).write_mvp_run_record(
                query="test",
                tool_trace=[],
                params={},
                input_files=[input_path],
            )
            self.assertTrue(os.path.exists(record.run_record_path))
            self.assertTrue(record.input_file_md5[input_path])
            self.assertEqual(record.artifact_paths, {})

    def test_replay_verifies_run_record_and_indexes_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = os.path.join(tmp, "input.txt")
            figure_path = os.path.join(tmp, "figure.svg")
            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("input")
            with open(figure_path, "w", encoding="utf-8") as handle:
                handle.write("<svg></svg>")
            record = StorageLayer(root=os.path.join(tmp, "outputs")).write_mvp_run_record(
                query="Validated Xenium pilot: test replay",
                tool_trace=[],
                params={"max_records": 10},
                input_files=[input_path],
                figures=[figure_path],
            )
            verification = verify_run_record(record.run_record_path)
            self.assertEqual(verification.status, "verified")
            indexed = index_run_records(os.path.join(tmp, "outputs"), os.path.join(tmp, "runs.sqlite"))
            self.assertEqual(indexed["run_records_indexed"], 1)


class GovernanceTests(unittest.TestCase):
    def test_governance_manifest_marks_local_metadata_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = os.path.join(tmp, "data")
            os.makedirs(data_root)
            csv_path = os.path.join(data_root, "demo.csv")
            with open(csv_path, "w", encoding="utf-8") as handle:
                handle.write("sample_id,x,y,cell_type,CD8A\n")
                handle.write("S1,1,2,T cell,3\n")
            out = os.path.join(tmp, "manifest.json")
            manifest = build_dataset_governance_manifest(data_root, out)
            self.assertEqual(manifest["status"], "needs_human_governance_review")
            self.assertEqual(len(manifest["records"]), 1)
            self.assertEqual(manifest["records"][0]["license"], "needs_review")
            self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
