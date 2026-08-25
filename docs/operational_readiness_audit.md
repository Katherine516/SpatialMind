# SpatialMind Operational Readiness Audit

Date: 2026-06-27

## Executive Status

SpatialMind is usable now as a local, validation-gated spatial omics agent for ingestion, review packet generation, workflow planning, visualization, provenance, replay, and software QA. It is not yet a fully validated biomedical interpretation agent because the local Xenium datasets still lack expert-reviewed cell labels, user-reviewed tissue/ROI regions, tissue-matched reference labels, and biological benchmark truth.

The wet-lab-output-to-report capability is documented in `docs/wet_lab_to_report_capability.md`. In short, SpatialMind can ingest platform-processed wet-lab outputs and generate comprehensive review/readiness reports now; validated biological interpretation reports require reviewed labels and regions.

Adding an LLM API now would make the natural-language planning layer more flexible, but it would not by itself make the agent biologically validated. The agent should keep its current validation gates: hosted LLM output can propose a tool plan, but validated annotation, marker detection, region summary, neighborhood enrichment, benchmark construction, and disease comparison should only run when reviewed labels/regions and appropriate references are present.

## What Was Checked

- Repository architecture and layer boundaries.
- LLM provider wiring.
- API surface for runs, sessions, Xenium pilot intake, Xenium pilot execution, and local promotion.
- Local Xenium pilot readiness across all datasets under `data/`.
- Local promotion/gap report.
- Real Scanpy/Squidpy backend wrappers.
- MVP and legacy evaluation suites.

## Current Strengths

- Raw Xenium ingestion works from local 10x output folders.
- H5 feature matrix loading works for Xenium.
- H5AD ingestion exists when AnnData is installed.
- Scanpy wrappers pass for differential expression, clustering, and variable-gene ranking.
- Squidpy neighborhood enrichment now passes using a single-process-safe `threading` backend.
- Review-only visualizations are generated even when validated analysis is blocked.
- Expert label and region templates are generated for all local Xenium datasets.
- Glioblastoma-specific review packet and validation gates are present.
- Claim ledger and report language refuse unsupported biological claims.
- Run records, hashes, governance manifest scaffolding, and replay utilities exist.
- CLI and optional FastAPI app are available.
- OpenAI Responses and Anthropic Messages adapters are implemented behind explicit provider selection.

## Latest Audit Results

- Local promotion scan:
  - Dataset candidates: `6`
  - Xenium datasets: `4`
  - Validated-ready Xenium datasets: `0`
- Xenium pilot scorecard:
  - `0/4` local Xenium datasets are validated-ready.
  - Each local Xenium dataset is blocked by missing expert labels and missing user regions.
- Real backend validation:
  - `differential_expression`: passed with Scanpy.
  - `spatial_clustering`: passed with Scanpy.
  - `spatial_variable_genes`: passed with Scanpy.
  - `neighborhood_enrichment`: passed with Squidpy after forcing the wrapper to use `backend="threading"`.
- Eval:
  - MVP eval: `10/10`, mean score `1.0000`.
  - Legacy eval: `15/15`, mean score `1.0000`.

## If We Add An LLM API Now

The agent becomes more usable for natural-language interaction, query decomposition, and user-facing planning. It can be used to:

- interpret user requests into validated tool plans,
- route workflows through the existing CLI/API,
- summarize supported outputs and limitations,
- guide expert-review and region-review operations,
- refuse unsupported biological claims when gates fail.

It should not be used yet to:

- make disease biology claims from the glioblastoma/healthy brain Xenium data,
- benchmark annotation quality,
- compare healthy brain vs glioblastoma,
- perform reference-assisted annotation as evidence,
- report statistical neighborhood enrichment as a validated finding for local Xenium data.

Those steps require reviewed biological inputs first.

## Remaining Needs

1. Expert cell labels.
   - Required files: `expert_cell_labels.csv` in each source Xenium folder.
   - Required columns: `cell_id,expert_label,confidence,notes`.
   - Recommended extended columns: `cell_id,expert_label,cl_id,secondary_state,confidence,notes`.
   - Label vocabulary: use the broad Cell Ontology-compatible set in `docs/cell_ontology_labeling_guide.md`.
   - Minimum pilot threshold: at least two biological label classes and sufficient coverage.

2. User tissue/ROI regions.
   - Required files: `cell_regions.csv` in each source Xenium folder.
   - Required columns: `cell_id,region,region_confidence,notes`.
   - Recommended first-pass region labels: `tumor_core`, `infiltrative_margin`, `reactive_glia_rich`, `immune_rich`, `vascular_perivascular`, `necrotic_hypoxic`, `white_matter`, `gray_matter`, `normal_appearing_brain`, and `artifact_or_low_quality`.
   - Minimum pilot threshold: at least two reviewed regions.

3. Tissue-matched reference data.
   - Healthy brain and glioblastoma references need validated labels and license/consent metadata.
   - A local healthy Xenium sample is useful context, but not a label-transfer reference until it is reviewed.

4. Biological benchmark truth.
   - Freeze reviewed labels/regions into held-out benchmark splits.
   - Track annotation F1, cluster-label agreement, region composition error, neighborhood reproducibility, and unsupported-claim refusal.

5. LLM API configuration.
   - Add `OPENAI_API_KEY` plus an explicit model name, or `ANTHROPIC_API_KEY` plus an explicit model name.
   - Keep raw biomedical tables/images out of prompts; pass summaries, schema, run IDs, and artifact paths.
   - Route all LLM output through existing tool-plan validation.

6. Production API hardening.
   - Add authentication, authorization, request limits, dataset allowlists, and audit logging before multi-user deployment.
   - Add a background job runner for long Xenium workflows.

7. Environment hardening.
   - Pin thread settings for Scanpy/Squidpy deployments to avoid OpenMP conflicts.
   - Recommended runtime settings include writable `MPLCONFIGDIR`, bounded `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, and `LOKY_MAX_CPU_COUNT`.

8. Governance metadata.
   - Complete source, license, consent class, PHI risk, and allowed-use fields for every dataset.

## Recommendation

Add an LLM API only after keeping the current validation gates intact. The best immediate sequence is:

1. Complete glioblastoma expert labels and ROI regions from the review packet.
2. Complete healthy brain labels and regions if healthy-vs-glioblastoma comparison is required.
3. Rerun validated Xenium pilot and benchmark gates.
4. Add LLM API configuration for planner UX.
5. Freeze the reviewed labels into a small benchmark set.
6. Use the benchmark to evaluate LLM-assisted planning, annotation support, and refusal behavior.

With only an LLM API and no reviewed labels/regions, SpatialMind is usable as a local workflow and review assistant. With reviewed labels/regions and a curated reference, it becomes a genuine validated Xenium pilot agent.

## 2026-08-12 Correctness Update

- Source counts and normalized expression are now separate data layers, and Xenium QC uses preserved counts.
- Validated statistical wrappers fail closed instead of silently using prototype fallbacks.
- Xenium CLI and API requests share one validated pilot execution path.
- Sampled review runs are explicitly ineligible for final biological claims; final runs require complete-section scope.
- The current healthy-brain and glioblastoma smoke reports used real backends but remain blocked by missing human labels and regions.
- The current leakage-aware review packet is `outputs/brain_expert_benchmark_20260812/`; both 750-cell cohorts have 0% reviewed joint label/ROI coverage and zero spatial-block leakage.

These changes reduce software and statistical risk, but do not remove the remaining human-validation, independent-replicate, governance-approval, or multi-user deployment requirements listed above.
