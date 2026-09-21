# Agent evaluation — 20 Sep 2026

A second end-to-end evaluation, thirteen days after `agent_evaluation.md`. The
whole workflow was driven through the app's own HTTP API on the real healthy
brain section, the router was scored against a fixed question set, and the
packaged app was measured separately. Reproduce with:

```bash
python scripts/evaluate_studio_workflow.py --out outputs/studio_evaluation
python -m unittest discover -s tests -p 'test_*.py'
python -m eval.runner --cases eval/test_cases --data data/demo_manifest.json --out outputs/eval_report.json
python -m eval.runner --cases eval/mvp_cases  --data data/demo_manifest.json --out outputs/eval_mvp.json --mvp
python scripts/smoke_test_macos_app.py
```

**Read section 6 first.** The workflow completes, the gate behaves, and the
reports are disciplined. The finding that matters is that the agent accepted
labels its own marker table contradicts, on every one of the ten classes, and
said nothing.

## 1. Correctness — 521 automated checks, 0 failures

| Suite | 7 Sep | 20 Sep | Notes |
| --- | --- | --- | --- |
| Unit and integration | 207 / 207 | **484 / 484** | +277 |
| Legacy eval cases | 15 / 15 | **16 / 16** | mean score 1.0000 |
| MVP eval cases | 11 / 11 | **13 / 13** | mean score 1.0000 |
| Import-linter contracts | 4 / 4 | **6 / 6** | layering intact |
| Packaged-app smoke | 11 / 11 | **12 / 12** | drives the built `.app`'s API |

The twelfth smoke check is new and was added because the eleven that preceded it
all passed against a bundle in which `spatial_variable_genes` could not run at
all: `squidpy` imports `spatialdata`, which reaches `dask`, `datashader` and
`plotly`, and all four were excluded from the spec. The check named "scanpy and
squidpy load inside the bundle" only read the tool catalogue. Two of twelve
plannable tools were dead in every shipped build and no test noticed.

## 2. The complete workflow, driven through the API

Healthy brain section, 24,406 cells, from a shut gate to a validated report.

| Stage | Time |
| --- | --- |
| health check | 0.02 s |
| scan the data folder (17 datasets, 7 reviewable) | 0.01 s |
| open a section — build the cell index | 0.68 s |
| draw the cell map (12,203 of 24,406 displayed) | 0.42 s |
| ask a question | 1.03 s |
| **descriptive lane** (gate shut) | **100.8 s** |
| — `qc_and_cluster` | 13.4 s |
| — `spatial_variable_genes` | 53.8 s |
| expert review — 16 cluster decisions + 2 regions | 17.5 s |
| re-evaluate the gate | 0.95 s |
| **validated lane** (gate open, 5 tools) | **37.3 s** |
| — `qc_and_cluster` | 10.6 s |
| — `annotation` | 0.2 s |
| — `marker_detection` | 6.7 s |
| — `region_summary` | 1.1 s |
| — `cell_neighborhood_enrichment` | 3.9 s |
| **total** | **158.7 s** |

API latency, median over 5 calls: `/api/health` 9.4 ms, `/api/datasets` 6.5 ms,
`/api/tools` 17.3 ms, `/api/resources` 10.6 ms.

Single-run timings remain indicative rather than benchmarks — `qc_and_cluster`
came out at 13.4 s and 10.6 s in the same process on the same cells.

## 3. The gate, in both directions

| | Before review | After 18 decisions |
| --- | --- | --- |
| status | `blocked_missing_validation_inputs` | `validated_ready` |
| blockers | 4 | 0 |
| label coverage | 0.0% | 100% |
| region coverage | 0.0% | 100% |
| reviewed classes | 0 | 10 |
| reviewed regions | 0 | 2 |

It shuts again on `POST /clear`, verified in both directions in the same session.
The gate is the product's central claim and it holds mechanically.

One detail worth recording: 16 cluster decisions were submitted and the label
report counted 15. The sixteenth was `cluster:unclustered`, three cells, and all
three were among the 44 that per-cell QC removed. The decision count reflects
what survived into the analysis rather than what was clicked, which is correct.

## 4. Router — 25 questions, 100% as designed

| Outcome | n | Meaning |
| --- | --- | --- |
| planned | 13 | routed to implemented tools |
| refused, tool named | 5 | no tools; named the scaffold responsible |
| partial | 3 | planned the answerable half, named the scaffold for the rest |
| declined | 4 | no tools and no claim about why |

My first scoring run marked the three partials as failures, because it assumed
"plan" and "refuse" were exclusive. They are not, and the prose is explicit:
*"Note that `spatial_deconvolution` is a scaffold, so any part of the question
needing it is not answered here."* The scoring was wrong, not the agent.

That said, `"Show cell type proportions per spot by deconvolution"` returns a
`qc_and_cluster + annotation` plan. The note is honest, but a reviewer skimming
a plan they asked for by another name is being offered a near neighbour, and
this agent's distinguishing claim is that it does not do that. Worth a decision
about whether a partial should lead with the refusal rather than the plan.

The four declines include three that earlier builds got wrong: `"What does this
healthy brain section look like?"` was answered *"the tool for it
(`multi_sample_comparison`) is a scaffold"* because `healthy` was a keyword;
`"Are any genes near the top of the section?"` routed to a permutation test on
the spatial graph because `near` matched.

## 5. Honesty surface

| Metric | Value |
| --- | --- |
| tools registered | 30 |
| plannable | 12 |
| registered scaffolds | 18 |
| **scaffolds exposed as plannable** | **0** |
| lanes blocked while the gate is shut | 4 |
| dependency insertion | 2 requested → 4 steps, plan `valid`, 2 blocked |

The two lanes say materially different things about the same section:

> **descriptive** — "every group below is data-derived — a Leiden cluster, not a
> cell type. Nothing here names a cell type, and no biological claim is made or
> implied."

> **validated** — "reviewed cell labels were applied, so groups below are named
> cell types and not clusters."

The validated report cites the absolute path of the label table it used. The
machine-readable payload now carries the gate status and states in its own
fields whether anything was reviewed, so a script reading `plan_results.json`
sees what a person reading `report.md` sees.

## 6. The finding that matters

**The agent accepted ten labels that its own marker table contradicts, and
flagged none of them.**

The labels submitted in this evaluation were deliberately arbitrary: cluster
index mapped onto a list of cell-type names, with no biological input at all.
Then `marker_detection` ran in the same job, over those labels, and produced:

| Reviewed label | Its own top markers | What those markers mean |
| --- | --- | --- |
| `EVAL_Excitatory neuron` | GJA1, AQP4, SOX9 | astrocyte |
| `EVAL_Astrocyte` | SV2B, NPTX1, SNCA | neuron |
| `EVAL_Endothelial` | LHX6, GAD2, TAC1 | inhibitory neuron |
| `EVAL_Microglia` | DCN, IGFBP7 | fibroblast / stromal |
| `EVAL_Inhibitory neuron` | TRHDE, NTNG1, RORB | excitatory neuron |

Five of five checked against canonical markers contradict the label they were
given. The run finished `succeeded`, the gate read `validated_ready`, and the
report names those cell types with no caveat anywhere that the evidence
disagrees.

The agent is not missing the capability. `spatialmind/review/sizing.py` computes
`marker_disagreement_share` and has the sentence ready:

> `-- MARKERS DISAGREE on 42% of cells; trust the markers column`

But it is reachable only from `GET /api/datasets/{id}/sizing`, the review
*planning* endpoint, and it was built to check labels a *reference* proposes.
Labels a human submits are never re-checked against the markers, and the
analysis run never calls it. The evidence and the check exist in the same
process, in the same job, and never meet.

This matters more here than it would in other software. The gate's premise is
that a human reviewed the data, and the gate enforces coverage, class count,
region count and decision count — everything except whether the labels are
consistent with the measurements. A reviewer who mislabels confidently gets the
same `validated_ready` as one who is right.

**Secondary finding: the gate opens with no recorded author.** The label table
the Studio writes has columns `cell_id, expert_label, confidence, notes,
assignment_scope`. There is no reviewer column, and `POST /assign` has no field
for one, so `label_report.reviewers` came back `{}`. The *reader* supports four
spellings — `reviewer_id`, `reviewer`, `annotator`, `curator` — for tables
authored outside the app. The app cannot populate any of them for its own. A
section can reach `validated_ready` without recording who validated it.

## 7. Packaged app

Measured on the built `.app`, healthy brain, `qc_and_cluster +
spatial_variable_genes`:

| | First analysis |
| --- | --- |
| before the kernel warmup | 199.0 s |
| warmup running, 40 s of idle first | 146.8 s |
| warmup complete | **99.3 s** |

numba's `cache=True` does not survive PyInstaller — a bundled module's
`__file__` points into the archive, so numba cannot build the source stamp its
cache index needs and silently stops caching whatever `NUMBA_CACHE_DIR` says.
Compilation cannot be avoided, so it is moved: the same tools run once over 120
synthetic cells while the window is up, which compiles the same specialisations
a real section needs.

Matrix memory at full lymph-node scale (377,985 cells × 380 genes), for one
tool call: **6.89 GB → 2.30 GB**, by dropping a `counts` layer that was a
byte-identical copy of `source_values` and by handing over rather than caching
matrices above a gigabyte.

## 8. What this evaluation did not establish

- **No biological validation.** As on 7 Sep, no validated run has used expert
  labels. These were worse than synthetic — they were wrong on purpose, to test
  whether the agent would notice. It did not.
- **One section, one donor.** Nothing here speaks to replication.
- **The windowed boot path is untested.** Splash, background app construction and
  the warmup kickoff are exercised only by opening the `.app` by hand; the smoke
  test runs headless.
- **Timings are single runs** on a warm 16-core Intel machine.

## 9. Recommendations, in order

1. **Re-check submitted labels against the markers the same run computes**, and
   surface the disagreement in the report and the payload. The computation and
   the wording already exist in `review/sizing.py`; they are wired to the wrong
   endpoint. This is the gap between "a human said so" and "the data agrees".
2. **Record the reviewer.** Add a reviewer column to `LABEL_FIELDS` and a field
   to `AssignRequest`. The reader already expects it.
3. **Decide what a partial answer leads with** — the plan or the refusal.
4. Open the packaged app by hand once before shipping it, to cover the boot path
   no automated check reaches.
