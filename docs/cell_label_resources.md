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

Last checked: 5 Sep 2026, against the glioblastoma section.

## Have

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

### 1. A human reference carrying a malignant class — blocking for tumour work

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

Roughly **1,600 labelled cells** at a 2,000-cell run. This is measured, not
estimated: a 500-cell run clears the 70% coverage gate and then fails with
`blocked_analysis_backend` because a class has too few cells for marker
statistics.

No reference, model or heuristic replaces this. Transferred labels carry
`review_status=needs_expert_review`, and the gate accepts only
`expert_cell_labels.csv`, which a human writes. That refusal is the feature.

**Unblocks:** everything gated — annotation, region summaries, cell-type
neighbourhood enrichment, and any scored biological claim.

### 3. Region delineation

`cell_regions.csv`, at least two regions, 70% coverage. Tumour core versus
infiltrating edge versus normal cortex is a judgement about *this* section; no
atlas contains it.

**Unblocks:** region summaries and every region-stratified claim.

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
