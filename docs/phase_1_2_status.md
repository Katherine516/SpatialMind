# SpatialMind Build Status

## Current Status

SpatialMind now implements the first production architecture layers plus the focused v7 MVP plan. The project has moved from a dependency-light proof of concept into a runnable local research agent with real spatial omics ingestion paths, optional scientific backends, provenance, reports, and evaluation gates.

## Completed Foundation

- Repository structure, environment files, `requirements.txt`, `environment.yml`, `.env.example`, `.pre-commit-config.yaml`, `.importlinter`, Docker Compose placeholders, and Makefile tasks.
- Layered packages: `contracts`, `agent`, `api`, `ingestion`, `memory`, `storage`, `tools`, `workflows`, and `viz`.
- Shared contracts for artifacts, spatial data, tool I/O, claims, reports, memory items, method citations, readiness, and responses.
- Deterministic agent loop plus MVP mode through `SpatialAgent(mvp_mode=True)`.
- Tool registry with full/default and v7 MVP registries.
- Local JSON memory, run storage, provenance hashes, replay support, report builders, and visualization outputs.

## Completed Ingestion and Runtime Work

- Tidy CSV and manifest ingestion.
- Optional H5AD/AnnData ingestion.
- Xenium directory ingestion with `cells.csv.gz`, metrics, morphology metadata, panel metadata, and `cell_feature_matrix.h5` feature loading.
- loaders for scRNA, scATAC, and Xenium cell-by-feature workflows.
- Full `.venv` environment installed from `requirements.txt`.
- Full runtime validation with Scanpy, Squidpy, AnnData, h5py, NumPy, SciPy, Pandas, Matplotlib, Seaborn, and related dependencies.

## Completed Agent and Analysis Work

- MVP workflows: scRNA-lite, scATAC-lite, Xenium-primary, and reference-assisted annotation.
- MVP tools: QC/clustering, annotation, marker detection, feature overlay, user-region summary, and cell-neighborhood enrichment.
- Typed `QualityMetrics` contract attached to tool results for QC, diagnostics, and statistical evidence.
- Real optional wrappers for Scanpy differential expression, Scanpy spatial clustering, Scanpy highly variable genes, and Squidpy neighborhood enrichment.
- Grounding caveats for targeted Xenium panels, transferred labels, scATAC accessibility inference, and deferred v1.0 workflows.

## Completed Output Work

- Cluster-style SVG, PNG, and interactive HTML spatial visualizations.
- Structured HTML reports.
- Dataset readiness reports.
- Methods/citation-aware report sections.
- Local run records with md5 fields for input and output artifacts.
- Xenium breast MVP run outputs under `outputs/xenium_breast_mvp/`.

## Current Validation

- Unit tests: 45/45 passing in the full environment.
- Legacy eval: 15/15 passing, mean score 1.0000.
- MVP eval: 10/10 passing, mean score 1.0000.
- Import boundary checks: passing.
- Full environment package check: passing.

## Remaining Scientific Gaps

- Current breast labels are marker-rule MVP labels, not expert-validated annotations.
- Full reference label transfer needs a real Scanpy ingest or scANVI backend before returning to MVP mode.
- Motif/TF activity needs real chromVAR/pychromVAR validation before returning to MVP mode.
- Evaluation cases are still small and mostly planner-oriented.
- The training corpus does not yet contain expert-labeled query-plan-result examples.
- Production storage, asynchronous batch execution, and frontend UI remain future work.

## Next Phase

The next phase is **expert-label-ready Xenium MVP**:

- run all local Xenium datasets through the same report path,
- add validated annotation/reference transfer for at least one tissue,
- expand MVP eval from 10 cases toward 50 then 100,
- curate supervised training records,
- replace marker-rule labels with confidence-scored annotation outputs.
