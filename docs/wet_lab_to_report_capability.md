# Wet-Lab Output To Report Capability

Last updated: 2026-06-27

## Goal

SpatialMind's product goal is to ingest wet-lab platform outputs and generate a comprehensive, auditable spatial omics report. The current implementation supports this goal for platform-processed outputs, especially 10x Xenium folders, H5AD/AnnData files, and tidy CSV/manifest tables.

It does not process primary instrument basecalls such as FASTQ/BCL. Those should be processed by the appropriate platform pipeline first, then passed to SpatialMind as Xenium, H5AD, or table outputs.

## Current End-To-End Flow

```text
wet-lab platform output
-> ingestion and QC
-> internal SpatialDataset contract
-> governance/readiness checks
-> expert-review packet or validated pilot gate
-> analysis tools
-> visualization and report
-> provenance, hashes, and replay
```

## Capability Assessment

| Capability | Current Status | Evidence |
| --- | --- | --- |
| Xenium directory / `.xenium` ingestion | Ready | Local Xenium breast, glioblastoma, healthy brain, and lymph node folders load with cells, coordinates, H5 matrix features, gene panel metadata, morphology metadata, boundaries, and `experiment.xenium` descriptor metadata. |
| H5AD ingestion | Ready when AnnData is installed | H5AD adapter is implemented and covered by tests. |
| CSV/manifest ingestion | Ready | Demo and manifest workflows run through CLI/eval. |
| QC/readiness reporting | Ready | `build_readiness_report`, label intake reports, pilot scorecards, and local promotion reports are implemented. |
| Expert review packet generation | Ready | Glioblastoma and all-dataset review packets are generated. |
| Ontology-guided labels | Partial review support | Cell Ontology guide and astrocyte `CL:0000127` prefill are present, but expert confirmation is still required. |
| Real analysis wrappers | Partially ready | Scanpy DE/clustering/HVG and Squidpy neighborhood enrichment pass backend validation. |
| Validated biological interpretation | Blocked by inputs | Requires reviewed `expert_cell_labels.csv` and `cell_regions.csv`. |
| Comprehensive reporting | Ready for review/readiness reports; gated for biology | Reports are generated for blocked and validated-ready states. Biological claims remain refused until gates pass. |
| Replay/provenance | Local ready | Run records, hashes, SQLite indexing, and replay checks exist. |
| LLM API planning | Optional ready | OpenAI and Anthropic adapters exist behind validated JSON plan boundaries. |
| Multi-user production | Partial | FastAPI and batch scaffolds exist; auth, job queue hardening, dataset allowlists, and audit logs are required before shared deployment. |

## Current Blockers For A Validated Biological Report

1. `expert_cell_labels.csv` in the selected Xenium folder.
2. `cell_regions.csv` in the selected Xenium folder.
3. Dataset governance manifest fields: source, license, consent class, PHI risk, and allowed use.
4. Tissue-matched reference data for reference-assisted annotation.
5. Frozen benchmark labels for measuring annotation/report quality.

## Cleanup Decision

The codebase was reviewed for files that do not serve the wet-lab-output-to-report goal. Source modules were retained when they are used by CLI/API/eval/tests or provide active compatibility paths. Generated caches and stale ad hoc demo outputs were removed.

Retained source areas:

- `spatialmind/ingestion`: raw platform output loaders and readiness checks.
- `spatialmind/tools`: analysis tools and real backend wrappers.
- `spatialmind/pilot`: validated Xenium pilot gates and reports.
- `spatialmind/review`: expert-review packet and ontology-guided review support.
- `spatialmind/viz`: figures and report rendering.
- `spatialmind/storage`: run records, hashes, SQLite indexing, and replay.
- `spatialmind/api`, `spatialmind/batch`: partial but relevant production surfaces.
- `eval`, `tests`: required to prevent regressions.

Removed workspace noise:

- Python `__pycache__` directories.
- import-linter cache.
- package build metadata.
- macOS `.DS_Store` files.
- stale ad hoc demo run folders under `outputs/`.
