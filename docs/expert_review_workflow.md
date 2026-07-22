# SpatialMind Expert Review Workflow

## Purpose

SpatialMind needs three reviewed files before it can treat cell identities, tissue regions, or spatial biological claims as ground truth:

1. `expert_cell_labels.csv`
2. `cell_regions.csv`
3. a completed `spatial_claim_truth_draft_for_review.csv`

These files cannot be downloaded as generic replacements for review. The first two must use the exact `cell_id` values from the Xenium section being analyzed, and the third must judge claims produced from those reviewed labels and regions. Public atlases, marker references, pathology images, and model suggestions are evidence for review, not substitutes for reviewer approval.

## Recommended Review Team

- A neuropathologist or neuro-oncologist defines histologic regions and adjudicates tumor-related claims.
- A brain single-cell/spatial transcriptomics analyst reviews cell labels, marker evidence, and reference transfer.
- A second reviewer resolves low-confidence or disputed cells/regions and reviews the held-out benchmark.
- Record stable reviewer IDs, review date, reference version, ontology version, and disagreements.

For a pilot, one domain expert plus one computational reviewer is acceptable. For a publication-grade benchmark, use at least two independent reviewers and adjudicate disagreements without exposing the held-out test labels to model development.

## 1. Expert Cell Labels

### Starting file

Use:

`outputs/glioblastoma_expert_review_packet_latest/expert_cell_labels_draft_for_review.csv`

The draft contains cell coordinates, current/provisional labels, graph clusters, top features, marker evidence, and machine suggestions. The suggestions are weak labels and must not be copied to the final file without review.

### Review procedure

1. Open the glioblastoma `experiment.xenium` bundle in Xenium Explorer or the SpatialMind Explorer-lite viewer.
2. Review segmentation against morphology before interpreting expression. Exclude or flag cells with poor boundaries, merged nuclei, or implausible transcript localization.
3. Review graph clusters and marker evidence, then compare them with a tissue-matched scRNA/snRNA reference.
4. Assign broad Cell Ontology-compatible cell types first. Keep tumor state, reactive state, cycling state, and uncertainty in `notes` or a secondary-state field.
5. For malignant-cell calls, require convergent evidence such as spatial context, a coherent tumor-state program, and preferably CNV or pathology evidence. A generic glial marker alone is insufficient.
6. Mark ambiguous cells as `unresolved` or an agreed parent class rather than forcing a specific label.
7. Save the approved table in the glioblastoma Xenium folder as `expert_cell_labels.csv`.

Minimum accepted columns:

```csv
cell_id,expert_label,confidence,notes
aaaaicom-1,microglial cell,0.95,PTPRC AIF1 C1QA support; reviewed by NP01
```

Recommended additions are `cl_id`, `secondary_state`, `reviewer_id`, `reviewed_at`, `reference_source`, and `review_status`. Confidence should use one documented scale, preferably `0.0` to `1.0`.

### Useful resources

- [10x Xenium Explorer](https://www.10xgenomics.com/support/software/xenium-explorer/latest)
- [Xenium Explorer cell groups and cell export](https://www.10xgenomics.com/support/software/xenium-explorer/latest/analysis/interface-and-features/nav-cells)
- [Xenium segmentation/data-quality review](https://www.10xgenomics.com/support/software/xenium-explorer/latest/analysis/interface-and-features/xe-checking-xenium-data-quality)
- [Cell Ontology in EBI OLS](https://www.ebi.ac.uk/ols4/ontologies/cl)
- [Human Brain Cell Atlas v1.0](https://cellxgene.cziscience.com/collections/283d65eb-dd53-496d-adb7-7570c7caa443)
- [GBmap human glioblastoma reference](https://cellxgene.cziscience.com/collections/999f2a15-3d7e-440b-96ae-2c806799c08c)
- [Neftel et al. IDH-wild-type GBM, GEO GSE131928](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE131928)
- [Core-to-cortex human GBM scRNA-seq](https://cellxgene.cziscience.com/collections/113a558a-e96e-4643-81db-140e95c58578)
- [Darmanis et al. infiltrating-front GBM reference](https://cellxgene.cziscience.com/collections/558385a4-b7b7-4eca-af0c-9e54d010e8dc)

Before reference transfer, record the dataset license, consent/data-use restrictions, sample disease state, brain region, assay, preprocessing, feature overlap with the Xenium panel, and ontology mapping.

## 2. Cell Regions

### Starting file

Use:

`outputs/glioblastoma_expert_review_packet_latest/cell_regions_draft_for_review.csv`

The draft spatial bins are navigation aids, not biological ROIs.

### Review procedure

1. A neuropathology reviewer draws polygons using the morphology image and any available aligned H&E/IF image.
2. Use a controlled region vocabulary appropriate to the section, for example `tumor_core`, `infiltrative_margin`, `microvascular_proliferation`, `necrosis`, `reactive_brain`, and `normal_appearing_brain`.
3. Export polygons from Xenium Explorer or QuPath. Preserve the coordinate system and units; Xenium cell centroids are in micrometers, while QuPath exports commonly use full-resolution pixel coordinates.
4. Perform point-in-polygon assignment of each Xenium cell centroid to a reviewed ROI. Visually audit boundaries and overlapping polygons.
5. Assign `unassigned` outside reviewed tissue and document overlap precedence. Do not infer a region solely from cell type.
6. Save the approved table in the glioblastoma Xenium folder as `cell_regions.csv`.

Minimum accepted columns:

```csv
cell_id,region,region_confidence,notes
aaaaicom-1,infiltrative_margin,0.90,inside NP01-reviewed polygon margin_03
```

Useful resources:

- [Xenium Explorer annotation layer](https://www.10xgenomics.com/support/software/xenium-explorer/latest/tutorials/interface-and-features/xe-selecting-multiple-regions-of-interest)
- [QuPath annotation export](https://qupath.readthedocs.io/en/latest/docs/advanced/exporting_annotations.html)

The final region table must contain at least two reviewed biological regions and cover at least 70% of the cells loaded by the selected pilot configuration. Production analysis should annotate all in-tissue cells, not only the 3,000-cell review sample.

## 3. Spatial Claim Truth

### Starting file

Use:

`outputs/claim_reliability_review_packet_v12/spatial_claim_truth_draft_for_review.csv`

Complete cell labels and regions first, rerun the validated pilot, and regenerate the claim packet. Otherwise the candidate positive claims lack computed biological evidence.

### Review procedure

For every claim selected for calibration:

- Set `reviewed_truth_label` to `1` only if the exact wording is supported by reviewed labels/regions, statistical output, robustness controls, and domain evidence.
- Set it to `0` if the claim is false, unsupported, overstated, or should have been refused.
- Set `use_for_calibration` to `yes` only when enough evidence exists to judge the claim.
- Fill `reviewer_id`, `reviewed_at`, `truth_basis`, `source_citation`, and `notes`.
- Keep train/validation/test splits stable. Reviewers may adjudicate test truth, but model developers should not tune against it.
- Include positive claims, negative claims, coordinate-permutation nulls, label-shuffle nulls, and difficult ambiguous cases.

The software minimum is four usable reviewed claims with at least one positive and one negative. That only checks plumbing. A serious pilot should target at least 50 to 100 reviewed claims across multiple sections and reviewers, with a held-out dataset-level test split.

## Validation Commands

Validate glioblastoma label and region coverage:

```bash
.venv/bin/python scripts/validate_xenium_label_intake.py \
  --data "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs" \
  --out outputs/glioblastoma_label_intake_reviewed \
  --max-records 3000
```

Validate the completed claim-truth table:

```bash
.venv/bin/python scripts/prepare_claim_reliability_review_packet.py \
  --out outputs/claim_reliability_reviewed \
  --validate-truth /path/to/completed_spatial_claim_truth.csv
```

Fit the claim-reliability calibration after validation passes:

```bash
.venv/bin/python scripts/train_claim_reliability_local.py \
  --out outputs/training/human_brain_claim_reliability_reviewed \
  --max-records 3000 \
  --claim-truth /path/to/completed_spatial_claim_truth.csv
```

## Acceptance Checklist

- Cell IDs match the target Xenium section with no accidental cross-dataset mixing.
- At least 70% loaded-cell coverage for labels and regions; production target is all analyzable in-tissue cells.
- At least two biological cell classes and two reviewed ROI classes.
- Ontology IDs and cell-type names are versioned.
- Low-confidence and unresolved cases are retained, not silently discarded.
- Reviewer identity, date, evidence, and disagreements are auditable.
- Claim truth contains supported and unsupported examples and a held-out test split.
- Dataset license, consent/data-use terms, and PHI status are recorded before use.

