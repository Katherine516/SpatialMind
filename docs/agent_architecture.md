# How the SpatialMind Agent Works

This is the single end-to-end explanation of the agent: what each layer does, what
runs when, and where the gates sit. The README is the command reference;
`development_tracking.md` is the historical work log. Start here.

Last verified: 2026-08-26. Unit tests 166/166; legacy eval 15/15; MVP eval 11/11; real Scanpy/Squidpy backend checks passed; import-linter 3/3.

## The one-sentence version

SpatialMind ingests a Xenium output bundle, prepares review artifacts, and refuses
to make biological claims until a human supplies expert cell labels and tissue
regions — at which point it runs a fixed, validated tool plan and reports every
claim with a per-claim reliability score.

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
- **Source and analysis layers are separate.** Count-aware QC and AnnData
  `layers["counts"]` use preserved Xenium counts. Library-size normalization and
  `log1p` change only biological values in `genes`; count summaries and morphology
  features remain unchanged. H5AD ingestion prefers `layers["counts"]` when it
  exists and records source-value semantics when it does not.
- **Scope is explicit.** Every Xenium load records total cells, loaded cells,
  sampling method, fraction loaded, and `sampled` versus `full_section` scope.

## Stage 3: Label and region intake

The agent looks for two reviewer-supplied files inside the Xenium folder:

- `expert_cell_labels.csv` — `cell_id,expert_label,confidence,notes`
- `cell_regions.csv` — `cell_id,region,region_confidence,notes`

Both are matched by `cell_id`. Absent them, the loader's conservative marker-rule
labels are used **for review display only** and are never treated as truth.

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
`to_anthropic_tools()` exclude them by default: of 30 registered tools, 16 are
plannable and 14 are hidden, so a model cannot select a tool that does nothing.
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
| `spatial_variable_genes` | Squidpy | Moran's I over a spatial kNN graph. Genes are **screened before permutation testing** (see below), so FDR is corrected over the tested subset, not the whole panel; Scanpy HVG is an explicit development fallback only |
| `region_summary` | — | Cell-type composition and feature means per user region |
| `cell_neighborhood_enrichment` | Squidpy | Permutation z-scores for cell-type adjacency |
| `feature_overlay` | — | Single-feature spatial values, with panel-absence guarding |

`qc_and_cluster`, cluster-group marker detection, `spatial_variable_genes`, and cluster-group neighborhood enrichment can run in the descriptive lane before expert labels exist. Annotation, reviewed-region summaries, and cell-type relationship claims remain validation-gated.

### Gene screening before permutation testing

Permutation testing dominates `spatial_variable_genes`: measured at 43s for
`n_perms=100` across 491 genes, against 0.5s for the analytic Moran's I. Running
`n_jobs=4` measured *slower* than `n_jobs=1`, so the lever is testing fewer genes
rather than testing them faster. Two screens run first, and both are recorded:

1. **Detection filter.** Genes detected in too few cells are dropped. They cannot
   support a spatial claim and only enlarge the multiple-testing burden.
2. **Analytic pre-rank.** Survivors are ranked by the near-free analytic Moran's I,
   and only the strongest candidates are permuted.

On a 24,406-cell section this took the stage from 60.6s to 17.1s and the whole
descriptive lane from 114.8s to 72.0s, with the top genes and their order
unchanged.

**This changes what the p-values mean, so the report says so.** Every run states
the screening rule, the panel/detected/tested gene counts, and that FDR is
corrected over the tested set. Reporting "50 significant" without that context
would read as 50 of 491 rather than 50 of 50 tested.

The permutation budget stays at `n_perms` *per gene*. Raising it to spend the
saving back is a measured mistake: 50 genes at 999 permutations is the same total
work as 491 at 100, and it ran no faster. `screened_n_perms` raises it explicitly
at proportional cost. Note also that the strongest genes tie at the p-value floor
regardless of budget — they sit at p ≈ 0, and effect size is what separates them,
which is already the ranking used.

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
