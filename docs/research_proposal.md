# SpatialMind: An Agentic Platform for Reproducible Spatial Omics Analysis

## Project Summary

Spatial omics technologies such as 10x Genomics Xenium, Visium, Visium HD, NanoString CosMx, and Vizgen MERSCOPE now generate spatially resolved molecular data at scales that are difficult for many laboratories to analyze reproducibly. Wet-lab researchers often need to ask biologically grounded questions such as "where are immune cells enriched," "which genes vary across tissue architecture," or "are tumor and T cell neighborhoods spatially associated." However, answering these questions currently requires manual format conversion, specialized computational expertise, careful method selection, and substantial provenance tracking.

This proposal describes the development of SpatialMind, an agentic spatial omics analysis system that translates natural-language biological questions into validated computational workflows. The system will ingest heterogeneous spatial omics datasets, select appropriate tools through a constrained registry, run reproducible analyses, generate publication-ready visual and tabular outputs, and preserve full provenance for every result. The immediate research focus is to evolve the current dependency-light prototype into a validated research platform capable of analyzing real Xenium, H5AD/AnnData, and SpatialData datasets.

## Central Hypothesis

A constrained, evaluation-driven agent architecture can make spatial omics analysis more accessible and reproducible if it combines strict data contracts, curated tool schemas, biological guardrails, automated provenance, and interpretable visual outputs.

## Significance

Spatial omics analysis is becoming central to cancer biology, immunology, neuroscience, developmental biology, and tissue atlas construction. The main bottleneck is no longer data generation alone; it is the ability to move from raw spatial data to defensible biological interpretation. Existing pipelines are powerful but fragmented. Researchers must choose among multiple file formats, coordinate conventions, normalization strategies, spatial statistics, deconvolution methods, and visualization tools.

SpatialMind addresses this gap by separating biological intent from computational execution while preserving scientific rigor. Instead of allowing a language model to execute arbitrary code, the system forces all actions through typed tools with explicit preconditions, parameter schemas, structured outputs, caveats, and reproducibility metadata. This architecture is designed to support both wet-lab exploration and computational review.

## Preliminary Work

The current repository implements an initial vertical slice of the SpatialMind architecture:

- Data ingestion for tidy spatial tables and manifest-driven datasets.
- Prototype Xenium directory ingestion from `cells.csv.gz`, `metrics_summary.csv`, morphology paths, and gene-panel metadata.
- Optional H5AD/AnnData ingestion adapter that activates when `anndata` is installed.
- Xenium `cell_feature_matrix.h5` feature loading with barcode matching.
- v7 cell-by-feature contracts for scRNA, scATAC gene activity, and Xenium targeted spatial RNA.
- Tool registry with full/default and MVP tool sets.
- Deterministic local agent loop with structured tool traces and MVP refusal behavior.
- Evaluation harness with 15 legacy test cases and 10 MVP cases.
- JSON memory, storage, provenance, report generation, and interactive spatial visualization.
- Full-environment verification currently passing 45/45 unit tests.
- Legacy evaluation suite currently passing 15/15 cases on the demo fixture.
- MVP evaluation suite currently passing 10/10 cases.
- Full `requirements.txt` environment validated locally, including Scanpy and Squidpy wrappers.
- A Xenium breast MVP run producing report, JSON outputs, static PNG/SVG, interactive HTML, and an md5-backed run record.
- A glioblastoma expert-review packet, ontology-grounded label guide, validated-pilot gates, and operational readiness audit.

The project also contains three real Xenium datasets under `data/`:

| Dataset | Platform | Current Readiness | Current Use | Current Blocker |
| --- | --- | --- | --- | --- |
| Human Breast Biomarkers | Xenium | MVP runnable | QC, marker-rule annotation, differential expression scaffold, neighborhood workflow, cluster visualization | Expert-validated labels/reference transfer |
| Human Brain Glioblastoma (FFPE) | Xenium | Expert-review packet ready | QC, spatial scatter, spatial clustering, HDF5 feature loading, review packet | Expert labels and user ROI regions |
| Human Healthy Brain (FFPE) | Xenium | Review-template ready | QC, spatial scatter, spatial clustering, HDF5 feature loading | Expert labels and user ROI regions |
| Human Non-diseased Lymph Node (FFPE) | Xenium | Review-template ready | QC, spatial scatter, spatial clustering, HDF5 feature loading | Expert labels and user ROI regions |

These datasets include `cell_feature_matrix.h5`, cell tables, transcript tables, morphology images, boundaries, gene panels, and metrics summaries. They are now appropriate for MVP workflow validation, with the main remaining limitation being biological label quality.

## Specific Aims

### Aim 1: Build robust real-data ingestion for spatial omics formats

The first aim is to convert SpatialMind from a prototype table reader into a real spatial omics ingestion layer. The system will support H5AD/AnnData, Xenium output directories, 10x Visium/Space Ranger directories, and SpatialData Zarr stores. Each ingestion path will produce a unified internal dataset contract with coordinates, expression features, observation annotations, sample metadata, image metadata, QC metrics, and provenance.

Key tasks:

- Extend the implemented H5AD ingestion path to preserve layers, raw counts, and richer `obsm`/`uns` metadata.
- Extend the implemented Xenium `cell_feature_matrix.h5` parser with chunked full-dataset reads, raw-count preservation, and stronger panel metadata checks.
- Add optional SpatialData/SpatialData-IO readers for Xenium, Visium, Visium HD, CosMx, MERSCOPE, and CODEX-style outputs.
- Preserve raw counts in a dedicated layer before normalization.
- Add deterministic downsampling for large datasets so agent workflows remain interactive.
- Create dataset readiness reports that identify usable workflows and blockers.

Milestone:

- SpatialMind can load at least one local Xenium dataset with real gene expression features and produce a valid QC report, spatial scatter plot, and expression overlay.

### Aim 2: Implement validated computational tools for core spatial biology workflows

The second aim is to replace prototype algorithms with real spatial omics methods while retaining strict tool contracts. Initial emphasis will be on methods that are broadly useful, relatively stable, and evaluable without requiring model training.

Priority tools:

- QC and normalization using Scanpy-compatible workflows.
- Cell-type annotation using existing labels first, then CellTypist or reference mapping.
- Spatial scatter and gene expression overlays.
- Spatial neighborhood graph construction.
- Neighborhood enrichment using Squidpy permutation tests.
- Spatial clustering using expression plus spatial graph information.
- Spatially variable gene ranking using Moran's I and later SpatialDE/SPARK-X-style methods.
- Differential expression using Scanpy rank-based methods.

Deferred tools:

- Cell2location/RCTD-style deconvolution.
- Ligand-receptor inference through CellChat/NicheNet-style databases.
- Trajectory inference through Palantir/PAGA-like workflows.

These deferred tools are biologically valuable but have stronger assumptions and higher computational cost, so they should be added after the ingestion, visualization, and evaluation layers are stable.

Milestone:

- At least four real computational wrappers pass unit tests, return structured `ToolResult` objects, and include clear caveats when assumptions are not satisfied.

### Aim 3: Develop an evaluation-driven agent planner for biological queries

The third aim is to improve the agent's reasoning layer without relying prematurely on fine-tuning. The agent will plan against a constrained tool registry and will be evaluated on tool selection, parameter selection, precondition handling, clarification behavior, output grounding, and graceful failure.

Training strategy:

- Use deterministic local planning as a baseline for regression testing.
- Add hosted LLM planning behind a stable provider interface.
- Require the LLM to produce a JSON plan that is validated locally before execution.
- Expand the eval suite from 15 cases to at least 100 curated cases across visualization, spatial statistics, differential expression, ambiguous requests, missing data, and invalid requests.
- Collect failure traces and expert corrections before considering fine-tuning.
- Consider fine-tuning only after a sufficient set of labeled query-plan-result examples exists.

Agent guardrails:

- Never run a tool if preconditions are unmet.
- Ask clarification questions when the sample, target cell type, gene, or metric is ambiguous.
- Never claim statistical significance without a valid statistical test result.
- Always surface caveats about normalization, annotation uncertainty, sample size, and platform limitations.
- Preserve full tool traces for audit and evaluation.

Milestone:

- Tool selection accuracy reaches at least 0.85 across the expanded eval suite, with graceful-failure behavior above 0.95.

### Aim 4: Produce interpretable, reproducible visual and report outputs

The fourth aim is to make visualization a first-class research product. Spatial omics users will judge trust largely through plots, so every output must be clear, inspectable, and tied to exact data and parameters.

Visualization outputs:

- Static SVG/PNG spatial scatter.
- Interactive HTML spatial viewer with hoverable points.
- Gene expression overlays.
- Neighborhood enrichment heatmaps.
- Differential expression volcano plots.
- Cell composition plots.
- QC summary plots.

Report outputs:

- Natural-language interpretation.
- Tool trace and parameters.
- Dataset metadata.
- QC metrics.
- Generated figures.
- Caveats and failed preconditions.
- Provenance hash and software versions.

Milestone:

- Every agent run produces a report, machine-readable JSON outputs, visual artifacts, and provenance metadata sufficient to reconstruct the analysis.

## Research Design and Methods

### System Architecture

SpatialMind will use a layered architecture:

1. Ingestion layer: Converts raw spatial omics files into a unified internal dataset contract.
2. Tool registry: Defines analysis tools, schemas, preconditions, output formats, and runtime expectations.
3. Algorithm layer: Runs validated computational methods and returns structured outputs.
4. Agent layer: Converts user queries into validated tool plans.
5. Visualization layer: Produces static and interactive figures.
6. Storage/provenance layer: Saves outputs, parameters, tool traces, versions, and run metadata.
7. Evaluation layer: Scores behavior against curated test cases.

This modular design allows model providers, spatial methods, and data backends to evolve without destabilizing the entire platform.

### Data Resources

Local data resources:

- 10x Xenium human brain glioblastoma dataset.
- 10x Xenium human healthy brain dataset.
- 10x Xenium human lymph node dataset.
- Demo BRCA spatial table and manifest fixture.

Recommended external resources:

- 10x Genomics public datasets: https://www.10xgenomics.com/datasets
- 10x Xenium Explorer demos and downloads: https://www.10xgenomics.com/support/software/xenium-explorer/latest/resources/xenium-explorer-demos
- SpatialData example datasets: https://spatialdata.scverse.org/en/stable/tutorials/notebooks/datasets/README.html
- SpatialData-IO readers: https://spatialdata.scverse.org/projects/io/en/latest/index.html
- CosMx public datasets: https://nanostring.com/products/cosmx-spatial-molecular-imager/ffpe-dataset/
- Vizgen MERSCOPE data releases: https://vizgen.com/data-release-program/
- HuBMAP data portal: https://hubmapconsortium.org/hubmap-data/
- CELLxGENE Census reference data: https://registry.opendata.aws/biohub-cellxgene-census/
- CellTypist documentation and models: https://celltypist.readthedocs.io/

### Evaluation Plan

Evaluation will be performed at four levels:

1. Ingestion correctness:
   - File format detection.
   - Coordinate extraction.
   - Expression matrix parsing.
   - Annotation field mapping.
   - QC metric consistency.

2. Tool correctness:
   - Preconditions enforced.
   - Parameter validation.
   - Structured output shape.
   - Reproducibility with random seeds.
   - Expected behavior on small fixtures.

3. Agent correctness:
   - Correct tool selection.
   - Correct parameter selection.
   - Clarification behavior.
   - Graceful failure.
   - Grounded interpretation.

4. Scientific usability:
   - Output readability.
   - Biological caveat quality.
   - Visualization interpretability.
   - Provenance completeness.
   - Review by at least one wet-lab or computational biology user.

Target metrics:

| Metric | Target |
| --- | --- |
| Unit test pass rate | 100 percent |
| Eval suite mean score | >= 0.85 |
| Tool selection accuracy | >= 0.85 |
| Graceful-failure score | >= 0.95 |
| Provenance completeness | 100 percent of successful runs |
| Manual usability review | At least one domain user sign-off |

## Expected Outcomes

By the end of the proposed work, SpatialMind should support:

- Real ingestion of H5AD and Xenium datasets.
- Dataset readiness reports for heterogeneous spatial omics folders.
- Natural-language analysis requests over real spatial data.
- Validated first-line spatial analysis tools.
- Static and interactive spatial visualizations.
- Reproducible reports with full provenance.
- A growing evaluation harness for agent behavior.

The long-term outcome is a research-grade agent that lowers the barrier to spatial omics analysis while keeping computational decisions transparent and auditable.

## Innovation

SpatialMind is innovative in three ways:

1. It treats the language model as a planner, not an executor. This reduces risk and keeps all computation inside validated local tools.
2. It combines spatial omics data contracts with agentic tool selection, allowing biological questions to be mapped to reproducible workflows.
3. It uses evaluation as the primary training mechanism before fine-tuning, making improvement measurable and scientifically grounded.

## Risks and Mitigation Strategies

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Spatial file formats vary across platform versions | Ingestion failures | Use SpatialData-IO where possible and maintain format-specific tests |
| Xenium data lacks cell-type labels by default | Limited biological interpretation | Add annotation workflows using CellTypist, marker rules, or user-provided labels |
| Large datasets make local algorithms slow | Poor interactivity | Use deterministic downsampling, chunked reads, and explicit runtime warnings |
| LLM selects inappropriate tools | Incorrect analysis | Validate plans against registry preconditions and eval suite |
| Visualizations mislead users | Scientific risk | Include normalization, coordinate, and caveat metadata in every figure/report |
| Memory stores weak findings as facts | Compounded errors | Separate raw outputs, validated findings, user corrections, and speculative notes |

## Ethical, Privacy, and Reproducibility Considerations

Spatial omics data may include human tissue, disease state, and clinically relevant metadata. SpatialMind should treat all non-public datasets as sensitive. The system should avoid uploading data to hosted model providers unless explicitly configured and approved. Hosted LLM calls should receive only minimal query and schema context when possible, not raw expression matrices or patient-linked metadata.

All analyses should preserve:

- Input dataset identity.
- Software versions.
- Tool parameters.
- Random seeds.
- Normalization choices.
- Coordinate systems.
- Generated artifacts.
- Warnings and failed preconditions.

This provenance is essential for reproducibility and scientific review.

## Work Plan and Timeline

| Phase | Duration | Main Deliverables |
| --- | --- | --- |
| Phase 1: Real ingestion | Complete | H5AD adapter, Xenium gene matrix adapter, dataset readiness reports |
| Phase 2: Core algorithms | Complete for first wrappers | Scanpy/Squidpy wrappers, cell annotation baseline, expression plots |
| Phase 3: Agent evaluation | In progress | Expanded MVP eval suite, hosted planner validation, failure analysis |
| Phase 4: Reporting and provenance | In progress | Interactive figures, full run reconstruction, report polish |
| Phase 5: Pilot validation | Next | Run all local Xenium datasets, add validated labels, document findings, domain-user feedback |

## Resource Requirements

Software:

- Python 3.10 or newer recommended.
- `anndata`, `scanpy`, `squidpy`, `spatialdata`, `spatialdata-io`, `h5py`, `numpy`, `pandas`, `scipy`, `plotly`.
- Optional: `celltypist`, `chromadb`, `redis`, `fastapi`, hosted LLM SDKs.

Compute:

- Local development machine for small fixtures and sampled datasets.
- At least 32 GB RAM recommended for full Xenium matrix loading.
- GPU optional for future deconvolution or deep learning modules.

Data:

- Existing local Xenium datasets.
- Public Visium/Xenium/SpatialData example datasets.
- Curated single-cell references for annotation and deconvolution.

## Deliverables

1. Production-ready H5AD ingestion adapter.
2. Xenium gene-level ingestion adapter.
3. Dataset readiness report CLI.
4. Real Scanpy/Squidpy algorithm wrappers.
5. Expanded agent evaluation suite.
6. Interactive spatial visualization layer.
7. Reproducible report and provenance schema.
8. Documentation for installation, data preparation, and example analyses.
9. Pilot analysis report on local Xenium brain and lymph node datasets.

## Conclusion

SpatialMind is positioned to become a practical research assistant for spatial omics analysis by combining natural-language interaction with strict computational boundaries. The current repository now demonstrates the core architecture, evaluation harness, provenance tracking, real Xenium/H5AD ingestion, first Scanpy/Squidpy wrappers, and an end-to-end Xenium breast MVP report. The next research phase should focus on validated annotation, larger training/evaluation data, and domain-expert review. This sequence will produce a system that is not only convenient but scientifically defensible.
