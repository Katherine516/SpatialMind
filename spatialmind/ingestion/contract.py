from spatialmind.contracts import ArrayRef, CellByFeatureContract, ContractViolationError, SegmentationRef
from spatialmind.schemas import expression_feature_names, SpatialDataset, has_tissue_coordinates


def to_cell_by_feature_contract(dataset: SpatialDataset) -> CellByFeatureContract:
    subtype = str(dataset.metadata.get("assay_subtype") or _infer_subtype(dataset))
    feature_type = str(dataset.metadata.get("feature_type") or _feature_type_for_subtype(subtype))
    resolution = str(dataset.metadata.get("resolution") or ("subcellular" if "xenium" in subtype else "single_cell"))
    contract = CellByFeatureContract(
        sample_id=dataset.sample_id,
        modality="proteomics" if subtype == "protein_imaging" else ("atac" if subtype == "scatac_gene_activity" else "transcriptomics"),
        spatial_coords=ArrayRef(
            artifact_id="%s_coords" % dataset.sample_id,
            path=dataset.source_path,
            shape=[len(dataset.records), 2],
            dtype="float64",
        )
        if has_tissue_coordinates(dataset)
        else None,
        measurement_layer=ArrayRef(
            artifact_id="%s_matrix" % dataset.sample_id,
            path=dataset.source_path,
            shape=[len(dataset.records), len(dataset.genes)],
            dtype="float64",
        ),
        assay_schema={"source_modality": dataset.modality,
                      "coordinate_system": dataset.coordinate_system,
                      "coordinate_kind": "tissue" if has_tissue_coordinates(dataset) else "nonspatial",
                      "coordinate_units": dataset.metadata.get("coordinate_units") or (
                          "microns" if dataset.coordinate_system in {"micron", "microns", "um"} else
                          "pixels" if dataset.coordinate_system in {"pixel", "pixels"} else "unknown"),
                      "source_value_semantics": dataset.metadata.get("source_value_semantics", "unspecified"),
                      "measured_feature_names": dataset.metadata.get("measured_feature_names", dataset.genes)},
        species=str(dataset.metadata.get("species") or dataset.metadata.get("organism") or "unknown"),
        qc_passed=bool(dataset.records),
        assay_subtype=subtype,
        feature_type=feature_type,
        # Measured genes, not every detected feature. Counting `dataset.genes`
        # raw put control probes and QC pseudo-features in the panel size --
        # 483 for a 319-gene brain panel -- and that number is what the
        # reliability record printed beside every claim.
        n_features=len(expression_feature_names(dataset)),
        is_targeted_panel=bool(dataset.metadata.get("is_targeted_panel") or subtype == "xenium_spatial_rna"),
        panel_name=dataset.metadata.get("panel_name"),
        resolution=resolution,  # type: ignore[arg-type]
        segmentation=SegmentationRef(artifact_id="%s_segmentation" % dataset.sample_id, path=dataset.source_path)
        if subtype == "xenium_spatial_rna"
        else None,
    )
    contract.validate()
    return contract


def validate_cell_by_feature_contract(dataset: SpatialDataset) -> CellByFeatureContract:
    try:
        return to_cell_by_feature_contract(dataset)
    except Exception as exc:
        if isinstance(exc, ContractViolationError):
            raise
        raise ContractViolationError(str(exc)) from exc


def _infer_subtype(dataset: SpatialDataset) -> str:
    modality = (dataset.modality or "").lower()
    if modality in {"multiplexed_protein", "protein_imaging", "proteomics"}:
        return "protein_imaging"
    if "atac" in modality:
        return "scatac_gene_activity"
    if "xenium" in modality:
        return "xenium_spatial_rna"
    if modality in {"spatial_table", "spatial_transcriptomics", "annotated_expression"}:
        return "spatial_rna" if has_tissue_coordinates(dataset) else "scrna"
    if modality in {"scrna", "snrna", "transcriptomics"}:
        return "scrna"
    raise ContractViolationError("Unsupported or ambiguous assay modality: %s" % dataset.modality)


def _feature_type_for_subtype(subtype: str) -> str:
    if subtype == "protein_imaging":
        return "protein_intensity"
    if subtype == "scatac_gene_activity":
        return "gene_activity"
    if subtype == "xenium_spatial_rna":
        return "targeted_panel"
    return "gene_counts"
