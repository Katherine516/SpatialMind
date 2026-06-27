# SpatialMind MVP Plan v4 Review

Reviewed plan: `/Users/dongli/Desktop/Spatial_omics/SpatialMind/spatialmind mvp plan v4.html`

## Assessment

The v4 plan is a useful correction from the earlier architecture: it narrows the MVP to three standalone cell-by-feature workflows and one optional bridge:

- scRNA-seq standalone,
- scATAC-seq standalone,
- Xenium standalone,
- optional scRNA/scATAC reference label transfer onto Xenium.

That scope is more practical than trying to build every spatial/multi-omics method at once. The strongest design decision is the shared `CellByFeatureContract`: scRNA, scATAC gene activity, and Xenium targeted spatial RNA all share a cell-by-feature matrix shape, while subtype fields preserve the scientific differences that matter.

## Ambiguity Noted

The plan says the MVP has 9 tools, but the detailed tool table names 8:

1. `qc_and_cluster`
2. `annotation`
3. `differential_expression`
4. `feature_overlay`
5. `trajectory_inference`
6. `motif_tf_activity`
7. `cell_neighborhood_enrichment`
8. `reference_label_transfer`

I implemented the eight named tools exactly rather than inventing a ninth tool without a scientific role. The full registry still preserves future v1.0 scaffolds, but the explicit MVP registry exposes only those named tools.

## Implemented

- Added `CellByFeatureContract` and `SegmentationRef` to `spatialmind.contracts`.
- Added scRNA, scATAC, and Xenium MVP loaders under `spatialmind/ingestion/loaders/`.
- Added `validate_cell_by_feature_contract()` for contract validation.
- Extended readiness reports with v4 workflow checks and honesty warnings:
  - scATAC gene activity is accessibility-inferred, not expression.
  - Xenium is a targeted panel; absent genes are not measured, not unexpressed.
  - deconvolution is deferred to v1.0 in MVP mode.
- Added v4 MVP tool wrappers:
  - `qc_and_cluster`
  - `annotation`
  - `feature_overlay`
  - `motif_tf_activity`
  - `cell_neighborhood_enrichment`
  - `reference_label_transfer`
  - plus existing `differential_expression` and `trajectory_inference`.
- Added `build_mvp_registry()` while keeping `build_full_registry()`/`build_default_registry()` for backward compatibility.
- Added `spatialmind/workflows/` with:
  - `SCRNA_STANDALONE`
  - `SCATAC_STANDALONE`
  - `XENIUM_STANDALONE`
  - `INTEGRATION_MODE`
- Added `SpatialAgent(mvp_mode=True)` for the trimmed v4 planner/refusal policy.
- Added `agent/grounding.py` with MVP claim-softening and type-honesty caveats.
- Added v4 visualization routes for the eight MVP renderer types.
- Added local MVP JSON run records with input/artifact/figure/table md5 fields.
- Added automatic report limitations generated from run facts.
- Added `eval/mvp_cases/` with 10 MVP eval cases and `eval.runner --mvp`.

## Validation

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests eval` passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m unittest discover -s tests -p 'test_*.py'` passed 29/29 tests.
- Legacy eval: `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --out outputs/eval_report.json` passed 15/15 with mean score 1.0000.
- MVP eval: `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --mvp --cases eval/mvp_cases --out outputs/mvp_eval_report.json` currently passes 10/10 with mean score 1.0000.
- `.venv/bin/lint-imports` passed: 3 import contracts kept, 0 broken.
- `.venv/bin/python -m spatialmind.versioning` passed.
- `.venv/bin/python -m pip check` passed.

## Remaining Gaps

- scRNA/scATAC loaders currently reuse the existing generic table/H5AD loader and set MVP subtype metadata. Real 10x scRNA/scATAC H5 matrix parsing should be added next.
- `motif_tf_activity` is a prototype chromVAR-style scaffold, not real chromVAR/pychromVAR yet.
- `reference_label_transfer` checks shared features and confidence but is not yet Scanpy ingest/scANVI.
- The MVP eval cases use the current demo fixture with query-based assay hints. Real public scRNA/scATAC/Xenium benchmark datasets are still needed for accuracy gates.
- The plan's full pydantic-v2 contract strictness is still a future migration; current contracts remain dependency-light dataclasses for base-environment compatibility.

## Latest Run Update

The v4 MVP has now been exercised on a real local Xenium breast biomarker dataset:

- dataset: `data/Human_Breast_Biomarkers_S1_Top_outs`
- records sampled: 6,000
- targeted panel features loaded: 390
- tools run: `qc_and_cluster`, `annotation`, `differential_expression`, `cell_neighborhood_enrichment`
- outputs: `outputs/xenium_breast_mvp/`

The run generated a report, static PNG/SVG cluster-style figures, interactive HTML, JSON tool outputs, and an md5-backed MVP run record. The result validates the agent execution path and visualization style, but the current cell labels remain marker-rule MVP labels and should be replaced by validated annotation before being used as biological ground truth.
