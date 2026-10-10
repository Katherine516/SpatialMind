# How the SpatialMind Agent Works

Current assessment: the [October 3 correctness upgrade](correctness_upgrade_20261003.md)
repairs the eight findings from the [layer evaluation](layer_evaluation_20261003.md)
and starts the [data-expansion roadmap](multimodal_roadmap_20261003.md).
Passing software tests does not establish assay or biological validation.

The [P1 reference-readiness increment](reference_readiness_20261003.md) adds
explicit matrix/feature pairing, donor filtering before label reads, measured
panel metadata and source-observation provenance. Collection-level donor plans
remain unapproved. The [ordered P1 follow-up](brain_p1_implementation_20261003.md)
replaces path-based merged IDs with content-bound source/observation identities,
adds chunked CSR H5AD storage and verifies adjacent cache manifests during loading.
Legacy downstream adapters still use bounded SpotRecord objects; this is not an
end-to-end out-of-core backend. Reference curation and a human-approved prespecified
development protocol now gate reviewed brain model selection.

This is the single end-to-end explanation of the agent: what each layer does, what
runs when, and where the gates sit. The README is the command reference;
`development_tracking.md` is the historical work log. Start here.

Last verified: 2026-10-03. Full suite 637/637 in 191.843 s.
Import-linter 6/6, legacy routing 16/16
and MVP routing 13/13 passed. These are software checks, not brain biological
accuracy. Current verification is in `outputs/brain_p1_implementation_20261003/`;
sampled brain reports from the preceding increment are under
`outputs/correctness_upgrade_20261003/final/`.
Historical held-out annotation results are in [the benchmark record](annotation_benchmark_20260927.md),
and were not rescored or promoted in this upgrade. The ordered brain review gates
and breast-only rare-class experiment are documented in [the brain review execution record](brain_review_execution.md).

Inventory counts: 649 discovered unit tests; 16 legacy cases; 13 MVP cases; 6 import contracts. Counts are not execution results.

## The one-sentence version

SpatialMind ingests a Xenium output bundle, prepares review artifacts, and refuses
to make biological claims until a human supplies expert cell labels and tissue
regions. Accepted review evidence unlocks label-dependent tool execution; this
is not proof of population-level biological validity. Reports attach per-claim
reliability scores, which remain heuristic until reviewed, donor-held-out
calibration supports interpreting them as probabilities.

## The six tiers

Read from the import graph, not from any docstring. Each tier depends only on
tiers below it.

| # | Tier | Lines | What it is for |
| --- | --- | --- | --- |
| 6 | **Surfaces** — `app`, `api`, `cli`, `batch`, `review`, `promotion` | ~5,330 | How a human or another program gets in |
| 5 | **Execution** — `agent`, `pilot`, `workflows` | ~3,880 | Turning a plan into a run |
| 4 | **Derived products** — `viz`, `methods`, `datasets`, `governance` | ~2,570 | Reports, figures, reliability scores, manifests |
| 3 | **The gate** — `gatekeeper` | 278 | The one tier whose job is to say no |
| 2 | **Capability** — `ingestion`, `tools`, `storage`, `memory`, `llm` | ~7,100 | Things that can do work, knowing no workflow |
| 1 | **Contracts** — `contracts`, `schemas` | ~860 | The vocabulary every tier speaks |

**Tier 1** must import nothing else in the project. The moment the vocabulary
imports a layer, every layer is coupled through it.

**Tier 2** is deliberately workflow-ignorant. `ingestion` reads ~6 MB of a 2.5 GB
bundle into one contract; `tools` is the 30-tool registry with capability states.
Neither knows a gate exists.

**Tier 3** is thin and sits alone because of who has to reach it. `gatekeeper`
imports only `ingestion`, `tools` and `schemas`, so every executing tier above
can call it without a cycle. `pilot_gate` moved here for exactly that reason: it
lived in `pilot.xenium`, which imports `agent.runtime`, so an agent-layer caller
would have closed a loop.

**Tier 4** consumes results and produces artifacts. Contracted as pure consumers:
`viz` and `storage` may not import the agent or app, so rendering can never reach
back and trigger analysis.

**Tier 5** is where a plan becomes a run. `pilot` is the largest single unit in
the codebase at 3,065 lines.

**Tier 6** is entry points. `app` is contracted as a top layer nothing else may
import.

### What is actually enforced

Six import-linter contracts enforce the layer ordering and forbidden edges.
Studio and the canonical pilot share an execution boundary that checks effective
calls after dependency insertion. Group resolution and per-cell review provenance
are shared by tools and presentation. See the
[September 27 correctness release](correctness_release_20260927.md) for regression
cases, real-data measurements, and the biological validation still required.

### Shared Execution and Compatibility

`agent.planning` owns typed plans and parameter-aware dependencies; `app.planner`
re-exports its API for compatibility. Supported executors use
`agent.runtime.execute_tool_step`, which resolves group aliases, requires real
backends, checks capabilities/preconditions and the effective gate, and records
effective parameters in each result.

`SpatialMindAgent` retains v1 intent parsing for saved prompts, but maps intents
to canonical annotation, neighborhood enrichment and gene-overlay tools. Repeated
gene overlays have numbered artifacts. `AlgorithmEngine` remains a compatibility
module, not an active backend. The local loop and legacy intent parser are not
yet a single planning vocabulary; the shared executor prevents the remaining
planning differences from bypassing policy.

Old colocalization reports are not numerically equivalent to real Squidpy
enrichment; regenerate them before comparison. Non-Xenium biological runs still
record `gate_not_evaluated`, never an automatic validated status.

### Three self-descriptions that disagreed

Worth recording, because it is how the drift stayed invisible. The codebase
described its own layering three incompatible ways: `orchestrator.py` said "six
layers" and named the v1 set (ingestion, algorithms, reasoning, visualization,
storage, memory), omitting `tools`, `pilot`, `gatekeeper` and `app`;
`__init__.py`'s `__all__` listed fifteen names flat; and the import graph said
the six tiers above. The most authoritative-sounding one was the most out of
date. It has been corrected.

## Stage 1: Input — the `.xenium` bundle

A Xenium run ships a ~2.5 GB folder. The agent reads about 6 MB of it.

| File | Size | Used for |
| --- | --- | --- |
| `experiment.xenium` | 1.4 KB | Manifest: run/panel metadata, `pixel_size`, asset links |
| `cells.csv.gz` | ~2 MB | Cell IDs + centroids (microns) |
| `cell_feature_matrix.h5` | ~4 MB | Per-cell targeted-panel expression |
| `gene_panel.json`, `metrics_summary.csv` | small | Panel identity, run QC |
| `cell_boundaries.parquet` | ~2.5 MB | Segmentation polygons (viewer) |
| `morphology*.ome.tif` | ~450 MB | Tissue image, read as a downsampled pyramid level |
| `transcripts.*`, `*.zarr.zip` | ~1.5 GB | **Not parsed** — catalogued for provenance only |

`experiment.xenium` is a *manifest, not data*. Passing either the `.xenium` file or
its parent folder works identically: `_resolve_xenium_input_path` resolves the file
to its directory.

The agent operates at **cell** level, not transcript level. That is a deliberate
scope boundary, not an omission.

> Where a language model may and may not sit in this pipeline, and why the
> plan DAG means it never needs to emit a plan: [`llm_placement.md`](llm_placement.md).

## Stage 2: Ingestion → `SpatialDataset`

Everything downstream speaks one contract. `load_xenium` produces a
`SpatialDataset` of `SpotRecord`s carrying `cell_id`, `x`/`y` (microns),
`cell_type`, `region`, normalized analysis values in `genes`, immutable source values
in `raw_genes`, plus dataset-level metadata, QC metrics,
and caveats.

Two details that matter:

- **Full panel by default.** `max_features_per_record=0` keeps every measured gene
  per cell. Per-cell top-N truncation would silently turn mid-expression genes into
  zeros and distort PCA and marker ranking.
- **QC pseudo-features are not genes.** The loader stores `TRANSCRIPT_COUNTS`,
  `TOTAL_COUNTS`, `CELL_AREA`, and `NUCLEUS_AREA` alongside real counts. They are
  library-size and area proxies on a different scale, so
  `expression_feature_names()` excludes them from every expression matrix. Left in,
  they dominate PCA and rank as top "markers".
- **Source and analysis layers are separate.** Count-aware QC uses the preserved
  Xenium counts, carried into AnnData as `layers["source_values"]`. Library-size
  normalization and `log1p` change only biological values in `genes`; count
  summaries and morphology features remain unchanged. The built matrix has no
  separate `counts` layer -- it was a byte-identical copy of `source_values`,
  1.15 GB of it at full lymph-node scale, whose only reader used it to choose a
  label; `uns["spatialmind"]["raw_counts_available"]` carries that instead. H5AD
  ingestion still prefers an incoming `layers["counts"]` when one exists, and
  records source-value semantics when it does not.
- **Scope is explicit.** Every Xenium load records total cells, loaded cells,
  sampling method, fraction loaded, and `sampled` versus `full_section` scope.

## Stage 3: Label and region intake

The agent looks for two reviewer-supplied files inside the Xenium folder:

- `expert_cell_labels.csv`: cell_id, expert_label, confidence, reviewer_id,
  review_status, reviewed_at, evidence_ref; optional cl_id and notes.
- `cell_regions.csv`: cell_id, region, region_confidence, reviewer_id (or
  region_reviewer_id), review_status, reviewed_at (or region_reviewed_at),
  evidence_ref, region_basis; optional notes.

Both are matched by `cell_id`. Absent them, the loader's conservative marker-rule
labels are used **for review display only** and are never treated as truth.

Approval must be explicit (`reviewed`/`approved`), with an identified reviewer,
valid ISO date, finite confidence in [0,1] and evidence. Duplicate IDs are refused.
General user ROI decisions require an allowed basis; specialist brain benchmark
regions additionally require anatomical evidence, not merely user ROI membership.
These checks validate recorded provenance, not credentials or biological truth.

## Stage 4: The gate

`pilot_gate()` is the single decision point separating review prep from validated
analysis. It requires:

1. Core assets present (cell table, feature matrix, morphology, boundaries)
2. Expert labels applied, ≥70% coverage
3. User regions applied, ≥70% coverage
4. ≥2 biological cell classes
5. ≥2 user-defined regions
6. Complete-section scope for final validated inference

Missing review evidence yields `blocked_missing_validation_inputs`; a passing review gate on a sample yields `blocked_sampled_inference`; a failed required backend yields `blocked_analysis_backend`. A label-free descriptive lane still runs strict Scanpy/Squidpy QC, expression clustering, per-cluster markers, Moran's I, and cluster neighborhoods. Those outputs describe data-derived groups only and never name them as cell types.

## Stage 4b: Tool capability states

Every registered tool carries a capability:

| State | Meaning |
| --- | --- |
| `validated` | Real backend; may support biological claims once gated inputs exist |
| `descriptive` | Real backend; describes data-derived groups only |
| `experimental` | Real method, not yet trusted for claims |
| `unavailable` | Registered scaffold that returns a placeholder and does no work |

Scaffolds are detected automatically from the implementation, so the registry
stays honest even if a caller forgets to set the field. `list_plannable()` and
`to_anthropic_tools()` exclude them by default: of 30 registered tools, 12 are
plannable and 18 are hidden, so a model cannot select a tool that does nothing.
They remain in `list_all()` for provenance.

## Stage 5: Typed plan validation

`build_xenium_mvp_plan()` produces a typed tool sequence with declared
dependencies; `validate_tool_plan()` checks it. Plan validation checks *structure*
(ordering, dependencies, tools exist) against the full input set — input
*availability* is the gate's job alone. That separation is why a blocked run still
reports a valid plan instead of duplicating the gate's blockers as fake plan errors.

## Stage 6: The seven MVP tools

| Tool | Backend | What it does |
| --- | --- | --- |
| `qc_and_cluster` | Scanpy | Per-cell QC, then normalize → log1p → PCA → neighbours → Leiden on **expression**. Uses scanpy's exact sklearn kNN backend, falling back to the default when unsupported. `cluster_on="spatial"` opts into spatial-domain clustering. |
| `annotation` | — | Summarises applied expert labels |
| `marker_detection` | Scanpy | **One-vs-rest** markers for every cell type by default; explicit `group1`+`group2` gives a pairwise contrast |
| `spatial_variable_genes` | Squidpy | Moran's I over a tissue kNN graph. Coordinate-independent detection filter, followed by testing and BH correction over every eligible gene. Display top-N does not affect inference; Scanpy HVG is an explicit development fallback only |
| `region_summary` | — | Cell-type composition and feature means per user region |
| `cell_neighborhood_enrichment` | Squidpy | Permutation z-scores for cell-type adjacency |
| `feature_overlay` | — | Single-feature spatial values, with panel-absence guarding |

`qc_and_cluster`, cluster-group marker detection, `spatial_variable_genes`, and cluster-group neighborhood enrichment can run in the descriptive lane before expert labels exist. Annotation, reviewed-region summaries, and cell-type relationship claims remain validation-gated.

### Complete spatial gene testing family

Only a prespecified detection filter precedes inference. It is invariant to
spatial permutation; the previous same-data analytic Moran ranking was removed
because selected-set BH did not account for that selection. Every eligible gene
is tested using `n_perms`, with BH correction over the complete eligible family.
The filter is not relaxed when no genes survive.

`all_tested_genes` retains every tested row; `top_genes` is a separate display
slice. Tables include tested rows and explicit detection-filter exclusions.
Legacy `screen_candidates` and `screened_n_perms` do not cap the testing family
or raise its budget; use `n_perms` explicitly. Finite permutation resolution,
spatial dependence and tissue-specific null calibration remain limitations.

Index/embedding positions are not exposed as tissue coordinates. Wide matrices
use CSR and source-value QC uses sparse reductions, while small targeted panels
retain the existing dense path. See the correctness upgrade for measured scope
and remaining storage/registration work.

All statistical tools in the validated plan carry `strict_engine=True`. If Scanpy,
Leiden, or Squidpy is absent or fails, the run records a backend blocker; it cannot
silently publish coordinate bins, pseudo-p-values, variance ranks, or radius counts.

## Stage 7: Robustness and spatial relationships

- **Robustness sweep** (`run_neighborhood_robustness`) re-runs neighbourhood
  enrichment across a graph-size grid (`n_neighs` 6/10/15) and scores stability as
  `0.6 × sign_agreement + 0.4 × top-K Jaccard`. This is a real perturbation
  measurement, and it feeds the `R` reliability component.
- **Spatial relationships** (`build_spatial_relationship_summary`) combines
  enrichment, per-pair stability, nearest-neighbour distance, and region overlap
  into descriptive rows. Every row carries an `evidence_status`
  (`stable_enriched` / `*_sensitivity_limited` / `weak_or_indeterminate`) and an
  `allowed_interpretation` string. Adjacency is never described as interaction,
  signalling, or causation.

## Stage 8: Claims and reliability

The claim ledger marks each claim `supported`, `dropped`, or `refused`. Every claim
is scored on four components, combined by **weakest link**:

```
reliability = min(S_statistical, A_annotation, P_panel, R_spatial_robustness)
```

`S` = statistical support, `A` = annotation quality/coverage, `P` = panel adequacy,
`R` = the measured robustness sweep. Weakest-link keeps a claim at 0.0 whenever any
required evidence class is missing. The calibrated logistic combiner stays `not_fit`
until expert-reviewed claim truth exists.

## Stage 7b: Biological replication

Cells within one section are not independent biological replicates. A
healthy-versus-disease difference computed from one section per condition is
pseudoreplication: the apparent sample size is the cell count, but the real
sample size is one donor per group, so the difference cannot be attributed to the
conditions however many cells were measured.

`assess_condition_replication` reports the design — sections and donors per
condition — and `build_brain_comparison_report` refuses condition-level output
when it is not met, returning `blocked_insufficient_biological_replication`. It
still emits a per-section descriptive summary; it never subtracts one condition
from the other.

This matters most *after* expert labels arrive. Labels alone would otherwise flip
the comparison to `ready` and produce condition deltas from n=1 versus n=1, so the
guard exists ahead of the review sprint rather than after it. Once replicates
exist, condition-level statistics should be section-aware or pseudobulk.

## Stage 8b: Running it — scope, sampling, and cost

`scripts/analyze.py` is the entry point for someone who has just produced a Xenium
run and wants a report:

```bash
python scripts/analyze.py <xenium_folder> --out outputs/analysis
```

It runs the descriptive lane and prints where the report, viewer, and JSON landed,
plus what expert review would add. No labels required.

**How many cells to analyze.** Clustering was compared against full-section labels
on shared cells for a healthy-brain section:

| Sample | Clusters found | ARI vs full section |
| --- | ---: | ---: |
| 3,000 | 8 | 0.79 |
| 6,000 | 10 | 0.90 |
| 20,000 | 10 | 0.94 |
| full (24,406) | 10 | — |

Cluster structure is recovered from roughly 6,000 cells; 3,000 merges or drops
populations. Runs below that carry an explicit `sampling_warning` in the payload,
the report, and the CLI. The default cap is 20,000.

**Display is capped separately from analysis.** The viewer draws one DOM node per
cell, so a full section would otherwise produce a file no browser opens usefully.
`spatialmind/viz/display_sampling.py` subsamples on a spatial grid — deterministic,
coverage-preserving — for the viewer, the SVG, and the interactive HTML only.
Analysis still uses every loaded cell, and the cap is stated in the artifact.
Measured on the 377,985-cell lymph node section: viewer 7.35 MB against roughly
131 MB projected uncapped. Output is bounded by the cap rather than by input size.

**Stage timings** are recorded for every descriptive run (`stage_seconds`) and
rendered in the report, so slow stages are identifiable rather than guessed at.

## Stage 9: Explorer-lite viewer

A self-contained HTML review UI — no server, no external viewer — written entirely
in Python (`spatialmind/viz/explorer_lite.py` + `spatialmind/viz/morphology.py`).

**Layers**

1. **Morphology image.** `tifffile` reads the OME-TIFF pyramid, picks the smallest
   level still meeting the requested detail, percentile contrast-stretches to 8-bit,
   and embeds a base64 PNG. The full-resolution plane is never decoded, so a 450 MB
   image costs a few seconds.
2. **Segmentation boundaries.** Per-cell polygons from `cell_boundaries.parquet`,
   loaded only for the cells in view.
3. **Cells.** Coloured by label, cluster, or region; clickable, searchable,
   box-selectable.

**Registration.** Centroids are microns, the image is pixels, related by
`pixel = micron / pixel_size`. Micron-Y maps **directly** to image rows
(verified empirically: mean intensity at cell positions 143.7 direct vs 39.7 flipped
vs 48.9 random background), while the plot draws Y upward — so the image is mirrored
back about its own centre. Verified in-browser: 400/400 sampled centroids fall
inside their own polygon, max offset 0.63 SVG units.

**Output.** Reviewers assign labels/regions and export `expert_cell_labels.csv` and
`cell_regions.csv` — closing the loop back to Stage 3.

Every layer degrades to an explicit `status` payload when an asset or optional
dependency is missing, so dependency-light environments still get the cell map.

Not a full Xenium Explorer replacement: no deep-zoom tiled navigation, no
transcript-level rendering, no persistent browser-side label database.

## Stage 10: Reports, provenance, replay

Full runs write markdown/HTML (optionally PDF) reports, machine-readable tool JSON,
figures, review templates, and a hashed run record for replay. Blocked runs still
produce the full review packet — that is the point: a blocked run should be
*useful*, not empty.

## Two speeds

- **`readiness_only=True`** — gate, readiness, plan validation, and claim status
  only; writes one `pilot_validation.json`. ~0.67s and 17 KB per dataset, no
  matplotlib. Used by the multi-dataset scorecard.
- **Full run** — every artifact above, including the morphology-backed viewer.
- **Sampled review run** — bounded by `max_records`; useful for review preparation
  and descriptive QA, but not eligible for final biological claims.
- **Full-section validated run** — launched with `--full-section` after labels and
  regions pass; analysis and review-template row limits are independent.

## Getting labels: the two routes

1. **Expert annotation** — annotate in Explorer-lite (or Xenium Explorer / QuPath /
   napari), export the two CSVs. This is the authoritative route.
2. **Reference transfer** — `scripts/build_candidate_cell_labels.py --reference`
   runs a distance-weighted KNN over shared features from a labelled scRNA reference
   (`.h5ad` or tabular) and emits one predicted label plus confidence per cell.

Route 2 produces **candidates for review, never expert truth**. The output file is
`expert_cell_labels_candidate.csv` with `review_status=needs_expert_review`; a
reviewer must complete `expert_label` and `reviewer_id` and save it as
`expert_cell_labels.csv` before the gate accepts it. Without a labelled reference
dataset the tool reports feature *compatibility only* and explicitly states that no
labels were transferred.

### Route 2's failure mode: a reference that cannot name the tissue

A KNN vote is taken over the classes the reference *happens to contain*, so it
cannot express "none of these". A cell whose true type is absent still gets its
nearest available label, usually at high confidence — and neither the vote
fraction nor panel overlap can surface it. Measured on the healthy brain section
against three Human Brain Atlas superclusters: mean confidence 0.8845 while
roughly 40% of cells belonged to lineages (astrocyte, endothelial, myeloid, OPC)
the reference had no class for.

`assess_reference_lineage_coverage` closes this. It compares the lineages the
reference can name against the lineages the target's own markers support, and
`reference_label_transfer` **refuses** when two or more populations are
unnameable — before fitting the KNN, so a doomed run costs seconds rather than
minutes. `scripts/build_candidate_cell_labels.py --inspect` runs the same check
header-only in about 1.5s. `allow_incomplete_reference=True` overrides it and the
caveat survives into the report.

The counts it reports are a **floor, not an estimate**. They come from the strict
per-cell `marker_lineage` rule, which under-counts sparse populations but does not
invent them. Two looser estimators were tried and rejected: raw marker argmax
hands low-expression lineages (endothelial) to abundant ones (neuronal) on
background signal, and per-lineage standardization pushes assignment toward
uniform, inventing thousands of lymphoid cells in a brain section. The refusal
therefore rests on *which* lineages are confidently present and unnameable — which
the strict rule does establish — not on a precise share it cannot.

## The invariant

Every layer is built so that missing evidence produces an explicit refusal rather
than a confident guess. When you change this agent, preserve that: a tool must never
report work it did not do.
