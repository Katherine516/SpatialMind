# Calibrating claim reliability

`S_statistical` shipped with the caveat *"heuristic until calibrated against
ground-truth positive/negative controls"*. This is that calibration, the bug it
found, and what it still cannot tell you.

```bash
python scripts/calibrate_claim_reliability.py --out outputs/claim_calibration
```

## Scope, before anything else

This calibrates whether the score **separates real spatial structure from a
permutation null**. It does *not* calibrate whether a biological claim is true.
That still needs a reviewed claim-truth table, and
`prepare_claim_reliability_review_packet` remains the route to one. The review
packet's README is right that biological calibration is blocked; this is a
narrower question that can be answered without an expert, because the truth is a
property of how the data was built.

## Why the existing null controls could not do this

`train_claim_reliability_local.py` builds two "null control" records per
dataset. Each one writes a sentence describing a permutation, scores it against
the **unpermuted** pilot payload, and labels it 0. Nothing is ever permuted. A
model fit on those rows learns to associate a label with a claim's wording, not
with its evidence.

The controls here are run. One section is loaded once; each variant reassigns
cell labels in memory and re-runs `cell_neighborhood_enrichment`, so the
z-scores the scorer reads are the ones that labelling actually produced.

| Arm | Construction | Truth |
| --- | --- | --- |
| positive | two real cell-type names interleaved in 60 µm diagonal stripes | adjacent by construction |
| negative | the positive arm's own labels permuted among the same cells | no real association |

Matched across arms: label vocabulary, marginal composition, coverage, cell
count, **pair count**. Different: whether the two labels are spatially
interleaved. 18 variants, 9 per arm, across 3 seeds × 3 coverage levels.

## The bug this found

The first grid did not match pair count — the negative arm kept the section's
ten cell types while the positive arm had two. The result:

```
Weakest-link AUROC against the controls: 0.3457
S_statistical  pos=0.479  neg=0.535  sep=-0.056
```

**Below chance.** The score ranked the permutation null *above* implanted
structure.

The cause was in `_statistical_component`, not in the data. It scored
`max|z| / 5` across every reported pair with no correction, and Squidpy's
neighborhood enrichment reports a z-score and no p-value — so the adjusted-p
branch was dead code and the maximum was always unadjusted. Ten cell types draw
that maximum from 55 pairs; two draw from 3. The larger vocabulary wins on pair
count alone.

That is not an artefact of the controls. **Any section with more cell types
scored higher on statistical strength for free.**

Two fixes:

1. **Correct for the pairs tested.** Convert the z to a two-sided p, Bonferroni-
   correct by the number of pairs, and score that. An arm's vocabulary size no
   longer buys it strength.
2. **Replace the cliff with a scale.** The old mapping, `1 - min(1, p × 20)`,
   was zero at p ≥ 0.05 and linear below. Against corrected p-values it drove
   most runs to exactly 0.000 on *both* arms — including implanted structure at
   p = 0.066 — so genuinely different evidence became indistinguishable.
   Strength is now `-log10(p) / 3`, capped: p = 0.05 → 0.43, p = 0.01 → 0.67,
   p = 0.001 → 1.00. Monotone, no discontinuity. Chosen for those properties;
   the AUROC below is a consequence, not a target.

## Result after the fix

```
Weakest-link AUROC against the controls: 0.9753
S_statistical  pos=0.465  neg=0.036  sep=+0.428
```

The corrected scorer reaches the same discrimination the confounded one appeared
to have, but earns it from evidence rather than from pair count, and separation
improves from +0.294 to +0.428.

| Component | Positive | Negative | Separation |
| --- | --- | --- | --- |
| S_statistical | 0.465 | 0.036 | **+0.428** |
| A_annotation | 0.728 | 0.728 | 0.000 |
| P_panel | 0.600 | 0.600 | 0.000 (constant) |
| R_spatial_robustness | 0.635 | 0.635 | 0.000 (constant) |

## What the fitted model is worth: not much yet

`fit_claim_reliability_calibration` returns `status: fit` on these 18 records,
training AUROC 0.9753, with weights dominated by `S_statistical` (+5.49). **Do
not deploy it.** Three reasons:

- **Only S varies.** A, P and R are constant or matched by design, so the fit is
  a univariate rescaling of S wearing four coefficients. The non-S weights are
  noise fitted to nothing.
- **18 records, 4 features, no held-out split.** Training AUROC is not a
  performance estimate. The earlier confounded grid reported training AUROC
  **1.0000** while its underlying score was *worse than chance* — a clean
  demonstration that this number measures fit, not skill.
- **The controls answer a narrower question** than the score is used for. A
  claim that survives a permutation null can still be biologically wrong.

The model is written to `outputs/claim_calibration/claim_calibration.json` for
inspection. The pilot continues to report `weakest_link` and
`calibration_model: None`, which remains the honest default.

## What would make a deployable calibrator

1. **Vary A, P and R deliberately.** Coverage sweeps move A; restricting the
   feature set moves P; the neighbourhood-radius sweep moves R. Until each
   component varies independently, no multivariate weight is identifiable.
2. **Hold out a split.** By seed at minimum, by section ideally.
3. **Reviewed biological claim truth**, which is what the review packet exists
   to collect and what no control can substitute for.
