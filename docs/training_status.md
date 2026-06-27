# SpatialMind Training Status

Last updated: 2026-06-27

## Summary

SpatialMind has not yet been fine-tuned or trained as a learned model. The current training approach is evaluation-driven agent development: improve the deterministic planner, tool schemas, precondition checks, grounding rules, and report behavior against curated cases before collecting supervised examples for model training.

This is the right stage for the project. Fine-tuning before we have expert-labeled examples would teach the model from weak labels and prototype outputs.

## Current Training Pass

The current validation pass trains the agent behavior in the engineering sense:

- plan selection is checked against expected tool traces,
- refusal/deferral behavior is checked for unsupported MVP workflows,
- grounding warnings are checked for Xenium targeted panels and scATAC accessibility-inferred outputs,
- wrapper compatibility is checked in the full environment,
- run artifacts are generated for a real local Xenium breast dataset,
- local query-plan-result records are generated for future planner tuning and regression tests.

Current gates:

| Gate | Result |
| --- | --- |
| Unit tests | 45/45 passing in the full environment |
| Legacy eval | 15/15 passing, mean score 1.0000 |
| MVP eval | 10/10 passing, mean score 1.0000 |
| Full environment `pip check` | Passing |
| Import boundary check | Passing |
| Real backend validation | Scanpy DE/clustering/HVG and Squidpy neighborhood enrichment passing |
| Xenium breast MVP run | Completed with report and visualizations |
| Xenium expert-label readiness inventory | Completed for 4 local Xenium datasets |
| Local training record generation | 15 records, mean behavior score 1.0000 |
| Region-label template generation | Completed for 4 local Xenium datasets |
| Validated Xenium pilot scorecard | 4 datasets scanned, 0 validated-ready |
| v11 real-agent pilot controls | Typed plan, claim ledger, limitations, and run record generated |
| Xenium label-intake validator | Generated blocked intake report for breast dataset |

Latest local training artifacts:

- `outputs/training/local_spatialmind_training/training_records.jsonl`
- `outputs/training/local_spatialmind_training/training_summary.json`
- `outputs/training/local_spatialmind_training/training_report.md`
- `outputs/xenium_expert_mvp_readiness/*/region_label_template.csv`
- `outputs/xenium_validated_pilot/pilot_validation.json`
- `outputs/xenium_validated_pilot/runs/*.json`
- `outputs/xenium_label_intake/label_intake_report.json`
- `outputs/xenium_label_intake/label_intake_report.md`
- `outputs/xenium_pilot_scorecard/pilot_readiness_scorecard.md`

The 15 generated records are distributed as:

- 10 MVP query-plan-result records,
- 1 weak-label breast Xenium pipeline record,
- 4 Xenium expert-label readiness records.

The v11 pilot run also creates structured readiness/refusal records:

- `tool_plan` records the typed Xenium sequence and required upstream outputs.
- `plan_validation` records whether expert labels and user regions are available before tools run.
- `claim_ledger` refuses unsupported biological claims when validation inputs are missing.
- `run_record_path` points to a hashed local run record for provenance and future replay work.

These records are useful for planner training, tool-selection regression, refusal-policy training, readiness-policy training, weak-label caveat training, and pipeline regression. They are not useful as biological ground truth yet because the local Xenium datasets still lack expert labels.

## What Data We Need For Real Training

The agent needs supervised training records, not just raw omics matrices.

Each useful record should contain:

- user query,
- dataset modality and metadata,
- expected workflow type,
- expected tool sequence,
- expected parameters,
- expected clarification/refusal when the request is not supported,
- expert-reviewed interpretation,
- accepted caveats,
- links to generated figures/tables,
- provenance for raw data and labels.

## Biological Data Needed

### Xenium

- Cell coordinates, transcript/gene matrix, panel metadata, morphology image metadata, and segmentation boundaries.
- Expert labels or high-quality reference-transferred labels.
- Tissue-specific references for breast, lymph node, healthy brain, and glioblastoma.
- Negative examples for missing panel genes and ambiguous labels.

Current local status:

- Breast, lymph node, healthy brain, and glioblastoma folders all have the core Xenium raw assets needed for an expert-label MVP.
- All four are missing external expert/reference label tables.
- All four are missing user-provided region label tables for `region_summary`.
- Expert-label and region-label templates were generated under `outputs/xenium_expert_mvp_readiness/`.
- The accepted minimum label table is `cell_id,expert_label`; `confidence` and `notes` are recommended.
- The recommended training label table is `cell_id,expert_label,cl_id,secondary_state,confidence,notes`.
- Brain/glioblastoma labels should follow `docs/cell_ontology_labeling_guide.md`.
- The accepted minimum region table is `cell_id,region`; `region_confidence` and `notes` are recommended.

### scRNA-seq

- Raw or normalized cell-by-gene matrices.
- Curated cell-type labels.
- Batch/sample metadata.
- Marker genes and reference labels suitable for transfer to Xenium.

### scATAC-seq

- Cell-by-peak matrix or gene activity matrix.
- Motif/TF activity ground truth or accepted benchmark outputs.
- Cell-type labels and paired or matched scRNA references where possible.
- Clear wording labels that separate accessibility inference from expression.

### Integration

- Matched or biologically comparable scRNA/scATAC/Xenium datasets from the same tissue.
- Shared feature maps.
- Expert-reviewed label transfer outputs and confidence thresholds.
- Cases where integration should be refused because feature overlap or metadata is insufficient.

## Training Roadmap

1. Add expert/user labels and user-provided region labels for at least one local Xenium tissue.
2. Rerun `scripts/train_spatialmind_local.py` to convert those labels into stronger query-plan-result records.
3. Expand the local corpus from 15 records to 50 v7 MVP records.
4. Add expert-reviewed interpretations and corrections for at least one Xenium tissue.
5. Expand to 100 to 200 examples across scRNA, scATAC, Xenium, and reference-assist workflows.
6. Train or tune the planner only after the labels and expected outputs are reviewed.
7. Keep a held-out benchmark set so improvements do not overfit the examples.

## Current Limitation

The latest Xenium breast report is useful for system validation and visualization QA. It should not be used as supervised biological ground truth until the cell labels are reviewed or replaced by validated reference annotation.
