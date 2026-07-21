# Validated Xenium Pilot Agent

SpatialMind now has a validated Xenium pilot layer. The pilot layer is intentionally stricter than the MVP runner: it will not run validated biological analysis until expert cell labels and user region labels are present.

## What This Adds

- Reusable pilot API in `spatialmind.pilot`.
- Single-dataset pilot CLI: `scripts/run_validated_xenium_pilot.py`.
- Multi-dataset scorecard CLI: `scripts/evaluate_xenium_pilot_readiness.py`.
- Typed Xenium MVP tool plan with plan-time dependency validation.
- Claim ledger that marks each interpretation as supported, refused, or non-biological readiness.
- Automatic limitations block generated from dataset facts, label status, region status, and tools run.
- Local MVP run record with input, artifact, figure, and table hashes.
- Label-intake validator for preflight review of `expert_cell_labels.csv` and `cell_regions.csv`.
- Review-only visualization gallery for blocked runs, so experts can inspect current labels/clusters before biological validation.
- Validation gate for:
  - Xenium cell table,
  - feature matrix,
  - morphology metadata,
  - cell/nucleus boundaries,
  - expert cell-label coverage,
  - user region-label coverage,
  - at least two biological cell classes,
  - at least two user-defined regions.
- Report outputs that explicitly separate validated-ready from blocked states.

## Current Result

The local scorecard scanned four Xenium datasets:

- breast biomarkers,
- lymph node,
- healthy brain,
- glioblastoma.

Current status: `0/4` datasets are validated-ready.

All four datasets have core Xenium assets, but all four still need:

- `expert_cell_labels.csv`
- `cell_regions.csv`

## Run Commands

Single dataset with both user-facing report formats:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/run_validated_xenium_pilot.py --data data/Human_Breast_Biomarkers_S1_Top_outs --out outputs/xenium_validated_pilot --max-records 2500 --report-format both
```

All local Xenium datasets:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/evaluate_xenium_pilot_readiness.py --data-root data --out outputs/xenium_pilot_scorecard --max-records 800
```

Label intake preflight:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/validate_xenium_label_intake.py --data data/Human_Breast_Biomarkers_S1_Top_outs --out outputs/xenium_label_intake --max-records 2500
```

## Output Artifacts

- `outputs/xenium_validated_pilot/pilot_validation.json`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.md`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.html`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.pdf` when `--report-format pdf` or `both` is selected
- `outputs/xenium_validated_pilot/expert_label_template.csv`
- `outputs/xenium_validated_pilot/region_label_template.csv`
- `outputs/xenium_validated_pilot/runs/*.json`
- `outputs/xenium_validated_pilot/review_current_label_map.png`
- `outputs/xenium_validated_pilot/review_cell_type_composition.svg`
- `outputs/xenium_validated_pilot/spatial_distribution.svg`
- `outputs/xenium_validated_pilot/spatial_distribution_interactive.html`
- `outputs/xenium_label_intake/label_intake_report.json`
- `outputs/xenium_label_intake/label_intake_report.md`
- `outputs/xenium_pilot_scorecard/pilot_readiness_scorecard.json`
- `outputs/xenium_pilot_scorecard/pilot_readiness_scorecard.md`

The single-dataset pilot currently writes:

- `tool_plan`: `qc_and_cluster -> annotation -> marker_detection -> region_summary -> cell_neighborhood_enrichment`
- `plan_validation`: invalid until expert labels and user regions are available
- `claim_summary`: one refused biological claim and one supported non-biological readiness statement
- `run_record_path`: hashed local provenance for the preparation run
- `review_figures`: QA visualizations generated from current loader labels only

## Required Inputs To Become Validated-Ready

Place these files inside the chosen Xenium output folder.

Expert labels:

```csv
cell_id,expert_label,confidence,notes
```

Recommended extended expert labels:

```csv
cell_id,expert_label,cl_id,secondary_state,confidence,notes
```

Use `docs/cell_ontology_labeling_guide.md` for the first-pass healthy brain/glioblastoma label vocabulary. The pilot accepts the minimal table, but `cl_id` and `secondary_state` should be retained for benchmark construction and reference-assist evaluation.

Region labels:

```csv
cell_id,region,region_confidence,notes
```

The default validation threshold requires at least 70% loaded-cell coverage for both files and at least two region classes unless `--allow-single-region` is explicitly passed.

## Claim Policy

Validated biological claims are allowed only after the pilot gate passes. Weak marker-rule labels and section-level placeholder regions are software QA inputs, not biological ground truth.
