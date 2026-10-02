# Ordered Brain Validation Work

Updated 2026-09-30. The user confirmed that no reviewers are currently available.
The software preparation below is implemented; the biological study is **not complete**.
No specialist names, reviewed labels, anatomical regions, registered images, or independent-donor performance have been fabricated.

## 1. Assign Specialists

Current packet: `outputs/brain_specialist_handoff_20260927/`, containing two frozen
750-cell cohorts (healthy brain and glioblastoma). Both still have zero accepted
cell labels and zero accepted anatomical regions.

`study_readiness.json` now holds two explicitly unassigned roles. The brain
single-cell specialist owns cell identity, panel coverage, ambiguity, and cell-state
interpretation. The neuropathologist owns specimen pairing, anatomical interpretation,
pathological boundaries, and image review. One person may hold both roles only when
qualified for both. A software-generated reviewer identity is not acceptable.

Ask the project leader to nominate collaborators through your institution's
single-cell/genomics core and neuropathology service. Give each person the cohort
viewer, first-pass sheets, marker evidence and the separate second-pass candidate
sheet. Ask them to accept the role and record an institutional profile or other
qualification evidence. No invitations have been sent by this agent.

Suggested request:

> We seek a brain single-cell specialist and a neuropathologist to review two
> Xenium brain cohorts, 750 cells each. Please assess cell identities and anatomical
> regions independently of model predictions on the first pass, document uncertainty
> and evidence, and identify cases needing H&E/IHC. Please confirm which role you
> can accept and whether a second reviewer is available for ambiguous cases.

After acceptance, record the actual person's ID (not the placeholder below):

```bash
.venv/bin/python scripts/manage_brain_specialist_review.py assign \
  --packet outputs/brain_specialist_handoff_20260927 \
  --role brain_single_cell_specialist --reviewer-id ACTUAL_REVIEWER_ID \
  --qualification-evidence ACTUAL_INSTITUTIONAL_PROFILE --accepted
```

Repeat for `--role neuropathologist`. Assignment alone does not constitute review.
For initialized studies, staging checks reviewer identity against the assignments.
Existing legacy packets without a readiness registry retain their earlier checks.
At least 90% of cells in **each** frozen split must have jointly accepted decisions.
Neither registration nor computational annotation fills these decisions automatically.

## 2. Obtain Matched Images

The current local brain bundles contain DAPI morphology but no identified registered
H&E/IHC. Their source is the [10x 2023 brain preview collection](https://www.10xgenomics.com/datasets/xenium-human-brain-preview-data-1-standard),
with 24,406 healthy and 40,887 glioblastoma cells. These are the specific specimens
to request from 10x support/the tissue provider. The published page identifies Acepix
for healthy brain and Avaden for glioblastoma. Matching tissue type or a similar
filename does not establish section identity.

Request original H&E or relevant IHC/IF images, donor/slide/section identifiers,
pixel scale, orientation, staining/channel metadata, source/license, and any existing
registration transform. An adjacent section is not interchangeable with the same
section for cell-level labeling. If the original specimen cannot supply matched
histology, keep unsupported anatomy unresolved, or designate a new matched specimen
as a separate study rather than attaching an unrelated image to these cells.

Follow the [official 10x alignment guide](https://www.10xgenomics.com/support/software/xenium-explorer/latest/tutorials/xe-image-alignment).
Use landmarks distributed across the tissue, inspect nuclei overlays and local
distortion, and reserve independent landmarks for checking the transform.

Fill [the image evidence schema](templates/brain_image_evidence.example.json).
Set its path under `images.<dataset>.evidence_manifest` in `study_readiness.json`.
Paths in its `files` dictionary map to SHA-256 digests and are relative to the
manifest unless absolute. Hash both the image and the exact `experiment.xenium`.
The neuropathologist must confirm same-section pairing and visual alignment.

The validator expects a 3x3 affine transform mapping an image pixel column vector
`[x_px, y_px, 1]` to Xenium `[x_um, y_um, 1]`. **Do not paste a native Explorer
matrix without verifying its units and direction.** Each landmark is an object
with `use` (`fit` or `check`), `image_xy_px` and `xenium_xy_um` (two numbers each).
At least three noncollinear points in each group are required; checking points
cannot reuse fitting points. This is a software minimum, not a recommendation
that six points suffice for a large or distorted section. Prespecify the maximum
acceptable checking error in microns with a task-specific rationale. No universal
biological tolerance is assumed. Identity transforms are valid only for genuinely
prealigned images with verified pixel/micron scaling.

The validator rejects wrong specimens, missing hashes, DAPI substitutes, unknown
units, singular matrices, out-of-image landmarks and excessive independent residuals.
It does not perform automatic image registration, certify tissue identity, detect
all nonlinear distortions, or certify individual anatomical region boundaries.

## 3. Acquire and Freeze an External Donor

Candidate identified: [BioStudies S-BSST2273](https://www.ebi.ac.uk/biostudies/studies/S-BSST2273),
described in [De et al., Communications Biology](https://www.nature.com/articles/s42003-025-09270-7).
The repository metadata was downloaded to
`data/external_candidates/S-BSST2273/`, with timestamp and SHA-256 provenance.
**Only metadata was acquired, not expression matrices, histology or test truth.**

The repository lists `GBM_supp.tar.gz` (6,567,174,953 bytes), containing an annotated
Seurat object, necrotic-cell list and H&E; raw Xenium GBM output is 27,460,467,573
bytes. Repository metadata declares CC0. Do not substitute the article's license
for the dataset's recorded terms. The integrated GBM/grade-3 object is not a
preferred independent test input because joint integration complicates provenance.

Before bulk acquisition, have a data custodian confirm donor identifiers, no overlap
with development material/references, annotation methods and label granularity,
panel gene coverage, and whether raw counts can be exported as H5AD with separate
cell-label metadata. The panel emphasizes extracellular-matrix biology, so its
suitability for rare brain-cell identity testing is not established by the paper
title. Author computational annotations are independently produced labels, but not
automatically histological or specialist-certified truth.

Use [the external-test manifest](templates/brain_external_test.example.json).
It requires disjoint development/test donor IDs plus documentary evidence, label
provenance, license, assay, a frozen label crosswalk and evaluation protocol, and
hashed expression/truth files. Keep test labels with the custodian until model lock.
The checks validate recorded provenance; they do not establish independence merely
because donor ID strings differ. A public metadata catalog cannot pass this gate.

No large archives were downloaded yet: compatibility, donor identity and independent
label quality remain unverified. The existing GSE311609 breast donors are not a brain
benchmark and do not currently have the needed published expert label files.

## 4. Rare-Class Development, Then One External Evaluation

Brain training and external scoring remain blocked. There is no honest brain model
performance number to report until the preceding inputs exist. Software now
supports reviewed brain selection and an explicit custodian-released external
test, but neither has been run on real reviewed brain truth.

Implemented now: optional `class_prior_power` on the production
`reference_label_transfer` tool, default **0** (unchanged behavior). It divides each
neighbor-vote probability by the corresponding **training-only** class frequency
raised to this power, then renormalizes. It can help underrepresented classes already
present among neighbors; it cannot discover missing classes or create marker evidence.
Adjusted votes are not calibrated probabilities. Existing coverage checks and expert
review caveats remain in effect. No prediction is promoted to reviewed truth.

A separate, explicitly **breast-only development experiment** reused the frozen
11,263 training cells and 3,737 validation cells, 313 genes, and k=15. Powers
0, 0.25, 0.5 and 1 were declared before fitting. Selection used validation macro-F1,
with lower power breaking ties; rare classes were defined only from training support
(less than 100 cells). The previous internal test truth was not opened or rescored.

| Validation Metric | Default | Selected Power 0.25 |
|---|---:|---:|
| Accuracy | 82.53% | 82.66% |
| Macro-F1 | 0.6705 | 0.7196 |
| Balanced accuracy | 63.73% | 73.54% |
| Rare-class macro-F1 | 0.4749 | 0.5788 |
| Coverage at fixed 0.6 threshold | 76.91% | 75.17% |
| Accuracy among retained predictions | 91.20% | 91.53% |

These are selection metrics on a reused validation set, not unbiased performance
estimates. Rare-class improvement does not generalize automatically to brain, and
some classes remain unresolved. No confidence calibration, external test or default
model promotion occurred. The original k=15 validation metrics reproduce exactly.

Output: `outputs/rare_class_development_20260927/report.html`, with selection protocol,
locked parameters, per-class metrics, validation predictions and artifact hashes.
The lock describes a KNN reference/parameter policy, not an LLM fine-tune or a serialized
standalone classifier. Its reference must remain restricted to the frozen training IDs.

```bash
.venv/bin/python scripts/select_rare_class_annotation.py \
  --benchmark outputs/annotation_holdout_20260927_v2 \
  --matrix data/Xenium_Breast_Cancer_Rep1_Janesick2023/cell_feature_matrix.h5 \
  --out outputs/rare_class_development_NEW_RUN
```

Once brain reviews are complete, freeze a brain-specific development protocol and
training/validation cohort; choose model, hyperparameters, feature panel, class
crosswalk and abstention/calibration policy there only. Hold out entire donors
where possible. Lock all artifacts and code version before releasing the external
truth. Report all-cell and per-class accuracy/F1, rare-class support, balanced
accuracy, coverage/selective accuracy, calibration, unknown-class failures and assay
shift. One independent donor is an external case study, not a population-level
validation; donor confidence intervals need multiple independent donors. After
any test-driven change, that donor becomes development data and a new test is needed.

## Current Ordered Status

```bash
.venv/bin/python scripts/manage_brain_specialist_review.py readiness \
  --packet outputs/brain_specialist_handoff_20260927
```

This writes `ordered_readiness_report.json`: step 1 needs reviewers; steps 2-4 are
blocked by earlier prerequisites while listing their own missing inputs. This is
intentional, not a failed analysis. The most useful next human action is to ask the
project leader to secure the two reviewers and a data custodian. No final brain
CSV files or externally validated model have been generated.

The readiness command also writes `ordered_readiness_report.html`, listing
accepted-review counts and ordered blockers. Only status artifacts are updated,
not human review CSVs.

## Execution After Review

Use new output directories. Do not rename candidates to final truth. Old label
tables without explicit provenance no longer unlock the gate, including published
labels and composition-derived regions. Preserve them as evidence and obtain a
documented review; do not bulk-add approval fields.

```bash
.venv/bin/python scripts/manage_brain_specialist_review.py validate \
  --packet outputs/brain_specialist_handoff_20260927 \
  --export-to outputs/brain_review_staging_NEW

.venv/bin/python scripts/validate_brain_model.py select \
  --packet outputs/brain_specialist_handoff_20260927 \
  --staging outputs/brain_review_staging_NEW \
  --donor-map VERIFIED_DEVELOPMENT_DONORS.json --out outputs/brain_model_NEW
```

The donor map is a JSON object mapping every section key to its verified donor ID.
Omit it only for internal development; external scoring then stays blocked. The
selector reads staged train/validation truth, not staged test truth. Source review
files are hashed, not parsed. It selects k=5/15 and prior power=0/0.25/0.5/1 by
validation macro-F1. Outputs contain the frozen training reference, parameters,
features, source/review hashes, per-class validation metrics and predictions.
Selection metrics are optimistic, not independent performance estimates.

Give the custodian the SHA-256 of `locked_model.json`. Their hashed protocol must
name `model_lock_sha256`, `confidence_threshold` (0.6), `min_shared_features` and
`min_shared_fraction`. Prespecify overlap thresholds with biological justification;
two shared genes is a code minimum, not a scientific recommendation. The crosswalk
CSV has `source_label,target_label`. External truth needs unique cell_id,
expert_label, donor_id, approval, reviewer/date, confidence and evidence. Truth must
match every prediction exactly; no post-result dropping of difficult cells.

A [protocol example](templates/brain_annotation_protocol.example.json) supplies
the schema, not universal acceptance thresholds. Adapt and approve it before
sealing. Fit/tune only on development donors; a seen external donor is no longer
an untouched test.

```bash
.venv/bin/python scripts/validate_brain_model.py external-test \
  --model-lock outputs/brain_model_NEW/locked_model.json \
  --manifest VERIFIED_EXTERNAL_MANIFEST.json --custodian-id ACTUAL_CUSTODIAN_ID \
  --expected-lock-sha256 EXACT_MODEL_HASH --out outputs/brain_external_test_NEW
```

The evaluator reserves one attempt beside the model before prediction, saves
predictions before parsing truth, then reports all-cell/per-class metrics, coverage,
selective accuracy and per-donor results. Errors after reservation do not permit a
silent retry. This is procedural sealing, not secure isolation. Never delete the
reservation to tune against the same donor; failed/completed attempts require a
new documented custodian study/release. Cross-assay annotation tests do not
validate Xenium segmentation, spatial neighborhoods or pathological ROI accuracy.

Set `model_lock` and `external_evaluation` paths in `study_readiness.json` only
after successful runs. Readiness checks model/manifest identity; it does not
declare population-level validity.

Verification on 2026-09-30: 586 unit tests passed, including 24 new review-boundary,
model-lock and donor-held-out calibration regression tests; all six import
contracts passed. Legacy routing evaluation passed 16/16 and MVP evaluation 13/13.
This is software verification, not evidence that the outstanding biological
review is complete. Both 750-cell specialist cohorts still have zero accepted
labels and zero accepted anatomical regions; local brain selection remains blocked.
