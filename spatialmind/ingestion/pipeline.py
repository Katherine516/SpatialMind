import csv
import gzip
import json
import math
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..schemas import RawDataSource, SpatialDataset, SpotRecord


KNOWN_COLUMNS = {"sample_id", "x", "y", "cell_type", "region", "spot_id", "barcode", "cell_id"}
TABLE_TYPES = {"tidy_csv", "segmentation_csv", "multiplex_imaging_csv", "spatial_table"}
COMMON_ANNOTATION_KEYS = ("cell_type", "celltype", "cell_type_key", "annotation", "cluster", "leiden", "seurat_clusters")
COMMON_SPATIAL_KEYS = ("spatial", "X_spatial")

SUPPORTED_RAW_DATA_TYPES = [
    {
        "data_type": "tidy_csv",
        "examples": "Prototype exports, Seurat/Scanpy-derived tables",
        "contains": "One row per spot/cell with sample_id, x, y, cell_type, region, and gene/protein marker columns.",
        "status": "implemented",
    },
    {
        "data_type": "10x_visium_directory",
        "examples": "10x Genomics Visium spaceranger output",
        "contains": "Filtered feature matrix, tissue positions, scale factors, and histology image assets.",
        "status": "adapter stub; install scanpy/anndata or add matrix parser",
    },
    {
        "data_type": "h5ad_anndata",
        "examples": "AnnData files from Scanpy, Squidpy, Cell2location",
        "contains": "Expression matrix, obs/var annotations, embeddings, spatial coordinates in obsm.",
        "status": "implemented when anndata is installed",
    },
    {
        "data_type": "spatialdata_zarr",
        "examples": "SpatialData Zarr stores",
        "contains": "Tables, labels, images, shapes, coordinate transforms, and multi-modal spatial assets.",
        "status": "adapter stub; requires spatialdata/spatialdata-io",
    },
    {
        "data_type": "xenium_directory",
        "examples": "10x Genomics Xenium Analyzer output folders",
        "contains": "cells.csv.gz/parquet, cell_feature_matrix.h5, transcripts, boundaries, morphology images, metrics summary.",
        "status": "implemented for cells.csv.gz metadata plus optional h5py gene matrix loading",
    },
    {
        "data_type": "xenium_experiment_file",
        "examples": "10x Genomics experiment.xenium descriptor opened by Xenium Explorer",
        "contains": "Run metadata plus relative paths to morphology, zarr, summary, and analysis assets.",
        "status": "implemented as an entry point that resolves and ingests the sibling Xenium output folder",
    },
    {
        "data_type": "multiplex_imaging_csv",
        "examples": "CODEX, MIBI, IMC, mIF cell segmentation tables",
        "contains": "Single-cell coordinates, phenotypes, protein marker intensities, ROI/image metadata.",
        "status": "implemented as table ingestion",
    },
    {
        "data_type": "pathology_image",
        "examples": "H&E TIFF, OME-TIFF, whole-slide image tiles",
        "contains": "Morphology pixels and coordinate frames used for overlays and registration.",
        "status": "metadata-only in manifest; image parsing comes later",
    },
]


class UnsupportedRawDataError(RuntimeError):
    pass


class IngestionValidationError(ValueError):
    pass


class DataFormat(Enum):
    VISIUM_H5 = "visium_h5"
    VISIUM_SPACERANGER = "visium_spaceranger"
    MERFISH_H5AD = "merfish_h5ad"
    XENIUM = "xenium"
    CODEX_CSV = "codex_csv"
    GENERIC_H5AD = "generic_h5ad"
    TIDY_CSV = "tidy_csv"
    MANIFEST_JSON = "manifest_json"


@dataclass
class IngestionConfig:
    format: Optional[DataFormat] = None
    min_counts: int = 100
    min_genes: int = 1
    max_pct_mito: Optional[float] = None
    normalize_total: bool = True
    log1p: bool = True
    annotation_key: Optional[str] = None
    sample_id: Optional[str] = None
    max_records: int = 5000
    max_features_per_record: int = 200
    species: str = "human"
    normalize_coordinates_to_microns: bool = True


@dataclass
class IngestionReport:
    n_spots_raw: int
    n_spots_after_qc: int
    n_genes_raw: int
    n_genes_after_qc: int
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    format_detected: Optional[DataFormat] = None
    qc_metrics: Dict[str, object] = field(default_factory=dict)


@dataclass
class SampleConfig:
    path: Path
    sample_id: Optional[str] = None
    format: Optional[DataFormat] = None
    annotation_key: Optional[str] = None


@dataclass
class BatchIngestionConfig:
    samples: List[SampleConfig]
    harmonize_genes: bool = True
    batch_key: str = "sample_id"
    run_harmony: bool = False
    species: str = "human"


@dataclass
class BatchIngestionReport:
    sample_reports: Dict[str, IngestionReport] = field(default_factory=dict)
    failed_samples: Dict[str, str] = field(default_factory=dict)
    harmonized_gene_count: int = 0
    warnings: List[str] = field(default_factory=list)


class DataIngestionLayer:
    """Loads raw spatial omics sources into the agent's unified dataset contract."""

    def load(self, path: str, sample_id: Optional[str] = None) -> SpatialDataset:
        data_type = infer_data_type(path)
        if data_type == "manifest_json":
            return self.load_manifest(path, sample_id=sample_id)
        if data_type in TABLE_TYPES:
            return self.load_csv(path, sample_id=sample_id, data_type=data_type)
        if data_type == "h5ad_anndata":
            return self.load_h5ad(path, sample_id=sample_id)
        if data_type == "xenium_experiment_file":
            return self.load_xenium_directory(path, sample_id=sample_id)
        if data_type == "xenium_directory":
            return self.load_xenium_directory(path, sample_id=sample_id)
        raise unsupported_format_error(data_type, path)

    def load_manifest(self, path: str, sample_id: Optional[str] = None) -> SpatialDataset:
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        if not isinstance(manifest, dict):
            raise ValueError("Manifest must be a JSON object: %s" % path)

        manifest_sample = sample_id or str(manifest.get("sample_id") or "")
        base_dir = os.path.dirname(os.path.abspath(path))
        sources = []
        for item in manifest.get("sources", []):
            if not isinstance(item, dict):
                continue
            raw_path = str(item.get("path") or "")
            resolved = raw_path if os.path.isabs(raw_path) else os.path.join(base_dir, raw_path)
            image_path = item.get("image_path")
            if image_path and not os.path.isabs(str(image_path)):
                image_path = os.path.join(base_dir, str(image_path))
            sources.append(
                RawDataSource(
                    path=resolved,
                    data_type=str(item.get("data_type") or infer_data_type(resolved)),
                    modality=str(
                        item.get("modality")
                        or modality_for_data_type(str(item.get("data_type") or infer_data_type(resolved)))
                    ),
                    sample_id=str(item.get("sample_id") or manifest_sample or "") or None,
                    coordinate_system=str(item.get("coordinate_system") or manifest.get("coordinate_system") or "pixel"),
                    image_path=str(image_path) if image_path else None,
                    metadata=dict(item.get("metadata") or {}),
                )
            )

        primary = self._primary_table_source(sources)
        dataset = self.load_csv(
            primary.path,
            sample_id=sample_id or primary.sample_id or manifest_sample or None,
            data_type=primary.data_type,
            modality=primary.modality,
            coordinate_system=primary.coordinate_system,
        )
        dataset.source_path = path
        dataset.sources = sources
        dataset.metadata.update({key: value for key, value in manifest.items() if key != "sources"})
        dataset.processing_steps.insert(0, "Loaded dataset through manifest: %s" % path)
        if any(source.image_path for source in sources):
            dataset.notes.append("Manifest includes image assets; image registration is tracked as metadata only in this prototype.")
        return dataset

    def load_csv(
        self,
        path: str,
        sample_id: Optional[str] = None,
        data_type: str = "tidy_csv",
        modality: Optional[str] = None,
        coordinate_system: str = "pixel",
    ) -> SpatialDataset:
        rows = self._read_table(path)
        self._validate_columns(rows, path)
        records, rejected_rows = self._rows_to_records(rows, sample_id=sample_id)
        if not records:
            requested = sample_id or "any sample"
            raise ValueError("No records found for %s in %s" % (requested, path))

        inferred_sample = sample_id or records[0].sample_id
        source = RawDataSource(
            path=path,
            data_type=data_type,
            modality=modality or modality_for_data_type(data_type),
            sample_id=inferred_sample,
            coordinate_system=coordinate_system,
        )
        dataset = SpatialDataset(
            sample_id=inferred_sample,
            records=records,
            source_path=path,
            modality=source.modality,
            coordinate_system=coordinate_system,
            sources=[source],
        )
        dataset.processing_steps.append("Loaded %d records from %s." % (len(records), path))
        if rejected_rows:
            dataset.notes.append("%d rows were rejected during ingestion because required values were invalid." % rejected_rows)
        self._qc(dataset)
        self._annotate_feature_metadata(dataset)
        self._normalize_features(dataset)
        return dataset

    def load_h5ad(
        self,
        path: str,
        sample_id: Optional[str] = None,
        annotation_key: Optional[str] = None,
        max_records: int = 5000,
        max_features_per_record: int = 200,
    ) -> SpatialDataset:
        try:
            import anndata as ad  # type: ignore
        except ImportError as exc:
            raise unsupported_format_error("h5ad_anndata", path) from exc

        adata = ad.read_h5ad(path)
        if adata.n_obs == 0:
            raise IngestionValidationError("H5AD contains no observations: %s" % path)

        coords = _extract_obsm_coordinates(adata)
        if coords is None:
            raise IngestionValidationError(
                "H5AD must contain spatial coordinates in one of obsm keys: %s" % ", ".join(COMMON_SPATIAL_KEYS)
            )

        annotation = annotation_key or _choose_annotation_key(adata.obs.keys())
        var_names = [str(name).upper() for name in list(adata.var_names)]
        selected_indices = _sample_indices(int(adata.n_obs), max_records)
        records: List[SpotRecord] = []
        inferred_sample = sample_id or _infer_sample_id_from_obs(adata.obs, selected_indices) or Path(path).stem
        for index in selected_indices:
            coord = coords[index]
            row = adata.X[index]
            features = _matrix_row_to_features(row, var_names, max_features_per_record=max_features_per_record)
            cell_type = "Unannotated"
            if annotation:
                cell_type = str(adata.obs.iloc[index][annotation])
            else:
                cell_type = _infer_marker_cell_type(features) or cell_type
            records.append(
                SpotRecord(
                    sample_id=inferred_sample,
                    x=float(coord[0]),
                    y=float(coord[1]),
                    cell_type=cell_type or "Unannotated",
                    genes=features,
                    region=_obs_value(adata.obs, index, "region"),
                    cell_id=str(adata.obs_names[index]),
                )
            )

        dataset = SpatialDataset(
            sample_id=inferred_sample,
            records=records,
            source_path=path,
            modality="annotated_expression",
            coordinate_system="obsm:spatial",
            sources=[
                RawDataSource(
                    path=path,
                    data_type="h5ad_anndata",
                    modality="annotated_expression",
                    sample_id=inferred_sample,
                    coordinate_system="obsm:spatial",
                    metadata={
                        "n_obs_total": int(adata.n_obs),
                        "n_vars_total": int(adata.n_vars),
                        "annotation_key": annotation,
                        "spatial_key": _choose_spatial_key(adata),
                    },
                )
            ],
            metadata={
                "n_obs_total": int(adata.n_obs),
                "n_vars_total": int(adata.n_vars),
                "annotation_key": annotation,
                "annotation_strategy": "obs_column" if annotation else "marker_rule_v0",
                "max_records": max_records,
                "max_features_per_record": max_features_per_record,
            },
        )
        if len(records) < int(adata.n_obs):
            dataset.notes.append("Loaded a deterministic subset of %d/%d observations for agent-safe execution." % (len(records), int(adata.n_obs)))
        if not annotation:
            dataset.notes.append("No known annotation column found; conservative marker-rule labels were applied where possible.")
        dataset.processing_steps.append("Loaded H5AD through anndata: %s." % path)
        self._qc(dataset)
        self._annotate_feature_metadata(dataset)
        self._normalize_features(dataset)
        return dataset

    def load_xenium_directory(
        self,
        path: str,
        sample_id: Optional[str] = None,
        max_records: int = 5000,
        max_features_per_record: int = 200,
    ) -> SpatialDataset:
        input_path = path
        path = _resolve_xenium_input_path(path)
        cells_path = _first_existing(
            [
                os.path.join(path, "cells.csv.gz"),
                os.path.join(path, "cells.csv"),
            ]
        )
        if not cells_path:
            raise IngestionValidationError("Xenium directory is missing cells.csv.gz/cells.csv: %s" % path)
        metadata = _read_xenium_metadata(path)
        metadata["xenium_input_path"] = input_path
        metadata["xenium_resolved_directory"] = path
        inferred_sample = sample_id or str(metadata.get("run_name") or Path(path).name)
        total_rows = 0
        records: List[SpotRecord] = []
        selected_cell_ids: List[str] = []
        target_indices: Optional[set[int]] = None
        estimated_total = _safe_int(metadata.get("num_cells_detected"))
        if estimated_total and estimated_total > max_records:
            target_indices = set(_sample_indices(estimated_total, max_records))
        with _open_text(cells_path) as handle:
            reader = csv.DictReader(handle)
            for row_index, row in enumerate(reader):
                total_rows += 1
                if target_indices is not None and row_index not in target_indices:
                    continue
                try:
                    cell_id = str(row.get("cell_id") or row.get("barcode") or row.get("cell") or row_index)
                    records.append(
                        SpotRecord(
                            sample_id=inferred_sample,
                            x=float(row.get("x_centroid") or row.get("x") or 0.0),
                            y=float(row.get("y_centroid") or row.get("y") or 0.0),
                            cell_type=str(row.get("cell_type") or row.get("cluster") or "Unannotated cell"),
                            genes={
                                "TRANSCRIPT_COUNTS": float(row.get("transcript_counts") or 0.0),
                                "TOTAL_COUNTS": float(row.get("total_counts") or 0.0),
                                "CELL_AREA": float(row.get("cell_area") or 0.0),
                                "NUCLEUS_AREA": float(row.get("nucleus_area") or 0.0),
                            },
                            region=str(metadata.get("region_name") or "") or None,
                            cell_id=cell_id,
                        )
                    )
                    selected_cell_ids.append(cell_id)
                except (TypeError, ValueError):
                    continue
                if target_indices is None and len(records) >= max_records:
                    break

        if not records:
            raise IngestionValidationError("No loadable cell records found in Xenium directory: %s" % path)
        if not estimated_total:
            estimated_total = total_rows
        matrix_features, matrix_metadata, matrix_warnings = _load_xenium_gene_matrix(
            path,
            selected_cell_ids,
            max_features_per_record=max_features_per_record,
        )
        if matrix_features:
            annotated_count = 0
            for record, cell_id in zip(records, selected_cell_ids):
                gene_values = matrix_features.get(cell_id)
                if not gene_values:
                    continue
                record.genes.update(gene_values)
                if record.cell_type == "Unannotated cell":
                    inferred_type = _infer_marker_cell_type(gene_values)
                    if inferred_type:
                        record.cell_type = inferred_type
                        annotated_count += 1
            matrix_metadata["marker_rule_annotations"] = annotated_count

        sources = [
            RawDataSource(
                path=input_path,
                data_type="xenium_experiment_file" if str(input_path).lower().endswith(".xenium") else "xenium_directory",
                modality="spatial_transcriptomics",
                sample_id=inferred_sample,
                coordinate_system="microns",
                image_path=_xenium_image_path(path, metadata),
                metadata=metadata,
            )
        ]
        dataset = SpatialDataset(
            sample_id=inferred_sample,
            records=records,
            source_path=input_path,
            modality="spatial_transcriptomics",
            coordinate_system="microns",
            sources=sources,
            metadata={
                "xenium_files": _summarize_xenium_files(path),
                "gene_matrix": matrix_metadata,
                "n_obs_total": estimated_total,
                "max_records": max_records,
                "max_features_per_record": max_features_per_record,
                "sampling": {
                    "method": "deterministic_even_index" if target_indices is not None else "all_or_first_n",
                    "requested_records": max_records,
                    "loaded_records": len(records),
                    "total_records": estimated_total,
                    "fraction_loaded": round(len(records) / float(estimated_total or len(records)), 6),
                },
                **metadata,
            },
        )
        dataset.notes.extend(matrix_warnings)
        if matrix_features:
            dataset.notes.append(
                "Xenium adapter attached top expressed genes from cell_feature_matrix.h5 to %d/%d loaded cells."
                % (matrix_metadata.get("n_cells_matched", 0), len(records))
            )
            if matrix_metadata.get("marker_rule_annotations", 0):
                dataset.notes.append(
                    "Applied conservative marker-rule labels to %d cells with expression support."
                    % matrix_metadata["marker_rule_annotations"]
                )
        else:
            dataset.notes.append(
                "Xenium adapter loaded cell centroids/count summaries. Gene-level expression will attach automatically when h5py can read cell_feature_matrix.h5."
            )
        if len(records) < estimated_total:
            dataset.notes.append("Loaded a deterministic subset of %d/%d cells for agent-safe execution." % (len(records), estimated_total))
        if input_path != path:
            dataset.processing_steps.append("Resolved Xenium experiment descriptor %s to %s." % (input_path, path))
        dataset.processing_steps.append("Loaded Xenium cell table from %s." % cells_path)
        if matrix_features:
            dataset.processing_steps.append("Loaded Xenium gene matrix from cell_feature_matrix.h5.")
        self._qc(dataset)
        self._annotate_feature_metadata(dataset)
        self._normalize_features(dataset)
        return dataset

    def _read_table(self, path: str) -> List[Dict[str, str]]:
        delimiter = "\t" if path.endswith(".tsv") else ","
        with _open_text(path, newline="") as handle:
            return list(csv.DictReader(handle, delimiter=delimiter))

    def _validate_columns(self, rows: List[Dict[str, str]], path: str) -> None:
        if not rows:
            raise ValueError("No rows found in %s" % path)
        required = {"x", "y", "cell_type"}
        missing = sorted(required - set(rows[0].keys()))
        if missing:
            raise ValueError("Missing required columns in %s: %s" % (path, ", ".join(missing)))

    def _rows_to_records(self, rows: List[Dict[str, str]], sample_id: Optional[str]) -> Tuple[List[SpotRecord], int]:
        records: List[SpotRecord] = []
        rejected = 0
        for row in rows:
            row_sample = row.get("sample_id") or sample_id or "unknown"
            if sample_id and row_sample != sample_id:
                continue
            try:
                x = float(row["x"])
                y = float(row["y"])
            except (KeyError, TypeError, ValueError):
                rejected += 1
                continue
            cell_type = (row.get("cell_type") or "").strip()
            if not cell_type:
                rejected += 1
                continue
            records.append(
                SpotRecord(
                    sample_id=row_sample,
                    x=x,
                    y=y,
                    cell_type=cell_type,
                    genes=self._extract_feature_values(row),
                    region=row.get("region") or None,
                    cell_id=row.get("cell_id") or row.get("barcode") or row.get("spot_id") or None,
                )
            )
        return records, rejected

    def _extract_feature_values(self, row: Dict[str, str]) -> Dict[str, float]:
        features: Dict[str, float] = {}
        for key, value in row.items():
            if key in KNOWN_COLUMNS or value in (None, ""):
                continue
            feature_name = key[5:] if key.startswith("gene_") else key
            feature_name = feature_name[7:] if feature_name.startswith("marker_") else feature_name
            try:
                features[feature_name.upper()] = float(value)
            except ValueError:
                continue
        return features

    def _qc(self, dataset: SpatialDataset) -> None:
        nonfinite_coordinate_records = sum(
            1 for record in dataset.records if not math.isfinite(record.x) or not math.isfinite(record.y)
        )
        if nonfinite_coordinate_records:
            dataset.records = [
                record for record in dataset.records if math.isfinite(record.x) and math.isfinite(record.y)
            ]
        if not dataset.records:
            raise IngestionValidationError("No records with finite spatial coordinates remain after ingestion QC.")

        nonfinite_feature_values = 0
        for record in dataset.records:
            for feature, value in list(record.genes.items()):
                if not math.isfinite(value):
                    record.genes[feature] = 0.0
                    nonfinite_feature_values += 1

        xs = [record.x for record in dataset.records]
        ys = [record.y for record in dataset.records]
        coordinate_pairs = [(record.x, record.y) for record in dataset.records]
        duplicate_coordinates = len(coordinate_pairs) - len(set(coordinate_pairs))
        missing_feature_rows = sum(1 for record in dataset.records if not record.genes)
        negative_values = sum(1 for record in dataset.records for value in record.genes.values() if value < 0)
        totals = [sum(max(value, 0.0) for value in record.genes.values()) for record in dataset.records]
        positive_totals = [value for value in totals if value > 0]
        dataset.qc_metrics.update(
            {
                "record_count": len(dataset.records),
                "cell_type_count": len(dataset.cell_types),
                "feature_count": len(dataset.genes),
                "region_count": len({record.region for record in dataset.records if record.region}),
                "duplicate_coordinate_count": duplicate_coordinates,
                "missing_feature_row_count": missing_feature_rows,
                "negative_value_count": negative_values,
                "nonfinite_feature_value_count": nonfinite_feature_values,
                "nonfinite_coordinate_record_count": nonfinite_coordinate_records,
                "median_total_feature_count": round(_median(positive_totals), 4) if positive_totals else 0.0,
                "coordinate_bounds": {
                    "min_x": min(xs) if xs else 0.0,
                    "max_x": max(xs) if xs else 0.0,
                    "min_y": min(ys) if ys else 0.0,
                    "max_y": max(ys) if ys else 0.0,
                },
            }
        )
        dataset.processing_steps.append("Computed ingestion QC metrics.")
        if len(dataset.records) < 10:
            dataset.notes.append("Dataset has fewer than 10 observations; statistics are exploratory.")
        if len(dataset.cell_types) < 2:
            dataset.notes.append("Only one cell type is present; co-localization is not meaningful.")
        if missing_feature_rows:
            dataset.notes.append("%d observations have no numeric feature values." % missing_feature_rows)
        if negative_values:
            dataset.notes.append("%d negative feature values were clipped during normalization." % negative_values)
        if nonfinite_feature_values:
            dataset.notes.append(
                "%d non-finite feature values were replaced with zero before normalization." % nonfinite_feature_values
            )
        if nonfinite_coordinate_records:
            dataset.notes.append(
                "%d observations with non-finite spatial coordinates were removed." % nonfinite_coordinate_records
            )
        if duplicate_coordinates:
            dataset.notes.append("%d duplicate coordinate pairs were detected." % duplicate_coordinates)

    def _normalize_features(self, dataset: SpatialDataset) -> None:
        for record in dataset.records:
            total = sum(max(value, 0.0) for value in record.genes.values())
            if total <= 0:
                continue
            for feature, value in list(record.genes.items()):
                record.genes[feature] = math.log1p((max(value, 0.0) / total) * 10000.0)
        dataset.normalized = True
        dataset.processing_steps.append("Applied library-size normalization and log1p transform.")
        dataset.notes.append("Feature values were library-size normalized and log1p transformed.")

    def _annotate_feature_metadata(self, dataset: SpatialDataset) -> None:
        genes = dataset.genes
        ensembl_like = sum(1 for gene in genes if gene.upper().startswith(("ENSG", "ENSMUSG")))
        mito_human = sum(1 for gene in genes if gene.upper().startswith("MT-"))
        mito_mouse = sum(1 for gene in genes if gene.startswith("mt-"))
        dataset.metadata["feature_name_format"] = "ensembl" if ensembl_like > len(genes) / 2.0 else "symbol"
        dataset.metadata["mitochondrial_feature_count"] = mito_human + mito_mouse
        if ensembl_like:
            dataset.notes.append(
                "%d Ensembl-like feature names detected; HGNC mapping should be run with MyGene.info in production." % ensembl_like
            )
        if mito_human or mito_mouse:
            dataset.processing_steps.append("Detected %d mitochondrial features by species-aware prefixes." % (mito_human + mito_mouse))

    def _primary_table_source(self, sources: List[RawDataSource]) -> RawDataSource:
        for source in sources:
            if source.data_type in TABLE_TYPES or infer_data_type(source.path) in TABLE_TYPES:
                return source
        if sources:
            raise unsupported_format_error(sources[0].data_type, sources[0].path)
        raise ValueError("Manifest must include at least one source.")


class DataIngestionPipeline:
    """Phase-1 ingestion contract from the build plan.

    Production will return a real spatialdata.SpatialData object. The current
    dependency-light implementation returns the internal SpatialDataset contract,
    which carries the same downstream fields this prototype consumes.
    """

    def __init__(self, layer: Optional[DataIngestionLayer] = None) -> None:
        self.layer = layer or DataIngestionLayer()

    def ingest(self, path: Path, config: IngestionConfig) -> Tuple[SpatialDataset, IngestionReport]:
        detected = config.format or self.auto_detect_format(path)
        try:
            dataset = self._load_for_format(path, detected, config)
            raw_count = dataset.qc_metrics.get("record_count", len(dataset.records))
            report = IngestionReport(
                n_spots_raw=int(raw_count),
                n_spots_after_qc=len(dataset.records),
                n_genes_raw=len(dataset.genes),
                n_genes_after_qc=len(dataset.genes),
                warnings=list(dataset.notes),
                errors=[],
                format_detected=detected,
                qc_metrics=dict(dataset.qc_metrics),
            )
            return dataset, report
        except Exception as exc:
            report = IngestionReport(
                n_spots_raw=0,
                n_spots_after_qc=0,
                n_genes_raw=0,
                n_genes_after_qc=0,
                warnings=[],
                errors=[str(exc)],
                format_detected=detected,
            )
            raise IngestionValidationError(str(report.errors[0])) from exc

    def auto_detect_format(self, path: Path) -> DataFormat:
        data_type = infer_data_type(str(path))
        if data_type == "manifest_json":
            return DataFormat.MANIFEST_JSON
        if data_type == "tidy_csv":
            lower = str(path).lower()
            if "codex" in lower or "imc" in lower or "mibi" in lower:
                return DataFormat.CODEX_CSV
            return DataFormat.TIDY_CSV
        if data_type == "h5ad_anndata":
            lower = str(path).lower()
            return DataFormat.MERFISH_H5AD if "merfish" in lower else DataFormat.GENERIC_H5AD
        if data_type in {"xenium_directory", "xenium_experiment_file"}:
            return DataFormat.XENIUM
        if data_type == "10x_visium_directory":
            return DataFormat.VISIUM_SPACERANGER
        if str(path).lower().endswith(".h5"):
            return DataFormat.VISIUM_H5
        if "xenium" in str(path).lower():
            return DataFormat.XENIUM
        raise unsupported_format_error(data_type, str(path))

    def _load_for_format(self, path: Path, data_format: DataFormat, config: IngestionConfig) -> SpatialDataset:
        if data_format == DataFormat.MANIFEST_JSON:
            dataset = self.layer.load_manifest(str(path), sample_id=config.sample_id)
        elif data_format in (DataFormat.TIDY_CSV, DataFormat.CODEX_CSV):
            dataset = self.layer.load_csv(
                str(path),
                sample_id=config.sample_id,
                data_type="multiplex_imaging_csv" if data_format == DataFormat.CODEX_CSV else "tidy_csv",
            )
        elif data_format in (DataFormat.GENERIC_H5AD, DataFormat.MERFISH_H5AD):
            dataset = self.layer.load_h5ad(
                str(path),
                sample_id=config.sample_id,
                annotation_key=config.annotation_key,
                max_records=config.max_records,
                max_features_per_record=config.max_features_per_record,
            )
        elif data_format == DataFormat.XENIUM:
            dataset = self.layer.load_xenium_directory(
                str(path),
                sample_id=config.sample_id,
                max_records=config.max_records,
                max_features_per_record=config.max_features_per_record,
            )
        else:
            raise unsupported_format_error(data_format.value, str(path))
        _apply_threshold_qc(dataset, config)
        return dataset


class BatchIngestionPipeline:
    def __init__(self, pipeline: Optional[DataIngestionPipeline] = None) -> None:
        self.pipeline = pipeline or DataIngestionPipeline()

    def ingest_batch(self, config: BatchIngestionConfig) -> Tuple[List[SpatialDataset], BatchIngestionReport]:
        datasets: List[SpatialDataset] = []
        report = BatchIngestionReport()
        gene_sets = []
        for sample in config.samples:
            try:
                dataset, sample_report = self.pipeline.ingest(
                    sample.path,
                    IngestionConfig(
                        format=sample.format,
                        sample_id=sample.sample_id,
                        annotation_key=sample.annotation_key,
                        min_counts=0,
                        min_genes=0,
                        species=config.species,
                    ),
                )
                datasets.append(dataset)
                report.sample_reports[dataset.sample_id] = sample_report
                gene_sets.append(set(dataset.genes))
            except Exception as exc:
                key = sample.sample_id or str(sample.path)
                report.failed_samples[key] = str(exc)
        if config.harmonize_genes and gene_sets:
            shared = set.intersection(*gene_sets) if len(gene_sets) > 1 else gene_sets[0]
            report.harmonized_gene_count = len(shared)
            for dataset in datasets:
                for record in dataset.records:
                    record.genes = {gene: value for gene, value in record.genes.items() if gene in shared}
                dataset.processing_steps.append("Harmonized gene space across batch to %d shared features." % len(shared))
            if not shared:
                report.warnings.append("No shared genes were found across the batch.")
        if config.run_harmony:
            report.warnings.append("Harmony batch correction is requested but not implemented in the dependency-light prototype.")
        return datasets, report


def infer_data_type(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".xenium"):
        return "xenium_experiment_file"
    if lower.endswith(".json"):
        return "manifest_json"
    if lower.endswith((".csv", ".tsv", ".csv.gz", ".tsv.gz")):
        return "tidy_csv"
    if lower.endswith(".h5ad"):
        return "h5ad_anndata"
    if lower.endswith(".zarr"):
        return "spatialdata_zarr"
    if os.path.isdir(path) and _looks_like_xenium(path):
        return "xenium_directory"
    if os.path.isdir(path) and _looks_like_visium(path):
        return "10x_visium_directory"
    if lower.endswith((".tif", ".tiff", ".ome.tif", ".ome.tiff", ".svs")):
        return "pathology_image"
    return "unknown"


def modality_for_data_type(data_type: str) -> str:
    return {
        "tidy_csv": "spatial_table",
        "segmentation_csv": "multiplexed_protein",
        "multiplex_imaging_csv": "multiplexed_protein",
        "10x_visium_directory": "spatial_transcriptomics",
        "h5ad_anndata": "annotated_expression",
        "xenium_directory": "spatial_transcriptomics",
        "xenium_experiment_file": "spatial_transcriptomics",
        "spatialdata_zarr": "multi_modal_spatial",
        "pathology_image": "morphology_image",
    }.get(data_type, "unknown")


def summarize_supported_raw_data_types() -> List[Dict[str, str]]:
    return list(SUPPORTED_RAW_DATA_TYPES)


def available_samples(path: str) -> List[str]:
    data_type = infer_data_type(path)
    if data_type == "manifest_json":
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        sample = str(manifest.get("sample_id") or "")
        if sample:
            return [sample]
        samples = []
        for item in manifest.get("sources", []):
            source_sample = item.get("sample_id") if isinstance(item, dict) else None
            if source_sample:
                samples.append(str(source_sample))
        return sorted(set(samples)) if samples else ["unknown"]
    if data_type == "xenium_directory":
        metrics = _read_xenium_metadata(path)
        sample = str(metrics.get("run_name") or Path(path).name)
        return [sample]
    if data_type == "xenium_experiment_file":
        metrics = _read_xenium_metadata(_resolve_xenium_input_path(path))
        sample = str(metrics.get("run_name") or Path(path).parent.name)
        return [sample]
    if data_type not in TABLE_TYPES:
        raise unsupported_format_error(data_type, path)
    with _open_text(path, newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t" if path.endswith(".tsv") else ",")
        return sorted({row.get("sample_id", "unknown") for row in reader})


def unsupported_format_error(data_type: str, path: str) -> UnsupportedRawDataError:
    messages = {
        "10x_visium_directory": "10x Visium ingestion should parse matrix.mtx/h5, tissue_positions, scalefactors, and histology assets. Add scanpy/squidpy or a matrix parser before enabling this adapter.",
        "visium_h5": "Visium H5 ingestion requires scanpy/anndata or a 10x H5 parser.",
        "visium_spaceranger": "Space Ranger ingestion requires spatialdata-io or a matrix/tissue-position parser.",
        "merfish_h5ad": "MERFISH H5AD ingestion requires anndata/scanpy and a coordinate mapping for molecule/cell tables.",
        "xenium": "Xenium ingestion requires parsing cell_feature_matrix, cells.parquet/csv, and morphology transforms.",
        "xenium_directory": "Xenium ingestion requires cells.csv.gz/cells.csv. Gene-level expression from cell_feature_matrix.h5 needs h5py/anndata.",
        "xenium_experiment_file": "Xenium experiment files must live next to cells.csv.gz/cells.csv and other Xenium output assets.",
        "generic_h5ad": "Generic H5AD ingestion requires anndata/scanpy so obs, var, X, and obsm['spatial'] can be loaded safely.",
        "h5ad_anndata": "H5AD ingestion requires anndata/scanpy so obs, var, X, and obsm['spatial'] can be loaded safely.",
        "spatialdata_zarr": "SpatialData Zarr ingestion requires spatialdata so tables, images, labels, and coordinate transforms stay consistent.",
        "pathology_image": "Image-only sources need a paired table or segmentation source. Add them through a manifest for now.",
    }
    guidance = messages.get(data_type, "Use a tidy CSV/TSV or manifest JSON for the current prototype.")
    return UnsupportedRawDataError("Unsupported raw data type '%s' for %s. %s" % (data_type, path, guidance))


def _looks_like_visium(path: str) -> bool:
    expected = ["spatial", "filtered_feature_bc_matrix.h5"]
    names = set(os.listdir(path)) if os.path.isdir(path) else set()
    return any(name in names for name in expected)


def _looks_like_xenium(path: str) -> bool:
    names = set(os.listdir(path)) if os.path.isdir(path) else set()
    return "experiment.xenium" in names or "cells.csv.gz" in names or "cell_feature_matrix.h5" in names


def _open_text(path: str, newline: Optional[str] = None):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", newline=newline, encoding="utf-8")
    return open(path, newline=newline, encoding="utf-8")


def _sample_indices(total: int, max_records: int) -> List[int]:
    if max_records <= 0 or total <= max_records:
        return list(range(total))
    if max_records == 1:
        return [0]
    step = (total - 1) / float(max_records - 1)
    return sorted({int(round(index * step)) for index in range(max_records)})


def _choose_annotation_key(keys: Iterable[str]) -> Optional[str]:
    key_lookup = {str(key).lower(): str(key) for key in keys}
    for candidate in COMMON_ANNOTATION_KEYS:
        if candidate.lower() in key_lookup:
            return key_lookup[candidate.lower()]
    return None


def _choose_spatial_key(adata: Any) -> Optional[str]:
    for key in COMMON_SPATIAL_KEYS:
        if key in adata.obsm:
            return key
    return None


def _extract_obsm_coordinates(adata: Any) -> Optional[Any]:
    key = _choose_spatial_key(adata)
    if not key:
        return None
    coords = adata.obsm[key]
    if getattr(coords, "shape", (0, 0))[1] < 2:
        return None
    return coords


def _infer_sample_id_from_obs(obs: Any, indices: List[int]) -> Optional[str]:
    if not indices:
        return None
    for key in ("sample_id", "sample", "library_id", "batch"):
        if key in obs:
            value = str(obs.iloc[indices[0]][key])
            if value and value.lower() != "nan":
                return value
    return None


def _obs_value(obs: Any, index: int, key: str) -> Optional[str]:
    if key not in obs:
        return None
    value = str(obs.iloc[index][key])
    return None if value.lower() == "nan" else value


def _matrix_row_to_features(row: Any, gene_names: List[str], max_features_per_record: int) -> Dict[str, float]:
    if hasattr(row, "toarray"):
        values = row.toarray()[0]
    elif hasattr(row, "A1"):
        values = row.A1
    else:
        values = row
    pairs = []
    for index, value in enumerate(values):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            pairs.append((index, numeric))
    pairs.sort(key=lambda item: item[1], reverse=True)
    if max_features_per_record > 0:
        pairs = pairs[:max_features_per_record]
    return {gene_names[index]: value for index, value in pairs if index < len(gene_names)}


def _load_xenium_gene_matrix(
    path: str,
    cell_ids: List[str],
    max_features_per_record: int,
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Any], List[str]]:
    matrix_path = os.path.join(path, "cell_feature_matrix.h5")
    metadata: Dict[str, Any] = {
        "available": False,
        "path": matrix_path if os.path.exists(matrix_path) else None,
        "loader": "h5py_10x_csc_v1",
        "n_cells_requested": len(cell_ids),
        "n_cells_matched": 0,
        "n_cells_in_matrix": 0,
        "n_features_in_matrix": 0,
    }
    if not os.path.exists(matrix_path):
        return {}, metadata, ["Xenium cell_feature_matrix.h5 was not found; expression features were not attached."]
    try:
        import h5py  # type: ignore
    except ImportError:
        return {}, metadata, ["h5py is not installed; Xenium gene matrix loading was skipped."]

    requested = {_normalize_cell_identifier(cell_id): cell_id for cell_id in cell_ids}
    if not requested:
        return {}, metadata, ["No selected Xenium cell IDs were available for matrix matching."]

    try:
        with h5py.File(matrix_path, "r") as handle:
            matrix = handle.get("matrix")
            if matrix is None:
                return {}, metadata, ["cell_feature_matrix.h5 does not contain a matrix group."]
            barcodes = [_decode_h5_value(value) for value in matrix["barcodes"][:]]
            indptr = matrix["indptr"][:]
            indices = matrix["indices"]
            data = matrix["data"]
            feature_names = _read_h5_feature_names(matrix)
            metadata.update(
                {
                    "n_cells_in_matrix": len(barcodes),
                    "n_features_in_matrix": len(feature_names),
                }
            )
            if len(indptr) != len(barcodes) + 1:
                return {}, metadata, ["Xenium matrix orientation was not recognized; expected indptr length to match barcodes + 1."]

            barcode_lookup = {_normalize_cell_identifier(barcode): index for index, barcode in enumerate(barcodes)}
            matched: Dict[str, Dict[str, float]] = {}
            for normalized_cell_id, original_cell_id in requested.items():
                column = barcode_lookup.get(normalized_cell_id)
                if column is None:
                    continue
                start = int(indptr[column])
                end = int(indptr[column + 1])
                feature_indices = indices[start:end]
                values = data[start:end]
                features = _feature_slice_to_values(feature_indices, values, feature_names, max_features_per_record)
                if features:
                    matched[original_cell_id] = features

            metadata["available"] = bool(matched)
            metadata["n_cells_matched"] = len(matched)
            if not matched:
                return {}, metadata, ["No loaded Xenium cells matched barcodes in cell_feature_matrix.h5."]
            return matched, metadata, []
    except Exception as exc:
        return {}, metadata, ["Failed to load Xenium gene matrix with h5py: %s" % exc]


def _read_h5_feature_names(matrix: Any) -> List[str]:
    features = matrix.get("features")
    if features is None:
        shape = matrix.get("shape")
        feature_count = int(shape[0]) if shape is not None and len(shape[:]) else 0
        return ["FEATURE_%d" % index for index in range(feature_count)]
    for key in ("name", "gene_names", "id", "gene_ids"):
        if key in features:
            return [_decode_h5_value(value).upper() for value in features[key][:]]
    shape = matrix.get("shape")
    feature_count = int(shape[0]) if shape is not None and len(shape[:]) else 0
    return ["FEATURE_%d" % index for index in range(feature_count)]


def _feature_slice_to_values(
    feature_indices: Any,
    values: Any,
    feature_names: List[str],
    max_features_per_record: int,
) -> Dict[str, float]:
    pairs = []
    for feature_index, value in zip(feature_indices, values):
        try:
            numeric = float(value)
            index = int(feature_index)
        except (TypeError, ValueError):
            continue
        if numeric > 0 and 0 <= index < len(feature_names):
            pairs.append((feature_names[index], numeric))
    pairs.sort(key=lambda item: item[1], reverse=True)
    if max_features_per_record > 0:
        pairs = pairs[:max_features_per_record]
    return {gene: value for gene, value in pairs}


def _infer_marker_cell_type(features: Dict[str, float]) -> Optional[str]:
    marker_sets = {
        "T/NK cell": ("PTPRC", "CD3D", "CD3E", "CD8A", "CD4", "NKG7", "GNLY"),
        "B cell": ("MS4A1", "CD79A", "CD79B", "CD19", "MZB1"),
        "Myeloid cell": ("LYZ", "CD68", "LST1", "C1QA", "FCGR3A"),
        "Endothelial cell": ("PECAM1", "VWF", "KDR", "RAMP2"),
        "Fibroblast/Stromal cell": ("COL1A1", "COL1A2", "DCN", "LUM", "ACTA2"),
        "Epithelial/Tumor-like cell": ("EPCAM", "KRT8", "KRT18", "KRT19", "MKI67"),
        "Neural/Glial cell": ("GFAP", "AQP4", "MBP", "SNAP25", "RBFOX3"),
    }
    scores = []
    for label, markers in marker_sets.items():
        score = sum(float(features.get(marker, 0.0)) for marker in markers)
        if score > 0:
            scores.append((score, label))
    if not scores:
        return None
    scores.sort(reverse=True)
    return scores[0][1]


def _decode_h5_value(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _normalize_cell_identifier(value: str) -> str:
    return str(value).strip().strip('"').strip("'")


def _read_xenium_metadata(path: str) -> Dict[str, Any]:
    path = _resolve_xenium_input_path(path)
    metadata: Dict[str, Any] = {}
    experiment_path = os.path.join(path, "experiment.xenium")
    if os.path.exists(experiment_path):
        with open(experiment_path, encoding="utf-8") as handle:
            experiment = json.load(handle)
        if isinstance(experiment, dict):
            metadata.update(experiment)
            metadata["experiment_xenium_path"] = experiment_path
            metadata["xenium_explorer_assets"] = _resolve_xenium_explorer_assets(path, experiment)
    metrics_path = os.path.join(path, "metrics_summary.csv")
    if os.path.exists(metrics_path):
        with open(metrics_path, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if rows:
            metadata.update(rows[0])
    gene_panel_path = os.path.join(path, "gene_panel.json")
    if os.path.exists(gene_panel_path):
        with open(gene_panel_path, encoding="utf-8") as handle:
            panel = json.load(handle)
        panel_payload = panel.get("payload", {}) if isinstance(panel, dict) else {}
        panel_info = panel_payload.get("panel", {}) if isinstance(panel_payload, dict) else {}
        metadata["panel_name"] = _nested_get(panel_info, ["identity", "name"]) or panel_info.get("description") or metadata.get("panel_name")
        metadata["panel_species"] = panel_info.get("species")
        metadata["panel_tissue"] = panel_info.get("tissue")
        metadata["num_gene_targets"] = panel_info.get("num_gene_targets")
    return metadata


def _summarize_xenium_files(path: str) -> Dict[str, bool]:
    path = _resolve_xenium_input_path(path)
    names = set(os.listdir(path)) if os.path.isdir(path) else set()
    return {
        "experiment_xenium": "experiment.xenium" in names,
        "cells": "cells.csv.gz" in names or "cells.csv" in names or "cells.parquet" in names,
        "cell_feature_matrix_h5": "cell_feature_matrix.h5" in names,
        "transcripts": "transcripts.csv.gz" in names or "transcripts.parquet" in names,
        "cell_boundaries": "cell_boundaries.csv.gz" in names or "cell_boundaries.parquet" in names,
        "nucleus_boundaries": "nucleus_boundaries.csv.gz" in names or "nucleus_boundaries.parquet" in names,
        "morphology": any(name.startswith("morphology") and name.endswith((".tif", ".ome.tif")) for name in names),
        "analysis": "analysis.tar.gz" in names or "analysis.zarr.zip" in names,
    }


def _resolve_xenium_input_path(path: str) -> str:
    if str(path).lower().endswith(".xenium"):
        return str(Path(path).resolve().parent)
    return path


def _resolve_xenium_explorer_assets(path: str, experiment: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    assets: Dict[str, Dict[str, Any]] = {}
    for group_name in ("images", "xenium_explorer_files"):
        group = experiment.get(group_name)
        if not isinstance(group, dict):
            continue
        for key, value in group.items():
            if not value:
                continue
            relative = str(value)
            resolved = relative if os.path.isabs(relative) else os.path.join(path, relative)
            assets[key] = {"relative_path": relative, "resolved_path": resolved, "exists": os.path.exists(resolved)}
    return assets


def _xenium_image_path(path: str, metadata: Dict[str, Any]) -> Optional[str]:
    assets = metadata.get("xenium_explorer_assets")
    if isinstance(assets, dict):
        for key in ("morphology_filepath", "morphology_focus_filepath", "morphology_mip_filepath"):
            item = assets.get(key)
            if isinstance(item, dict) and item.get("exists"):
                return str(item.get("resolved_path"))
    return _first_existing(
        [
            os.path.join(path, "morphology.ome.tif"),
            os.path.join(path, "morphology_focus.ome.tif"),
            os.path.join(path, "morphology_mip.ome.tif"),
        ]
    )


def _first_existing(paths: List[str]) -> Optional[str]:
    for path in paths:
        if path and os.path.exists(path):
            return path
    return None


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _nested_get(mapping: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _apply_threshold_qc(dataset: SpatialDataset, config: IngestionConfig) -> None:
    before = len(dataset.records)
    kept = []
    removed_low_counts = 0
    removed_low_genes = 0
    for record in dataset.records:
        total = sum(max(value, 0.0) for value in record.genes.values())
        positive_genes = sum(1 for value in record.genes.values() if value > 0)
        if total < config.min_counts:
            removed_low_counts += 1
            continue
        if positive_genes < config.min_genes:
            removed_low_genes += 1
            continue
        kept.append(record)
    if not kept:
        dataset.notes.append("QC thresholds would remove every record; retained original data for inspection.")
        return
    dataset.records = kept
    dataset.qc_metrics["spots_removed_low_counts"] = removed_low_counts
    dataset.qc_metrics["spots_removed_low_genes"] = removed_low_genes
    dataset.qc_metrics["n_spots_after_threshold_qc"] = len(kept)
    dataset.processing_steps.append(
        "Applied threshold QC: removed %d of %d records." % (before - len(kept), before)
    )
    if removed_low_counts:
        dataset.notes.append("%d records failed min_counts=%d." % (removed_low_counts, config.min_counts))
    if removed_low_genes:
        dataset.notes.append("%d records failed min_genes=%d." % (removed_low_genes, config.min_genes))
