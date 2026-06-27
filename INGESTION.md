# Data Ingestion Layer

The ingestion layer converts raw spatial omics inputs into one internal `SpatialDataset` contract:

- spatial coordinates
- cell or spot annotations
- gene/protein feature values
- sample metadata
- source provenance
- QC metrics
- processing history

## Raw Data Types

| Type | Examples | What It Contains | Prototype Status |
| --- | --- | --- | --- |
| `tidy_csv` | Prototype exports, Seurat/Scanpy tables | One row per cell or spot with `sample_id`, `x`, `y`, `cell_type`, optional `region`, and feature columns such as `gene_CD8A` or `marker_CD3` | Implemented |
| `multiplex_imaging_csv` | CODEX, MIBI, IMC, multiplex IF segmentation tables | Single-cell coordinates, phenotype labels, marker intensities, ROI metadata | Implemented as table ingestion |
| `10x_visium_directory` | Space Ranger output | Feature matrix, barcodes, tissue positions, scale factors, histology images | Adapter stub |
| `h5ad_anndata` | Scanpy/Squidpy/Cell2location outputs | AnnData expression matrix, observations, variables, embeddings, `obsm["spatial"]` | Implemented when `anndata` is installed |
| `xenium_directory` | 10x Xenium output folder | Cells, coordinates, morphology metadata, panel metadata, and `cell_feature_matrix.h5` features | Implemented with optional HDF5 feature loading |
| `xenium_experiment_file` | `experiment.xenium` opened by Xenium Explorer | Run metadata plus relative paths to morphology, zarr, analysis summary, and related Explorer assets | Implemented as an entry point that resolves and ingests the sibling Xenium folder |
| `spatialdata_zarr` | SpatialData stores | Tables, images, labels, shapes, coordinate transforms | Adapter stub |
| `pathology_image` | H&E TIFF, OME-TIFF, WSI tiles | Morphology pixels for registration and visual overlays | Metadata-only through manifest |

## Current Implemented Paths

Use a tidy CSV, manifest JSON, H5AD file, Xenium output directory, or `experiment.xenium` file. CSV ingestion expects:

- Required: `x`, `y`, `cell_type`
- Recommended: `sample_id`, `region`
- Features: any numeric column not reserved above, with optional prefixes `gene_` or `marker_`

The loader performs:

- source type detection
- required-column validation
- row-level rejection for invalid coordinates or missing cell types
- QC metrics: record count, cell-type count, feature count, coordinate bounds, duplicate coordinates, missing features, negative values
- library-size normalization plus `log1p`
- provenance tracking through `RawDataSource`

## Manifest Format

`data/demo_manifest.json` shows the intended multi-source contract. The first table-like source becomes the primary analytical dataset. Image and future multi-modal sources are preserved as metadata until their adapters are implemented.

```json
{
  "sample_id": "BRCA_04",
  "coordinate_system": "pixel",
  "sources": [
    {
      "path": "demo_spatial.csv",
      "data_type": "tidy_csv",
      "modality": "spatial_transcriptomics"
    },
    {
      "path": "demo_he_image.tiff",
      "data_type": "pathology_image",
      "modality": "morphology_image"
    }
  ]
}
```

## v4 MVP Loaders

The v4 MVP exposes modality-specific loader entrypoints under `spatialmind/ingestion/loaders/`:

- `scrna.py`: wraps table/H5AD data as a scRNA cell-by-feature contract.
- `scatac.py`: wraps gene activity data as accessibility-inferred cell-by-feature input.
- `xenium.py`: wraps Xenium targeted spatial RNA data, including segmentation references and targeted-panel caveats.

All three loaders validate the shared `CellByFeatureContract` through `validate_cell_by_feature_contract()`.

## Latest Real Dataset Run

The current Xenium breast MVP run uses:

```text
data/Human_Breast_Biomarkers_S1_Top_outs
```

The run sampled 6,000 cells, loaded 390 targeted panel features, generated marker-rule MVP labels, and wrote outputs to:

```text
outputs/xenium_breast_mvp/
```

The labels are intentionally caveated. They are acceptable for testing ingestion, planning, visualization, and provenance, but not yet for expert biological conclusions.

## Xenium `.xenium` Descriptor Files

`experiment.xenium` is treated as a first-class entry point. SpatialMind parses the descriptor, resolves linked images and Explorer files relative to the parent directory, and then loads the parent Xenium output folder.

Example:

```bash
python3 -m spatialmind.cli "Inspect this Xenium run" --data "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs/experiment.xenium"
```

The loaded dataset metadata includes:

- `experiment_xenium_path`
- `xenium_input_path`
- `xenium_resolved_directory`
- `xenium_explorer_assets`
- `xenium_files`

This gives the agent an Explorer-style launch point while keeping manual annotation in specialist tools such as Xenium Explorer, QuPath, or napari.

## Explorer-Lite Review Viewer

SpatialMind can generate a local `explorer_lite_viewer.html` for any loaded Xenium directory or `experiment.xenium` file:

```bash
MPLCONFIGDIR=/private/tmp/spatialmind_mpl PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache .venv/bin/python scripts/build_xenium_explorer_lite.py \
  --data "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs/experiment.xenium" \
  --out outputs/xenium_brain_healthy_explorer_lite \
  --max-records 1200
```

The viewer embeds the loaded cell map and supports:

- color by current label, 10x graph cluster, or draft region,
- label and cluster filters,
- cell ID search and cell detail inspection,
- rectangular cell selection,
- draft ROI assignment and export as `cell_regions.csv`,
- draft expert-label assignment and export as `expert_cell_labels.csv`,
- linked Xenium asset inventory from `experiment.xenium`.

The generated CSVs are review artifacts. They should be checked by a domain expert before being copied into the source Xenium folder and treated as validation inputs.

## Expert Label Tables

The ingestion layer now preserves `cell_id` on records and can apply external expert or reference-transferred labels. Put one of these files inside a Xenium dataset folder:

- `expert_cell_labels.csv`
- `cell_labels.csv`
- `cell_annotations.csv`
- `annotations.csv`
- `labels.csv`

Required columns:

- `cell_id`
- `expert_label` or another recognized label column such as `cell_type`, `annotation`, or `label`

Recommended columns:

- `confidence`
- `notes`
- `cl_id`
- `secondary_state`

Use `scripts/prepare_xenium_expert_mvp.py` to generate one `expert_label_template.csv` per local Xenium dataset and a readiness report at `outputs/xenium_expert_mvp_readiness/xenium_expert_mvp_readiness.md`. The template includes `graph_cluster`, `top_features`, and `marker_evidence` columns so expert review can use 10x clustering plus marker support without treating either as ground truth.

For healthy brain and glioblastoma review, use the broad Cell Ontology-compatible vocabulary in `docs/cell_ontology_labeling_guide.md`. Disease states and tumor programs should be stored in `secondary_state` or `notes`, not used as primary cell-type labels unless the term is explicitly a cell type.

## Next Adapter Work

The highest-value ingestion work is no longer basic H5AD or Xenium HDF5 support; those paths exist. The next ingestion improvements are:

- true 10x scRNA/scATAC matrix directory readers,
- optional SpatialData-IO readers for richer image/shape alignment,
- user-provided label file ingestion,
- preservation of raw counts/layers for downstream Scanpy workflows,
- deterministic chunked reading for full-size Xenium runs.
