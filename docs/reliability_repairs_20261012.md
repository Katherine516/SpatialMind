# Reliability Repairs and Brain Workflow Re-evaluation

Date: October 12, 2026 (America/New_York). This follows the
[source review](agent_review_20261012.md) at `8c9b996`.
Changes are local source changes, not a new packaged release. Real datasets and
human review decisions were not edited. No biological training was performed.

## Implementation Order

| Order | Repair | Implemented behavior |
| --- | --- | --- |
| 1 | Input and output provenance | Pilot and Studio snapshot the declared input read set before ingestion. Changed inputs produce an invalid run record retaining the original hashes and an execution error. Restoring the input later does not make that record valid. |
| 2 | Report lane honesty | Studio requires a passed gate and an actual reviewed-only result. Clustering remains descriptive even with an open gate; mixed reports do not describe every result as a cell-type result. Unreviewed cells are not displayed as reviewed labels. |
| 3 | Local spatial inference | Focal values are excluded from conditional permutation pools. Two-sided empirical p-values include ties and the +1 correction. Z-scores are diagnostics only; per-gene BH and finite permutation resolution are disclosed. |
| 4 | PDF and HTML coverage | Both include the cluster map and marker heatmap. PDF adds local hotspot counts, inference method and caveats. Titles explicitly identify descriptive/readiness runs. Interactive HTML features are not claimed to exist in PDF. |
| 5 | Workstation installation | The standard `requirements.txt` includes the shared constraints already used by CI and packaging. No dependency upgrade was performed. |
| 6 | Replay fidelity | Preserve zero thresholds, low-coverage acknowledgement, review-artifact choice, review size, section requirement and original report format. An explicit format flag overrides the original. Dataset identity is explicit rather than inferred from alphabetically sorted sidecars. |
| 7 | Biological handoff | Refreshed readiness and updated the English review workflow. No automatic promotion of draft labels, reference mappings or anatomical candidates into truth. |

The pilot now records seven descriptive execution entries, including local
structure and region proposals, alongside explicit skipped biological stages.
Both descriptive raster figures and their source tool JSONs are hashed.
Alternate review filenames, `.xenium`-resolved directories and 10x clustering
inputs are included in the declared input list. Readiness-only mode remains a
lightweight status check rather than an attestation to executed analysis.

## Statistical Specification

The local statistic uses centered, standardized expression and zero-diagonal,
row-standardized spatial weights. For each cell, the null fixes its value and
randomizes other cells into its neighbor slots. A sparse correction to a shared
uniform permutation implements the same per-cell conditional draw without
allocating a cell-by-cell permutation matrix.

The test statistic is the absolute deviation from the conditional expectation,
`-z_i^2/(n-1)`, for a non-isolated row. Empirical p-values use
`(exceedances + 1)/(permutations + 1)`. Isolated or degenerate-null cells receive
p=1. Default settings remain 18 neighbors, 999 permutations, seed 0 and alpha
0.05. Correction is BH across cells separately for each tested gene.

This is **exploratory**, not confirmatory inference: gene selection uses the same
section, neighborhoods overlap, and correction does not establish across-gene
or post-selection error control. Shared permutations have correct marginal
conditional draws, not independent tests across cells. No hotspot count was used
to tune settings. A lack of detected hotspots does not establish lack of biology.

Validation includes all 120 permutations of a five-cell weighted graph, compared
against explicit focal-fixed permutations and the exact conditional expectation;
an isolated-cell check; a 1,200-cell implanted-stripe/noise control; and 30
independent synthetic count datasets with three tested genes each. The latter
produced **0/90 gene families with any rejection** at 199 permutations. This
bounded conservative diagnostic is not a population-level FDR guarantee or a
biological benchmark.

## Full-section Brain Results

| Metric | Healthy brain | Glioblastoma |
| --- | ---: | ---: |
| Input cells | 24,406 | 40,887 |
| Retained cells | 24,362 | 40,786 |
| QC removals | 44 | 101 |
| Measured biological features | 319 | 319 |
| Expression clusters | 9 | 11 |
| PCA silhouette | 0.10334 | 0.14534 |
| Graph modularity | 0.76702 | 0.78431 |
| Eligible globally spatial genes | 296 | 307 |
| Significant global spatial genes | 289 | 307 |
| Descriptive execution trace entries | 7 | 7 |
| Verified input/artifact checks | 24/24 | 24/24 |
| Hashed visualization files | 7 | 7 |
| PDF pages | 7 | 8 |
| PDF raster figures | 3 | 3 |
| Descriptive-stage wall time | 148.78 s | 244.58 s |
| Biological gate | Blocked | Blocked |

Global spatial tests use 100 permutations. Their small p-value resolution and
the broad tissue structure mean significance counts should not be presented as
disease-specific mechanisms. Clusters, silhouette and modularity are unchanged
from the original review; the repair changes local inference and reporting,
not the clustering algorithm. Low silhouettes still indicate overlapping
expression groups. These are not cell-type accuracy scores.

Timing was measured while other tests/workloads were running. It is not an
isolated speed benchmark and should not be used to infer a performance regression.
The healthy-brain rerun began before the additional alternate-filename input-list
hardening; its standard bundle was already protected by the pre-ingestion hash.
The glioblastoma rerun and subsequent source acceptance include that hardening.

Both runs have no analysis-backend error. Both descriptive figures were verified
in HTML, in PDF captions and in the run record. All 15 rendered PDF pages were
visually inspected. HTML image references and report text were checked; browser
layout was not verified in this task.

## Regression Evidence

- Final-source full regression: **664/664 tests passed in 337.425 seconds**;
  `unit_tests_verified.log` includes the effective-trace refinement. The final
  synthetic CLI replay also verified effective parameters and per-tool lanes.
- Fourteen new regression tests cover input mutation, restoration, manifest and
  alternate-table hashing, report lanes, PDF figure coverage, conditional draws,
  installation constraints and replay identity/options.
- Source-server acceptance: **13/13**, including scientific analysis, refusal,
  review writes and report exports. This is not packaged-app acceptance.
- Routing evaluation: **16/16 legacy**, **13/13 MVP**, all four invariants passed.
- Six import contracts passed; compilation, `pip check` and runtime version
  policy passed. The standard constrained installation dry-run succeeded against
  the existing environment; a fresh independent environment was not installed.
- Synthetic 300-cell gated pilot: six core tools, robustness score 1.0 and
  **38/38** provenance checks passed. Region-stratified analysis correctly refused
  insufficient within-region class support. Synthetic labels demonstrate software
  execution only; they do not establish annotation accuracy or claim calibration.
- An actual CLI replay of the synthetic pilot completed after input/output hash
  verification. Low-coverage and format preservation are also covered by dedicated
  round-trip and CLI regression tests; no real-data gate was relaxed.

Evidence lives in `outputs/reliability_repairs_20261012/`, including
`verification_metrics.json`, `local_null.json`, `source_smoke/checks.json`,
`synthetic_gate_demo/summary.json` and test logs.

## Remaining Requirements and Priorities

1. **Human review and curation:** both 750-cell cohorts still have zero accepted
   labels and regions. Assign the two real specialist roles, collect registered
   pathology evidence where needed, and complete reference/state/donor decisions.
   Use the [current handoff](expert_review_workflow.md#current-handoff-october-12-2026).
2. **Prespecified biological development:** obtain protocol approval and an
   independently labeled donor. Tune only on training/validation; evaluate the
   locked external test once. Report macro-F1, rare-class recall, abstention,
   calibration and donor-level uncertainty, not within-section cluster scores.
3. **Stronger spatial interpretation:** separate changes in cell composition from
   within-cell-type expression once reviewed labels/regions exist. Specify the
   question and null first; report effect sizes, detection support and sensitivity
   to graphs/regions before mechanistic language. Broader edge/sparsity/graph-size
   calibration remains appropriate before claiming confirmatory local inference.
4. **Release:** rebuild and test Intel and Apple Silicon packages from the final
   tested commit; configure Developer ID signing/notarization for public release.
   Current downloaded DMGs do not contain these local fixes. No push or release
   was performed in this task.

Input hashes detect observed changes, not arbitrary concurrent edits that are
changed and restored between checks. They are not locks, immutable snapshots,
cryptographic signatures or proof of scientific truth. Directory hash scope is
explicit: analysis files are content-hashed, while large unused assets can remain
name/size catalogued. For multi-user production, use immutable input snapshots,
access control and an audited execution service.

## Example Reports

- [Healthy-brain HTML](../outputs/reliability_repairs_20261012/healthy_brain/validated_xenium_pilot_report.html)
- [Healthy-brain PDF](../outputs/reliability_repairs_20261012/healthy_brain/validated_xenium_pilot_report.pdf)
- [Glioblastoma HTML](../outputs/reliability_repairs_20261012/glioblastoma/validated_xenium_pilot_report.html)
- [Glioblastoma PDF](../outputs/reliability_repairs_20261012/glioblastoma/validated_xenium_pilot_report.pdf)

Generated output links are local workspace artifacts and are not uploaded to
GitHub by these changes.
