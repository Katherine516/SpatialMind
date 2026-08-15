# SpatialMind Next Development Plan

## 2026-08-12 Priority Update

The scientific-correctness sprint is implemented:

- Xenium source counts are preserved separately from normalized expression; count-aware QC now reports `source=raw_counts`.
- Morphology/count-summary pseudo-features are excluded from normalization and expression analysis.
- Validated Scanpy/Squidpy tools fail closed with `strict_engine=True`.
- Sampled review runs and complete-section inference are explicitly separated; final claims require `--full-section`.
- The general CLI and `POST /runs` route Xenium inputs through the validated pilot rather than the lightweight three-tool path.
- Spatial variable genes are part of the fixed validated Xenium plan.
- A fresh leakage-aware packet is available at `outputs/brain_expert_benchmark_20260812/`.

The next milestone is no longer another unsupervised software pass. It is the first human-grounded validation loop:

1. Review at least 675/750 jointly labeled and region-assigned cells in each brain packet, including reviewer IDs and timestamps.
2. Revalidate the packet and freeze the generated train/validation/test truth files without changing spatial-block assignments.
3. Train or calibrate annotation only on `train`; select thresholds on `validation`; report macro-F1, balanced accuracy, per-class recall, abstention coverage, and calibration on untouched `test`.
4. Apply the accepted annotation procedure across each full section, audit uncertain/out-of-reference cells, and obtain reviewer approval for the final `expert_cell_labels.csv` and `cell_regions.csv`.
5. Run the final pilot with `--full-section`, then review claim truth and calibrate S/A/P/R reliability on held-out claims.
6. Add independent sections/donors before making healthy-versus-glioblastoma condition-level generalizations.

Do not convert `candidate_label`, `suggested_label`, expression clusters, or grid-based draft regions directly into truth. They are review evidence only.

## Current Position

SpatialMind has moved beyond the earlier v0.3/v2 scaffold. The current project state is a v7 MVP agent with:

- layer-boundary contracts in `spatialmind/contracts/`,
- v7 scRNA/scATAC-lite, Xenium-primary, and reference-assist workflow definitions,
- MVP mode through `SpatialAgent(mvp_mode=True)`,
- full `requirements.txt` environment installed in `.venv`,
- real H5AD and Xenium HDF5 ingestion paths,
- validated Scanpy/Squidpy wrappers for first-line methods,
- 45 unit tests passing,
- legacy eval passing 15/15,
- MVP eval passing 10/10,
- a real Xenium breast MVP run with report, JSON outputs, static PNG/SVG, and interactive HTML.
- a glioblastoma expert-review packet with Cell Ontology label guidance.

The agent is now good enough to run controlled MVP analyses on local sampled datasets. It is not yet good enough to claim expert biological conclusions without better annotation labels, reference transfer, and benchmark validation.

## What Is Complete

- Full runtime dependency file: `requirements.txt`.
- Local full environment validation: Scanpy, Squidpy, AnnData, h5py, NumPy, SciPy, Pandas, Matplotlib, Seaborn, and related packages.
- H5AD ingestion adapter with AnnData support.
- Xenium directory ingestion with `cell_feature_matrix.h5` barcode matching and top-feature loading.
- v7 `CellByFeatureContract` use for scRNA, scATAC gene activity, and Xenium targeted RNA.
- MVP workflows for scRNA-lite, scATAC-lite, Xenium-primary, and reference-assisted annotation.
- MVP tools for QC/clustering, annotation, marker detection, feature overlay, user-region summary, and cell-neighborhood enrichment.
- Typed `QualityMetrics` attached to tool results, separating QC, diagnostic metrics, and statistical evidence.
- Grounding caveats for targeted Xenium panels, accessibility-inferred scATAC features, transferred labels, and deferred v1.0 workflows.
- Cluster-style visualizations and Xenium breast run artifacts under `outputs/xenium_breast_mvp/`.
- Expert-label readiness inventory and label templates under `outputs/xenium_expert_mvp_readiness/`.
- External label-table adapter keyed by Xenium `cell_id`.

## Immediate Next Steps

### 1. Replace marker-rule breast labels with validated annotation

The breast MVP run currently uses conservative marker rules, and the other local Xenium datasets only have broad marker-rule fallback labels or unannotated cells. The next scientific step is to produce defensible labels.

Acceptance criteria:

- Load user-provided labels when available.
- Add CellTypist/reference annotation for scRNA-like data.
- Add Scanpy ingest or scANVI-style reference transfer for Xenium where a matched reference exists.
- Store label method, confidence, evidence genes, and caveats in every run output.

Current accepted label format:

- filename: `expert_cell_labels.csv`, `cell_labels.csv`, `cell_annotations.csv`, `annotations.csv`, or `labels.csv`;
- required columns: `cell_id`, `expert_label`;
- optional columns: `confidence`, `notes`.
- recommended extended columns: `cell_id`, `expert_label`, `cl_id`, `secondary_state`, `confidence`, `notes`.

Use broad Cell Ontology-compatible labels from `docs/cell_ontology_labeling_guide.md` for the first validated brain/glioblastoma pilot. Keep glioblastoma programs such as `cycling`, `hypoxic`, `reactive`, or `glioblastoma_like` in `secondary_state` or `notes`, not as primary Cell Ontology labels.

### 2. Build the supervised training corpus

The agent needs expert-labeled examples before fine-tuning or serious planner training.

Required data:

- natural-language query,
- dataset metadata and modality,
- expected tool plan,
- expected parameters,
- expected refusal or clarification when appropriate,
- expert-reviewed output interpretation,
- ground-truth or reference cell labels,
- provenance for all data and labels.

Initial target: 100 to 200 curated examples split across scRNA, scATAC, Xenium, and integration workflows.

### 3. Upgrade prototype MVP methods to production methods

Priority wrappers:

- `annotation`: CellTypist or reference-mapping backend, gated by expert/reference evidence.
- `marker_detection`: strengthen Scanpy ranking, pct-expressing, AUROC, and per-cluster marker outputs.
- `region_summary`: import user-provided region labels from CSV/JSON and add report-ready plots.
- `cell_neighborhood_enrichment`: default to real Squidpy permutation testing with a single-process-safe threading backend.
- `feature_overlay`: richer PNG/HTML expression overlays with measured-missing-gene handling.

Deferred production methods:

- `reference_label_transfer`: Scanpy ingest first, scANVI later, outside the active v7 MVP tool set.
- `motif_tf_activity`: chromVAR/pychromVAR or Signac-style validation, outside the active v7 MVP tool set.

### 4. Expand evaluation beyond happy-path planner tests

Add cases for:

- missing target genes in Xenium panels,
- ambiguous sample names,
- insufficient cell counts,
- invalid cell labels,
- unsupported modalities,
- privacy-sensitive requests,
- overclaiming statistical significance,
- transferred-label uncertainty,
- scATAC expression-vs-accessibility wording.

Acceptance criteria:

- at least 100 MVP cases,
- tool-selection accuracy >= 0.85,
- graceful-failure score >= 0.95,
- no unsupported statistical claims in report text.

### 5. Run all local datasets through the same report path

The first readiness pass has now covered breast, lymph node, healthy brain, and glioblastoma. All four have matrices/images/boundaries/clusters, but all four still need expert or reference-transferred biological labels.

Acceptance criteria:

- one report folder per dataset,
- shared JSON run schema,
- per-dataset readiness summary,
- comparable cluster/annotation visualizations,
- clear caveats for each dataset.

Current inventory output:

- `outputs/xenium_expert_mvp_readiness/xenium_expert_mvp_readiness.md`
- `outputs/xenium_expert_mvp_readiness/summary.json`

## Data Needed For Training

The most useful training data is not only raw expression. It is paired expert decision data:

- Public Xenium datasets with matched histology, panel metadata, cell coordinates, and validated or reference-derived cell labels.
- scRNA references from the same tissue domain as each Xenium sample.
- scATAC gene activity matrices with motif/TF labels or known marker programs.
- Negative cases where the correct answer is refusal, caveat, or clarification.
- Expert-reviewed reports that mark which conclusions are supported, weak, or unsupported.

SpatialMind should treat raw public datasets as evaluation substrates and expert-labeled query-plan-result examples as training records.

## Recommended Next Milestone

**Milestone: Expert-label-ready Xenium MVP with ontology-grounded labels.**

Run breast, lymph node, healthy brain, and glioblastoma datasets through the same v7 MVP workflow; add Cell Ontology-grounded validated labels for at least one dataset; add user-provided region labels for at least one tissue; expand eval to 50 MVP cases; and write a pilot report that separates agent-generated observations from expert-confirmed findings.
