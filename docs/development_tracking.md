# SpatialMind Development Tracking

This log tracks implementation work against the current v2 build plan. It is updated as development proceeds so decisions, blockers, and verification steps remain visible.

## 2026-05-24

### Step 1: Create Development Tracking Log

Status: Complete

Work started:

- Created this tracking document.
- Next actions are to inspect optional dependency availability and local Xenium H5 matrix structure before changing ingestion behavior.

Verification:

- File created at `docs/development_tracking.md`.

### Step 2: Inspect Dependency and Xenium Matrix Readiness

Status: Complete

What we found:

- The current lightweight Python environment can run the existing agent and tests, but does not include `h5py`, `anndata`, `scanpy`, `squidpy`, `spatialdata`, or `spatialdata-io`.
- The bundled workspace Python includes `numpy` and `pandas`, but not the HDF5/AnnData stack needed to validate gene-matrix loading end to end.
- The local Xenium datasets include `cell_feature_matrix.h5` files and matrix-like HDF5 keys: `matrix`, `barcodes`, `data`, `indices`, `indptr`, `shape`, and `features/name`.
- The local Xenium Zarr zip stores the same sparse matrix family under `cell_features`, but its chunks use Blosc/LZ4 compression, so it is not a good dependency-free parsing route.

Decision:

- Implement the Xenium expression adapter as an optional `h5py` path. The agent will continue to ingest cell centroids/count summaries without heavy dependencies, and will automatically attach per-cell gene features when `h5py` is installed.

Verification:

- Confirmed the H5/Zarr structure from local files and updated the implementation plan accordingly.

### Step 3: Implement Xenium Gene Matrix Adapter

Status: Complete

Work started:

- Added an optional `h5py` loader for Xenium `cell_feature_matrix.h5`.
- Matched selected `cells.csv.gz` cell IDs to H5 barcodes.
- Attached top expressed genes per loaded cell using `max_features_per_record`.
- Preserved the dependency-light fallback path when `h5py` is unavailable.

Implementation details:

- `DataIngestionLayer.load_xenium_directory()` now accepts `max_features_per_record`.
- The ingestion pipeline forwards `IngestionConfig.max_features_per_record` into the Xenium adapter.
- Dataset metadata now includes a `gene_matrix` block with loader name, requested cells, matched cells, matrix cell count, feature count, and marker-rule annotation count.
- When `h5py` is missing, the loader records the blocker in dataset notes and still returns usable centroid/count-summary records.

Validation on local datasets:

- Human Brain Glioblastoma: 12/12 sampled cells matched H5 barcodes; 40,887 matrix cells; 541 features; 143 loaded features after top-feature truncation.
- Human Healthy Brain: 12/12 sampled cells matched H5 barcodes; 24,406 matrix cells; 541 features; 117 loaded features after top-feature truncation.
- Human Non-diseased Lymph Node: 12/12 sampled cells matched H5 barcodes; 377,985 matrix cells; 541 features; 143 loaded features after top-feature truncation.

Verification:

- `python3 -m unittest tests.test_spatialmind` passed with the base dependency-light environment.
- `PYTHONPATH=/private/tmp/spatialmind_h5py python3 -m unittest tests.test_spatialmind` passed with temporary `h5py`.
- `python3 -m eval.runner` passed 15/15 cases with mean score 1.0000.
- `PYTHONPATH=/private/tmp/spatialmind_h5py python3 -m eval.runner` passed 15/15 cases with mean score 1.0000.

### Step 4: Add Baseline Expression Annotation Support

Status: Complete

Work completed:

- Added a conservative marker-rule baseline for broad cell categories.
- Xenium records can now be labeled after H5 expression features attach.
- H5AD ingestion now uses obs annotations when present and falls back to the same marker-rule baseline when no known annotation column is available.
- Annotation caveats are recorded in dataset notes rather than presented as expert-validated labels.

Validation on local datasets:

- Glioblastoma sample produced broad labels including Myeloid cell, Neural/Glial cell, T/NK cell, and Unannotated cell.
- Healthy brain sample produced broad labels including Endothelial cell, Fibroblast/Stromal cell, Neural/Glial cell, and Unannotated cell.
- Lymph node sample produced broad B cell and T/NK cell labels for the sampled cells.

### Step 5: Update Tests, Evaluation, and Next-Step Docs

Status: Complete

Work completed:

- Added a regression assertion that Xenium ingestion reports the H5 matrix loader metadata.
- Updated next-step documentation to separate completed v0.3 work from the remaining production hardening tasks.
- Verified the implementation in both base and temporary-`h5py` environments.

Final verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests` passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m unittest tests.test_spatialmind` passed 17/17 tests.
- `PYTHONPATH=/private/tmp/spatialmind_h5py PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m unittest tests.test_spatialmind` passed 17/17 tests.
- `python3 -m eval.runner` passed 15/15 eval cases with mean score 1.0000.
- `PYTHONPATH=/private/tmp/spatialmind_h5py PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner` passed 15/15 eval cases with mean score 1.0000.

Remaining production tasks:

- Add a reproducible locked environment for the full spatial omics stack.
- Add confidence/evidence reporting for marker-rule labels.
- Replace prototype analysis functions with real Scanpy/Squidpy wrappers.
- Expand eval coverage from 15 cases toward the planned 100-case suite.

### Step 6: Add Full Environment Setup and Cluster-Style Visualization

Status: Complete

Work started:

- Added an initial full requirements file for installing the SpatialMind research stack through `pip`.
- Added `environment.yml` for creating a Conda environment with Python, HDF5, numeric dependencies, and the project extras.
- Added a Makefile install target.
- Upgraded the static and interactive spatial renderers to use a cluster-style layout matching the requested reference pattern: title, spatial axes, bordered spatial panel, and categorical legend on the right.
- Added a regression test that checks the SVG contains the cluster title, `spatial1`, `spatial2`, and cell-type legend text.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests` passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m unittest tests.test_spatialmind` passed 18/18 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner` passed 15/15 eval cases with mean score 1.0000.

### Step 9: Reassess v2 Plan Position and Upgrade QC Dashboard

Status: Complete

Plan assessment:

- Phase 1 foundation is mostly implemented in dependency-light form: package structure, ingestion contracts, Xenium/H5AD adapters, batch ingestion, QC gate, and QC dashboard exist.
- Phase 2 tools are partially implemented: all 22 tools are registered; four have optional Scanpy/Squidpy backends; the rest remain scaffolded.
- Phase 3 agent core is scaffolded: modality prompts, dependency graph, structured tool traces, user priors, and replay support exist, but correction replay and production memory stores are not complete.
- Phase 4 output layers are partially implemented: cluster-style SVG/HTML visualization, report builders, provenance, API, and CLI exist; full Plotly/Vitessce/PDF production outputs remain future work.
- Phase 5 production is not implemented beyond Docker Compose service placeholders.

Work started:

- Upgraded `QCReportBuilder` to include v2-required sections in a dependency-light HTML dashboard:
  - metric distributions for nUMI, nGenes, and pct_mito,
  - spatial QC overlays for nUMI and pct_mito,
  - filtration waterfall,
  - warnings,
  - QC approval guidance.
- Added regression checks that the generated QC dashboard contains the new sections.
- Updated `docs/v2_implementation_status.md` so it reflects the current implementation instead of the earlier pre-Xenium/pre-wrapper state.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests` passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m unittest tests.test_spatialmind` passed 18/18 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner` passed 15/15 eval cases with mean score 1.0000.
- Generated preview dashboard at `outputs/qc_preview/qc_dashboard.html`.
- Generated preview artifact at `outputs/visualization_preview/spatial_distribution.svg`.

### Step 7: Rename Runtime Requirements and Add Real Scanpy/Squidpy Wrappers

Status: Complete

Work started:

- Replaced the initial full requirements name with a clearer workstation install filename at that stage.
- Updated the Makefile install target to use that workstation requirements file.
- Added graph-clustering and file-format dependencies needed by the real wrappers: `igraph`, `leidenalg`, `matplotlib`, `pyarrow`, and `scikit-learn`.
- Expanded `README.md` with a fuller interpretation of the agent structure, data contract, execution flow, and optional analysis backends.
- Added optional Scanpy/Squidpy paths for:
  - Scanpy `rank_genes_groups` differential expression.
  - Scanpy neighbors plus Leiden spatial clustering.
  - Scanpy highly variable gene ranking.
  - Squidpy spatial neighbors plus neighborhood enrichment.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests` passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m unittest tests.test_spatialmind` passed 18/18 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner` passed 15/15 eval cases with mean score 1.0000.
- Real Scanpy/Squidpy execution still requires installing the workstation requirements file; the current local base environment correctly exercises the fallback path.

### Step 8: Rename and Expand Requirements File

Status: Complete

Work started:

- Renamed the workstation install file to the conventional `requirements.txt`.
- Made the requirements explicit instead of relying mainly on `-e .[full,dev]`.
- Added comprehensive groups for numerical processing, tables, HDF5/Zarr, single-cell/spatial omics, graph clustering, visualization, microscopy images, reports, API/background jobs, vector memory, LLM adapters, and developer tooling.
- Updated README install instructions and Makefile target to use `python3 -m pip install -r requirements.txt`.

Verification:

- Confirmed no stale `requirements-agent`, `requirements-full`, `install-agent`, or `install-full` references remain in README, Makefile, docs, environment, or project metadata.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests` passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m unittest tests.test_spatialmind` passed 18/18 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner` passed 15/15 eval cases with mean score 1.0000.

### Step 10: Install Full Runtime Environment and Validate Real Backends

Status: Complete

Work started:

- Created a local `.venv` and installed the full `requirements.txt` runtime for the agent.
- Corrected package names to their active PyPI distributions: `decoupler`, `liana`, `omnipath`, and `vitessce`.
- Added compatibility pins required by the installed spatial stack: `numpy<2`, `setuptools<81`, `decoupler<1.9`, and `opencv-python<4.13`.
- Mirrored the dependency corrections into `pyproject.toml` full extras where applicable.
- Added `scripts/validate_real_backends.py` to validate real Scanpy/Squidpy execution and Xenium HDF5 matrix ingestion.
- Made the Squidpy neighborhood enrichment wrapper accept an explicit `n_jobs` parameter and report it in metrics.
- Made the backend validation script record pass/fail per wrapper so one backend failure does not hide other results.
- Updated ingestion tests so the H5AD fallback guidance is tested by explicitly simulating missing `anndata`, which keeps tests valid in the full installed environment.
- Ignored local install artifacts (`.venv/` and `*.egg-info/`) in `.gitignore`.

Validation results:

- `python3 -m venv .venv` created the local environment.
- `.venv/bin/python -m pip install -r requirements.txt` completed after dependency-name and compatibility-pin corrections.
- `.venv/bin/python -m pip check` passed with no broken requirements.
- Import validation passed for `numpy 1.26.4`, `scipy 1.13.1`, `pandas 2.3.3`, `anndata 0.10.8`, `scanpy 1.10.3`, `squidpy 1.6.1`, `h5py 3.14.0`, `sklearn 1.6.1`, `matplotlib 3.9.4`, and `seaborn 0.13.2`.
- `scripts/validate_real_backends.py` passed for Scanpy differential expression, Scanpy spatial clustering, Scanpy highly variable gene ranking, and Squidpy neighborhood enrichment.
- The same validation loaded the Xenium lymph node dataset from `cell_feature_matrix.h5`, matching 30 requested cells against a 377,985-cell by 541-feature matrix sample.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m compileall spatialmind tests scripts` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` passed 18/18 tests.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m eval.runner` passed 15/15 eval cases with mean score 1.0000.

Notes:

- Squidpy neighborhood enrichment uses a multiprocessing manager. It fails inside the restricted sandbox with a local socket bind permission error, but passes when the same validation is run outside the sandbox.
- The full environment emits non-fatal warnings from PyArrow CPU probing, `xarray_schema`/`pkg_resources`, Numba, and mixed OpenMP runtimes. These do not currently break validation but should be monitored before production deployment.

### Step 11: Review Layer Plan and Add Contract/Readiness Safeguards

Status: Complete

Work started:

- Reviewed the new layer-by-layer plan at `/Users/dongli/Desktop/Spatial_omics/SpatialMind/spatialmind layer plan.html`.
- Added `docs/layer_plan_review.md` with an expert assessment, current codebase comparison, implemented changes, validation, and next build steps.
- Added the new `spatialmind/contracts/` package for layer-boundary types:
  - artifact references,
  - core/modality spatial objects,
  - tool calls/results/errors,
  - execution/no-analysis responses,
  - biological claims and grounding rules,
  - agent/viz responses,
  - readiness/ingestion reports,
  - memory items,
  - method citations.
- Added modality-aware readiness scoring in `spatialmind/ingestion/readiness.py`.
- Wired `SpatialAgent` to return a structured `NoAnalysisResponse` when a requested workflow is blocked by dataset readiness.
- Added `ResourceProfile` and `MethodCitation` metadata to the tool registry.
- Updated `ReportBuilder` so Methods content can be generated from method citations.
- Added `spatialmind/versioning.py`, `make check-versions`, `.importlinter`, and `make import-lint`.
- Added `import-linter` to `requirements.txt` and `pyproject.toml`.
- Added regression tests for contracts, claim grounding, readiness blocking, agent refusal, and tool citation metadata.

Validation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests` passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m unittest discover -s tests -p 'test_*.py'` passed 22/22 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner` passed 15/15 eval cases with mean score 1.0000.
- `.venv/bin/python -m spatialmind.versioning` passed with Scanpy 1.10.3, Squidpy 1.6.1, AnnData 0.10.8, NumPy 1.26.4, and related runtime packages.
- `.venv/bin/lint-imports` passed with 3 import-boundary contracts kept and 0 broken.

Notes:

- The attached plan recommends exact older library pins. The validated local environment is newer and working, so this step preserved the working stack and added compatibility checks instead of downgrading.
- The new contracts are dependency-light dataclasses for now. A later migration can switch internals to pydantic v2 once the public contract shape has stabilized.

### Step 12: Refine Agent To MVP Plan v4

Status: Complete

Work started:

- Reviewed `/Users/dongli/Desktop/Spatial_omics/SpatialMind/spatialmind mvp plan v4.html`.
- Added `docs/mvp_plan_v4_review.md` with scope assessment, ambiguity notes, implemented changes, validation, and remaining gaps.
- Added v4 cell-by-feature contract fields:
  - `CellByFeatureContract`,
  - assay subtypes `scrna`, `scatac_gene_activity`, `xenium_spatial_rna`,
  - feature types `gene_counts`, `gene_activity`, `targeted_panel`,
  - targeted-panel flag,
  - resolution flag,
  - segmentation reference.
- Added MVP ingestion loader entrypoints for scRNA, scATAC, and Xenium.
- Added contract validation via `validate_cell_by_feature_contract()`.
- Added v4 MVP tool wrappers and an explicit `build_mvp_registry()`.
- Added `spatialmind/workflows/` with the three standalone pipelines and integration mode.
- Added `SpatialAgent(mvp_mode=True)` so v4 deferrals/refusals do not break older scaffold compatibility.
- Added MVP grounding logic for unsupported statistical claims, transferred labels, targeted panels, and scATAC accessibility-inferred outputs.
- Added MVP visualization routes and automatic report limitations.
- Added local MVP run record JSON writing with md5 hashes.
- Added the MVP eval case set and `eval.runner --mvp`; the current MVP set contains 10 cases.

Validation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests eval` passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m unittest discover -s tests -p 'test_*.py'` passed 29/29 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --out outputs/eval_report.json` passed 15/15 legacy eval cases with mean score 1.0000.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --mvp --cases eval/mvp_cases --out outputs/mvp_eval_report.json` originally passed the active MVP eval set; the current set passes 10/10 with mean score 1.0000.
- `.venv/bin/lint-imports` passed with 3 import-boundary contracts kept and 0 broken.
- `.venv/bin/python -m spatialmind.versioning` passed.
- `.venv/bin/python -m pip check` passed.

Notes:

- The v4 plan says "9 tools" but names only 8 tools in the detailed tool sections. This step implemented the eight named tools exactly and documented the mismatch rather than inventing an unsupported ninth method.
- The full v1.0 scaffold remains available through the full/default registry; the v4 MVP behavior is isolated through `build_mvp_registry()` and `SpatialAgent(mvp_mode=True)`.

### Step 13: Run Xenium Breast MVP and Update Training Documentation

Status: Complete

Work completed:

- Ran the v4 MVP workflow on `data/Human_Breast_Biomarkers_S1_Top_outs`.
- Sampled 6,000 cells and loaded 390 targeted panel features.
- Applied conservative marker-rule MVP labels for breast-like cell classes.
- Executed `qc_and_cluster`, `annotation`, `differential_expression`, and `cell_neighborhood_enrichment`.
- Generated a report, JSON tool outputs, static PNG/SVG visualizations, interactive HTML, and an md5-backed MVP run record.
- Updated project documentation so current status, ingestion capabilities, training needs, and next steps match the implemented code.
- Added `docs/training_status.md` to distinguish current evaluation-driven agent training from future supervised fine-tuning.

Generated outputs:

- `outputs/xenium_breast_mvp/xenium_breast_mvp_report.html`
- `outputs/xenium_breast_mvp/xenium_breast_cluster.png`
- `outputs/xenium_breast_mvp/spatial_distribution.svg`
- `outputs/xenium_breast_mvp/spatial_distribution_interactive.html`
- `outputs/xenium_breast_mvp/run_summary.json`
- `outputs/xenium_breast_mvp/runs/mvp_20260607T043802Z_97b47734.json`

Training status:

- No supervised fine-tuning was performed because expert-labeled query-plan-result records are not available yet.
- The current training pass is evaluation-driven: planner behavior, tool selection, refusal behavior, grounding, and report generation are trained through tests/evals and documented gates.
- The next training milestone is a curated 50-case MVP corpus, then 100 to 200 expert-reviewed records across scRNA, scATAC, Xenium, and integration workflows.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests eval scripts` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` passed 29/29 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --out outputs/eval_report.json` passed 15/15 legacy eval cases with mean score 1.0000.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --mvp --cases eval/mvp_cases --out outputs/mvp_eval_report.json` originally passed the active MVP eval set; the current set passes 10/10 with mean score 1.0000.
- `.venv/bin/python -m pip check` passed with no broken requirements.
- `.venv/bin/lint-imports` passed with 3 import contracts kept and 0 broken.

Notes:

- The Xenium breast labels are not expert-confirmed. They are suitable for validating the agent pipeline and visualization style, but should not be treated as final biological annotations.

### Step 14: Build Expert-Label-Ready Xenium MVP Layer

Status: Complete

Work completed:

- Added `cell_id` preservation to `SpotRecord` for Xenium, H5AD, and table ingestion.
- Added `spatialmind/ingestion/labels.py` with:
  - external label table discovery,
  - label application by `cell_id`,
  - confidence summary support,
  - breast marker-rule fallback as an explicit weak-label path,
  - Xenium expert-readiness summaries,
  - expert label template writing.
- Exported label helpers through `spatialmind.ingestion`.
- Updated `scripts/run_xenium_breast_mvp.py` so external labels are used automatically when present and marker rules are reported as weak labels when not.
- Added `scripts/prepare_xenium_expert_mvp.py` to scan local Xenium datasets and write readiness reports plus label templates.
- Enriched generated label templates with 10x graph clusters, top loaded features, and marker evidence columns.
- Added tests for external label application and local Xenium readiness detection.
- Added `docs/expert_label_ready_xenium_mvp.md`.

Local data findings:

- Four local Xenium datasets were found: breast biomarkers, lymph node, healthy brain, and glioblastoma.
- All four have cell tables, HDF5 feature matrices, morphology assets, boundaries, and 10x analysis clusters.
- No external expert or validated reference-transfer label table was found in any of the four folders.
- The required next input is a biological cell-label table keyed by Xenium `cell_id`.

Generated outputs:

- `outputs/xenium_expert_mvp_readiness/summary.json`
- `outputs/xenium_expert_mvp_readiness/xenium_expert_mvp_readiness.md`
- `outputs/xenium_expert_mvp_readiness/*/expert_label_template.csv`
- updated `outputs/xenium_breast_mvp/run_summary.json` with `label_readiness`.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests scripts` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` passed 32/32 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --out outputs/eval_report.json` passed 15/15 legacy eval cases with mean score 1.0000.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --mvp --cases eval/mvp_cases --out outputs/mvp_eval_report.json` originally passed the active MVP eval set; the current set passes 10/10 with mean score 1.0000.
- `.venv/bin/lint-imports` passed with 3 import contracts kept and 0 broken.
- `.venv/bin/python -m pip check` passed with no broken requirements.

Next required input:

- Fill one generated `expert_label_template.csv` or provide a completed `expert_cell_labels.csv`/`cell_labels.csv` with at least `cell_id` and `expert_label`; `confidence` and `notes` are strongly recommended.

### Step 15: Refine Agent To MVP Plan v7

Status: Complete

Work completed:

- Reviewed `/Users/dongli/Desktop/Spatial_omics/SpatialMind/spatialmind mvp plan v7.html`.
- Added `docs/mvp_plan_v7_review.md` with a comparison against v4, scientific assessment, implemented changes, validation status, and next work.
- Refined the active MVP registry to six v7 tools:
  - `qc_and_cluster`
  - `annotation`
  - `marker_detection`
  - `feature_overlay`
  - `region_summary`
  - `cell_neighborhood_enrichment`
- Added typed `QualityMetrics` contracts and attached them to tool results through the registry execution path.
- Added `marker_detection` as the MVP marker-ranking interface and updated the Xenium breast MVP runner to use it.
- Added `region_summary` for user-provided region labels.
- Updated MVP workflows to `SCRNA_LITE`, `SCATAC_LITE`, `XENIUM_PRIMARY`, and `REFERENCE_ASSIST`.
- Updated readiness behavior so trajectory, motif/chromVAR, and full reference label transfer are deferred from the active MVP.
- Updated the MVP planner to avoid accidental annotation when the user only asks for clustering/markers.
- Updated visualization routing for v7 renderer names, including marker dotplot, feature grid, QC violins, region summary, and metrics summary routes.
- Added and updated MVP eval cases so v7 behavior is tested.
- Updated README and status docs to mark v7 as the current active MVP policy.
- Re-ran the Xenium breast MVP report path with v7 tools and removed the stale top-level `differential_expression.json` artifact from the old report run.

Scientific interpretation:

- Full label transfer, chromVAR/motif analysis, trajectory inference, CNV, ligand-receptor, deconvolution, and pathway analysis remain future/backlog methods, not active MVP claims.
- Region summaries require user-provided region labels.
- Weak marker-rule labels are valid for system exercise and visualization only; expert or validated reference labels are still required for biological claims.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests eval scripts` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` passed 34/34 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --mvp --cases eval/mvp_cases --out outputs/mvp_eval_report.json` passed 10/10 MVP eval cases with mean score 1.0000.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --out outputs/eval_report.json` passed 15/15 legacy eval cases with mean score 1.0000.
- `.venv/bin/python -m pip check` passed with no broken requirements.
- `.venv/bin/lint-imports` passed with 3 import contracts kept and 0 broken.

Generated outputs:

- `outputs/xenium_breast_mvp/xenium_breast_mvp_report.html`
- `outputs/xenium_breast_mvp/marker_detection.json`
- `outputs/xenium_breast_mvp/run_summary.json`
- `outputs/xenium_breast_mvp/runs/mvp_20260613T052116Z_dcea0ca0.json`

Next required input:

- Provide one completed expert/user label table and one region-label table for a local Xenium dataset so the v7 Xenium-primary report can move from weak-label readiness to expert-label-ready analysis.

### Step 16: Generate Local SpatialMind Training Records

Status: Complete

Work completed:

- Added `scripts/train_spatialmind_local.py` as a repeatable local training-data generation entrypoint.
- Ran the v7 MVP eval cases through `SpatialAgent(mvp_mode=True)` and converted the outputs into query-plan-result records.
- Ran a local breast Xenium weak-label pipeline record using the best currently available labels:
  - `qc_and_cluster`
  - `annotation`
  - `marker_detection`
  - `cell_neighborhood_enrichment`
- Added expert-label readiness records for all four local Xenium datasets.
- Wrote machine-readable JSONL records, a JSON summary, and a Markdown training report.
- Updated README and training-status documentation with the new training artifacts.

Training result:

- 15 records generated.
- Mean behavior score: 1.0000.
- Record types:
  - 10 MVP query-plan-result records.
  - 1 weak-label breast Xenium pipeline record.
  - 4 Xenium label-readiness records.
- Label status:
  - 6 demo/existing-label records.
  - 8 missing-expert-label records.
  - 1 weak-marker-rule-label record.

Generated outputs:

- `outputs/training/local_spatialmind_training/training_records.jsonl`
- `outputs/training/local_spatialmind_training/training_summary.json`
- `outputs/training/local_spatialmind_training/training_report.md`

Verification:

- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/train_spatialmind_local.py` completed successfully.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m compileall scripts/train_spatialmind_local.py` passed.

Scientific interpretation:

- This is behavioral agent training and training-data generation, not neural fine-tuning.
- The generated records are suitable for planner training, tool-selection regression, refusal-policy training, readiness recommendations, weak-label caveat behavior, and pipeline regression.
- The generated records are not suitable as biological ground truth until expert/user labels and region labels are added.

Next required input:

- Provide at least one completed Xenium expert/user label table keyed by `cell_id`.
- Provide one user region-label table keyed by `cell_id`.
- Add expert-reviewed interpretations for successful runs and corrections for weak/failed runs.

### Step 17: Implement Region-Label Readiness and Evaluate Agent

Status: Complete

Work completed:

- Added region-label discovery, application, and reporting helpers:
  - `discover_region_label_tables`
  - `apply_external_region_table`
  - `apply_best_available_regions`
  - `write_region_label_template`
- Accepted region file names include `cell_regions.csv`, `region_labels.csv`, `cell_region_labels.csv`, `expert_region_labels.csv`, and `regions.csv`.
- Required region columns are `cell_id` and `region`; optional columns include `region_confidence` and `notes`.
- Updated Xenium readiness summaries to separately report:
  - external expert label tables,
  - external region label tables,
  - expert-label MVP readiness,
  - region-summary MVP readiness.
- Updated `scripts/prepare_xenium_expert_mvp.py` to generate one `region_label_template.csv` for each local Xenium dataset.
- Updated `scripts/train_spatialmind_local.py` so training records include region-readiness metadata.
- Added tests for applying user region tables and writing region-label templates.

Generated outputs:

- `outputs/xenium_expert_mvp_readiness/human_breast_biomarkers_s1_top_outs/region_label_template.csv`
- `outputs/xenium_expert_mvp_readiness/xenium_v1_hlymphnode_nondiseased_section_outs/region_label_template.csv`
- `outputs/xenium_expert_mvp_readiness/xenium_v1_ffpe_human_brain_healthy_with_addon_outs/region_label_template.csv`
- `outputs/xenium_expert_mvp_readiness/xenium_v1_ffpe_human_brain_glioblastoma_with_addon_outs/region_label_template.csv`
- Updated `outputs/xenium_expert_mvp_readiness/summary.json`
- Updated `outputs/xenium_expert_mvp_readiness/xenium_expert_mvp_readiness.md`
- Updated `outputs/training/local_spatialmind_training/training_records.jsonl`
- Updated `outputs/training/local_spatialmind_training/training_summary.json`
- Updated `outputs/training/local_spatialmind_training/training_report.md`

Evaluation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind scripts tests` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` passed 36/36 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --mvp --cases eval/mvp_cases --out outputs/mvp_eval_report.json` passed 10/10 MVP eval cases with mean score 1.0000.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --out outputs/eval_report.json` passed 15/15 legacy eval cases with mean score 1.0000.
- `.venv/bin/lint-imports` passed with 3 import contracts kept and 0 broken.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/prepare_xenium_expert_mvp.py` completed successfully.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/train_spatialmind_local.py` completed successfully.

Current finding:

- All four local Xenium datasets have core assets, feature matrices, morphology, boundaries, and 10x clusters.
- None currently has an expert label table.
- None currently has a user-provided region label table.
- The agent is now ready to ingest both as soon as they are supplied, but it correctly refuses to treat weak marker-rule labels or section-level placeholder regions as biological ground truth.

Next required input:

- Fill one `expert_label_template.csv` and one `region_label_template.csv` for a selected Xenium dataset, then place the completed files in that dataset folder as `expert_cell_labels.csv` and `cell_regions.csv`.

### Step 18: Promote Validated Xenium Pilot Layer

Status: Complete

Work completed:

- Added `spatialmind/pilot/` as a reusable pilot-agent layer.
- Moved validated Xenium pilot gating and report orchestration into `spatialmind.pilot.xenium`.
- Kept `scripts/run_validated_xenium_pilot.py` as a CLI wrapper around the package API.
- Added `scripts/evaluate_xenium_pilot_readiness.py` to scan all local Xenium datasets and generate a pilot readiness scorecard.
- Added tests for blocked and validated-ready pilot gate states.
- Added `docs/validated_xenium_pilot.md`.
- Updated README/status docs so the project is described as a gated Xenium pilot agent, not only a prototype MVP.

Generated outputs:

- `outputs/xenium_validated_pilot/pilot_validation.json`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.md`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.html`
- `outputs/xenium_validated_pilot/expert_label_template.csv`
- `outputs/xenium_validated_pilot/region_label_template.csv`
- `outputs/xenium_pilot_scorecard/pilot_readiness_scorecard.json`
- `outputs/xenium_pilot_scorecard/pilot_readiness_scorecard.md`

Pilot scorecard result:

- 4 local Xenium datasets scanned.
- 0 datasets are validated-ready.
- All four are blocked by missing expert cell labels and missing user region labels.

Evaluation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind/pilot scripts tests/test_spatialmind.py` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/run_validated_xenium_pilot.py --data data/Human_Breast_Biomarkers_S1_Top_outs --out outputs/xenium_validated_pilot --max-records 2500` completed successfully and correctly returned `blocked_missing_validation_inputs`.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/evaluate_xenium_pilot_readiness.py --data-root data --out outputs/xenium_pilot_scorecard --max-records 800` completed successfully.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` originally passed the active suite; the current suite passes 45/45 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --mvp --cases eval/mvp_cases --out outputs/mvp_eval_report.json` passed 10/10 MVP eval cases with mean score 1.0000.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --out outputs/eval_report.json` passed 15/15 legacy eval cases with mean score 1.0000.
- `.venv/bin/lint-imports` passed with 3 import contracts kept and 0 broken.
- `.venv/bin/python -m pip check` passed with no broken requirements.

Next required input:

- Add `expert_cell_labels.csv` and `cell_regions.csv` to at least one Xenium dataset folder, with at least 70% loaded-cell coverage and at least two reviewed regions.

### Step 19: Promote v11 Real-Agent Controls

Status: Complete

Work completed:

- Reviewed `spatialmind mvp plan v11.html` and mapped the remaining gap from pilot MVP to real agent behavior.
- Extended `ToolCallSpec` with explicit `requires` dependencies while preserving older `depends_on` compatibility.
- Added `spatialmind.agent.runtime` with:
  - typed Xenium MVP tool-plan construction,
  - plan-time dependency validation,
  - a bounded `RunContext` for session-local execution state,
  - closed `LoopAction` structure for future adaptive retries/refusals.
- Added `spatialmind.pilot.claims` to generate an auditable claim ledger.
- Updated the validated Xenium pilot to write:
  - typed tool plan,
  - plan validation status,
  - claim ledger and claim summary,
  - automatic limitations block,
  - local MVP run record with input, artifact, figure, and table hashes.
- Updated the HTML and Markdown pilot reports so blocked runs clearly show refused biological claims instead of only reporting missing files.
- Updated docs and README to reflect the v11 promotion.

Generated outputs:

- `outputs/xenium_validated_pilot/pilot_validation.json`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.md`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.html`
- `outputs/xenium_validated_pilot/runs/mvp_20260627T061544Z_0a863b4c.json`
- `outputs/xenium_pilot_scorecard/pilot_readiness_scorecard.json`
- `outputs/xenium_pilot_scorecard/pilot_readiness_scorecard.md`

Evaluation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests/test_spatialmind.py` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_spatialmind.py'` passed 40/40 tests.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/run_validated_xenium_pilot.py --data data/Human_Breast_Biomarkers_S1_Top_outs --out outputs/xenium_validated_pilot --max-records 2500` completed successfully and correctly returned `blocked_missing_validation_inputs`.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/evaluate_xenium_pilot_readiness.py --data-root data --out outputs/xenium_pilot_scorecard --max-records 800` completed successfully.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --mvp --cases eval/mvp_cases --out outputs/mvp_eval_report.json` passed 10/10 MVP eval cases with mean score 1.0000.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --out outputs/eval_report.json` passed 15/15 legacy eval cases with mean score 1.0000.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/lint-imports` passed with 3 import contracts kept and 0 broken.

Current finding:

- The agent is structurally closer to a real agent because it now has an explicit plan, validation boundary, claim ledger, limitations, and provenance record around the Xenium pilot workflow.
- The pilot remains scientifically blocked, correctly, because all four local Xenium datasets still lack expert cell labels and user-provided region labels.

Next required input:

- Add `expert_cell_labels.csv` and `cell_regions.csv` to one Xenium folder, then rerun the pilot to unlock validated tool execution and replace the refused claim ledger with supported biological claims.

### Step 20: Add Xenium Label-Intake Validator

Status: Complete

Discussion and rationale:

- The v11 pilot can now refuse unsupported biological claims, but the next practical bottleneck is reviewer-file intake.
- To promote the agent further, SpatialMind needs a formal preflight step that checks whether `expert_cell_labels.csv` and `cell_regions.csv` are usable before running the validated pilot.
- This is the right next layer because it turns the current blocker into an operational workflow: generate templates, receive reviewer files, validate coverage/classes/regions, then unlock the pilot.

Work completed:

- Added `XeniumLabelIntakeReport`.
- Added `validate_xenium_label_intake()` for real Xenium folders.
- Added `build_xenium_label_intake_report()` as a pure scoring function for testable intake rules.
- Added `scripts/validate_xenium_label_intake.py`.
- The intake validator checks:
  - expert label table application status,
  - user region table application status,
  - label coverage threshold,
  - region coverage threshold,
  - minimum biological label diversity,
  - minimum user region diversity,
  - required Xenium assets.
- Updated README, training status, and validated pilot docs.

Generated outputs:

- `outputs/xenium_label_intake/label_intake_report.json`
- `outputs/xenium_label_intake/label_intake_report.md`

Current intake result:

- Breast Xenium intake status: `blocked_label_intake`.
- Expert label coverage: `0.0000`.
- Region coverage: `0.0000`.
- Validated biological label classes: `0`.
- Validated user region classes: `0`.

Evaluation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind scripts/validate_xenium_label_intake.py tests/test_spatialmind.py` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_spatialmind.py'` originally passed the active suite; the current suite passes 45/45 tests.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/validate_xenium_label_intake.py --data data/Human_Breast_Biomarkers_S1_Top_outs --out outputs/xenium_label_intake --max-records 2500` completed successfully.

Next required input:

- Place completed `expert_cell_labels.csv` and `cell_regions.csv` in one Xenium dataset folder.
- Rerun `scripts/validate_xenium_label_intake.py`.
- If the intake status becomes `validated_ready`, rerun `scripts/run_validated_xenium_pilot.py`.

### Step 21: Restore Comprehensive Review Visualizations in Validated Pilot

Status: Complete

Discussion and rationale:

- The validated pilot was scientifically safer than the previous weak-label MVP, but its blocked output looked too sparse because no visualizations were generated before the expert-label gate.
- The correct fix is not to run validated analysis early; it is to add a separate review-only visualization lane.
- Review figures can help experts inspect current loader labels, 10x clusters, and tissue coordinates while the claim ledger continues to refuse biological interpretation.

Work completed:

- Updated the validated Xenium pilot to always generate review-only visual artifacts:
  - current-label spatial PNG map,
  - current-label composition SVG,
  - static spatial distribution SVG,
  - interactive spatial HTML.
- Added `cell_type_counts`, `region_counts`, `review_figures`, and `figure_policy` to `pilot_validation.json`.
- Updated the Markdown and HTML pilot reports with:
  - review visualization gallery,
  - current label count table,
  - current region count table,
  - explicit review-only warning text.
- Updated README and validated pilot docs.

Generated outputs:

- `outputs/xenium_validated_pilot/review_current_label_map.png`
- `outputs/xenium_validated_pilot/review_cell_type_composition.svg`
- `outputs/xenium_validated_pilot/spatial_distribution.svg`
- `outputs/xenium_validated_pilot/spatial_distribution_interactive.html`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.html`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.md`
- `outputs/xenium_validated_pilot/pilot_validation.json`

Evaluation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind/pilot/xenium.py` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/run_validated_xenium_pilot.py --data data/Human_Breast_Biomarkers_S1_Top_outs --out outputs/xenium_validated_pilot --max-records 2500` completed successfully.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_spatialmind.py'` originally passed the active suite; the current suite passes 45/45 tests.

Current finding:

- The output is now more comprehensive and visually inspectable.
- The figures are explicitly review-only; validated biological result figures remain gated on expert labels and user regions.

### Step 22: Build Local Agent Promotion Workflow

Status: Complete

Work completed:

- Added `spatialmind.promotion` package.
- Added `build_local_promotion_report()` to scan local `data/`, run label-intake validation, generate Xenium review packets, run pilot gates, and summarize remaining gaps.
- Added `scripts/promote_local_agent.py`.
- Added optional FastAPI endpoints:
  - `POST /pilot/xenium/intake`
  - `POST /pilot/xenium/run`
  - `POST /promotion/local`
- Added a lightweight unit test for local promotion report generation.
- Updated README with the local promotion workflow command.

Generated outputs:

- `outputs/agent_promotion/local_promotion_report.json`
- `outputs/agent_promotion/local_promotion_report.md`
- `outputs/agent_promotion/review_packets/human_breast_biomarkers_s1_top_outs/`
- `outputs/agent_promotion/review_packets/xenium_v1_ffpe_human_brain_glioblastoma_with_addon_outs/`
- `outputs/agent_promotion/review_packets/xenium_v1_ffpe_human_brain_healthy_with_addon_outs/`
- `outputs/agent_promotion/review_packets/xenium_v1_hlymphnode_nondiseased_section_outs/`

Local promotion result:

- Dataset candidates discovered: `6`.
- Xenium datasets discovered: `4`.
- Validated-ready Xenium datasets: `0`.
- Fulfilled locally:
  - Xenium raw data ingestion,
  - review visualization,
  - local CLI orchestration,
  - API hooks for pilot/intake/promotion.
- Still blocked:
  - expert cell labels,
  - user tissue regions,
  - biological ground-truth benchmark labels.

Evaluation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind/promotion scripts/promote_local_agent.py spatialmind/api/app.py` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/promote_local_agent.py --data-root data --out outputs/agent_promotion --max-records 800` completed successfully.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_spatialmind.py'` passed 43/43 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/lint-imports` passed with 3 contracts kept and 0 broken.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --mvp --cases eval/mvp_cases --out outputs/mvp_eval_report.json` passed 10/10 with mean score 1.0000.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --out outputs/eval_report.json` passed 15/15 with mean score 1.0000.

Important boundary:

- The local `data/` folder can fulfill engineering, review, visualization, orchestration, and software-QA gaps.
- It cannot fulfill expert biological labels or user ROI labels without human review. The agent now makes that boundary explicit and generates all files needed to complete that review.

### Step 23: Add Governance, Acquisition Plan, and Replay Storage

Status: Complete

Discussion and rationale:

- Expert cell labels, ROI regions, and biological benchmark labels cannot be created honestly by code from the current local data.
- The correct promotion work is to provide the acquisition protocol, governance metadata scaffolding, and reproducible replay infrastructure so reviewed inputs can be incorporated safely.

Work completed:

- Added `docs/real_agent_acquisition_and_operations.md` describing how to get/conduct:
  - expert cell labels,
  - user tissue/ROI regions,
  - biological benchmark labels,
  - curated tissue-matched scRNA/scATAC references,
  - dataset license/consent/PHI metadata,
  - replay/database storage.
- Added `spatialmind/governance.py`.
- Added `scripts/build_dataset_governance_manifest.py`.
- Added `spatialmind/storage/replay.py` with:
  - SQLite run indexing,
  - run-record hash verification,
  - replay preparation.
- Added `scripts/index_run_database.py`.
- Added `scripts/replay_run.py`.
- Updated `StorageLayer.write_mvp_run_record()` so run records preserve artifact paths and stable artifact hashes.
- Fixed validated pilot run-record ordering so report hashes verify cleanly.
- Added tests for governance manifest generation, run-record verification, and run database indexing.

Generated outputs:

- `outputs/governance/dataset_governance_manifest.json`
- `outputs/spatialmind_runs.sqlite`
- `outputs/replay/xenium_validated_pilot_latest/validated_xenium_pilot_report.html`

Current generated metadata:

- Governance manifest records: `6`.
- SQLite run records indexed: `16`.
- Latest pilot run record verified: `outputs/xenium_validated_pilot/runs/mvp_20260627T070618Z_f6c76103.json`.
- Replay output status: `blocked_missing_validation_inputs`, matching the original validated pilot gate.

Evaluation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind/governance.py spatialmind/storage/replay.py spatialmind/storage/run_store.py tests/test_spatialmind.py` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/build_dataset_governance_manifest.py --data-root data --out outputs/governance/dataset_governance_manifest.json` completed successfully.
- `.venv/bin/python scripts/index_run_database.py --outputs-root outputs --db outputs/spatialmind_runs.sqlite` indexed 16 run records.
- `.venv/bin/python scripts/replay_run.py outputs/xenium_validated_pilot/runs/mvp_20260627T070618Z_f6c76103.json` verified all hashes.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/replay_run.py outputs/xenium_validated_pilot/runs/mvp_20260627T070618Z_f6c76103.json --replay --out outputs/replay/xenium_validated_pilot_latest` replayed successfully.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_spatialmind.py'` passed 45/45 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/lint-imports` passed with 3 import contracts kept and 0 broken.

### Step 25: Whole-Agent Operational Readiness Audit

Status: Complete.

Discussion and rationale:

- The user asked whether adding an LLM API now would make the agent usable.
- The audit separates software usability from biomedical validation readiness.
- Hosted LLM planning is useful now for natural-language UX, but it must remain gated by reviewed labels, reviewed regions, curated references, and benchmark evidence.

Work completed:

- Reviewed LLM provider adapters, CLI wiring, API endpoints, validated pilot gates, local promotion workflow, and backend wrappers.
- Ran local promotion audit under `outputs/agent_promotion_audit`.
- Ran latest Xenium pilot scorecard under `outputs/xenium_pilot_scorecard_latest`.
- Ran MVP and legacy eval reports under `outputs/mvp_eval_report_latest.json` and `outputs/eval_report_latest.json`.
- Validated real Scanpy/Squidpy backends.
- Fixed the Squidpy neighborhood wrapper by defaulting `sq.gr.nhood_enrichment()` to `backend="threading"`, `numba_parallel=False`, and `show_progress_bar=False`.
- Added `docs/operational_readiness_audit.md`.

Current result:

- SpatialMind is usable as a local, validation-gated review/workflow/provenance agent.
- It is not yet a fully validated biomedical interpretation agent because all four local Xenium datasets still lack reviewed expert labels and reviewed user regions.
- Adding an LLM API now improves natural-language planning but does not replace expert labels, ROI regions, benchmark truth, curated references, or governance metadata.

Evaluation:

- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/promote_local_agent.py --data-root data --out outputs/agent_promotion_audit --max-records 800` completed successfully; `0/4` Xenium datasets validated-ready.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/evaluate_xenium_pilot_readiness.py --data-root data --out outputs/xenium_pilot_scorecard_latest --max-records 800` completed successfully; `0/4` Xenium datasets validated-ready.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --mvp --cases eval/mvp_cases --out outputs/mvp_eval_report_latest.json` passed 10/10 with mean score 1.0000.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner --out outputs/eval_report_latest.json` passed 15/15 with mean score 1.0000.
- Initial backend validation found Squidpy neighborhood enrichment blocked by sandbox multiprocessing.
- After the wrapper patch, `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/validate_real_backends.py` passed Scanpy differential expression, Scanpy clustering, Scanpy variable genes, and Squidpy neighborhood enrichment.

### Step 26: Cell Ontology Label Vocabulary and Link Consolidation

Status: Complete.

Discussion and rationale:

- Expert labels need a constrained vocabulary before review begins.
- Cell Ontology is appropriate for cell-type labels, while glioblastoma programs and tissue states should remain secondary annotations or ROI labels.
- The first validated pilot should prefer broad, auditable labels instead of overly specific or weakly supported subtypes.

Work completed:

- Added `docs/cell_ontology_labeling_guide.md`.
- Added recommended `expert_label`, `cl_id`, and `secondary_state` guidance.
- Added first-pass brain/glioblastoma Cell Ontology terms.
- Added recommended ROI labels for `cell_regions.csv`.
- Added links for Cell Ontology, annotation tools, reference data portals, governance, consent, and production hardening to `README.md`.
- Updated operational/acquisition docs to point reviewers to the ontology guide.

Recommended label table:

```csv
cell_id,expert_label,cl_id,secondary_state,confidence,notes
```

The validated pilot still accepts the minimal table:

```csv
cell_id,expert_label,confidence,notes
```

Recommended first-pass Cell Ontology labels:

- `astrocyte` (`CL:0000127`)
- `oligodendrocyte` (`CL:0000128`)
- `microglial cell` (`CL:0000129`)
- `neuron` (`CL:0000540`)
- `oligodendrocyte precursor cell` (`CL:0002453`)
- `endothelial cell` (`CL:0000115`)
- `pericyte` (`CL:0000669`)
- `fibroblast` (`CL:0000057`)
- `macrophage` (`CL:0000235`)
- `T cell` (`CL:0000084`)
- `CD4-positive, alpha-beta T cell` (`CL:0000624`)
- `CD8-positive, alpha-beta T cell` (`CL:0000625`)
- `B cell` (`CL:0000236`)
- `plasma cell` (`CL:0000786`)
- `natural killer cell` (`CL:0000623`)
- `dendritic cell` (`CL:0000451`)
- `epithelial cell` (`CL:0000066`)
- `neoplastic cell` (`CL:0001064`)
- `unknown` / `unresolved` for ambiguous cells

### Step 27: Astrocyte Ontology JSON and Review-Only Label Prefill

Status: Complete.

Discussion and rationale:

- The user supplied the OLS JSON for astrocyte (`CL:0000127`) and asked to save it under `data/` and use it for cell labeling.
- Because this is not a human expert review, the implementation generates review-only machine suggestions rather than a final `expert_cell_labels.csv`.
- The current glioblastoma Xenium panel measures `AQP4`, `EGFR`, and `CD68`, but does not measure several ontology marker references such as `GFAP`, `GLUT1/SLC2A1`, `MBP`, or `NGFR`. Suggestions therefore remain conservative and require expert confirmation.

Work completed:

- Saved the supplied ontology term JSON at `data/cell_ontology_terms/CL_0000127_astrocyte.json`.
- Added `spatialmind/review/ontology_labels.py`.
- Added `scripts/write_astrocyte_label_suggestions.py`.
- Generated `outputs/glioblastoma_expert_review_packet/expert_cell_labels_astrocyte_prefill_for_review.csv`.
- Generated `outputs/glioblastoma_expert_review_packet/astrocyte_prefill_summary.json`.
- Updated `outputs/glioblastoma_expert_review_packet/README.md`.
- Updated `README.md` and `docs/cell_ontology_labeling_guide.md` with the astrocyte prefill command and caveat.

Current result:

- Records loaded: `2500`.
- Astrocyte candidates needing expert review: `1007`.
- Not prefilled as astrocyte: `1493`.
- Ontology ID used: `CL:0000127`.
- Measured marker basis: `AQP4`, `EGFR`, `CD68`.

Evaluation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind/review scripts/write_astrocyte_label_suggestions.py` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/write_astrocyte_label_suggestions.py --max-records 2500` completed successfully.

### Step 28: Architecture Figure, Wet-Lab-To-Report Assessment, and Cleanup

Status: Complete.

Discussion and rationale:

- The project goal is now stated explicitly as wet-lab platform output ingestion through comprehensive report generation.
- The agent can run the engineering/review/report path today for supported processed outputs such as Xenium folders, H5AD, and CSV manifests.
- Validated biological interpretation remains gated by expert labels, reviewed ROI regions, governance metadata, and benchmark/reference data.
- Source modules were retained when they are used by CLI/API/eval/tests, provide active compatibility paths, or support the wet-lab-to-report product path.

Work completed:

- Added a Mermaid architecture figure to `README.md`.
- Added layer-by-layer explanations in `README.md`.
- Added a wet-lab-output-to-report capability table in `README.md`.
- Added `docs/wet_lab_to_report_capability.md`.
- Updated `docs/operational_readiness_audit.md` to link the capability assessment.
- Updated project description text in `pyproject.toml`, `spatialmind/__init__.py`, and CLI help text.
- Added `.import_linter_cache/` to `.gitignore`.
- Removed generated or stale workspace debris:
  - Python `__pycache__` directories,
  - import-linter cache,
  - package build metadata,
  - macOS `.DS_Store` files,
  - stale ad hoc demo output folders,
  - empty `data/fixtures` directory.

Current assessment:

- Ready now: platform-processed Xenium/H5AD/CSV ingestion, QC/readiness reporting, review packets, ontology-guided review support, real backend wrappers, report generation, provenance, and replay.
- Not yet complete for validated biology: expert cell labels, user ROI regions, tissue-matched references, frozen benchmark truth, and dataset governance metadata.

### Step 29: Attempted Label/Region Completion and Gate Rerun

Status: Conducted; biologically blocked pending human review.

Discussion and rationale:

- The requested final outputs `expert_cell_labels.csv` and `cell_regions.csv` require human expert review.
- The agent rebuilt all review inputs and reran the validated workflows, but did not falsely promote machine suggestions to expert-reviewed truth.
- The resulting blocked reports are expected and scientifically correct.

Work completed:

- Rebuilt `outputs/glioblastoma_expert_review_packet/expert_cell_labels_draft_for_review.csv`.
- Rebuilt `outputs/glioblastoma_expert_review_packet/expert_cell_labels_astrocyte_prefill_for_review.csv`.
- Rebuilt `outputs/glioblastoma_expert_review_packet/cell_regions_draft_for_review.csv`.
- Reran the glioblastoma validated pilot.
- Reran the glioblastoma benchmark gate.
- Reran the tissue-matched reference-assist gate.
- Reran the healthy brain validated pilot.
- Reran the healthy-vs-glioblastoma comparison gate.
- Added `outputs/review_completion_status.md`.

Current result:

- Glioblastoma validated pilot: `blocked_missing_validation_inputs`.
- Glioblastoma benchmark: `blocked_missing_reviewed_labels`.
- Tissue reference assist: `blocked_missing_curated_reference`.
- Healthy brain validated pilot: `blocked_missing_validation_inputs`.
- Healthy-vs-glioblastoma comparison: `blocked_missing_validated_inputs`.

Required next human inputs:

- Reviewed glioblastoma `expert_cell_labels.csv`.
- Reviewed glioblastoma `cell_regions.csv`.
- Reviewed healthy brain `expert_cell_labels.csv`.
- Reviewed healthy brain `cell_regions.csv`.
- Curated tissue-matched healthy brain/glioblastoma reference with license/consent metadata.

### Step 30: Xenium `.xenium` Descriptor Entry Point

Status: Complete.

Discussion and rationale:

- Users naturally open Xenium datasets through `experiment.xenium` in Xenium Explorer.
- SpatialMind should accept that same file as the dataset entry point, then resolve the sibling output folder and linked Explorer assets.
- This is not a full Xenium Explorer GUI replacement; it is an agent-ingestion entry point and metadata parser.

Work completed:

- Added `xenium_experiment_file` raw data type detection for `.xenium` files.
- Updated `DataIngestionLayer.load()` and `load_xenium_directory()` to accept `.xenium` paths.
- Parsed `experiment.xenium` metadata before metrics/gene-panel metadata.
- Added resolved Explorer asset metadata under `xenium_explorer_assets`.
- Preserved `xenium_input_path`, `xenium_resolved_directory`, and `experiment_xenium_path` in dataset metadata.
- Updated dataset inspection to load `.xenium` entry points.
- Added tests for `.xenium` file detection and loading.
- Updated `README.md`, `INGESTION.md`, and `docs/wet_lab_to_report_capability.md`.

Supported now:

- `.xenium` JSON parsing,
- morphology/zarr/analysis-summary asset resolution,
- cell/matrix ingestion through the sibling output folder,
- report/provenance metadata preserving the `.xenium` input path.

Not implemented:

- full Xenium Explorer GUI,
- manual ROI drawing inside SpatialMind,
- browser-side label editing,
- full zarr-backed image/cell browser.

Verification:

- `.xenium` glioblastoma pilot completed from `data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs/experiment.xenium`.
- Output report: `outputs/xenium_brain_glioblastoma_pilot_xenium_file/validated_xenium_pilot_report.html`.
- Asset readiness correctly detected cell table, feature matrix, morphology, boundaries, and 10x analysis clusters through the `.xenium` entry point.
- The pilot remains intentionally blocked for validated biological claims because reviewed `expert_cell_labels.csv` and `cell_regions.csv` are still missing.
- Unit tests passed 46/46.
- Import-linter passed with 3 contracts kept and 0 broken.
- MVP eval passed 10/10 with mean score 1.0000.
- Legacy eval passed 15/15 with mean score 1.0000.

### Step 31: Explorer-Lite Xenium Review Viewer

Status: Complete for local review preparation.

Discussion and rationale:

- The agent needed an internal tool closer to the daily Xenium Explorer review workflow.
- A full Xenium Explorer replacement is not appropriate yet because morphology pyramid rendering, segmentation-boundary editing, and zarr-backed browsing need a dedicated frontend/backend.
- The useful next step is a local HTML viewer that loads from the agent's Xenium ingestion contract and helps reviewers produce CSV validation inputs.

Work completed:

- Added `spatialmind/viz/explorer_lite.py` with `XeniumExplorerLiteViewer`.
- Added `scripts/build_xenium_explorer_lite.py` for standalone viewer generation from a Xenium folder or `experiment.xenium`.
- Wired the viewer into the validated Xenium pilot review artifacts as `explorer_lite_viewer.html`.
- Added a unit test confirming the viewer includes review controls, CSV export names, embedded cells, and linked asset metadata.
- Updated `README.md` and `INGESTION.md`.

Supported now:

- local static HTML viewer with embedded loaded cells,
- color by current label, graph cluster, or draft region,
- label and cluster filters,
- cell ID search and selected-cell inspection,
- rectangular cell selection,
- draft ROI assignment and export as `cell_regions.csv`,
- draft expert-label assignment and export as `expert_cell_labels.csv`,
- linked Xenium asset inventory from `.xenium` metadata.

Not implemented:

- morphology image pyramid viewer,
- segmentation-boundary-aware editing,
- zarr-backed transcript/cell browser,
- persistent multi-user annotation database,
- direct writeback into source Xenium folders from the browser.

Verification:

- Standalone viewer generated for healthy brain from `data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs/experiment.xenium`.
- Output viewer: `outputs/xenium_brain_healthy_explorer_lite/explorer_lite_viewer.html`.
- Browser check rendered `1200` SVG cell points and all review/export controls.
- Browser interaction selected `aaaaieod-1`, applied region `tumor_core`, and produced a valid CSV preview row.
- Validated pilot generated `outputs/xenium_brain_healthy_pilot_explorer_lite/explorer_lite_viewer.html` as a review artifact.
- Unit tests passed 47/47.
- Import-linter passed with 3 contracts kept and 0 broken.

### Step 32: v12 Claim-Level Reliability Scoring

Status: Complete for conservative baseline; blocked for calibrated biological reliability until reviewed truth labels exist.

Discussion and rationale:

- The v12 plan makes claim reliability the central methodological contribution.
- Reliability must be attached to each report claim, not averaged across the whole run.
- The score should be interpretable enough for expert reviewers to see which evidence class limits a claim.
- The current implementation therefore uses a transparent weakest-link baseline and refuses to fit a calibrated model without ground-truth claim correctness labels.

Work completed:

- Added typed reliability contracts in `spatialmind/contracts/reliability.py`.
- Added `spatialmind/methods/reliability/` with claim scoring, S/A/P/R component scoring, weakest-link combination, and calibrated-combiner scaffolding.
- Wired claim reliability into `spatialmind.pilot` so every pilot claim ledger entry receives:
  - `S_statistical`
  - `A_annotation`
  - `P_panel`
  - `R_spatial_robustness`
  - final reliability score
  - interpretation and provenance
- Updated markdown and HTML validated-pilot reports with a Claim Reliability section.
- Added `scripts/train_claim_reliability_local.py` for human-brain Xenium reliability/control runs.
- Added tests for blocked biological claims and supported readiness claims.
- Updated `README.md` and `docs/training_status.md`.

Generated outputs:

- `outputs/training/human_brain_claim_reliability_v12/claim_reliability_training_report.md`
- `outputs/training/human_brain_claim_reliability_v12/claim_reliability_training_records.json`
- `outputs/training/human_brain_claim_reliability_v12/claim_reliability_training_summary.json`
- `outputs/training/human_brain_claim_reliability_v12/healthy_brain_pilot/validated_xenium_pilot_report.html`
- `outputs/training/human_brain_claim_reliability_v12/glioblastoma_pilot/validated_xenium_pilot_report.html`

Current result:

- Human-brain reliability run generated 8 local claim/control records.
- Local-control AUROC is 1.0000.
- Calibrated model status is `not_fit`.
- Biological claims remain blocked at reliability 0.0000 because expert labels and ROI regions are missing.
- Non-biological readiness claims score 0.7500 because they are grounded in asset-readiness checks.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind/contracts/reliability.py spatialmind/methods scripts/train_claim_reliability_local.py spatialmind/pilot tests/test_spatialmind.py` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_spatialmind.py'` passed 48/48 tests.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/train_claim_reliability_local.py --out outputs/training/human_brain_claim_reliability_v12 --max-records 800` completed successfully.

### Step 33: Expert Claim-Truth Review Gate

Status: Complete for software workflow; awaiting expert review for biological calibration.

Discussion and rationale:

- The next real step after v12 reliability scoring is not to fabricate labels; it is to collect auditable claim-level truth from an expert.
- The agent now needs a concrete bridge from human review to calibrated reliability, including positive claims, negative/null claims, and provenance for why each claim is judged correct or unsupported.
- The implementation creates that bridge while keeping calibration blocked until a completed review table exists.

Work completed:

- Added `spatialmind/review/claim_truth.py`.
- Added `scripts/prepare_claim_reliability_review_packet.py`.
- Added `spatialmind/methods/reliability/calibration.py`.
- Updated `scripts/train_claim_reliability_local.py` to accept `--claim-truth`.
- Added validation for reviewed claim-truth CSVs.
- Added optional logistic calibration fitting when reviewed truth has both supported and unsupported claims.
- Added tests for blocked incomplete review data and fitted reviewed calibration data.
- Updated `README.md` and `docs/training_status.md`.

Generated outputs:

- `outputs/claim_reliability_review_packet_v12/spatial_claim_truth_draft_for_review.csv`
- `outputs/claim_reliability_review_packet_v12/README.md`
- `outputs/claim_reliability_review_packet_v12/claim_truth_review_summary.json`
- `outputs/claim_reliability_review_packet_v12/claim_truth_validation_report.json`
- `outputs/claim_reliability_review_packet_v12/claim_truth_validation_report.md`
- `outputs/claim_reliability_review_packet_v12/pilot_outputs/healthy_brain/validated_xenium_pilot_report.html`
- `outputs/claim_reliability_review_packet_v12/pilot_outputs/glioblastoma/validated_xenium_pilot_report.html`
- `outputs/training/human_brain_claim_reliability_review_gate_v12/claim_reliability_calibration_model.json`

Current result:

- Claim-truth draft rows: 11.
- Reviewed calibration rows: 0.
- Calibration status: `not_fit`.
- Blockers:
  - Need at least 4 reviewed calibration records.
  - Need at least one reviewed supported/correct claim.
  - Need at least one reviewed unsupported/false claim.

Verification:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind/methods/reliability spatialmind/review scripts/prepare_claim_reliability_review_packet.py scripts/train_claim_reliability_local.py tests/test_spatialmind.py` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_spatialmind.py'` passed 49/49 tests.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/prepare_claim_reliability_review_packet.py --out outputs/claim_reliability_review_packet_v12 --max-records 800` completed successfully.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/prepare_claim_reliability_review_packet.py --out outputs/claim_reliability_review_packet_v12 --validate-truth outputs/claim_reliability_review_packet_v12/spatial_claim_truth_draft_for_review.csv` completed with expected block.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/train_claim_reliability_local.py --out outputs/training/human_brain_claim_reliability_review_gate_v12 --max-records 800 --claim-truth outputs/claim_reliability_review_packet_v12/spatial_claim_truth_draft_for_review.csv` completed with expected `not_fit` calibration status.

### Step 24: Glioblastoma Expert-Review Packet and Validation Gates

Status: Complete for software implementation; blocked for biological validation until human-reviewed inputs are supplied.

Discussion and rationale:

- The local glioblastoma Xenium data can support review-packet generation, visualization, panel/QC checks, and validation-gated analysis.
- It cannot honestly produce expert cell labels, ROI regions, benchmark truth, or healthy-vs-glioblastoma biological conclusions without reviewed labels and regions.
- The implementation therefore pre-fills draft review files, then blocks downstream biological analyses until the reviewed files are saved under the required names.

Work completed:

- Added `spatialmind/review/` for glioblastoma review, benchmark, reference-assist, and healthy-vs-glioblastoma comparison gates.
- Added `scripts/prepare_glioblastoma_review_packet.py`.
- Added `scripts/build_glioblastoma_benchmark.py`.
- Added `scripts/run_tissue_reference_assist.py`.
- Added `scripts/build_brain_comparison_report.py`.
- Updated `README.md` with the glioblastoma review workflow.

Generated outputs:

- `outputs/glioblastoma_expert_review_packet/README.md`
- `outputs/glioblastoma_expert_review_packet/expert_cell_labels_draft_for_review.csv`
- `outputs/glioblastoma_expert_review_packet/cell_regions_draft_for_review.csv`
- `outputs/glioblastoma_expert_review_packet/review_packet_summary.json`
- `outputs/glioblastoma_benchmark/benchmark_report.md`
- `outputs/glioblastoma_reference_assist/reference_assist_report.md`
- `outputs/brain_comparison/brain_comparison_report.md`

Current result:

- Glioblastoma review packet generated for `2500` loaded cells and `410` targeted-panel features.
- 10x graph clusters loaded: `23`.
- Current loader label counts:
  - Neural/Glial cell: `1328`
  - Myeloid cell: `370`
  - T/NK cell: `332`
  - Unannotated cell: `250`
  - Fibroblast/Stromal cell: `130`
  - Endothelial cell: `89`
  - Epithelial/Tumor-like cell: `1`
- Benchmark status: `blocked_missing_reviewed_labels`.
- Tissue reference-assist status: `blocked_missing_curated_reference`.
- Healthy-vs-glioblastoma comparison status: `blocked_missing_validated_inputs`.

Required next inputs:

- Reviewed glioblastoma `expert_cell_labels.csv` keyed by Xenium `cell_id`.
- Reviewed glioblastoma `cell_regions.csv` keyed by Xenium `cell_id`.
- Reviewed healthy brain `expert_cell_labels.csv` and `cell_regions.csv` before any healthy-vs-glioblastoma comparison.
- Curated tissue-matched brain/glioblastoma reference with validated labels and source/license/consent metadata before reference-assisted annotation is treated as evidence.

Evaluation:

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind/review scripts/prepare_glioblastoma_review_packet.py scripts/build_glioblastoma_benchmark.py scripts/run_tissue_reference_assist.py scripts/build_brain_comparison_report.py` passed.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/prepare_glioblastoma_review_packet.py --max-records 2500` completed successfully.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/build_glioblastoma_benchmark.py --max-records 2500` completed with expected validation block.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/run_tissue_reference_assist.py --max-records 2500` completed with expected reference block.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/build_brain_comparison_report.py --max-records 2500` completed with expected comparison block.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/run_validated_xenium_pilot.py --data "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs" --out outputs/xenium_brain_glioblastoma_pilot --max-records 2500` completed with expected validation block and regenerated review figures/report.
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_spatialmind.py'` passed 45/45 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/lint-imports` passed with 3 import contracts kept and 0 broken.

### Step 34: Full Data-Root Workflow, Numerical QC, and All-Xenium Training

Status: Complete for software validation and exploratory training; biological validation remains blocked by reviewed inputs.

Work completed on 2026-07-11:

- Ran discovery, ingestion, review-packet generation, validated-pilot gates, Explorer-lite outputs, real Scanpy/Squidpy wrappers, behavioral training, claim-reliability controls, governance, benchmark/reference/comparison gates, replay verification, SQLite indexing, and both eval suites.
- Corrected dataset discovery so ontology/reference JSON files are not treated as analysis manifests.
- Corrected H5 readiness reporting to use actual matrix-load status.
- Added deterministic sampling method, total-cell count, loaded-cell count, and sampling fraction to Xenium provenance.
- Added finite-value QC before normalization; 77 non-finite values in the sampled breast data were detected and sanitized.
- Removed undefined Squidpy permutation pairs from evidence tables, recorded omitted-pair counts, and enabled strict JSON serialization.
- Marked label-dependent workflows as partial when labels are provisional.
- Updated the local planner to recognize plain-language comparisons and neighborhood requests.
- Generalized `train_spatialmind_local.py` from one hard-coded breast pipeline to every Xenium dataset discovered under `data/`, using strict real Scanpy/Squidpy wrappers.
- Added OpenMP conflict detection to runtime preflight and training summaries.

Latest results:

- Analysis inputs discovered: 6 (4 Xenium, 1 demo manifest, 1 demo table).
- Training records: 18, mean behavioral score 1.0000.
- Real Xenium wrapper records: 4/4 completed with Scanpy and Squidpy.
- MVP eval: 10/10; legacy eval: 15/15.
- Validated-ready Xenium datasets: 0/4 because reviewed labels and ROIs are absent.
- Claim-reliability controls: 8 records, local-control AUROC 1.0000, calibrated model `not_fit`.
- Replay: all glioblastoma input/artifact hashes verified.
- Run database: 10 records indexed.

Detailed report:

- `outputs/full_workflow_20260711/FULL_WORKFLOW_REPORT.md`

### Step 35: Conflict-Free Core Scientific Environment

Status: Complete.

Work completed on 2026-07-11:

- Split the default core runtime from optional PyTorch models.
- Removed `scvi-tools` and `cell2location` from `requirements.txt` and the `full` package extra.
- Added `requirements-deep-learning.txt` and a `deep-learning` package extra for isolated model environments.
- Added `requirements-dev.txt` so lint/test tools do not block device runtime installation.
- Preserved the previous environment as `.venv-deep` and rebuilt the default `.venv` without PyTorch.
- Pinned the validated Python 3.9 `dask`, `fsspec`, and `s3fs` combination to avoid resolver backtracking.
- Removed the previously unused ReportLab dependency at that stage; reports remained HTML/Markdown only.
- Updated README, Makefile, `.gitignore`, dependency metadata, and runtime preflight guidance.

Verification:

- `pip check`: no broken requirements.
- PyTorch, scvi-tools, and cell2location are absent from `.venv`.
- Direct runtime probe: `torch_loaded=false`; only LLVM `libomp` is loaded, with no Intel `libiomp`.
- Runtime version check passes with no mixed-OpenMP warning.
- Scanpy DE, clustering, and HVG wrappers pass.
- Squidpy neighborhood enrichment passes.
- Xenium H5 matrix loading passes.
- Unit tests pass 61/61.

### Step 36: Post-Fix Training Refresh and Expert-Review Handoff

Status: Complete for behavioral training and software evaluation; awaiting human biological review.

Work completed on 2026-07-17:

- Re-ran the behavioral/tool-selection trainer across all four local Xenium datasets with 1,200 deterministically sampled cells per dataset.
- Exercised real Scanpy clustering/marker wrappers and Squidpy neighborhood enrichment on breast, glioblastoma brain, healthy brain, and lymph node data.
- Re-ran human-brain claim-reliability training on healthy brain and glioblastoma pilots.
- Validated the current glioblastoma label/region intake and claim-truth draft, preserving expected biological validation gates.
- Added `docs/expert_review_workflow.md` with reviewer roles, schemas, reference resources, ROI procedure, claim adjudication, commands, and acceptance criteria.
- Added `outputs/training/current_20260717/TRAINING_AND_REVIEW_REPORT.md` as the consolidated output example.

Results:

- Behavioral records: 18; mean score: 1.0000.
- Real Xenium pipelines: 4/4 completed with Scanpy and Squidpy.
- Runtime conflict warnings: 0.
- Claim/control records: 8; local-control AUROC: 1.0000.
- Claim calibration: `not_fit`, correctly blocked by missing reviewed biological truth.
- Glioblastoma expert-label coverage: 0%; reviewed-region coverage: 0%.
- Claim-truth rows: 11; reviewed calibration rows: 0.

Required next inputs:

- Reviewed `expert_cell_labels.csv` keyed to glioblastoma Xenium `cell_id`.
- Reviewed `cell_regions.csv` keyed to the same cells and pathology-defined ROIs.
- Completed claim-truth table with positive and negative claims, evidence provenance, reviewer identity, and stable train/validation/test splits.

### Step 37: Selectable HTML and PDF Report Delivery

Status: Complete.

Work completed on 2026-07-18:

- Added a shared ReportLab-based PDF renderer with page numbering, metadata, sections, bullets, tables, raster figures, and PDF signature/size validation.
- Replaced the old PDF text placeholder and removed the native-library-dependent WeasyPrint runtime requirement.
- Added `--report-format html|pdf|both` to the main agent CLI, validated Xenium pilot CLI, and replay CLI.
- Added the same validated `report_format` choice to the `/runs` and `/pilot/xenium/run` API requests.
- Added `report_paths` to agent run outputs and `report_html`, `report_pdf`, `report_path`, and `report_format` to Xenium pilot outputs.
- Kept HTML as the default and retained HTML beside PDF for auditable, accessible source output.
- Updated the README, validated-pilot documentation, dependency manifests, and tests.

Verification:

- Generated `outputs/xenium_brain_glioblastoma_selectable_report/validated_xenium_pilot_report.html` and `.pdf` with `--report-format both`.
- The PDF is a valid three-page A4 document, starts with `%PDF-`, and contains the expected metadata, figure, label/region summaries, typed plan, claim reliability, limitations, and provenance sections.
- Extracted PDF text contains `claim_002` with corrected reliability `0.7500`.
- Rendered all three pages to PNG and visually checked figure scaling, table wrapping, page breaks, margins, and page-number footers; no clipping or overlap remained.
- Main agent CLI generated both `report.html` and `report.pdf` from the demo data.
- API OpenAPI schema exposes `html`, `pdf`, and `both` for both report-producing endpoints.
- `pip check` reports no broken requirements.
- Unit tests pass 63/63 and all three import contracts remain intact.

### Step 38: Readiness-Only CLI and Visible Spatial Robustness

Status: Complete.

Work completed on 2026-07-22:

- Evaluated Claude's internal `run_pilot(readiness_only=True)` fast path and retained it because it genuinely skips templates, figures, reports, validated tools, and run records.
- Added `--readiness-only` to `scripts/run_validated_xenium_pilot.py` and `scripts/promote_local_agent.py`.
- Added an in-memory `label_intake` block to pilot results so promotion no longer reloads every Xenium dataset solely to produce intake status.
- Made readiness-only promotion write per-dataset `pilot_validation.json` plus the small aggregate Markdown/JSON reports, without heavy review artifacts.
- Added execution metadata to the real neighborhood robustness sweep: requested graph sizes, permutation count, random seed, top-K, and engines.
- Added a Spatial Robustness Sweep section immediately after claim reliability in Markdown, HTML, and PDF validated-run reports.
- Kept robustness hidden on blocked reports because no real sweep is run before expert-label and ROI gates pass.
- Added tests for robustness execution metadata and cross-format report rendering.

Verification:

- A single-dataset readiness-only Xenium run wrote only `pilot_validation.json`; it did not create templates, figures, reports, tool results, or a run record.
- A readiness-only promotion scan inspected all four local Xenium datasets and wrote only per-dataset readiness JSON plus the aggregate Markdown/JSON summary.
- A full blocked-run regression still produced HTML and PDF reports and correctly omitted the unmeasured robustness section.
- A synthetic validated-report render verified that the measured robustness table appears in Markdown, HTML, and PDF; all three PDF pages were visually checked with no clipping or overlap.
- Unit tests pass 67/67.
- Legacy evaluation passes 15/15 with mean score 1.0000; MVP evaluation passes 10/10 with mean score 1.0000.
- All three import contracts remain intact, `pip check` reports no broken requirements, bytecode compilation passes, and `git diff --check` reports no whitespace errors.
