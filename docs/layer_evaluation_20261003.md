# SpatialMind Layer Evaluation: 2026-10-03

Historical baseline review. The subsequent [correctness upgrade](correctness_upgrade_20261003.md)
addresses F1-F8 and records new evidence. Measurements below describe the
pre-upgrade source commit, not the current repaired checkout.

## Decision Summary

SpatialMind is a functional, local, review-gated Xenium research assistant with
real Scanpy/Squidpy execution, reports, review tooling and provenance. It is not
yet an independently validated brain annotation system or a general multimodal
spatial omics agent. Adding an LLM API alone would not change that conclusion.

The existing suite passes **586/586**, but targeted review found correctness gaps
not covered by that suite. Prioritize statistical validity, coordinate/assay
semantics and complete result export before adding new assays. Obtain human
review and independent biological evidence in parallel.

The [modality expansion roadmap](multimodal_roadmap_20261003.md) specifies priorities,
required data, dependencies and acceptance criteria. This review changes no
scientific implementation, raw data, reviewed labels or model parameters.

## Scope and Evidence

- Source baseline: `2d0a00acc2d4bc0c5119a0e85cc9584301cf514c`.
- Reviewed the six architectural tiers, their active entry points and scientific,
  review, reliability, storage and delivery boundaries. Import analysis covers
  118 files and 288 dependencies. This is not a claim of exhaustive line coverage.
- Fresh verification: complete unit/integration suite, both routing suites,
  import contracts, dependency consistency, compilation and documentation counts.
- Fresh real-data work: five Xenium readiness scans; sampled healthy-brain and
  glioblastoma end-to-end reports; clustering seed sensitivity; read-only
  metadata inspection of nine H5AD references.
- Additional audit: nine synthetic boundary checks, eight finding observations
  and one passing invariant. Several observations concern the same root cause;
  this is a deliberately adversarial sample, not an overall failure-rate estimate.
- No hosted LLM calls, model training, external-donor rescoring or human decisions.
- No new full-section inference, native-app rebuild, browser interaction test,
  PDF visual inspection, distributed-service load test or code coverage percentage.

Local evidence is under `outputs/layer_evaluation_20261003/`. Start with
`evaluation_summary.json`, `cluster_stability.json`, `modality_boundary_audit.json`,
`local_data_inventory.json`, `brain_review_readiness.json` and the command logs.
Outputs are intentionally excluded from Git; this document retains the principal
measurements, and the audit script is tracked for reproduction.

## Findings

Severity P1 means scientific correctness should be addressed before promoting the
affected workflow. P2 means a narrower integrity or capability-reporting defect.
Roadmap priority P0 means the next implementation increment, not a severity label.

### F1: P1 - Spatial gene screening does not establish the reported FDR

In [implementations.py](../spatialmind/tools/implementations.py#L2248), genes are
ranked by analytic Moran's I on the same cells/graph and the strongest candidates
are selected. At line 2360, permutation tests and BH correction then operate on
only that selected subset. This selection is dependent on the tested statistic;
ordinary selected-set BH does not account for that selection. Calling the results
"conditional" in a caveat does not implement selective inference.

Both fresh reports select 50 genes from 309 and 298 detection-eligible genes,
respectively, and report 50 passing the tool's threshold. These are observed
software outputs, **not a verified 5% FDR result**. This review did not estimate
the numerical inflation rate or establish that any particular gene is false.

Recommended correction: retain a prespecified, coordinate-independent detection
filter, test all eligible genes, and correct the complete family. Alternatively,
use independent screening data or a properly selection-aware procedure. Keep
display top-N separate from the inferential family. Evaluate null rejection
rates with prespecified repeated simulations and spatial nulls. The relevant
independent-filtering principle is described by
[Bourgon et al., PNAS](https://pmc.ncbi.nlm.nih.gov/articles/PMC2906865/).

### F2: P1 - Nonspatial coordinates pass spatial execution checks

[registry.py:226](../spatialmind/tools/registry.py#L226) only checks whether both
coordinate ranges are zero. The scRNA loader deliberately uses varying index
positions when tissue coordinates are unavailable. These therefore pass the
"spatial coords" precondition. The AnnData bridge also writes those positions
into `obsm['spatial']` unconditionally.

Reproduction: a 40-cell scRNA fixture with `coordinate_system=embedding_or_index`
passed preconditions and executed real Squidpy Moran analysis through
`agent.runtime.execute_tool_step`. Its results described tissue-space statistics
on an arbitrary ordering. No significant genes were needed to establish the bug.

Require typed coordinate provenance, physical units and a spatial-observation
flag. Reject index, PCA, UMAP and t-SNE coordinates for tissue statistics; permit
them only for explicitly named embedding visualizations. Do not infer spatial
validity from coordinate variation or a filename.

### F3: P1 - Ordinary H5AD ingestion truncates source expression before analysis

[pipeline.py:269](../spatialmind/ingestion/pipeline.py#L269) defaults to 200
features per record. [_matrix_row_to_features](../spatialmind/ingestion/pipeline.py#L1236)
keeps each row's largest values before constructing both `genes` and `raw_genes`.
Subsequent normalization therefore uses an incomplete library; missing values
are later interpreted as zero. This is not dataset-level HVG selection.

A 301-gene count fixture became 200 genes. Its source row sum changed from
45,451 to 40,300; normalized G300 changed from 4.20805 to 4.32664.
`max_features_per_record=0` preserved all 301. The separate large-reference
streaming path does not apply this same default, so behavior can depend on file
size and entry point. The current Xenium-specific loader already requests the
full panel; these brain pilots are not evidence that generic H5AD is safe.

Preserve a sparse source matrix and its measured feature universe. Apply an
explicit shared feature selection after count-aware QC. Make previews an
independent presentation object, never the scientific source layer.

### F4: P1 - Protein tables inherit RNA preprocessing and an RNA contract

[pipeline.py:260](../spatialmind/ingestion/pipeline.py#L260) normalizes every
accepted table using library-size scaling and log1p, including
`multiplex_imaging_csv`. [contract.py:11](../spatialmind/ingestion/contract.py#L11)
then identifies a protein dataset as transcriptomics/scRNA/gene counts.

An explicit protein fixture with CD3/CD20 intensities 100/200 was transformed to
8.11203/8.80503 and received that RNA contract. Protein tools being unavailable
does not protect the shared preprocessing stage. This blocks advertising general
CODEX/IMC support beyond raw table intake.

Require assay-specific measurement semantics and transformations. Preserve
intensities, antibody/channel identities and background controls; apply a
validated intensity transformation only when explicitly configured. Unknown
modalities must not default to human RNA or Xenium.

### F5: P2 - Export omits 35 tested spatial genes in each fresh brain report

[implementations.py:2377](../spatialmind/tools/implementations.py#L2377) serializes
only `ranked.head(n_top)`. The descriptive pilot requests `n_top=15` but tests 50,
then calls those 15 rows `all_tested_genes` at
[xenium.py:1104](../spatialmind/pilot/xenium.py#L1104).
[tables.py](../spatialmind/viz/tables.py#L153) cannot recover the discarded rows.

Glioblastoma exported 274 rows for 309 eligible genes; healthy brain exported
263 for 298. Both omit exactly 35 actually tested genes, including their p-values.
Retain a complete per-gene result artifact and derive display tables from it.
Assert that each eligible feature has a tested or explicitly excluded status.

### F6: P2 - A tiny expression subset reintroduces technical features

[schemas.py:119](../spatialmind/schemas.py#L119) returns all features if fewer than
two biological genes remain, to accommodate small fixtures. A one-gene fixture
therefore includes `NegControlProbe_1` and `TOTAL_COUNTS` in its expression feature
list. This is a real data path for small panels or sparse ROIs, not just a test
convenience. Always exclude technical features and return an explicit
insufficient-features result when a method needs more genes.

### F7: P2 - Incomplete provenance can still be called verified

[replay.py:125](../spatialmind/storage/replay.py#L125) warns and skips an artifact
with a stored hash but no path. If another file verifies, the aggregate status is
still `verified`. The audit reproduced this with one valid table and one
unresolvable artifact. Require complete verification or return a distinct
partial/unverifiable status. The two actual new reports each pass 17 checks with
no warnings; this finding concerns the damaged/incomplete-record boundary.

### F8: P2 - Fusion scaffold emits apparently measured quality values

[fuser.py:42](../spatialmind/tools/fusion/fuser.py#L42) reports the first dataset's
cell count as shared cells and returns quality 1.0 for recognized modality pairs
without alignment. Disjoint fixtures of 40 and 1 cells produced 40 shared cells
and quality 1.0. A scaffold warning is present, and this is not evidence that the
active Xenium pilot performs fusion. Nonetheless, future callers could consume
the numeric fields as measurements. Return unavailable/null metrics until a real
matching or registration method computes them.

## Layer Assessment

These are readiness judgments, not arbitrary numerical grades. Architectural
tiers and functional layers are separated because a tier contains several
different capabilities.

| Tier / functional layer | Current evidence | Assessment and remaining work |
| --- | --- | --- |
| 1. Contracts and schemas | Typed plans, results, claims and review decisions; import rules pass | Useful boundaries, but coordinate kind, spot/bin resolution, measurement semantics and modality dispatch need strengthening; F2/F4/F6. |
| 2. Ingestion | All five local Xenium bundles ingest in bounded readiness runs; nine H5AD metadata inspections | Xenium is the strongest adapter. Generic H5AD needs F3 fixed. Visium/SpatialData readers remain stubs; transcript-level Xenium processing is absent. |
| 2. QC and preprocessing | Fresh brain QC removes 5/1,500 and 3/1,500 cells; full-panel real-data technical-feature checks pass | Good source-count preservation on the tested Xenium path. Separate RNA, protein and ATAC preprocessing; retain feature masks and segmentation QC. |
| 2. Clustering | Real PCA/neighbors/Leiden; diagnostics and three-seed checks below | Descriptive clustering works. Seed consistency is not cell-type accuracy; assess resolution, subsampling, batch and segmentation sensitivity next. |
| 2. Annotation/reference transfer | kNN transfer, abstention, training-prior option, species/lineage checks; historical breast holdout exists | Assisted annotation only. No reviewed brain accuracy, external-donor result or calibrated vote probability. Reference files require verified expression semantics. |
| 2. Scientific tools | 30 registered; 12 plannable; 18 unavailable and excluded from model schemas | Real marker/neighborhood/Moran methods work; F1/F5 affect rigorous gene inference/export. LR, CNV, pathways, deconvolution, true ATAC/protein and fusion are not completed capabilities. |
| 2. Storage/replay | Both new records verify 17/17 files; SQLite index and replay CLI exist | Useful local audit trail; F7 remains. Hash verification is not bitwise rerun equivalence or tamper-proof signing. Pin complete scientific inputs and portable paths. |
| 2. Memory and LLM providers | Local JSON/keyword memory; provider adapters; deterministic routing tests | Memory is not biological learning. No live-provider accuracy, latency, cost or prompt-injection evaluation in this audit; keep tool authorization outside the model. |
| 3. Validation gate | All five bundles correctly remain blocked under current evidence; explicit review provenance enforced | A good Xenium safeguard. Non-Xenium runs can be `gate_not_evaluated`; this is permission with a caveat, not validation. Replace asset-specific gate assumptions with assay-aware evidence requirements. |
| 4. Spatial methods | Real cluster neighborhoods, global/local Moran, region proposals; region/co-occurrence code and tests exist | Reviewed-cell region tests cannot be evaluated biologically on these brain data. Distance curves are descriptive, not signaling tests; add prespecified null families and donor-level replication. |
| 4. Claim reliability | Pair/direction/scope binding, measured kNN sweeps, weakest-link index; no reviewed calibration truth | Structurally improved but uncalibrated. Annotation coverage is not accuracy; panel marker coverage is a heuristic. Do not report the score as probability of truth. |
| 4. Visualization/reporting | Two fresh HTML reports, five image references each, five TSVs each, no missing image paths | PNG cluster maps inspected and readable. F5 limits report completeness. Browser `file:` access was blocked by tool policy; no browser-layout claim is made. |
| 4. Governance | Dataset/provenance manifests and external-donor/image evidence validators | Owner redistribution clearance is recorded, but it does not authenticate reviewers or establish donor independence. Maintain per-dataset provenance and allowed use. |
| 5. Planning and execution | Legacy 16/16; MVP 13/13; registry invariants 4/4 in each; canonical runtime for supported agent/Studio calls | Good deterministic routing coverage, not open-ended agent intelligence. Some pilot descriptive calls still invoke registry tools directly with strict parameters; broader policy unification remains work. |
| 6. Studio, CLI and API | 77 Studio tests, 14 API tests; HTML/PDF code paths covered in suite | Usable as a trusted local workstation. Jobs and memory are process-local; multi-user authentication, authorization, durable workers and concurrent-review transactions are not established. |
| 6. Expert review, training and evaluation | Two 750-cell packets; provenance-checked staging and model-lock/external-test machinery | Both packets have zero accepted labels/regions. No specialists, matched reviewed H&E/IHC or sealed acquired external donor. Training code exists; biological training readiness does not. |
| 6. Packaging and delivery | Existing local environment consistent; full suite passes on this checkout | No new app build or clean-machine installation was performed. Dependencies remain only partly pinned; a passing installed environment is not a reproducible lockfile. |

## Fresh Measurements

### Software Verification

| Check | Result | Interpretation |
| --- | --- | --- |
| Unit/integration suite | 586 passed, 0 failed, 0 skipped; 220.823 s | Current tested mechanics pass, including real-data plausibility checks. |
| Legacy routing | 16/16; mean score 1.0 | Fixed query cases select expected tools. |
| MVP routing | 13/13; mean score 1.0 | Includes refusal and deferred-workflow cases, not true ATAC/Visium data validation. |
| Registry invariants | 4/4 in each routing evaluation | No unavailable tools exposed as plannable. |
| Import contracts | 6/6 | Architecture dependencies obey configured rules. |
| Dependency consistency | No broken requirements | Installed distribution requirements agree; binary/biological validity is separate. |
| Compile/documentation counts | Pass | Syntax and documented inventory agree. |
| Targeted boundary audit | 8 findings / 9 checks | Purposefully selected gaps outside the passing suite. |

Suite breakdown: core `test_spatialmind` 405, Studio 77, correctness boundary 31,
annotation holdout 18, validation safety 15, API 14, brain readiness 13, reviewed
validation 9, biological plausibility 4. These modules span multiple layers and
must not be treated as independent per-layer accuracy estimates.

Environment: Python 3.9.7, NumPy 1.26.4, SciPy 1.13.1, Scanpy 1.10.3,
Squidpy 1.6.1, AnnData 0.10.8, h5py 3.14.0, pandas 2.3.3,
FastAPI 0.128.8 and ReportLab 4.2.5. The complete installed package snapshot is
saved in `environment_freeze.txt`; it is evidence, not a new installation lock.

### Real Brain Report Runs

Both runs requested 1,500 evenly indexed cells, full measured panel, resolution
0.55, seed 0, six spatial neighbors and 100 permutations in the descriptive
lane. Review templates were capped at 200 rows to keep this evaluation bounded;
they are not a full-section annotation deliverable.

| Metric | Glioblastoma | Healthy brain |
| --- | ---: | ---: |
| Original section cells | 40,887 | 24,406 |
| Requested sample fraction, before QC | 3.6686% | 6.1460% |
| Cells after QC | 1,495 | 1,497 |
| Sample QC retention | 99.6667% | 99.8000% |
| Biological genes detected in loaded data | 318 | 318 |
| Expression clusters at seed 0 | 9 | 8 |
| Silhouette | 0.14060 | 0.08926 |
| Graph modularity | 0.74032 | 0.71581 |
| Median source counts per cell | 214 | 165 |
| Median detected genes per cell | 71 | 68 |
| Cells in clusters meeting population-size heuristic | 88.7% | 84.1% |
| Description-stage wall time | 26.74 s | 36.31 s |
| Whole CLI process wall time | 33.71 s | 43.20 s |
| Process peak RSS | 613,748,736 bytes | 488,599,552 bytes |
| Exported result tables | 5 | 5 |
| Path-backed provenance checks | 17/17 | 17/17 |
| Accepted labels / regions | 0 / 0 | 0 / 0 |
| Validated biological claims permitted | No | No |

Low positive silhouettes indicate substantial overlap in the clustering
representation; high modularity only describes the expression graph partition.
Neither establishes cell identities. Cluster IDs are arbitrary and cannot be
matched between sections by number. Timing is a single local measurement with
import/cache effects, not a throughput benchmark or an estimate for full data.

The same sampled cells were clustered at seeds 0, 1 and 2 without selecting a
winner. Glioblastoma yielded 9/10/9 clusters and pairwise ARI 0.9491-0.9646;
healthy brain yielded 8/8/8 and ARI 0.9702-0.9852. This supports limited
random-seed stability, **not agreement with truth**, robustness to sampling, or
generalization across donors.

Reports:

- [Glioblastoma example](../outputs/layer_evaluation_20261003/glioblastoma/validated_xenium_pilot_report.html)
- [Healthy brain example](../outputs/layer_evaluation_20261003/healthy_brain/validated_xenium_pilot_report.html)

Both status fields are `blocked_missing_validation_inputs`. Clustering, cluster
markers, descriptive cluster neighborhoods, gene rankings and candidate regions
are available. Validated named-cell neighborhoods, anatomical summaries and
healthy-versus-GBM biological comparison are not unlocked. Treat spatial-gene
significance wording as provisional pending F1, and TSV completeness as limited
by F5. The plots display expression clusters, not expert-assigned cell types.

### Ingestion and Biological Evidence

All five local Xenium bundles completed 500-cell readiness requests in a combined
18.08 s. Post-QC loaded counts were 478 (breast biomarkers), 490 (Janesick breast),
498 (GBM), 500 (healthy brain), and 488 (lymph). All five were blocked. The Janesick
tables exist but are `blocked_unapproved_labels` / `blocked_unapproved_regions`
under the current recorded-review contract; the other four lack final tables.
Do not loosen the validator to reuse older annotation evidence as new approval.

Nine local H5AD files contain 9,932-490,246 observations and 27,632-58,232 features.
Their inspected `obsm` keys are embeddings, not tissue coordinates. All use CSR X;
none has a named `counts`/`raw_counts` layer or `uns/log1p` in this inspection.
This does not prove X is raw or normalized, nor rule out useful data in `.raw`.
Confirm source preprocessing and choose a documented expression layer/semantics;
do not guess from extension or nonnegative values. GBmap Core has 338,564 cells
and 17 declared label categories; the smaller GBM reference has 94,181 cells and
29. Single-supercluster files are not complete annotation references alone.

The pre-existing breast benchmark remains historical evidence only: 3,110 test
cells, accuracy 0.8071, macro-F1 0.6208, balanced accuracy 0.5700, coverage 0.7653,
selective accuracy 0.8861. It is an internal spatial holdout within one breast
section, not a brain benchmark or independent donor test. This audit read the
saved summary, did not open truth CSVs, and did not rescore or tune on the test.

Both specialist packets contain 750 cells and zero accepted labels, regions or
joint decisions. The claim-truth draft contains 11 rows, zero reviewed rows and
zero usable calibration rows. Fresh donor-heldout calibration evaluation returns
`blocked`, `test_scored=false`; therefore brain annotation F1, external AUROC,
biological claim Brier score and ECE are **unavailable**, not zero.

The current biological annotation claim scores 0 because review evidence is
missing. The separate non-biological readiness claim scores 0.5312. It must not
be described as 53.12% biological accuracy. S/R values marked not-applicable are
not measurements of perfect statistical evidence or robustness.

## Reproduction and Follow-Through

Run from the repository root in the existing verified environment:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/lint-imports
.venv/bin/python -m eval.runner --out outputs/recheck/eval_legacy.json
.venv/bin/python -m eval.runner --mvp --out outputs/recheck/eval_mvp.json
.venv/bin/python -m pip check
.venv/bin/python scripts/check_doc_numbers.py --check
.venv/bin/python scripts/audit_modality_boundaries.py --out outputs/recheck
.venv/bin/python scripts/manage_brain_specialist_review.py readiness --packet outputs/brain_specialist_handoff_20260927
```

The audit intentionally exits 1 when it reproduces unresolved findings. It is
not added as a passing CI test. Promote each case into a focused regression test
when its production correction lands.

For either brain bundle, the report command is:

```bash
.venv/bin/python scripts/run_validated_xenium_pilot.py \
  --data 'data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs' \
  --out outputs/recheck/glioblastoma --max-records 1500 \
  --review-max-records 200 --report-format html
```

Best next increment: resolve F1/F2/F3/F5, add the boundary regressions, preserve
complete sparse source data and results, then rerun this evaluation. Arrange
specialist review in parallel; do not make software progress depend on inventing
missing biological evidence.
