# Cell Ontology Labeling Guide for Xenium Brain/Glioblastoma Review

Last updated: 2026-06-27

Use this guide when completing `expert_cell_labels.csv` for the healthy brain and glioblastoma Xenium datasets. The goal is to keep first-pass labels broad, auditable, and compatible with reference data. Disease states and tumor programs should be captured as secondary annotations or notes, not forced into Cell Ontology cell-type labels.

## Labeling Rule

Required columns for the agent:

```csv
cell_id,expert_label,confidence,notes
```

Recommended extended columns for expert review and benchmarking:

```csv
cell_id,expert_label,cl_id,secondary_state,confidence,notes
```

- `expert_label` should use the canonical Cell Ontology-style cell type.
- `cl_id` should store the Cell Ontology identifier where available.
- `secondary_state` can store study-specific states such as `glioblastoma_like`, `cycling`, `hypoxic`, `reactive`, `infiltrating`, `perivascular`, or `uncertain`.
- `notes` should preserve marker evidence, disagreement, or reviewer uncertainty.

## Recommended First-Pass Labels

| Use In `expert_label` | CL ID | Use When | Notes |
| --- | --- | --- | --- |
| `astrocyte` | `CL:0000127` | GFAP/AQP4/SLC1A3/AQP4-like glial profile. | Good broad label for astrocytic/reactive astrocytic cells. Put `reactive` in `secondary_state` if needed. |
| `oligodendrocyte` | `CL:0000128` | MBP/MOG/MOBP/PLP1/CLDN11-like myelinating profile. | Common in healthy brain and tumor-adjacent brain. |
| `microglial cell` | `CL:0000129` | P2RY12/CX3CR1/TMEM119/AIF1-like resident myeloid profile. | If macrophage vs microglia is unclear, use `myeloid cell` or reviewer note. |
| `neuron` | `CL:0000540` | SNAP25/SYT1/RBFOX3/neuronal marker profile. | Use broad neuron label unless subtype confidence is strong. |
| `oligodendrocyte precursor cell` | `CL:0002453` | PDGFRA/CSPG4/VCAN-like OPC profile. | Important for glioma-like OPC programs; keep tumor state separate. |
| `endothelial cell` | `CL:0000115` | PECAM1/VWF/KDR/CLDN5 vascular profile. | Use for blood-vessel lining cells. |
| `pericyte` | `CL:0000669` | RGS5/PDGFRB/CSPG4/ACTA2 vascular mural profile. | If ACTA2-high and mural identity is unclear, note uncertainty. |
| `fibroblast` | `CL:0000057` | COL1A1/DCN/LUM-like stromal profile. | Brain datasets may have vascular/leptomeningeal stromal cells; note context. |
| `macrophage` | `CL:0000235` | CD68/LYZ/APOE/C1QA-like infiltrating myeloid profile. | Use when not clearly resident microglia. |
| `T cell` | `CL:0000084` | CD3D/CD3E/TRAC-like T lineage. | Use CD4/CD8 subtypes only when markers are clear. |
| `CD4-positive, alpha-beta T cell` | `CL:0000624` | CD3D/CD3E plus CD4 support. | Optional more specific label. |
| `CD8-positive, alpha-beta T cell` | `CL:0000625` | CD3D/CD3E plus CD8A/CD8B support. | Optional more specific label. |
| `B cell` | `CL:0000236` | MS4A1/CD79A/CD79B-like B lineage. | Use broad label unless plasma state is clear. |
| `plasma cell` | `CL:0000786` | MZB1/JCHAIN/IGH high antibody-secreting profile. | Optional immune subtype. |
| `natural killer cell` | `CL:0000623` | NKG7/GNLY/KLRD1-like NK profile. | Use only when distinguishable from T/NK aggregate labels. |
| `dendritic cell` | `CL:0000451` | FCER1A/CLEC10A/CD1C or related DC profile. | Rare in many brain panels; use if marker-supported. |
| `epithelial cell` | `CL:0000066` | EPCAM/KRT marker profile. | In brain/glioblastoma, review carefully; may indicate contamination, tumor-like epithelial marker expression, or panel artifact. |
| `neoplastic cell` | `CL:0001064` | Expert identifies malignant/tumor cell identity. | Prefer `neoplastic cell` plus `secondary_state` such as `glioblastoma_like`, `cycling`, or `hypoxic`. |
| `unknown` / `unresolved` | no CL ID | Ambiguous or insufficient marker evidence. | Better than forcing a false biological label. |

## Local Astrocyte Term

The OLS JSON supplied for astrocyte is stored at:

```text
data/cell_ontology_terms/CL_0000127_astrocyte.json
```

It can be used to create a review-only astrocyte prefill table:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/write_astrocyte_label_suggestions.py --max-records 2500
```

For the current glioblastoma Xenium panel, only `AQP4`, `EGFR`, and `CD68` are available from the broader astrocyte evidence family. Key ontology markers such as `GFAP`, `GLUT1/SLC2A1`, `MBP`, and `NGFR` are not measured in this panel, so generated astrocyte suggestions must remain low-confidence review support until expert-confirmed.

## Region Labels

`cell_regions.csv` is not a Cell Ontology file. Use human-readable tissue/ROI labels:

- `tumor_core`
- `infiltrative_margin`
- `reactive_glia_rich`
- `immune_rich`
- `vascular_perivascular`
- `necrotic_hypoxic`
- `white_matter`
- `gray_matter`
- `normal_appearing_brain`
- `artifact_or_low_quality`

Required columns:

```csv
cell_id,region,region_confidence,notes
```

## Links

- Cell Ontology in OLS: https://www.ebi.ac.uk/ols4/search?q=label&ontology=cl
- Cell Ontology home: https://obophenotype.github.io/cell-ontology/
- Astrocyte term: http://purl.obolibrary.org/obo/CL_0000127
- Oligodendrocyte term: http://purl.obolibrary.org/obo/CL_0000128
- Microglial cell term: http://purl.obolibrary.org/obo/CL_0000129
- Neuron term: http://purl.obolibrary.org/obo/CL_0000540
- Oligodendrocyte precursor cell term: http://purl.obolibrary.org/obo/CL_0002453
- Endothelial cell term: http://purl.obolibrary.org/obo/CL_0000115
- Pericyte term: http://purl.obolibrary.org/obo/CL_0000669
- Fibroblast term: http://purl.obolibrary.org/obo/CL_0000057
- Macrophage term: http://purl.obolibrary.org/obo/CL_0000235
- T cell term: http://purl.obolibrary.org/obo/CL_0000084
- CD4-positive alpha-beta T cell term: http://purl.obolibrary.org/obo/CL_0000624
- CD8-positive alpha-beta T cell term: http://purl.obolibrary.org/obo/CL_0000625
- B cell term: http://purl.obolibrary.org/obo/CL_0000236
- Plasma cell term: http://purl.obolibrary.org/obo/CL_0000786
- Natural killer cell term: http://purl.obolibrary.org/obo/CL_0000623
- Dendritic cell term: http://purl.obolibrary.org/obo/CL_0000451
- Epithelial cell term: http://purl.obolibrary.org/obo/CL_0000066
- Neoplastic cell term: http://purl.obolibrary.org/obo/CL_0001064
- Uberon anatomy ontology: https://obophenotype.github.io/uberon/
- 10x Xenium Explorer: https://www.10xgenomics.com/support/software/xenium-explorer/latest
- QuPath: https://qupath.github.io/
- napari: https://napari.org/stable/
