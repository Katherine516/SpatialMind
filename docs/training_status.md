# SpatialMind Training Status

Last updated: 2026-07-11

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
| Unit tests | 81/81 passing in the full environment |
| Legacy eval | 15/15 passing, mean score 1.0000 |
| MVP eval | 10/10 passing, mean score 1.0000 |
| Full environment `pip check` | Passing |
| Numerical runtime isolation | Passing; default `.venv` is PyTorch-free with one OpenMP runtime |
| Import boundary check | Passing |
| Real backend validation | Scanpy DE/clustering/HVG and Squidpy neighborhood enrichment passing |
| Xenium breast MVP run | Completed with report and visualizations |
| Xenium expert-label readiness inventory | Completed for 4 local Xenium datasets |
| Local training record generation | 18 records, mean behavior score 1.0000 |
| Region-label template generation | Completed for 4 local Xenium datasets |
| Validated Xenium pilot scorecard | 4 datasets scanned, 0 validated-ready |
| v11 real-agent pilot controls | Typed plan, claim ledger, limitations, and run record generated |
| Xenium label-intake validator | Generated blocked intake report for breast dataset |
| v12 claim-level reliability | S/A/P/R weakest-link scores generated for every pilot claim |
| Human brain reliability pass | 8 local claim/control records, AUROC 1.0000 on local controls, calibrated model not fit |
| Claim-truth review packet | Generated for healthy brain and glioblastoma; awaiting expert review |

Latest local training artifacts:

- `outputs/full_workflow_20260711/FULL_WORKFLOW_REPORT.md`
- `outputs/full_workflow_20260711/training/local_spatialmind/training_records.jsonl`
- `outputs/full_workflow_20260711/training/local_spatialmind/training_summary.json`
- `outputs/full_workflow_20260711/training/local_spatialmind/training_report.md`
- `outputs/full_workflow_20260711/training/claim_reliability/claim_reliability_training_report.md`

- `outputs/training/local_spatialmind_training/training_records.jsonl`
- `outputs/training/local_spatialmind_training/training_summary.json`
- `outputs/training/local_spatialmind_training/training_report.md`
- `outputs/xenium_expert_mvp_readiness/*/region_label_template.csv`
- `outputs/xenium_validated_pilot/pilot_validation.json`
- `outputs/xenium_validated_pilot/runs/*.json`
- `outputs/xenium_label_intake/label_intake_report.json`
- `outputs/xenium_label_intake/label_intake_report.md`
- `outputs/xenium_pilot_scorecard/pilot_readiness_scorecard.md`
- `outputs/training/human_brain_claim_reliability_v12/claim_reliability_training_report.md`
- `outputs/training/human_brain_claim_reliability_v12/claim_reliability_training_records.json`
- `outputs/training/human_brain_claim_reliability_v12/healthy_brain_pilot/validated_xenium_pilot_report.html`
- `outputs/training/human_brain_claim_reliability_v12/glioblastoma_pilot/validated_xenium_pilot_report.html`
- `outputs/claim_reliability_review_packet_v12/spatial_claim_truth_draft_for_review.csv`
- `outputs/claim_reliability_review_packet_v12/claim_truth_validation_report.md`
- `outputs/training/human_brain_claim_reliability_review_gate_v12/claim_reliability_calibration_model.json`

The latest 18 generated records are distributed as:

- 10 MVP query-plan-result records,
- 4 real-wrapper exploratory Xenium pipeline records,
- 4 Xenium expert-label readiness records.

The v11 pilot run also creates structured readiness/refusal records:

- `tool_plan` records the typed Xenium sequence and required upstream outputs.
- `plan_validation` records whether expert labels and user regions are available before tools run.
- `claim_ledger` refuses unsupported biological claims when validation inputs are missing.
- `run_record_path` points to a hashed local run record for provenance and future replay work.

These records are useful for planner training, tool-selection regression, refusal-policy training, readiness-policy training, weak-label caveat training, and pipeline regression. They are not useful as biological ground truth yet because the local Xenium datasets still lack expert labels.

## Claim-Level Reliability Training Status

The v12 plan promotes reliability from a run-level statement to a per-claim score. Each report claim is scored with four components:

- `S_statistical`: statistical support from p-values, z-scores, or effect sizes.
- `A_annotation`: expert-label or validated reference-label support.
- `P_panel`: targeted-panel adequacy for the markers required by the claim.
- `R_spatial_robustness`: robustness across spatial neighborhoods, graph/radius settings, and null controls.

The current baseline combiner is conservative:

```text
claim_reliability = min(S_statistical, A_annotation, P_panel, R_spatial_robustness)
```

This is implemented and report-ready. The calibrated logistic combiner is scaffolded but intentionally marked `not_fit` because the local human brain data does not yet contain expert-reviewed spatial claim truth labels.

Latest local human-brain run:

| Metric | Result |
| --- | --- |
| Datasets | Healthy brain Xenium and glioblastoma Xenium |
| Records | 8 claim/control records |
| Positive controls | 2 non-biological readiness claims |
| Negative controls | 6 refused biological/null-control claims |
| AUROC on local controls | 1.0000 |
| Calibrated model status | not_fit |

Interpretation:

- This run validates the reliability pipeline, refusal behavior, and null-control handling.
- It does not prove biological claim correctness.
- Biological claims stay at reliability `0.0000` while expert labels and ROI regions are missing.
- Dataset-readiness claims can score above zero because they are grounded in file/asset checks, not biological interpretation.

The next training milestone is to create expert-reviewed positive and negative spatial claims, then fit the calibrated combiner on train/validation/test splits.

The software path for that milestone now exists:

1. Generate `spatial_claim_truth_draft_for_review.csv` with `scripts/prepare_claim_reliability_review_packet.py`.
2. A reviewer fills `reviewed_truth_label`, `use_for_calibration`, `truth_basis`, `source_citation`, and `reviewer_id`.
3. Validate the completed table with `--validate-truth`.
4. Rerun `scripts/train_claim_reliability_local.py --claim-truth <completed csv>`.
5. If the table has at least four usable reviewed records with both positive and negative claims, the trainer writes `claim_reliability_calibration_model.json` with logistic weights.

Current claim-truth review status:

| Metric | Result |
| --- | --- |
| Draft rows | 11 |
| Reviewed calibration rows | 0 |
| Status | blocked |
| Blocker | awaiting expert-reviewed positive and negative claim truth |

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
2. Add reviewed positive spatial claims and null-control claims for healthy brain and glioblastoma.
3. Rerun `scripts/train_claim_reliability_local.py` and fit the calibrated logistic reliability combiner once enough truth labels exist.
4. Rerun `scripts/train_spatialmind_local.py` to convert reviewed labels into stronger query-plan-result records.
5. Expand the local corpus from 18 records to at least 50 reviewed v7 MVP records.
6. Add expert-reviewed interpretations and corrections for at least one Xenium tissue.
7. Expand to 100 to 200 examples across scRNA, scATAC, Xenium, and reference-assist workflows.
8. Train or tune the planner only after the labels and expected outputs are reviewed.
9. Keep a held-out benchmark set so improvements do not overfit the examples.

## Current Limitation

The latest Xenium breast report is useful for system validation and visualization QA. It should not be used as supervised biological ground truth until the cell labels are reviewed or replaced by validated reference annotation.

## 2026-07-17 Training Refresh

The post-environment-fix training refresh is stored under `outputs/training/current_20260717/`.

| Metric | Result |
| --- | --- |
| Behavioral records | 18 |
| Mean behavior score | 1.0000 |
| Xenium wrapper runs | 4/4 completed with Scanpy and Squidpy |
| Runtime conflict warnings | 0 |
| Claim/control records | 8 |
| Local-control AUROC | 1.0000 |
| Biological calibration | `not_fit`; awaiting expert review |

The detailed run report is `outputs/training/current_20260717/TRAINING_AND_REVIEW_REPORT.md`. The exact process for obtaining and validating `expert_cell_labels.csv`, `cell_regions.csv`, and completed claim truth is documented in `docs/expert_review_workflow.md`.
