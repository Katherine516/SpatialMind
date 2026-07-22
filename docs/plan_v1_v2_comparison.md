# SpatialMind Build Plan Comparison: v1 vs v2

## Executive Summary

The v1 build plan defined a strong MVP architecture for a single-sample spatial transcriptomics agent. It focused on ingestion, eight core tools, an agent loop, memory, visualization, storage, API/CLI, frontend, and deployment.

The v2 build plan upgrades the project from an MVP roadmap to a production roadmap. It adds real-data hardening, a mandatory QC gate, 22 tools, multi-modal fusion, batch execution, structured reports, richer visualization, replay, and production observability.

The v2 plan is directionally stronger and more scientifically realistic, but it is also much larger. The safest implementation strategy is staged: first add schemas, gates, stubs, and eval coverage; then add real heavy algorithms one modality at a time.

## High-Level Comparison

| Area | v1 Plan | v2 Plan | Evaluation |
| --- | --- | --- | --- |
| Phases | 4 phases | 5 phases | v2 is more production realistic |
| Sections | 12 milestones | 16 sections | v2 is more granular |
| Timeline | ~16 weeks | ~22 weeks | v2 accounts for batch/fusion/reporting complexity |
| Tool count | 8 spatial transcriptomics tools | 22 tools across RNA, protein, ATAC, tumor, batch | v2 better covers real biology but needs strict staging |
| Data scope | Mostly Visium/H5AD/Xenium/CODEX | Adds IMC, GeoMx, WSI, ATAC, multi-modal fusion | v2 better, but format complexity is high |
| QC | Ingestion report only | Mandatory interactive QC dashboard + approval gate | v2 is much safer scientifically |
| Agent | ReAct loop with preconditions | Modality-aware routing, dependency graph, correction replay, batch routing | v2 improves reliability |
| Memory | Redis + Chroma concept | Session, analysis memory, and user prior store | v2 schema is more actionable |
| Batch | Not included | Celery batch engine for multi-sample jobs | Essential for real studies |
| Visualization | 6 plot types | 15 modality-aware visualization types | v2 is closer to user expectations |
| Reporting | Basic report | Multi-section HTML/PDF report | v2 better for PI/manuscript sharing |
| Storage | RunRecord/provenance | Batch/fusion/report records + replay | v2 improves reproducibility |
| Frontend | Chat/figure/history | Adds QC, batch tracker, report viewer, modality browser | v2 matches production workflow |
| Monitoring | Basic metrics | Adds correction rate, p90 tool runtime, graceful-fail alerting | v2 better for trust and iteration |

## Most Important v2 Improvements

1. Mandatory QC approval before analysis.
2. Tool registry expansion from 8 to 22 tools.
3. Explicit modality-aware tool routing.
4. Multi-modal fusion as its own layer.
5. Batch execution for multi-sample studies.
6. Structured report generation instead of a single text response.
7. Replay and stronger provenance.
8. User priors and correction-aware memory.
9. Expanded eval coverage across modalities.
10. Production observability tied to biological trust metrics.

## Main Risks in v2

The v2 plan is ambitious enough that implementation order matters. The main risks are:

- implementing advanced tools before ingestion is scientifically reliable,
- exposing tools that appear production-ready before their dependencies and validation data exist,
- attempting multi-modal fusion without coordinate and metadata contracts,
- using LLM planning before tool preconditions and eval coverage are strong enough,
- adding frontend complexity before real biological workflows work end to end.

The current implementation avoids these risks by registering v2 interfaces first and marking heavy algorithms as scaffolds until their dependencies and test datasets are ready.

## Implemented from v2 in Current Repository

| v2 Section | Status | Notes |
| --- | --- | --- |
| Repo structure | Implemented | Package split now follows `agent/`, `ingestion/`, `memory/`, `storage/`, `api/`, `viz/`, `tools/`, `batch/` |
| New dependencies | Declared | Added to `pyproject.toml` optional `full` group |
| Docker batch services | Scaffolded | Added Celery worker and Flower profiles |
| Production ingestion metadata | Partially implemented | Feature-name detection, mitochondrial feature detection, batch ingestion config |
| QC dashboard | Scaffolded | `QCReportBuilder` emits dependency-light HTML |
| QC approval gate | Scaffolded | API has `/sessions/{id}/approve-qc` and query gate |
| Eval coverage report | Implemented | Eval summary now includes modality/tool coverage |
| 22-tool registry | Implemented | All v2 tools registered with schemas and disambiguating descriptions |
| New tool implementations | Scaffolded | Heavy tools return scaffold results or explicit modality/precondition errors |
| DataModalityError | Implemented | Used for wrong-modality tool calls |
| Multi-modal fusion | Scaffolded | `ModalityFuser` and `FusedDataset` added |
| Modality-aware agent context | Started | Agent has modality prompt map and tool dependency graph |
| Batch engine | Scaffolded | Synchronous local `BatchEngine`; Celery app placeholder added |
| Memory user priors | Scaffolded | `UserPriorStore`, `PriorType`, `PriorSource` added |
| VizRouter and 15 viz specs | Implemented as routing specs | Concrete renderers still pending |
| ReportBuilder | Implemented | Structured HTML plus paginated ReportLab PDF; CLI/API format selection supports HTML, PDF, or both |
| Storage replay fields | Partially implemented | `RunRecord` includes batch/fusion fields, CLI replay added |
| Extended API | Partially implemented | Health, runs, figures, QC approval, batch jobs/status |

## Historical Not-Yet-Implemented Items

Several items from the earlier v2 comparison have since moved forward. Real Xenium `cell_feature_matrix.h5` parsing, H5AD ingestion, the full requirements environment, and first Scanpy/Squidpy wrappers are now implemented and validated. The remaining future work is:

- true MyGene.info ENSEMBL to HGNC mapping,
- 10x barcode whitelist validation,
- scrublet-based ambient RNA/doublet detection,
- SpatialData-IO readers for all modalities,
- real CNV inference with inferCNVpy,
- real Cell2location/RCTD deconvolution,
- LIANA/OmniPath communication analysis,
- IMC/CODEX protein phenotyping,
- spatial ATAC peak/motif workflows,
- real Celery asynchronous execution,
- Plotly/Vitessce/PNG renderers for all 15 visualization types,
- selectable HTML/PDF export with ReportLab,
- frontend v2 views.

## Recommended Implementation Order

1. Complete real Xenium gene-matrix ingestion.
2. Add annotation strategy for Xenium datasets.
3. Expand eval cases for Xenium and H5AD.
4. Implement real expression overlay and spatial scatter renderers.
5. Implement Squidpy neighborhood enrichment.
6. Implement structured reports using current tool outputs.
7. Add API session creation and dataset upload contracts.
8. Implement true batch persistence and Celery execution.
9. Add one advanced biology tool at a time, beginning with pathway/TF activity before CNV/deconvolution.
10. Build frontend only after the real Xenium workflow is scientifically useful.

## Bottom Line

v2 remains useful as the broader production roadmap, while the v7 MVP is the better immediate scope. The current repository follows that staged strategy: broad contracts and interfaces exist, while the active development target is a scientifically honest Xenium-primary MVP with scRNA/scATAC-lite support, validated labels, grounded reports, and growing eval/training data.
