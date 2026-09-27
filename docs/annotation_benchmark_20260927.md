# Held-Out Annotation Benchmark and Specialist Brain Handoff

Date: 2026-09-27.

## Status and Scope

The production reference-transfer tool now has a reproducible, label-blind, buffered spatial holdout benchmark. It fits a distance-weighted KNN reference on training labels, selects k on validation only, and evaluates test predictions against separately held published labels. This is **internal validation within one breast section, not an independent donor benchmark**. An additional labeled specimen with documented donor/section identity remains necessary for external validation.

The healthy-brain and glioblastoma specialist handoffs are prepared, with morphology-backed ROI context. **Specialist review is not complete:** both cohorts have zero accepted labels and zero accepted anatomical regions. No final brain `expert_cell_labels.csv` or `cell_regions.csv` was manufactured or installed.

## Accepted Benchmark Run

[Open the HTML report](../outputs/annotation_holdout_20260927_v2/report.html).

| Item | Result |
| --- | --- |
| Source | Local Janesick breast replicate 1; published supervised labels |
| Requested / QC-retained cells | 20,000 / 19,557 |
| Expression features | 313; control probes/codewords excluded |
| Spatial design | 6 x 6 coordinate blocks; seeded whole-block assignment |
| Separation | 50-micron minimum between retained cells in different splits |
| Buffer exclusions | 865 cells |
| Remaining cells lacking published labels | 582; not scored |
| Train / validation / test | 11,263 / 3,737 / 3,110 |
| Model selection | k=15 selected from k=5 and k=15 using validation macro-F1 |
| Test label classes | 19; none absent from training |
| Accuracy | 80.71% |
| Macro-F1 | 0.6208 |
| Balanced accuracy | 57.00% |
| Weighted F1 | 0.7932 |
| Training-majority baseline accuracy / macro-F1 | 22.64% / 0.0194 |
| Coverage at fixed vote threshold 0.6 | 76.53% |
| Accuracy among retained predictions | 88.61% |
| Macro-F1 counting abstentions as missed labels | 0.4652 |
| Accuracy block-bootstrap interval | 77.45%-84.02% |
| Macro-F1 block-bootstrap interval | 0.5347-0.6341 |

Bootstrap intervals use 200 resamples of seven test blocks. They describe variation within this section, not between donors. Spatial separation reduces immediate-neighbor leakage but does not create biological independence. Published expression-assisted labels also are not independent assay truth. The existing reference-transfer tool's incomplete-reference preflight is explicitly overridden for benchmarking so unsupported classes would count as errors rather than disappearing from evaluation; this does not change production gating.

### Interpretation

Overall accuracy is substantially above a training-majority baseline, but it hides important class imbalance. For example, the test F1 is 0 for `Stromal_&_T_Cell_Hybrid` (11 cells), 0.163 for `Prolif_Invasive_Tumor` (79 cells), and 0.167 for `LAMP3+_DCs` (11 cells). Some small class estimates are highly uncertain. These findings support an assisted annotation workflow with abstention and review, not unattended fine-grained cell typing.

Confidence here is a neighbor vote fraction, not calibrated correctness. The selective metric uses that threshold alone; it does not measure a complete expert acceptance policy incorporating marker conflicts and reference coverage. No claim-reliability calibration model or deep-learning model was trained in this step.

### Leakage and Provenance

- Fresh prediction objects contain expression and cell IDs, but no cell labels, regions, original metadata, spatial coordinates, or source paths.
- The reference contains training labels only. Feature selection uses training expression, not test label associations.
- Whole blocks do not cross splits; the recorded cell-ID and spatial-block overlap counts are zero.
- A regression test changes hidden query labels and verifies unchanged production-tool predictions.
- The protocol and split manifest are written before model selection. Selection is locked before test predictions are written, and outputs cannot overwrite an existing benchmark directory.
- Input and output SHA-256 manifests identify the evaluated artifacts. Evaluator-only truth files are logically separated, not protected by an access-control sandbox.
- This test set has now been inspected. Further model development must use train/validation data; confirm improvements on a newly locked external test specimen.

### Ingestion Defect Found and Fixed

The older breast H5 matrix declares 159 `Blank Codeword` features. The existing declared-type exclusion list did not recognize this class, allowing detected blank controls into expression analyses. Added this instrument feature type to the shared exclusion list and tested H5 declaration parsing plus downstream feature filtering.

The exploratory run at `outputs/annotation_holdout_20260927/` is **superseded** because it included 458 detected features, including blank controls. Use only the `_v2` run above. Older breast reports should be regenerated with the corrected filter before reuse as current evidence; the earlier correctness-release reports remain historical records.

## Brain Review Materials

[Reviewer instructions](../outputs/brain_specialist_handoff_20260927/REVIEW_INSTRUCTIONS.md) and [readiness status](../outputs/brain_specialist_handoff_20260927/specialist_validation.json).

| Tissue | Frozen cohort | Accepted labels / regions | Morphology context |
| --- | --- | --- | --- |
| Healthy brain | 750 cells | 0 / 0 | 12 candidate domains; 9 meeting the packet's size criterion |
| Glioblastoma | 750 cells | 0 / 0 | 13 candidate domains; 11 meeting the packet's size criterion |

The pre-existing August 12 cohorts and split assignments are preserved. Blank first-pass decision sheets omit machine candidate labels; original candidate evidence remains available separately. Existing cluster-based cohort viewers remain expression evidence, not independent morphology adjudication.

- [Healthy-brain morphology ROI packet](../outputs/brain_specialist_handoff_20260927/healthy_brain/roi_context/region_review.html)
- [Glioblastoma morphology ROI packet](../outputs/brain_specialist_handoff_20260927/glioblastoma/roi_context/region_review.html)

Candidate domains and gene-selected hotspots are not anatomical boundaries. The ROI pages hide cell composition but retain the candidate domains; a pathologist may reject or redraw them. The cohort decision sheet, not the domain naming sheet alone, is the input to the strict staging command. A domain-level name must not silently turn every cell into reviewed anatomical truth.

### What a Reviewer Must Supply

For labels: `expert_label`, optional appropriate `cl_id` and separate `secondary_state`, confidence, reviewer identity, ISO review date, evidence reference, and explicit reviewed/approved status. Uncertain cases remain uncertain.

For regions: the anatomical name, confidence, reviewer identity/date, reviewed status, `region_basis`, and image/slide/ROI evidence reference. Accepted bases are morphology, registered histology, or registered IHC. Composition-only regions are not accepted by this handoff.

At least 90% of each split must have jointly accepted labels and regions; duplicate/mismatched cell IDs, changed frozen coordinates/splits, or invalid provenance block export. Staging exports only jointly accepted cells. It does not install files into `data/`, verify professional credentials, certify the biological decisions, or imply full-section review coverage.

## Verification

- Full unit suite: 548/548 passed in 266.394 seconds, including 18 new benchmark/handoff tests.
- All six import contracts passed; compilation, documentation inventory checks, and `git diff --check` passed.
- All 12 benchmark artifact hashes verified; the accepted protocol has 313 expression features and no blank codewords.
- Confusion and split figures plus a morphology ROI crop were visually inspected. Browser preview of the local HTML was blocked by the browser URL policy; a full browser-layout check was not completed.
- Logs: `outputs/annotation_benchmark_verification_20260927/`.

## Commands

```sh
# New output directory required on every benchmark run.
.venv/bin/python scripts/evaluate_annotation_holdout.py \
  --data data/Xenium_Breast_Cancer_Rep1_Janesick2023 \
  --out outputs/annotation_holdout_new

# Validate reviewer decisions without writing final files.
.venv/bin/python scripts/manage_brain_specialist_review.py validate \
  --packet outputs/brain_specialist_handoff_20260927

# Only after review passes; produces staged cohort files, not full-section truth.
.venv/bin/python scripts/manage_brain_specialist_review.py validate \
  --packet outputs/brain_specialist_handoff_20260927 \
  --export-to outputs/brain_reviewed_staging
```

## Next Decisions and Needed Inputs

1. Assign a brain single-cell specialist and neuropathologist to the two packets. Include a blinded second review of disputed cases and a prespecified random subset, followed by adjudication. Do not substitute machine suggestions for their signatures.
2. Obtain registered H&E/IHC and anatomical context where the available nuclear morphology is insufficient. Record specimen/section identity and coordinate transforms. The official [Xenium image alignment guide](https://www.10xgenomics.com/support/software/xenium-explorer/latest/tutorials/xe-image-alignment) describes the registration workflow.
3. Obtain at least one additional labeled donor with compatible panel/features for a locked external test, preferably several for generalization estimates. A consecutive section from the same tumor is useful section-level validation but not independent donor validation. The [Janesick study](https://www.nature.com/articles/s41467-023-43458-x) documents the current public breast resource; do not treat it as brain truth.
4. Develop class-balanced and hierarchical annotation baselines on train/validation only. Separate broad identity from proliferative/malignant state, quantify per-class errors and abstention, and lock the model before opening a new external test.
5. After reviewed brain labels/regions exist, evaluate brain annotation separately, rerun reviewed-cell spatial analyses, and collect independently judged spatial claims for reliability calibration. Do not use this breast classification accuracy as the probability that a brain spatial claim is correct.

No raw data or existing review decisions were overwritten. No GitHub push or desktop rebuild was performed.
