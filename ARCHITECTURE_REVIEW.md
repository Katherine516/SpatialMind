# SpatialMind Plan Review

## What Is Strong

The proposal has the right modular shape. Separating ingestion, algorithms, reasoning, visualization, memory, and storage keeps the system evolvable as new spatial omics formats and methods appear. The selected v0.1 vertical slice, natural language to spatial visualization on one Visium-style dataset, is also the right first milestone because it tests the user experience, data plumbing, tool calling, artifacts, and provenance without taking on every analysis class at once.

The biggest strength is user focus. Wet-lab users do not want an algorithm catalog. They want to ask biologically framed questions and receive figures, statistics, caveats, and next-step suggestions. The proposed architecture supports that well.

## Main Risks

The proposal currently under-specifies data contracts. A real implementation needs explicit schemas for samples, coordinates, spot/cell annotations, image registrations, gene matrices, regions of interest, and provenance. Without these contracts, the agent will spend too much time guessing.

The LLM layer should not be trusted to choose methods freely. It should plan against a constrained tool registry with typed inputs, validation, and method-specific guardrails. For example, a co-localization test should know whether inputs are spots, segmented cells, regions, or pixels, because the appropriate null model differs.

The memory layer needs governance. Storing prior biological findings is useful, but it should distinguish between raw outputs, validated findings, user preferences, and speculative interpretations. Otherwise old weak results can quietly become "facts."

## Recommended V0.1 Scope

Ship one complete workflow first:

Natural-language request -> dataset lookup -> QC summary -> spatial feature plot -> one spatial statistic -> report -> provenance.

Recommended first queries:

- "Show CD8A expression in BRCA_04."
- "Map tumor and CD8+ T cells in BRCA_04."
- "Are CD8+ T cells co-localized with tumor cells in BRCA_04?"

Do not start with multi-modal registration, ligand-receptor analysis, or trajectory inference. They are valuable, but each brings enough assumptions to slow the first prototype.

## Implementation Advice

Use strict typed tool definitions before adding a real LLM. The LLM should produce a plan, not execute arbitrary code. Every tool should validate inputs and return structured outputs that include metrics, artifact paths, caveats, and provenance.

For the LLM layer, keep OpenAI and Anthropic behind one internal provider interface. Model names and response formats change, but the rest of SpatialMind should only depend on a stable internal `ExecutionPlan`. The safest first integration is "LLM proposes JSON plan, local validator accepts or falls back"; do not let hosted models directly execute code or choose filesystem paths.

Treat visualization as a first-class product surface. Spatial omics users will judge trust through plots. Even in the prototype, every result should include the exact data subset, color mapping, coordinate transform, and normalization used.

Add curated method guidance as retrieval content only after the tool registry is stable. RAG is most useful when it helps select parameters, explain caveats, and cite methods. It should not be the source of executable behavior.

Plan for human approval on expensive or destructive actions. Large H5AD loading, image registration, deconvolution model training, and cloud writes should require an explicit confirmation step.

## Current Implementation Update

The repository has now advanced beyond the initial review scope. SpatialMind implements a v7/v11 Xenium-first MVP agent with explicit cell-by-feature contracts, MVP workflow definitions, full and MVP tool registries, real H5AD/Xenium ingestion paths, Scanpy/Squidpy-backed wrappers, dataset readiness checks, grounded refusal behavior, validated pilot gates, review packets, and local run records.

The latest real-data run uses the local Xenium breast biomarker dataset and produces:

- `outputs/xenium_breast_mvp/xenium_breast_mvp_report.html`
- `outputs/xenium_breast_mvp/xenium_breast_cluster.png`
- `outputs/xenium_breast_mvp/spatial_distribution.svg`
- `outputs/xenium_breast_mvp/spatial_distribution_interactive.html`
- `outputs/xenium_breast_mvp/run_summary.json`

The architecture risk has shifted. The main risk is no longer basic data plumbing; it is biological label validity and training-data quality. The next architecture priority is to make annotation and reference transfer confidence-scored, Cell Ontology-grounded, auditable, and suitable for supervised training records. The current label vocabulary guidance lives in `docs/cell_ontology_labeling_guide.md`.
