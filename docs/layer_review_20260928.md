# Layer-by-layer review — 28 Sep 2026

A review of the agent after the 27 Sep changes (`38f09ce`, plus uncommitted and
untracked work in the tree). Every number here was re-measured rather than read
out of a prior document.

## Verification baseline

| Gate | Result |
| --- | --- |
| Unit and integration | **561 / 561** (was 499 on 21 Sep) |
| Legacy eval cases | 16 / 16, mean 1.0000 |
| MVP eval cases | 13 / 13, mean 1.0000 |
| Import-linter contracts | 6 / 6 |
| `check_doc_numbers.py --check` | docs match the code |

Everything green. The rest of this document is about what the green means.

---

## 1. Ingestion — a residual control-probe leak, found and closed

**What changed.** `NON_GENE_FEATURE_TYPES` gained `"blank codeword"`.

**Why it matters.** This is the third instance of one bug family. Control probes
were 39% of the breast panel and driving PCA; that was fixed by reading declared
feature types from the matrix rather than guessing from names. The declared-type
list itself was then incomplete: the older breast H5 declares 159 `Blank
Codeword` features, and that string was not in the exclusion set, so detected
blank controls entered expression analyses anyway.

**Verified.** `tests/test_annotation_holdout.py:101` builds a real H5 fixture,
asserts `_read_h5_control_features` returns `{BLANK_01, N1}` with source
`declared_feature_type`, and asserts `expression_feature_names` then yields only
`{G1, G2}`. End-to-end, not a unit assertion on a constant.

**Assessment: sound.** The consequence is stated plainly in the README — older
breast analyses must be regenerated before their numbers are reused. That is the
right disclosure and it is easy to skip; it is worth tracking which published
outputs still carry the defect.

---

## 2. Tools — the dependency graph became parameter-aware

**What changed.** `order_plan(tool_names, overrides)` and a new
`requirements_for(name, overrides)`. When a `GROUPED_TOOLS` member is grouped by
cluster, its `annotation` requirement is rewritten to `clustering`.

**Measured:**

```
marker_detection, group_key=cell_type   qc_and_cluster -> annotation -> marker_detection
                                        blocked_steps=2, annotation and markers blocked

marker_detection, group_key=cluster     qc_and_cluster -> marker_detection
                                        blocked_steps=0, both descriptive
```

**Why it matters.** This resolves a circularity in the workflow. Cluster markers
are what a reviewer reads *in order to* name clusters; requiring a completed
review before markers could be computed inverted the dependency. Cluster markers
are now a descriptive question and cell-type markers remain a validated one,
which is the correct split — the grouping, not the tool, decides whether a
biological name is being asserted.

`strict_engine: True` was also added to `spatial_clustering`,
`differential_expression` and `neighborhood_enrichment` defaults, so a prototype
fallback cannot silently substitute for the real backend in those three.

**Assessment: the best change in this batch.** It is a genuine conceptual
correction, not a convenience.

---

## 3. The gate — widened, and moved off a legacy allowlist

**What changed.** The grouping vocabulary moved to `tools/grouping.py`.
`requires_labels` now asks `normalize_group_key(params) != "cluster"` for grouped
tools. The `LEGACY_LABEL_GATED` allowlist was removed from one branch, so tools
reaching it are gated unconditionally rather than only when named in a list.

**Assessment: sound, and it pairs correctly with §2.** The gate is now keyed on
what the call actually asks for rather than on a hand-maintained list of names.
A list of names is the kind of thing that silently falls behind; a predicate over
parameters does not.

---

## 4. Claims and reliability — the largest and most consequential change

**What changed, and it is a lot.**

Previously the pilot emitted one generic claim per capability: *"Cell-type
neighborhood enrichment **can** support cell-level spatial adjacency claims when
permutation z-scores and graph-sensitivity evidence are present."* That is an
assertion about the tool, not about the tissue, and it is unfalsifiable.

Now it emits one claim per observed pair, each carrying an explicit
`spatial_target` binding `{tool, pair, direction, graph_family, n_neighs,
radius}`, with text naming both cell types, the direction, the z-score, and
*"this is not a causal claim."*

`_statistical_component` was rewritten to honour that binding:

- no `spatial_target` with tool, pair and a direction in
  `{enrichment, depletion, association}` → the component is **blocked**;
- evidence is only consulted from the named tool, and only from results whose
  `region`, `graph_family`, `n_neighs` and `radius` match the target;
- direction is checked against the sign of z — an enrichment claim cannot be
  supported by a depletion result;
- raw p-values are Bonferroni-corrected over the number of pairs tested;
- any blocked component blocks the whole claim.

**Measured:**

```
no evidence binding        reliability=0.0  status=blocked
                           "No explicit tool/pair/direction evidence binding was supplied"
bound, no matching result  reliability=0.0  status=blocked
                           "No adjusted spatial statistic or effect-size evidence was available"
```

Two different refusals for two different reasons, which is what a diagnostic
should do.

**The withdrawn claim.** The old `S_statistical` caveat read *"Calibrated against
matched permutation-null and stripe-implant controls (AUROC 0.98)"*. It now
reads *"This is an uncalibrated evidence index, not a probability of biological
truth."* That is a retraction, and it is the correct one: the 9 Sep calibration
was fit on 18 rows from a synthetic section in which `P_panel` and `A_annotation`
had **zero** separation, so the AUROC was carried almost entirely by
`S_statistical`. Presenting that as calibration of the composite was an
overstatement. Removing it is the single most honest edit in this batch.

**Assessment: sound, and a real strengthening.** The previous behaviour let any
result's best pair support any colocalization claim. Claims and their
verification are now bound to the same object.

---

## 5. Review — the first ground-truth evaluation this project has had

**What changed.** `review/annotation_benchmark.py` (291 lines) and
`review/specialist_handoff.py` (196 lines).

**Method, and it is careful.** Whole coordinate blocks are assigned to
train/validation/test by a seeded hash *before labels are consulted*; cells
within 50 µm of a different split are excluded (865 of them); query datasets are
rebuilt from scratch with coordinates zeroed, no metadata, no labels, and
`predict()` raises if any query record carries a label or region, or if query and
reference cell IDs intersect. Incomplete-reference preflight is deliberately
overridden so unsupported classes count as errors rather than vanishing.

**Result on the Janesick breast replicate:**

| | |
| --- | --- |
| Accuracy | 80.71% (bootstrap 77.45–84.02%) |
| Macro-F1 | 0.6208 (bootstrap 0.5347–0.6341) |
| Balanced accuracy | 57.00% |
| Training-majority baseline | 22.64% / macro-F1 0.0194 |
| Coverage at vote threshold 0.6 | 76.53%, accuracy 88.61% among retained |
| Macro-F1 counting abstentions as misses | 0.4652 |

**Assessment: methodologically the strongest work in the repository**, and its
self-assessment is appropriately severe. Balanced accuracy of 57% against 19
classes, with F1 of 0 for `Stromal_&_T_Cell_Hybrid` and 0.163 for
`Prolif_Invasive_Tumor`, supports exactly the conclusion drawn: *assisted
annotation with abstention and review, not unattended fine-grained cell typing.*

The document is also correct that this is **internal validation within one
section, not an independent donor benchmark**, and that published
expression-assisted labels are not independent assay truth. The note that the
test set has now been inspected, and that further development must use
train/validation only, is the right discipline and is easy to forget later.

---

## 6. Annotation priors — opt-in, and the README claim checks out

`tools/annotation_priors.py` reweights neighbour votes by inverse training
frequency raised to `class_prior_power`. Verified: the registry default is `0`,
`power == 0` returns the input unchanged, and the selection script picks the
winner on **validation** macro-F1 only. The README says it improved rare-class F1
in breast validation only, is not enabled by default, and is not evidence of
brain or external performance. All three statements match the code.

**Assessment: sound.** The guard against estimating priors from a query or test
set is in the module docstring and enforced by where the call sits.

---

## 7. The Studio app — unchanged in substance, and now stale as a build

The app layer picked up the planner and gate changes and some endpoint work. No
regression: all 561 tests including the 76 Studio tests pass.

**Finding: the packaged app is stale.** `dist/SpatialMind Studio.app` was built
21 Sep; **57 source files are newer than the bundle**. None of the work reviewed
here — the reliability rewrite, the parameter-aware DAG, the control-probe fix —
is in the artifact anyone would open.

---

## 8. Repository hygiene — the one thing I would act on first

The working tree is not clean, and the split is awkward:

| State | Files |
| --- | --- |
| Committed | `annotation_benchmark.py`, `specialist_handoff.py`, `tools/grouping.py` |
| **Uncommitted edits** | `README.md`, `docs/agent_architecture.md`, `development_tracking.md`, `specialist_handoff.py`, `implementations.py`, `registry.py`, `manage_brain_specialist_review.py` |
| **Untracked** | `brain_readiness.py` (231), `rare_class_selection.py` (128), `annotation_priors.py` (22), `tests/test_brain_readiness.py`, `scripts/select_rare_class_annotation.py`, `docs/brain_review_execution.md`, `docs/templates/` |

Consequences worth naming:

- The README's uncommitted paragraph links `docs/brain_review_execution.md`,
  which is untracked. Committing the README without the doc produces a broken
  link on a public repository.
- `annotation_priors.py` is untracked, and the import of it in
  `spatialmind/tools/implementations.py:1443` is part of the *uncommitted* edit
  to that file. So HEAD is self-consistent — a fresh clone imports cleanly —
  but the pair must land together. Committing `implementations.py` without
  `annotation_priors.py` breaks `reference_label_transfer` on import, and the
  two are currently in different states.
- `tests/test_brain_readiness.py` runs and passes (13 tests) but is not in the
  repository, so CI has never executed it.

**This is the highest-priority item in the review** — not because the code is
wrong, but because the verified state and the committed state are different
things, and only one of them is what anyone else receives. The 561 passing tests
describe the working tree, not HEAD.

(An earlier draft of this section claimed HEAD itself was broken by the
`annotation_priors` import. It is not: that import is uncommitted too. The risk
is a partial commit, not the current HEAD.)

**Resolution for publication:** the reviewed source changes, their companion
module, focused tests, updated introductions and this review are being committed
together. This publishes the tested worktree state as one coherent change. The
older packaged macOS app remains a separate build artifact and must be rebuilt
before distributing the app.

---

## Overall

The 27 Sep work is careful, and in two places it is better than what it
replaced by a wide margin: the parameter-aware dependency graph resolves a real
circularity, and the claim-to-evidence binding turns an unfalsifiable capability
statement into a falsifiable per-pair one. The retraction of the calibration
claim is the kind of edit that is easy to avoid making and was made anyway.

The gaps are not in the reasoning. They are that the work is half-committed, the
shipped bundle predates all of it, and the benchmark — while the strongest
evidence this project has ever produced — is still one section, one donor, with
labels that are published annotation rather than independent assay truth. The
documents say so themselves, clearly, which is why they are trustworthy.
