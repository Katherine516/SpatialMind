# SpatialMind: Layer-by-Layer Review and Evaluation

Audit date: 2026-09-27. Source revision: `59a4703` on `spatialmind-studio`.

Follow-up: the findings below describe that audited revision. See the
[correctness release](correctness_release_20260927.md) for subsequent fixes and
their verification; this historical evaluation is retained unchanged in substance.

## Executive Assessment

SpatialMind is now a working local Xenium analysis and expert-review application, with real Scanpy/Squidpy execution, a desktop package, review workflows, reports, and considerably stronger tests. It is no longer just a collection of placeholder analysis functions.

It is **not yet a biologically validated autonomous analysis agent**. The principal release blockers are inconsistent enforcement between execution paths, misrepresented groupings in a figure, incomplete separation of reviewed and provisional labels, and a reliability score that is not actually bound to the individual claim being scored. Adding an LLM would not resolve these issues.

All 499 existing unit/integration tests passed. New adversarial probes nevertheless reproduced several important defects. Passing the existing suite therefore establishes regression coverage, not correctness of every scientific claim.

This audit added evaluation artifacts and this document only. It did not change application code, train a model, edit expert labels, or replace reviewed regions. Defects below remain open.

## Scope and Evidence

The review traced ingestion, scientific tools, gating, planning, execution, reporting, reliability, persistence, memory, and deployment through the current architecture. It combined source review, the complete existing test suite, new boundary-condition probes, real-section execution, and inspection of generated artifacts. It was not an exhaustive proof of every code path or a penetration test.

Fresh evidence is saved in `outputs/agent_audit_20260927/`:

| Evidence | Purpose |
| --- | --- |
| `audit_summary.json` | Environment, test counts, gate inventory, workflow measurements, archived-run metadata |
| `unit_tests.log` | Complete fresh 499-test run |
| `eval_legacy.json`, `eval_mvp.json` | Fresh routing and invariant evaluations |
| `audit_probes.py`, `audit_probes.json` | Reproducible gate, grouping, and statistical-scoring probes |
| `runtime_checks.py`, `runtime_checks.json` | Strict backend checks and two real-data sampled runs |
| `workflow/studio_evaluation.json` | Full healthy-brain descriptive run and synthetic-label machinery test |
| `packaged_app_smoke_retry.log` | Existing macOS bundle: 12/12 smoke checks |
| `import_contracts.log`, `doc_counts.log` | Architecture pass and documentation-check failure |

The full Janesick breast pilot under `outputs/janesick_full/` was inspected, not recomputed in this audit. Its JSON records creation on 2026-09-19. A new 5,000-input-cell breast sample was executed against the current source. The synthetic-label healthy-brain run measures software machinery only and must not be presented as biological validation.

## Findings, Ordered by Priority

### P1: Studio Execution Can Bypass the Review Gate

Sources: `spatialmind/app/server.py:673`, `spatialmind/app/server.py:226`, `spatialmind/app/planner.py:38`, `spatialmind/gatekeeper.py:115`.

The run endpoint checks only the requested tools. The worker subsequently expands dependencies and executes them without rechecking the gate or the actual expanded plan's preconditions. `marker_detection` is classified as ungated from its registry preconditions, but its default plan inserts the gated `annotation` step and groups markers by `cell_type`. Additionally, a cluster-group override returns from `requires_labels` before the unconditional annotation check.

Fresh probes against the unreviewed healthy-brain section:

| Request | HTTP status | Job accepted? | Expected safety behavior |
| --- | ---: | --- | --- |
| `annotation` | 409 | No | Correct refusal |
| `region_summary` | 409 | No | Correct refusal |
| `marker_detection`, defaults | 200 | Yes | Refuse the expanded cell-type plan |
| `annotation`, `group_key=cluster` | 200 | Yes | Still require reviewed labels; annotation does not become clustering |
| `cell_neighborhood_enrichment`, `group_key=leiden` | 200 | Yes | Resolve grouping consistently and validate dependencies |

The HTTP probes intercepted job submission to avoid unwanted execution. A separate direct invocation of the exact Studio worker then **actually completed** the default marker plan on 998 QC-retained healthy-brain cells with zero reviewed labels: clustering, annotation, and five cell-type marker groups, in 3.375 seconds. This is not merely a theoretical endpoint issue.

Recommended fix: resolve the complete plan and effective parameters first, normalize group modes, validate its actual inputs, and gate each executed step inside one shared executor. A cluster-marker plan should depend on clustering, not reviewed annotation. Enforce mandatory requirements before optional grouping exemptions.

Acceptance: every public entry point and direct worker call refuses unauthorized biological steps; valid cluster-only plans still run on unreviewed data.

### P1: Group Aliases and the Descriptive Figure Misrepresent the Analysis

Sources: `spatialmind/gatekeeper.py:32`, `spatialmind/tools/implementations.py:971`, `spatialmind/app/planner.py:216`, `spatialmind/app/plan_report.py:373`.

The gate recognizes `cluster`, `leiden`, `clusters`, and `leiden_cluster` as descriptive grouping modes. The analysis resolver recognizes only `cluster`; all other values silently use `record.cell_type`. The Studio descriptive recipe requests `leiden`.

All three alternative aliases resolved to cell-type names in a direct probe; only `cluster` returned the supplied cluster IDs. A request can therefore pass the descriptive exemption but calculate a different grouping.

There is a second, independent manifestation in rendering. Cluster assignments are stored in `dataset.metadata['cluster_assignments']`. The Studio figure renderer looks for per-record `metadata['cluster']`, then falls back to cell-type labels. Visual inspection of the fresh full-section figure confirmed a title and caption claiming unsupervised clusters but a legend containing six provisional cell-type categories. The actual analysis found nine clusters.

Affected example: `outputs/agent_audit_20260927/workflow/runs/eval_descriptive/spatial_map.png`. Do not reuse this figure as a cluster map.

Recommended fix: a single validated grouping resolver used by planning, gating, analysis, table export, and plotting. Reject unknown modes instead of silently falling back. Test the actual legend categories and per-cell group assignments, not just the image's existence or caption.

### P1: Statistical Reliability Is Not Claim-Specific

Source: `spatialmind/methods/reliability/scoring.py:126`.

The statistical component searches all reported pairs and gives every spatial claim the strongest pair's evidence. It does not bind the score to the claim's pair, direction, region, or evidence references. Taking the absolute z-score also means depletion can score as strong support for a claim of enrichment.

Fresh adversarial probes, with 100 declared tested pairs:

| Probe | Observed S | Interpretation |
| --- | ---: | --- |
| Target A-B has z=0 | 0.0000 | Correctly no statistical support |
| Same target, unrelated C-D has z=8 | 1.0000 | Unrelated evidence inflates the target claim |
| Target A-B has z=-8, claim says enrichment | 1.0000 | Direction is ignored |
| Raw `pvalue=0.01` | 0.6667 | Raw p is treated as adjusted; 100-test correction is skipped |
| Explicit adjusted p=0, no z | 0.0000 | Boolean `or` discards a valid zero and treats evidence as missing |

The pilot's present claim ledger mostly contains generic capability statements rather than explicit biological pair claims. That limits what its current scores mean; it does not make the scorer safe for the specific spatial claims the agent is intended to generate.

Recommended fix: typed claims carrying cell pair, region, graph, distance scale, direction, statistical family, test ID, and source artifact. Score only matching evidence. Distinguish raw and adjusted p-values explicitly, preserve zero values, and apply a direction-aware test appropriate to the claim. Report a score as an evidence index, not a probability, until independently calibrated.

Acceptance: unrelated evidence never changes a claim score; opposing-direction evidence cannot support an enrichment claim; p=0 and missing p are distinct; adjustment uses the declared test family.

### P1: Reviewed and Provisional Labels Are Mixed in Studio Biological Results

Sources: `spatialmind/app/server.py:250`, `spatialmind/tools/implementations.py:2454`, `spatialmind/pilot/xenium.py:1311`, `spatialmind/tools/implementations.py:1660`.

The canonical pilot supplies a reviewed-label list to neighborhood tools. Studio does not. Applying a partially complete reviewed table leaves provisional labels on unmatched cells; the tools then treat those labels as ordinary groups unless explicitly filtered.

Fresh published-breast sample: 5,000 input cells, 4,893 retained, 4,756 reviewed-label matches. Studio neighborhood enrichment analyzed all 4,893 cells, reported `reviewed_only=false`, and excluded zero unreviewed cells. Its pair table contained 330 rows. Marker detection used 24 groups rather than only the 19 published classes; the extra groups included provisional types and `Unannotated cell`.

Even the canonical pilot only lists neighborhood tools in `CELL_TYPE_GROUPED_TOOLS`; marker detection does not consume a reviewed-cell restriction. Filtering by label spelling is also weaker than a per-cell provenance mask when a provisional label shares a reviewed class name.

Recommended fix: carry per-cell label source, review status, ontology mapping, and decision ID into a common reviewed-cell mask. Apply it consistently to all validated annotations, markers, neighborhoods, regions, and figures; keep exploratory results separate and explicit. Report excluded counts and denominators.

Acceptance: published/reviewed analyses never silently include unreviewed cells; every output reconciles its analyzed population with the same provenance mask.

### P2: Studio Run Records Cannot Verify Their Generated Outputs or Be Replayed

Sources: `spatialmind/app/server.py:275`, `spatialmind/storage/replay.py:152`.

The worker writes its run record before tables, figures, and reports are generated. Both fresh sampled Studio runs had **zero artifact, figure, and table hashes**. Input verification succeeded, but automatic replay returned `blocked_replay_not_supported` for both records because replay supports the canonical validated pilot, not Studio plans.

Recommended fix: persist an immutable effective plan and input/review snapshot, then finalize the record after output generation with all output hashes, versions, seeds, and outcome status. Add a Studio-plan replay implementation. Record report/table generation failures as a partial result rather than a fully successful deliverable.

Acceptance: a clean replay reproduces declared outputs within numerical tolerances; modifying a recorded output fails verification; review-sidecar changes are detectable.

### P2: The Documentation Check Fails Solely Because the Date Advances

Sources: `scripts/check_doc_numbers.py:65`, `.github/workflows/checks.yml:76`.

The checker derives discovered test counts, then expects the documentation's verification date to equal `date.today()`. All counts matched in this audit, but `--check` exited 1 because September 21 was not September 27. This is wired into CI, so unchanged code can fail on a later day.

The `--write` path also generates wording that says tests and backends passed even though that command only counts discovered tests and cases. Discovery is not execution.

Recommended fix: compare stable counts independently of verification timestamps. Update pass/fail and verification dates only from actual completed test evidence.

## Measured Results by Layer

The architecture has six dependency tiers; the functional rows below give more useful scientific and operational detail. Test counts cited for specific classes are subsets of the 499 tests, not additional independent experiments.

| Layer | Measurement | Interpretation and remaining limitation |
| --- | --- | --- |
| Contracts and architecture | 6/6 import contracts passed; compile check passed | Dependency ordering is enforced. Scientific execution policy is still duplicated across Studio, pilot, and legacy paths. |
| Environment | `pip check`: no broken requirements; 4/4 strict backend checks passed | Existing local environment works. This was not a clean install or verification of the CI Python 3.11 environment. |
| Discovery and ingestion | 17 datasets discovered, 7 reviewable Xenium bundles; healthy index: 24,406 cells in 1.14 s | Existing processed Xenium bundles load. This is not an end-to-end FASTQ decoding or image-segmentation pipeline. H5AD/reference loading is exercised by the suite. |
| QC and clustering | Healthy: 24,362/24,406 retained (99.82%), 319 expression features, 9 clusters; silhouette 0.10334; modularity 0.76702 | Strong graph community structure but weak global cluster separation. Neither metric establishes cell-type accuracy. Cluster names must remain provisional. |
| Biological plausibility checks | 4/4 tests passed, including all 6 expected brain marker families and all 5 expected lymph-node marker families; technical-feature exclusion passed | Useful safeguards against contaminated expression and implausible clustering. These are marker-family recovery checks, not held-out annotation F1. |
| Routing and planning | Legacy 16/16; MVP 13/13; all 4 registry invariants passed; 12 plannable of 30 registered, 18 unavailable | Deterministic routing works on its fixtures. Every MVP case reports `visium_like` fixture modality; this does not validate 13 real Xenium/scATAC datasets or natural-language generalization. |
| Execution gate | Direct annotation/region controls refused; 3/3 adversarial requests accepted on a blocked section | A release blocker despite the passing regression suite. One bypass was also executed successfully. |
| Annotation and reference assist | Label-transfer tests 9/9; marker-audit tests 5/5; healthy and glioblastoma reviewed coverage both 0%; published breast full-input coverage 94.9% | Transfer and audit machinery work. There is no newly measured held-out annotation accuracy, macro-F1, or calibration. Coverage is not accuracy. |
| ROI and region summaries | Published breast has 19 composition-derived regions; full-input region coverage 97.7%; fresh sampled summary completed | These are useful exploratory spatial domains, not independently validated anatomical regions. Brain ROI review remains missing. |
| Gene-level statistics | Healthy: 296/319 genes met detection filter; 100 selected by analytic Moran's I and tested with 250 permutations; all 100 called significant, 50 displayed | Strong detected structure under the current procedure. The same statistic selects the tested subset; these numbers do not establish calibrated full-panel FDR or disease effects. |
| Spatial relationships | Fresh breast-sample Squidpy run completed with 19 permutations; archived full pilot includes neighborhoods, region-stratified tests, distance curves, point patterns, and graph robustness | The fresh sample is a computational check, not a definitive biological result. Its reviewed-cell scope is wrong. The expanded archived spatial analyses were not recomputed here. |
| Claim reliability | Target score changed from 0 to 1 after adding an unrelated pair; opposite-direction evidence also scored 1 | Current score is not safe as a per-claim confidence estimate. The four components describe evidence properties, not a validated truth probability. |
| Visualization and reports | Four fresh Studio runs generated HTML, Markdown, tables, and one PNG each; export tests 10/10 | Delivery works. Visual inspection found the incorrect descriptive map; successful file creation is insufficient QA. PDF paths are covered by existing tests, not a fresh full brain PDF render in this audit. |
| Storage and replay | Both sampled Studio records verify inputs but hash 0 generated outputs and reject automatic replay | Canonical pilot persistence is richer; Studio does not yet provide the same auditability. |
| Memory | Existing memory test 1/1 passed | Basic recall/storage works. No longitudinal learning, outcome-driven biological adaptation, or memory-isolation benchmark was demonstrated. |
| API and desktop | Existing macOS bundle 12/12 smoke checks; startup health in 3.7 s; source API medians 5.9-13.7 ms across four read endpoints | Usable local application. These are small-sample local timings, not concurrent-load benchmarks or a multi-user security certification. |
| CI and verification honesty | Unit suite 499/499 in 224.293 s; doc check failed with counts matching | Excellent increase in regression coverage, but the date-sensitive checker and missing adversarial cases must be corrected. |

### Full Healthy-Brain Descriptive Execution

- Raw section: 24,406 cells; 44 removed by QC; 24,362 analyzed.
- Expression features: 319, with technical controls excluded.
- Clustering: 25.70 s; spatially variable genes: 39.52 s.
- Outer worker timing: 78.87 s, including loading and report generation.
- Payload `wall_seconds`: 65.55 s. This starts after input loading and is captured before all final artifacts; it is not the full end-to-end wall time.
- Outputs: 24,362-row cells table and 246-row spatial-gene table. The latter includes both tested and screened-out rows, not 246 tested significant genes.
- Gate remained blocked for missing reviewed labels/regions, as expected for the descriptive workflow.
- HTML example: `outputs/agent_audit_20260927/workflow/runs/eval_descriptive/report.html`.
- Important: the current spatial map is mislabeled as clusters, as documented above. The example is audit evidence, not publication-ready output.

Clustering silhouette is measured in the implementation's expression representation; modularity is a graph measure. High modularity alongside low silhouette is possible. Do not tune these metrics upward without checking reproducibility, marker coherence, rare-population recovery, and segmentation/QC effects.

### Published Breast Evidence: What It Does and Does Not Establish

The fresh gate inventory confirms that `Xenium_Breast_Cancer_Rep1_Janesick2023` is the only one of seven reviewable local bundles passing the current gate.

Its stored full-section pilot analyzed 163,920 cells after excluding 3,860 of 167,780 input cells. The published label table supplies 19 classes; 159,168 retained cells matched it, giving 97.10% post-QC label coverage. It is wrong to describe the project as having no real annotated dataset at all.

However:

- The 19 regions identify their author as `composition-derived, not a pathologist call`. Their composition summaries partly restate how they were defined.
- `validated_ready` currently means the configured input gate passed, not that cell labels, ROIs, or every scientific conclusion have been independently validated.
- The archived claim score is 0.7568: S=1, A=0.9710, P=0.7568, R=1. The limiting panel component measures 28/37 canonical markers. It is not a 75.68% probability of biological correctness.
- Annotation here reuses published labels. Evaluating those same applied labels against their own source would be circular. A prediction benchmark must withhold evaluation labels from the prediction pipeline.
- The fresh breast sample completed five tools in 41.399 s, with 4,893 retained cells, 436 detected expression features, and 19 region summaries. It demonstrates current-source execution, but not full-section biological inference.
- Seven of 26 mixed label categories triggered marker-conflict flags in that sample. Eleven of the 19 published classes were not recognized by the coarse lineage-name mapper. These flags and abstentions are review aids, not measured error rates; underscore-form names, hybrid categories, and mixed stromal populations need curated interpretation.

### Reliability and Statistical Interpretation

The recent changes improve honesty by separating reviewer confidence from coverage, recording reviewers, excluding technical controls, reporting assay limits, and exposing measured graph perturbation results. These are worthwhile changes.

Remaining distinctions must stay explicit:

- A is reviewed-label **coverage**, not annotation accuracy or independent review depth. Per-cell source rows need not equal independent expert decisions.
- P is a canonical-marker coverage heuristic. The relevant markers and denominator should belong to the specific claim and tissue, not just the union of all labels in a run.
- R is graph-parameter stability. A stable wrong label or confounded association can still have R=1. Sample selection, spatial blocks, segmentation, and biological replication test different failure modes.
- S is statistical evidence under a particular null, not biological causality. Current pair binding, direction, and p-value handling require correction before calibration.
- The cited synthetic-control AUROC near 0.98 is historical simulation discrimination, not a fresh held-out biological validation result from this audit.
- Spatial-gene screening selects top Moran statistics before applying BH to the smaller tested set. The whole selection-and-testing pipeline needs null controls; reporting the screen does not itself establish nominal false-discovery control.
- Region definitions derived from the same spatial cell-type patterns should not receive an unconditional assurance that within-region inference is unaffected. Evaluate the entire region-selection procedure under nulls or use independently defined morphology ROIs.
- No donor-level healthy-versus-glioblastoma differential biology should be inferred from one section per condition, even with many cells.

## What Claude's Changes Improved

1. Six explicit dependency tiers, enforced through import contracts.
2. A common gatekeeper, broader entry-point checks, and stricter assay/capability refusals.
3. Real scientific backends, control-feature filtering, QC preservation, cluster diagnostics, and biological-plausibility regression tests.
4. A functional Studio/desktop workflow for discovery, review, planning, jobs, and report delivery.
5. Reviewer attribution, label-marker disagreement reporting, and warnings about composition-derived regions.
6. A real published-label breast dataset and full-section pilot, materially stronger evidence than synthetic demonstrations alone.
7. More reproducible environment/package checks and a substantially broader test suite.

The remaining defects are mainly failures to carry these policies consistently into every consumer, not a reason to discard the architecture or rewrite the project.

## Recommended Next Steps

### 1. Correct Execution and Reporting Before Expanding Capabilities

Implement one effective-plan executor shared by Studio and the canonical pilot. It should normalize groupings, enforce gate/preconditions after dependency expansion, apply per-cell review masks, retain strict backend semantics, and record the exact effective inputs. Use that same grouping object for figures and exports.

Turn every reproduced audit probe into a committed regression test. Include a fixture where reviewed and provisional cells share the same class name, a partial-review section, every grouping alias, a direct worker call, and an actual figure-label assertion.

Exit criteria: no reviewed/provisional mixing in validated outputs, no gate bypass, and figures/tables agree with execution. No additional dataset or LLM API is needed for this work.

### 2. Make Reliability Genuinely Claim-Level

Introduce typed claims and evidence identifiers, then repair statistical direction, p-value handling, claim-specific annotation/panel adequacy, and pair/region-specific robustness. Retain an interpretable evidence score while probability calibration is unavailable.

Evaluate null and positive controls through the full analysis pipeline, including gene screening, region selection, graph construction, pair selection, and score generation. Report false-positive behavior, sensitivity, and uncertainty across repeated seeds. Do not tune thresholds on the final evaluation set.

Exit criteria: evidence-isolation probes pass; the full-pipeline null behaves as specified; unsupported claims remain unsupported even when unrelated strong findings are present.

### 3. Establish an Independent Biological Benchmark

Use the published breast dataset immediately, but separate reference/prediction inputs from frozen evaluation labels. Start with broad cell classes whose ontology mapping and marker evidence are defensible. Report macro-F1, balanced accuracy, per-class precision/recall, abstention coverage, and performance on rare populations. Report cluster stability and ARI/NMI against withheld labels without treating expression clusters as exact cell types.

Spatial-block holdout within a section is useful for development; it is not a substitute for independent sections and donors. Reserve a donor/section-disjoint test cohort before tuning. Acquire or curate brain-specific expert labels and independently reviewed anatomy ROIs for healthy brain and glioblastoma. Retain reviewer identity, uncertainty, source, and adjudication records.

Exit criteria: predictions are scored against labels they never consumed; the benchmark reports uncertainty and its unit of independence; anatomical validation is not inferred from composition-defined regions.

### 4. Close Reproducibility and Delivery Gaps

Finalize run manifests after artifacts exist; hash reports, tables, plots, input bundles, and review sidecars. Implement Studio-plan replay. Distinguish analysis completion from report-generation failure. Fix the date-sensitive documentation check and derive verification claims from actual completed runs.

Run clean-install checks for the supported Python versions and rebuild the desktop app from an identified source commit. The present environment and existing bundle passed, but that does not prove every dependency resolution will work.

### 5. Add a Constrained LLM Only After the Above

The current Studio router is deterministic. Provider adapters exist, but the hosted-LLM planner is connected to the legacy three-tool path, not the complete Studio workflow. No live-provider evaluation was performed in this audit.

An LLM should translate a user's question into a constrained intent, ask clarifications, and explain already-computed evidence. It must not set review status, invent biological labels, override execution gates, or assign statistical confidence. Evaluate tool selection, parameter validity, unsupported-request refusal, evidence citation, and robustness to misleading dataset text before enabling autonomous use.

## What We Still Need

| Need | Available now? | How to proceed |
| --- | --- | --- |
| Data for fixing execution, grouping, reports, replay | Yes | Existing brain and published-breast data plus small fixtures are sufficient. |
| Real labels for an initial annotation benchmark | Yes, published breast | Freeze provenance and splits; withhold test labels from annotation inputs. |
| Final healthy-brain and glioblastoma expert cell labels | No applied reviewed tables in fresh gate checks | Arrange specialist review of marker evidence, morphology, and cluster worksheets; use ontology terms to standardize identities, not to assign cells automatically. |
| Independent anatomical ROI truth | Not established by current composition-derived regions | Pathologist/neuroanatomist review on registered tissue imagery; preserve uncertain/unassigned areas and reviewer provenance. |
| Tissue-matched references and independent donors | Not validated by this audit | Curate human reference labels with compatible tissue, disease, species, and panel overlap; reserve independent donors/sections for testing. |
| Reviewed claim truth for reliability calibration | No held-out biological calibration demonstrated | Review explicit pair/region/direction claims independently; keep calibration and final evaluation donors separate. |
| Consent/license/PHI assurance for new wet-lab data | Must be supplied for each new dataset | Require a provenance/governance manifest from the data provider; do not infer consent or absence of identifiers from file format. |
| Hosted LLM | Not needed for immediate fixes | Add later behind the constrained planner boundary and evaluate it separately. |
| Multi-user production controls | Not certified by local tests | Before deployment, test authentication, authorization, dataset isolation, durable jobs, audit retention, resource limits, backup/restore, and concurrent load. |

**Best immediate move:** a focused correctness release addressing execution gating, grouping/figure consistency, reviewed-cell scope, and claim-to-evidence binding. Then use the published breast labels for an honest held-out benchmark while expert brain review proceeds in parallel. Expanding the tool list or fine-tuning a language model is lower priority.

## Reproduction and Limits

Commands used included:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/lint-imports
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q spatialmind eval tests scripts
.venv/bin/python -m eval.runner --out outputs/agent_audit_20260927/eval_legacy.json
.venv/bin/python -m eval.runner --mvp --out outputs/agent_audit_20260927/eval_mvp.json
.venv/bin/python scripts/evaluate_studio_workflow.py --out outputs/agent_audit_20260927/workflow
.venv/bin/python outputs/agent_audit_20260927/audit_probes.py
.venv/bin/python outputs/agent_audit_20260927/runtime_checks.py
.venv/bin/python scripts/check_doc_numbers.py --check
```

The existing macOS app was smoke-tested on a dynamically selected free port. An initial attempt on port 18791 encountered an existing listener; the retry passed 12/12. No existing server was stopped. The test creates and removes its own temporary synthetic section.

Local environment: macOS 15.7.9, x86_64, Python 3.9.7, NumPy 1.26.4, SciPy 1.13.1, Scanpy 1.10.3, Squidpy 1.6.1, AnnData 0.10.8, Numba 0.60.0, FastAPI 0.128.8, Matplotlib 3.9.4. Tests/runs shared a workstation; these timings are descriptive measurements, not controlled performance benchmarks.

Not established here: annotation accuracy on independent donors, calibrated biological claim probability, clinical validity, raw imaging/FASTQ reconstruction, production multi-user readiness, fresh full-section Janesick extended-spatial rerun, live LLM behavior, or exhaustive reference-dataset curation. No application-code fixes were applied during this review.
