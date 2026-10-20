# SpatialMind Agent Review and Workflow Evaluation

Follow-up: the actionable reliability findings below were subsequently repaired.
See [implementation and re-evaluation](reliability_repairs_20261012.md). This
document preserves the original review measurements and findings rather than
rewriting them as results from the repaired source.

Review date: **2026-10-12, America/New_York**. Reviewed source:
`8c9b99612d63303634c6d3f1094713bd04976d9c` on `spatialmind-studio`.
The working tree was clean when evaluation began. Production code and input
datasets were not changed during this review.

SpatialMind can run a substantial, reproducible-looking exploratory Xenium
workflow and deliver useful reports. The current automated checks pass, and
missing brain review evidence correctly blocks biological interpretation.
However, six remaining correctness and delivery issues need attention before
calling it a validated research agent. Passing software tests is not a measure
of cell-label accuracy or biological claim calibration.

## Findings

### F1 / P1: Pilot provenance can verify the wrong input revision

Location: [pilot run-record creation](../spatialmind/pilot/xenium.py#L506).

The canonical pilot first loads and analyzes data, then computes its input
hashes when writing the final record. A controlled probe modified a synthetic
matrix count from 12 to 1012 after ingestion. The resulting record matched the
modified file, did not match the file ingested, and still returned `verified`.
This is a reproducibility failure if a collaborator edits inputs during analysis.
No real dataset was altered by the probe.

There is also incomplete artifact coverage: both real runs recorded zero entries
in `tool_trace`, despite executing four descriptive tools. Their cluster maps
and marker heatmaps are absent from `figure_md5`. The 18 successful hash checks
per run therefore verify only the artifacts actually listed, not every output.

Recommended repair: snapshot/hash inputs before loading, compare at completion,
fail or mark the run invalid when inputs change, and record descriptive tool
calls, effective parameters, figures and intermediate results. Use an immutable
input snapshot for replay. Add mutation and omitted-artifact regression tests.

### F2 / P1: A blocked Studio plan can be described as validated

Location: [plan report lane selection](../spatialmind/app/plan_report.py#L27).

`lane_for_payload` uses `expert_labels_applied` without checking coverage, gate
status or the grouping of the tools actually executed. A probe with one reviewed
cell out of 100, missing regions and a blocked gate produced a `validated` report
introduction claiming that groups were named cell types. Its only requested tool
was expression clustering. Execution remains gated, but the report contradicts
that protection.

Recommended repair: derive wording from the gate and each result's actual
grouping/review scope. A cluster analysis remains descriptive even when some
reviewed labels exist. Test partial coverage, cluster-only plans and mixed plans.

### F3 / P2: Hotspot inference does not implement its stated conditional null

Location: [local Moran randomization](../spatialmind/tools/spatial_statistics.py#L497).

The implementation holds the focal multiplier fixed but shuffles the entire
expression vector into the neighboring positions. This allows the focal value
back into its own null neighborhood. True conditional randomization excludes
that value from the sampling pool. The resulting null mean and variance differ,
particularly for small regions or influential observations.

For a centered vector `[-2, -1, 0, 1, 2]`, a non-isolated row-standardized graph
has conditional expected local statistics `[-1, -0.25, 0, -0.25, -1]`; the current
full-vector shuffle has expectation zero. The report nevertheless names the
method `local_morans_i_conditional_permutation`.

An exploratory all-null check found at least one rejection in 5/90 gene families
across 30 seeds, using 100 cells and 199 permutations. This small, dependent set
of gene families neither demonstrates inflation nor validates the method. The
finding is the mismatch between the claimed null and the implemented one.

Recommended repair: use a tested conditional-randomization implementation or
implement focal exclusion with numerical parity tests. Explicitly distinguish
normal-approximation p-values from empirical permutation p-values. Validate
sparse, skewed and small-region cases before relying on significance to propose
ROIs. The code's assertion that BH always multiplies the minimum p-value by the
number of cells also needs correction: the adjustment depends on rank.
See the primary [PySAL conditional-permutation explanation](https://pysal.org/esda/dev/user-guide/local_spatial_autocorrelation.html#the-logic-of-conditional-spatial-permutations).

### F4 / P2: PDF delivery loses the main descriptive visualizations

Location: [PDF figure selection](../spatialmind/pilot/xenium.py#L2457).

Both brain runs generate a cluster map and marker heatmap, and HTML includes
them. The PDF renderer selects only `review_figures` for its raster figure list;
its descriptive sections contain tables but no figures. Visual inspection of all
six healthy-brain PDF pages confirmed that the provisional label map is present
while the cluster map and marker heatmap are absent. This makes format choice
change the scientific evidence a collaborator receives.

Recommended repair: give HTML and PDF a shared report-content manifest, including
descriptive figures, local spatial results and relevant caveats. Test figure and
section parity. Use a status-aware title rather than an unconditional
"Validated Xenium Pilot" heading on a blocked report.

### F5 / P2: The normal workstation installation still bypasses tested pins

Location: [requirements and install command](../requirements.txt#L3).

Claude correctly constrained CI and the application build, but `requirements.txt`
still documents an unconstrained installation, and `make install` follows it.
`numpy<2` and an unpinned `pyarrow` remain beside other floating dependencies.
This leaves source users exposed to the dependency drift that the recent CI
repair addressed. The existing local environment passes; this review did not
install a fresh unconstrained environment or claim every resolver will fail.

Recommended repair: route the supported install path through
`packaging/constraints.txt`, document the supported Python versions, and test
that exact public installation command in a fresh environment. Keep optional
deep-learning dependencies in their separate environment.

### F6 / P2: Replay changes valid configuration values

Location: [pilot replay parameter reconstruction](../spatialmind/storage/replay.py#L172)
and [pilot record parameters](../spatialmind/pilot/xenium.py#L509).

The replay adapter treats zero coverage thresholds as absent and replaces them
with 0.7. It also omits the low-coverage acknowledgment; the pilot does not
persist that acknowledgment in the first place. A probe recorded zero thresholds
and an explicit acknowledgment, then received 0.7 thresholds and no acknowledgment
from replay. Nonzero thresholds below the floor cannot replay with the required
acknowledgment either. Report-format preservation also depends on a new CLI flag.

Recommended repair: serialize all effective options, preserve zero distinctly
from missing, carry acknowledgments, and apply defaults only to absent fields.
Test ordinary settings and explicitly relaxed settings without changing their
meaning.

These findings concern the current agent, including older code. They are not
all regressions introduced by Claude's latest commits.

## Evaluation Results

| Check | Measured result | Interpretation |
| --- | --- | --- |
| Local unit/integration suite | 650/650 passed; 372.033 seconds | Regression suite passes; targeted review exposed uncovered cases |
| Legacy routing | 16/16; 4/4 registry invariants | Existing intent routes behave as expected |
| MVP routing | 13/13; 4/4 registry invariants | MVP routes and refusals behave as expected |
| Architecture | 6/6 import contracts; 125 files, 303 dependencies | Layer boundaries enforced |
| Studio source acceptance | 13/13 | Real API, strict scientific backends, review writes and HTML/PDF/DOCX/XLSX delivery |
| Environment | `pip check`, version policy and compile check passed | Installed environment is consistent; not a fresh-install test |
| Documentation inventory | Passed; 650 tests, 30 registered tools | Counts match code |
| Tool availability | 12 plannable; 18 disabled scaffolds | Registered placeholders are not presented to planners as working tools |
| Current GitHub Checks | Passed on Python 3.9 and 3.11 | Verified for exact source commit |
| H5AD inventory | 9 files audited; zero read errors | Technical inventory, not reference approval |
| Bounded human reference loading | 8/8 loaded, 64 cells each | Draft training donors only; no test labels scored |
| Pilot recorded-artifact verification | 18/18 per brain run | Passes for recorded artifacts; subject to F1's coverage limits |

Current CI evidence: [Checks run 38219016692](https://github.com/Katherine516/SpatialMind/actions/runs/38219016692).
Local environment: Intel macOS, Python 3.9.7, NumPy 1.26.4, SciPy 1.13.1,
Scanpy 1.10.3, Squidpy 1.6.1 and AnnData 0.10.8. Exact package versions are
archived in the evaluation directory. Optional scVI/cell2location are absent
from this environment by design.

### Full-section brain workflows

Both runs used the current canonical pilot, complete sections, strict scientific
backends and `--report-format both`. No review thresholds were relaxed. The
descriptive pilot uses **100 permutations** for global spatial genes and cluster
neighborhoods, and **999** for local hotspot diagnostics. This differs from
the Studio plan's 250-permutation spatial-gene default; their runtime numbers
should not be compared as equivalent settings.

| Metric | Healthy brain | Glioblastoma |
| --- | ---: | ---: |
| Input cells | 24,406 | 40,887 |
| Cells retained after QC | 24,362 | 40,786 |
| Cells excluded by QC | 44 | 101 |
| Measured expression genes | 319 | 319 |
| Expression clusters | 9 | 11 |
| PCA silhouette | 0.10334 | 0.14534 |
| Graph modularity | 0.76702 | 0.78431 |
| Eligible spatial genes tested | 296 | 307 |
| Genes with adjusted p <= 0.05 | 289 (97.6%) | 307 (100%) |
| Descriptive analysis time | 106.65 s | 168.09 s |
| Global spatial-gene stage | 40.73 s | 74.55 s |
| Candidate spatial domains | 9 | 10 |
| Candidate gene-hotspot regions | 5 | 3 |
| Accepted labels/regions applied | 0 / 0 | 0 / 0 |
| Biological gate | Blocked | Blocked |
| Analysis backend errors | None | None |
| Delivered result tables | 5 | 5 |

Times above cover the descriptive stage, not complete launch-to-report latency.
Other evaluation processes ran concurrently, so these are observed timings, not
isolated performance benchmarks. The pipeline's wall/CPU ratio detector reports
"clean," but aggregate CPU time from multiple threads cannot establish absence
of contention or cross-run comparability.

The modest silhouettes indicate overlapping expression profiles; modularity
measures graph communities, not cell-type accuracy. The high spatial rejection
fractions indicate pervasive tissue structure. They do not establish disease
specificity, mechanisms, signaling or independent biomarker discovery. The
leading global genes were TESPA1, NRN1 and ENC1 in healthy brain, and SLC17A7,
ENC1 and NPTX1 in glioblastoma. These are measured rankings without a cell-type
or malignant-state interpretation.

Treat this table as an engineering comparison of two runs. There is no replicated
healthy-versus-glioblastoma differential analysis, batch adjustment or donor-level
inference here. Hotspot-derived ROI candidates remain exploratory pending F3.

### Gated success-path exercise

A separate 300-cell synthetic fixture used explicitly synthetic reviewer IDs
and evidence references. Its pilot opened the gate and ran six planned tools in
36.567 seconds. Annotation, markers, region summary, neighborhood enrichment,
the robustness sweep, distance co-occurrence, group autocorrelation, point
patterns and gene-pair spatial calculations executed without a backend error.
Its 24 recorded hash checks passed. The robustness index was 1.0 on this fixture;
this is not a biological accuracy score.

Region-stratified testing correctly returned `insufficient_data`: the synthetic
label arrangement left individual regions without enough cell-type diversity.
Thus this exercise verifies that refusal, not a positive region-stratified
result. The existing regression suite also exercises this analysis. No synthetic
review decision was added to a real dataset.

## Status by Layer

| Layer | Current evidence | Remaining work |
| --- | --- | --- |
| Contracts and architecture | Six enforced import contracts; typed plans and data semantics | Preserve these boundaries when adding platforms |
| Ingestion and QC | Two complete Xenium sections; nine H5AD inventories; eight bounded human loads | Full-atlas memory/scaling validation and finalized reference semantics |
| Planning and execution | 29 routing cases; scaffold refusal; shared execution policy | Real hosted-LLM evaluation, parameter fidelity and ambiguous-question cases |
| Scientific tools | Clustering, markers and spatial analyses run with real backends | Repair local null; examine effect sizes and composition-conditioned patterns |
| Expert review and references | Missing evidence blocks both brain cohorts | Human labels, morphology-backed regions, approved lineage/state/donor mappings |
| Claims and reliability | Refused claims receive blocked scores; synthetic sweep exercised | Reviewed claim truth and donor-disjoint calibration; scores remain heuristic |
| Visualization and reports | HTML, six-page PDFs, TSVs and Explorer-lite generated | PDF/HTML parity and accurate Studio lane wording |
| Storage and replay | Recorded hashes verify | Input snapshot timing, descriptive provenance and exact replay options |
| Desktop and distribution | Current source acceptance; previous native release evidence | Retest repaired source in both native builds; Apple notarization remains pending |
| Training and external evaluation | Protocol and gates exist; readiness check refuses training | Approved protocol plus independent labeled donor; no new biological metrics claimed |

Healthy brain and glioblastoma specialist packets each contain 750 cells, with
**zero accepted labels, zero accepted regions and no assigned specialists**.
Reference review has 28 label mappings and 114 collection/donor entries awaiting
curation, producing 397 explicit validation messages. These are not 397 new
software defects. The eight human loading checks find 318 shared panel genes in
Siletti references and 316 in GBmap; overlap alone does not validate transfer.

## Assessment of Claude's Changes

The changes are useful and verified: the shared constraint file now serves CI
and app builds, the publication workflow requires a green Checks run on the
same source commit, and the documentation inventory is consistent. The source
branch now incorporates the earlier native-app work without the previous dirty
working-tree ambiguity.

The published 1.0.1 installers still point to source `9237f4033b4d22e5ee64d042f74d15a31900e287`.
This review did not rebuild or republish them. Current source checks therefore
must not be presented as new acceptance evidence for those existing binaries.

## Recommended Next Steps

1. **P0: Complete a focused reliability repair.** Fix F1 and F2 first, then F4
   and F6, and make the supported installation command use the tested pins (F5).
   Acceptance: changed-input runs cannot verify, every emitted result/figure is
   accounted for, blocked cluster runs are never called validated, PDF and HTML
   contain the same core evidence, and replay preserves all options.
2. **P1: Repair and validate local spatial inference (F3).** Compare the chosen
   conditional null with a trusted implementation; predefine one- or two-sided
   alternatives and correction families. Test sparse counts, rare populations,
   tissue edges, varying neighbor sizes and null/positive controls. Do not tune
   the method merely to increase the number of hotspots.
3. **P1, in parallel: Start actual expert review.** Obtain acceptance from a brain
   single-cell specialist and a neuropathologist. Begin with a blinded,
   stratified development subset covering rare/ambiguous groups, resolve
   disagreements and obtain registered histology where anatomy cannot be read
   from existing morphology. Keep frozen test decisions inaccessible to tuning.
   The prepared 750-cell packets are a benchmark cohort, not full-section review
   coverage; broader review or a separately validated transfer workflow is still
   needed to clear the full-section gate.
4. **P2: Make the output answer stronger spatial questions.** Lead with Moran's I,
   expression/detection support, location maps and stability across graphs.
   After labels/regions are reviewed, distinguish cell-composition structure
   from within-cell-type expression patterns and perform region-stratified
   tests. Define the target question and null before implementation; exploratory
   cluster-conditioned analyses must be labeled as such.
5. **P2: Freeze biological development and external evaluation.** Finalize
   reference label/state/donor mappings and protocol approval. Select models on
   training/validation only, obtain an independently labeled donor, then run the
   locked external evaluation once. Report macro-F1, per-class recall, abstention
   coverage, calibration and donor-level uncertainty. Existing internal breast
   scores are historical context, not brain performance.
6. **P3: Release the repaired agent and expand only after validation.** Rebuild
   Intel/Apple Silicon packages from the tested commit, complete collaborator
   acceptance and notarization, and only then prioritize additional modalities.
   Add hosted-LLM paraphrase/parameter/adversarial evaluations separately from
   biological tool validation.

The best immediate move is the focused reliability repair plus recruiting the
two real reviewers. Further training on unreviewed brain assignments would not
resolve either the software findings or the missing biological evidence.

## Outputs and Reproduction

- [Healthy-brain HTML report](../outputs/agent_review_20261012/healthy_brain/validated_xenium_pilot_report.html)
- [Healthy-brain PDF report](../outputs/agent_review_20261012/healthy_brain/validated_xenium_pilot_report.pdf)
- [Glioblastoma HTML report](../outputs/agent_review_20261012/glioblastoma/validated_xenium_pilot_report.html)
- [Glioblastoma PDF report](../outputs/agent_review_20261012/glioblastoma/validated_xenium_pilot_report.pdf)
- [Machine-readable evaluation metrics](../outputs/agent_review_20261012/evaluation_metrics.json)
- [Targeted probe evidence](../outputs/agent_review_20261012/review_probes.json)
- [Brain/reference readiness](../outputs/agent_review_20261012/brain_readiness/readiness.html)
- [Synthetic success-path evidence](../outputs/agent_review_20261012/synthetic_gate_demo/summary.json)

The evaluation directory also contains test logs, package versions, source API
acceptance results, reference audits, PDF page renders and reproducible probes.
Real dataset files were not modified. No model was trained, no independent test
was scored, no hosted LLM was called, and nothing was pushed to GitHub.

Both PDFs were rendered for visual QA. HTML links and images were checked from
their source; browser layout inspection was blocked by the browser tool's local
file URL policy. The report findings above remain open for the next implementation
step; this task evaluated and documented them rather than changing the scientific
code under evaluation.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m eval.runner --out outputs/new_review/legacy.json
.venv/bin/python -m eval.runner --mvp --out outputs/new_review/mvp.json
.venv/bin/lint-imports
.venv/bin/python scripts/check_doc_numbers.py --check

.venv/bin/python scripts/run_validated_xenium_pilot.py \
  --data 'data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs' \
  --out outputs/new_review/glioblastoma --full-section --report-format both
```
