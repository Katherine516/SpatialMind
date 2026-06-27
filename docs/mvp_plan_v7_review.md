# SpatialMind MVP Plan v7 Review

Reviewed plan: `/Users/dongli/Desktop/Spatial_omics/SpatialMind/spatialmind mvp plan v7.html`

## Executive Assessment

The v7 plan is a scientifically stronger MVP scope than the previous v4 plan. It correctly makes Xenium the primary product path, keeps scRNA/scATAC as lightweight support modes, and removes methods that would create premature biological claims without sufficient data or validated backends.

The most important improvement is the separation between useful exploratory outputs and defensible evidence. The plan explicitly gates annotation quality, marks marker-rule labels as weak, requires user-provided regions for region-level claims, and separates metric roles into QC, diagnostic, and statistical-evidence categories.

## Comparison With v4

| Area | v4 Plan | v7 Plan |
| --- | --- | --- |
| Active scope | scRNA, scATAC, Xenium, optional integration | Xenium-primary, scRNA/scATAC-lite, reference-assisted annotation |
| MVP tools | Included trajectory, motif/TF, reference label transfer scaffolds | Six active tools only |
| Marker workflow | `differential_expression` in MVP | `marker_detection` with adjusted-p-value caveats |
| Annotation | Existing labels/reference transfer allowed | Readiness-gated; weak labels are caveated |
| Region analysis | Not a core MVP tool | User-provided region summary is core |
| Metrics | Tool-specific dictionaries | Typed `QualityMetrics` with role/provenance/caveat fields |
| Deferred methods | Some unsupported methods exposed as scaffolds | Trajectory, motif/chromVAR, full label transfer, deconvolution, ligand-receptor, pathway, CNV deferred from MVP |

## Implemented Changes

- Set the active MVP registry to six tools:
  - `qc_and_cluster`
  - `annotation`
  - `marker_detection`
  - `feature_overlay`
  - `region_summary`
  - `cell_neighborhood_enrichment`
- Added typed `QualityMetrics` contracts with QC, clustering, annotation, differential, and spatial metric groups.
- Attached quality metrics to tool results through the registry execution path.
- Added `marker_detection` as the MVP marker-ranking interface.
- Added `region_summary` for user-provided region labels.
- Updated MVP workflow definitions:
  - `SCRNA_LITE`
  - `SCATAC_LITE`
  - `XENIUM_PRIMARY`
  - `REFERENCE_ASSIST`
- Updated MVP readiness checks so trajectory, motif/chromVAR, and full label-transfer workflows are deferred from MVP mode.
- Updated the MVP planner so marker/cluster requests no longer accidentally trigger annotation.
- Updated visualization routing for v7 renderer names including marker dotplots, feature grids, region summaries, QC violins, and metrics summaries.
- Updated the Xenium breast MVP runner to call `marker_detection` instead of `differential_expression`.
- Added a region-summary eval case and updated scRNA/scATAC/reference-assist eval expectations.

## Scientific Decisions

The v7 plan is reasonable with one important interpretation: full reference label transfer should remain outside the active MVP until there is a real validated backend and matched tissue reference. The current implementation supports reference-assisted annotation planning, but avoids presenting transferred labels as ground truth.

The plan's emphasis on user-provided regions is also appropriate. Image-derived region discovery is a separate segmentation problem and should not be implied by a simple region summary tool.

## Validation

Current verification after v7 implementation:

- Compile check: passing.
- Full-environment unit tests: 45/45 passing.
- MVP eval: 10/10 passing, mean score 1.0000.

## Next Work

The next scientific milestone is to provide expert/user labels and region labels for at least one local Xenium dataset. Once those labels exist, SpatialMind can produce a stronger Xenium MVP report with annotation confidence, region summaries, marker tables, neighborhood enrichment, and explicit limitations.
