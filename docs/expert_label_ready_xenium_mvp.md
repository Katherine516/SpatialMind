# Expert-Label-Ready Xenium MVP

## What Was Built

SpatialMind now has the first expert-label-ready layer for Xenium workflows:

- `SpotRecord.cell_id` is preserved for Xenium, H5AD, and table ingestion.
- External label tables can override loaded labels by matching Xenium `cell_id`.
- Label application writes structured metadata into `dataset.metadata["label_readiness"]`.
- Breast marker-rule labels are now an explicit weak-label fallback, not an implicit expert annotation.
- `scripts/prepare_xenium_expert_mvp.py` inventories local Xenium folders and creates label templates.
- Label templates include review evidence: spatial coordinates, 10x graph cluster, top loaded features, and selected marker values.

## Local Data Inventory

The full-environment inventory scanned four local Xenium datasets:

| Dataset | Matrix | Morphology | Boundaries | 10x clusters | Expert labels |
| --- | --- | --- | --- | --- | --- |
| Breast biomarkers | yes | yes | yes | yes | missing |
| Human brain glioblastoma | yes | yes | yes | yes | missing |
| Human healthy brain | yes | yes | yes | yes | missing |
| Human lymph node | yes | yes | yes | yes | missing |

Generated report:

```text
outputs/xenium_expert_mvp_readiness/xenium_expert_mvp_readiness.md
```

Generated templates:

```text
outputs/xenium_expert_mvp_readiness/*/expert_label_template.csv
```

## What We Need Next

We need biological labels keyed by Xenium `cell_id`. Either of these is acceptable:

- expert-reviewed labels filled into the generated template;
- reference-transferred labels from a matched scRNA/scATAC reference;
- a curated public label table with provenance and confidence scores.

Minimum file format:

```csv
cell_id,expert_label,confidence,notes
aaaafije-1,CD8+ T cell,0.95,expert review
```

Recommended review format:

```csv
cell_id,expert_label,cl_id,secondary_state,confidence,notes
aaaafije-1,microglial cell,CL:0000129,reactive,0.90,expert review
```

Use the broad Cell Ontology-compatible vocabulary in `docs/cell_ontology_labeling_guide.md`. For glioblastoma review, keep disease programs such as `glioblastoma_like`, `cycling`, `hypoxic`, `reactive`, or `infiltrating` in `secondary_state` or `notes`.

Place the completed file inside the matching Xenium output directory as `expert_cell_labels.csv` or `cell_labels.csv`, then rerun:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/prepare_xenium_expert_mvp.py
```

The generated template columns are:

```text
cell_id,x,y,current_label,graph_cluster,top_features,marker_evidence,expert_label,confidence,notes
```

Only `expert_label` needs to be filled to start; `cl_id`, `secondary_state`, `confidence`, and `notes` make the labels more useful for later training and benchmark construction.

## Current Limitation

10x analysis clusters and marker-rule labels are useful review evidence, but they are not biological ground truth. SpatialMind should not use them as supervised training labels unless a domain expert approves or corrects them.
