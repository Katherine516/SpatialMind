# Agent evaluation — 7 Sep 2026

An end-to-end run of the whole workflow through the packaged app, on real
sections, with what each stage cost and what it produced. Reproduce with:

```bash
python scripts/evaluate_studio_workflow.py --out outputs/studio_evaluation
python -m unittest discover -s tests -p 'test_*.py'
python -m eval.runner --cases eval/test_cases --data data/demo_manifest.json --out outputs/eval_report.json
python -m eval.runner --cases eval/mvp_cases  --data data/demo_manifest.json --out outputs/eval_mvp.json --mvp
python scripts/smoke_test_macos_app.py
```

**One correction up front.** I previously wrote that nothing had completed the
validated path. That was wrong: `outputs/workflow_demo_20260826/13_validated_v3`
reached `validated_ready` on the healthy brain section. What has never happened
is a validated run on *expert* labels — those labels are marked
`SYNTHETIC_GATE_DEMO_NOT_AN_EXPERT` in every row. The machinery has been proven;
the biology has not, and no claim from that run is licensed.

## 1. Correctness — 248 automated checks, 0 failures

| Suite | Result | Notes |
| --- | --- | --- |
| Unit and integration | **207 / 207** | includes 26 for the app |
| Legacy eval cases | **15 / 15** | mean score 1.0000 |
| MVP eval cases | **11 / 11** | mean score 1.0000 |
| Import-linter contracts | **4 / 4** | layering intact |
| Packaged-app smoke | **11 / 11** | drives the built `.app`'s API |

## 2. The gate, in both directions

Healthy brain section, 24,406 cells, evaluated through the app's own
`pilot_gate()`.

| | Unlabelled | Labelled (synthetic demo) |
| --- | --- | --- |
| status | `blocked_missing_validation_inputs` | `validated_ready` |
| blockers | 4 | 0 |
| label coverage | 0.0% | 100% |
| region coverage | 0.0% | 100% |
| cell classes | 0 | 10 |
| regions | 0 | 4 |
| evaluation time | 0.17 s | 0.74 s |

The gate blocks and opens on the evidence it is supposed to, on real data, in
under a second. This is the product's central claim and it holds.

## 3. Workflow timings — 24,362 cells, complete section

| Stage | Time |
| --- | --- |
| create app | 0.07 s |
| discover 12 datasets | 0.06 s |
| build cell index | 1.36 s |
| evaluate gate | 0.17 s |
| cells endpoint (display sample) | 0.12 s |
| **descriptive lane** | **67.8 s** |
| — `qc_and_cluster` | 29.4 s |
| — `spatial_variable_genes` | 31.7 s |
| **validated lane** (5 tools) | **29.1 s** |
| — `qc_and_cluster` | 9.7 s |
| — `annotation` | 0.1 s |
| — `marker_detection` | 6.4 s |
| — `region_summary` | 0.7 s |
| — `cell_neighborhood_enrichment` | 5.7 s |

API latency, median over 5 calls: `/api/health` 4.5 ms, `/api/datasets` 3.2 ms,
`/api/tools` 6.0 ms, `/api/resources` 4.7 ms.

**Caveat on these numbers.** `qc_and_cluster` took 29.4 s in the first run and
9.7 s in the second on identical cell counts in the same process — page cache and
BLAS warm-up. Treat single-run timings as indicative, not as benchmarks.

### The index decision, measured

| Approach | Time | Peak memory |
| --- | --- | --- |
| Cell index (ids, coordinates, clusters) | 1.55 s | +97 MB |
| Full load with the targeted panel | 6.32 s | +507 MB |

**4.1x faster, 5.2x less memory.** Review Studio needs an id, a coordinate and a
group; it does not need expression. That is why the map opens in about a second.

## 4. Honesty surface

| Metric | Value |
| --- | --- |
| tools registered | 30 |
| plannable | 12 |
| registered scaffolds | 18 |
| **scaffolds exposed as plannable** | **0** |
| tools whose lane is `blocked` while the gate is shut | 4 |
| dependency insertion | 2 requested → 4 steps, plan `valid`, 2 blocked |

Five questions were put to the router:

| Question | Tools planned | Outcome |
| --- | --- | --- |
| spatially structured genes | 2 | planned, descriptive lane |
| cell types next to each other | 3 | planned, 2 steps gate-blocked |
| malignant cells by copy number | 0 | **refused**, named `cnv_inference` |
| ligand–receptor communication | 0 | **refused**, named `ligand_receptor_analysis` |
| weather in Oslo | 0 | declined, no route claimed |

Three of five produced no tools; two of those named the specific scaffold that
would have been needed. The router does not substitute a near-miss.

## 5. Claims and reliability

From the validated run (3 claims: 2 supported, 1 dropped):

| Claim type | S | A | P | R | Reliability | Limiting |
| --- | --- | --- | --- | --- | --- | --- |
| cell_type_annotation | 1.000 | 0.862 | **0.667** | 1.000 | **0.667** | P_panel |
| visual_pattern | 1.000 | 0.862 | **0.500** | 1.000 | **0.500** | P_panel |
| spatial_colocalization | 1.000 | 0.862 | **0.667** | 0.964 | **0.667** | P_panel |

`method = weakest_link`, `calibration_model = None`.

## 6. The finding that matters

**The panel is the binding constraint on every claim, and nothing about the
review can change it.**

In three claims out of three, the limiting component was `P_panel`. Statistics
scored 1.000, annotation 0.862, spatial robustness 0.964–1.000. Reliability is a
weakest-link score, so a reviewer who labels every cell perfectly moves `A` from
0.862 to at most 1.0 and the claim's reliability **does not move at all**.

Computed up front from `gene_panel.json`, before any labelling:

```
panel features : 339
markers        : 34 of 51 canonical markers measured
ceiling        : 0.6667
```

That reproduces exactly the `34 of 51` the pipeline computed post-hoc. Per
lineage:

| Lineage | Measured | Ceiling | Missing |
| --- | --- | --- | --- |
| endothelial | 2 / 6 | 0.33 | CLDN5, KDR, RAMP2, VWF |
| stromal | 2 / 6 | 0.33 | ACTA2, COL1A1, LUM, PDGFRB |
| astrocyte | 3 / 5 | 0.60 | **GFAP**, SLC1A3 |
| neuronal | 5 / 8 | 0.62 | RBFOX3, SNAP25, SYT1 |

`GFAP` — the canonical astrocyte marker — is not on this panel at all.

**What this means in practice.** Labelling buys you *which claims are possible*,
not *how reliable they are*. A day of expert review unlocks cell-type and region
claims that are currently refused outright; it will not raise any of them above
0.67. Vascular and stromal claims on this panel start at 0.33 and should
probably not be attempted. That is worth knowing before the day is spent, which
is why the ceiling is now shown on the Readiness screen rather than discovered in
the report afterwards.

## 7. What the numbers do not say

- **Reliability is uncalibrated for biology.** `calibration_model` is `None` in
  the pilot, deliberately. It has since been calibrated against matched
  permutation-null and stripe-implant controls (AUROC 0.975, see
  [`claim_reliability_calibration.md`](claim_reliability_calibration.md)), which
  established that the score separates real structure from noise — and found
  that it previously did not, scoring 0.35 against those controls because
  statistical strength grew with the number of cell types. That is fixed. It
  says nothing about whether a claim is biologically true. These are
  conservative floors over four evidence components, not probabilities that a
  claim is true, and must not be read as accuracy. Calibrating them needs a
  claim truth set that does not exist yet.
- **No biology has been validated.** Every validated run to date used
  `SYNTHETIC_GATE_DEMO_NOT_AN_EXPERT` labels. The pipeline is proven; the
  science is not.
- **Timings are single-run.** See the warm-up caveat above.
- **One architecture.** All measurements are x86_64; nothing here has run on
  Apple Silicon.
