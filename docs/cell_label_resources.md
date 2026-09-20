# Resources needed for expert cell labels

Every local Xenium dataset is blocked on the same two files:

```text
<xenium_outs>/expert_cell_labels.csv    cell_id,expert_label,confidence,notes
<xenium_outs>/cell_regions.csv          cell_id,region,region_confidence,notes
```

[`getting_cell_labels.md`](getting_cell_labels.md) is the procedure. This page is
the **inventory**: what the workspace already has, what is genuinely missing, and
what each missing piece unblocks. The Studio shows the same list live on its
Readiness screen (`GET /api/resources`), computed from what is on disk.

Last checked: 19 Sep 2026. Two changes since: a human malignant reference
(14 Sep) and **the first expertly labelled section in the workspace** (18 Sep,
below).

## Have

### A section that arrives already labelled — ACQUIRED 18 Sep 2026

`data/Xenium_Breast_Cancer_Rep1_Janesick2023/` — Xenium FFPE human breast cancer
replicate 1, with **159,226 expert-labelled cells across 19 cell types** from
Janesick et al. 2023 (Nat Commun 14:8353), Zenodo 10076046, CC BY 4.0. See that
folder's `PROVENANCE.md`.

This is the only local section whose labels did not have to be produced. It is
the answer to a question worth stating plainly: **per-cell expert labels are
almost never downloadable.** They exist for a section when named authors
annotated it, published, and deposited the table — which is rare, and is why
every other dataset here is blocked on a reviewer.

```text
GATE  validated_ready
      label coverage 0.949, 19 reviewed classes
      region coverage 0.977, 19 regions
      all four assets present
```

The gate is open, and the two halves of that are not equally strong.

**Labels** are expert truth: named authors, peer reviewed, deposited under CC BY.

**Regions** are not. `cell_regions.csv` here was written by accepting the
descriptive lane's spatial domains and naming each one from its reviewed cell
composition. The table says so in its own `reviewer_id` --
`composition-derived, not a pathologist call` -- and the report now prints that
line under *Label and Region Readiness*, because the gate counts a reviewed
region table and cannot read who wrote it.

Two consequences a reader needs:

- A region summary over these regions is **partly circular**. `tumor_rich` is
  tumour-rich by construction; that it is, is not a finding.
- Neighbourhood results *within* a region do not inherit the circularity. Cell
  composition set which cells fall in which domain; it did not set which pairs
  sit adjacent, so a within-region enrichment z-score is still a measurement.

Real regions still cannot be downloaded from anywhere: tumour core versus DCIS
versus stroma is a judgement about this section. Replacing the derived table with
a pathologist's on the same 19 domains is what turns the region-level results
from illustration into evidence.

What this section unblocks that the brain sections cannot: an end-to-end
validated run on **real expert labels** rather than transferred candidates, which
is the only way to see what the claim ledger and reliability scores do when the
annotation is genuinely trustworthy.

Fetch and import:

```bash
sh scripts/fetch_janesick_breast.sh          # ~650 MB, seven 10x files + the workbook
python scripts/import_published_labels.py \
    --workbook data/Xenium_Breast_Cancer_Rep1_Janesick2023/Cell_Barcode_Type_Matrices.xlsx \
    --sheet "Xenium R1 Fig1-5 (supervised)" \
    --bundle data/Xenium_Breast_Cancer_Rep1_Janesick2023
```

#### What was checked before trusting it

The 10x brain demo bundles were checked first, since brain is this project's
subject. `analysis.tar.gz` contains `gene_expression_graphclust` and nine k-means
solutions and **no cell type anywhere** — the cell types in 10x's brain write-ups
came from label transfer and were not released per cell. No published per-cell
annotation for a human brain Xenium section was found.

The join was verified rather than assumed: 167,780 annotation rows against
167,780 bundle cells, **0 unmatched**. Both come from Xenium Analyzer 1.0.1, and
`cells.csv.gz` from 10x is byte-identical in size to `xe1_cells.csv.gz` on
Zenodo. The ids are integers — a bundle reprocessed with a later Analyzer uses
`aaaafije-1` style ids and will not join at all. The importer's
`unmatched to bundle` count is the check that catches that.

8,554 cells carrying the authors' own `Unlabeled` class are dropped rather than
written through: an explicit abstention must not become a class name.

### Reference atlases — all normal lineages covered

Eight `.h5ad` references sit under `data/`, seven of them Human Brain Cell Atlas
superclusters:

| Reference | Size | Classes it can name |
| --- | --- | --- |
| `Supercluster_Astrocyte` | 0.8 GB | astrocyte |
| `Supercluster_Microglia` | 0.3 GB | microglial cell |
| `Supercluster_Oligodendrocyte` | 2.3 GB | oligodendrocyte |
| `Supercluster_Oligodendrocyte_precursor` | 0.6 GB | OPC |
| `Supercluster_Vascular` | 0.05 GB | endothelial cell, pericyte, VSMC |
| `Supercluster_Splatter` | 3.4 GB | neuron, SST CHODL GABAergic interneuron |
| `Supercluster_Upper-layer intratelencephalic` | 6.1 GB | IT-projecting glutamatergic cortical neuron |

The preflight over all seven against the glioblastoma section reports **11
combined cell classes** and:

> Every lineage confidently detected in the target has a matching reference class.

This is a change worth recording. `getting_cell_labels.md` documents an earlier
run where three superclusters gave mean confidence **0.8845** while roughly
**40%** of cells belonged to lineages the reference could not name. That gap is
closed by the four references added since — astrocyte, microglia, OPC and
vascular are exactly the lineages that were missing.

Reproduce it:

```bash
.venv/bin/python scripts/build_candidate_cell_labels.py \
  --data "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs" \
  --inspect --reference data/Supercluster_*.h5ad
```

### Controlled vocabulary

`data/cell_ontology_terms/` plus
[`cell_ontology_labeling_guide.md`](cell_ontology_labeling_guide.md) — astrocyte
(CL:0000127), oligodendrocyte (CL:0000128), microglial cell (CL:0000129), neuron
(CL:0000540), endothelial cell (CL:0000115), neoplastic cell (CL:0001064).

### Review tooling

Review Studio in the app (click a cluster, apply a label; drag a rectangle, name
a region), `scripts/plan_expert_review.py` for sizing the packet, and
`scripts/build_candidate_cell_labels.py` for Route B. Xenium Explorer, QuPath and
napari all export CSVs the loader ingests unchanged.

## Missing

### 1. A human reference carrying a malignant class — OBTAINED 14 Sep 2026

`data/GBmap_Core_human_glioblastoma.h5ad` — Core GBmap, 338,564 human cells,
17 cell types including **malignant cell**, 7.6 GB, from
[CELLxGENE](https://datasets.cellxgene.cziscience.com/861acfd8-25f0-418b-a445-aa96da232827.h5ad).

The preflight now passes on the glioblastoma section:

```text
REFERENCE data/GBmap_Core_human_glioblastoma.h5ad
         organism=Homo sapiens  cells=338564  classes=17  panel_overlap=316
LINEAGE COVERAGE
         Every lineage confidently detected in the target has a matching reference class.
USABLE: 17 combined cell classes.
```

One reference covering every lineage the section carries *and* the malignant
class, replacing what previously needed seven superclusters and still could not
name a tumour cell.

**Two defects had to be fixed before it was usable**, both silent:

- anndata's backed mode covers `X` only. This file's `layers` total 37 GB
  uncompressed, so a backed open was killed before sampling a single cell — and
  `_open_h5ad` then fell back to a full in-memory read, which is worse.
  `read_h5ad_subsample` reads the wanted rows through h5py and never touches
  `layers` or `raw`: 2,000 cells in 7.8 s at 0.57 GB peak.
- CELLxGENE keys `var` by Ensembl ID and puts symbols in `feature_name`. A
  Xenium panel is symbols, so reading the index gives an overlap of **zero** —
  not an error that announces itself, but a confident answer computed from
  nothing. Reading `feature_name` gives 296 of 339 panel genes.

#### A caveat the reviewer needs before touching this file

Candidate labels are **highly sensitive to how the reference is sampled**, and
the effect is large enough to change the headline finding:

| Reference sample | Malignant share of reference | Target cells called malignant |
| --- | --- | --- |
| proportional, 2,000 cells | 38% | **955** of 2,497 |
| stratified by class, 6,000 cells | 6.5% | **71** of 2,497 |

A 13.5x swing from the sampling choice alone, with no change to the target data.
Both runs used the same reference file and the same algorithm.

Neither number is the truth. A proportional draw preserves the atlas's own prior
— in a GBM atlas a great many cells really are malignant — and lets the majority
class dominate a neighbour vote. A stratified draw gives every class equal
voting weight and discards that prior entirely. Stratification is used here
because a class absent from the sample can never be assigned at all, which is
the worse failure, but it is a trade and not a correction.

**What this means in practice:** treat the malignant count as a starting point
for review, not as a measurement. It is exactly the kind of number that looks
like a result and is not one, which is why the gate does not accept this file.

#### The original entry, kept for the record

### 1b. What the mouse reference could not do (superseded)

The only tumour reference present, `glioblastoma_brain.h5ad`, is **Mus musculus**.
The preflight refuses it twice over:

```text
BLOCKED: species mismatch (target=human, reference=mouse)
BLOCKED: reference cannot name 1 lineage(s) present in this tissue (oligodendrocyte)
```

So candidate labels can currently name astrocyte, oligodendrocyte and microglia,
but never **neoplastic cell** — which is the central call in a glioblastoma
section. A normal-brain atlas will label a malignant cell as its nearest normal
neighbour, at high confidence, with no signal that anything is wrong.

**What to get:** a human glioma/GBM scRNA-seq reference with an explicit
malignant or neoplastic class, panel overlap above ~120 genes with the 313-gene
Xenium brain panel. cellxgene and the Human Tumor Atlas Network are the usual
sources. Mouse cannot substitute.

**Unblocks:** candidate labels that distinguish tumour from reactive glia, which
is most of the review effort in this section.

### 2. Expert reviewer time — the irreducible one

Irreducible, and far smaller than "1,600 cells" suggested. That figure sized the
review in **cells**, which is correct arithmetic in the wrong unit: nobody
labels cells one at a time, and the Review Studio's gesture is a cluster click.
Sized in **decisions**, on the healthy brain section:

```text
LABELS    4 decisions reach 73.5% coverage   (9 Leiden clusters, all with markers)
REGIONS   6 decisions reach 75.4% coverage   (12 proposed domains)
TOTAL    10 decisions -> gate: validated_ready
```

That last line is measured, not projected: the gate was run against those ten
decisions and returned `validated_ready`, 4 reviewed classes and 6 reviewed
regions. `scripts/size_expert_review.py --all` sizes every section the same way.

All four blocked sections, sized the same way:

```text
                    cells    clusters  labels  regions  total  markers separate?
healthy brain      24,406       9         4       6      10    yes
glioblastoma       40,786      11         5       6      11    two pairs do not
lymph node        372,099       8         2       9      11    yes, but 1 pair
breast S1         209,467       9         5      11      16    one pair does not
```

The totals are close and the jobs are not. The lymph node has the cheapest label
side of all — T cells and B cells are 70% of the section, so **two** decisions
clear the gate — and that is also its problem: two classes give exactly one
cell-type pair to test, which is the entire neighbourhood analysis. The plan says
so rather than reporting the cheapness alone.

The glioblastoma section costs about the same and is not the same job:

```text
LABELS    5 decisions reach 71.6% coverage   (11 clusters, all with markers)
REGIONS   6 decisions reach 72.7% coverage   (13 proposed domains)
TOTAL    11 decisions -> gate: validated_ready
```

Two of those five label decisions are on clusters markers cannot separate —
0 and 1 share C3/GPR34/RNASET2/VSIG4 (microglia against tumour-associated
macrophage), 6 and 7 share ENC1/NPTX1/NRGN/SLC17A7. The plan flags both.

And it flags what it *cannot* size. Cluster 5 — PTPRZ1, BCAN, VCAN, OLIG2,
PDGFRA — reads as OPC and reads equally as OPC-like tumour; cluster 8 carries
astrocyte markers plus SERPINA3. Neither is a within-section confusability
problem, so the overlap check is silent on them: a malignant cell mimicking a
lineage carries that lineage's markers. Every normal-lineage call in a tumour
section is provisional in a way the same call on the healthy section is not, and
resolving it needs CNV (`cnv_inference` is a scaffold), a malignant-carrying
reference (GBmap Core is here, and swings 13.5× on sampling), or a pathologist.

The catch is in the same number. Ten decisions is the arithmetic **floor**, not
an estimate of careful work: naming a cluster asserts that all 4,763 of its
cells are that class, which is wrong at the margins of every cluster. The run
records `review_decisions: 4` against 17,909 covered cells and every claim
carries "coverage is not review depth", so the shortcut is visible rather than
hidden. A reviewer who splits the mixed clusters and refuses the ambiguous ones
does more than ten things, and should.

No reference, model or heuristic replaces the judgement itself. Transferred
labels carry `review_status=needs_expert_review`, and the gate accepts only
`expert_cell_labels.csv`, which a human writes. That refusal is the feature.

**Unblocks:** everything gated — annotation, region summaries, cell-type
neighbourhood enrichment, and any scored biological claim.

### 2b. Checked and rejected: a pathologist region annotation that does not fit

[Zenodo 15411357](https://zenodo.org/records/15411357), *Xenium ILC / IDC
pathologist annotation breast cancer* (Bhuva & Kiessling, CC BY 4.0), is exactly
the thing this page says cannot be downloaded: per-cell **pathologist** domains
-- Invasive Tumor, DCIS, Stroma, Normal ducts, Blood vessels, Immune cells,
Adipose tissue -- over a public 10x Xenium breast section, from
[Bhuva et al. 2024](https://genomebiology.biomedcentral.com/articles/10.1186/s13059-024-03241-7).

**It is not this workspace's section.** It was checked and rejected:

```text
idc.csv  127,575 rows   unmatched to bundle: 0     <- looks perfect
ilc.csv  150,200 rows   unmatched to bundle: 0     <- looks perfect
```

Both join at 100% and neither belongs here. These bundles number cells
`1, 2, 3, ...`, so **any** annotation of a section with at most 167,780 cells
matches every row. Cross-tabulated against the section's own published cell
types, every cell type maps to the same domain distribution -- `Stromal` cells
land in `Invasive Tumor` 69% of the time, which is the marginal, not agreement:

```text
published cell types x foreign IDC domains    Cramer's V = 0.048    independent
published cell types x foreign ILC domains    Cramer's V = 0.054    independent
published cell types x this section's regions Cramer's V = 0.223    the real pairing
```

`scripts/import_published_labels.py` now runs this check itself and refuses,
because `unmatched to bundle: 0` was the only provenance test it had and on an
integer-id bundle that test is vacuous.

Worth revisiting if the matching outs bundle is identified: it is a real
pathologist's region call, which is the one input no atlas supplies.

### 3. Region delineation

`cell_regions.csv`, at least two regions, 70% coverage. Tumour core versus
infiltrating edge versus normal cortex is a judgement about *this* section; no
atlas contains it.

**Unblocks:** region summaries and every region-stratified claim.

Still outstanding on all four unlabelled sections. On the Janesick section it is
satisfied by a composition-derived table that is honest about being one (above);
a pathologist naming the same 19 domains is a short session and would remove the
only circularity in that section's results.

### 4. Lymphoid reference — low priority

Three T/NK cells were confidently detected in the glioblastoma section. Below the
threshold where a reference class would change anything, and far below what
marker statistics need. Worth adding only if immune infiltration is a question
being asked.

## What this costs in practice

| Resource | Cost | Blocking? |
| --- | --- | --- |
| Human GBM reference | download, ~1-5 GB | yes, for tumour identity |
| Reviewer time | ~1,600 cells, one session | yes |
| Region drawing | same session | yes |
| Normal-lineage references | already present | no |
| Ontology vocabulary | already present | no |

Two of the three blockers are a person's afternoon. The third is a download.
