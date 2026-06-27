# SpatialMind Real-Agent Acquisition and Operations Plan

Last updated: 2026-06-27

This document lists the remaining non-LLM requirements for promoting SpatialMind from a validated local pilot to a real spatial omics analysis agent. The local `data/` folder can support engineering validation, review packets, visualization QA, replay/hash verification, and governance templates. It cannot create expert biological truth by itself.

## 1. Expert Cell Labels

Required file per Xenium dataset:

```csv
cell_id,expert_label,confidence,notes
```

How to get it:

- Use the generated `expert_label_template.csv` in each review packet.
- Review cells by combining current loader labels, 10x graph clusters, marker evidence, and the review spatial map.
- Have a domain expert assign final labels, confidence, and notes.
- Save the completed file into the source Xenium folder as `expert_cell_labels.csv`.
- Use broad Cell Ontology-compatible labels for the first validated pilot. See `docs/cell_ontology_labeling_guide.md`.
- Recommended review columns are `cell_id,expert_label,cl_id,secondary_state,confidence,notes`; the pilot gate requires `cell_id,expert_label,confidence,notes`.

Minimum acceptance:

- At least 70% loaded-cell coverage.
- At least two reviewed biological cell classes.
- Confidence is strongly recommended, even if not strictly required.

## 2. User Tissue / ROI Regions

Required file per Xenium dataset:

```csv
cell_id,region,region_confidence,notes
```

How to get it:

- Use the generated `region_label_template.csv` in each review packet.
- Define regions such as `tumor_core`, `invasive_margin`, `stroma`, `immune_rich`, `cortex`, `white_matter`, or tissue-specific ROIs.
- Assign regions by expert review of spatial maps and morphology context.
- Save the completed file into the source Xenium folder as `cell_regions.csv`.

Minimum acceptance:

- At least 70% loaded-cell coverage.
- At least two reviewed tissue/ROI regions unless a single-region pilot is explicitly requested.

## 3. Biological Ground-Truth Benchmark Labels

How to get them:

- Use one reviewed tissue as a held-out benchmark after expert labels are completed.
- Freeze the label and region files; do not iterate on them during agent tuning.
- Track label accuracy, ARI/F1, region-composition error, neighborhood reproducibility, and unsupported-claim refusal rate.

Local status:

- Demo/eval cases exist for software QA.
- Local Xenium datasets do not yet have biological ground truth.

## 4. Curated Tissue-Matched scRNA/scATAC References

How to get them:

- Use local data only for software QA until curated references are added.
- For real reference-assisted annotation, collect tissue-matched references for breast, lymph node, healthy brain, and glioblastoma.
- Required metadata: cell-type labels, sample/tissue context, gene ID namespace, species, batch/source, and license/consent terms.
- Recommended portals: CZ CELLxGENE Discover, Human Cell Atlas, Allen Brain resources, Broad Single Cell Portal, NCBI GEO, EBI Single Cell Expression Atlas, Ivy Glioblastoma Atlas Project, and NCI GDC/TCGA.

Acceptance checks:

- Shared gene overlap with the Xenium panel.
- Clear label ontology.
- Reference-transfer confidence threshold.
- Refusal when overlap or metadata is insufficient.

## 5. Dataset License / Consent / PHI Metadata

Required manifest fields:

- source and source URL,
- license,
- consent class,
- PHI risk,
- allowed use,
- restrictions,
- reviewer,
- notes.

How to get it:

- Pull license/source terms from the dataset provider or publication.
- Pull consent terms from IRB/dbGaP/DUO metadata for controlled human data.
- Review local filenames, metadata, image labels, and clinical fields for PHI risk.
- Keep raw data out of LLM prompts; pass summaries and artifact IDs only.

Local implementation:

- `scripts/build_dataset_governance_manifest.py` creates a reviewable manifest template.
- Link sources and policy references are listed in the root `README.md` under External Links.

## 6. Full Replay CLI / Database Storage

How to conduct locally:

- Index all run records into SQLite using `scripts/index_run_database.py`.
- Verify hashes using `scripts/replay_run.py`.
- Replay supported validated Xenium pilot run records after hash verification.

Current scope:

- Local SQLite run index.
- Input/artifact/figure/table MD5 verification.
- Automatic replay for validated Xenium pilot run records.

Future hardening:

- Add PostgreSQL for multi-user deployment.
- Add object storage for large artifacts.
- Add replay comparison reports with output hash diffs.

## Current Local Workflow

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/promote_local_agent.py --data-root data --out outputs/agent_promotion --max-records 800
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/build_dataset_governance_manifest.py --data-root data --out outputs/governance/dataset_governance_manifest.json
.venv/bin/python scripts/index_run_database.py --outputs-root outputs --db outputs/spatialmind_runs.sqlite
```
