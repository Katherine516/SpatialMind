# SpatialMind Development Tracking

This log tracks implementation work against the current v2 build plan. It is updated as development proceeds so decisions, blockers, and verification steps remain visible.

## 2026-10-03: Ordered P1 Review Contracts, Portable Sparse Storage and Training Protocol

Implemented the engineering portions of the requested three-step sequence. The
owner confirmed no reviewers or completed files are available. Full implementation
and commands: [ordered P1 report](brain_p1_implementation_20261003.md).

- Prepared frozen source membership and pending decisions for eight human
  references, 28 label mappings and 114 collection/donor entries. Kept lineage,
  ontology, malignant state and evidence separate. Added canonical donor aliases,
  partition-overlap checks, source-provenance checks and explicit human-review gates.
- Added content-bound observation identities and chunked CSR H5AD caches with
  exact source row/feature identities, selected-value readback, content manifests
  and exclusive publication. Auto reference loading checks cache integrity.
  Merging identical copied sources or overlapping caches is refused.
- Exported two full-feature 256-cell caches: GBmap 27,632 features, 201,293 nonzeros,
  575,903 selected counts; Siletti 58,232 features, 395,417 nonzeros, 669,740 counts.
  Independent AnnData/source comparison confirmed exact sparse parity. Panel-based
  agent reloads preserved IDs and measured 316/318 shared features respectively.
- GBmap export took 25.46 s with 137,973,760-byte maximum RSS; Siletti took 5.99 s
  with 169,406,464-byte maximum RSS. These include full source hashing and are
  sampled technical checks, not whole-atlas scaling evidence or biological metrics.
- Added mandatory approved development protocols binding curation hashes and
  source-backed section donors. Candidate grids, confidence and acceptance
  thresholds are prespecified. Failure produces development results without a
  model lock. Successful locks include the exact protocol; external release
  checks its integrity. Existing custodian-controlled testing was not executed.
- Generated HTML/JSON ordered readiness. Both 750-cell brain packets retain zero
  accepted labels and regions. No final CSVs, training or external scores created.

Final verification: 637/637 tests passed in 191.843 s; routing 16/16 and 13/13,
four registry invariants per routing suite, six import contracts, compilation,
documentation counts and diff whitespace checks passed. Sixteen tests were added
in this increment. Synthetic reviewed fixtures test the success path but do not
represent human or biological validation. Evidence is under
`outputs/brain_p1_implementation_20261003/`.

Remaining: actual specialist review, matched histology where needed, approved
reference/donor mappings and scientific thresholds, an independent external donor,
cross-version biological duplicate checks and full-study downstream scaling.
No raw data edits, GitHub push, app rebuild or model training occurred.

## 2026-10-03: P1 Reference Curation and Donor-Safe Ingestion

Continued the priority order with [reference readiness](reference_readiness_20261003.md),
not another assay adapter or unreviewed biological training.

- Audited nine local H5AD references: eight human candidates, one mouse atlas.
  Recovered version/collection/schema metadata and bounded layer evidence. All
  candidates remain pending curation; no expert or licensing approvals inferred.
- Found that all seven Siletti files share four donors (21 overlapping file pairs).
  Drafted collection-level 2/1/1 donor roles for Siletti and 66/22/22 for GBmap.
  These are internal, unapproved proposals, not untouched external tests.
- Added explicit X/raw.X/named-layer selection with matching feature metadata;
  donor filtering before label reads; species and source-observation provenance;
  panel-overlap, symbol-collision and integer-count checks; source namespaces.
- Prevented I/O fallback and non-H5AD directory paths from silently ignoring
  explicit donor/layer constraints. Exposed selectors on reference-assist CLI.
- Read 64 training-donor cells from each human file: 512 cells across eight files.
  Shared measured panel coverage was 318/319 per Siletti file and 316/319 for
  GBmap. Loading time totals were 13.099 s and 1.470 s respectively, single local
  smoke measurements, not full-study scaling or accuracy benchmarks.
- Exercised the real reference-assist CLI with the mouse atlas: returned
  blocked_unusable_reference rather than fitting a human transfer model.

Verification: the full suite passed 619/619 in 547.558 s. Two safety tests added
after that suite started passed in the final 19/19 reference-focused run
(3.366 s); current inventory is 621 tests, not a single 621-test execution.
Legacy/MVP routing passed 16/16 and 13/13, with four invariants each. All six
import contracts, compilation, diff whitespace and refreshed documentation counts
passed. Logs and JSON evidence are in `outputs/reference_readiness_20261003/`.

No training, specialist approval, independent test scoring, raw-data change,
packaged rebuild or GitHub push occurred. Remaining P1 work: curator crosswalks,
source/donor verification, portable identities, sparse-native storage, real brain
review and independent testing. The metadata audit inspected all-donor label
summaries; its later donor plan must not be described as a sealed benchmark.

## 2026-10-03: P0 Correctness Repairs and Initial P1 Foundation

Implemented all eight software findings from the preceding audit. Full details
and remaining scope are in [the upgrade report](correctness_upgrade_20261003.md).

- Replaced same-statistic Moran screening with a coordinate-independent detection
  filter and complete-family BH correction. Kept full tested results separate
  from display top-N and exported every tested/excluded gene.
- Rejected index/embedding coordinates in spatial execution and AnnData spatial
  fields; expanded cache invalidation for coordinate/source-semantic changes.
- Preserved complete H5AD/Xenium source features; rejected scientific per-cell
  feature caps and ambiguous duplicate mapped H5AD identifiers.
- Preserved protein intensities, added proteomics contract semantics, skipped RNA
  count/gene thresholds for protein and refused unsupported protein analysis.
- Removed control-feature fallback, marked incomplete replay verification partial,
  and made unimplemented fusion measurements null.
- Added CSR construction for wide matrices and sparse source-value QC. Added a
  bounded HDF5 reference-curation inventory, without inferring biological approval.

Verification: 602/602 tests passed in 192.827 s; 16 new boundary regressions,
9/9 original audit checks, 16/16 legacy and 13/13 MVP routing, 6/6 import contracts,
compilation and documentation-count checks. Two older test expectations were
updated because they encoded the unsafe control/filter fallbacks.

Both sampled brain reports reran successfully with unchanged clustering:
1,495 GBM cells / 9 clusters and 1,497 healthy cells / 8 clusters. Each exports
318 gene rows: 309 tested + 9 excluded for GBM, 298 + 20 for healthy brain.
Each run verifies 17/17 provenance entries and retains the missing-review gate.
Fifty prespecified exchangeable all-null simulations produced a family rejection
rate of 0.04 (Wilson 95% interval 0.0110-0.1346); this is not real-tissue validation.

All nine local H5AD candidates have a pending-curation entry. Candidate donor/label
columns exist, but expression semantics, source evidence and donor independence
still need confirmation. No expert decisions, training, external-test tuning,
new assay adapter, dependency installation, packaged build or GitHub push occurred.
P1 curation/storage work and P2-P4 platform milestones remain open.

## 2026-10-03: Layer Review and Data Expansion Evaluation

Reviewed all six architectural tiers and their functional boundaries at source
commit `2d0a00acc2d4bc0c5119a0e85cc9584301cf514c`. Added an English
[evaluation](layer_evaluation_20261003.md), an English
[prioritized expansion roadmap](multimodal_roadmap_20261003.md), and the repeatable
`scripts/audit_modality_boundaries.py` audit. Updated the README reference index.
No scientific implementation, raw data, review decision or model was changed.

Fresh verification: 586/586 tests in 220.823 s, legacy routing 16/16, MVP routing
13/13, four registry invariants in each routing evaluation, import contracts 6/6,
dependency consistency, compilation and documentation counts all passed.
The adversarial boundary audit nevertheless reproduced eight observations across
nine checks; these are documented findings, not newly fixed capabilities.

Ran 500-cell readiness scans on all five local Xenium bundles and inspected
metadata of nine H5AD references. Generated new healthy-brain and GBM reports
using 1,500 requested cells each: 1,497/1,495 after QC, 8/9 clusters, 318 detected
biological genes each, 43.20/33.71 s total CLI time. Both reports verified 17/17
provenance entries and retained the missing-review block. Three-seed clustering
ARI ranges were 0.9702-0.9852 (healthy) and 0.9491-0.9646 (GBM), measuring seed
stability rather than annotation accuracy. Report PNGs were visually inspected;
browser layout inspection was unavailable because file-URL navigation was blocked.

Priority findings: same-statistic spatial-gene screening before selected-set FDR;
nonspatial index coordinates accepted by spatial tools; per-cell H5AD top-200
truncation; RNA normalization/contract assignment for protein tables; 35 tested
gene rows missing from each brain export; technical features reintroduced in
one-gene subsets; partial provenance reported verified; unimplemented fusion
returning numeric quality/shared-cell metrics. Fixes remain next-step work, with
reproducible evidence under `outputs/layer_evaluation_20261003/`.

Both 750-cell brain packets still have zero accepted labels/regions. The 11-row
claim-truth draft has zero reviewed/usable rows; donor-heldout calibration remains
blocked. No biological training or external-test rescoring was performed. All new
files and documentation are English.

## 2026-10-02: GitHub Collaborator Distribution

The owner explicitly confirmed all local datasets are cleared for public
redistribution after being informed that the repository is public. Prepare the
full approximately 42 GB data snapshot as checksum-bound split release assets,
not Git blobs; `.gitignore` continues excluding large raw data and binaries.
Package the September 30 tested Intel app instead of the stale September 28 DMG.
Include the glioblastoma example and the frozen specialist-review packet so a
collaborator can inspect actual outputs and pending work. Added a collaborator
handoff with source-tag, download, integrity, restoration, privacy and validation
limitations. The owner attestation does not substitute for an independent audit.

Publication and asset-verification results will be recorded below after upload.

## 2026-09-30: Ordered Evidence-Boundary Upgrade

### 1. Correctness Boundaries

Implemented explicit review approval/provenance checks shared by ingestion,
Studio and specialist/brain benchmark validators. Candidate/anonymous/invalid
rows and duplicate IDs cannot become reviewed truth. Studio preserves extra
columns, versions previous CSVs and journals before atomic replacement. Missing
donor identity now blocks condition inference even with multiple sections. H5AD
semantics distinguish counts from natural-log expression and reject ambiguous,
negative, scaled, nonfinite or non-natural-log input instead of double logging.

### 2. Shared Execution

Moved typed plan construction to agent.planning with a Studio compatibility API.
Removed AlgorithmEngine from the active orchestrator; canonical tools use the
shared runtime boundary across supported entry points. Real backends, group
aliases, gates and preconditions are enforced there and effective parameters
recorded. Legacy intent vocabulary remains for saved requests, not a separate
execution backend. A full-suite regression caught canonical existing-label
annotation missing from the always-gated set; fixed and directly tested.

### 3. Specialist Brain Review

Blocked on human input. Refreshed the ordered JSON/HTML readiness report for the
existing two 750-cell cohorts: accepted labels/regions remain zero. No identities,
credentials, cell labels, pathology ROIs or matched histology were fabricated;
raw data and review CSVs were not edited.

### 4. Brain Model Lock and External Evaluation

Implemented validate_brain_model.py: stage provenance/hash checks, train/validation
only k/prior selection, a frozen JSON training reference and model lock, verified
development donor IDs, custodian/hash-bound external release, prespecified panel
overlap, predictions before truth parsing, exact truth membership and per-donor
metrics. One-attempt reservation prevents silent test reuse; it is procedural,
not authenticated access control. Synthetic tests exercise this path, not real
brain performance. The actual local selection refuses before creating model
artifacts because specialists are unassigned.

### 5. Biological Reliability Evaluation

Implemented reviewed claim truth/provenance checks and donor-disjoint calibration
with train-only fitting, held-out Brier/ECE/AUROC, curves and per-donor metrics.
Null/readiness controls cannot train this biological calibrator; new drafts leave
donor/split blank for custodial assignment. No reviewed biological claim table is
available, so the pilot still uses weakest-link reliability and no biological
calibrator was trained or deployed.

Verification:

- Full suite: 586/586 passed in 204.087 seconds, including 24 new regression tests.
  An initial run passed 584/585 and exposed the migrated annotation gate gap;
  the implementation was fixed without weakening the expected policy.
- Import contracts: 6/6 passed; legacy routing 16/16 and MVP evaluation 13/13.
  Compilation, documentation inventory and environment dependency checks passed.
  These checks do not measure brain biological accuracy.
- Real glioblastoma example: 1,500 sampled cells from a 40,887-cell section,
  1,495 retained after QC, 9 newly computed expression clusters. Scanpy/Squidpy
  produced descriptive maps, marker summaries and spatial statistics. Report:
  `outputs/reliability_boundary_20260930/glioblastoma_example/validated_xenium_pilot_report.html`.
  Status remains `blocked_missing_validation_inputs`; no validated cell-type or
  pathology claims were unlocked. This is a sampled run, not a full-section study.
- Studio visual inspection confirmed that reviewer/evidence/confidence/basis
  controls fit the review panel. No real review assignments were submitted.
  The 77 Studio tests passed again after the final CSS change.
- Intel macOS app rebuilt successfully, 209 native libraries passed architecture
  audit, and bundled UI SHA-256 matches source. Signature is ad-hoc, not notarized;
  no Apple Silicon app or refreshed distribution DMG was produced.
  Frozen-app smoke checks passed 12/12, including actual Scanpy clustering and
  Squidpy spatial-gene analysis on a clearly synthetic 300-cell fixture, review
  table writes, gate reopening/closing and scaffold refusal. This verifies the
  headless bundled backend, not native-window rendering or biological validity.
- Historical breast benchmark numbers were not rescored or promoted. Specialist
  assignment, reviewed brain truth, independent donor testing and biological
  calibration are still pending human evidence, not completed training.

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
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` passed the active suite at the time of this step (45 tests).
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
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_spatialmind.py'` passed the active suite at the time of this step (45 tests).
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
- `MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python -m unittest discover -s tests -p 'test_spatialmind.py'` passed the active suite at the time of this step (45 tests).

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

### Step 39: Reliable Spatial Relationship Evidence

Status: Complete.

Work completed on 2026-07-22:

- Added a validated-only spatial relationship synthesis that combines Squidpy permutation adjacency, pair-level graph-size stability, bidirectional nearest-cell distance, and reviewed-region overlap.
- Added transparent evidence statuses: `stable_enriched`, `stable_depleted`, sensitivity-limited, and weak/indeterminate.
- Added minimum effect, cell-count, global robustness, sign-agreement, and top-K-presence criteria before a pair can be called stable.
- Added a diverging neighborhood z-score heatmap and relationship tables to Markdown, HTML, and PDF reports.
- Added explicit language separating spatial adjacency from physical contact, signaling, mechanism, and causation.
- Reused the primary `n_neighs=6` neighborhood result as the first robustness setting when parameters match, avoiding one repeated Squidpy run.
- Increased the validated default to 250 seeded permutations and retained all finite pair results for report synthesis.
- Tightened claim grounding so prototype neighbor counts cannot satisfy permutation-z-score evidence requirements.
- Added unit coverage for stable relationships, region context, distance context, prototype rejection, pair-level sensitivity metadata, and cross-format report rendering.

Verification:

- Unit tests pass 69/69.
- Legacy evaluation passes 15/15 with mean score 1.0000; MVP evaluation passes 10/10 with mean score 1.0000.
- A blocked local Xenium run produced no pair findings or heatmap and clearly reported that reviewed labels and regions are required.
- A synthetic validated rendering fixture produced the expected enriched/depleted evidence table, nearest-distance and region-overlap context, spatial adjacency heatmap, and robustness table in Markdown, HTML, and PDF.
- Visually checked all four PDF pages and the standalone heatmap; tables, labels, color scale, captions, and page transitions are legible with no clipping or overlap.
- All three import contracts remain intact, `pip check` reports no broken requirements, bytecode compilation passes, and `git diff --check` reports no whitespace errors.

### Step 40: Region-Stratified Neighborhoods and Distance Co-Occurrence

Status: Complete.

Work completed on 2026-08-01:

- Added independent Squidpy neighborhood permutation tests within each reviewed ROI.
- Added explicit region and per-cell-type minimum support thresholds, deterministic region prioritization, and auditable skip reasons.
- Added cross-region pair summaries for direction agreement, strongest region, and region-consistent versus heterogeneous effects; consistency requires at least two regional effects with `|z| >= 2`.
- Added distance-dependent Squidpy co-occurrence probability-ratio curves for leading cell-type pairs with at least 20 cells per type.
- Added automatic, provenance-recorded distance scaling from nearest-cell spacing and tissue extent.
- Forced co-occurrence execution through one threading worker to avoid fragile multiprocessing behavior in CLI and notebook contexts.
- Added region-by-pair heatmaps, distance curves, report tables, JSON evidence artifacts, limitations, and run-record hashing.
- Kept both analyses behind the expert-label and reviewed-region validation gate.

Verification:

- Unit tests pass 77/77.
- Live synthetic Squidpy probes passed for a two-region neighborhood analysis and a distance-dependent co-occurrence curve.
- A blocked local Xenium run produced no inferred regional effects or distance curves and stated that reviewed labels and regions are required.
- A synthetic validated fixture rendered both new figures and the corresponding tables in Markdown, HTML, and PDF.
- Visually checked all six PDF pages plus both standalone figures; labels, legends, tables, captions, and page transitions are legible with no clipping or overlap.
- Legacy evaluation passes 15/15 with mean score 1.0000; MVP evaluation passes 10/10 with mean score 1.0000.
- All three import contracts remain intact, `pip check` reports no broken requirements, bytecode compilation passes, and `git diff --check` reports no whitespace errors.

### Step 41: Full Layer Audit, Reliable Clustering Metrics, and Spatial Gene Statistics

Status: Complete for software and exploratory analysis; biological validation remains blocked by human inputs.

Work completed on 2026-08-11:

- Ran discovery, governance, ingestion, contracts, planning, real Scanpy/Squidpy tools, annotation assistance, grounding, claim reliability, visualization, storage/replay, promotion readiness, behavioral training, and both evaluation suites.
- Replaced the incorrectly named clustering `modularity` value, which had represented cluster count, with weighted kNN graph modularity; added PCA-space silhouette as a complementary diagnostic.
- Excluded zero-expression cells from clustering and cluster-dependent analyses while retaining them in ingestion and provenance counts.
- Normalized and log-transformed unnormalized expression before marker and differential-expression ranking.
- Promoted spatial-gene analysis from non-spatial Scanpy HVG ranking to seeded Squidpy Moran's I with permutation p-values and Benjamini-Hochberg FDR; retained HVG only as an explicitly non-spatial fallback.
- Added Moran's I and its graph setting to the shared spatial quality-metric contract.
- Added descriptive clustering, markers, spatial genes, and cluster co-occurrence to Markdown, HTML, and PDF blocked-pilot reports without presenting clusters as validated cell types.
- Added `spatial_variable_genes` to the seven-tool MVP surface and taught the MVP planner to recognize spatial-gene requests.
- Corrected the eval CLI so `--mvp` selects `eval/mvp_cases` by default, while explicit `--cases` still takes precedence.
- Added an MVP spatial-gene case, increasing current MVP coverage to 11 cases.
- Refreshed behavioral training after the planner change: 19 records, including 11 MVP query-plan-result records and 4/4 real Xenium exploratory wrapper runs, with mean score 1.0000 and no runtime warnings.

Measured healthy-brain results on a deterministic 3,000-cell sample:

- Loaded 3,000 of 24,406 cells and 374 panel features; 2 cells had no measured expression and 2,998 entered expression analysis.
- Leiden at resolution 0.5 produced 8 clusters, PCA silhouette 0.10703, and weighted graph modularity 0.74436.
- Adjacent-resolution stability was ARI 0.86020 for 0.3 versus 0.5 and 0.87271 for 0.5 versus 0.8.
- Marker programs were biologically plausible for broad neural/glial, vascular, and inhibitory-neuronal structure, but cluster names remain unvalidated.
- Squidpy Moran's I found 172 panel genes at FDR <= 0.05 with 100 permutations; the strongest was `TESPA1` at I=0.259063 and adjusted p=0.02410109.
- Cluster-level neighborhood enrichment tested 36 pairs on 2,998 assigned cells. These are exploratory cluster-structure results, not cell-type interaction claims.
- The blocked biological claim scored reliability 0.00; the asset-readiness claim scored 0.75.

Reference-assist findings:

- Healthy-brain transfer ran across 188 shared features and 4 reference classes for 1,000 cells, with mean neighbor-vote confidence 0.883.
- The reference was too narrow for biological validation: 256 cells were high review priority, 64 carried lineage evidence absent from the reference, 59 disagreed with marker evidence, and the platform-shift ratio was 2.85.
- Glioblastoma transfer correctly refused the local mouse reference for the human target and wrote no candidate labels.

Verification:

- Unit tests pass 99/99 in `.venv`.
- Legacy eval passes 15/15 and MVP eval passes 11/11, both with mean score 1.0000.
- Real backend validation passes Scanpy differential expression and clustering plus Squidpy Moran's I and neighborhood enrichment.
- Runtime version checks and `pip check` pass; optional PyTorch models remain isolated.
- All three import-boundary contracts remain intact.
- The six-page A4 healthy-brain PDF was rendered page by page and visually checked with no clipping, overlap, or unreadable tables.

Detailed report:

- `outputs/layer_audit_20260811/LAYER_EVALUATION_REPORT.md`

### Step 42: Leakage-Aware Human Brain Expert Benchmark

Status: Engineering complete; awaiting expert labels and reviewed tissue regions.

Work completed on 2026-08-11:

- Added a reusable healthy-brain/glioblastoma benchmark builder and CLI.
- Ran real Scanpy expression clustering and marker detection on deterministic 10,000-cell pools from both local Xenium sections.
- Selected 750 review cells per tissue with square-root cluster balancing, round-robin spatial coverage, difficult reference cases, and bounded QC-tail representation.
- Generated morphology-aware Explorer-lite viewers, spatial maps, marker summaries, cell-label tables, ROI tables, cohort hashes, and split manifests.
- Froze provisional splits by complete spatial block before expert truth is entered.
- Added validation for cross-table ID identity, duplicate and blank IDs, reviewer provenance, all-split coverage, spatial-block leakage, and at least 90% joint label-plus-region coverage.
- Ensured frozen truth outputs contain only jointly reviewed cells and synchronized packet-level validation summaries.
- Added focused regression tests for deterministic cohort selection, spatial split integrity, QC balancing, joint completion, and frozen truth materialization.

Measured packet results:

- Healthy brain: 24,406 total cells, 10,000-cell pool, 9 clusters, silhouette 0.11455, modularity 0.77452, and 554/79/117 train/validation/test cells.
- Glioblastoma: 40,887 total cells, 10,000-cell pool, 11 clusters, silhouette 0.16364, modularity 0.77921, and 531/114/105 train/validation/test cells.
- Both cohorts represent 15 spatial blocks with zero block leakage.
- Healthy candidate-label evidence covers 116/750 selected cells; glioblastoma has no same-species local candidate reference and remains intentionally unprefilled.
- Both datasets remain `awaiting_expert_review`: label, region, and joint coverage are all 0%.

Required handoff:

- Complete at least 675 jointly reviewed label/ROI rows per tissue with reviewer IDs.
- Add a broad healthy human brain reference and a human glioblastoma reference; do not transfer the current mouse reference to the human GBM section.
- Add independent donors or sections before claiming condition-level generalization.
- Complete institutional consent/data-use/PHI review even though the official 10x download page identifies the dataset license as CC BY 4.0.

Verification:

- Unit tests pass 104/104 in `.venv`, including five focused brain-benchmark tests.
- Legacy evaluation passes 15/15 and MVP evaluation passes 11/11, both with mean score 1.0000.
- Packet revalidation finds matching IDs, zero duplicate or blank IDs, all three splits, and zero spatial-block leakage in both tissues.
- All three import-boundary contracts remain intact.
- `pip check`, bytecode compilation, and `git diff --check` pass.
- Removed the deprecated explicit Pillow image mode; all three morphology-layer tests pass without that warning.
- Upstream `xarray-datatree` and `xarray-schema` deprecation warnings remain transitive through `spatialdata`; they do not currently break the validated environment but should be revisited during the next dependency upgrade.
- Automated `file://` browser navigation was blocked by the app security policy, so this pass did not add a new screenshot-level visual check; existing Explorer-lite integration coverage remains green.

Detailed report:

- `outputs/brain_expert_benchmark_20260811/BENCHMARK_PREPARATION_REPORT.md`

### Step 43: Count-Layer Integrity, Strict Backends, And Full-Section Scope

Status: Software complete; human biological validation remains pending.

Work completed on 2026-08-12:

- Added immutable `SpotRecord.raw_genes` source values alongside normalized `genes` analysis values.
- Made ingestion QC count-aware, preferred H5AD `layers["counts"]`, and preserved Xenium count summaries/morphology features without normalizing them as genes.
- Published source/count layers into AnnData and made Scanpy QC report the exact matrix source.
- Added sampled-versus-full-section provenance and blocked final validated inference on sampled sections unless a development override is explicit.
- Made Scanpy clustering/markers and Squidpy Moran's I/neighborhood analyses strict in Xenium lanes; backend failure now blocks claims instead of producing prototype statistics.
- Added Squidpy spatial-variable-gene analysis to the fixed validated tool plan.
- Routed Xenium requests from the general CLI and `POST /runs` API through the validated pilot; exposed scope/review/readiness options and fixed API report-format forwarding.
- Added scope and expression-layer evidence to reports, validation JSON, and run provenance.
- Made the brain benchmark candidate importer compatible with older `suggested_label` drafts without converting candidates into truth.
- Regenerated `outputs/brain_expert_benchmark_20260812/` with deterministic cohort hashes and zero spatial-block leakage.

Measured smoke-run results:

- Healthy brain: 300/24,406 sampled cells, 315 expression genes, five Scanpy Leiden clusters, silhouette 0.09867, modularity 0.58833, and median 165.5 raw transcripts/cell. No Moran's I gene passed FDR <= 0.05 in this small sample.
- Glioblastoma: 300/40,887 sampled cells, 340 expression genes, six Scanpy Leiden clusters, silhouette 0.12615, modularity 0.68322, and median 216.5 raw transcripts/cell. Moran's I found 136 panel genes at FDR <= 0.05; these are descriptive sampled-section findings, not validated disease claims.
- Both runs correctly returned `blocked_missing_validation_inputs` because final expert labels and reviewed regions do not exist.

Current expert benchmark:

- Healthy brain: 750 cells, 9 clusters, 552/80/118 train/validation/test, 12.00% candidate evidence, 0% reviewed truth.
- Glioblastoma: 750 cells, 11 clusters, 534/114/102 train/validation/test, 6.53% candidate evidence, 0% reviewed truth.
- Both require at least 90% joint expert label/ROI coverage (675 cells), reviewer provenance, and untouched spatial-block splits before truth is materialized.

Verification:

- Final full regression passed 106/106; focused count/scope/plan, report-compatibility, and full-section replay tests also passed.
- Healthy and glioblastoma unified-CLI runs completed with real Scanpy/Squidpy engines and comprehensive blocked HTML reports.
- Legacy eval passed 15/15 and MVP eval passed 11/11, both with mean score 1.0000.
- Real backend validation passed Scanpy differential expression/clustering and Squidpy Moran's I/neighborhood enrichment.
- `pip check` found no broken requirements; all three import contracts were kept; bytecode compilation and `git diff --check` passed.
- Detailed implementation report: `outputs/NEXT_MOVE_IMPLEMENTATION_REPORT_20260812.md`.

### Step: Correctness Release After the September 27 Audit

Status: Implemented; final verification recorded in `docs/correctness_release_20260927.md`.

- Shared Studio/pilot step execution now enforces the expanded plan's gate, preconditions, and real-backend requirement.
- One grouping resolver handles aliases across planning, analysis, and figures. Cluster-only dependencies no longer insert annotation.
- Label/ROI intake preserves cell-specific review provenance; biological tools and exports use that scope. Matching a reviewed class name alone does not confer review.
- Repaired the mislabeled descriptive cluster map and added a regression test of actual legend labels.
- Spatial claims bind to explicit tool/pair/direction/scope. Fixed raw/adjusted p handling, zero p-values, nonfinite statistics, and pair-specific measured robustness; removed the robustness proxy.
- Final Studio manifests include output hashes and effective plans; replay is supported, and partial artifact delivery is not reported as successful.
- Documentation inventory checks no longer change merely because the date advances or assert that discovered tests passed.
- Ran the full healthy-brain descriptive recipe and a reviewed-label breast sample. Breast biological tools excluded 137 unreviewed cells; replay reproduced all five numerical tool outputs exactly.
- Added reproducible evaluation script `scripts/evaluate_correctness_release.py` and regression suite `tests/test_correctness_boundary.py`.
- Final verification passed 530/530 unit tests (31 new regression cases), 6/6 import contracts, legacy routing 16/16, and MVP routing 13/13. A real sampled breast sweep supported pair-specific robustness for three of ten spatial claims; seven correctly remained blocked because their pairs lacked stored sweep measurements.
- Raw data, expert labels, and regions were not edited. No model was trained, no independent biological accuracy was asserted, and no GitHub push or desktop rebuild was performed.

Next: independent held-out breast benchmark, specialist brain label/ROI review, and whole-pipeline statistical calibration. See the release record for outputs and remaining limitations.

### Step: Buffered Annotation Holdout and Specialist Brain Handoff

Status: Benchmark and review tooling implemented; specialist review and independent donor validation remain blocked on external inputs.

- Evaluated the existing distance-weighted KNN transfer with label-free query objects, spatial-block train/validation/test splits, a 50-micron buffer, validation-only k selection, artifact hashes, and no-overwrite output directories.
- Fixed legacy H5 `Blank Codeword` feature handling in the shared control filter. The first exploratory benchmark was superseded; the accepted `_v2` run uses 313 expression genes.
- Accepted test result: 3,110 cells, 80.71% accuracy, 0.6208 macro-F1, 57.00% balanced accuracy. Fixed-threshold abstention retains 76.53% at 88.61% accuracy. These are internal section-level metrics, not independent donor accuracy.
- Preserved both existing 750-cell brain cohorts; prepared blinded first-pass sheets and separate machine evidence, with morphology-backed candidate-domain context (12 healthy-brain and 13 glioblastoma domains).
- Added explicit specialist decision/provenance and anatomical-evidence checks, immutable cohort/split checks, per-split joint coverage requirements, and staged export of accepted rows only. Current accepted labels/regions are zero for both cohorts; no final brain files were fabricated.
- Added 18 tests covering leakage, hidden-label invariance, buffering, metrics, control parsing, review provenance, immutable splits, and staging.
- Verification passed: 548/548 full-suite tests, 6/6 import contracts, all 12 accepted benchmark artifact hashes, compilation, and documentation checks. Logs are in `outputs/annotation_benchmark_verification_20260927/`.
- Results, limitations, output links, and next steps: `docs/annotation_benchmark_20260927.md`.

### Step: Remove Superseded Planning Documents and Reclaim the Repository

Status: Complete

Why:

- The repository's `.git` directory had grown to 112 GB against a working tree whose largest tracked blob is a 1.7 MB PNG. 74 GB of that was leftover `tmp_pack_*` files from interrupted pack operations dated 23-24 May, which git itself reports as `garbage`; the rest was unreachable objects, almost certainly `data/` committed before `.gitignore` excluded it.
- Sixteen documents were point-in-time records of superseded plans rather than descriptions of current behaviour. `docs/mvp_plan_v4_review.md` reviewed a file on a Desktop that was never in the repository at all.

What was removed:

- Repacked and pruned with `git gc --prune=now`: 112 GB to 7.5 MB. All nine refs, 89 commits and 1,205 reachable objects verified identical before and after, `git fsck` clean.
- Plan and status records: `ARCHITECTURE_REVIEW.md` (a review of the original Visium v0.1 proposal), `INGESTION.md`, `docs/research_proposal.md`, `docs/next_steps.md`, `docs/phase_1_2_status.md`, `docs/v2_implementation_status.md`, `docs/plan_v1_v2_comparison.md`, `docs/layer_plan_review.md`, `docs/mvp_plan_v4_review.md`, `docs/mvp_plan_v7_review.md`, `docs/operational_readiness_audit.md`, `docs/expert_label_ready_xenium_mvp.md`, `docs/real_agent_acquisition_and_operations.md`, `docs/spatialomics_build_plan_v2.html`, `docs/spatialmind_studio_prototype.html`, `docs/SpatialMind.png`.
- Regenerable artifacts: `.venv-deep` (3.4 GB, supporting only scaffold tools -- `cell2location` appears in the codebase once, as a documentation URL on `spatial_deconvolution`, which is `capability=unavailable`), `build/`, `tmp/`, every cache directory, and the stray `.DS_Store` files.

What was deliberately kept:

- `docs/gate_enforcement.md` and `docs/validated_xenium_pilot.md` had zero inbound references and would have been cut by a link-count rule. Both describe current product behaviour -- the gate invariant and the pilot layer -- rather than a past decision. Reference counting is not a test of whether a document is still true.
- `data/`, `outputs/` and `dist/`: research inputs, analysis products and the built app.
- `spatialmind/api/` and `spatialmind/batch/`: a second service, exercised only by `tests/test_api.py` and excluded from the packaged app. Unused is not the same as abandoned, and that call is not one to make while tidying.

Verification:

- Full suite 484/484, import contracts 6/6, legacy eval 16/16, MVP eval 13/13, `check_doc_numbers.py --check` clean.
- `docs/agent_architecture.md` corrected: it still described the `layers["counts"]` that the matrix-memory work removed.

### Step: Ordered Brain Study Readiness and Rare-Class Development

Status: Software preparation implemented; biological completion remains blocked on real reviewers and verified external inputs.

- User confirmed that no reviewers are available. Added explicit unassigned specialist/neuropathologist roles, acceptance/qualification records, assignment-aware staging, and an ordered readiness CLI. No people were assigned without acceptance and no review decisions were manufactured.
- Added a registered-image evidence validator: exact dataset and image hashes, assigned neuropathologist, documented section pairing and visual approval, explicit pixel-to-micron affine convention, and independent landmark residual checks. Local brain data still lack matched H&E/IHC.
- Retrieved and hashed BioStudies S-BSST2273 repository metadata only. It lists GBM annotations and H&E, but donor non-overlap, panel suitability and truth quality are not yet verified; no expression/annotation archive was downloaded or declared an external benchmark.
- Added external-test manifest checks for recorded donor independence, provenance, separate hashed expression/truth, frozen crosswalk/protocol, and custodian sealing. These checks do not independently certify biological truth or provide operating-system access control.
- Added opt-in training-prior correction to the production KNN annotation tool; default power zero preserves predictions. On 11,263 frozen breast training and 3,737 validation cells, validation-only selection chose power 0.25. Macro-F1 increased 0.6705 -> 0.7196, rare-class macro-F1 0.4749 -> 0.5788, and accuracy 82.53% -> 82.66%; coverage at 0.6 decreased 76.91% -> 75.17%.
- The old test truth was not opened/rescored. These are reused validation-set selection metrics, not brain training, independent test performance or a production promotion. An automatic brain external-test executor remains deferred until reviewed development data and a compatible independently labeled donor exist.
- Output examples: `outputs/rare_class_development_20260927/report.html` and `outputs/brain_specialist_handoff_20260927/ordered_readiness_report.json`. All six new experiment artifact hashes verify.
- Added 13 focused tests covering unassigned roles, identity mismatch, image pairing/units/hash/landmark errors, donor overlap, metadata-only acquisition, opt-in production behavior and training/validation-only selection. These and all 18 existing holdout/handoff tests pass; all six import contracts pass.
- Final verification: full suite 561/561 passed in 274 seconds, documentation inventory check passed, and `git diff --check` passed. Existing dependency deprecation, synthetic-data, sparse-efficiency and test file-handle warnings remain non-fatal.
- Updated README and added `docs/brain_review_execution.md` with recruitment brief, image/external manifest templates, acquisition links, metrics, commands, and explicit blockers.
