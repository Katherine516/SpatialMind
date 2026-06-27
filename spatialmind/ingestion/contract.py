from spatialmind.contracts import ArrayRef, CellByFeatureContract, ContractViolationError, SegmentationRef
from spatialmind.schemas import SpatialDataset


def to_cell_by_feature_contract(dataset: SpatialDataset) -> CellByFeatureContract:
    subtype = str(dataset.metadata.get("assay_subtype") or _infer_subtype(dataset))
    feature_type = str(dataset.metadata.get("feature_type") or _feature_type_for_subtype(subtype))
    resolution = str(dataset.metadata.get("resolution") or ("subcellular" if "xenium" in subtype else "single_cell"))
    contract = CellByFeatureContract(
        sample_id=dataset.sample_id,
        modality="transcriptomics" if subtype != "scatac_gene_activity" else "atac",
        spatial_coords=ArrayRef(
            artifact_id="%s_coords" % dataset.sample_id,
            path=dataset.source_path,
            shape=[len(dataset.records), 2],
            dtype="float64",
        )
        if dataset.records and resolution == "subcellular"
        else None,
        measurement_layer=ArrayRef(
            artifact_id="%s_matrix" % dataset.sample_id,
            path=dataset.source_path,
            shape=[len(dataset.records), len(dataset.genes)],
            dtype="float64",
        ),
        assay_schema={"source_modality": dataset.modality},
        species=str(dataset.metadata.get("species") or "human"),
        qc_passed=bool(dataset.records),
        assay_subtype=subtype,
        feature_type=feature_type,
        n_features=len(dataset.genes),
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
    if "atac" in modality:
        return "scatac_gene_activity"
    if "xenium" in modality or "spatial" in modality:
        return "xenium_spatial_rna"
    return "scrna"


def _feature_type_for_subtype(subtype: str) -> str:
    if subtype == "scatac_gene_activity":
        return "gene_activity"
    if subtype == "xenium_spatial_rna":
        return "targeted_panel"
    return "gene_counts"
