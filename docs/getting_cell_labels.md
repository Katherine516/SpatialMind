# Getting Expert Cell Labels and Regions

All four local Xenium datasets are blocked on exactly two files per dataset:

```text
<xenium_outs>/expert_cell_labels.csv    cell_id,expert_label,confidence,notes
<xenium_outs>/cell_regions.csv          cell_id,region,region_confidence,notes
```

Supplying them for **one** dataset unblocks the entire validated path: expression
clustering, one-vs-rest markers, region summaries, neighbourhood enrichment, the
robustness sweep, spatial relationships, and scored claims.

The agent cannot produce these files itself. Cell identity and ROI boundaries are
expert judgements; a tool that invented them would defeat the gate that makes the
rest of the system trustworthy. What the agent *can* do is make the review as small
and well-informed as possible.

## Route A — expert annotation (authoritative)

1. Build the review packet and viewer:

   ```bash
   .venv/bin/python scripts/prepare_glioblastoma_review_packet.py --max-records 2500
   ```

2. Open `explorer_lite_viewer.html` from the pilot output. Enable **Morphology** and
   **Segmentation** to see tissue and cell outlines, colour by 10x cluster, assign
   labels/regions, and export both CSVs.

   Use Xenium Explorer, QuPath, or napari instead when you need deep-zoom navigation
   or pathology-grade ROI drawing; the agent ingests their exported CSVs the same way.

3. Save the completed files into the Xenium output folder and re-run the pilot.

**Scope tip.** You do not need to label all 40,887 cells. The gate needs ≥70%
coverage *of the loaded sample*, ≥2 cell classes, and ≥2 regions. Running with
`--max-records 500` means ~350 labelled cells clears the gate for a first real pass.

Use the broad Cell Ontology vocabulary in
[`cell_ontology_labeling_guide.md`](cell_ontology_labeling_guide.md) — `astrocyte`
(CL:0000127), `oligodendrocyte` (CL:0000128), `microglial cell` (CL:0000129),
`neuron` (CL:0000540), `endothelial cell` (CL:0000115), `neoplastic cell`
(CL:0001064), and so on. Keep disease states such as `glioblastoma_like` or
`hypoxic` in a `secondary_state` column, not in `expert_label`.

## Route B — reference transfer, then review

Predict candidate labels from a labelled scRNA reference, then have an expert
correct them. Faster than labelling from scratch, and the confidence column tells
the reviewer where to look first.

```bash
.venv/bin/python scripts/build_candidate_cell_labels.py \
  --data "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs" \
  --out outputs/candidate_labels_glioblastoma \
  --reference /path/to/brain_reference.h5ad \
  --max-records 2500
```

This runs a distance-weighted KNN over shared features and writes
`expert_cell_labels_candidate.csv` with `candidate_label`, `confidence`,
`marker_evidence`, and `top_features` per cell, plus a summary JSON.

Reviewing it: sort by `confidence` ascending and check the low-confidence cells
first — the summary reports `low_confidence_cell_count` explicitly. Fill
`expert_label` and `reviewer_id`, then save as `expert_cell_labels.csv`.

Without `--reference`, the script falls back to the loader's marker-rule labels.
Those are weak heuristics for prioritising review only.

**The boundary.** Transferred labels are predictions, never expert truth. The output
carries `review_status=needs_expert_review` and the tool's caveats say so. The gate
only accepts `expert_cell_labels.csv`, which a human must write.

## Where to get a reference

| Resource | What it gives you | How to get it |
| --- | --- | --- |
| [CZ CELLxGENE Discover](https://cellxgene.cziscience.com/) | Curated human brain / GBM scRNA with cell-type labels | Filter tissue=brain (disease=glioblastoma for GBM), download `.h5ad` |
| [Allen Brain Map](https://portal.brain-map.org/) | Gold-standard healthy human cortex taxonomy | Direct download |
| [Ivy Glioblastoma Atlas](https://glioblastoma.alleninstitute.org/) | **ROI vocabulary**: tumour core, infiltrating margin, perinecrotic zone, hyperplastic vessels | Free browse; use for `cell_regions.csv` naming |
| GBmap (via CELLxGENE) | Integrated ~1M-cell GBM atlas | `.h5ad` |
| [Broad Single Cell Portal](https://singlecell.broadinstitute.org/) / [GEO](https://www.ncbi.nlm.nih.gov/geo/) | Additional brain/GBM references | Registration or accession |

A reference is usable when it has per-cell **cell-type labels** and a **gene
expression matrix** sharing enough genes with the Xenium panel. The Xenium brain
panel is ~250–540 targeted genes, so expect tens to a few hundred shared genes —
`--min-shared-features` defaults to 20.

Record licence, consent, and PHI status for any downloaded reference; the governance
manifest (`scripts/build_dataset_governance_manifest.py`) has fields for these.

## Checking your files before a full run

```bash
.venv/bin/python scripts/validate_xenium_label_intake.py \
  --data "<xenium_outs>" --out outputs/label_intake --max-records 2500
```

Reports coverage, class counts, and region counts, and tells you exactly which gate
condition still fails. When it returns `validated_ready`, run the pilot.

## Region labels

Regions are ROI/tissue-domain assignments, not cell types, and must come from a
human looking at tissue. `cell_regions_draft_for_review.csv` in the review packet
pre-fills a `draft_spatial_zone` (a 4×4 spatial grid) purely as a drawing aid — grid
bins are **not** biological regions and must be replaced with real ones such as
`tumor_core`, `infiltrative_margin`, `necrotic_hypoxic`, `white_matter`, or
`normal_appearing_brain`.
