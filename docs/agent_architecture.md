# How the SpatialMind Agent Works

This is the single end-to-end explanation of the agent: what each layer does, what
runs when, and where the gates sit. The README is the command reference;
`development_tracking.md` is the historical work log. Start here.

Last verified: 2026-08-12. Unit tests 106/106; legacy eval 15/15; MVP eval 11/11; real Scanpy/Squidpy backend checks passed; import-linter 3/3.

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

## Stage 5: Typed plan validation

`build_xenium_mvp_plan()` produces a typed tool sequence with declared
dependencies; `validate_tool_plan()` checks it. Plan validation checks *structure*
(ordering, dependencies, tools exist) against the full input set — input
*availability* is the gate's job alone. That separation is why a blocked run still
reports a valid plan instead of duplicating the gate's blockers as fake plan errors.

## Stage 6: The seven MVP tools

| Tool | Backend | What it does |
| --- | --- | --- |
| `qc_and_cluster` | Scanpy | Per-cell QC, then normalize → log1p → PCA → neighbours → Leiden on **expression**. `cluster_on="spatial"` opts into spatial-domain clustering. |
| `annotation` | — | Summarises applied expert labels |
| `marker_detection` | Scanpy | **One-vs-rest** markers for every cell type by default; explicit `group1`+`group2` gives a pairwise contrast |
| `spatial_variable_genes` | Squidpy | Moran's I over a spatial kNN graph with seeded permutations and FDR correction; Scanpy HVG is an explicit development fallback only |
| `region_summary` | — | Cell-type composition and feature means per user region |
| `cell_neighborhood_enrichment` | Squidpy | Permutation z-scores for cell-type adjacency |
| `feature_overlay` | — | Single-feature spatial values, with panel-absence guarding |

`qc_and_cluster`, cluster-group marker detection, `spatial_variable_genes`, and cluster-group neighborhood enrichment can run in the descriptive lane before expert labels exist. Annotation, reviewed-region summaries, and cell-type relationship claims remain validation-gated.

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

## The invariant

Every layer is built so that missing evidence produces an explicit refusal rather
than a confident guess. When you change this agent, preserve that: a tool must never
report work it did not do.
