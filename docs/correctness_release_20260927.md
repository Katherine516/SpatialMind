# Correctness Release: Execution, Review Scope, and Claim Evidence

Date: 2026-09-27. This implements the immediate correctness work recommended in the [agent audit](agent_evaluation_20260927.md). It does not claim independent biological validation or model training.

Follow-up: the [annotation benchmark](annotation_benchmark_20260927.md) subsequently found and fixed legacy
`Blank Codeword` controls entering expression analyses. The breast outputs below are historical pre-fix
runs; regenerate them before treating their numerical results as current scientific evidence.

## Changes

### Execution Policy

- Studio checks the effective plan after dependencies are inserted, both at the API boundary and inside the worker.
- Studio and the canonical pilot share `execute_tool_step`, which checks the gate, tool availability, and preconditions. Scientific runs require real backends and reject prototype fallback.
- Cluster markers/neighborhoods depend on clustering, not expert annotation. Annotation cannot bypass its gate through a grouping override.
- `cluster`, `leiden`, `clusters`, and `leiden_cluster` resolve to the same stored assignments. Unknown modes fail explicitly.
- Pairwise differential expression supports the same cluster grouping as one-vs-rest markers.

### Per-Cell Review Scope

- Label and region application retain cell-ID-specific assignments, source paths, reviewer identities, and assignment scopes.
- Validated tools use the reviewed-cell mask, rather than accepting every cell whose label name appears somewhere in a reviewed table.
- Region summaries use the intersection of reviewed labels and reviewed regions. Robustness sweeps, region-stratified tests, distance curves, and cell-type spatial statistics use reviewed scope too.
- Tools record analyzed/excluded counts. Cell exports distinguish reviewed from provisional labels using the same provenance.
- Descriptive analysis still uses all QC-retained cells; unreviewed data is not discarded from exploration.

### Figures and Reliability

- Studio cluster maps read `dataset.metadata['cluster_assignments']`. They no longer silently substitute provisional cell types. Unreviewed cells in a reviewed-label map are explicitly marked as such.
- Pilot spatial claims carry a structured binding to the tool, pair, direction, and graph scope. The statistical component cannot borrow an unrelated pair's result.
- Raw and adjusted p-values are distinguished; zero is preserved; nonfinite statistics are rejected. Direction is checked before evidence is counted.
- Robustness uses the same pair's measured sign agreement and top-K presence, with a penalty for missing settings. Missing pair-specific sweeps block R; the old heuristic proxy is removed.
- Panel-marker adequacy uses the target pair for spatial claims. Annotation support remains coverage, not measured accuracy.
- The score remains an **uncalibrated evidence index**, not a probability of biological truth. Historical calibration models/control AUROCs do not validate this revised scorer.

### Delivery and Reproducibility

- Studio records the effective plan and selected review-table paths.
- Final manifests hash the payload, HTML/Markdown reports, figures, and tables. Inputs are checked for changes during analysis.
- Missing required artifacts yield partial delivery, not a successful background job. Available results are retained.
- `scripts/replay_run.py --replay` now handles recorded Studio plans after verification, while reapplying current safety checks.
- Documentation inventory counts are independent of verification dates. Counting tests no longer writes a claim that those tests passed.

## Real-Data Verification

Source inputs under `data/` were not edited. Outputs are under `outputs/correctness_release_20260927/`.

| Check | Result |
| --- | --- |
| Unreviewed default marker request | HTTP 409; refused |
| Annotation with cluster override | HTTP 409; refused |
| Cluster-only neighborhood request | HTTP 200; permitted with clustering dependency |
| Unknown grouping mode | HTTP 400; rejected |
| Healthy-brain full descriptive recipe | 24,362 retained cells; 319 expression features; four tools; 80.102 seconds |
| Healthy-brain map | Visually inspected; nine cluster IDs, 0-8, rather than six provisional cell-type names |
| Published breast sample | 5,000 requested, 4,893 retained; five tools; 29.382 seconds |
| Breast reviewed-cell scope | 4,756 reviewed cells used; 137 unreviewed cells excluded from biological tools |
| Output hashes, each run | 3 artifacts + 1 figure + 4 tables |
| Breast replay | Completed; numerical metrics identical for all five tools |
| Final unit suite | 530/530 passed in 177.048 seconds, including 31 new regression cases |
| Routing evaluations | Legacy 16/16; MVP 13/13; registry invariants passed |
| Architecture/environment | Six import contracts kept; `pip check` passed |

Timings are workstation observations, not controlled performance benchmarks. The breast run is sampled and uses published cell labels plus composition-derived regions; it is not an independent biological benchmark or an anatomical validation study.

Final suite details are in `outputs/correctness_release_20260927/final_unit_tests.log`. New regression cases live in `tests/test_correctness_boundary.py`; they cover direct worker refusal, alias consistency, actual plot legends, same-name unreviewed cells, direction/p-value handling, pair-specific robustness, output tampering, replay preparation, strict backends, and partial delivery.

### Measured Claim Binding

An additional real breast-sample check ran Squidpy robustness at k=6, 10, and 15 with 50 permutations per setting. Its aggregate stability index was 0.897; the distance-band comparison was 0.8067 with 93 isolated cells. These are exploratory measurements, not confirmatory significance or biological accuracy.

Of ten spatial pair claims, three had matching stored pair-level sweep measurements and received R=1.0; seven remained blocked with R=0 because the sweep stores stability for its reference top ten pairs, which also include same-type pairs. The global score was not substituted for missing pair evidence. This is conservative but limits report coverage; a future sweep should explicitly measure every reported claim's pair. The two non-spatial capability claims are outside this spatial count.

The panel component still has incomplete lineage/marker mappings for breast label names and can fall back to a generic availability score. That fallback is not measured marker adequacy or annotation accuracy. Do not treat the combined score as calibrated confidence. Full diagnostic evidence is in `outputs/correctness_release_20260927/real_claim_binding.json`.

### Reports

- [Healthy-brain descriptive report](../outputs/correctness_release_20260927/runs/healthy_descriptive/report.html)
- [Published-breast sampled report](../outputs/correctness_release_20260927/runs/breast_reviewed_sample/report.html)
- [Replayed breast report](../outputs/correctness_release_20260927/replay/replay/report.html)
- [Machine-readable verification](../outputs/correctness_release_20260927/evaluation.json)

Generated outputs are ignored by Git; the evaluator and this record are tracked source artifacts.

## Reproduce

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/lint-imports
.venv/bin/python scripts/check_doc_numbers.py --check
.venv/bin/python scripts/evaluate_correctness_release.py
.venv/bin/python scripts/replay_run.py \
  outputs/correctness_release_20260927/runs/breast_reviewed_sample/runs/breast_reviewed_sample.json \
  --replay --out outputs/correctness_release_20260927/replay
```

The existing packaged macOS application was not rebuilt. Run the updated source environment to use these changes; rebuild the desktop bundle before distributing it. No Git commit or GitHub push was performed.

## Remaining Work

1. Freeze an independent annotation benchmark using published breast labels. Keep held-out labels unavailable to the predictor; report class-balanced and per-class metrics, abstention, and section/donor independence.
2. Complete healthy-brain and glioblastoma expert labels and anatomy-based ROI review. Ontology terms standardize labels; they do not assign cells or establish truth.
3. Validate the entire spatial-statistics pipeline under null and positive controls, including data-dependent gene screening and region selection. Pair binding fixes a correctness defect, not false-discovery calibration.
4. Collect independently reviewed spatial claim truth, then fit and evaluate calibration on disjoint sections/donors. The new scorer must be recalibrated from scratch.
5. Expand reproducibility testing to full sections and clean installations. Input bundles remain in-place sources with change detection, not a content-addressed immutable archive.
6. Add a constrained LLM planner after these checks. Existing provider adapters and local memory do not constitute biological training or multi-user production hardening.

The immediate software blockers identified in the audit have been addressed in the active Studio/pilot paths. Independent biology, expert review, production security, and rebuilding the desktop distribution remain separate acceptance tasks.
