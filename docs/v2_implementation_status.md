# SpatialMind v2 Implementation Status

## Completed in This Upgrade

- Re-read and evaluated the v2 production build plan.
- Added v2 comparison document: `docs/plan_v1_v2_comparison.md`.
- Expanded `pyproject.toml` optional `full` dependencies for production spatial omics tooling.
- Added comprehensive workstation dependencies in `requirements.txt`.
- Added Docker Compose batch profiles for Celery worker and Flower.
- Added `spatialmind/batch/` with a synchronous local `BatchEngine` and Celery app placeholder.
- Added `BatchIngestionConfig`, `SampleConfig`, `BatchIngestionPipeline`, and `BatchIngestionReport`.
- Added feature metadata detection during ingestion.
- Added `QCReportBuilder` and `QCGate`; the dashboard now includes metric distributions, spatial QC overlays, a filtration waterfall, warnings, and approval guidance.
- Added optional H5AD ingestion through AnnData.
- Added optional Xenium `cell_feature_matrix.h5` loading through h5py, with barcode matching and per-cell top gene features.
- Added conservative marker-rule annotation fallback for H5AD and Xenium expression records.
- Added all 14 new v2 tools to the registry, increasing total registry tools from 8 to 22.
- Added `DataModalityError`.
- Added dependency-light scaffolds for the 14 new algorithm callables.
- Added optional Scanpy/Squidpy wrappers for differential expression, variable-gene ranking, spatial clustering, and neighborhood enrichment.
- Added `ModalityFuser` and `FusedDataset`.
- Added modality prompts and a tool dependency graph to the agent loop.
- Added `UserPriorStore`, `UserPrior`, `PriorType`, and `PriorSource`.
- Added `VizRouter` with all 15 v2 visualization specs.
- Upgraded static and interactive spatial visualizations to a cluster-style layout.
- Added `ReportBuilder` and `ReportPaths`.
- Extended `RunRecord` with batch/fusion fields and added `ReportRecord`.
- Added CLI run replay support via `--replay-run-id`.
- Extended API with QC approval and batch endpoints.
- Extended eval summary with modality/tool coverage.

## Verification

The dependency-light path remains operational, and the full environment has also been installed and validated:

```text
Unit tests: 45/45 passing in the full environment
Legacy eval suite: 15/15 passing, mean score 1.0000
MVP eval suite: 10/10 passing, mean score 1.0000
Compile check: passing
Full environment pip check: passing
Real backend validation: Scanpy DE/clustering/HVG and Squidpy neighborhood enrichment passing
```

## Current Scientific Blockers

The v2 interfaces exist and several real backends now work. Real biological use still depends on:

- adding confidence/evidence reporting for biological cell-type annotation,
- adding full production plotting/export backends beyond dependency-light SVG/HTML,
- expanding eval cases beyond the current 15 legacy cases and 10 MVP cases,
- replacing marker-rule labels with Cell Ontology-grounded expert labels or validated reference-transferred labels.

## Next Engineering Step

The next engineering step is to run the current v7/v11 Xenium-primary workflow across local datasets with expert/user labels where available: add Cell Ontology-grounded validated annotation, user-provided region labels, expanded MVP eval coverage, and shared report schemas.

## MVP Plan Addendum

The v7 MVP supersedes the earlier v4 active tool policy. Current MVP work focuses on Xenium targeted RNA as the primary workflow, scRNA/scATAC-lite marker workflows as support modes, and reference-assisted annotation without full label-transfer claims. This narrower scope is implemented through `spatialmind/workflows/`, `CellByFeatureContract`, `QualityMetrics`, `build_mvp_registry()`, and `SpatialAgent(mvp_mode=True)`.
