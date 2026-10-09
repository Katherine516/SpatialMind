# Correctness Upgrade and Reference Readiness

Date: 2026-10-03.

This increment follows the [layer review](layer_evaluation_20261003.md) and
[priority roadmap](multimodal_roadmap_20261003.md). It implements the eight P0
correctness repairs and the first P1 data-foundation work. It does not claim to
complete all multimodal roadmap milestones or biological validation.

## Implemented

| Review finding | Change | Verification |
| --- | --- | --- |
| F1: Selected-set spatial FDR | Removed same-data Moran candidate screening. Every gene meeting a coordinate-independent detection threshold is tested and included in BH correction. Display top-N cannot change that family. Empty eligibility does not relax the filter. | Direct Squidpy parity, family-size invariance and repeated synthetic null evaluation |
| F2: Index coordinates accepted as tissue | Shared coordinate predicate rejects embeddings, indices, unknown coordinate kinds and nonfinite values. Registry execution and spatial-gene entry points reject them; AnnData no longer exposes them as `obsm['spatial']`. | Direct execution and cache-invalidation regressions |
| F3: H5AD top-200 truncation | Scientific H5AD/Xenium ingestion defaults to all features and rejects positive per-cell caps. Duplicate mapped H5AD feature names fail explicitly. Measured-feature identities are recorded separately from detected values. | 301-feature count conservation fixture; sparse row extraction without densification |
| F4: Protein treated as RNA | Protein intensity tables preserve values, receive a proteomics contract and skip RNA threshold QC. Active RNA tools reject protein input until an assay-specific pipeline exists. | Intensity preservation, contract and tool-refusal regressions |
| F5: Incomplete spatial gene export | Tool results retain `all_tested_genes`; display rows remain limited separately. The descriptive pilot forwards the complete list, and HTML now states the testing family beside its gene table. | Both new reports export 318 rows, covering every detected biological gene |
| F6: Technical features in tiny panels | Control/QC features are always excluded, even when no biological features remain. | Empty and one-gene cases; obsolete fixture expectations corrected |
| F7: Partial provenance called verified | Missing artifact paths produce `partial`, not `verified`; replay remains blocked unless fully verified. | Mixed valid/unresolvable artifact fixture; actual runs verify 17/17 |
| F8: Invented fusion measurements | Unimplemented fusion returns null shared-cell count and quality, retaining its scaffold warning. | Disjoint-input fixture; fusion remains unavailable for planning |

These repair known software errors. They do not establish universal FDR control,
annotation accuracy, calibrated biological claim probabilities or production
multi-user readiness.

## P1 Foundation

- Generic spatial RNA is no longer classified as Xenium automatically. Unknown
  modalities fail contract construction; missing species remains unknown.
- Contracts record coordinate system/kind/units, measurement semantics and the
  declared measured-feature universe. A molecular value of zero is not evidence
  that a feature absent from the assay was measured.
- The AnnData bridge uses CSR for more than 1,024 detected biological features,
  building both analysis and source matrices without a dense intermediate.
  Existing small-panel dense behavior is preserved. QC uses sparse reductions.
- Sparse H5AD rows are extracted by stored indices and values. Full-scale input
  still uses the legacy per-cell record representation, so this is not a complete
  out-of-core redesign. Memory preflight remains a conservative dense estimate.
- `prepare_reference_curation.py` inspects HDF5 metadata without loading X. It
  creates an explicitly unapproved inventory and refuses to overwrite an
  existing file that may contain curation decisions.

All nine local H5AD candidates were inspected successfully. All expose candidate
cell-type and donor columns; two contain a `.raw` object. Those observations do
not establish what X or `.raw` represents. The manifest leaves source accession,
version, expression semantics, label provenance, donor-overlap audit, split role,
ontology mapping and curator identity unfilled. `training_ready` remains false.

The existing reference loader and label-transfer pipeline are not automatically
approved by this inventory. It is a handoff checklist, not a replacement for the
review gate or a sealed benchmark manifest.

## Real Brain Reruns

Both commands requested 1,500 evenly indexed cells, resolution 0.55, seed 0 and
100 spatial-gene permutations. They are sampled exploratory runs, not full-section
or independent-donor validation.

| Metric | Glioblastoma | Healthy brain |
| --- | ---: | ---: |
| Cells after QC | 1,495 | 1,497 |
| Expression clusters | 9 | 8 |
| Silhouette | 0.14060 | 0.08926 |
| Biological genes detected | 318 | 318 |
| Genes in complete testing family | 309 | 298 |
| Detection-filter exclusions | 9 | 20 |
| Displayed genes | 15 | 15 |
| Exported gene rows | 318 | 318 |
| Genes passing adjusted p <= 0.05 | 225 | 93 |
| Provenance checks | 17/17 | 17/17 |
| Review gate | Blocked | Blocked |

The prior 50-gene selected-set result and the new complete-family significance
counts are not an accuracy comparison. The tested family changed. These results
indicate spatial structure under the configured model, not named cell identity,
malignancy, causality or healthy-versus-tumor differential biology.

Local reports:

- [Glioblastoma HTML](../outputs/correctness_upgrade_20261003/final/glioblastoma/validated_xenium_pilot_report.html)
- [Healthy brain HTML](../outputs/correctness_upgrade_20261003/final/healthy_brain/validated_xenium_pilot_report.html)
- [Reference curation manifest](../outputs/correctness_upgrade_20261003/reference_curation_manifest.json)

## Statistical Check

The prespecified simulation used 50 seeds, a 10x10 grid, 60 independent Poisson
genes with gene-specific means, six neighbors and 199 permutations. No gene had
true spatial structure. Two of 50 trials rejected at least one gene: observed
all-null family rejection rate 0.04, Wilson 95% interval 0.0110-0.1346.

Under the complete null this rate estimates FDR, but the wide interval and simple
exchangeable null do not demonstrate control at 0.05 in real tissue. Follow-up
must include non-null mixtures, density/segmentation effects, alternate spatial
nulls and donor replication. This result is not used to tune the algorithm.

## Verification Results

- Complete suite: **602 passed, 0 failed, 0 skipped**, 192.827 seconds.
- New boundary regression module: **16/16 passed**.
- Original adversarial audit: **9/9 passed**, zero remaining finding observations.
- Legacy/MVP routing: **16/16 and 13/13**, with four registry invariants each.
- Architecture import contracts: **6/6**; compilation and documentation counts pass.
- Actual brain records: **17/17 provenance checks each**. Each gene table has
  exactly 318 unique data rows after excluding provenance comments and headers.

The first development test run found two old tests that required unsafe behavior:
reintroducing control probes and relaxing an empty detection filter. Their
expectations were corrected and the complete suite was rerun. No failing test
was skipped or removed. Report layout was not browser-tested in this increment.

## Reproduction

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/lint-imports
.venv/bin/python scripts/audit_modality_boundaries.py --out outputs/recheck
.venv/bin/python scripts/evaluate_spatial_gene_null.py --out outputs/recheck/spatial_gene_null.json
.venv/bin/python scripts/prepare_reference_curation.py --data data --out outputs/recheck/reference_curation_manifest.json
.venv/bin/python -m eval.runner --out outputs/recheck/eval_legacy.json
.venv/bin/python -m eval.runner --mvp --out outputs/recheck/eval_mvp.json
```

Evidence from this increment is in `outputs/correctness_upgrade_20261003/`.
Historical evaluation documents retain their original baseline measurements.

## Remaining Priority Order

1. **P1:** Confirm reference expression semantics and provenance with source
   documentation, audit donor overlap, and curate a tissue/disease-aware label
   crosswalk. Only then develop reference transfer on development donors.
2. **P1, parallel:** Assign real reviewers, obtain matched registered H&E/IHC,
   and complete accepted brain labels/regions and claim truth. None was invented
   or approved by this implementation.
3. **P1:** Finish sparse/source-native storage, explicit spot/bin/cell resolution,
   transform validation, stable cross-file observation identities and scaling
   tests before claiming general multimodal ingestion.
4. **P2:** Integrate one demand-driven spatial RNA platform, then resolution-aware
   Visium/HD, with vendor parity and gated biological benchmarks.
5. **P3/P4:** Implement protein or ATAC preprocessing and independent evaluation
   before genuine multimodal registration/fusion. Do not expose the current
   scaffolds as completed analysis tools.

No training run, external-test tuning, new package installation, human approval,
GitHub push or new packaged application build was performed in this increment.
