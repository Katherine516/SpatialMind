# Brain Reference Readiness and Safe Ingestion

Date: 2026-10-03. This is the next P1 increment after the
[correctness upgrade](correctness_upgrade_20261003.md), not completed biological
training or a new assay adapter. All generated curation and donor plans remain
unapproved. No raw datasets, expert decisions or sealed-test scores were changed.

Follow-up: the [ordered P1 implementation](brain_p1_implementation_20261003.md)
supersedes this increment's path-based merged identities with content-bound IDs
and adds sparse caches and mandatory development protocols. The observations
and timings below remain the historical measurements from this earlier increment.

## Findings From Local Data

The audit inspected nine H5AD files, their source metadata, donor membership and
bounded numeric samples. It completed with zero file errors.

| Reference | Declared organism | Observed donors | Candidate count layer | Direct human-reference eligibility |
| --- | --- | ---: | --- | --- |
| GBmap Core | Homo sapiens | 110 | raw/X | Candidate pending curation |
| Seven Siletti supercluster files | Homo sapiens | The same 4 in all seven files | X | Candidates pending curation |
| glioblastoma_brain.h5ad | Mus musculus | 10 | raw/X | Excluded from direct human transfer |

The smaller glioblastoma filename does not identify its species. Its internal
title is "Single-cell census of murine glioblastoma subtypes". The mouse atlas
has not been deleted; a future explicitly cross-species study would need its own
orthology mapping, scientific question and validation.

All 21 pairs of Siletti files overlap in donor IDs. Splitting by file would leak
donors between development and testing. Their four IDs are H18.30.001,
H18.30.002, H19.30.001 and H19.30.002. Different donor strings between collections
do not prove independence: source-backed alias and specimen checks remain needed.

Raw-layer candidates use the declared
[CELLxGENE 7.1.0 schema](https://github.com/chanzuckerberg/single-cell-curation/blob/main/schema/7.1.0/schema.md)
plus numeric consistency. For RNA count data this schema places raw counts in
raw.X, or X when a separate normalized matrix is absent. An AnnData object named
raw does not by itself establish counts. The audit checks at most 4,096 stored
values per matrix, not every entry, and neither schema metadata nor integer-like
values constitute curator approval or prove assay suitability.

The full feature spaces contain case-insensitive symbol collisions: 7 for
GBmap, 1,203 for each Siletti file and 9 for the mouse atlas. The selected Xenium
panel has no collisions among matched features in the eight human references.
Whole-transcriptome use still requires a curated stable-ID-to-symbol policy.

Source collections recovered from local metadata:

- [Siletti human brain collection](https://cellxgene.cziscience.com/collections/283d65eb-dd53-496d-adb7-7570c7caa443).
- [GBmap Core collection](https://cellxgene.cziscience.com/collections/999f2a15-3d7e-440b-96ae-2c806799c08c).
- [Mouse glioblastoma collection](https://cellxgene.cziscience.com/collections/6d7d23d0-237d-4430-9200-92858abba2d8).

Versioned dataset download URLs, citation strings and required evidence fields
are recorded in the local audit. Publication links were not used as evidence of
independent verification of each biological annotation or license.

## Implemented Behavior

1. **Explicit layer selection:** H5AD reads support X, raw.X and layers/name.
   raw.X uses raw/var, not potentially different X feature metadata. Missing
   layers, ambiguous semantics and fractional declared counts are refused.
2. **Donor-restricted reading:** donor membership is applied before reading
   annotation labels and before class-stratified row sampling. A selected donor
   must exist; an empty selection is an error. I/O failures cannot fall back to
   a reader that ignores the donor or layer selection.
3. **Panel projection:** both small and large H5AD files use bounded row reads
   when a panel is supplied. Zero overlap and selected symbol collisions fail
   closed. Measured shared features are recorded separately from detected genes.
4. **Identity and species:** streamed datasets preserve selected observation IDs,
   source row positions, donor IDs and declared species. Merged references use
   source-path namespaces and retain original IDs; duplicate input paths are
   refused. These namespaces are local, not portable biological identifiers.
5. **Curation audit:** source/schema metadata, layer samples, donor overlaps and
   missing curator evidence are recorded without manufacturing approval.
6. **Draft donor plans:** deterministic collection-wide donor assignments create
   internal train/validation/test proposals. They never claim to acquire an
   independent external Xenium donor or supply reviewed brain truth.
7. **CLI integration:** reference-assist accepts --expression-layer,
   --expression-semantics and repeatable --reference-donor selections. Predictions
   remain candidates and do not create approved expert labels.

The metadata audit reads label summaries across all donors. Consequently the
proposed test partition is **not a sealed, untouched benchmark**. The later
technical loading check reads training-donor expression and labels only. Formal
test custody, immutable snapshots and model locking remain separate steps.

## Real-Data Technical Results

| Check | Siletti | GBmap |
| --- | ---: | ---: |
| Files successfully loaded | 7/7 | 1/1 |
| Sampled training-donor cells | 448 (64 per file) | 64 |
| Shared measured Xenium features | 318/319 per file | 316/319 |
| Draft train/validation/test donors | 2/1/1 | 66/22/22 |
| Sum of per-file loading times | 13.099 s | 1.470 s |
| Training performed | No | No |
| Test accuracy measured | No | No |

These are single local smoke measurements, not peak-memory, full-atlas throughput,
annotation accuracy or biological validity metrics. The 64-cell samples are
class-stratified, not donor-balanced; not every allowed training donor appears.
No validation/test donor was loaded by these smoke checks. The full declared
Xenium biological panel has 319 features; historical 318-gene pilot outputs count
detected genes, not a different panel definition.

Artifacts are under `outputs/reference_readiness_20261003/`:

- `reference_audit.json`: nine source profiles and 21 donor-overlap pairs.
- `siletti_donor_plan.json` and `gbmap_donor_plan.json`: unapproved donor plans.
- `siletti_loading.json` and `gbmap_loading.json`: bounded loading measurements.
- `unit_tests.log`, `eval_legacy.json`, `eval_mvp.json`: software verification.
- `mouse_refusal/reference_assist_report.json`: real CLI refusal of the mouse
  reference for human transfer, without model fitting.

New regression coverage exercises layer/var pairing, donor-before-label selection,
source IDs, species, panel failures, symbol collisions, count semantics, no unsafe
I/O fallback and unapproved split status. Software verification is recorded in
the development log: 619/619 full-suite tests, followed by 19/19 focused tests
including two added safety cases; 16/16 and 13/13 routing cases; six import
contracts. The current inventory is 621 tests, not one full 621-test execution.
Passing tests does not measure biological accuracy.

## Commands

Run from the repository root; choose new output paths to preserve existing evidence.

```bash
.venv/bin/python scripts/prepare_reference_curation.py \
  --data data --audit --out outputs/reference_review_next/audit.json

.venv/bin/python scripts/plan_reference_donors.py \
  --audit outputs/reference_review_next/audit.json \
  --collection https://cellxgene.cziscience.com/collections/283d65eb-dd53-496d-adb7-7570c7caa443 \
  --out outputs/reference_review_next/siletti_donors.json

.venv/bin/python scripts/verify_reference_loading.py \
  --donor-plan outputs/reference_review_next/siletti_donors.json \
  --target-matrix /absolute/path/to/xenium/cell_feature_matrix.h5 \
  --max-records 64 --out outputs/reference_review_next/siletti_loading.json
```

These utilities produce readiness evidence, not approval. Do not remove blockers
by changing a status string or declaring a guessed expression semantic.

## Remaining Work in Order

1. **Finish P1 reference curation.** Confirm assay, layer/source version, donor
   aliases, tissue/condition, labeling method, license/allowed use and a
   specialist-approved ontology crosswalk. Keep normal lineage, malignant state
   and uncertainty separate. Owner redistribution clearance is recorded elsewhere;
   it does not replace source-level provenance. No human approvals are available.
2. **Finish P1 scalable identity/storage contracts.** Add portable source-version
   identities, cross-file observation checks, sparse-native assay storage and
   count-parity/peak-memory tests. Current bounded readers still create per-cell
   dictionaries; they are not a complete out-of-core analysis backend.
3. **Complete brain review and histology evidence.** Have real specialists review
   cell identity and anatomical ROIs, with registered images where required.
   Existing brain review gates remain blocked; no final labels were fabricated.
4. **Run a prespecified development benchmark.** Balance donor and class sampling,
   tune only on development data, report macro-F1, per-class recall, abstention
   coverage/risk and donor uncertainty. Atlas-label agreement is not independent
   Xenium biological truth. Four healthy donors cannot support strong population
   generalization merely because a three-way split is technically possible.
5. **Acquire and lock independent testing, then start P2.** Verify external donor
   identity and reviewed truth before a custodian-controlled evaluation. Add one
   demanded spatial RNA platform only after contract and workflow parity tests.

Still unresolved: cross-study donor aliases, true biological duplicates across
different source files, portable immutable identities, full-matrix validation,
expert crosswalks/labels/regions, independent external test truth and biological
claim-score calibration. No GitHub push or packaged-app rebuild was performed.
