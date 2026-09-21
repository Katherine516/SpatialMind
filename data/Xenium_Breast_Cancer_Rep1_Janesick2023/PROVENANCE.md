# Xenium FFPE Human Breast Cancer, Replicate 1 — with published expert labels

The first dataset in this workspace that arrives **already expertly labelled**.
Every other section here is blocked on a reviewer; this one is blocked only on
regions.

## What is here, and where each piece came from

| File | Source | Size |
| --- | --- | --- |
| `experiment.xenium`, `metrics_summary.csv`, `gene_panel.json` | 10x Genomics | 156 KB |
| `cells.csv.gz` | 10x Genomics | 7.9 MB |
| `cell_feature_matrix.h5` | 10x Genomics | 12.1 MB |
| `cell_boundaries.csv.gz` | 10x Genomics | 21.4 MB |
| `morphology_mip.ome.tif` | 10x Genomics | 628 MB |
| `Cell_Barcode_Type_Matrices.xlsx` | Zenodo 10076046 | 9.4 MB |
| `expert_cell_labels.csv` | derived from the workbook | 14 MB |

**Instrument data** — 10x Genomics public dataset
`Xenium_FFPE_Human_Breast_Cancer_Rep1`, Xenium Analyzer 1.0.1, December 2022:

```
https://cf.10xgenomics.com/samples/xenium/1.0.1/Xenium_FFPE_Human_Breast_Cancer_Rep1/
```

Seven files rather than the 9.86 GB `_outs.zip`. The agent reads about 6 MB of a
bundle; the rest of that archive is transcript tables and a full-resolution
morphology stack it catalogues for provenance and never parses. `morphology_mip`
is taken instead of `morphology.ome.tif` because the viewer reads a downsampled
pyramid level anyway.

**Cell type annotations** — Janesick et al. 2023, *High resolution mapping of the
breast cancer tumor microenvironment using integrated single cell, spatial and in
situ analysis of FFPE tissue*, Nature Communications 14:8353,
[doi:10.1038/s41467-023-43458-x](https://doi.org/10.1038/s41467-023-43458-x).
Annotations from [Zenodo record 10076046](https://zenodo.org/records/10076046),
**CC BY 4.0** — redistributable with attribution, which the label file carries in
its own `reviewer_id` and `source` columns.

## Why this one, and not a brain section

The two brain sections here are the project's subject, and neither has published
per-cell labels. 10x's brain demo bundles ship unsupervised clusters only —
`analysis.tar.gz` contains `gene_expression_graphclust` and nine k-means
solutions, and no cell type anywhere. The cell types shown in 10x's own brain
write-ups were produced by label transfer and were not released per cell.

This section is the exception: named authors annotated it, the paper was peer
reviewed, and the per-cell table was deposited under a licence that permits
reuse. That is what makes it usable as expert truth rather than as another
candidate needing review.

## The join, verified

```
bundle cells        : 167,780
annotation rows     : 167,780
unmatched to bundle : 0
```

Exact, because both come from the same Xenium Analyzer 1.0.1 run: `cells.csv.gz`
from 10x is byte-identical in size to `xe1_cells.csv.gz` on Zenodo. Cell ids are
integers (`1`, `2`, `3`…), the pre-2023 Xenium format — a bundle reprocessed
with a later Analyzer version uses `aaaafije-1` style ids and **will not join**.
If a future re-release is substituted here, the importer's `unmatched to bundle`
count is what catches it.

## What was dropped, and why

8,554 cells carry the authors' own `Unlabeled` class. They are not written to
`expert_cell_labels.csv`. `Unlabeled` is an explicit abstention — the authors
declining to call a cell — and writing it into `expert_label` would convert a
refusal into a class name, which is the same mistake as letting a loader's
marker guess count as review.

Resulting coverage: **159,226 of 167,780 cells, 94.9%**, across **19 cell types**
(Stromal, Invasive_Tumor, DCIS_1/2, Macrophages_1/2, Endothelial, CD4+/CD8+ T,
Myoepi_ACTA2+/KRT15+, B_Cells, Prolif_Invasive_Tumor, Perivascular-Like,
IRF7+/LAMP3+ DCs, Mast_Cells, and two hybrid classes).

## Gate status

```
ASSETS  cell table  feature matrix  morphology  boundaries   all present
GATE    validated_ready
        label coverage   0.949    19 reviewed classes
        region coverage  0.977    19 regions
```

The gate is open. The two inputs that opened it are not of the same kind, and the
report says so on every run.

`expert_cell_labels.csv` is expert truth — named authors, peer reviewed,
deposited under a licence.

`cell_regions.csv` is **not a pathologist's call**. It was made by running the
descriptive lane, accepting its 19 spatial domains, and naming each from its
reviewed cell composition. Its `reviewer_id` column carries that sentence
verbatim on all 163,920 rows, and the pilot report prints it under *Label and
Region Readiness*: the gate counts a reviewed region table and has no way to read
who wrote it, so the disclosure has to be carried rather than enforced.

What follows from it:

- **Region composition is partly circular here.** A domain named `tumor_rich`
  because it is tumour-rich, then reported as tumour-rich, is a restatement.
- **Within-region neighbourhood enrichment is not.** Composition decided which
  cells fall in which domain; it did not decide which cell types sit adjacent.

Real regions cannot be downloaded from anywhere. Replacing this table with a
pathologist's — the same 19 domains, named from morphology — is the single step
that turns the region-level results from illustration into evidence.

### The packet for doing that

```bash
python scripts/build_region_review_packet.py \
    --data data/Xenium_Breast_Cancer_Rep1_Janesick2023 \
    --out outputs/region_review
```

Renders all 19 domains on this section's own DAPI morphology — each with its
cells marked, a scale bar, and a locator showing where it sits — and writes
`region_naming_sheet.csv` to name them on. Fill the sheet, then:

```bash
python scripts/apply_region_naming.py \
    --data data/Xenium_Breast_Cancer_Rep1_Janesick2023 \
    --sheet outputs/region_review/region_naming_sheet.csv \
    --reviewer "Dr Name, DAPI morphology review, <date>"
```

**The packet is blinded by default.** Cell composition is not shown, because
these domains were named from their composition in the first place — showing it
and asking for a name would reproduce the circularity the exercise removes.
`--unblind` is for a second pass, after names are written, and the page says so.

Two limits it states on its own front page: Xenium images DAPI rather than H&E,
so a call needing cytoplasm or IHC is one this image cannot support (the sheet
has an `uncertain` column); and the boundaries are the algorithm's — they can be
accepted, renamed or merged here, but redrawing them means Review Studio.

Once applied, the `reviewer_id` stops reading `composition-derived`, and the
report's circularity caveat stops firing — which is the point, and is asserted
by a test rather than left to be noticed.

## Reproducing this

```bash
sh scripts/fetch_janesick_breast.sh          # the seven 10x files + the Zenodo workbook
python scripts/import_published_labels.py \
    --workbook data/Xenium_Breast_Cancer_Rep1_Janesick2023/Cell_Barcode_Type_Matrices.xlsx \
    --sheet "Xenium R1 Fig1-5 (supervised)" \
    --bundle data/Xenium_Breast_Cancer_Rep1_Janesick2023
```

`--dry-run` reports the join and writes nothing.

Replicate 2 is a consecutive section from the same block, with its own supervised
sheet (`Xenium R2 Fig1-5 (supervised)`, 118,752 cells) and its own outs bundle at
the same 10x path. Two sections of one tumour are still one donor: they do not
satisfy `assess_condition_replication`, which needs independent donors.
