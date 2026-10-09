# SpatialMind Data Expansion Roadmap

Date: 2026-10-03. Based on the [fresh layer evaluation](layer_evaluation_20261003.md).
This is a proposed implementation order, not a claim of completed capabilities.

Progress: the [October 3 correctness increment](correctness_upgrade_20261003.md)
implements P0 repairs and an initial P1 sparse/contract/reference-readiness
foundation. The [reference-readiness increment](reference_readiness_20261003.md)
adds explicit layer/donor ingestion, actual source audits and draft collection-wide
splits. P1 biological curation/storage and P2-P4 platform milestones remain open.

The [ordered P1 follow-up](brain_p1_implementation_20261003.md) implements
curation contracts, portable content identities, chunked sparse storage and
mandatory development-protocol gates. Real human review and independent testing
remain unavailable; downstream full-study scaling is not yet demonstrated.

## Recommended Order

| Priority | Work package | Why now | Exit criterion |
| --- | --- | --- | --- |
| P0 | Correct spatial FDR, reject nonspatial coordinates, preserve H5AD features, export every tested result | These affect numerical interpretation before any new assay | Findings F1/F2/F3/F5 have regression tests; repeated brain reports retain honest scope and complete tables |
| P0 | Stop protein misclassification, technical-feature fallback, incomplete verification and fabricated fusion metrics | Prevent known defects from becoming new adapter behavior | F4/F6/F7/F8 fail closed or return explicit unsupported/unverifiable states |
| P1 | Sparse, assay-aware data contracts and manifests | Per-cell dictionaries and dense AnnData copies do not scale to whole-transcriptome or HD data | Source-count parity, typed units/resolution, observation identity and bounded-memory tests pass |
| P1, parallel | Brain specialist review and matched histology | More software cannot replace biological evidence | Accepted review decisions, registered-image QC and a prespecified donor-level evaluation design |
| P1 | Curate existing sc/snRNA references and complete brain validation | Nine reference files are already local | Verified expression semantics, donor splits, label crosswalk, development evaluation and locked external test |
| P2 | One other cell-resolved spatial RNA platform | Reuses most of the Xenium workflow | One CosMx or MERSCOPE/MERFISH adapter with versioned fixtures, vendor parity and a gated full report |
| P2 | Visium, then Visium HD | Adds spot/bin resolution and whole-transcriptome scale | Resolution-aware QC and registration; no single-cell/contact claims from mixed spots or bins |
| P3 | Protein imaging or true ATAC, one at a time | Each requires a different measurement model | One assay-specific pipeline and independent benchmark, not just a CSV/H5AD reader |
| P4 | Cross-modal integration and broader autonomous planning | Individual modalities must work first | Evaluated matching/registration uncertainty, source-bound claims and model/provider evaluation |

P0 means the next engineering increment, not a severity label. P1 establishes a
defensible brain pilot and extension architecture. P2-P4 should follow laboratory
demand. A near-term Visium project can move ahead of CosMx, but cannot skip the
P0/P1 contracts. Adding an LLM API is not a substitute for any of these steps.

## Data Model Before New Readers

Use three concepts rather than one ever-growing `genes` dictionary:

1. **Study manifest:** donor, specimen, section, condition, batch, species, assay,
   platform/software version, accession, license/consent/PHI metadata, file hashes
   and processing history. Never infer donor independence from filenames.
2. **Assay object:** sparse cell/spot/bin-by-feature matrices, immutable source
   layers, explicit RNA counts/log values, protein intensity or ATAC accessibility
   semantics, stable feature IDs/types and measured-feature masks. A panel-absent
   feature is not zero expression. Namespace observation IDs by sample/assay while
   preserving original barcodes and donor metadata.
3. **Spatial scene:** images, labels, polygons, transcript points and named
   coordinate transforms with units, direction and section identity. Store
   embeddings separately from physical coordinates. Distinguish transcript,
   segmented cell, capture spot and bin resolution.

Add a compatibility bridge around existing tools rather than rewriting the whole
project at once. Recommendation: AnnData for matrices and SpatialData for spatial
assets/transforms. Its standard models and platform readers avoid duplicating
file-format machinery; installing the package does not integrate its readers
with SpatialMind's gates or scientific contracts.
[SpatialData models](https://spatialdata.scverse.org/en/stable/api/models.html),
[SpatialData object](https://spatialdata.scverse.org/en/stable/api/SpatialData.html),
[platform readers](https://spatialdata.scverse.org/projects/io/en/stable/).

Use MuData for genuine multimodal assay collections where needed, retaining
separate feature spaces. A container or shared barcode does not prove biological
integration. [MuData documentation](https://muon.readthedocs.io/latest/io/mudata.html).

Avoid densifying complete studies to preserve the current `SpotRecord` API. For
illustration, two float64 matrices at 100,000 cells x 20,000 genes alone consume
approximately 29.8 GiB, before graphs, caches or Python objects. This is arithmetic,
not measured application RSS. Use sparse/block operations, backed reads and
bounded plot samples without changing scientific scope.
[AnnData partial reading](https://anndata.readthedocs.io/en/stable/tutorials/notebooks/getting-started.html).
Test newer APIs in an isolated locked environment first; the evaluated workstation
uses AnnData 0.10.8, not the latest documentation build.

## Use Existing Data First

### Xenium

The five local bundles are suitable for input/QC/report regression and exploratory
clustering. Neither brain section has approved labels/regions. Historical breast
annotations are useful published-label benchmark evidence, not brain truth or a
new approval under the current review contract.

Current scope is platform-processed Xenium output, not raw imaging-cycle decoding
or validation of a segmentation model. Transcripts and Zarr archives are
catalogued, not a transcript-level analytical backend. If molecule-level questions
are needed, add lazy transcript reads, Q-score controls, assignment provenance and
transcript-to-cell agreement tests as a separate extension.
[10x Xenium output definitions](https://www.10xgenomics.com/support/software/xenium-onboard-analysis/1.9/analysis/outputs/xoa-output-understanding-outputs).

### sc/snRNA References

The local Siletti supercluster files and GBmap Core are human reference candidates,
not automatically curated training truth. The smaller GBM H5AD declares Mus
musculus and must be excluded from direct human transfer. The seven Siletti files
share four donors. Prioritize source-aware curation before unrelated modalities.

- Confirm X versus `.raw` semantics from source metadata; record normalization,
  log base, species and gene identifiers. Do not guess `raw_counts` to bypass a
  useful ambiguity refusal.
- Combine complementary classes with sample-prefixed identities. Check shared
  observations/donors before merging atlases. Preserve donor, region, disease,
  batch and assay covariates; do not silently overwrite duplicate gene symbols.
- Build an expert-approved coarse-to-fine crosswalk with Cell Ontology IDs. Keep
  lineage, malignancy/state and review status separate: an astrocyte-like tumor
  state is not automatically a nonmalignant astrocyte.
- Measure shared-panel coverage per lineage, unseen-class rejection, reference
  agreement and class balance. Reference-assisted labels remain predictions.
- Select k, priors and abstention thresholds using development data only. Freeze
  the model before a custodian releases the verified independent donor test.

Measure macro-F1, balanced accuracy, per-class recall, confusion matrices,
coverage-versus-risk and donor-level uncertainty. Agreement with computational
reference annotations is not orthogonal biological ground truth.

## New Input Families

| Family | Required data | Processing/claim boundary | Evaluation |
| --- | --- | --- | --- |
| CosMx / MERSCOPE-MERFISH RNA | Counts, panel/types, cell IDs, physical coordinates, FOV transforms, boundaries, QC; images when used | Platform controls and segmentation; explicit FOV stitching; transcript/cell distinction | Matrix/barcode parity, landmarks, equivalent spatial graphs and reviewed tissue-matched annotation |
| Visium | Space Ranger matrix, tissue positions, scale factors, histology, in-tissue mask, slide/library metadata | Spots are not cells; spatial domains first; deconvolution requires a separate validated method/reference | Count conservation, image registration, domain reproducibility and composition error against appropriate truth |
| Visium HD | Binned/segmented outputs, bin size, feature matrices/slices, masks/images, transforms | Explicit aggregation provenance and sparse/out-of-core execution; no cell-contact claim from bins | Scaling, aggregation conservation, segmentation overlap, resolution sensitivity and donor-heldout biology |
| H&E / IHC / IF | Same-section image, pixel size, channels/antibodies, transform, fit/check landmarks, reviewer approval | Registered ROI context first; pathology prediction is a separate model product | Unused-landmark target registration error and visual QC; region Dice/IoU only against independent review |
| CODEX / IMC / MIBI / mIF | Marker intensities, antibodies/channels, controls, spillover/background processing, masks, coordinates, batch | Assay-specific intensity preprocessing, not automatic RNA normalization | Control/intensity stability, batch effects, segmentation and reviewed phenotype macro-F1 |
| scATAC / spatial ATAC | Fragments/index, peaks, genome build, blacklist, TSS annotations, barcodes; physical coordinates for spatial claims | ATAC-specific QC/embeddings; activity is inferred accessibility, not measured RNA | TSS enrichment, FRiP, fragment/doublet QC, peak reproducibility, reviewed labels and donor-heldout transfer |
| Paired RNA+ATAC / RNA+protein | Both objects, verified shared-cell map or unpaired status, donor/batch/provenance | Distinguish same-cell measurement, same-section alignment and cross-donor transfer | Correspondence, held-out transfer, biological conservation under integration and modality ablation |

For raw Visium sequencing plus images, use vendor preprocessing upstream and
ingest its products first rather than embedding a new aligner in the agent.
[Space Ranger](https://www.10xgenomics.com/support/software/space-ranger/latest),
[Visium HD output metadata](https://docs.hubmapconsortium.org/doi-pages/visium-hd).

For true ATAC, wrap an established fragment/peak-aware toolchain. The current
`load_scatac` is a gene-activity adapter, not a fragment/peak pipeline.
[SnapATAC2 API](https://snapatac2.scverse.org/api/index.html).

## Acceptance Protocol

1. Freeze a supported platform/version and a small public fixture. Check file
   membership, barcodes, feature identities, units and dimensions against
   independently obtained upstream expectations.
2. Check exact integer count conservation or a declared tolerance for continuous
   intensities. Exercise duplicate IDs, unknown units, sparse/dense formats,
   corrupt files and ambiguous layers. Missing is not silently zero.
3. Route typed inputs to assay-specific processing. Reject unsupported
   modality/tool combinations before execution and preserve source values.
4. Compare outputs with direct upstream-library calls on identical input, graph,
   parameters and seeds. Check numeric parity, complete result export and backend
   failures, not only successful report generation.
5. Evaluate spatial nulls and positive controls across tissue windows, boundaries,
   density and label imbalance. Prespecify tested families, sidedness,
   permutations, adjustment and effect definitions.
6. Benchmark reviewed biological tasks using donor-disjoint splits, unknown-class
   handling, uncertainty intervals and frozen model selection. Specify task-level
   acceptance criteria before external results are examined.
7. Verify HTML/PDF/table consistency, unsupported-claim refusals, provenance and
   replay. Measure memory/time as cell, feature and image sizes increase.

A universal 90% accuracy target, or the existing two-donor minimum, is not a
power calculation. Choose biological sample sizes and success thresholds for the
actual question and required uncertainty, not for convenient software defaults.

## Expand Reliability With the Assay

Do not reuse the Xenium score unchanged for every input:

- **Statistics:** bind claims to gene/pair/contrast/region, donor/section,
  coordinate frame, effect and complete tested family. Keyword presence is not
  claim-specific evidence.
- **Annotation:** distinguish coverage, review depth, agreement and measured
  external accuracy. Coverage alone is not accuracy.
- **Feature adequacy:** use assay-specific support and missingness. RNA panel
  coverage is not antibody specificity or ATAC peak coverage.
- **Robustness:** vary graph scale/family, boundaries, density, segmentation and
  registration where relevant. Nonspatial claims use not-applicable spatial
  components, not apparent perfect biological scores.
- **Calibration:** use independently reviewed positive and negative claims,
  donor/study splits and held-out Brier/ECE/discrimination per assay and claim
  type. Synthetic readiness controls cannot establish biological probabilities.

Keep calling the present score an evidence index until a prespecified held-out
calibration study establishes a defensible probability interpretation.

## Human and Operational Dependencies

The brain single-cell specialist reviews identities, ambiguity, doublets,
marker/reference consistency and tumor-versus-normal interpretation. The
neuropathologist reviews anatomical/lesion regions and matched-image context.
These are real reviewers, not two LLM sub-agents. AI can prioritize and draft
evidence, but cannot provide their approvals.

The 750-cell packets support bounded benchmarks. Completing them does not satisfy
a 70% full-section gate on 24,406 or 40,887 cells. Plan review expansion or
justified cluster/ROI-level assignments with recorded scope; do not equate 750
per-cell decisions with validation of the whole section.

For trusted local collaborators, prioritize reproducible environments, portable
evidence manifests and packaged-source consistency. For a shared service, add
authentication, role-based authorization, dataset-root controls, durable jobs,
transactional concurrent edits, quotas, audit retention and tested backup/restore
before remote exposure. The synchronous batch endpoint is not a distributed queue.
Public redistribution clearance remains separate from per-dataset provenance.

## Best Next Move

P0 repairs and the first P1 reference-readiness increment are implemented.
Next, verify reference label crosswalks and donor/source identities while completing
sparse-native storage and portable manifests. Arrange real reviewers and matched
histology in parallel. Establish a prespecified development benchmark and acquire
independent reviewed testing before promoting another spatial RNA adapter.
