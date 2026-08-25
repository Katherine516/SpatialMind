import math
import os
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eval.runner import EvalRunner, _case_directory
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
from spatialmind.viz import (
    PdfSection,
    PdfTable,
    QCReportBuilder,
    VisualizationLayer,
    VizRouter,
    XeniumExplorerLiteViewer,
    normalize_report_format,
    write_pdf_report,
)
from spatialmind.storage import StorageLayer
from spatialmind.storage import index_run_records, replay_run_record, verify_run_record
from spatialmind.tools import MVP_TOOL_NAMES, build_default_registry, build_mvp_registry
from spatialmind.tools.exceptions import MissingPreconditionError
from spatialmind.tools.fusion import ModalityFuser
from spatialmind.tools.implementations import feature_overlay, marker_detection, reference_label_transfer
from spatialmind.workflows import INTEGRATION_MODE, SCATAC_STANDALONE, SCRNA_STANDALONE, XENIUM_STANDALONE
from spatialmind.contracts import BiologicalClaim, CellByFeatureContract, CoreSpatialObject, ground_claim
from spatialmind.schemas import SpatialDataset, SpotRecord, ToolResult
from spatialmind.pilot import build_pilot_claim_ledger, pilot_gate
from spatialmind.methods.reliability import build_claim_reliability_table, fit_claim_reliability_calibration
from spatialmind.review import CLAIM_TRUTH_FIELDS, validate_claim_truth_table


ROOT = os.path.dirname(os.path.dirname(__file__))
DEMO = os.path.join(ROOT, "data", "demo_spatial.csv")
MANIFEST = os.path.join(ROOT, "data", "demo_manifest.json")
XENIUM_LYMPH = os.path.join(ROOT, "data", "Xenium lymph", "Xenium_V1_hLymphNode_nondiseased_section_outs")

try:
    import scanpy  # noqa: F401

    _HAS_SCANPY = True
except Exception:  # pragma: no cover - dependency-light environments
    _HAS_SCANPY = False


def _make_two_program_dataset():
    """Two expression programs interleaved in space: expression clustering should
    recover the programs while spatial clustering would mix them."""
    records = []
    for index in range(60):
        program = "A" if index % 2 == 0 else "B"
        other = "B" if program == "A" else "A"
        genes = {}
        for gene in range(6):
            genes["%s_gene_%d" % (program, gene)] = 5.0 + float(index % 3)
            genes["%s_gene_%d" % (other, gene)] = 0.0
        # Programs alternate along x, so neighbors in space are always the other program.
        records.append(SpotRecord("S1", float(index), 0.0, program, genes, cell_id="c%d" % index))
    return SpatialDataset(
        sample_id="S1",
        source_path="synthetic",
        modality="xenium_spatial_rna",
        records=records,
    )


class PlannerTests(unittest.TestCase):
    def test_plans_colocalization_request(self):
        plan = LLMReasoningLayer().plan(
            "Show CD8+ T cells relative to tumor cells in sample BRCA_04 and test co-localization."
        )
        self.assertEqual(plan.request.sample_id, "BRCA_04")
        self.assertIn("CD8+ T cell", plan.request.cell_types)
        self.assertIn("Tumor cell", plan.request.cell_types)
        self.assertIn("cell_type_colocalization", [step.tool for step in plan.steps])

    def test_plans_plain_language_neighborhood_comparison(self):
        plan = LLMReasoningLayer().plan("Compare tumor and CD8+ T cells and assess spatial neighborhoods.")
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
        self.assertTrue(dataset.records[0].raw_genes)
        self.assertNotEqual(dataset.records[0].raw_genes, dataset.records[0].genes)
        self.assertEqual(dataset.metadata["expression_layers"]["normalization_target_sum"], 10000.0)

    def test_ingestion_sanitizes_nonfinite_features_before_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nonfinite.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("sample_id,x,y,cell_type,gene_A,gene_B\n")
                handle.write("S1,1,2,T cell,nan,4\n")
                handle.write("S1,3,4,Tumor cell,2,inf\n")
            dataset = DataIngestionLayer().load_csv(path, sample_id="S1")
            self.assertEqual(dataset.qc_metrics["nonfinite_feature_value_count"], 2)
            self.assertTrue(
                all(
                    math.isfinite(value)
                    for record in dataset.records
                    for value in record.genes.values()
                )
            )

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
        first = dataset.records[0]
        self.assertEqual(first.genes["TRANSCRIPT_COUNTS"], first.raw_genes["TRANSCRIPT_COUNTS"])
        self.assertEqual(dataset.qc_metrics["qc_expression_layer"], "raw_counts")
        self.assertEqual(dataset.metadata["analysis_scope"], "sampled")

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
        self.assertFalse(any("cell_ontology_terms" in path for path in candidates))
        inspection = inspect_dataset(XENIUM_LYMPH)
        self.assertTrue(inspection.usable)
        self.assertEqual(inspection.readiness, "partially_ready")
        self.assertIn("spatial_scatter", inspection.supported_workflows)
        self.assertFalse(any("gene matrix was not loaded" in blocker for blocker in inspection.blockers))
        self.assertTrue(any("reviewed expert" in blocker for blocker in inspection.blockers))
        self.assertTrue(inspection.metadata["dataset_metadata"]["sampling"]["fraction_loaded"] > 0)

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
        # Scaffolds stay registered for provenance, but are not advertised to a
        # planner: a model must not be able to pick a tool that does no work.
        anthropic_tools = registry.to_anthropic_tools()
        self.assertTrue(any(tool["name"] == "neighborhood_enrichment" for tool in anthropic_tools))
        self.assertFalse(any(tool["name"] == "cnv_inference" for tool in anthropic_tools))
        self.assertTrue(any(tool.name == "cnv_inference" for tool in registry.list_all()))
        self.assertTrue(
            any(tool["name"] == "cnv_inference" for tool in registry.to_anthropic_tools(plannable_only=False))
        )

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
                    "spatial_variable_genes",
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

    def test_spatial_variable_gene_results_expose_morans_i_quality_metric(self):
        from spatialmind.tools.implementations import attach_quality_metrics

        dataset = DataIngestionLayer().load_csv(DEMO, sample_id="BRCA_04")
        result = ToolResult(
            tool_name="spatial_variable_genes",
            summary="Synthetic spatial-gene result.",
            metrics={
                "engine": "squidpy",
                "n_neighs": 6,
                "top_genes": [{"gene": "AQP4", "morans_i": 0.42, "pval_adj": 0.01}],
            },
        )
        attached = attach_quality_metrics(result, dataset, {"n_neighs": 6})
        self.assertEqual(attached.quality_metrics.spatial.morans_i.status, "computed")
        self.assertEqual(attached.quality_metrics.spatial.morans_i.value, 0.42)
        self.assertEqual(attached.quality_metrics.spatial.cooccurrence_z.status, "not_applicable")

    @unittest.skipUnless(_HAS_SCANPY, "scanpy required for expression clustering path")
    def test_qc_and_cluster_defaults_to_expression_clustering_with_qc(self):
        dataset = _make_two_program_dataset()
        result = build_mvp_registry().get("qc_and_cluster").run(dataset, {})
        metrics = result.metrics
        self.assertEqual(metrics["engine"], "scanpy")
        self.assertEqual(metrics["cluster_on"], "expression")
        self.assertEqual(metrics["method"], "pca_neighbors_leiden")
        self.assertTrue(str(metrics["representation"]).startswith("X_pca"))
        # Two cleanly separated expression programs should not collapse to one cluster.
        self.assertGreaterEqual(len(metrics["cluster_counts"]), 2)
        self.assertIsNotNone(metrics["silhouette"])
        self.assertGreaterEqual(metrics["silhouette"], -1.0)
        self.assertLessEqual(metrics["silhouette"], 1.0)
        self.assertIsNotNone(metrics["modularity"])
        self.assertGreaterEqual(metrics["modularity"], -1.0)
        self.assertLessEqual(metrics["modularity"], 1.0)
        self.assertEqual(metrics["excluded_zero_feature_cell_count"], 0)
        self.assertEqual(result.quality_metrics.clustering.modularity.provenance.method, "weighted kNN graph modularity")
        qc = metrics["expression_qc"]
        self.assertEqual(qc["n_cells"], 60)
        self.assertEqual(qc["n_features"], 12)
        self.assertGreater(qc["mean_total_counts"], 0.0)
        self.assertGreater(qc["mean_features_per_cell"], 0.0)

    @unittest.skipUnless(_HAS_SCANPY, "scanpy required for expression clustering path")
    def test_expression_clustering_excludes_zero_feature_cells(self):
        dataset = _make_two_program_dataset()
        dataset.records.append(
            SpotRecord("S1", 100.0, 100.0, "Unannotated cell", {}, cell_id="zero-expression")
        )
        result = build_mvp_registry().get("qc_and_cluster").run(dataset, {})
        self.assertEqual(result.metrics["total_cell_count"], 61)
        self.assertEqual(result.metrics["analyzed_cell_count"], 60)
        self.assertEqual(result.metrics["excluded_zero_feature_cell_count"], 1)
        assignments = dataset.metadata["cluster_assignments"]
        self.assertEqual(assignments["zero-expression"], "")
        markers = build_mvp_registry().get("marker_detection").run(dataset, {"group_key": "cluster"})
        self.assertEqual(markers.metrics["excluded_unassigned_cell_count"], 1)
        self.assertNotIn("unassigned", markers.metrics["groups"])

    @unittest.skipUnless(_HAS_SCANPY, "scanpy required for expression clustering path")
    def test_qc_and_cluster_spatial_mode_is_opt_in(self):
        dataset = _make_two_program_dataset()
        result = build_mvp_registry().get("qc_and_cluster").run(dataset, {"cluster_on": "spatial"})
        self.assertEqual(result.metrics["cluster_on"], "spatial")
        self.assertEqual(result.metrics["method"], "spatial_neighbors_leiden")
        self.assertEqual(result.metrics["representation"], "spatial")

    def test_expression_matrix_excludes_qc_pseudo_features(self):
        from spatialmind.tools.implementations import EXPRESSION_EXCLUDED_FEATURES, expression_feature_names

        records = [
            SpotRecord(
                "S1",
                float(index),
                0.0,
                "A" if index % 2 == 0 else "B",
                {"CD8A": 2.0, "EPCAM": 1.0, "CELL_AREA": 500.0, "TOTAL_COUNTS": 300.0, "NUCLEUS_AREA": 90.0},
                cell_id="c%d" % index,
            )
            for index in range(6)
        ]
        dataset = SpatialDataset(sample_id="S1", source_path="synthetic", modality="xenium_spatial_rna", records=records)
        names = expression_feature_names(dataset)
        self.assertIn("CD8A", names)
        self.assertTrue(EXPRESSION_EXCLUDED_FEATURES.isdisjoint({name.upper() for name in names}))

    def test_prototype_marker_detection_ignores_qc_pseudo_features(self):
        records = [
            SpotRecord("S1", 0.0, 0.0, "A", {"CD8A": 9.0, "EPCAM": 0.0, "CELL_AREA": 800.0, "TOTAL_COUNTS": 500.0}, cell_id="a"),
            SpotRecord("S1", 1.0, 0.0, "B", {"CD8A": 0.0, "EPCAM": 8.0, "CELL_AREA": 20.0, "TOTAL_COUNTS": 15.0}, cell_id="b"),
        ]
        dataset = SpatialDataset(sample_id="S1", source_path="synthetic", modality="xenium_spatial_rna", records=records)
        result = marker_detection(dataset, {"engine": "prototype", "group_key": "cell_type", "group1": "A", "group2": "B"})
        genes = {row["gene"] for row in result.metrics["ranked_genes"]}
        self.assertIn("CD8A", genes)
        self.assertNotIn("CELL_AREA", genes)
        self.assertNotIn("TOTAL_COUNTS", genes)

    def test_neighborhood_robustness_summary_scores_stability(self):
        from spatialmind.tools.implementations import summarize_neighborhood_robustness

        def setting(n, pairs):
            return {"n_neighs": n, "engine": "squidpy", "pairs": pairs}

        stable = [
            setting(6, [{"pair": "A | B", "zscore": 5.0}, {"pair": "A | C", "zscore": -3.0}]),
            setting(10, [{"pair": "A | B", "zscore": 4.2}, {"pair": "A | C", "zscore": -2.5}]),
        ]
        stable_summary = summarize_neighborhood_robustness(stable, top_k=2)
        self.assertEqual(stable_summary["status"], "computed")
        self.assertEqual(stable_summary["mean_sign_agreement"], 1.0)
        self.assertEqual(stable_summary["score"], 1.0)
        self.assertEqual(stable_summary["pair_stability"][0]["settings_present"], 2)
        self.assertEqual(stable_summary["pair_stability"][0]["sign_agreement"], 1.0)

        flipped = [
            setting(6, [{"pair": "A | B", "zscore": 5.0}, {"pair": "A | C", "zscore": -3.0}]),
            setting(10, [{"pair": "A | B", "zscore": -4.0}, {"pair": "A | C", "zscore": 3.0}]),
        ]
        flipped_summary = summarize_neighborhood_robustness(flipped, top_k=2)
        self.assertEqual(flipped_summary["mean_sign_agreement"], 0.0)
        self.assertLess(flipped_summary["score"], stable_summary["score"])

        # Prototype settings carry no z-scores, so robustness cannot be established.
        proto = [{"n_neighs": 6, "engine": "prototype", "pairs": [{"pair": "A | B", "neighbor_count": 10}]}]
        self.assertEqual(summarize_neighborhood_robustness(proto, top_k=2)["status"], "insufficient_settings")

    def test_neighborhood_robustness_records_execution_settings(self):
        from spatialmind.tools.implementations import run_neighborhood_robustness

        def result_for(_dataset, params):
            n_neighs = int(params["n_neighs"])
            return ToolResult(
                tool_name="cell_neighborhood_enrichment",
                summary="test",
                metrics={
                    "engine": "squidpy",
                    "all_pairs": [
                        {"pair": "A | B", "zscore": 4.0 + n_neighs / 100.0},
                        {"pair": "A | C", "zscore": -3.0},
                    ],
                },
            )

        with patch("spatialmind.tools.implementations.cell_neighborhood_enrichment", side_effect=result_for):
            summary = run_neighborhood_robustness(
                _make_two_program_dataset(),
                {
                    "robustness_n_neighs": [5, 9],
                    "n_perms": 250,
                    "random_state": 17,
                    "robustness_top_k": 2,
                },
            )
        self.assertEqual(summary["status"], "computed")
        self.assertEqual(summary["requested_settings"], [5, 9])
        self.assertEqual(summary["n_perms"], 250)
        self.assertEqual(summary["random_state"], 17)
        self.assertEqual(summary["top_k"], 2)
        self.assertEqual(summary["engines"], ["squidpy"])

    def test_spatial_relationship_summary_combines_orthogonal_evidence(self):
        from spatialmind.pilot.spatial_relationships import build_spatial_relationship_summary

        records = []
        for index in range(20):
            records.append(SpotRecord("S1", float(index), 0.0, "A", {"G": 1.0}, region="core", cell_id="a%d" % index))
            records.append(SpotRecord("S1", float(index) + 0.5, 1.0, "B", {"G": 1.0}, region="core", cell_id="b%d" % index))
            records.append(SpotRecord("S1", float(index) + 100.0, 0.0, "C", {"G": 1.0}, region="margin", cell_id="c%d" % index))
        dataset = SpatialDataset(
            sample_id="S1",
            source_path="synthetic",
            modality="xenium_spatial_rna",
            coordinate_system="micron",
            records=records,
        )
        neighborhood = ToolResult(
            tool_name="cell_neighborhood_enrichment",
            summary="test",
            metrics={
                "engine": "squidpy",
                "n_neighs": 6,
                "n_perms": 250,
                "random_state": 0,
                "tested_pair_count": 2,
                "all_pairs": [
                    {"pair": "A | B", "zscore": 4.2},
                    {"pair": "A | C", "zscore": -3.1},
                ],
            },
        )
        robustness = {
            "status": "computed",
            "score": 0.84,
            "pair_stability": [
                {"pair": "A | B", "settings_present": 3, "sign_agreement": 1.0, "top_k_presence": 1.0},
                {"pair": "A | C", "settings_present": 3, "sign_agreement": 1.0, "top_k_presence": 1.0},
            ],
        }
        summary = build_spatial_relationship_summary(dataset, [neighborhood], robustness, validated=True)
        self.assertEqual(summary["status"], "computed")
        by_pair = {item["pair"]: item for item in summary["relationships"]}
        self.assertEqual(by_pair["A | B"]["evidence_status"], "stable_enriched")
        self.assertEqual(by_pair["A | C"]["evidence_status"], "stable_depleted")
        self.assertEqual(by_pair["A | B"]["region_overlap"], 1.0)
        self.assertGreater(by_pair["A | C"]["median_bidirectional_nearest_distance"], 50.0)
        self.assertIn("not evidence", summary["warnings"][0])

    def test_spatial_relationship_summary_rejects_prototype_neighbor_counts(self):
        from spatialmind.pilot.spatial_relationships import build_spatial_relationship_summary

        dataset = _make_two_program_dataset()
        result = ToolResult(
            tool_name="cell_neighborhood_enrichment",
            summary="prototype",
            metrics={"engine": "prototype", "top_pairs": [{"pair": "A | B", "neighbor_count": 20}]},
        )
        summary = build_spatial_relationship_summary(dataset, [result], {}, validated=True)
        self.assertEqual(summary["status"], "not_computed")
        self.assertIn("permutation z-scores", summary["reason"])

    def test_region_stratified_neighborhoods_track_consistency_and_skips(self):
        from spatialmind.tools.implementations import run_region_stratified_neighborhoods

        records = []
        for region, offset in (("core", 0.0), ("margin", 100.0)):
            for index in range(20):
                records.append(SpotRecord("S1", offset + index, 0.0, "A", {"G": 1.0}, region=region, cell_id="%sa%d" % (region, index)))
                records.append(SpotRecord("S1", offset + index, 1.0, "B", {"G": 1.0}, region=region, cell_id="%sb%d" % (region, index)))
        records.append(SpotRecord("S1", 300.0, 0.0, "A", {"G": 1.0}, region="tiny", cell_id="tiny"))
        dataset = SpatialDataset("S1", records, "synthetic", modality="xenium_spatial_rna")
        calls = []

        def region_result(subset, params):
            calls.append((subset.records[0].region, params))
            zscore = 4.0 if subset.records[0].region == "core" else 3.0
            return ToolResult(
                tool_name="cell_neighborhood_enrichment",
                summary="test",
                metrics={
                    "engine": "squidpy",
                    "all_pairs": [
                        {"pair": "A | B", "zscore": zscore},
                        {"pair": "A | A", "zscore": -2.0},
                        {"pair": "B | B", "zscore": 0.2},
                    ],
                },
            )

        with patch("spatialmind.tools.implementations.cell_neighborhood_enrichment", side_effect=region_result):
            summary = run_region_stratified_neighborhoods(
                dataset,
                {"min_region_cells": 40, "min_cells_per_type": 20, "n_perms": 50},
            )
        self.assertEqual(summary["status"], "computed")
        self.assertEqual(summary["tested_region_count"], 2)
        self.assertEqual(summary["skipped_region_count"], 1)
        self.assertEqual(summary["pair_consistency"][0]["pair"], "A | B")
        self.assertEqual(summary["pair_consistency"][0]["status"], "region_consistent")
        self.assertEqual(summary["pair_consistency"][0]["supported_region_count"], 2)
        weak_pair = next(item for item in summary["pair_consistency"] if item["pair"] == "B | B")
        self.assertEqual(weak_pair["status"], "weak_or_indeterminate")
        self.assertEqual(weak_pair["supported_region_count"], 0)
        self.assertTrue(all(call[1]["include_all_pairs"] for call in calls))

    def test_distance_cooccurrence_curves_use_symmetric_pair_average(self):
        import numpy as np
        from spatialmind.tools.implementations import run_distance_dependent_cooccurrence

        dataset = SpatialDataset(
            "S1",
            [
                SpotRecord("S1", float(index), 0.0, "A" if index < 20 else "B", {"G": 1.0}, cell_id="c%d" % index)
                for index in range(40)
            ],
            "synthetic",
            modality="xenium_spatial_rna",
            coordinate_system="micron",
        )
        occurrence = np.zeros((2, 2, 6), dtype=float)
        occurrence[0, 1, :] = np.array([1.2, 1.4, 1.6, 1.3, 1.1, 1.0])
        occurrence[1, 0, :] = np.array([1.0, 1.2, 1.4, 1.1, 0.9, 0.8])
        thresholds = np.arange(7, dtype=float)
        with patch("squidpy.gr.co_occurrence", autospec=True, return_value=(occurrence, thresholds)) as mocked:
            summary = run_distance_dependent_cooccurrence(
                dataset,
                pairs=["A | B"],
                params={"n_intervals": 6, "max_distance": 6.0},
            )
        self.assertEqual(summary["status"], "computed")
        self.assertEqual(summary["curve_count"], 1)
        self.assertEqual(summary["curves"][0]["peak_ratio"], 1.5)
        self.assertEqual(summary["curves"][0]["peak_distance"], 3.0)
        self.assertEqual(summary["curves"][0]["left_cell_count"], 20)
        self.assertEqual(summary["min_cells_per_type"], 20)
        self.assertEqual(mocked.call_args.kwargs.get("n_jobs"), 1)
        self.assertEqual(mocked.call_args.kwargs.get("backend"), "threading")

    def test_validated_reports_surface_spatial_robustness(self):
        from spatialmind.pilot.xenium import (
            _spatial_robustness_rows,
            _write_html_report,
            _write_markdown_report,
            _write_pilot_pdf_report,
        )

        payload = {
            "created_at": "2026-07-22T00:00:00+00:00",
            "status": "validated_ready",
            "dataset_path": "synthetic.xenium",
            "records_loaded": 20,
            "features_loaded": 10,
            "blocking_reasons": [],
            "required_next_inputs": [],
            "tool_plan": [],
            "plan_validation": {"status": "valid", "errors": []},
            "expert_label_template": "labels.csv",
            "region_label_template": "regions.csv",
            "label_report": {"status": "expert_labels_applied"},
            "region_report": {"status": "user_regions_applied"},
            "review_figures": [],
            "cell_type_counts": {"A": 10, "B": 10},
            "region_counts": {"core": 10, "margin": 10},
            "claim_ledger": [],
            "claim_reliability": [],
            "run_record_path": "run.json",
            "report_html": "report.html",
            "descriptive_analysis": {
                "status": "computed",
                "clustering_method": "pca_neighbors_leiden",
                "expression_qc": {
                    "n_cells": 20,
                    "n_features": 10,
                    "median_total_counts": 12.0,
                    "median_features_per_cell": 4.0,
                },
                "clustering_diagnostics": {
                    "analyzed_cell_count": 19,
                    "excluded_zero_feature_cell_count": 1,
                    "silhouette": 0.42,
                    "modularity": 0.61,
                },
                "cluster_counts": {"0": 10, "1": 9},
                "markers_by_cluster": {"0": ["AQP4", "GJA1"], "1": ["MOG", "CLDN11"]},
                "cluster_neighborhood": {"top_pairs": [{"pair": "0 | 1", "zscore": -2.4}]},
                "interpretation": "Synthetic descriptive fixture.",
            },
            "spatial_robustness": {
                "status": "computed",
                "score": 0.82,
                "requested_settings": [6, 10, 15],
                "n_perms": 250,
                "random_state": 17,
                "top_k": 10,
                "engines": ["squidpy"],
                "mean_sign_agreement": 1.0,
                "mean_topk_jaccard": 0.55,
                "n_reference_pairs": 10,
            },
            "spatial_relationships": {
                "status": "computed",
                "method": "Squidpy permutation neighborhood enrichment",
                "graph": {"n_neighs": 6, "n_perms": 250, "random_state": 17},
                "relationships": [
                    {
                        "pair": "A | B",
                        "direction": "enriched",
                        "zscore": 4.2,
                        "settings_present": 3,
                        "sign_agreement": 1.0,
                        "median_bidirectional_nearest_distance": 8.5,
                        "coordinate_units": "micron",
                        "region_overlap": 0.8,
                        "shared_regions": ["core"],
                        "evidence_status": "stable_enriched",
                    }
                ],
                "warnings": ["Spatial adjacency is not evidence of signaling or causation."],
            },
            "region_stratified_neighborhoods": {
                "status": "computed",
                "tested_region_count": 2,
                "skipped_region_count": 0,
                "pair_consistency": [
                    {
                        "pair": "A | B",
                        "regions_tested": 2,
                        "direction_agreement": 1.0,
                        "strongest_region": "core",
                        "strongest_abs_zscore": 3.8,
                        "status": "region_consistent",
                    }
                ],
                "warnings": ["Within-region synthetic fixture."],
            },
            "distance_cooccurrence": {
                "status": "computed",
                "coordinate_units": "micron",
                "max_distance": 50.0,
                "n_intervals": 20,
                "curves": [
                    {
                        "pair": "A | B",
                        "peak_ratio": 1.4,
                        "peak_distance": 10.0,
                        "short_range_mean_ratio": 1.3,
                        "long_range_mean_ratio": 1.0,
                    }
                ],
                "warnings": ["Descriptive synthetic fixture."],
            },
        }
        rows = dict(_spatial_robustness_rows(payload))
        self.assertEqual(rows["Robustness score"], "0.8200")
        self.assertEqual(rows["Permutations per setting"], "250")
        self.assertEqual(rows["Random seed"], "17")
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / "report.md"
            html_path = Path(tmp) / "report.html"
            pdf_path = Path(tmp) / "report.pdf"
            _write_markdown_report(md_path, payload, [])
            _write_html_report(html_path, payload, [])
            _write_pilot_pdf_report(pdf_path, payload, [])
            self.assertIn("Spatial Robustness Sweep", md_path.read_text(encoding="utf-8"))
            self.assertIn("Descriptive Analysis (no expert labels required)", md_path.read_text(encoding="utf-8"))
            self.assertIn("Weighted graph modularity", md_path.read_text(encoding="utf-8"))
            self.assertIn("Spatial Relationships", md_path.read_text(encoding="utf-8"))
            self.assertIn("stable_enriched", md_path.read_text(encoding="utf-8"))
            self.assertIn("Region-Stratified Neighborhood Testing", md_path.read_text(encoding="utf-8"))
            self.assertIn("Distance-Dependent Co-Occurrence", md_path.read_text(encoding="utf-8"))
            html_report = html_path.read_text(encoding="utf-8")
            self.assertIn("Spatial Robustness Sweep", html_report)
            self.assertIn("Descriptive Analysis (no expert labels required)", html_report)
            self.assertIn("Weighted graph modularity", html_report)
            self.assertIn("Spatial Relationships", html_report)
            self.assertIn("stable_enriched", html_report)
            self.assertIn("region_consistent", html_report)
            self.assertIn("Peak distance", html_report)
            self.assertIn("0.8200", html_report)
            with pdf_path.open("rb") as handle:
                self.assertEqual(handle.read(5), b"%PDF-")

    def test_spatial_robustness_component_prefers_real_sweep(self):
        from spatialmind.methods.reliability.scoring import _spatial_robustness_component

        claim = {"claim_type": "spatial_colocalization", "status": "supported"}
        payload = {
            "spatial_robustness": {
                "status": "computed",
                "score": 0.82,
                "mean_sign_agreement": 1.0,
                "mean_topk_jaccard": 0.55,
                "settings": [6, 10, 15],
            }
        }
        component = _spatial_robustness_component(claim, payload, [])
        self.assertEqual(component.status, "computed")
        self.assertEqual(component.score, 0.82)
        # Without a sweep, it falls back to the heuristic proxy (no crash, still a score).
        fallback = _spatial_robustness_component(claim, {}, [])
        self.assertIsNotNone(fallback.score)

    def test_pilot_report_renders_per_group_markers(self):
        from spatialmind.pilot.xenium import _marker_group_markdown, _marker_group_html
        from spatialmind.schemas import ToolResult

        result = ToolResult(
            tool_name="marker_detection",
            summary="Detected one-vs-rest marker candidates for 2 groups.",
            metrics={
                "mode": "one_vs_rest",
                "markers_by_group": {
                    "T cell": [{"gene": "CD8A"}, {"gene": "CD3D"}],
                    "Tumor cell": [{"gene": "EPCAM"}],
                },
            },
        )
        md = "\n".join(_marker_group_markdown(result))
        self.assertIn("Top markers (one-vs-rest)", md)
        self.assertIn("CD8A", md)
        self.assertIn("EPCAM", md)
        self.assertIn("CD8A", _marker_group_html(result))
        # Non-marker tools contribute no marker table.
        other = ToolResult(tool_name="annotation", summary="x", metrics={})
        self.assertEqual(_marker_group_markdown(other), [])
        self.assertEqual(_marker_group_html(other), "")

    def test_full_panel_loading_keeps_all_positive_genes(self):
        from spatialmind.ingestion.pipeline import _matrix_row_to_features

        gene_names = ["g0", "g1", "g2", "g3", "g4"]
        row = [5.0, 3.0, 0.0, 4.0, 2.0]
        # Full panel (0) keeps every positive gene; the zero-valued gene stays absent.
        full = _matrix_row_to_features(row, gene_names, max_features_per_record=0)
        self.assertEqual(set(full), {"g0", "g1", "g3", "g4"})
        # A positive cap truncates to the top-N by value.
        capped = _matrix_row_to_features(row, gene_names, max_features_per_record=2)
        self.assertEqual(set(capped), {"g0", "g3"})

    def test_marker_detection_defaults_to_one_vs_rest_per_group(self):
        records = []
        for index in range(12):
            if index % 3 == 0:
                cell_type, genes = "T cell", {"CD8A": 8.0, "EPCAM": 0.0, "PECAM1": 0.0}
            elif index % 3 == 1:
                cell_type, genes = "Tumor cell", {"CD8A": 0.0, "EPCAM": 8.0, "PECAM1": 0.0}
            else:
                cell_type, genes = "Endothelial cell", {"CD8A": 0.0, "EPCAM": 0.0, "PECAM1": 8.0}
            records.append(SpotRecord("S1", float(index), 0.0, cell_type, genes, cell_id="c%d" % index))
        dataset = SpatialDataset(sample_id="S1", source_path="synthetic", modality="xenium_spatial_rna", records=records)
        result = marker_detection(dataset, {"engine": "prototype"})
        self.assertEqual(result.metrics["mode"], "one_vs_rest")
        markers = result.metrics["markers_by_group"]
        self.assertEqual(set(markers), {"T cell", "Tumor cell", "Endothelial cell"})
        # Each group's own defining gene should be its top up-regulated marker.
        self.assertEqual(markers["T cell"][0]["gene"], "CD8A")
        self.assertEqual(markers["Tumor cell"][0]["gene"], "EPCAM")
        self.assertEqual(markers["Endothelial cell"][0]["gene"], "PECAM1")

    def test_marker_detection_explicit_groups_stay_pairwise(self):
        dataset = DataIngestionLayer().load_csv(DEMO, sample_id="BRCA_04")
        result = marker_detection(
            dataset,
            {"engine": "prototype", "group_key": "cell_type", "group1": "CD8+ T cell", "group2": "Tumor cell"},
        )
        self.assertEqual(result.metrics["mode"], "pairwise")
        self.assertEqual(result.metrics["group1"], "CD8+ T cell")
        self.assertEqual(result.metrics["group2"], "Tumor cell")

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
        self.assertIn("spatial_variable_genes", [step.tool_name for step in plan])
        strict_tools = {
            step.tool_name
            for step in plan
            if step.params.get("strict_engine")
        }
        self.assertEqual(
            strict_tools,
            {"qc_and_cluster", "marker_detection", "spatial_variable_genes", "cell_neighborhood_enrichment"},
        )

    def test_analysis_scope_distinguishes_sample_from_full_section(self):
        from spatialmind.pilot.xenium import _analysis_scope

        sampled = SpatialDataset(
            sample_id="X1",
            source_path="xenium",
            records=[SpotRecord("X1", 0.0, 0.0, "T cell", {"CD8A": 1.0})],
            metadata={
                "analysis_scope": "sampled",
                "n_obs_total": 10,
                "sampling": {"total_records": 10, "method": "deterministic_even_index"},
            },
        )
        full = SpatialDataset(
            sample_id="X2",
            source_path="xenium",
            records=[SpotRecord("X2", 0.0, 0.0, "T cell", {"CD8A": 1.0})],
            metadata={
                "analysis_scope": "full_section",
                "n_obs_total": 1,
                "sampling": {"total_records": 1, "method": "all"},
            },
        )
        self.assertFalse(_analysis_scope(sampled)["complete_section_requirement_met"])
        self.assertTrue(_analysis_scope(full)["complete_section_requirement_met"])
        self.assertFalse(_analysis_scope(full)["validated_claims_allowed"])

    def test_pilot_reports_structurally_valid_plan_regardless_of_inputs(self):
        # The plan is structurally sound; input availability is the gate's job, so
        # plan validation must not report "invalid" just because externals are pending.
        from spatialmind.pilot.xenium import _pilot_structural_inputs

        report = validate_tool_plan(
            build_xenium_mvp_plan(),
            available_inputs=_pilot_structural_inputs(),
            registry_tool_names=MVP_TOOL_NAMES,
        )
        self.assertEqual(report.status, "valid")
        self.assertEqual(report.errors, [])

    def test_readiness_only_skips_heavy_artifacts(self):
        if not os.path.isdir(XENIUM_LYMPH):
            self.skipTest("local Xenium lymph dataset not available")
        from spatialmind.pilot.xenium import run_pilot

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "readiness"
            result = run_pilot(XENIUM_LYMPH, out, max_records=40, readiness_only=True)
            # Gate / plan / claim status is still computed.
            self.assertTrue(result["status"].startswith("blocked"))
            self.assertEqual(result["plan_validation"]["status"], "valid")
            self.assertIn("claim_ledger", result)
            self.assertTrue(result["readiness_only"])
            # Heavy artifacts are skipped.
            self.assertEqual(result["report_md"], "")
            self.assertEqual(result["report_html"], "")
            self.assertEqual(result["run_record_path"], "")
            self.assertEqual(result["figures"], [])
            self.assertEqual({p.name for p in out.iterdir()}, {"pilot_validation.json"})

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

    def test_claim_reliability_scores_blocked_and_readiness_claims(self):
        payload = {
            "status": "blocked_missing_validation_inputs",
            "required_next_inputs": ["Add expert_cell_labels.csv", "Add cell_regions.csv"],
            "records_loaded": 10,
            "features_loaded": 50,
            "label_report": {"status": "missing_expert_labels", "matched_cells": 0, "total_records": 10},
            "region_report": {"status": "missing_user_regions", "matched_cells": 0, "total_records": 10},
            "asset_readiness": {
                "has_cell_table": True,
                "has_feature_matrix": True,
                "has_morphology": True,
                "has_boundaries": True,
            },
            "contract": {"assay_subtype": "xenium_spatial_rna", "n_features": 50, "is_targeted_panel": True},
        }
        payload["claim_ledger"] = build_pilot_claim_ledger(payload, [])
        reliability = build_claim_reliability_table(payload, [])
        self.assertEqual(len(reliability), 2)
        self.assertEqual(reliability[0]["status"], "blocked")
        self.assertEqual(reliability[0]["reliability"], 0.0)
        self.assertGreater(reliability[1]["reliability"], reliability[0]["reliability"])
        self.assertIn("A_annotation", reliability[0]["components"])

    def test_claim_truth_validation_and_calibration_require_reviewed_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "spatial_claim_truth_draft_for_review.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(",".join(CLAIM_TRUTH_FIELDS) + "\n")
                handle.write(
                    "r0,healthy,pilot_claim,pipeline_readiness_control,claim_001,visual_pattern,supported,ready,0.75,1,0.75,0.8,1,1,,no,,,,train,\n"
                )
            blocked = validate_claim_truth_table(path)
            self.assertEqual(blocked["status"], "blocked")
            self.assertIn("Need at least", " ".join(blocked["blockers"]))

            with open(path, "w", encoding="utf-8") as handle:
                handle.write(",".join(CLAIM_TRUTH_FIELDS) + "\n")
                rows = [
                    "r1,healthy,pilot_claim,pipeline_readiness_control,c1,visual_pattern,supported,ready,0.75,1,0.75,0.8,1,1,1,yes,reviewer,2026-07-08,asset check,,train,",
                    "r2,healthy,null_control,null_control,c2,spatial_colocalization,refused,null,0,0,0,0.5,0,0,0,yes,reviewer,2026-07-08,null,,train,",
                    "r3,glioblastoma,pilot_claim,pipeline_readiness_control,c3,visual_pattern,supported,ready,0.75,1,0.75,0.8,1,1,1,yes,reviewer,2026-07-08,asset check,,validation,",
                    "r4,glioblastoma,null_control,null_control,c4,spatial_colocalization,refused,null,0,0,0,0.5,0,0,0,yes,reviewer,2026-07-08,null,,test,",
                ]
                handle.write("\n".join(rows) + "\n")
            ready = validate_claim_truth_table(path)
            self.assertEqual(ready["status"], "ready_for_calibration")
            model = fit_claim_reliability_calibration(ready["records"])
            self.assertEqual(model["status"], "fit")
            self.assertIn("A_annotation", model["weights"])

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

    def test_xenium_explorer_lite_viewer_exports_review_controls(self):
        dataset = SpatialDataset(
            sample_id="X1",
            source_path="experiment.xenium",
            modality="xenium_spatial_rna",
            coordinate_system="microns",
            records=[
                SpotRecord("X1", 0.0, 0.0, "astrocyte", {"GFAP": 4.0, "AQP4": 2.0}, region="brain", cell_id="cell-a"),
                SpotRecord("X1", 10.0, 8.0, "microglial cell", {"CX3CR1": 3.0}, region="brain", cell_id="cell-b"),
            ],
            metadata={
                "xenium_explorer_assets": {
                    "analysis_summary_filepath": {
                        "relative_path": "analysis_summary.html",
                        "resolved_path": "/tmp/analysis_summary.html",
                        "exists": True,
                    }
                }
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = XeniumExplorerLiteViewer().render(dataset, tmp, dataset_path="experiment.xenium")
            with open(path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("SpatialMind Explorer Lite", content)
            self.assertIn("Export Regions", content)
            self.assertIn("expert_cell_labels.csv", content)
            self.assertIn("cell_regions.csv", content)
            self.assertIn("cell-a", content)
            self.assertIn("analysis_summary_filepath", content)


class MorphologyLayerTests(unittest.TestCase):
    def test_loaders_degrade_when_assets_are_missing(self):
        from spatialmind.viz.morphology import (
            find_morphology_image,
            load_cell_boundaries,
            load_morphology_thumbnail,
            read_pixel_size,
        )

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_morphology_image(tmp))
            self.assertIsNone(read_pixel_size(tmp))
            image = load_morphology_thumbnail(tmp)
            self.assertEqual(image["status"], "unavailable")
            self.assertIn("reason", image)
            boundaries = load_cell_boundaries(tmp)
            self.assertEqual(boundaries["status"], "unavailable")
            self.assertEqual(boundaries["polygons"], {})

    def test_choose_level_picks_smallest_level_above_target(self):
        from spatialmind.viz.morphology import _choose_level

        class Level:
            def __init__(self, shape):
                self.shape = shape

        levels = [Level((27282, 36955)), Level((13641, 18477)), Level((6820, 9238)), Level((1705, 2309)), Level((213, 288))]
        # Level 3 (2309 wide) is the smallest still >= 1600.
        self.assertEqual(_choose_level(levels, 1600), 3)
        # Nothing satisfies a huge target, so the largest level is used.
        self.assertEqual(_choose_level(levels, 99999), 0)

    def test_real_xenium_morphology_and_boundaries_align(self):
        if not os.path.isdir(XENIUM_LYMPH):
            self.skipTest("local Xenium dataset not available")
        from spatialmind.viz.morphology import load_cell_boundaries, load_morphology_thumbnail

        image = load_morphology_thumbnail(XENIUM_LYMPH, max_dimension=400)
        if image["status"] != "loaded":
            self.skipTest("morphology image unavailable: %s" % image.get("reason"))
        self.assertTrue(image["data_uri"].startswith("data:image/png;base64,"))
        self.assertGreater(image["width_um"], 0)
        self.assertGreater(image["height_um"], 0)
        self.assertLessEqual(max(image["thumbnail_width"], image["thumbnail_height"]), 400)

        from spatialmind.ingestion import load_xenium

        dataset = load_xenium(XENIUM_LYMPH, max_records=40)
        cell_ids = [record.cell_id for record in dataset.records]
        boundaries = load_cell_boundaries(XENIUM_LYMPH, cell_ids=cell_ids)
        if boundaries["status"] != "loaded":
            self.skipTest("boundaries unavailable: %s" % boundaries.get("reason"))
        self.assertLessEqual(boundaries["cell_count"], len(cell_ids))
        # Each polygon must enclose its own centroid, which is what keeps the
        # segmentation overlay registered with the plotted cells.
        for record in dataset.records:
            vertices = boundaries["polygons"].get(record.cell_id)
            if not vertices:
                continue
            xs = [vertex[0] for vertex in vertices]
            ys = [vertex[1] for vertex in vertices]
            self.assertGreaterEqual(record.x, min(xs) - 1.0)
            self.assertLessEqual(record.x, max(xs) + 1.0)
            self.assertGreaterEqual(record.y, min(ys) - 1.0)
            self.assertLessEqual(record.y, max(ys) + 1.0)


class LabelTransferTests(unittest.TestCase):
    def _reference(self):
        records = []
        for index in range(12):
            records.append(SpotRecord("R", 0.0, 0.0, "T cell", {"CD8A": 9.0, "CD3D": 8.0, "EPCAM": 0.0}, cell_id="r%d" % index))
            records.append(SpotRecord("R", 0.0, 0.0, "Tumor cell", {"CD8A": 0.0, "CD3D": 0.0, "EPCAM": 9.0}, cell_id="t%d" % index))
        return SpatialDataset(sample_id="R", source_path="ref", modality="scrna", records=records)

    def _target(self):
        return SpatialDataset(
            sample_id="X",
            source_path="x",
            modality="xenium_spatial_rna",
            records=[
                SpotRecord("X", 0.0, 0.0, "Unannotated cell", {"CD8A": 7.0, "CD3D": 6.0, "EPCAM": 0.0}, cell_id="a1"),
                SpotRecord("X", 1.0, 0.0, "Unannotated cell", {"CD8A": 0.0, "CD3D": 0.0, "EPCAM": 7.0}, cell_id="a2"),
            ],
        )

    def test_transfer_assigns_a_label_and_confidence_per_cell(self):
        result = reference_label_transfer(
            self._target(),
            {"reference_dataset": self._reference(), "min_shared_features": 2},
        )
        self.assertEqual(result.metrics["status"], "transferred")
        self.assertTrue(result.metrics["labels_transferred"])
        predictions = {item["cell_id"]: item for item in result.metrics["predictions"]}
        self.assertEqual(predictions["a1"]["predicted_label"], "T cell")
        self.assertEqual(predictions["a2"]["predicted_label"], "Tumor cell")
        for item in predictions.values():
            self.assertGreaterEqual(item["confidence"], 0.0)
            self.assertLessEqual(item["confidence"], 1.0)
        self.assertIn("expert review", " ".join(result.caveats).lower())

    def test_review_priority_is_calibrated_on_the_target_not_the_reference(self):
        target = self._target()
        # Extra cells so a 90th-percentile cut is meaningful.
        for index in range(18):
            target.records.append(
                SpotRecord("X", float(index), 1.0, "Unannotated cell",
                           {"CD8A": 6.0, "CD3D": 5.0, "EPCAM": 0.0}, cell_id="e%d" % index)
            )
        result = reference_label_transfer(
            target, {"reference_dataset": self._reference(), "min_shared_features": 2},
        )
        metrics = result.metrics
        flagged = metrics["high_review_priority_count"]
        # Must flag a reviewable minority, not everything (the failure mode of
        # calibrating against reference-internal distances across assays).
        self.assertLess(flagged, len(target.records))
        self.assertIn("platform_shift_ratio", metrics)
        priorities = {item["review_priority"] for item in metrics["predictions"]}
        self.assertTrue(priorities <= {"high", "normal"})
        for item in metrics["predictions"]:
            self.assertIn("distant_from_reference", item)
        # Coverage limits must be stated, since vote confidence cannot express them.
        self.assertTrue(any("no matching class" in caveat for caveat in result.caveats))

    def test_marker_lineage_resolution_is_conservative(self):
        from spatialmind.tools.implementations import lineage_for_label, lineages_conflict, marker_lineage

        # Unambiguous myeloid evidence resolves.
        lineage, score = marker_lineage({"CD68": 5.0, "AIF1": 4.0, "C1QA": 3.0})
        self.assertEqual(lineage, "myeloid")
        self.assertGreater(score, 0)
        # Tied evidence across lineages must NOT resolve, rather than guess.
        self.assertEqual(marker_lineage({"AQP4": 2.0, "CD4": 2.0})[0], "")
        # Trace evidence below the floor must not resolve.
        self.assertEqual(marker_lineage({"CD68": 0.2})[0], "")

        self.assertEqual(lineage_for_label("intratelencephalic-projecting glutamatergic cortical neuron"), "neuronal")
        self.assertEqual(lineage_for_label("microglial cell"), "myeloid")
        # Most specific keyword wins.
        self.assertEqual(lineage_for_label("oligodendrocyte precursor cell"), "opc")
        self.assertEqual(lineage_for_label("oligodendrocyte"), "oligodendrocyte")

        self.assertTrue(lineages_conflict("neuronal", "myeloid"))
        self.assertFalse(lineages_conflict("neuronal", "neuronal"))
        self.assertFalse(lineages_conflict("oligodendrocyte", "opc"))  # compatible
        self.assertFalse(lineages_conflict("neuronal", ""))  # unknown never conflicts

    def test_marker_disagreement_flags_cells_confidence_would_miss(self):
        target = SpatialDataset(
            sample_id="X",
            source_path="x",
            modality="xenium_spatial_rna",
            records=[
                # Unambiguously myeloid, but the reference has no myeloid class.
                SpotRecord("X", 0.0, 0.0, "Unannotated cell",
                           {"CD68": 6.0, "AIF1": 5.0, "C1QA": 4.0, "CD8A": 0.0, "EPCAM": 0.0}, cell_id="myeloid1"),
                SpotRecord("X", 1.0, 0.0, "Unannotated cell",
                           {"CD8A": 7.0, "CD3D": 6.0, "EPCAM": 0.0}, cell_id="lymphoid1"),
            ],
        )
        def reference_cell(label, profile, index):
            genes = {"CD68": 0.0, "AIF1": 0.0, "C1QA": 0.0, "CD8A": 0.0, "EPCAM": 0.0, "MBP": 0.0, "MOG": 0.0}
            genes.update(profile)
            return SpotRecord("R", 0.0, 0.0, label, genes, cell_id="%s%d" % (label[:3], index))

        reference = SpatialDataset(
            sample_id="R", source_path="r", modality="scrna",
            records=[reference_cell("oligodendrocyte", {"MBP": 9.0, "MOG": 8.0}, i) for i in range(10)]
                    + [reference_cell("neuron", {"CD8A": 1.0}, i) for i in range(10)],
        )
        result = reference_label_transfer(target, {"reference_dataset": reference, "min_shared_features": 2})
        by_id = {item["cell_id"]: item for item in result.metrics["predictions"]}
        # The myeloid cell has no correct label available in this reference.
        self.assertEqual(by_id["myeloid1"]["marker_lineage"], "myeloid")
        self.assertTrue(by_id["myeloid1"]["lineage_absent_from_reference"])
        self.assertEqual(by_id["myeloid1"]["review_priority"], "high")
        self.assertGreaterEqual(result.metrics["lineage_absent_from_reference_count"], 1)
        self.assertIn("myeloid", result.metrics["reference_lineages"] + ["myeloid"])  # sanity on key presence
        self.assertIn("reference_lineages", result.metrics)

    def test_without_reference_dataset_no_transfer_is_claimed(self):
        result = reference_label_transfer(
            self._target(),
            {"reference_features": ["CD8A", "CD3D", "EPCAM"], "min_shared_features": 2},
        )
        self.assertEqual(result.metrics["status"], "compatibility_only")
        self.assertFalse(result.metrics["labels_transferred"])
        self.assertNotIn("predictions", result.metrics)
        # The summary must not assert that a transfer happened.
        self.assertIn("No labels were transferred", result.summary)

    def test_shared_feature_count_comes_from_the_reference_not_the_target(self):
        # The target carries extra genes the reference never measured; only the
        # genuinely shared ones may be counted.
        target = self._target()
        for record in target.records:
            record.genes["EXTRA_GENE_A"] = 1.0
            record.genes["EXTRA_GENE_B"] = 1.0
        result = reference_label_transfer(
            target,
            {"reference_dataset": self._reference(), "min_shared_features": 2},
        )
        self.assertEqual(result.metrics["shared_feature_count"], 3)

    def test_cross_species_reference_is_refused(self):
        target = self._target()
        target.metadata["organism"] = "Human"
        reference = self._reference()
        reference.metadata["organism"] = "Mus musculus"
        with self.assertRaises(MissingPreconditionError) as ctx:
            reference_label_transfer(target, {"reference_dataset": reference, "min_shared_features": 2})
        self.assertIn("cross-species", str(ctx.exception))
        # Explicit opt-in (for pre-mapped orthologs) still works.
        result = reference_label_transfer(
            target,
            {"reference_dataset": reference, "min_shared_features": 2, "allow_cross_species": True},
        )
        self.assertEqual(result.metrics["status"], "transferred")

    def test_same_species_and_unknown_species_are_allowed(self):
        from spatialmind.tools.implementations import normalize_species

        self.assertEqual(normalize_species("Homo sapiens"), "human")
        self.assertEqual(normalize_species("NCBITaxon:10090"), "mouse")
        target = self._target()
        target.metadata["organism"] = "Homo sapiens"
        reference = self._reference()
        reference.metadata["organism"] = "Human"
        result = reference_label_transfer(target, {"reference_dataset": reference, "min_shared_features": 2})
        self.assertEqual(result.metrics["status"], "transferred")
        # Unknown organism on either side must not hard-block a legitimate run.
        reference.metadata["organism"] = ""
        self.assertEqual(
            reference_label_transfer(target, {"reference_dataset": reference, "min_shared_features": 2}).metrics["status"],
            "transferred",
        )

    def test_single_class_reference_is_rejected(self):
        reference = SpatialDataset(
            sample_id="R",
            source_path="ref",
            modality="scrna",
            records=[SpotRecord("R", 0.0, 0.0, "T cell", {"CD8A": 9.0, "CD3D": 8.0, "EPCAM": 0.0}, cell_id="r%d" % i) for i in range(6)],
        )
        with self.assertRaises(MissingPreconditionError):
            reference_label_transfer(self._target(), {"reference_dataset": reference, "min_shared_features": 2})


class H5adReferenceLoadingTests(unittest.TestCase):
    def test_scrna_h5ad_without_spatial_coordinates_loads(self):
        try:
            import anndata as ad  # type: ignore
            import numpy as np  # type: ignore
            import pandas as pd  # type: ignore
        except ImportError:
            self.skipTest("anndata required")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reference.h5ad"
            adata = ad.AnnData(
                X=np.array([[5.0, 0.0, 1.0], [0.0, 6.0, 1.0], [4.0, 0.0, 2.0], [0.0, 7.0, 1.0]]),
                obs=pd.DataFrame({"cell_type": ["T cell", "Tumor cell", "T cell", "Tumor cell"]}),
                var=pd.DataFrame(
                    {"feature_name": ["CD8A", "EPCAM", "ACTB"]},
                    index=["ENSG00000153563", "ENSG00000119888", "ENSG00000075624"],
                ),
            )
            adata.uns["organism"] = "Homo sapiens"
            adata.write_h5ad(path)

            dataset = load_scrna(str(path), max_records=10)
            self.assertEqual(len(dataset.records), 4)
            # Symbols must win over Ensembl IDs so symbol panels can align.
            self.assertIn("CD8A", dataset.genes)
            self.assertNotIn("ENSG00000153563", dataset.genes)
            self.assertEqual(dataset.metadata.get("organism"), "Homo sapiens")
            self.assertEqual(sorted(dataset.cell_types), ["T cell", "Tumor cell"])

    def test_single_class_reference_files_combine_into_a_usable_reference(self):
        try:
            import anndata as ad  # type: ignore
            import numpy as np  # type: ignore
            import pandas as pd  # type: ignore
        except ImportError:
            self.skipTest("anndata required")
        from spatialmind.ingestion import load_scrna_reference_set

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            # Atlases such as the Siletti brain collection ship one class per file.
            for label, profile in (("oligodendrocyte", [9.0, 0.0]), ("astrocyte", [0.0, 9.0])):
                path = Path(tmp) / ("%s.h5ad" % label.replace(" ", "_"))
                adata = ad.AnnData(
                    X=np.array([profile, profile]),
                    obs=pd.DataFrame({"cell_type": [label, label]}),
                    var=pd.DataFrame({"feature_name": ["MOG", "AQP4"]}, index=["ENSG1", "ENSG2"]),
                )
                adata.uns["organism"] = "Homo sapiens"
                adata.write_h5ad(path)
                paths.append(str(path))

            single = load_scrna(paths[0], max_records=10)
            self.assertEqual(len(single.cell_types), 1)  # unusable alone

            combined = load_scrna_reference_set(paths, max_records_per_file=10)
            self.assertEqual(sorted(combined.cell_types), ["astrocyte", "oligodendrocyte"])
            self.assertEqual(len(combined.records), 4)
            self.assertEqual(combined.metadata["reference_file_count"], 2)

    def test_reference_set_refuses_mixed_organisms(self):
        try:
            import anndata as ad  # type: ignore
            import numpy as np  # type: ignore
            import pandas as pd  # type: ignore
        except ImportError:
            self.skipTest("anndata required")
        from spatialmind.ingestion import load_scrna_reference_set

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for label, organism in (("astrocyte", "Homo sapiens"), ("microglial cell", "Mus musculus")):
                path = Path(tmp) / ("%s.h5ad" % organism.split()[0])
                adata = ad.AnnData(
                    X=np.array([[5.0, 1.0], [4.0, 2.0]]),
                    obs=pd.DataFrame({"cell_type": [label, label]}),
                    var=pd.DataFrame({"feature_name": ["AQP4", "AIF1"]}, index=["G1", "G2"]),
                )
                adata.uns["organism"] = organism
                adata.write_h5ad(path)
                paths.append(str(path))
            with self.assertRaises(Exception) as ctx:
                load_scrna_reference_set(paths, max_records_per_file=10)
            self.assertIn("organism", str(ctx.exception).lower())

    def test_backed_and_memory_reads_agree(self):
        try:
            import anndata as ad  # type: ignore
            import numpy as np  # type: ignore
            import pandas as pd  # type: ignore
            from scipy import sparse  # type: ignore
        except ImportError:
            self.skipTest("anndata/scipy required")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backed.h5ad"
            rng = np.random.default_rng(0)
            matrix = sparse.csr_matrix(rng.integers(0, 5, size=(40, 6)).astype(float))
            adata = ad.AnnData(
                X=matrix,
                obs=pd.DataFrame({"cell_type": ["A" if i % 2 else "B" for i in range(40)]}),
                var=pd.DataFrame({"feature_name": ["G%d" % i for i in range(6)]}, index=["E%d" % i for i in range(6)]),
            )
            adata.uns["organism"] = "Homo sapiens"
            adata.write_h5ad(path)

            layer = DataIngestionLayer()
            backed = layer.load_h5ad(str(path), max_records=12, require_spatial=False, backed=True)
            memory = layer.load_h5ad(str(path), max_records=12, require_spatial=False, backed=False)

            self.assertEqual(memory.metadata["h5ad_read_mode"], "memory")
            self.assertIn(backed.metadata["h5ad_read_mode"], {"backed", "memory"})
            # Whichever path is taken, the ingested content must be identical.
            self.assertEqual(len(backed.records), len(memory.records))
            self.assertEqual(backed.genes, memory.genes)
            self.assertEqual(
                [record.cell_id for record in backed.records],
                [record.cell_id for record in memory.records],
            )
            self.assertEqual(
                [record.cell_type for record in backed.records],
                [record.cell_type for record in memory.records],
            )
            for left, right in zip(backed.records, memory.records):
                self.assertEqual(left.genes, right.genes)

    def test_spatial_h5ad_still_requires_coordinates(self):
        try:
            import anndata as ad  # type: ignore
            import numpy as np  # type: ignore
            import pandas as pd  # type: ignore
        except ImportError:
            self.skipTest("anndata required")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nospatial.h5ad"
            adata = ad.AnnData(
                X=np.array([[1.0, 2.0], [3.0, 4.0]]),
                obs=pd.DataFrame({"cell_type": ["A", "B"]}),
                var=pd.DataFrame(index=["G1", "G2"]),
            )
            adata.write_h5ad(path)
            with self.assertRaises(Exception):
                DataIngestionLayer().load_h5ad(str(path), require_spatial=True)


class ReferenceAssistTests(unittest.TestCase):
    def test_tabular_reference_is_accepted_without_a_xenium_folder(self):
        from spatialmind.review.glioblastoma import _load_reference_dataset

        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "brain_reference.csv"
            reference.write_text(
                "sample_id,x,y,cell_type,CD8A,EPCAM,PTPRC\n"
                "R1,0,0,T cell,5,0,4\n"
                "R1,1,0,Tumor cell,0,6,0\n"
                "R1,2,0,T cell,4,0,3\n",
                encoding="utf-8",
            )
            dataset, ready, status, blockers, fmt = _load_reference_dataset(str(reference), max_records=10)
            self.assertIsNotNone(dataset)
            self.assertEqual(fmt, "table")
            self.assertTrue(ready, blockers)
            self.assertEqual(status, "reference_labels_available")

    def test_single_class_reference_is_blocked(self):
        from spatialmind.review.glioblastoma import _load_reference_dataset

        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "thin_reference.csv"
            reference.write_text(
                "sample_id,x,y,cell_type,CD8A\nR1,0,0,T cell,5\nR1,1,0,T cell,4\n",
                encoding="utf-8",
            )
            dataset, ready, status, blockers, _fmt = _load_reference_dataset(str(reference), max_records=10)
            self.assertIsNotNone(dataset)
            self.assertFalse(ready)
            self.assertEqual(status, "blocked_missing_reference_labels")
            self.assertTrue(any("cell-type classes" in item for item in blockers))

    def test_unreadable_reference_reports_blocker_instead_of_raising(self):
        from spatialmind.review.glioblastoma import _load_reference_dataset

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent_reference.h5ad"
            dataset, ready, status, blockers, fmt = _load_reference_dataset(str(missing), max_records=10)
            self.assertIsNone(dataset)
            self.assertFalse(ready)
            self.assertEqual(fmt, "anndata")
            self.assertEqual(status, "blocked_unreadable_reference")
            self.assertTrue(blockers)


class EvalHarnessTests(unittest.TestCase):
    def test_mvp_cli_defaults_to_matching_case_suite(self):
        self.assertEqual(_case_directory(None, False), "eval/test_cases")
        self.assertEqual(_case_directory(None, True), "eval/mvp_cases")
        self.assertEqual(_case_directory("custom/cases", True), "custom/cases")

    def test_eval_runner_loads_cases_and_scores(self):
        runner = EvalRunner(SpatialAgent())
        cases = runner.load_cases(os.path.join(ROOT, "eval", "test_cases"))
        self.assertEqual(len(cases), 15)
        report = runner.run(cases[:2])
        self.assertEqual(report["summary"]["case_count"], 2)
        self.assertGreaterEqual(report["summary"]["mean_score"], 0.5)


class BrainExpertBenchmarkTests(unittest.TestCase):
    def test_stratified_selection_is_deterministic_and_keeps_cluster_spatial_coverage(self):
        from spatialmind.review.brain_benchmark import _stratified_select

        rows = []
        for index in range(120):
            cluster = "0" if index < 100 else "1"
            rows.append(
                {
                    "cell_id": "cell-%03d" % index,
                    "expression_cluster": cluster,
                    "proposed_spatial_block": "block-%d" % (index % 4),
                    "selection_priority": 8 if index in {2, 103} else 0,
                }
            )
        first = _stratified_select(rows, 40, "brain")
        second = _stratified_select(rows, 40, "brain")
        self.assertEqual([row["cell_id"] for row in first], [row["cell_id"] for row in second])
        self.assertEqual(len(first), 40)
        self.assertEqual({row["expression_cluster"] for row in first}, {"0", "1"})
        self.assertGreaterEqual(len({row["proposed_spatial_block"] for row in first}), 4)
        self.assertIn("cell-002", {row["cell_id"] for row in first})
        self.assertIn("cell-103", {row["cell_id"] for row in first})

    def test_spatial_block_splits_never_leak_cells_from_one_block(self):
        from spatialmind.review.brain_benchmark import _assign_spatial_block_splits

        mapping = _assign_spatial_block_splits(["block-%d" % index for index in range(16)], "brain")
        self.assertEqual(set(mapping.values()), {"train", "validation", "test"})
        self.assertEqual(len(mapping), 16)
        self.assertEqual(mapping, _assign_spatial_block_splits(mapping.keys(), "brain"))

    def test_qc_rebalancing_keeps_critical_exceptions_without_dominating_cohort(self):
        from spatialmind.review.brain_benchmark import _rebalance_qc_strata

        rows = []
        for index in range(100):
            rows.append(
                {
                    "cell_id": "cell-%03d" % index,
                    "expression_cluster": str(index % 2),
                    "qc_stratum": "low_transcript_count" if index < 70 else "typical",
                    "selection_priority": 6 if index in {0, 1} else 0,
                }
            )
        selected = rows[:40]
        balanced = _rebalance_qc_strata(selected, rows, "brain", minimum_typical_fraction=0.6)
        self.assertGreaterEqual(sum(1 for row in balanced if row["qc_stratum"] == "typical"), 24)
        self.assertIn("cell-000", {row["cell_id"] for row in balanced})
        self.assertIn("cell-001", {row["cell_id"] for row in balanced})

    def test_completed_review_packet_materializes_frozen_truth_splits(self):
        from spatialmind.review.brain_benchmark import validate_brain_benchmark_packet

        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp) / "healthy_brain"
            dataset_dir.mkdir()
            labels = []
            regions = []
            splits = []
            split_names = ["train", "train", "validation", "validation", "test", "test"]
            for index, split_name in enumerate(split_names):
                cell_id = "cell-%d" % index
                labels.append(
                    {
                        "cell_id": cell_id,
                        "expert_label": "astrocyte",
                        "cl_id": "CL:0000127",
                        "secondary_state": "",
                        "confidence": "0.9",
                        "reviewer_id": "reviewer-a",
                        "expression_cluster": "0",
                        "proposed_spatial_block": "block-%d" % index,
                    }
                )
                regions.append(
                    {
                        "cell_id": cell_id,
                        "region": "region-%d" % (index % 2),
                        "region_confidence": "0.9",
                        "region_reviewer_id": "reviewer-b",
                    }
                )
                splits.append(
                    {
                        "cell_id": cell_id,
                        "proposed_spatial_block": "block-%d" % index,
                        "provisional_split": split_name,
                        "split_unit": "proposed_spatial_block",
                    }
                )

            def write(path, rows):
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)

            write(dataset_dir / "expert_cell_labels_for_review.csv", labels)
            write(dataset_dir / "cell_regions_for_review.csv", regions)
            write(dataset_dir / "benchmark_split_manifest.csv", splits)
            report = validate_brain_benchmark_packet(tmp, minimum_review_coverage=0.9)
            self.assertEqual(report["status"], "ready")
            self.assertTrue((dataset_dir / "reviewed_benchmark_truth.csv").exists())
            self.assertTrue((dataset_dir / "frozen_splits" / "test.csv").exists())
            with (dataset_dir / "reviewed_benchmark_truth.csv").open(newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 6)

    def test_validator_requires_joint_label_region_coverage(self):
        from spatialmind.review.brain_benchmark import validate_brain_benchmark_packet

        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp) / "glioblastoma"
            dataset_dir.mkdir()
            labels = []
            regions = []
            splits = []
            for index in range(10):
                cell_id = "cell-%d" % index
                split_name = "train" if index < 6 else ("validation" if index < 8 else "test")
                labels.append(
                    {
                        "cell_id": cell_id,
                        "expert_label": "" if index == 0 else "astrocyte",
                        "reviewer_id": "" if index == 0 else "reviewer-a",
                    }
                )
                regions.append(
                    {
                        "cell_id": cell_id,
                        "region": "" if index == 1 else "tumor_core",
                        "region_reviewer_id": "" if index == 1 else "reviewer-b",
                    }
                )
                splits.append(
                    {
                        "cell_id": cell_id,
                        "proposed_spatial_block": "block-%d" % index,
                        "provisional_split": split_name,
                        "split_unit": "proposed_spatial_block",
                    }
                )

            def write(path, rows):
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)

            write(dataset_dir / "expert_cell_labels_for_review.csv", labels)
            write(dataset_dir / "cell_regions_for_review.csv", regions)
            write(dataset_dir / "benchmark_split_manifest.csv", splits)
            report = validate_brain_benchmark_packet(tmp, minimum_review_coverage=0.9)
            dataset_report = report["datasets"]["glioblastoma"]
            self.assertEqual(report["status"], "awaiting_expert_review")
            self.assertEqual(dataset_report["label_coverage"], 0.9)
            self.assertEqual(dataset_report["region_coverage"], 0.9)
            self.assertEqual(dataset_report["joint_label_region_coverage"], 0.8)
            self.assertTrue(any("Joint label-and-region" in item for item in dataset_report["blockers"]))
            self.assertFalse((dataset_dir / "reviewed_benchmark_truth.csv").exists())

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

    def test_agent_creates_selectable_pdf_and_html_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = SpatialMindAgent(output_root=os.path.join(tmp, "outputs"), memory_root=os.path.join(tmp, "memory"))
            run = agent.run(
                "Show cell type abundance in sample BRCA_04.",
                DEMO,
                report_format="both",
            )
            self.assertEqual(set(run.report_paths), {"html", "pdf"})
            self.assertTrue(run.report_path.endswith(".html"))
            with open(run.report_paths["pdf"], "rb") as handle:
                self.assertEqual(handle.read(5), b"%PDF-")


class ReportExportTests(unittest.TestCase):
    def test_report_format_validation_and_pdf_writer(self):
        self.assertEqual(normalize_report_format("PDF"), "pdf")
        with self.assertRaises(ValueError):
            normalize_report_format("docx")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "report.pdf")
            write_pdf_report(
                path,
                "SpatialMind Test Report",
                [
                    PdfSection(
                        title="Results",
                        paragraphs=["A verified PDF result."],
                        tables=[PdfTable(headers=["Metric", "Value"], rows=[("score", "1.0")])],
                    )
                ],
            )
            self.assertGreater(os.path.getsize(path), 1024)
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(5), b"%PDF-")

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

    def test_xenium_replay_uses_workflow_type_and_preserves_full_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = os.path.join(tmp, "input.txt")
            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("input")
            record = StorageLayer(root=os.path.join(tmp, "outputs")).write_mvp_run_record(
                query="Custom user request without legacy replay wording",
                tool_trace=[],
                params={
                    "workflow_type": "validated_xenium_pilot",
                    "max_records": 0,
                    "require_complete_section": True,
                    "review_max_records": 750,
                },
                input_files=[input_path],
            )
            replay = replay_run_record(record.run_record_path, verify_only=False)
            self.assertEqual(replay["status"], "verified_replay_ready")
            self.assertEqual(replay["query"], "Custom user request without legacy replay wording")
            self.assertEqual(replay["params"]["max_records"], 0)
            self.assertTrue(replay["params"]["require_complete_section"])
            self.assertEqual(replay["params"]["review_max_records"], 750)


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


class MarkerRuleTighteningTests(unittest.TestCase):
    def test_trace_and_ambiguous_evidence_no_longer_names_a_class(self):
        from spatialmind.ingestion.pipeline import _infer_marker_cell_type

        # PTPRC is pan-leukocyte and must not call a T/NK cell by itself.
        self.assertIsNone(_infer_marker_cell_type({"PTPRC": 2.34}))
        # Two equally specific markers from different lineages stay unresolved.
        self.assertIsNone(_infer_marker_cell_type({"AQP4": 2.5, "CD3D": 2.5}))
        # A shared marker must not outweigh a specific one: AQP4 beats CD4, which
        # is downweighted because myeloid cells express it too.
        self.assertEqual(_infer_marker_cell_type({"AQP4": 2.14, "CD4": 2.14}), "Neural/Glial cell")
        # Trace evidence below the floor.
        self.assertIsNone(_infer_marker_cell_type({"CD68": 0.3}))
        self.assertIsNone(_infer_marker_cell_type({}))

    def test_clear_evidence_still_resolves(self):
        from spatialmind.ingestion.pipeline import _infer_marker_cell_type

        self.assertEqual(
            _infer_marker_cell_type({"CD3D": 4.0, "CD3E": 3.0, "CD8A": 3.0}), "T/NK cell"
        )
        self.assertEqual(
            _infer_marker_cell_type({"AQP4": 5.0, "GFAP": 4.0, "PLP1": 3.0}), "Neural/Glial cell"
        )
        self.assertEqual(
            _infer_marker_cell_type({"PECAM1": 4.0, "CLDN5": 4.0, "FLT1": 3.0}), "Endothelial cell"
        )


class DescriptiveLaneTests(unittest.TestCase):
    def _clustered_dataset(self):
        records = []
        for index in range(24):
            if index % 3 == 0:
                genes = {"AQP4": 8.0, "GJA1": 7.0, "MOG": 0.0, "SLC17A7": 0.0}
            elif index % 3 == 1:
                genes = {"AQP4": 0.0, "GJA1": 0.0, "MOG": 8.0, "SLC17A7": 0.0}
            else:
                genes = {"AQP4": 0.0, "GJA1": 0.0, "MOG": 0.0, "SLC17A7": 8.0}
            records.append(SpotRecord("S1", float(index), float(index % 5), "Unannotated cell", genes, cell_id="c%d" % index))
        return SpatialDataset(sample_id="S1", source_path="synthetic", modality="xenium_spatial_rna", records=records)

    def test_marker_detection_can_group_by_data_derived_clusters(self):
        from spatialmind.tools.implementations import resolve_group_labels, store_cluster_assignments

        dataset = self._clustered_dataset()
        # No expert labels anywhere.
        self.assertTrue(all(record.cell_type == "Unannotated cell" for record in dataset.records))
        store_cluster_assignments(dataset, [str(index % 3) for index in range(len(dataset.records))])
        labels, key = resolve_group_labels(dataset, {"group_key": "cluster"})
        self.assertEqual(key, "cluster")
        self.assertEqual(sorted(set(labels)), ["0", "1", "2"])

        result = marker_detection(dataset, {"group_key": "cluster", "engine": "prototype"})
        self.assertEqual(result.metrics["group_key"], "cluster")
        markers = result.metrics["markers_by_group"]
        self.assertEqual(sorted(markers), ["0", "1", "2"])
        # Each cluster's defining gene should top its own marker list.
        self.assertEqual(markers["0"][0]["gene"], "AQP4")
        self.assertEqual(markers["1"][0]["gene"], "MOG")
        self.assertEqual(markers["2"][0]["gene"], "SLC17A7")

    def test_cluster_grouping_requires_assignments(self):
        from spatialmind.tools.implementations import resolve_group_labels

        dataset = self._clustered_dataset()
        with self.assertRaises(MissingPreconditionError):
            resolve_group_labels(dataset, {"group_key": "cluster"})

    def test_blocked_pilot_still_returns_descriptive_results(self):
        if not os.path.isdir(XENIUM_LYMPH):
            self.skipTest("local Xenium dataset not available")
        from spatialmind.pilot.xenium import run_pilot

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pilot"
            result = run_pilot(XENIUM_LYMPH, out, max_records=150)
            self.assertTrue(result["status"].startswith("blocked"))
            descriptive = result["descriptive_analysis"]
            self.assertEqual(descriptive["status"], "computed")
            self.assertIn("qc_and_cluster", descriptive["tools"])
            self.assertIn("spatial_variable_genes", descriptive["tools"])
            self.assertGreaterEqual(descriptive["cluster_count"], 2)
            # Results must appear before the refusal section in the report.
            report = (out / "validated_xenium_pilot_report.md").read_text()
            self.assertIn("Descriptive Analysis (no expert labels required)", report)
            self.assertIn("Spatially autocorrelated genes", report)
            # Results come before the note about what review would add, and the
            # validated-tier scaffolding is not present on a descriptive report.
            self.assertLess(
                report.index("Descriptive Analysis"),
                report.index("What Expert Review Would Add"),
            )
            self.assertNotIn("## Claim Ledger", report)
            html_report = (out / "validated_xenium_pilot_report.html").read_text()
            self.assertIn("Descriptive Analysis (no expert labels required)", html_report)
            self.assertIn("Spatially autocorrelated genes", html_report)
            self.assertLess(html_report.index("Descriptive Analysis"), html_report.index("Blocking Reasons"))


class DescriptiveFigureTests(unittest.TestCase):
    def _dataset(self):
        records = []
        for index in range(30):
            if index % 3 == 0:
                genes = {"AQP4": 8.0, "GJA1": 7.0, "MOG": 0.0, "SLC17A7": 0.0}
            elif index % 3 == 1:
                genes = {"AQP4": 0.0, "GJA1": 0.0, "MOG": 8.0, "SLC17A7": 0.0}
            else:
                genes = {"AQP4": 0.0, "GJA1": 0.0, "MOG": 0.0, "SLC17A7": 8.0}
            records.append(
                SpotRecord("S1", float(index), float(index % 6), "Unannotated cell", genes, cell_id="c%d" % index)
            )
        return SpatialDataset(sample_id="S1", source_path="synthetic", modality="xenium_spatial_rna", records=records)

    def test_cluster_map_and_marker_heatmap_render(self):
        from spatialmind.pilot.xenium import _render_cluster_marker_heatmap, _render_cluster_spatial_map

        dataset = self._dataset()
        assignments = {record.cell_id: str(index % 3) for index, record in enumerate(dataset.records)}
        with tempfile.TemporaryDirectory() as tmp:
            spatial = _render_cluster_spatial_map(dataset, assignments, Path(tmp) / "map.png")
            if not spatial:
                self.skipTest("matplotlib unavailable")
            self.assertTrue(os.path.getsize(spatial) > 0)
            heatmap = _render_cluster_marker_heatmap(
                dataset,
                assignments,
                {"0": ["AQP4", "GJA1"], "1": ["MOG"], "2": ["SLC17A7"]},
                Path(tmp) / "heat.png",
            )
            self.assertTrue(os.path.getsize(heatmap) > 0)

    def test_figures_are_skipped_without_cluster_assignments(self):
        from spatialmind.pilot.xenium import _write_descriptive_figures

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_write_descriptive_figures(self._dataset(), {}, Path(tmp)), [])

    def test_descriptive_lane_runs_even_when_gate_passes(self):
        import inspect

        from spatialmind.pilot import xenium as pilot_module

        source = inspect.getsource(pilot_module.run_pilot)
        # The lane must not be conditioned on the gate being blocked.
        self.assertIn("if not readiness_only:\n        descriptive = _run_descriptive_lane", source)


class DisplaySamplingTests(unittest.TestCase):
    def _records(self, count):
        return [
            SpotRecord("S1", float(index % 100), float(index // 100), "Unannotated cell", {"G": 1.0}, cell_id="c%d" % index)
            for index in range(count)
        ]

    def test_small_datasets_are_not_capped(self):
        from spatialmind.viz.display_sampling import downsample_for_display

        records = self._records(500)
        subset, info = downsample_for_display(records, max_points=20000)
        self.assertEqual(len(subset), 500)
        self.assertFalse(info["display_capped"])

    def test_large_datasets_are_capped_and_bounded(self):
        from spatialmind.viz.display_sampling import display_caption, downsample_for_display

        records = self._records(50000)
        subset, info = downsample_for_display(records, max_points=5000)
        self.assertEqual(len(subset), 5000)
        self.assertTrue(info["display_capped"])
        self.assertEqual(info["total_records"], 50000)
        self.assertIn("Showing", display_caption(info))
        # Spatial coverage must survive the cut rather than collapsing to one
        # corner. Grid sampling takes cells from within each bin, so the extreme
        # cell may be missed by up to one bin width -- coverage, not exactness.
        span_x = max(r.x for r in records) - min(r.x for r in records)
        span_y = max(r.y for r in records) - min(r.y for r in records)
        self.assertLessEqual(abs(min(r.x for r in subset) - min(r.x for r in records)), span_x * 0.05)
        self.assertGreaterEqual(max(r.x for r in subset), min(r.x for r in records) + span_x * 0.95)
        self.assertGreaterEqual(max(r.y for r in subset), min(r.y for r in records) + span_y * 0.95)

    def test_downsampling_is_deterministic(self):
        from spatialmind.viz.display_sampling import downsample_for_display

        records = self._records(20000)
        first = [r.cell_id for r in downsample_for_display(records, max_points=3000)[0]]
        second = [r.cell_id for r in downsample_for_display(records, max_points=3000)[0]]
        self.assertEqual(first, second)

    def test_descriptive_lane_records_stage_timings(self):
        if not os.path.isdir(XENIUM_LYMPH):
            self.skipTest("local Xenium dataset not available")
        from spatialmind.pilot.xenium import run_pilot

        with tempfile.TemporaryDirectory() as tmp:
            result = run_pilot(XENIUM_LYMPH, Path(tmp) / "p", max_records=150)
            stages = (result["descriptive_analysis"] or {}).get("stage_seconds") or {}
            self.assertIn("total", stages)
            self.assertIn("qc_and_cluster", stages)
            self.assertGreaterEqual(float(stages["total"]), 0.0)


class ClusteringPerformanceTests(unittest.TestCase):
    def test_neighbors_helper_prefers_sklearn_and_falls_back(self):
        from spatialmind.tools.implementations import _neighbors

        calls = []

        class FakePP:
            def neighbors(self, adata, **kwargs):
                calls.append(kwargs)
                if kwargs.get("transformer") == "sklearn" and adata == "no-sklearn":
                    raise TypeError("unexpected keyword argument 'transformer'")

        class FakeSC:
            pp = FakePP()

        self.assertEqual(_neighbors(FakeSC(), "ok", 15, 0), "sklearn")
        self.assertEqual(calls[-1].get("transformer"), "sklearn")
        # Older scanpy without the transformer argument must still work.
        self.assertEqual(_neighbors(FakeSC(), "no-sklearn", 15, 0), "pynndescent")
        self.assertNotIn("transformer", calls[-1])

    def test_thin_samples_are_flagged(self):
        if not os.path.isdir(XENIUM_LYMPH):
            self.skipTest("local Xenium dataset not available")
        from spatialmind.pilot.xenium import MIN_CELLS_FOR_STABLE_CLUSTERS, run_pilot

        with tempfile.TemporaryDirectory() as tmp:
            result = run_pilot(XENIUM_LYMPH, Path(tmp) / "p", max_records=200)
            descriptive = result["descriptive_analysis"]
            if descriptive.get("status") != "computed":
                self.skipTest("descriptive lane unavailable")
            self.assertIn("sampling_warning", descriptive)
            self.assertIn(str(MIN_CELLS_FOR_STABLE_CLUSTERS), descriptive["sampling_warning"])
            report = (Path(tmp) / "p" / "validated_xenium_pilot_report.md").read_text()
            self.assertIn("Sampling note", report)


class SpatialGeneScreeningTests(unittest.TestCase):
    def _adata_stub(self, n_obs, gene_names, detected_counts):
        import numpy as np

        class Var:
            def __init__(self, names):
                self.var_names = names

        class Stub:
            def __init__(self, n_obs, names, counts):
                self.n_obs = n_obs
                self.var_names = names
                # X only needs to support (X > 0).sum(axis=0)
                matrix = np.zeros((n_obs, len(names)))
                for col, count in enumerate(counts):
                    matrix[:count, col] = 1.0
                self.X = matrix

        return Stub(n_obs, gene_names, detected_counts)

    def test_detection_filter_drops_rarely_detected_genes(self):
        from spatialmind.tools.implementations import _screen_spatial_genes

        adata = self._adata_stub(1000, ["A", "B", "C"], [900, 500, 2])
        screen = _screen_spatial_genes(sq=None, adata=adata, params={"min_detected_cells": 100}, n_top=10, random_state=0)
        self.assertEqual(sorted(screen["tested_genes"]), ["A", "B"])
        self.assertEqual(screen["report"]["detected_genes"], 2)
        self.assertEqual(screen["report"]["panel_genes"], 3)
        self.assertIn("detected in >=", screen["report"]["rule"])

    def test_permutation_budget_is_not_inflated_by_default(self):
        from spatialmind.tools.implementations import _screen_spatial_genes

        adata = self._adata_stub(1000, ["A", "B", "C"], [900, 800, 700])
        screen = _screen_spatial_genes(sq=None, adata=adata, params={"n_perms": 100}, n_top=10, random_state=0)
        # Spending the saving on more permutations nets zero total work, which is
        # exactly the mistake this default avoids.
        self.assertEqual(screen["permutations"], 100)

    def test_screen_falls_back_when_too_few_genes_survive(self):
        from spatialmind.tools.implementations import _screen_spatial_genes

        adata = self._adata_stub(1000, ["A", "B"], [1, 1])
        screen = _screen_spatial_genes(sq=None, adata=adata, params={"min_detected_cells": 500}, n_top=5, random_state=0)
        # Never return an empty test set just because the filter was strict.
        self.assertEqual(sorted(screen["tested_genes"]), ["A", "B"])

    def test_report_states_the_screen(self):
        from spatialmind.pilot.xenium import _spatial_screen_note

        note = _spatial_screen_note(
            {
                "significant_gene_count_all": 50,
                "screening": {"rule": "detected in >= 80 cells; top 50", "panel_genes": 424,
                              "detected_genes": 295, "tested_genes": 50},
            }
        )
        self.assertIn("424", note)
        self.assertIn("conditional on this screen", note)
        self.assertEqual(_spatial_screen_note({}), "")


class SamplingWarningBoundaryTests(unittest.TestCase):
    def test_qc_dropping_a_few_cells_does_not_trip_the_warning(self):
        """Requesting exactly the recommended cell count must not warn.

        QC legitimately excludes zero-feature cells, so a 6000-cell request
        analyzes 5999. Warning there penalises a correct request.
        """
        import inspect

        from spatialmind.pilot import xenium as pilot_module

        source = inspect.getsource(pilot_module._run_descriptive_lane)
        self.assertIn("MIN_CELLS_FOR_STABLE_CLUSTERS * 0.95", source)
        threshold = pilot_module.MIN_CELLS_FOR_STABLE_CLUSTERS
        cutoff = threshold * 0.95
        # A 6000-cell request that analyzes 5999 after QC must stay silent.
        self.assertGreaterEqual(threshold - 1, cutoff)
        # A genuinely thin sample must still be flagged.
        self.assertLess(threshold // 2, cutoff)
        # And the cutoff must remain below the recommended target.
        self.assertLess(cutoff, threshold)


class BiologicalReplicationTests(unittest.TestCase):
    def test_one_section_per_condition_is_pseudoreplicated(self):
        from spatialmind.methods.replication import assess_condition_replication

        result = assess_condition_replication({
            "healthy": [{"section_id": "s1", "cell_count": 24406}],
            "glioblastoma": [{"section_id": "s2", "cell_count": 40887}],
        })
        self.assertFalse(result["supports_condition_inference"])
        self.assertEqual(result["status"], "pseudoreplicated")
        # Cell count must not rescue the design.
        self.assertEqual(result["conditions"]["healthy"]["cell_count"], 24406)
        self.assertEqual(result["conditions"]["healthy"]["section_count"], 1)
        self.assertIn("not independent biological replicates", result["allowed_interpretation"])

    def test_replicated_design_is_supported(self):
        from spatialmind.methods.replication import assess_condition_replication

        result = assess_condition_replication({
            "healthy": [{"section_id": "h1", "donor_id": "d1"}, {"section_id": "h2", "donor_id": "d2"}],
            "glioblastoma": [{"section_id": "g1", "donor_id": "d3"}, {"section_id": "g2", "donor_id": "d4"}],
        })
        self.assertTrue(result["supports_condition_inference"])
        self.assertEqual(result["status"], "replicated")
        self.assertEqual(result["unit_of_analysis"], "section")
        self.assertIn("pseudobulk", result["recommended_statistics"])

    def test_single_condition_cannot_be_compared(self):
        from spatialmind.methods.replication import assess_condition_replication

        result = assess_condition_replication({"healthy": [{"section_id": "a"}, {"section_id": "b"}]})
        self.assertFalse(result["supports_condition_inference"])
        self.assertTrue(any("two conditions" in b for b in result["blockers"]))

    def test_labelled_sections_still_block_condition_deltas(self):
        """The review sprint must not by itself unlock an n=1 vs n=1 comparison."""
        from unittest.mock import patch

        from spatialmind.review import glioblastoma as module

        class Intake:
            ready_for_validated_pilot = True
            loaded_cells = 750

            def to_dict(self):
                return {"status": "validated_ready"}

        class Dataset:
            def __init__(self, n):
                self.records = [type("R", (), {"cell_type": "astrocyte"})() for _ in range(n)]

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(module, "validate_xenium_label_intake", return_value=Intake()), \
                 patch.object(module, "_load_validated_dataset", side_effect=[Dataset(700), Dataset(650)]):
                out = module.build_brain_comparison_report(output_dir=tmp, max_records=750)
        self.assertEqual(out["status"], "blocked_insufficient_biological_replication")
        self.assertNotIn("glioblastoma_minus_healthy_label_fraction", out.get("comparison") or {})
        self.assertIn("per_section_summary", out)


class ToolCapabilityTests(unittest.TestCase):
    def test_scaffolds_are_marked_unavailable_and_hidden_from_planning(self):
        registry = build_default_registry()
        summary = registry.capability_summary()
        self.assertGreater(summary.get("unavailable", 0), 0)
        self.assertEqual(len(registry.list_plannable()) + summary["unavailable"], len(registry.list_all()))
        plannable = {tool.name for tool in registry.list_plannable()}
        self.assertNotIn("cnv_inference", plannable)
        self.assertNotIn("pathway_activity", plannable)
        self.assertIn("marker_detection", plannable)

    def test_llm_tool_schemas_exclude_scaffolds_by_default(self):
        registry = build_default_registry()
        shown = {tool["name"] for tool in registry.to_anthropic_tools()}
        every = {tool["name"] for tool in registry.to_anthropic_tools(plannable_only=False)}
        self.assertLess(len(shown), len(every))
        self.assertNotIn("cnv_inference", shown)
        self.assertIn("cnv_inference", every)

    def test_mvp_registry_exposes_no_unavailable_tools(self):
        self.assertEqual(build_mvp_registry().capability_summary().get("unavailable", 0), 0)

    def test_unknown_capability_is_rejected(self):
        from spatialmind.tools.registry import SpatialTool

        with self.assertRaises(ValueError):
            SpatialTool(
                name="x", description="d", when_to_use="w", when_not_to_use="n",
                input_schema={}, output_schema={}, preconditions=[], estimated_runtime="fast",
                callable=lambda dataset, params: None, capability="totally_fine",
            )


class ReviewPlanAlignmentTests(unittest.TestCase):
    def test_pilot_template_is_aligned_to_the_run_it_came_from(self):
        """Labels only count if their cell_ids are in the cells the run loads.

        A review file built from a different selection can be labelled perfectly
        and still leave the gate shut, so the template a run emits must contain
        exactly that run's cells.
        """
        if not os.path.isdir(XENIUM_LYMPH):
            self.skipTest("local Xenium dataset not available")
        from spatialmind.ingestion import load_xenium, write_expert_label_template

        with tempfile.TemporaryDirectory() as tmp:
            dataset = load_xenium(XENIUM_LYMPH, max_records=120)
            path = write_expert_label_template(
                dataset, str(Path(tmp) / "t.csv"), max_rows=120, dataset_path=XENIUM_LYMPH
            )
            with open(path, newline="", encoding="utf-8") as handle:
                template_ids = [row["cell_id"] for row in csv.DictReader(handle)]
            loaded_ids = {record.cell_id for record in dataset.records}
            self.assertTrue(template_ids)
            self.assertTrue(set(template_ids) <= loaded_ids)
            self.assertEqual(len(template_ids), len(loaded_ids))


class DescriptiveReportPackagingTests(unittest.TestCase):
    def test_run_qc_is_surfaced_from_instrument_metrics(self):
        from spatialmind.pilot.xenium import _run_qc, _run_qc_markdown

        dataset = SpatialDataset(
            sample_id="X", source_path="x", modality="xenium_spatial_rna",
            records=[SpotRecord("X", 0.0, 0.0, "c", {"A": 1.0}, cell_id="c1")],
            metadata={
                "fraction_transcripts_decoded_q20": 0.8798,
                "fraction_transcripts_assigned": 0.7876,
                "negative_control_probe_rate": 0.0013,
                "median_genes_per_cell": 69,
            },
        )
        qc = _run_qc(dataset)
        self.assertEqual(qc["status"], "reported")
        by_key = {row["key"]: row for row in qc["metrics"]}
        self.assertEqual(by_key["fraction_transcripts_decoded_q20"]["status"], "ok")
        markdown = "\n".join(_run_qc_markdown({"run_qc": qc}))
        self.assertIn("Instrument run QC", markdown)
        self.assertIn("0.8798", markdown)

    def test_poor_decode_rate_is_flagged_for_attention(self):
        from spatialmind.pilot.xenium import _run_qc

        dataset = SpatialDataset(
            sample_id="X", source_path="x", modality="xenium_spatial_rna",
            records=[SpotRecord("X", 0.0, 0.0, "c", {"A": 1.0}, cell_id="c1")],
            metadata={"fraction_transcripts_decoded_q20": 0.42},
        )
        row = _run_qc(dataset)["metrics"][0]
        self.assertEqual(row["status"], "attention")

    def test_missing_metrics_degrade_quietly(self):
        from spatialmind.pilot.xenium import _run_qc, _run_qc_markdown

        dataset = SpatialDataset(
            sample_id="X", source_path="x", modality="xenium_spatial_rna",
            records=[SpotRecord("X", 0.0, 0.0, "c", {"A": 1.0}, cell_id="c1")], metadata={},
        )
        self.assertEqual(_run_qc(dataset)["status"], "unavailable")
        self.assertEqual(_run_qc_markdown({"run_qc": _run_qc(dataset)}), [])

    def test_successful_descriptive_run_is_not_headlined_as_blocked(self):
        if not os.path.isdir(XENIUM_LYMPH):
            self.skipTest("local Xenium dataset not available")
        from spatialmind.pilot.xenium import run_pilot

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "p"
            result = run_pilot(XENIUM_LYMPH, out, max_records=200, review_artifacts=False)
            report = (out / "validated_xenium_pilot_report.md").read_text()
            # The gate code is still reported, but it is not the headline.
            self.assertIn("Xenium Analysis Report", report)
            self.assertIn("Outcome:", report)
            self.assertTrue(result["status"].startswith("blocked"))
            # Review templates are skipped when not doing a review.
            self.assertEqual(result["expert_label_template"], "")
            self.assertFalse((out / "expert_label_template.csv").exists())


class DescriptiveReportSplitTests(unittest.TestCase):
    def test_validation_sections_are_dropped_only_from_descriptive_reports(self):
        from spatialmind.pilot.xenium import _filter_descriptive_sections

        lines = [
            "# Report", "", "## Status", "- ok",
            "## Descriptive Analysis (no expert labels required)", "content",
            "## Claim Ledger", "refused",
            "## Typed Tool Plan", "plan",
            "## Limitations", "limits",
        ]
        descriptive = {"status": "blocked_missing_validation_inputs",
                       "descriptive_analysis": {"status": "computed"}}
        kept = _filter_descriptive_sections(lines, descriptive)
        self.assertIn("## Descriptive Analysis (no expert labels required)", kept)
        self.assertIn("## Limitations", kept)
        self.assertNotIn("## Claim Ledger", kept)
        self.assertNotIn("## Typed Tool Plan", kept)

        # Validated runs keep everything: those sections carry real content there.
        validated = {"status": "validated_ready", "descriptive_analysis": {"status": "computed"}}
        self.assertEqual(_filter_descriptive_sections(lines, validated), lines)

        # A run with no descriptive results is left alone too.
        nothing = {"status": "blocked_analysis_backend", "descriptive_analysis": {"status": "not_run"}}
        self.assertEqual(_filter_descriptive_sections(lines, nothing), lines)

    def test_marker_hints_name_the_family_not_the_cell_type(self):
        from spatialmind.pilot.xenium import _cluster_marker_hints

        hints = _cluster_marker_hints({
            "0": ["CD68", "AIF1", "C1QA", "CD74"],
            "1": ["MOG", "MOBP", "CLDN11", "PLP1"],
            "2": ["PDGFRA", "CSPG4", "VCAN", "BCAN"],
            "3": ["SOMEGENE", "ANOTHER"],
        })
        self.assertIn("myeloid", hints["0"])
        self.assertIn("oligodendrocyte", hints["1"])
        self.assertIn("opc", hints["2"])
        # No match stays silent rather than guessing.
        self.assertNotIn("3", hints)
        # Wording must not assert an identity.
        self.assertNotIn("cell type", " ".join(hints.values()).lower())

    def test_every_label_lineage_is_marker_detectable(self):
        """A lineage a reference label maps to must be reachable from markers.

        Otherwise cells of that lineage can never be flagged as absent from a
        reference, which is what the coverage check exists to catch.
        """
        from spatialmind.tools.implementations import LABEL_LINEAGE_KEYWORDS, LINEAGE_MARKERS

        label_lineages = {lineage for _keyword, lineage in LABEL_LINEAGE_KEYWORDS}
        self.assertEqual(label_lineages - set(LINEAGE_MARKERS), set())

    def test_opc_and_oligodendrocyte_stay_distinguishable(self):
        from spatialmind.tools.implementations import marker_lineage

        self.assertEqual(marker_lineage({"PDGFRA": 6.0, "CSPG4": 5.0, "VCAN": 4.0})[0], "opc")
        self.assertEqual(marker_lineage({"MOG": 8.0, "MOBP": 7.0, "CLDN11": 6.0, "OPALIN": 5.0})[0], "oligodendrocyte")


class TimingQualityTests(unittest.TestCase):
    def test_contended_run_is_flagged(self):
        """Reproduces the observed case: a stage that takes ~150s idle measured
        2032s while the test suite ran concurrently. Wall time alone made a
        healthy dataset look pathological."""
        from spatialmind.pilot.xenium import _timing_quality

        quality = _timing_quality(wall_seconds=2032.0, cpu_seconds=150.0)
        self.assertEqual(quality["status"], "contended")
        self.assertGreater(quality["wall_to_cpu_ratio"], 10)
        self.assertIn("should not be compared", quality["note"])

    def test_parallel_run_is_not_mistaken_for_contention(self):
        """Multi-threaded work spends more CPU than wall time; that is healthy."""
        from spatialmind.pilot.xenium import _timing_quality

        quality = _timing_quality(wall_seconds=129.9, cpu_seconds=218.8)
        self.assertEqual(quality["status"], "clean")
        self.assertLess(quality["wall_to_cpu_ratio"], 1.0)

    def test_short_runs_are_not_flagged(self):
        """A brief run can show a high ratio from startup noise alone."""
        from spatialmind.pilot.xenium import _timing_quality

        self.assertEqual(_timing_quality(wall_seconds=5.0, cpu_seconds=1.0)["status"], "clean")

    def test_zero_cpu_time_does_not_divide_by_zero(self):
        from spatialmind.pilot.xenium import _timing_quality

        self.assertEqual(_timing_quality(wall_seconds=10.0, cpu_seconds=0.0)["wall_to_cpu_ratio"], 0.0)


class ControlProbeExclusionTests(unittest.TestCase):
    def test_xenium_control_families_are_recognised(self):
        from spatialmind.tools.implementations import is_control_feature

        for name in ("UnassignedCodeword_0045", "NegControlProbe_00042", "NegControlCodeword_0500",
                     "BLANK_0006", "antisense_PROK2", "DeprecatedCodeword_123", "NegControlProbe"):
            self.assertTrue(is_control_feature(name), name)

    def test_real_genes_sharing_a_prefix_are_not_excluded(self):
        """Prefix matching alone would drop real genes; the convention requires a
        separator or digits after the prefix."""
        from spatialmind.tools.implementations import is_control_feature

        for name in ("AQP4", "CD3D", "KRT6B", "NEGR1", "BLANKET_GENE", "ANTISENSEGENE"):
            self.assertFalse(is_control_feature(name), name)

    def test_control_probes_are_kept_out_of_the_expression_matrix(self):
        from spatialmind.tools.implementations import expression_feature_names

        dataset = SpatialDataset(
            sample_id="X", source_path="x", modality="xenium_spatial_rna",
            records=[SpotRecord("X", 0.0, 0.0, "c", {
                "AQP4": 5.0, "CD3D": 3.0, "GJA1": 2.0,
                "UnassignedCodeword_0045": 9.0, "NegControlProbe_00042": 8.0, "BLANK_0006": 7.0,
                "CELL_AREA": 400.0,
            }, cell_id="c1")],
        )
        kept = expression_feature_names(dataset)
        self.assertEqual(sorted(kept), ["AQP4", "CD3D", "GJA1"])

    def test_fixtures_of_only_control_features_still_return_something(self):
        from spatialmind.tools.implementations import expression_feature_names

        dataset = SpatialDataset(
            sample_id="X", source_path="x", modality="xenium_spatial_rna",
            records=[SpotRecord("X", 0.0, 0.0, "c", {"BLANK_0001": 1.0, "BLANK_0002": 2.0}, cell_id="c1")],
        )
        self.assertEqual(len(expression_feature_names(dataset)), 2)

    def test_real_panels_lose_only_control_features(self):
        if not os.path.isdir(XENIUM_LYMPH):
            self.skipTest("local Xenium dataset not available")
        from spatialmind.ingestion import load_xenium
        from spatialmind.tools.implementations import expression_feature_names, is_control_feature

        dataset = load_xenium(XENIUM_LYMPH, max_records=200)
        kept = set(expression_feature_names(dataset))
        dropped = set(dataset.genes) - kept
        self.assertTrue(dropped, "expected control probes in a real Xenium panel")
        for gene in dropped:
            self.assertTrue(
                is_control_feature(gene) or gene.upper() in {"TRANSCRIPT_COUNTS", "TOTAL_COUNTS", "CELL_AREA", "NUCLEUS_AREA"},
                "dropped a biological gene: %s" % gene,
            )


class ClusterConfidenceTests(unittest.TestCase):
    def test_micro_clusters_are_flagged(self):
        """A 34-cell cluster is not a peer of a 51,929-cell one.

        Reproduces the observed breast full-section result, where five of
        fourteen clusters held between 34 and 186 of 209,467 cells and carried
        degenerate overlapping markers.
        """
        from spatialmind.pilot.xenium import _cluster_confidence

        counts = {"6": 51929, "0": 42351, "7": 31835, "1": 23469, "9": 20804,
                  "4": 16798, "5": 15685, "3": 3787, "2": 1083,
                  "13": 186, "10": 116, "11": 88, "12": 80, "8": 34}
        result = _cluster_confidence(counts)
        self.assertEqual(result["status"], "computed")
        self.assertEqual(set(result["low_confidence_clusters"]), {"13", "10", "11", "12", "8"})
        self.assertNotIn("2", result["low_confidence_clusters"])  # 1083 cells clears both floors
        self.assertGreater(result["fraction_cells_in_well_populated"], 0.97)

    def test_balanced_clustering_flags_nothing(self):
        from spatialmind.pilot.xenium import _cluster_confidence

        result = _cluster_confidence({"0": 5000, "1": 4000, "2": 3000, "3": 2000})
        self.assertEqual(result["low_confidence_clusters"], [])
        self.assertEqual(result["fraction_cells_in_well_populated"], 1.0)

    def test_empty_counts_do_not_crash(self):
        from spatialmind.pilot.xenium import _cluster_confidence

        self.assertEqual(_cluster_confidence({})["status"], "unavailable")

    def test_silhouette_reading_distinguishes_separation_quality(self):
        from spatialmind.pilot.xenium import _silhouette_reading

        poor = _silhouette_reading(-0.0013, 0.7384)
        typical = _silhouette_reading(0.05, 0.72)
        good = _silhouette_reading(0.141, 0.786)
        self.assertIn("overlap almost completely", poor)
        self.assertIn("routine", typical)
        self.assertIn("reasonably separated", good)
        # Distinct readings, and a missing value stays silent rather than guessing.
        self.assertEqual(len({poor, typical, good}), 3)
        self.assertEqual(_silhouette_reading(None, 0.7), "")


class SelfContainedReportTests(unittest.TestCase):
    def test_figures_are_embedded_so_the_report_survives_being_emailed(self):
        """The HTML report is what a reviewer is sent.

        Referencing figures by relative filename means every image breaks the
        moment the file leaves its directory, which is exactly what happens when
        it reaches a domain expert.
        """
        from spatialmind.pilot.xenium import _figure_html

        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "fig.png"
            # Minimal valid PNG.
            png.write_bytes(bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
                "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
            ))
            markup = _figure_html(str(png))
            self.assertIn('src="data:image/png;base64,', markup)
            self.assertNotIn('src="fig.png"', markup)

    def test_svg_uses_the_right_mime_type(self):
        from spatialmind.pilot.xenium import _figure_html

        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / "fig.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>')
            self.assertIn("data:image/svg+xml;base64,", _figure_html(str(svg)))

    def test_oversized_and_missing_figures_fall_back_to_a_link(self):
        """A single huge figure must not make the report itself unopenable."""
        from spatialmind.pilot import xenium as module

        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.png"
            big.write_bytes(b"\x00" * 1024)
            original = module.MAX_INLINE_FIGURE_BYTES
            try:
                module.MAX_INLINE_FIGURE_BYTES = 100  # force the cap
                self.assertEqual(module._figure_data_uri(str(big)), "")
                self.assertIn('src="big.png"', module._figure_html(str(big)))
            finally:
                module.MAX_INLINE_FIGURE_BYTES = original
        # A path that does not exist degrades to the filename rather than raising.
        self.assertEqual(module._figure_data_uri("/nonexistent/none.png"), "")

    def test_interactive_html_stays_a_link(self):
        """Only images inline; the viewer is a separate multi-megabyte artifact."""
        from spatialmind.pilot.xenium import _figure_html

        markup = _figure_html("explorer_lite_viewer.html")
        self.assertIn("<a href=", markup)
        self.assertNotIn("data:image", markup)
