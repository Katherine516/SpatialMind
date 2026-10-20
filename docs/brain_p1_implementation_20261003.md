# Ordered Brain Validation Implementation

Date: 2026-10-03. This increment implements the engineering portions of the three
requested steps. The owner confirmed that no reviewers or completed review files
are currently available. Human biological review, model training and independent
validation therefore remain explicitly blocked.

## Status by Step

| Requested step | Implemented | Still requires evidence |
| --- | --- | --- |
| Confirm reference labels, tumor state and donors | Frozen source membership, reference decisions, label/state crosswalk, canonical donor decisions, alias-overlap checks and validators | Real curator review of each mapping, state and donor identity |
| Portable identities and sparse storage | Content-bound observation IDs, chunked standard CSR H5AD caches, exact selected-value readback, cache manifests, loader integration, duplicate-source protection | Whole-study scaling and cross-version biological duplicate reconciliation |
| Specialist labels/ROIs, then prespecified training and independent evaluation | Existing human review packets connected to an ordered preflight; mandatory approved development protocol; acceptance thresholds and protocol-bound model locks | Real specialists, reviewed decisions, matched image evidence where required and an independently reviewed external donor |

No source data was edited. No expert approval, final truth CSV or biological
performance score was manufactured. The existing external-test path remains
custodian-released and separate from development selection.

## Reference Review Packet

Local output: `outputs/brain_p1_implementation_20261003/reference_review/`.

- `source_snapshot.json`: frozen version/collection/species and source membership.
- `reference_decisions.json`: eight reference records, 28 source-label mappings
  and 114 collection/donor records. These are 110 GBmap donor strings and four
  shared Siletti donor strings, not 114 independently verified people.
- `REVIEW_GUIDE.md`: sequence, evidence fields and interpretation limits.

The mouse glioblastoma reference is recorded as excluded from direct human
transfer. The seven Siletti files share four donors; they are not seven independent
cohorts. Cross-study donor aliases remain unresolved.

Reference reviewers must record assay (scRNA/snRNA), expression layer and
semantics, label provenance, gene mapping policy, license evidence, reviewer ID,
ISO review date, confidence and evidence reference. Source version, species and
collection cannot be silently changed within the packet.

Each source label has separate fields for target lineage, Cell Ontology ID or an
explicit ontology exception, malignant state, state evidence and use for training.
An astrocyte label is not proof that a cell is nonmalignant. The validator refuses
a malignant/neoplastic source mapped silently to nonmalignant state. Unresolved
or excluded mappings still require an explicit human decision; missing rows
cannot disappear from the frozen source inventory.

Each donor requires a canonical identity, source-backed identity evidence and a
train/validation/internal_test/exclude role. Multiple source aliases can name one
canonical person, but that person cannot cross development partitions. A global
alias-review record documents the method and scope. Software checks recorded
evidence, not reviewer authenticity or the biological correctness of a donor map.

This reference packet is a curation contract, not an automatic relabeler. The
existing reviewed Xenium selector trains its reference from reviewed Xenium
training cells, not from the atlas decisions. Atlas-derived transfer candidates
must not be promoted to expert truth. A future atlas-trained model must explicitly
apply the approved crosswalk and retain the separate state target.

## Portable Sparse Storage

`spatialmind/ingestion/identity.py` computes full SHA256 source fingerprints and
observation IDs from the source fingerprint plus original cell ID. Renaming or
moving an identical source preserves its identity. Copying the same source cannot
create additional independent observations when reference files are merged.

`spatialmind/storage/reference_matrix.py` writes standard AnnData-compatible H5AD:

- Sparse CSR expression in X, with 64-bit row pointers and feature indices.
- Original feature IDs and feature-name metadata, including measured zero columns.
- Original source cell IDs, source row positions, donor IDs and portable IDs.
- Source-layer semantics, organism and explicit unapproved-cache status.
- An adjacent content manifest containing source/cache fingerprints, selected
  dimensions, nonzero count, selected value sum and readback parity.

Only selected donor labels are read. Optional sampling takes the first eligible
source rows without looking at labels; it is not class- or donor-balanced
scientific sampling. Explicit feature projection is optional. The source file
remains unchanged. Other expression layers are not materialized.

The exporter validates each selected source row before feature projection,
refusing negative/nonfinite values, fractional declared counts, malformed CSR
indices and missing donor metadata. Full-atlas symbol collisions remain preserved
under unique feature IDs; symbol-based downstream tools still reject ambiguous
selected symbols rather than silently sum them. Cache publication does not
overwrite an existing artifact. On failure, temporary files are removed; a cache
without its valid adjacent manifest is not usable through the reference loader.

The reference loader detects these caches even with auto selection, verifies
content and identity, and preserves original IDs through merges. It refuses
overlapping caches derived from the same byte-version and source cells. Distinct
byte versions of the same biological study can still contain duplicate cells;
portable source IDs are not a substitute for biological reconciliation.

Matrix working memory is bounded by row chunks, while observation/feature
metadata remains O(cells + features). Downstream legacy tools still use bounded
SpotRecord adapters. This is a sparse-native storage increment, not a claim that
the whole agent performs full-atlas analysis out of core.

## Measured Local Results

Both sources were read only from donors in the preceding draft training roles.
All features were retained for these storage checks.

| Measurement | GBmap Core | Siletti astrocytes |
| --- | ---: | ---: |
| Selected cells | 256 | 256 |
| Features retained | 27,632 | 58,232 |
| Nonzero entries | 201,293 | 395,417 |
| Selected count sum | 575,903 | 669,740 |
| Export chunk rows | 32 | 32 |
| Maximum exported chunk nonzeros | 28,042 | 59,582 |
| Wall time, including full source hashing | 25.46 s | 5.99 s |
| Maximum resident set size | 137,973,760 bytes | 169,406,464 bytes |
| Exact parity against source through independent AnnData read | Passed | Passed |
| Agent panel-projected reload | 32 cells, 316 features | 32 cells, 318 features |

These are single local technical measurements on 256 cells per file, not
full-study throughput or a biological benchmark. No training or test scores were
computed. All reloaded observation IDs matched the cache's portable identities.

Final software verification: 637/637 tests passed in 191.843 s, legacy/MVP routing
16/16 and 13/13 with four registry invariants each, all six import contracts,
compilation and documentation-count checks. Sixteen new tests exercise curation
and protocol blockers, sparse parity, identity relocation, copied-source overlap,
cache tampering, no dense conversion and failed acceptance preventing model locks.

The caches and adjacent manifests are in
`outputs/brain_p1_implementation_20261003/cache/`. The peak RSS values include the
Python/scientific runtime. Synthetic regression coverage additionally checks a
300 x 10,000 matrix with dense conversion prohibited and exact sparse parity.

## Human Review and Training Gate

The existing packet remains the authoritative place for real brain decisions:
`outputs/brain_specialist_handoff_20260927/`. Both glioblastoma and healthy brain
contain 750 selected cells; each currently has zero accepted labels and regions.

The brain single-cell specialist completes `expert_cell_labels_for_review.csv`.
The neuropathologist completes `cell_regions_for_review.csv`. They must document
the evidence actually used, including image pairing/registration when invoked.
Candidate evidence stays separate from final decisions. Completing these bounded
cohorts does not validate the entire section.

`outputs/brain_p1_implementation_20261003/development_protocol.json` is a draft,
not a signed protocol. It contains candidate neighbors/prior powers, selection
metric, tie-breaking, confidence threshold, exact reference-review bindings,
development donor evidence and acceptance thresholds. Minimum macro-F1 and
coverage are intentionally blank: the scientific team must justify and approve
them before selection, rather than adopting convenient software defaults.

`validate_brain_model.py select` now requires `--protocol`. The selector validates
real assignments, reviewed staging, reference curation, the approved protocol
and donor evidence before loading expression for selection. It uses only staged
training/validation truth. If the selected candidate misses either approved
acceptance threshold, it records development results but creates no model lock.
Passing selection freezes the exact protocol, reference decisions, source and
review hashes alongside the existing model lock. External evaluation checks the
frozen development protocol before reserving its one attempt.

The current development split is within-section spatial blocks, not donor-held-out
development. Protocol validation refuses a different scope label. The earlier
atlas audit inspected all-donor label summaries, so its proposed internal test
partition is not an untouched external benchmark. A separate independent donor
with reviewed truth, provenance and a custodian is still required.

## Commands

Run from the project root. Existing decisions and outputs are never overwritten.

```bash
.venv/bin/python scripts/advance_brain_validation.py prepare-references \
  --audit outputs/reference_readiness_20261003/reference_audit.json \
  --out outputs/reference_review_NEW

.venv/bin/python scripts/advance_brain_validation.py validate-references \
  --reference-packet outputs/brain_p1_implementation_20261003/reference_review

.venv/bin/python scripts/advance_brain_validation.py cache \
  --source data/GBmap_Core_human_glioblastoma.h5ad --layer raw.X \
  --semantics raw_counts --donor 3182 --max-cells 256 --chunk-rows 32 \
  --out outputs/reference_cache_NEW/gbmap.h5ad

.venv/bin/python scripts/advance_brain_validation.py status \
  --packet outputs/brain_specialist_handoff_20260927 \
  --reference-packet outputs/brain_p1_implementation_20261003/reference_review \
  --protocol outputs/brain_p1_implementation_20261003/development_protocol.json \
  --out outputs/brain_status_NEW
```

Status produces HTML and JSON; exit code 2 means missing review evidence, not a
crashed model. To relocate a cache, keep its `.h5ad` and `.h5ad.manifest.json`
sidecar together. Full source fingerprints are byte-version specific, so rewriting
the source intentionally creates a new source identity.

After real review and protocol approval, follow
[the staging and validation instructions](brain_review_execution.md). Do not run
external evaluation as a development smoke test.

## Remaining Dependencies

1. Named, qualified reviewers and their actual accepted decisions. The owner
   confirmed these are unavailable; no software step can supply them.
2. Source-backed label/state crosswalks and cross-study donor aliases, plus
   independently documented development-section donor identities.
3. Matched registered H&E/IHC where anatomical claims need it; DAPI and cluster
   composition alone do not establish every pathology region.
4. Scientific acceptance thresholds, sample-size rationale and an independently
   reviewed external donor with a custodian-controlled test release.
5. Larger-scale cache/downstream profiling and cross-version observation matching
   before whole-atlas or another-assay claims. File hashes provide integrity,
   not secure review authorization or external-test isolation.

The next human action is to send the existing brain handoff and the new reference
packet to the project leader for reviewer assignment. No GitHub push, packaged
app rebuild, ontology correctness claim or biological training occurred.
