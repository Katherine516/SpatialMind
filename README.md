# SpatialMind

This repository implements SpatialMind, an agentic spatial omics analysis system that converts biological questions into validated local workflows. The current active product path is a Xenium pilot agent: it can ingest real wet-lab platform outputs after instrument processing, prepare expert-review templates, run gated MVP analyses, generate comprehensive reports, and refuse validated biological claims until expert cell labels and user region labels are supplied.

1. Data ingestion
2. Algorithm engine
3. LLM-style reasoning and planning
4. Visualization
5. Memory
6. Storage and provenance

The base path remains dependency-light for fast testing, while the full workstation environment in `requirements.txt` enables real H5AD/Xenium ingestion and Scanpy/Squidpy-backed wrappers.

## Architecture

```mermaid
flowchart TB
    WetLab["Wet-lab output\nXenium folders, H5AD, CSV/manifest,\ncell tables, feature matrices, morphology metadata,\nboundaries, panel metadata"]
    Governance["Governance intake\nsource, license, consent class,\nPHI risk, allowed use"]
    Ingestion["Ingestion layer\nformat detection, QC, normalization,\ncell_id preservation, Xenium H5 loading,\nAnnData/H5AD loading, readiness reports"]
    Contract["Shared data contracts\nSpatialDataset, SpotRecord,\nCellByFeatureContract, ToolResult,\nclaim and metric contracts"]
    Review["Expert review layer\nlabel templates, ROI templates,\nCell Ontology guidance, astrocyte prefill,\nvalidated label/region intake gates"]
    Planner["Agent planning layer\ndeterministic planner or hosted LLM JSON plan,\ntool registry validation, dependency checks,\nclarification/refusal behavior"]
    Tools["Analysis tools\nScanpy DE/clustering/HVG,\nSquidpy neighborhood enrichment,\nannotation, marker detection,\nfeature overlay, region summary"]
    Claims["Grounding and claim ledger\npreconditions, caveats,\nunsupported-claim refusal,\ntargeted-panel warnings"]
    Viz["Visualization and reports\nreview maps, cluster maps,\ncomposition charts, static SVG/PNG,\ninteractive HTML, markdown/HTML reports"]
    Storage["Storage and replay\nrun records, hashes,\nSQLite index, replay checks,\nprovenance metadata"]
    Outputs["Research outputs\nvalidated pilot report,\nreview packet, benchmark gate,\nreference-assist gate,\nhealthy-vs-disease comparison gate"]

    WetLab --> Governance
    WetLab --> Ingestion
    Governance --> Contract
    Ingestion --> Contract
    Contract --> Review
    Review --> Planner
    Contract --> Planner
    Planner --> Tools
    Review --> Tools
    Tools --> Claims
    Claims --> Viz
    Tools --> Viz
    Viz --> Storage
    Claims --> Storage
    Storage --> Outputs
```

Layer responsibilities:

- **Wet-lab input layer** receives instrument/software outputs, not primary sequencing basecalls. Today this means Xenium output folders, H5AD/AnnData files, tidy CSV tables, and manifest JSON.
- **Governance layer** records dataset source, license, consent/PHI status, and allowed use before data becomes reusable.
- **Ingestion layer** converts raw platform outputs into one internal `SpatialDataset` with cell IDs, coordinates, features, labels if present, QC metrics, and processing notes.
- **Contract layer** keeps all downstream tools honest by carrying assay subtype, targeted-panel status, segmentation references, coordinates, feature metadata, metrics, and caveats.
- **Expert review layer** creates label/ROI templates and ontology-guided prefill files, then blocks validated biological analysis until `expert_cell_labels.csv` and `cell_regions.csv` pass coverage and diversity gates.
- **Planning layer** turns user intent into a typed tool plan. Hosted LLMs can propose JSON plans, but local validators decide what can run.
- **Tool layer** runs real wrappers where available: Scanpy for differential expression, clustering, and variable genes; Squidpy for neighborhood enrichment; local fallbacks only for development/debugging.
- **Grounding layer** separates supported non-biological readiness statements from validated biological claims and refuses unsupported interpretations.
- **Visualization/report layer** generates review figures, static/interactive spatial maps, machine-readable outputs, and markdown/HTML reports.
- **Storage/replay layer** writes run records, hashes, SQLite indexes, and replay metadata so analyses can be audited.

## Wet-Lab Raw Data To Report Capability

SpatialMind can already perform the engineering path from wet-lab platform output to a comprehensive report for supported formats:

```text
Xenium output folder / H5AD / CSV manifest
-> ingestion and QC
-> readiness and governance checks
-> review packet or validated analysis gate
-> tool execution when inputs pass
-> visualizations and report
-> provenance, hashes, replay metadata
```

Current capability status:

| Stage | Status | Notes |
| --- | --- | --- |
| Xenium output ingestion | Ready | Reads `.xenium` descriptors or output folders, cell tables, coordinates, gene panel metadata, H5 feature matrix, morphology metadata, and boundaries. |
| H5AD ingestion | Ready when AnnData is installed | Supports expression matrix, obs/var metadata, and spatial coordinates. |
| Tidy CSV/manifest ingestion | Ready | Useful for exported wet-lab/computational tables and demo fixtures. |
| Direct FASTQ/BCL processing | Not in scope | Use platform pipelines first, then provide Xenium/AnnData/CSV outputs. |
| Morphology image interpretation | Metadata/review support | Morphology files are tracked and review maps are produced; automated pathology interpretation is not claimed. |
| Explorer-lite review UI | Ready for local review prep | Generates a browser-based cell map with filters, selection, cell inspection, ROI/label editing, and CSV export. |
| Expert cell labels | Blocked until human review | Use `expert_cell_labels.csv`; review templates are generated. |
| User ROI/tissue regions | Blocked until human review | Use `cell_regions.csv`; region templates are generated. |
| Validated biological report | Conditionally ready | Runs only when label and region gates pass. Otherwise produces a comprehensive blocked/readiness/review report. |
| Claim-level reliability scoring | Ready as conservative v12 baseline | Every report claim receives S/A/P/R component scores and a weakest-link reliability score. Calibrated reliability is blocked until expert-reviewed claim truth exists. |
| LLM planning | Ready but optional | OpenAI/Anthropic adapters exist; LLM output remains locally validated before execution. |
| Production multi-user deployment | Partial | API, batch scaffolding, and storage exist; auth, dataset allowlists, job queue hardening, and audit logs are still needed. |

Bottom line: the agent is capable of ingesting supported wet-lab platform outputs and generating a comprehensive engineering/review report now. It becomes capable of generating a validated biological interpretation report after expert cell labels, ROI regions, and governance metadata are supplied.

## Claim-Level Reliability

The v12 agent adds a claim-level reliability layer. The scoring unit is one individual claim in the report, not the whole run. Each claim is decomposed into four interpretable components:

- `S_statistical`: strength of statistical evidence, such as adjusted p-values, z-scores, or effect sizes.
- `A_annotation`: expert-label or validated reference-label support, including coverage and confidence.
- `P_panel`: whether the targeted panel contains enough markers to support the claim.
- `R_spatial_robustness`: whether spatial evidence survives radius/graph/permutation checks.

The current production-safe baseline is a weakest-link score:

```text
claim_reliability = min(S_statistical, A_annotation, P_panel, R_spatial_robustness)
```

This deliberately keeps unsupported biological claims at `0.0` when any required evidence class is missing. A calibrated logistic combiner is scaffolded, but it stays marked `not_fit` until the project has expert-reviewed spatial claim truth labels.

Run the local human-brain reliability pass:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/train_claim_reliability_local.py \
  --out outputs/training/human_brain_claim_reliability_v12 \
  --max-records 800
```

Latest result on the local healthy-brain and glioblastoma Xenium datasets:

- `8` claim/control records were generated.
- AUROC on local refusal/null controls was `1.0000`.
- Calibrated model status is `not_fit`.
- Biological claims remain blocked at reliability `0.0000` because reviewed expert labels and ROI regions are missing.
- Non-biological dataset-readiness claims score `0.7500` because they are supported by asset checks but are not biological findings.

Generated artifacts:

- `outputs/training/human_brain_claim_reliability_v12/claim_reliability_training_report.md`
- `outputs/training/human_brain_claim_reliability_v12/claim_reliability_training_records.json`
- `outputs/training/human_brain_claim_reliability_v12/healthy_brain_pilot/validated_xenium_pilot_report.html`
- `outputs/training/human_brain_claim_reliability_v12/glioblastoma_pilot/validated_xenium_pilot_report.html`

To turn this into a real calibrated reliability model, add reviewed `expert_cell_labels.csv`, reviewed `cell_regions.csv`, literature-anchored positive spatial claims, coordinate-permutation nulls, label-shuffle nulls, and a held-out cross-dataset validation split.

Prepare the expert claim-truth review packet:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/prepare_claim_reliability_review_packet.py \
  --out outputs/claim_reliability_review_packet_v12 \
  --max-records 800
```

This writes:

- `outputs/claim_reliability_review_packet_v12/spatial_claim_truth_draft_for_review.csv`
- `outputs/claim_reliability_review_packet_v12/README.md`
- `outputs/claim_reliability_review_packet_v12/claim_truth_review_summary.json`
- per-dataset pilot reports under `outputs/claim_reliability_review_packet_v12/pilot_outputs/`

After a reviewer completes `reviewed_truth_label`, `use_for_calibration`, `truth_basis`, `source_citation`, and `reviewer_id`, validate the table:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/prepare_claim_reliability_review_packet.py \
  --out outputs/claim_reliability_review_packet_v12 \
  --validate-truth outputs/claim_reliability_review_packet_v12/spatial_claim_truth_draft_for_review.csv
```

Then train the calibrated reliability model:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/train_claim_reliability_local.py \
  --out outputs/training/human_brain_claim_reliability_review_gate_v12 \
  --max-records 800 \
  --claim-truth outputs/claim_reliability_review_packet_v12/spatial_claim_truth_draft_for_review.csv
```

The current unreviewed draft correctly remains blocked: `0` reviewed calibration records, no positive reviewed claims, and no negative reviewed claims.

## Xenium Explorer-Style Entry Point

SpatialMind now accepts the same `experiment.xenium` descriptor that users normally open from a Xenium output bundle. The agent parses the descriptor, resolves linked morphology/zarr/summary assets, then ingests the sibling Xenium output folder.

Example:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/run_validated_xenium_pilot.py \
  --data "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs/experiment.xenium" \
  --out outputs/xenium_brain_glioblastoma_pilot \
  --max-records 2500
```

Supported now:

- `.xenium` JSON metadata parsing,
- linked asset resolution for morphology, zarr, analysis summary, and Explorer assets,
- cell table and coordinate loading,
- H5 feature matrix loading,
- panel and run metadata preservation,
- report-ready provenance showing the `.xenium` file used as input,
- Explorer-lite local HTML viewer for filtering, selecting cells, inspecting cell details, assigning draft ROI/labels, and exporting `cell_regions.csv` / `expert_cell_labels.csv`.

Still not a full Xenium Explorer replacement:

- no full GUI image pyramid viewer,
- no segmentation-boundary-aware image overlay editing,
- no persistent browser-side label database,
- no full zarr-backed image/cell browser.

Recommended workflow: use the Explorer-lite viewer for fast cell-level review preparation and CSV export. Use Xenium Explorer, QuPath, or napari when morphology image context, segmentation boundaries, or pathology-grade ROI drawing are required, then let SpatialMind ingest the resulting label/region CSVs and generate the validated report.

Build the viewer directly:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/build_xenium_explorer_lite.py \
  --data "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs/experiment.xenium" \
  --out outputs/xenium_brain_healthy_explorer_lite \
  --max-records 1200
```

The validated pilot also writes `explorer_lite_viewer.html` into its output folder as a review artifact.

## Try It

```bash
python3 -m spatialmind.cli "Show me the spatial distribution of CD8+ T cells relative to tumor cells in sample BRCA_04, and tell me if there is significant co-localization." --data data/demo_spatial.csv --out outputs
```

By default the planning layer is deterministic and offline. Hosted providers require an API key and an explicit model name, so model upgrades stay visible:

```bash
OPENAI_API_KEY=... python3 -m spatialmind.cli "Show CD8+ T cells near tumor cells in sample BRCA_04" --llm-provider openai --llm-model gpt-5.4
ANTHROPIC_API_KEY=... python3 -m spatialmind.cli "Show CD8+ T cells near tumor cells in sample BRCA_04" --llm-provider anthropic --llm-model claude-sonnet-4-6
ANTHROPIC_API_KEY=... python3 -m spatialmind.cli "Show CD8+ T cells near tumor cells in sample BRCA_04" --llm-provider anthropic --llm-model claude-opus-4-7
```

The command creates a run folder under `outputs/` with:

- `execution_plan.json`
- `provenance.json`
- `spatial_distribution.svg`
- `report.html`
- machine-readable algorithm outputs

You can also point the agent at a multi-source manifest:

```bash
python3 -m spatialmind.cli "Show CD8+ T cells near tumor cells in sample BRCA_04" --data data/demo_manifest.json
```

## Run Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

## Full Research Environment

The full local environment has been validated with Scanpy, Squidpy, AnnData, h5py, NumPy, SciPy, Pandas, Matplotlib, Seaborn, and the supporting spatial omics stack. For real Xenium H5/H5AD workflows, use one of the full environment paths:

```bash
python3 -m pip install -r requirements.txt
```

or:

```bash
conda env create -f environment.yml
conda activate spatialmind
```

## Run Eval

```bash
python3 -m eval.runner --cases eval/test_cases --data data/demo_manifest.json --out outputs/eval_report.json
```

For the current v7 MVP policy, run the trimmed scRNA/scATAC/Xenium eval set:

```bash
python3 -m eval.runner --mvp --cases eval/mvp_cases --data data/demo_manifest.json --out outputs/mvp_eval_report.json
```

## Latest Xenium Breast MVP Run

The current end-to-end MVP run uses the local Xenium breast biomarker dataset:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/run_xenium_breast_mvp.py
```

Current generated artifacts:

- `outputs/xenium_breast_mvp/xenium_breast_mvp_report.html`
- `outputs/xenium_breast_mvp/xenium_breast_cluster.png`
- `outputs/xenium_breast_mvp/spatial_distribution.svg`
- `outputs/xenium_breast_mvp/spatial_distribution_interactive.html`
- `outputs/xenium_breast_mvp/run_summary.json`
- `outputs/xenium_breast_mvp/runs/mvp_20260613T052116Z_dcea0ca0.json`

The run samples 6,000 cells from `data/Human_Breast_Biomarkers_S1_Top_outs`, loads 390 targeted panel features, applies conservative breast marker-rule labels when expert labels are absent, executes `qc_and_cluster`, `annotation`, `marker_detection`, and `cell_neighborhood_enrichment`, and generates a cluster-style spatial visualization similar to the requested Xenium reference figure.

Important caveat: the breast labels are rule-based MVP labels, not expert-validated cell-type calls. They are useful for exercising the agent, report, and visualization flow, but they should be replaced with validated reference transfer or expert annotation before biological claims are treated as study findings.

## Expert-Label-Ready Xenium MVP

SpatialMind now has a label-readiness layer for Xenium MVP work:

- `SpotRecord.cell_id` is preserved for Xenium/H5AD/table records.
- `.xenium` files are accepted as direct input and resolved to the sibling Xenium output folder.
- External label tables can be applied by `cell_id`.
- Accepted label filenames include `expert_cell_labels.csv`, `cell_labels.csv`, `cell_annotations.csv`, `annotations.csv`, and `labels.csv`.
- Required columns are `cell_id` plus one label column such as `expert_label`, `cell_type`, `annotation`, or `label`.
- Optional confidence columns such as `confidence`, `score`, or `probability` are summarized in run metadata.

Run the local Xenium readiness inventory:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/prepare_xenium_expert_mvp.py
```

Generated readiness outputs:

- `outputs/xenium_expert_mvp_readiness/summary.json`
- `outputs/xenium_expert_mvp_readiness/xenium_expert_mvp_readiness.md`
- one `expert_label_template.csv` per local Xenium dataset.

Current result: all four local Xenium folders have cell tables, HDF5 feature matrices, morphology assets, boundaries, and 10x analysis clusters. The generated templates include `graph_cluster`, `top_features`, and `marker_evidence` to support review. None currently has an expert or validated reference-transfer label table, so the next required input is biological cell labels keyed by Xenium `cell_id`.

## Validated Xenium Pilot

The validated pilot layer lives in `spatialmind.pilot` and is exposed through:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/run_validated_xenium_pilot.py --data data/Human_Breast_Biomarkers_S1_Top_outs --out outputs/xenium_validated_pilot --max-records 2500
```

It produces:

- `outputs/xenium_validated_pilot/pilot_validation.json`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.md`
- `outputs/xenium_validated_pilot/validated_xenium_pilot_report.html`
- `outputs/xenium_validated_pilot/expert_label_template.csv`
- `outputs/xenium_validated_pilot/region_label_template.csv`
- `outputs/xenium_validated_pilot/runs/*.json`

The v11 pilot promotion adds the real-agent control layer around this workflow:

- typed Xenium MVP plan with dependency validation before tools run,
- strict readiness refusal before biological claims are emitted,
- claim ledger that separates refused biological claims from supported readiness statements,
- automatic limitations generated from label, region, panel, and tool facts,
- review-only visualization gallery for blocked runs,
- local run record with hashes for inputs, reports, templates, and figures.

Before rerunning the validated pilot with new reviewer files, validate label intake:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/validate_xenium_label_intake.py --data data/Human_Breast_Biomarkers_S1_Top_outs --out outputs/xenium_label_intake --max-records 2500
```

This writes:

- `outputs/xenium_label_intake/label_intake_report.json`
- `outputs/xenium_label_intake/label_intake_report.md`

Blocked validated-pilot runs still generate review-only visual artifacts:

- `outputs/xenium_validated_pilot/review_current_label_map.png`
- `outputs/xenium_validated_pilot/review_cell_type_composition.svg`
- `outputs/xenium_validated_pilot/spatial_distribution.svg`
- `outputs/xenium_validated_pilot/spatial_distribution_interactive.html`
- `outputs/xenium_validated_pilot/explorer_lite_viewer.html`

To run the full local promotion workflow across everything under `data/`:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/promote_local_agent.py --data-root data --out outputs/agent_promotion --max-records 800
```

This creates:

- `outputs/agent_promotion/local_promotion_report.json`
- `outputs/agent_promotion/local_promotion_report.md`
- one review packet per local Xenium dataset under `outputs/agent_promotion/review_packets/`

Governance and replay utilities:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/build_dataset_governance_manifest.py --data-root data --out outputs/governance/dataset_governance_manifest.json
.venv/bin/python scripts/index_run_database.py --outputs-root outputs --db outputs/spatialmind_runs.sqlite
.venv/bin/python scripts/replay_run.py outputs/xenium_validated_pilot/runs/mvp_20260627T070618Z_f6c76103.json
```

These create a reviewable governance manifest, a local SQLite run index, and hash-verified replay checks for run records.

Run the all-dataset pilot scorecard:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/evaluate_xenium_pilot_readiness.py --data-root data --out outputs/xenium_pilot_scorecard --max-records 800
```

Current result: `0/4` local Xenium datasets are validated-ready. All four have the raw assets needed for a pilot, but all four still need `expert_cell_labels.csv` and `cell_regions.csv`.

## Glioblastoma Expert Review

The glioblastoma pilot now has a dedicated expert-review packet and downstream gates:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/prepare_glioblastoma_review_packet.py --max-records 2500
.venv/bin/python scripts/build_glioblastoma_benchmark.py --max-records 2500
.venv/bin/python scripts/run_tissue_reference_assist.py --max-records 2500
.venv/bin/python scripts/build_brain_comparison_report.py --max-records 2500
```

The review packet writes:

- `outputs/glioblastoma_expert_review_packet/expert_cell_labels_draft_for_review.csv`
- `outputs/glioblastoma_expert_review_packet/cell_regions_draft_for_review.csv`
- `outputs/glioblastoma_expert_review_packet/README.md`
- copied review figures and the latest glioblastoma pilot report

These draft files are not treated as expert truth. After review, save completed files into the glioblastoma Xenium folder as `expert_cell_labels.csv` and `cell_regions.csv`. The benchmark, validated annotation, marker detection, region summary, neighborhood enrichment, tissue-reference assist, and healthy-vs-glioblastoma comparison will run only after the corresponding validation gates pass. Healthy-vs-glioblastoma comparison also requires the healthy brain dataset to have reviewed labels and regions.

### Cell Ontology Label Set

For the first validated glioblastoma/brain pilot, use broad Cell Ontology-compatible labels in `expert_cell_labels.csv` and keep disease programs in notes or a secondary column. See `docs/cell_ontology_labeling_guide.md`.

Recommended first-pass `expert_label` values:

- `astrocyte` (`CL:0000127`)
- `oligodendrocyte` (`CL:0000128`)
- `microglial cell` (`CL:0000129`)
- `neuron` (`CL:0000540`)
- `oligodendrocyte precursor cell` (`CL:0002453`)
- `endothelial cell` (`CL:0000115`)
- `pericyte` (`CL:0000669`)
- `fibroblast` (`CL:0000057`)
- `macrophage` (`CL:0000235`)
- `T cell` (`CL:0000084`)
- `CD4-positive, alpha-beta T cell` (`CL:0000624`)
- `CD8-positive, alpha-beta T cell` (`CL:0000625`)
- `B cell` (`CL:0000236`)
- `plasma cell` (`CL:0000786`)
- `natural killer cell` (`CL:0000623`)
- `dendritic cell` (`CL:0000451`)
- `epithelial cell` (`CL:0000066`)
- `neoplastic cell` (`CL:0001064`)
- `unknown` / `unresolved` for ambiguous cells

The local astrocyte Cell Ontology JSON is stored at `data/cell_ontology_terms/CL_0000127_astrocyte.json`. To generate review-only astrocyte suggestions from the glioblastoma data:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/write_astrocyte_label_suggestions.py --max-records 2500
```

This writes `outputs/glioblastoma_expert_review_packet/expert_cell_labels_astrocyte_prefill_for_review.csv`. It is not a final expert label file.

Recommended extended label table:

```csv
cell_id,expert_label,cl_id,secondary_state,confidence,notes
```

`secondary_state` can hold glioblastoma-specific states such as `glioblastoma_like`, `cycling`, `hypoxic`, `reactive`, `infiltrating`, or `perivascular`. The validated pilot only requires `cell_id,expert_label,confidence,notes`, but keeping `cl_id` and `secondary_state` makes later benchmarking much cleaner.

Recommended first-pass ROI labels for `cell_regions.csv`:

- `tumor_core`
- `infiltrative_margin`
- `reactive_glia_rich`
- `immune_rich`
- `vascular_perivascular`
- `necrotic_hypoxic`
- `white_matter`
- `gray_matter`
- `normal_appearing_brain`
- `artifact_or_low_quality`

### External Links

Cell labels and ontology:

- [Cell Ontology in OLS](https://www.ebi.ac.uk/ols4/search?q=label&ontology=cl)
- [Cell Ontology home](https://obophenotype.github.io/cell-ontology/)
- [Astrocyte `CL:0000127`](http://purl.obolibrary.org/obo/CL_0000127)
- [Oligodendrocyte `CL:0000128`](http://purl.obolibrary.org/obo/CL_0000128)
- [Microglial cell `CL:0000129`](http://purl.obolibrary.org/obo/CL_0000129)
- [Neuron `CL:0000540`](http://purl.obolibrary.org/obo/CL_0000540)
- [Oligodendrocyte precursor cell `CL:0002453`](http://purl.obolibrary.org/obo/CL_0002453)
- [Endothelial cell `CL:0000115`](http://purl.obolibrary.org/obo/CL_0000115)
- [Pericyte `CL:0000669`](http://purl.obolibrary.org/obo/CL_0000669)
- [Fibroblast `CL:0000057`](http://purl.obolibrary.org/obo/CL_0000057)
- [Macrophage `CL:0000235`](http://purl.obolibrary.org/obo/CL_0000235)
- [T cell `CL:0000084`](http://purl.obolibrary.org/obo/CL_0000084)
- [CD4-positive alpha-beta T cell `CL:0000624`](http://purl.obolibrary.org/obo/CL_0000624)
- [CD8-positive alpha-beta T cell `CL:0000625`](http://purl.obolibrary.org/obo/CL_0000625)
- [B cell `CL:0000236`](http://purl.obolibrary.org/obo/CL_0000236)
- [Plasma cell `CL:0000786`](http://purl.obolibrary.org/obo/CL_0000786)
- [Natural killer cell `CL:0000623`](http://purl.obolibrary.org/obo/CL_0000623)
- [Dendritic cell `CL:0000451`](http://purl.obolibrary.org/obo/CL_0000451)
- [Epithelial cell `CL:0000066`](http://purl.obolibrary.org/obo/CL_0000066)
- [Neoplastic cell `CL:0001064`](http://purl.obolibrary.org/obo/CL_0001064)
- [Uberon anatomy ontology](https://obophenotype.github.io/uberon/)

Review and annotation tools:

- [10x Xenium Explorer](https://www.10xgenomics.com/support/software/xenium-explorer/latest)
- [QuPath](https://qupath.github.io/)
- [napari](https://napari.org/stable/)

Reference and benchmark data portals:

- [CZ CELLxGENE Discover](https://cellxgene.cziscience.com/)
- [Human Cell Atlas Data Portal](https://data.humancellatlas.org/)
- [Allen Brain Knowledge Platform](https://brain-map.org/)
- [Allen Brain Knowledge resources](https://knowledge.brain-map.org/)
- [Broad Single Cell Portal](https://singlecell.broadinstitute.org/single_cell)
- [NCBI GEO](https://www.ncbi.nlm.nih.gov/geo/)
- [EBI Single Cell Expression Atlas](https://www.ebi.ac.uk/gxa/sc/home)
- [EBI BioStudies / ArrayExpress](https://www.ebi.ac.uk/biostudies/arrayexpress)
- [Ivy Glioblastoma Atlas Project](https://glioblastoma.alleninstitute.org/)
- [NCI Genomic Data Commons](https://portal.gdc.cancer.gov/)
- [TCGA overview](https://www.cancer.gov/ccg/research/genome-sequencing/tcga)

Governance, consent, and production hardening:

- [10x Genomics Terms of Use](https://www.10xgenomics.com/legal/terms-of-use)
- [NIH Genomic Data Sharing Policy](https://sharing.nih.gov/genomic-data-sharing-policy)
- [dbGaP](https://dbgap.ncbi.nlm.nih.gov/home/)
- [GDC Data Access](https://gdc.cancer.gov/access-data/data-access-processes-and-tools)
- [HHS HIPAA De-identification Guidance](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [FastAPI OAuth2 + JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
- [Celery](https://docs.celeryq.dev/en/stable/)
- [PostgreSQL docs](https://www.postgresql.org/docs/current/index.html)
- [OpenTelemetry](https://opentelemetry.io/docs/)

## Training and Evaluation Status

SpatialMind is not yet fine-tuned on expert-labeled examples. The current "training" pass is evaluation-driven agent training: we validate the planner, tool registry, grounding rules, wrappers, and refusal behavior against curated cases before collecting supervised data.

Current gates:

- Legacy eval: 15/15 passing, mean score 1.0000.
- MVP eval: 10/10 passing, mean score 1.0000.
- Unit tests: 45/45 passing in the full environment.
- Local training records: 15 records generated from demo MVP cases, a weak-label breast Xenium run, and four Xenium readiness records.
- Region-label templates: generated for all four local Xenium datasets.
- Validated pilot scorecard: 4 local Xenium datasets scanned, 0 validated-ready because expert labels and user regions are still missing.

Latest local training artifacts:

- `outputs/training/local_spatialmind_training/training_records.jsonl`
- `outputs/training/local_spatialmind_training/training_summary.json`
- `outputs/training/local_spatialmind_training/training_report.md`
- `outputs/xenium_expert_mvp_readiness/*/region_label_template.csv`
- `outputs/xenium_validated_pilot/pilot_validation.json`
- `outputs/xenium_pilot_scorecard/pilot_readiness_scorecard.md`

See `docs/training_status.md` for the exact training-data requirements and next model-development steps.

## Architecture Notes

This is not a substitute for production-grade spatial omics analysis yet. It is an agent scaffold that keeps every major responsibility explicit:

- Ingestion turns raw spatial data into one internal `SpatialDataset` contract.
- Planning turns a natural-language request into a constrained tool plan.
- Tools run biological or spatial analysis and return structured `ToolResult` objects.
- Visualization turns datasets and tool outputs into portable SVG/HTML artifacts.
- Memory stores session context, user priors, and prior run summaries.
- Storage writes reproducible run folders with reports, figures, and provenance.
- Evaluation checks whether the agent chose the expected workflows.

## Package Structure

The codebase now follows the build-plan layer boundaries while keeping backward-compatible imports:

```text
spatialmind/
  contracts/      # shared layer-boundary contracts, artifacts, claims, readiness, citations
  agent/          # orchestration, typed MVP runtime, dependency validation, response synthesis
  api/            # optional FastAPI app factory and endpoint contracts
  ingestion/      # format detection, H5AD/Xenium/table loading, QC, normalization
  memory/         # JSON-backed session memory, long-term memory, and user priors
  pilot/          # validated Xenium pilot gates, claim ledger, scorecards, and reports
  storage/        # run records, artifact paths, provenance hashes, run retrieval
  tools/          # tool registry, precondition checks, prototype and Scanpy/Squidpy wrappers
  workflows/      # v7 MVP standalone and reference-assist pipeline compositions
  viz/            # static SVG, interactive HTML, QC dashboards, report builders
```

### v7 MVP Mode

The v7 MVP makes Xenium the primary workflow and keeps scRNA/scATAC in standalone-lite or reference-assist roles. Use `SpatialAgent(mvp_mode=True)` to expose the six active MVP tools: `qc_and_cluster`, `annotation`, `marker_detection`, `feature_overlay`, `region_summary`, and `cell_neighborhood_enrichment`.

The full/default registry still contains earlier broad scaffolds for future development, but MVP mode defers trajectory, motif/chromVAR, ligand-receptor, deconvolution, pathway, CNV, and full label-transfer workflows until validated backends and datasets are available.

Compatibility modules such as `spatialmind.agent_loop` and `spatialmind.visualization` still re-export the new package implementations.

### Agent Flow

1. A user asks a biological question through the CLI/API.
2. `spatialmind.ingestion` loads the selected dataset into `SpatialDataset`.
3. `spatialmind.planner` or `spatialmind.agent.loop` converts the query into tool calls.
4. `spatialmind.tools.registry` checks whether each tool is valid for the dataset.
5. `spatialmind.tools.implementations` runs either real optional wrappers, such as Scanpy/Squidpy, or dependency-light fallbacks.
6. `spatialmind.viz` renders figures and reports.
7. `spatialmind.storage` saves artifacts and provenance.
8. `spatialmind.memory` stores useful context for future runs.

### Data Contract

The central object is `SpatialDataset`. It carries:

- `records`: one cell/spot per record with x/y coordinates, cell type, region, and numeric features.
- `sources`: original raw files, modalities, coordinate systems, and morphology image paths.
- `metadata`: dataset-level fields such as Xenium metrics, H5 matrix status, annotation method, and feature metadata.
- `qc_metrics`: record counts, feature counts, coordinate bounds, duplicate coordinates, and missing features.
- `notes`: caveats that should appear in downstream reports.

This contract lets the agent run in both dependency-light and full scientific environments, while keeping real backends isolated behind stable interfaces.

### Analysis Backends

Several tools now use optional real backends automatically:

- `differential_expression`: uses Scanpy `rank_genes_groups` when available.
- `marker_detection`: wraps adjusted-p-value marker ranking for the v7 MVP and labels scATAC outputs as gene-activity, not measured expression.
- `spatial_clustering`: uses Scanpy neighbors plus Leiden when available.
- `spatial_variable_genes`: uses Scanpy highly variable gene ranking when available.
- `neighborhood_enrichment`: uses Squidpy spatial neighbors plus neighborhood enrichment when available.

If those packages are not installed, the tools fall back to lightweight prototype behavior. Pass `engine="prototype"` in tool params to force fallback behavior during debugging.

## Dataset Inspection

```bash
python3 -m spatialmind.cli --inspect-data --data data --inspect-out outputs/dataset_report.json
```

The inspector reports which local datasets are ready for agent workflows and which blockers remain, for example missing biological cell-type labels, unsupported modality details, or missing optional readers.

## Architecture Checks

The layer plan is now partially enforced by import-linter and runtime version checks:

```bash
make check-versions
make import-lint
```

`check-versions` validates the installed scientific stack. `import-lint` checks that the shared `contracts/` package stays independent and that lower layers do not import agent/API internals.
