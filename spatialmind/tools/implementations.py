import math
import random
import warnings
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Tuple

from spatialmind.contracts.metrics import (
    AnnotationMetrics,
    ClusteringMetrics,
    DifferentialMetrics,
    QCMetrics,
    QualityMetrics,
    SpatialMetrics,
    metric,
)
from spatialmind.schemas import SpatialDataset, ToolResult

from .exceptions import DataModalityError, InsufficientDataError, InvalidParameterError, MissingPreconditionError


def require_records(dataset: SpatialDataset) -> None:
    if not dataset.records:
        raise InsufficientDataError("Dataset has no records.")


def require_cell_types(dataset: SpatialDataset) -> None:
    require_records(dataset)
    if not dataset.cell_types:
        raise MissingPreconditionError("Dataset requires cell-type labels.")


def cell_type_annotation(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    counts = Counter(record.cell_type for record in dataset.records)
    if not counts:
        raise MissingPreconditionError("No annotation column is available.")
    return ToolResult(
        tool_name="cell_type_annotation",
        summary="Found %d annotated cell types; reused existing labels." % len(counts),
        metrics={"cell_type_counts": dict(counts), "method": params.get("method", "existing_labels")},
        caveats=list(dataset.notes),
    )


def qc_and_cluster(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    result = spatial_clustering(dataset, params)
    result.tool_name = "qc_and_cluster"
    result.summary = "Ran per-type QC and clustering. %s" % result.summary
    result.metrics["qc"] = dict(dataset.qc_metrics)
    result.metrics["assay_subtype"] = dataset.metadata.get("assay_subtype", dataset.modality)
    result.caveats.extend(_type_honesty_caveats(dataset))
    return result


def annotation(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    result = cell_type_annotation(dataset, params)
    result.tool_name = "annotation"
    result.metrics["assay_subtype"] = dataset.metadata.get("assay_subtype", dataset.modality)
    caveats = _type_honesty_caveats(dataset)
    result.caveats.extend(caveats)
    result.label_caveat = caveats[0] if caveats else None
    return result


def feature_overlay(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    feature = str(params.get("feature") or (dataset.genes[0] if dataset.genes else ""))
    if feature not in dataset.genes:
        if _is_targeted_panel(dataset):
            return ToolResult(
                tool_name="feature_overlay",
                summary="%s is not in the targeted panel, so no expression absence claim is supported." % feature,
                metrics={"feature": feature, "status": "panel_absent"},
                caveats=_type_honesty_caveats(dataset),
                label_caveat="Panel-absent genes are not measured, not unexpressed.",
            )
        raise MissingPreconditionError("feature_overlay requires a measured feature; %s was not found." % feature)
    values = [record.genes.get(feature, 0.0) for record in dataset.records]
    return ToolResult(
        tool_name="feature_overlay",
        summary="Prepared overlay values for %s across %d cells." % (feature, len(values)),
        metrics={
            "feature": feature,
            "min": round(min(values), 5),
            "max": round(max(values), 5),
            "mean": round(_mean(values), 5),
            "feature_type": dataset.metadata.get("feature_type", "gene_counts"),
        },
        caveats=_type_honesty_caveats(dataset),
        label_caveat=_first_or_none(_type_honesty_caveats(dataset)),
    )


def spatial_deconvolution(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    by_region: Dict[str, Counter] = defaultdict(Counter)
    for record in dataset.records:
        by_region[record.region or "all"][record.cell_type] += 1
    proportions = {}
    for region, counts in by_region.items():
        total = sum(counts.values()) or 1
        proportions[region] = {key: round(value / total, 4) for key, value in counts.items()}
    return ToolResult(
        tool_name="spatial_deconvolution",
        summary="Estimated cell-type proportions from existing labels for %d regions." % len(proportions),
        metrics={"proportions": proportions, "method": params.get("method", "label_proportions")},
        caveats=["Prototype uses observed labels as proportions; production should call Cell2location/RCTD."],
    )


def spatial_variable_genes(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    spatial_result = _squidpy_spatial_variable_genes(dataset, params)
    if spatial_result:
        return spatial_result
    if params.get("strict_engine") and params.get("engine") != "scanpy":
        raise MissingPreconditionError(
            "spatial_variable_genes requires a successful Squidpy Moran's I backend in strict mode."
        )
    scanpy_result = _scanpy_spatial_variable_genes(dataset, params)
    if scanpy_result:
        return scanpy_result
    if params.get("strict_engine"):
        raise MissingPreconditionError(
            "spatial_variable_genes requires a successful requested backend in strict mode."
        )
    n_top = int(params.get("n_top", 50))
    if n_top <= 0:
        raise InvalidParameterError("n_top must be positive.")
    rows = []
    for gene in expression_feature_names(dataset):
        values = [record.genes.get(gene, 0.0) for record in dataset.records]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        rows.append({"gene": gene, "effect_size": round(variance, 5), "pval": _pseudo_pvalue(variance), "pattern": "spatial"})
    rows.sort(key=lambda item: item["effect_size"], reverse=True)
    return ToolResult(
        tool_name="spatial_variable_genes",
        summary="Ranked %d features by prototype spatial variability score." % len(rows[:n_top]),
        metrics={"top_genes": rows[:n_top]},
        caveats=["Prototype ranks feature variance; production should use SpatialDE2 or SPARK-X."],
    )


def neighborhood_enrichment(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    squidpy_result = _squidpy_neighborhood_enrichment(dataset, params)
    if squidpy_result:
        return squidpy_result
    if params.get("strict_engine"):
        raise MissingPreconditionError(
            "neighborhood_enrichment requires a successful Squidpy permutation backend in strict mode."
        )
    radius = float(params.get("radius", 18.0))
    pairs = Counter()
    for left in dataset.records:
        for right in dataset.records:
            if left is right:
                continue
            if _distance(left.x, left.y, right.x, right.y) <= radius:
                pairs[tuple(sorted([left.cell_type, right.cell_type]))] += 1
    top_pairs = [
        {"pair": "%s | %s" % pair, "neighbor_count": count, "pval": _pseudo_pvalue(float(count))}
        for pair, count in pairs.most_common(10)
    ]
    return ToolResult(
        tool_name="neighborhood_enrichment",
        summary="Computed prototype neighborhood enrichment for %d cell-type pairs." % len(top_pairs),
        metrics={"radius": radius, "top_pairs": top_pairs},
        caveats=["Prototype uses radius neighbor counts; production should use Squidpy permutation testing."],
    )


def ligand_receptor_analysis(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    genes = set(dataset.genes)
    candidates = []
    if "VEGFA" in genes:
        candidates.append({"ligand": "VEGFA", "receptor": "KDR/FLT1", "sender": "Tumor cell", "receiver": "Endothelial cell", "score": 0.72, "pval": 0.08})
    if "PTPRC" in genes:
        candidates.append({"ligand": "immune_marker", "receptor": "context_marker", "sender": "CD8+ T cell", "receiver": "Tumor cell", "score": 0.41, "pval": 0.2})
    return ToolResult(
        tool_name="ligand_receptor_analysis",
        summary="Generated %d candidate interaction records." % len(candidates),
        metrics={"database": params.get("db", "cellchat"), "interactions": candidates},
        caveats=["Prototype uses marker heuristics; production should call CellChat/NicheNet."],
    )


def trajectory_inference(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    subtype = str(dataset.metadata.get("assay_subtype") or dataset.modality)
    if subtype not in {"scrna", "spatial_transcriptomics", "spatial_table", "tidy_csv"}:
        raise DataModalityError("trajectory_inference", dataset.modality, "scRNA")
    bounds = dataset.bounds()
    span = max((bounds["max_x"] - bounds["min_x"]) + (bounds["max_y"] - bounds["min_y"]), 1.0)
    values = []
    for index, record in enumerate(dataset.records):
        pseudotime = ((record.x - bounds["min_x"]) + (record.y - bounds["min_y"])) / span
        values.append({"index": index, "cell_type": record.cell_type, "pseudotime": round(pseudotime, 4)})
    return ToolResult(
        tool_name="trajectory_inference",
        summary="Computed prototype spatial pseudotime for %d observations." % len(values),
        metrics={"root_cell_type": params.get("root_cell_type"), "pseudotime": values[:20]},
        caveats=["Prototype uses coordinate gradient; production should use Palantir/PAGA spatial."],
    )


def motif_tf_activity(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    subtype = str(dataset.metadata.get("assay_subtype") or dataset.modality)
    if subtype != "scatac_gene_activity" and dataset.modality not in {"scatac", "spatial_atac", "chromatin_accessibility"}:
        raise DataModalityError("motif_tf_activity", dataset.modality, "scATAC gene-activity or peak matrix")
    genes = dataset.genes[: max(1, min(10, len(dataset.genes)))]
    tf_rows = [
        {"tf": gene, "activity_score": round((index + 1) / float(len(genes) + 1), 4), "evidence": "accessibility_inferred"}
        for index, gene in enumerate(genes)
    ]
    return ToolResult(
        tool_name="motif_tf_activity",
        summary="Estimated prototype TF activity for %d accessibility-derived features." % len(tf_rows),
        metrics={"feature_type": "gene_activity", "tf_activity": tf_rows},
        caveats=["scATAC gene activity is accessibility-inferred; do not report it as measured expression."],
        label_caveat="Accessibility-derived gene activity is an estimate of expression, not measured transcription.",
    )


def cell_neighborhood_enrichment(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    result = neighborhood_enrichment(dataset, params)
    result.tool_name = "cell_neighborhood_enrichment"
    result.metrics["resolution"] = dataset.metadata.get("resolution", "subcellular")
    result.caveats.extend(_type_honesty_caveats(dataset))
    result.label_caveat = _first_or_none(_type_honesty_caveats(dataset))
    return result


def run_neighborhood_robustness(
    dataset: SpatialDataset,
    params: Optional[Dict[str, object]] = None,
    baseline_result: Optional[ToolResult] = None,
) -> Dict[str, object]:
    """Re-run neighborhood enrichment across a graph-size grid and measure how stable
    the top enriched/depleted cell-type pairs are (sign agreement + top-K overlap).

    This replaces the earlier single-setting robustness proxy with an actual
    perturbation sweep. Requires the Squidpy permutation engine for z-scores.
    """
    params = dict(params or {})
    grid = [int(value) for value in (params.get("robustness_n_neighs") or [6, 10, 15])]
    n_perms = int(params.get("n_perms", 250) or 250)
    seed = int(params.get("random_state", 0) or 0)
    top_k = int(params.get("robustness_top_k", 10) or 10)
    per_setting: List[Dict[str, object]] = []
    if baseline_result is not None:
        baseline_metrics = baseline_result.metrics or {}
        baseline_n_neighs = int(baseline_metrics.get("n_neighs") or 0)
        baseline_pairs = baseline_metrics.get("all_pairs") or baseline_metrics.get("top_pairs") or []
        if (
            baseline_metrics.get("engine") == "squidpy"
            and baseline_n_neighs in grid
            and baseline_pairs
            and int(baseline_metrics.get("n_perms") or 0) == n_perms
            and int(baseline_metrics.get("random_state") or 0) == seed
        ):
            per_setting.append(
                {"n_neighs": baseline_n_neighs, "engine": "squidpy", "pairs": baseline_pairs}
            )
    for n_neighs in grid:
        if any(item.get("n_neighs") == n_neighs for item in per_setting):
            continue
        result = cell_neighborhood_enrichment(
            dataset,
            {
                "n_neighs": n_neighs,
                "n_perms": n_perms,
                "random_state": seed,
                "include_all_pairs": True,
                "strict_engine": True,
            },
        )
        pairs = result.metrics.get("all_pairs") or result.metrics.get("top_pairs") or []
        per_setting.append({"n_neighs": n_neighs, "engine": result.metrics.get("engine"), "pairs": pairs})
    summary = summarize_neighborhood_robustness(per_setting, top_k=top_k)
    summary.update(
        {
            "requested_settings": grid,
            "n_perms": n_perms,
            "random_state": seed,
            "top_k": top_k,
            "engines": sorted({str(item.get("engine")) for item in per_setting if item.get("engine")}),
        }
    )
    return summary


def summarize_neighborhood_robustness(per_setting: List[Dict[str, object]], top_k: int = 10) -> Dict[str, object]:
    usable = [item for item in per_setting if item.get("engine") == "squidpy" and item.get("pairs")]
    settings = [item.get("n_neighs") for item in per_setting]
    if len(usable) < 2:
        return {
            "status": "insufficient_settings",
            "score": 0.0,
            "settings": settings,
            "reason": "Robustness needs at least two Squidpy settings with permutation z-scores.",
        }
    maps: List[Dict[str, float]] = []
    for item in usable:
        zmap = {}
        for pair in item["pairs"]:
            if isinstance(pair, dict) and "zscore" in pair and pair.get("pair"):
                zmap[str(pair["pair"])] = float(pair["zscore"])
        maps.append(zmap)
    reference = maps[0]
    reference_top = sorted(reference.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_k]
    reference_top_set = {pair for pair, _ in reference_top}
    sign_agreements: List[float] = []
    jaccards: List[float] = []
    top_sets = [
        {pair for pair, _value in sorted(mapping.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_k]}
        for mapping in maps
    ]
    for other in maps[1:]:
        agree = total = 0
        for pair, zscore in reference_top:
            if pair in other:
                total += 1
                if (zscore > 0) == (other[pair] > 0):
                    agree += 1
        sign_agreements.append(agree / total if total else 0.0)
        other_top = {pair for pair, _ in sorted(other.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_k]}
        intersection = len(reference_top_set & other_top)
        union = len(reference_top_set | other_top)
        jaccards.append(intersection / union if union else 0.0)
    mean_sign = sum(sign_agreements) / len(sign_agreements)
    mean_jaccard = sum(jaccards) / len(jaccards)
    score = round(0.6 * mean_sign + 0.4 * mean_jaccard, 4)
    pair_stability = []
    for pair, reference_zscore in reference_top:
        present = [mapping[pair] for mapping in maps if pair in mapping]
        sign_agreement = (
            sum(1 for value in present if (reference_zscore > 0) == (value > 0)) / float(len(present))
            if present
            else 0.0
        )
        top_presence = sum(1 for top_set in top_sets if pair in top_set) / float(len(top_sets))
        pair_stability.append(
            {
                "pair": pair,
                "reference_zscore": round(reference_zscore, 5),
                "settings_present": len(present),
                "sign_agreement": round(sign_agreement, 4),
                "top_k_presence": round(top_presence, 4),
            }
        )
    return {
        "status": "computed",
        "score": score,
        "mean_sign_agreement": round(mean_sign, 4),
        "mean_topk_jaccard": round(mean_jaccard, 4),
        "settings": [item["n_neighs"] for item in usable],
        "n_reference_pairs": len(reference_top),
        "top_k": top_k,
        "pair_stability": pair_stability,
    }


def region_summary(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    if not any(record.region for record in dataset.records):
        raise MissingPreconditionError("region_summary requires user-provided region labels.")
    by_region: Dict[str, Dict[str, Any]] = {}
    top_n = int(params.get("top_n_features", 8) or 8)
    for record in dataset.records:
        region = record.region or "unassigned"
        entry = by_region.setdefault(region, {"cell_count": 0, "cell_type_counts": Counter(), "feature_sums": Counter()})
        entry["cell_count"] += 1
        entry["cell_type_counts"][record.cell_type] += 1
        for feature, value in record.genes.items():
            try:
                entry["feature_sums"][feature] += float(value)
            except (TypeError, ValueError):
                continue
    summaries = {}
    for region, entry in by_region.items():
        cell_count = int(entry["cell_count"]) or 1
        summaries[region] = {
            "cell_count": cell_count,
            "cell_type_counts": dict(entry["cell_type_counts"]),
            "cell_type_fraction": {
                label: round(count / float(cell_count), 4) for label, count in entry["cell_type_counts"].items()
            },
            "top_features": [
                {"feature": feature, "mean": round(total / float(cell_count), 5)}
                for feature, total in entry["feature_sums"].most_common(top_n)
            ],
        }
    return ToolResult(
        tool_name="region_summary",
        summary="Summarized %d user-provided regions by cell type and feature means." % len(summaries),
        metrics={"region_count": len(summaries), "regions": summaries, "region_source": "user_provided"},
        caveats=["Region summaries use user-provided region labels; they were not derived from image segmentation."],
    )


def run_region_stratified_neighborhoods(
    dataset: SpatialDataset,
    params: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Run independent neighborhood-enrichment tests inside reviewed regions."""
    require_cell_types(dataset)
    params = dict(params or {})
    min_region_cells = int(params.get("min_region_cells", 50) or 50)
    min_cells_per_type = int(params.get("min_cells_per_type", 20) or 20)
    max_regions = int(params.get("max_regions", 12) or 12)
    requested_n_neighs = int(params.get("n_neighs", 6) or 6)
    n_perms = int(params.get("n_perms", 250) or 250)
    random_state = int(params.get("random_state", 0) or 0)
    min_abs_zscore = float(params.get("min_abs_zscore", 2.0) or 2.0)
    by_region: Dict[str, List[Any]] = defaultdict(list)
    for record in dataset.records:
        if record.region:
            by_region[str(record.region)].append(record)
    if not by_region:
        return {
            "status": "not_run",
            "reason": "Region-stratified testing requires user-reviewed region labels.",
            "regions": [],
            "pair_consistency": [],
        }

    region_items = sorted(by_region.items(), key=lambda item: len(item[1]), reverse=True)
    region_results: List[Dict[str, object]] = []
    skipped_regions: List[Dict[str, object]] = []
    for region, records in region_items[:max_regions]:
        type_counts = Counter(record.cell_type for record in records)
        eligible_types = {label for label, count in type_counts.items() if count >= min_cells_per_type}
        eligible_records = [record for record in records if record.cell_type in eligible_types]
        if len(records) < min_region_cells or len(eligible_types) < 2 or len(eligible_records) < 3:
            skipped_regions.append(
                {
                    "region": region,
                    "cell_count": len(records),
                    "eligible_cell_count": len(eligible_records),
                    "eligible_cell_types": sorted(eligible_types),
                    "reason": "Requires at least %d region cells and two cell types with at least %d cells each."
                    % (min_region_cells, min_cells_per_type),
                }
            )
            continue
        subset = SpatialDataset(
            sample_id=dataset.sample_id,
            records=eligible_records,
            source_path=dataset.source_path,
            modality=dataset.modality,
            coordinate_system=dataset.coordinate_system,
            normalized=dataset.normalized,
            notes=list(dataset.notes),
            sources=list(dataset.sources),
            qc_metrics=dict(dataset.qc_metrics),
            processing_steps=list(dataset.processing_steps),
            metadata=dict(dataset.metadata),
        )
        n_neighs = min(requested_n_neighs, max(2, len(eligible_records) - 1))
        result = cell_neighborhood_enrichment(
            subset,
            {
                "n_neighs": n_neighs,
                "n_perms": n_perms,
                "random_state": random_state,
                "include_all_pairs": True,
                "strict_engine": bool(params.get("strict_engine")),
            },
        )
        metrics = result.metrics or {}
        pairs = metrics.get("all_pairs") or metrics.get("top_pairs") or []
        if metrics.get("engine") != "squidpy" or not pairs:
            skipped_regions.append(
                {
                    "region": region,
                    "cell_count": len(records),
                    "eligible_cell_count": len(eligible_records),
                    "eligible_cell_types": sorted(eligible_types),
                    "reason": "Squidpy permutation z-scores were not available for this region.",
                }
            )
            continue
        region_results.append(
            {
                "region": region,
                "cell_count": len(records),
                "tested_cell_count": len(eligible_records),
                "cell_type_counts": {label: int(type_counts[label]) for label in sorted(eligible_types)},
                "n_neighs": n_neighs,
                "n_perms": n_perms,
                "random_state": random_state,
                "tested_pair_count": len(pairs),
                "pairs": pairs,
            }
        )

    if len(region_items) > max_regions:
        skipped_regions.extend(
            {
                "region": region,
                "cell_count": len(records),
                "eligible_cell_count": 0,
                "eligible_cell_types": [],
                "reason": "Skipped because max_regions=%d; larger regions were prioritized." % max_regions,
            }
            for region, records in region_items[max_regions:]
        )
    pair_consistency = _summarize_region_pair_consistency(region_results, min_abs_zscore=min_abs_zscore)
    return {
        "status": "computed" if region_results else "insufficient_data",
        "reason": "" if region_results else "No reviewed region met the minimum cell and cell-type support thresholds.",
        "method": "Independent Squidpy permutation neighborhood enrichment within each reviewed region",
        "parameters": {
            "min_region_cells": min_region_cells,
            "min_cells_per_type": min_cells_per_type,
            "max_regions": max_regions,
            "n_neighs": requested_n_neighs,
            "n_perms": n_perms,
            "random_state": random_state,
            "min_abs_zscore": min_abs_zscore,
        },
        "tested_region_count": len(region_results),
        "skipped_region_count": len(skipped_regions),
        "regions": region_results,
        "skipped_regions": skipped_regions,
        "pair_consistency": pair_consistency,
        "warnings": [
            "Region-specific z-scores are not directly comparable when region cell counts, densities, or label compositions differ.",
            "Cross-region consistency requires at least two region effects with absolute z-score >= %.2f; no multiplicity-adjusted p-values are inferred from z-scores."
            % min_abs_zscore,
            "A region-specific adjacency pattern does not establish physical contact, signaling, mechanism, or causation.",
        ],
    }


def _summarize_region_pair_consistency(
    region_results: List[Dict[str, object]],
    min_abs_zscore: float = 2.0,
) -> List[Dict[str, object]]:
    by_pair: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for region_result in region_results:
        region = str(region_result.get("region") or "")
        for pair in region_result.get("pairs") or []:
            if not isinstance(pair, dict) or pair.get("pair") is None or pair.get("zscore") is None:
                continue
            try:
                zscore = float(pair["zscore"])
            except (TypeError, ValueError):
                continue
            if math.isfinite(zscore):
                by_pair[str(pair["pair"])].append({"region": region, "zscore": zscore})
    rows = []
    for pair, values in by_pair.items():
        supported = [item for item in values if abs(float(item["zscore"])) >= min_abs_zscore]
        positive = sum(1 for item in supported if float(item["zscore"]) > 0)
        negative = sum(1 for item in supported if float(item["zscore"]) < 0)
        agreement = max(positive, negative) / float(len(supported)) if supported else 0.0
        strongest = max(values, key=lambda item: abs(float(item["zscore"])))
        if len(supported) >= 2 and agreement >= 0.8:
            status = "region_consistent"
        elif len(supported) >= 2:
            status = "region_heterogeneous"
        elif len(supported) == 1:
            status = "region_specific_only"
        else:
            status = "weak_or_indeterminate"
        pair_parts = pair.split(" | ", 1)
        is_self_pair = len(pair_parts) == 2 and pair_parts[0] == pair_parts[1]
        rows.append(
            {
                "pair": pair,
                "is_self_pair": is_self_pair,
                "regions_tested": len(values),
                "supported_region_count": len(supported),
                "min_abs_zscore": min_abs_zscore,
                "direction_agreement": round(agreement, 4),
                "strongest_region": strongest["region"],
                "strongest_abs_zscore": round(abs(float(strongest["zscore"])), 4),
                "status": status,
                "by_region": [
                    {"region": item["region"], "zscore": round(float(item["zscore"]), 4)}
                    for item in sorted(values, key=lambda item: abs(float(item["zscore"])), reverse=True)
                ],
            }
        )
    rows.sort(key=lambda item: (bool(item["is_self_pair"]), -float(item["strongest_abs_zscore"])))
    return rows


def run_distance_dependent_cooccurrence(
    dataset: SpatialDataset,
    pairs: Optional[List[str]] = None,
    params: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Compute descriptive cell-type co-occurrence ratios over distance thresholds."""
    require_cell_types(dataset)
    params = dict(params or {})
    n_intervals = max(6, int(params.get("n_intervals", 20) or 20))
    max_pairs = max(1, int(params.get("max_pairs", 8) or 8))
    min_cells_per_type = max(2, int(params.get("min_cells_per_type", 20) or 20))
    try:
        import numpy as np  # type: ignore
        import squidpy as sq  # type: ignore
        from scipy.spatial import cKDTree  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError(
                "Distance-dependent co-occurrence requires NumPy, SciPy, and Squidpy in strict mode."
            ) from exc
        return {
            "status": "not_computed",
            "reason": "Distance-dependent co-occurrence requires NumPy, SciPy, and Squidpy: %s" % exc,
            "curves": [],
        }

    cell_counts = Counter(record.cell_type for record in dataset.records)
    labels = sorted(cell_counts)
    if len(labels) < 2 or len(dataset.records) < 3:
        return {
            "status": "insufficient_data",
            "reason": "Co-occurrence curves require at least two cell types and three cells.",
            "curves": [],
        }
    coordinates = np.asarray([[record.x, record.y] for record in dataset.records], dtype=float)
    nearest, _indices = cKDTree(coordinates).query(coordinates, k=2)
    median_nearest = float(np.median(nearest[:, 1]))
    spans = np.ptp(coordinates, axis=0)
    positive_spans = [float(value) for value in spans if float(value) > 0]
    tissue_scale = min(positive_spans) if positive_spans else max(median_nearest * 12.0, 1.0)
    requested_max = params.get("max_distance")
    max_distance = float(requested_max) if requested_max is not None else max(
        median_nearest * 3.0,
        min(median_nearest * 12.0, tissue_scale * 0.25),
    )
    if not math.isfinite(max_distance) or max_distance <= 0:
        return {
            "status": "insufficient_data",
            "reason": "A positive distance range could not be derived from the coordinates.",
            "curves": [],
        }
    intervals = np.linspace(0.0, max_distance, n_intervals + 1)
    try:
        adata = _dataset_to_anndata(dataset)
        category_labels = [str(value) for value in adata.obs["cell_type"].cat.categories]
        cooccurrence_params: Dict[str, object] = {
            "cluster_key": "cell_type",
            "interval": intervals,
            "copy": True,
        }
        try:
            import inspect

            supported = inspect.signature(sq.gr.co_occurrence).parameters
            if "n_jobs" in supported:
                cooccurrence_params["n_jobs"] = 1
            if "backend" in supported:
                cooccurrence_params["backend"] = "threading"
            if "show_progress_bar" in supported:
                cooccurrence_params["show_progress_bar"] = False
        except (TypeError, ValueError):
            pass
        occurrence, thresholds = sq.gr.co_occurrence(adata, **cooccurrence_params)
    except Exception as exc:
        if params.get("strict_engine"):
            raise
        return {
            "status": "not_computed",
            "reason": "Squidpy co-occurrence failed: %s" % exc,
            "curves": [],
        }

    label_index = {label: index for index, label in enumerate(category_labels)}
    thresholds = np.asarray(thresholds, dtype=float)
    curve_length = int(occurrence.shape[2])
    distance_values = thresholds[1:] if len(thresholds) == curve_length + 1 else thresholds[:curve_length]
    requested_pairs = list(dict.fromkeys(pairs or []))
    if not requested_pairs:
        requested_pairs = ["%s | %s" % (left, right) for i, left in enumerate(labels) for right in labels[i + 1 :]]
    curves = []
    skipped_pairs = []
    for pair in requested_pairs[:max_pairs]:
        parsed = pair.split(" | ", 1)
        if len(parsed) != 2 or parsed[0] not in label_index or parsed[1] not in label_index:
            skipped_pairs.append({"pair": pair, "reason": "Cell-type pair was not present in the dataset."})
            continue
        left, right = parsed
        if cell_counts[left] < min_cells_per_type or cell_counts[right] < min_cells_per_type:
            skipped_pairs.append(
                {
                    "pair": pair,
                    "reason": "Requires at least %d cells for each cell type." % min_cells_per_type,
                    "left_cell_count": int(cell_counts[left]),
                    "right_cell_count": int(cell_counts[right]),
                }
            )
            continue
        left_values = np.asarray(occurrence[label_index[left], label_index[right], :], dtype=float)
        right_values = np.asarray(occurrence[label_index[right], label_index[left], :], dtype=float)
        values = np.nanmean(np.vstack([left_values, right_values]), axis=0)
        finite = np.isfinite(values)
        points = [
            {"distance": round(float(distance), 4), "cooccurrence_ratio": round(float(value), 5)}
            for distance, value, keep in zip(distance_values, values, finite)
            if bool(keep)
        ]
        if not points:
            continue
        ratios = [float(point["cooccurrence_ratio"]) for point in points]
        peak_index = max(range(len(ratios)), key=lambda index: ratios[index])
        third = max(1, len(ratios) // 3)
        curves.append(
            {
                "pair": pair,
                "left_cell_type": left,
                "right_cell_type": right,
                "left_cell_count": int(cell_counts[left]),
                "right_cell_count": int(cell_counts[right]),
                "points": points,
                "peak_ratio": round(ratios[peak_index], 4),
                "peak_distance": points[peak_index]["distance"],
                "short_range_mean_ratio": round(sum(ratios[:third]) / float(len(ratios[:third])), 4),
                "long_range_mean_ratio": round(sum(ratios[-third:]) / float(len(ratios[-third:])), 4),
            }
        )
    return {
        "status": "computed" if curves else "insufficient_data",
        "reason": "" if curves else "No requested cell-type pair produced a finite co-occurrence curve.",
        "method": "Squidpy distance-dependent co-occurrence probability ratio",
        "coordinate_units": dataset.coordinate_system or "dataset_coordinate_units",
        "n_intervals": n_intervals,
        "max_distance": round(max_distance, 4),
        "median_nearest_cell_distance": round(median_nearest, 4),
        "min_cells_per_type": min_cells_per_type,
        "curve_count": len(curves),
        "curves": curves,
        "skipped_pairs": skipped_pairs,
        "warnings": [
            "Co-occurrence ratios are descriptive scale profiles; they do not provide permutation p-values.",
            "Curves depend on coordinate units, cell density, field of view, segmentation, and the selected maximum distance.",
            "A ratio above one indicates greater conditional co-occurrence than expected from marginal label frequency, not signaling or causation.",
        ],
    }


def reference_label_transfer(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    reference_dataset = params.get("reference_dataset")
    if params.get("reference_features"):
        reference_features = {str(feature).upper() for feature in params["reference_features"]}
    elif reference_dataset is not None:
        # Must come from the reference, not the target; otherwise every target gene
        # counts as "shared" and the overlap is reported far larger than it is.
        reference_features = {gene.upper() for gene in reference_dataset.genes}
    else:
        reference_features = {gene.upper() for gene in dataset.genes}
    target_features = {gene.upper() for gene in dataset.genes}
    shared = sorted(reference_features & target_features)
    min_shared = int(params.get("min_shared_features", 5) or 5)
    if len(shared) < min_shared:
        raise MissingPreconditionError(
            "reference_label_transfer requires at least %d shared features; got %d." % (min_shared, len(shared))
        )
    if reference_dataset is None:
        # No reference expression matrix, so no label can be predicted. Reporting a
        # "transfer" here would assert labels that were never produced.
        return ToolResult(
            tool_name="reference_label_transfer",
            summary=(
                "Checked reference compatibility over %d shared features. No labels were transferred "
                "because no labelled reference dataset was supplied." % len(shared)
            ),
            metrics={
                "status": "compatibility_only",
                "labels_transferred": False,
                "shared_feature_count": len(shared),
                "shared_feature_fraction": round(len(shared) / float(max(len(target_features), 1)), 4),
            },
            caveats=[
                "Feature overlap indicates reference compatibility only; it is not evidence that any cell label is correct.",
                "Pass reference_dataset to run an actual k-nearest-neighbour label transfer.",
            ]
            + _type_honesty_caveats(dataset),
            label_caveat="No cell-type labels were transferred; this result reports feature compatibility only.",
        )
    return _knn_reference_label_transfer(dataset, reference_dataset, shared, params)


CLUSTER_ASSIGNMENT_KEY = "cluster_assignments"


def store_cluster_assignments(dataset: SpatialDataset, labels: List[str]) -> None:
    """Record per-cell cluster ids on the dataset, keyed by cell_id."""
    if len(labels) != len(dataset.records):
        return
    dataset.metadata[CLUSTER_ASSIGNMENT_KEY] = {
        (record.cell_id or str(index)): str(label)
        for index, (record, label) in enumerate(zip(dataset.records, labels))
    }


def resolve_group_labels(dataset: SpatialDataset, params: Dict[str, object]) -> Tuple[List[str], str]:
    """Per-record grouping labels for a tool, plus the resolved group key.

    ``cell_type`` uses the applied labels. ``cluster`` uses data-derived clusters
    -- from params, from a previous clustering run, or from the platform's own
    graph clusters -- which is what makes descriptive analysis possible before any
    expert annotation exists.
    """
    group_key = str(params.get("group_key", "cell_type") or "cell_type")
    if group_key != "cluster":
        return [record.cell_type or "" for record in dataset.records], "cell_type"
    assignments = params.get(CLUSTER_ASSIGNMENT_KEY) or dataset.metadata.get(CLUSTER_ASSIGNMENT_KEY) or {}
    if not isinstance(assignments, dict) or not assignments:
        raise MissingPreconditionError(
            "group_key='cluster' requires cluster assignments; run qc_and_cluster first or pass "
            "cluster_assignments={cell_id: cluster}."
        )
    labels = []
    for index, record in enumerate(dataset.records):
        key = record.cell_id or str(index)
        labels.append(str(assignments.get(key, "")))
    if len({label for label in labels if label}) < 2:
        raise MissingPreconditionError("group_key='cluster' needs at least two populated clusters.")
    return labels, "cluster"


# Broad lineages with canonical markers, used to sanity-check transferred labels
# against the target's own measured expression. Deliberately coarse: the point is
# to catch a myeloid cell labelled as a neuron, not to arbitrate subtypes.
LINEAGE_MARKERS = {
    "lymphoid": ("PTPRC", "CD3D", "CD3E", "CD8A", "CD4", "NKG7", "GNLY", "MS4A1", "CD79A", "MZB1"),
    "myeloid": ("CD68", "LYZ", "C1QA", "AIF1", "CTSS", "ITGAX", "P2RY12", "CX3CR1", "MS4A6A", "FCGR3A"),
    "endothelial": ("PECAM1", "VWF", "KDR", "FLT1", "CLDN5", "RAMP2"),
    "stromal": ("COL1A1", "COL1A2", "DCN", "LUM", "ACTA2", "PDGFRB"),
    "epithelial": ("EPCAM", "KRT8", "KRT18", "KRT19", "KRT15"),
    "neuronal": ("SNAP25", "RBFOX3", "SYT1", "NRGN", "SLC17A7", "GAD1", "GAD2", "ENC1"),
    "oligodendrocyte": ("MBP", "MOG", "MOBP", "PLP1", "CLDN11", "OPALIN", "ERMN", "CNDP1"),
    "astrocyte": ("GFAP", "AQP4", "SLC1A3", "GJA1", "SOX9"),
}

# Keyword -> lineage, matched against a reference label. Ordered most specific
# first so "oligodendrocyte precursor" does not match plain "oligodendrocyte".
LABEL_LINEAGE_KEYWORDS = (
    ("oligodendrocyte precursor", "opc"),
    ("opc", "opc"),
    ("oligodendrocyte", "oligodendrocyte"),
    ("astrocyte", "astrocyte"),
    ("microglia", "myeloid"),
    ("microglial", "myeloid"),
    ("macrophage", "myeloid"),
    ("monocyte", "myeloid"),
    ("dendritic", "myeloid"),
    ("neutrophil", "myeloid"),
    ("myeloid", "myeloid"),
    ("t cell", "lymphoid"),
    ("nk cell", "lymphoid"),
    ("natural killer", "lymphoid"),
    ("b cell", "lymphoid"),
    ("plasma cell", "lymphoid"),
    ("lymphocyte", "lymphoid"),
    ("endothelial", "endothelial"),
    ("pericyte", "stromal"),
    ("smooth muscle", "stromal"),
    ("fibroblast", "stromal"),
    ("stromal", "stromal"),
    ("epithelial", "epithelial"),
    ("neoplastic", "epithelial"),
    ("tumor", "epithelial"),
    ("neuron", "neuronal"),
    ("neuronal", "neuronal"),
    ("glutamatergic", "neuronal"),
    ("gabaergic", "neuronal"),
)

# Lineages that are close enough that a mismatch is not evidence of an error.
COMPATIBLE_LINEAGES = (
    {"oligodendrocyte", "opc"},
    {"astrocyte", "neuronal"},  # both neuroectodermal; panels share glial/neuronal genes
)


def lineage_for_label(label: str) -> str:
    text = str(label or "").strip().lower()
    for keyword, lineage in LABEL_LINEAGE_KEYWORDS:
        if keyword in text:
            return lineage
    return ""


def marker_lineage(
    genes: Dict[str, float],
    min_score: float = 2.0,
    dominance: float = 1.5,
) -> Tuple[str, float]:
    """Dominant lineage supported by a cell's own markers, or ("", 0.0).

    Requires a clear winner (``dominance`` times the runner-up and above
    ``min_score``) so ambiguous cells are left unflagged rather than generating
    noise for reviewers.
    """
    scores = []
    for lineage, markers in LINEAGE_MARKERS.items():
        total = 0.0
        for marker in markers:
            try:
                total += max(float(genes.get(marker, 0.0)), 0.0)
            except (TypeError, ValueError):
                continue
        if total > 0:
            scores.append((total, lineage))
    if not scores:
        return "", 0.0
    scores.sort(reverse=True)
    best_score, best_lineage = scores[0]
    if best_score < min_score:
        return "", 0.0
    runner_up = scores[1][0] if len(scores) > 1 else 0.0
    if runner_up > 0 and best_score < runner_up * dominance:
        return "", 0.0
    return best_lineage, best_score


def lineages_conflict(predicted: str, observed: str) -> bool:
    if not predicted or not observed or predicted == observed:
        return False
    pair = {predicted, observed}
    return not any(pair <= compatible for compatible in COMPATIBLE_LINEAGES)


SPECIES_ALIASES = {
    "human": "human",
    "homo sapiens": "human",
    "ncbitaxon:9606": "human",
    "mouse": "mouse",
    "mus musculus": "mouse",
    "ncbitaxon:10090": "mouse",
}


def normalize_species(value: Any) -> str:
    text = str(value or "").strip().lower()
    return SPECIES_ALIASES.get(text, text)


def _require_same_species(dataset: SpatialDataset, reference: SpatialDataset, params: Dict[str, object]) -> None:
    """Block cross-species transfer.

    Gene symbols are uppercased before matching, so mouse ``Aqp4`` and human
    ``AQP4`` collide and a mouse reference would otherwise appear to align with a
    human panel and produce confident, meaningless labels. Orthology is not a
    case change, so refuse unless the caller explicitly opts in.
    """
    if params.get("allow_cross_species"):
        return
    target = normalize_species((dataset.metadata or {}).get("organism"))
    source = normalize_species((reference.metadata or {}).get("organism"))
    if target and source and target != source:
        raise MissingPreconditionError(
            "reference_label_transfer refuses a cross-species reference: target organism is '%s' but the "
            "reference is '%s'. Uppercased gene symbols collide across species, so this would produce "
            "confident but meaningless labels. Supply a same-species reference, or map orthologs first and "
            "pass allow_cross_species=True." % (target, source)
        )


def _knn_reference_label_transfer(
    dataset: SpatialDataset,
    reference: SpatialDataset,
    shared: List[str],
    params: Dict[str, object],
) -> ToolResult:
    """Distance-weighted KNN transfer over shared features, one label per cell."""
    _require_same_species(dataset, reference, params)
    reference_records = [record for record in reference.records if record.cell_type]
    labels = sorted({record.cell_type for record in reference_records})
    if len(labels) < 2:
        raise MissingPreconditionError(
            "reference_label_transfer requires a reference with at least two labelled classes; got %d." % len(labels)
        )
    try:
        import numpy as np  # type: ignore
        from sklearn.neighbors import KNeighborsClassifier  # type: ignore
    except ImportError as exc:
        raise MissingPreconditionError("reference_label_transfer needs numpy and scikit-learn (%s)." % exc)

    neighbors = max(1, min(int(params.get("n_neighbors", 15) or 15), len(reference_records)))
    confidence_threshold = float(params.get("confidence_threshold", 0.6) or 0.6)

    def matrix(records: List[Any], lookup: Dict[str, str]) -> Any:
        rows = []
        for record in records:
            values = [max(float(record.genes.get(lookup.get(name, name), 0.0)), 0.0) for name in shared]
            total = sum(values)
            if total > 0:
                values = [float(np.log1p(value / total * 1e4)) for value in values]
            rows.append(values)
        return np.asarray(rows, dtype=float)

    reference_matrix = matrix(reference_records, {gene.upper(): gene for gene in reference.genes})
    target_matrix = matrix(list(dataset.records), {gene.upper(): gene for gene in dataset.genes})
    classifier = KNeighborsClassifier(n_neighbors=neighbors, weights="distance")
    classifier.fit(reference_matrix, [record.cell_type for record in reference_records])
    probabilities = classifier.predict_proba(target_matrix)
    classes = [str(value) for value in classifier.classes_]

    # Vote-fraction confidence is computed over the classes the reference happens
    # to contain, so it cannot express "none of these": a cell type absent from the
    # reference is still assigned its nearest available label, often at high
    # confidence. Distance to the reference is the independent signal.
    #
    # It must be calibrated on the target, not on the reference. scRNA references
    # and targeted-panel Xenium are different assays, so every target cell sits far
    # from the reference on absolute distance -- thresholding against the
    # reference's own neighbour distances flags ~100% of cells and is useless.
    # Ranking within the target isolates the cells that are unusual *for this
    # dataset*, which is what should be reviewed first.
    review_percentile = float(params.get("review_priority_percentile", 90.0) or 90.0)
    target_distances = classifier.kneighbors(target_matrix)[0].mean(axis=1)
    reference_neighbor_distances = classifier.kneighbors(reference_matrix)[0]
    # Column 0 is the self-match at distance 0.
    reference_baseline = (
        reference_neighbor_distances[:, 1:].mean(axis=1) if neighbors > 1 else reference_neighbor_distances.mean(axis=1)
    )
    distance_threshold = float(np.percentile(target_distances, review_percentile))
    # Reported so the platform gap between reference and target stays visible.
    median_target_distance = float(np.median(target_distances))
    median_reference_distance = float(np.median(reference_baseline))

    # Lineage each reference class belongs to, resolved once.
    label_lineages = {label: lineage_for_label(label) for label in classes}
    reference_lineages = {lineage for lineage in label_lineages.values() if lineage}

    predictions = []
    low_confidence = 0
    out_of_reference = 0
    disagreements = 0
    uncovered = 0
    for index, record in enumerate(dataset.records):
        row = probabilities[index]
        best = int(np.argmax(row))
        confidence = float(row[best])
        distance = float(target_distances[index])
        distant_for_dataset = bool(distance > distance_threshold)
        predicted_label = classes[best]
        predicted_lineage = label_lineages.get(predicted_label, "")
        observed_lineage, marker_score = marker_lineage(record.genes)
        # The cell's own markers disagree with the transferred label.
        disagreement = lineages_conflict(predicted_lineage, observed_lineage)
        # Stronger still: the markers point at a lineage the reference has no
        # class for, so no correct label was ever available for this cell.
        not_covered = bool(observed_lineage) and observed_lineage not in reference_lineages
        if confidence < confidence_threshold:
            low_confidence += 1
        if distant_for_dataset:
            out_of_reference += 1
        if disagreement:
            disagreements += 1
        if not_covered:
            uncovered += 1
        predictions.append(
            {
                "cell_id": record.cell_id or str(index),
                "predicted_label": predicted_label,
                "confidence": round(confidence, 4),
                "distance_to_reference": round(distance, 4),
                "distant_from_reference": distant_for_dataset,
                "marker_lineage": observed_lineage,
                "marker_score": round(marker_score, 4),
                "marker_disagreement": disagreement,
                "lineage_absent_from_reference": not_covered,
                # Marker conflict outranks vote agreement: a unanimous vote for a
                # lineage the cell's own markers contradict is the failure mode
                # that confidence alone cannot surface.
                "review_priority": "high"
                if (disagreement or not_covered or distant_for_dataset or confidence < confidence_threshold)
                else "normal",
            }
        )
    mean_confidence = float(np.mean([item["confidence"] for item in predictions])) if predictions else 0.0
    return ToolResult(
        tool_name="reference_label_transfer",
        summary=(
            "Transferred labels from %d reference classes to %d cells over %d shared features "
            "(k=%d, mean confidence %.2f)." % (len(labels), len(predictions), len(shared), neighbors, mean_confidence)
        ),
        metrics={
            "status": "transferred",
            "labels_transferred": True,
            "method": "knn_distance_weighted",
            "n_neighbors": neighbors,
            "shared_feature_count": len(shared),
            "reference_label_classes": labels,
            "reference_cell_count": len(reference_records),
            "mean_transfer_confidence": round(mean_confidence, 4),
            "low_confidence_cell_count": low_confidence,
            "confidence_threshold": confidence_threshold,
            "high_review_priority_count": sum(1 for item in predictions if item["review_priority"] == "high"),
            "marker_disagreement_count": disagreements,
            "lineage_absent_from_reference_count": uncovered,
            "reference_lineages": sorted(reference_lineages),
            "distant_from_reference_count": out_of_reference,
            "review_priority_percentile": review_percentile,
            "reference_distance_threshold": round(distance_threshold, 4),
            "median_target_distance": round(median_target_distance, 4),
            "median_reference_internal_distance": round(median_reference_distance, 4),
            "platform_shift_ratio": round(median_target_distance / max(median_reference_distance, 1e-9), 2),
            "predicted_label_counts": dict(Counter(item["predicted_label"] for item in predictions)),
            "predictions": predictions,
        },
        caveats=[
            "Transferred cell-type labels are predictions from a reference, not direct measurements.",
            "Reference and target were aligned over shared features only.",
            "Predicted labels require expert review before they can support biological claims.",
            "Confidence is a neighbour-vote fraction over the %d reference classes (%s) and cannot express "
            "'no matching class'; any cell type absent from the reference is still assigned its nearest "
            "available label, often at high confidence. Judge coverage from the class list, not the score."
            % (len(labels), ", ".join(labels[:6]) + (" ..." if len(labels) > 6 else "")),
            "%d cells carry marker evidence for a lineage the reference has no class for, and %d have "
            "markers that contradict their transferred label; both are flagged review_priority=high."
            % (uncovered, disagreements),
            "Target cells sit a median %.1fx further from the reference than reference cells sit from each "
            "other, reflecting the assay difference between scRNA and a targeted panel. Distances are used "
            "only to rank review priority within this dataset."
            % (median_target_distance / max(median_reference_distance, 1e-9)),
        ]
        + _type_honesty_caveats(dataset),
        label_caveat="Cell-type labels were transferred from a reference and must be expert-reviewed before use.",
    )


def spatial_clustering(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    scanpy_result = _scanpy_spatial_clustering(dataset, params)
    if scanpy_result:
        return scanpy_result
    if params.get("strict_engine"):
        raise MissingPreconditionError("spatial_clustering requires a successful Scanpy/Leiden backend in strict mode.")
    resolution = float(params.get("resolution", 0.5))
    bin_size = max(10.0, 30.0 / max(resolution, 0.1))
    clusters = Counter()
    for record in dataset.records:
        cluster = "C%d_%d" % (int(record.x // bin_size), int(record.y // bin_size))
        clusters[cluster] += 1
    return ToolResult(
        tool_name="spatial_clustering",
        summary="Assigned observations to %d prototype spatial clusters." % len(clusters),
        metrics={"resolution": resolution, "cluster_counts": dict(clusters)},
        caveats=["Prototype uses coordinate bins; production should use Squidpy graph + Leiden/BayesSpace."],
    )


def differential_expression(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    scanpy_result = _scanpy_differential_expression(dataset, params)
    if scanpy_result:
        return scanpy_result
    if params.get("strict_engine"):
        raise MissingPreconditionError(
            "differential_expression requires a successful Scanpy rank_genes_groups backend in strict mode."
        )
    group_key = str(params.get("group_key", "cell_type"))
    group1 = str(params.get("group1", "CD8+ T cell"))
    group2 = str(params.get("group2", "Tumor cell"))
    if group_key != "cell_type":
        raise InvalidParameterError("Prototype differential_expression only supports group_key='cell_type'.")
    rows = []
    for gene in expression_feature_names(dataset):
        first = [record.genes.get(gene, 0.0) for record in dataset.records if record.cell_type == group1]
        second = [record.genes.get(gene, 0.0) for record in dataset.records if record.cell_type == group2]
        if not first or not second:
            continue
        logfc = _mean(first) - _mean(second)
        rows.append({"gene": gene, "logFC": round(logfc, 4), "pval_adj": _pseudo_pvalue(abs(logfc)), "group": group1})
    rows.sort(key=lambda item: abs(float(item["logFC"])), reverse=True)
    return ToolResult(
        tool_name="differential_expression",
        summary="Ranked %d genes for %s vs %s." % (len(rows), group1, group2),
        metrics={"group_key": group_key, "group1": group1, "group2": group2, "ranked_genes": rows},
        caveats=["Prototype uses mean log-normalized difference; production should use scanpy rank_genes_groups."],
    )


def marker_detection(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    # Explicit group1+group2 keeps the pairwise contrast; otherwise detect markers
    # for every cluster/cell type with a one-vs-rest ranking (the usual "markers for
    # each cluster" request), instead of a single arbitrary pair.
    if params.get("group1") and params.get("group2"):
        result = differential_expression(dataset, params)
        result.summary = result.summary.replace("Ranked", "Detected marker candidates among")
        result.metrics["mode"] = "pairwise"
    else:
        result = _scanpy_marker_detection_one_vs_rest(dataset, params)
        if result is None and params.get("strict_engine"):
            raise MissingPreconditionError(
                "marker_detection requires a successful Scanpy rank_genes_groups backend in strict mode."
            )
        result = result or _prototype_marker_detection_one_vs_rest(dataset, params)
    result.tool_name = "marker_detection"
    result.metrics["adjusted_p_values_only"] = True
    feature_type = str(dataset.metadata.get("feature_type", "gene_counts"))
    if feature_type == "gene_activity":
        result.caveats.append("scATAC markers are accessibility-derived gene-activity markers, not measured expression.")
        result.label_caveat = "Gene activity is accessibility-inferred and must not be reported as measured expression."
    return result


def _marker_groups(dataset: SpatialDataset) -> List[str]:
    return sorted({record.cell_type for record in dataset.records if record.cell_type})


def _scanpy_marker_detection_one_vs_rest(dataset: SpatialDataset, params: Dict[str, object]) -> Optional[ToolResult]:
    if params.get("engine") == "prototype":
        return None
    try:
        group_labels, group_key = resolve_group_labels(dataset, params)
    except MissingPreconditionError:
        raise
    if len({label for label in group_labels if label}) < 2:
        return None
    try:
        import scanpy as sc  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError("Scanpy is required for strict marker detection.") from exc
        return None
    try:
        adata = _dataset_to_anndata(dataset)
        keep = [bool(label) for label in group_labels]
        if sum(keep) < 3:
            raise MissingPreconditionError("marker_detection needs at least three cells with populated group assignments.")
        adata = adata[keep].copy()
        retained_labels = [label for label, include in zip(group_labels, keep) if include]
        adata.obs["spatialmind_group"] = retained_labels
        adata.obs["spatialmind_group"] = adata.obs["spatialmind_group"].astype("category")
        if not dataset.normalized:
            sc.pp.normalize_total(adata, target_sum=1e4)
            sc.pp.log1p(adata)
        method = str(params.get("method", "wilcoxon"))
        n_top = int(params.get("n_top", 25) or 25)
        sc.tl.rank_genes_groups(adata, groupby="spatialmind_group", method=method)
        groups = [str(value) for value in adata.obs["spatialmind_group"].cat.categories]
        markers_by_group: Dict[str, object] = {}
        flattened: List[Dict[str, object]] = []
        for group in groups:
            table = _rank_genes_groups_table(adata, group, limit=n_top)
            markers_by_group[group] = table
            flattened.extend(table)
        return ToolResult(
            tool_name="marker_detection",
            summary="Detected one-vs-rest marker candidates for %d groups with Scanpy rank_genes_groups." % len(groups),
            metrics={
                "engine": "scanpy",
                "method": method,
                "mode": "one_vs_rest",
                "group_key": group_key,
                "groups": groups,
                "analyzed_cell_count": int(adata.n_obs),
                "excluded_unassigned_cell_count": len(group_labels) - int(adata.n_obs),
                "markers_by_group": markers_by_group,
                "ranked_genes": flattened,
            },
            caveats=list(dataset.notes),
        )
    except Exception:
        if params.get("strict_engine"):
            raise
        return None


def _prototype_marker_detection_one_vs_rest(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    group_labels, group_key = resolve_group_labels(dataset, params)
    groups = sorted({label for label in group_labels if label})
    if len(groups) < 2:
        raise MissingPreconditionError("marker_detection requires at least two cell groups.")
    genes = expression_feature_names(dataset)
    n_top = int(params.get("n_top", 25) or 25)
    markers_by_group: Dict[str, object] = {}
    flattened: List[Dict[str, object]] = []
    for group in groups:
        in_group = [record for record, label in zip(dataset.records, group_labels) if label == group]
        rest = [record for record, label in zip(dataset.records, group_labels) if label != group]
        rows = []
        for gene in genes:
            first = [record.genes.get(gene, 0.0) for record in in_group]
            second = [record.genes.get(gene, 0.0) for record in rest]
            if not first or not second:
                continue
            logfc = _mean(first) - _mean(second)
            rows.append({"gene": gene, "logFC": round(logfc, 4), "pval_adj": _pseudo_pvalue(abs(logfc)), "group": group})
        rows.sort(key=lambda item: abs(float(item["logFC"])), reverse=True)
        rows = rows[:n_top]
        markers_by_group[group] = rows
        flattened.extend(rows)
    return ToolResult(
        tool_name="marker_detection",
        summary="Detected one-vs-rest marker candidates for %d groups." % len(groups),
        metrics={
            "mode": "one_vs_rest",
            "group_key": group_key,
            "groups": groups,
            "markers_by_group": markers_by_group,
            "ranked_genes": flattened,
        },
        caveats=["Prototype uses one-vs-rest mean log-normalized difference; production uses scanpy rank_genes_groups."],
    )


def attach_quality_metrics(result: ToolResult, dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    if result.quality_metrics is not None:
        return result
    result.quality_metrics = _quality_metrics_for_result(result, dataset, params)
    result.metrics.setdefault("quality_metrics", _quality_metrics_to_dict(result.quality_metrics))
    return result


def cnv_inference(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    normal_ref_count = int(params.get("normal_ref_count", 0) or 0)
    if normal_ref_count and normal_ref_count < 50:
        raise InsufficientDataError("cnv_inference needs at least 50 normal reference cells; got %d." % normal_ref_count)
    return _scaffold_result(
        "cnv_inference",
        "CNV inference scaffold validated inputs but did not run inferCNVpy.",
        "Install infercnvpy and provide normal reference cells before using production CNV inference.",
        params,
    )


def tumor_niche_analysis(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    return _scaffold_result(
        "tumor_niche_analysis",
        "Tumor niche analysis scaffold summarized available labels but did not run TME statistics.",
        "Requires validated tumor labels plus Squidpy/statistical wrappers for production.",
        params,
    )


def protein_coexpression(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    _require_modality(dataset, "protein_coexpression", ["multiplexed_protein", "protein_imaging"])
    return _scaffold_result(
        "protein_coexpression",
        "Protein co-expression scaffold is registered for IMC/CODEX datasets.",
        "Requires protein marker matrix and correlation/cluster implementation.",
        params,
    )


def cell_phenotyping_spatial(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    _require_modality(dataset, "cell_phenotyping_spatial", ["multiplexed_protein", "protein_imaging"])
    return _scaffold_result(
        "cell_phenotyping_spatial",
        "Spatial cell phenotyping scaffold is registered for protein imaging datasets.",
        "Requires FlowSOM-style phenotyping implementation.",
        params,
    )


def pathway_activity(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    return _scaffold_result(
        "pathway_activity",
        "Pathway activity scaffold is ready for decoupleR/PROGENy integration.",
        "Requires decoupleR resource loading and pathway scoring.",
        params,
    )


def transcription_factor_activity(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    return _scaffold_result(
        "transcription_factor_activity",
        "TF activity scaffold is ready for CollecTRI/decoupleR integration.",
        "Requires regulon resource loading and TF scoring.",
        params,
    )


def spatial_communication_flow(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    return _scaffold_result(
        "spatial_communication_flow",
        "Spatial communication flow scaffold is registered for LIANA consensus analysis.",
        "Requires LIANA/OmniPath resources and cached ligand-receptor databases.",
        params,
    )


def niche_differential_analysis(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    if not any(record.region for record in dataset.records):
        raise MissingPreconditionError("niche_differential_analysis requires niche or region labels.")
    return _scaffold_result(
        "niche_differential_analysis",
        "Niche differential analysis scaffold validated region labels.",
        "Requires spatially aware differential model implementation.",
        params,
    )


def chromatin_accessibility_spatial(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    _require_modality(dataset, "chromatin_accessibility_spatial", ["spatial_atac", "chromatin_accessibility"])
    return _scaffold_result(
        "chromatin_accessibility_spatial",
        "Spatial chromatin accessibility scaffold is registered for ATAC datasets.",
        "Requires snapatac2/peak matrix integration.",
        params,
    )


def motif_enrichment_spatial(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    _require_modality(dataset, "motif_enrichment_spatial", ["spatial_atac", "chromatin_accessibility"])
    return _scaffold_result(
        "motif_enrichment_spatial",
        "Spatial motif enrichment scaffold is registered for ATAC datasets.",
        "Run chromatin_accessibility_spatial first and provide DA peaks.",
        params,
    )


def multi_sample_comparison(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    return _scaffold_result(
        "multi_sample_comparison",
        "Multi-sample comparison scaffold is registered; batch engine supplies real sample lists.",
        "Requires batch-level dataset collection rather than a single SpatialDataset.",
        params,
    )


def tissue_segmentation(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    _require_modality(dataset, "tissue_segmentation", ["morphology_image", "he_image"])
    return _scaffold_result(
        "tissue_segmentation",
        "Tissue segmentation scaffold is registered for H&E/imaging inputs.",
        "Requires Cellpose/StarDist image segmentation integration.",
        params,
    )


def spatial_gene_programs(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_records(dataset)
    if len(dataset.genes) < 5:
        raise InsufficientDataError("spatial_gene_programs requires at least 5 features; got %d." % len(dataset.genes))
    return _scaffold_result(
        "spatial_gene_programs",
        "Spatial gene program scaffold validated feature availability.",
        "Requires NMF/MEFISTO factorization implementation.",
        params,
    )


def cell_abundance_heatmap_regions(dataset: SpatialDataset, params: Dict[str, object]) -> ToolResult:
    require_cell_types(dataset)
    if not any(record.region for record in dataset.records):
        raise MissingPreconditionError("cell_abundance_heatmap_regions requires region labels.")
    return _scaffold_result(
        "cell_abundance_heatmap_regions",
        "Region-aware cell abundance scaffold validated region labels.",
        "Requires region x cell-type matrix statistics for production.",
        params,
    )


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def _scanpy_differential_expression(dataset: SpatialDataset, params: Dict[str, object]) -> Optional[ToolResult]:
    if params.get("engine") == "prototype":
        return None
    group_key = str(params.get("group_key", "cell_type"))
    group1 = str(params.get("group1", "CD8+ T cell"))
    group2 = str(params.get("group2", "Tumor cell"))
    if group_key != "cell_type" or group1 not in dataset.cell_types or group2 not in dataset.cell_types:
        return None
    try:
        import scanpy as sc  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError("Scanpy is required for strict differential expression.") from exc
        return None
    try:
        adata = _dataset_to_anndata(dataset)
        method = str(params.get("method", "wilcoxon"))
        if not dataset.normalized:
            sc.pp.normalize_total(adata, target_sum=1e4)
            sc.pp.log1p(adata)
        sc.tl.rank_genes_groups(adata, groupby="cell_type", groups=[group1], reference=group2, method=method)
        table = _rank_genes_groups_table(adata, group1, limit=int(params.get("n_top", 50) or 50))
        return ToolResult(
            tool_name="differential_expression",
            summary="Ranked %d genes for %s vs %s with Scanpy rank_genes_groups." % (len(table), group1, group2),
            metrics={"engine": "scanpy", "method": method, "group_key": group_key, "group1": group1, "group2": group2, "ranked_genes": table},
            caveats=list(dataset.notes),
        )
    except Exception as exc:
        if params.get("strict_engine"):
            raise
        return ToolResult(
            tool_name="differential_expression",
            summary="Scanpy differential expression could not run; used no real-wrapper result.",
            metrics={"engine": "scanpy", "status": "failed", "error": str(exc)},
            caveats=["Set engine='prototype' to force the lightweight fallback or inspect the Scanpy error."],
        )


def _scanpy_spatial_clustering(dataset: SpatialDataset, params: Dict[str, object]) -> Optional[ToolResult]:
    if params.get("engine") == "prototype":
        return None
    try:
        import scanpy as sc  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError("Scanpy and Leiden dependencies are required for strict clustering.") from exc
        return None
    try:
        import numpy as np  # type: ignore

        adata = _dataset_to_anndata(dataset)
        cluster_on = str(params.get("cluster_on", "expression") or "expression")
        n_neighbors = int(params.get("n_neighbors", min(15, max(2, len(dataset.records) - 1))) or 10)
        resolution = float(params.get("resolution", 0.5))
        random_state = int(params.get("random_state", 0) or 0)
        # Per-cell QC uses preserved counts when available and reports its source.
        expression_qc = _expression_qc_metrics(adata)
        analysis_adata = adata
        keep_mask = np.ones(adata.n_obs, dtype=bool)
        if cluster_on == "spatial":
            sc.pp.neighbors(analysis_adata, n_neighbors=max(2, n_neighbors), use_rep="spatial", random_state=random_state)
            method = "spatial_neighbors_leiden"
            representation = "spatial"
        else:
            # Cells without any measured expression cannot be positioned
            # meaningfully in PCA space. Keep them in the dataset for provenance,
            # but exclude them from clustering and downstream cluster-group tests.
            feature_counts = np.asarray((adata.X > 0).sum(axis=1)).reshape(-1)
            keep_mask = feature_counts > 0
            if int(keep_mask.sum()) < 3:
                raise InsufficientDataError("Expression clustering requires at least three cells with measured features.")
            analysis_adata = adata[keep_mask].copy()
            # Transcriptomic clustering: normalize -> log1p -> PCA -> expression graph -> Leiden.
            if not dataset.normalized:
                sc.pp.normalize_total(analysis_adata, target_sum=1e4)
                sc.pp.log1p(analysis_adata)
            n_comps = min(50, analysis_adata.n_vars - 1, analysis_adata.n_obs - 1)
            if n_comps >= 2 and analysis_adata.n_vars > 2:
                sc.pp.pca(analysis_adata, n_comps=n_comps, random_state=random_state)
                sc.pp.neighbors(
                    analysis_adata,
                    n_neighbors=max(2, n_neighbors),
                    use_rep="X_pca",
                    random_state=random_state,
                )
                representation = "X_pca(%d)" % n_comps
            else:
                sc.pp.neighbors(analysis_adata, n_neighbors=max(2, n_neighbors), random_state=random_state)
                representation = "X"
            method = "pca_neighbors_leiden"
        sc.tl.leiden(
            analysis_adata,
            resolution=resolution,
            random_state=random_state,
            key_added="spatialmind_cluster",
            flavor="igraph",
            n_iterations=2,
            directed=False,
        )
        analyzed_labels = [str(value) for value in analysis_adata.obs["spatialmind_cluster"].tolist()]
        labels = [""] * int(adata.n_obs)
        analyzed_index = 0
        for index, include in enumerate(keep_mask):
            if bool(include):
                labels[index] = analyzed_labels[analyzed_index]
                analyzed_index += 1
        counts = dict(Counter(analyzed_labels))
        # Publish assignments so marker and neighbourhood tools can group by these
        # data-derived clusters instead of requiring expert cell-type labels.
        store_cluster_assignments(dataset, labels)
        diagnostics = _clustering_diagnostics(analysis_adata, analyzed_labels, representation, random_state)
        excluded_count = int(adata.n_obs - analysis_adata.n_obs)
        cluster_style = "spatial-domain" if cluster_on == "spatial" else "expression"
        exclusion_text = " Excluded %d zero-feature cells." % excluded_count if excluded_count else ""
        return ToolResult(
            tool_name="spatial_clustering",
            summary=(
                "Assigned %d observations to %d %s clusters with Scanpy neighbors + Leiden.%s"
                % (analysis_adata.n_obs, len(counts), cluster_style, exclusion_text)
            ),
            metrics={
                "engine": "scanpy",
                "method": method,
                "cluster_on": cluster_on,
                "representation": representation,
                "resolution": resolution,
                "n_neighbors": n_neighbors,
                "random_state": random_state,
                "cluster_counts": counts,
                "total_cell_count": int(adata.n_obs),
                "analyzed_cell_count": int(analysis_adata.n_obs),
                "excluded_zero_feature_cell_count": excluded_count,
                "silhouette": diagnostics["silhouette"],
                "modularity": diagnostics["modularity"],
                "expression_qc": expression_qc,
            },
            caveats=list(dataset.notes)
            + (["Excluded %d cells with zero measured expression features from clustering." % excluded_count] if excluded_count else []),
        )
    except Exception as exc:
        if params.get("strict_engine"):
            raise
        return None


def _clustering_diagnostics(
    adata: Any,
    labels: List[str],
    representation: str,
    random_state: int,
) -> Dict[str, Optional[float]]:
    """Compute real diagnostic scores for the exact graph and embedding used."""
    if len(labels) < 3 or len(set(labels)) < 2:
        return {"silhouette": None, "modularity": None}
    silhouette: Optional[float] = None
    modularity: Optional[float] = None
    try:
        import numpy as np  # type: ignore
        from sklearn.metrics import silhouette_score  # type: ignore

        if representation == "spatial":
            values = np.asarray(adata.obsm["spatial"], dtype=float)
        elif representation.startswith("X_pca"):
            values = np.asarray(adata.obsm["X_pca"], dtype=float)
        else:
            values = np.asarray(adata.X, dtype=float)
        sample_size = min(5000, len(labels))
        silhouette = float(
            silhouette_score(
                values,
                labels,
                sample_size=sample_size if sample_size < len(labels) else None,
                random_state=random_state,
            )
        )
    except Exception:
        silhouette = None
    try:
        import igraph as ig  # type: ignore
        from scipy.sparse import triu  # type: ignore

        connectivities = triu(adata.obsp["connectivities"], k=1).tocoo()
        graph = ig.Graph(
            n=len(labels),
            edges=list(zip(connectivities.row.tolist(), connectivities.col.tolist())),
            directed=False,
        )
        weights = [float(value) for value in connectivities.data]
        graph.es["weight"] = weights
        label_index = {label: index for index, label in enumerate(sorted(set(labels)))}
        membership = [label_index[label] for label in labels]
        modularity = float(graph.modularity(membership, weights=weights))
    except Exception:
        modularity = None
    return {
        "silhouette": round(silhouette, 5) if silhouette is not None and math.isfinite(silhouette) else None,
        "modularity": round(modularity, 5) if modularity is not None and math.isfinite(modularity) else None,
    }


def _expression_qc_metrics(adata: Any) -> Dict[str, object]:
    import numpy as np  # type: ignore

    if "counts" in adata.layers:
        source = "raw_counts"
        matrix = adata.layers["counts"]
    elif "source_values" in adata.layers:
        source = "source_values"
        matrix = adata.layers["source_values"]
    else:
        source = "analysis_values_fallback"
        matrix = adata.X
    if hasattr(matrix, "toarray"):
        matrix = matrix.toarray()
    matrix = np.asarray(matrix, dtype=float)
    if matrix.size == 0:
        return {
            "source": source,
            "n_cells": int(matrix.shape[0]),
            "n_features": int(matrix.shape[1] if matrix.ndim > 1 else 0),
        }
    total_counts = matrix.sum(axis=1)
    features_per_cell = (matrix > 0).sum(axis=1)
    return {
        "source": source,
        "n_cells": int(matrix.shape[0]),
        "n_features": int(matrix.shape[1]),
        "mean_total_counts": round(float(np.mean(total_counts)), 4),
        "median_total_counts": round(float(np.median(total_counts)), 4),
        "mean_features_per_cell": round(float(np.mean(features_per_cell)), 4),
        "median_features_per_cell": round(float(np.median(features_per_cell)), 4),
        "min_features_per_cell": int(np.min(features_per_cell)),
    }


def _squidpy_spatial_variable_genes(
    dataset: SpatialDataset,
    params: Dict[str, object],
) -> Optional[ToolResult]:
    """Rank genes by genuine spatial autocorrelation with permutation support."""
    if params.get("engine") == "scanpy" or params.get("engine") == "prototype":
        return None
    try:
        import squidpy as sq  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError("Squidpy is required for strict spatial autocorrelation.") from exc
        return None
    try:
        adata = _dataset_to_anndata(dataset)
        if not dataset.normalized:
            import scanpy as sc  # type: ignore

            sc.pp.normalize_total(adata, target_sum=1e4)
            sc.pp.log1p(adata)
        n_top = max(1, int(params.get("n_top", 50) or 50))
        n_neighs = max(2, int(params.get("n_neighs", 6) or 6))
        n_perms = max(10, int(params.get("n_perms", 100) or 100))
        random_state = int(params.get("random_state", 0) or 0)
        sq.gr.spatial_neighbors(adata, coord_type="generic", n_neighs=n_neighs)
        table = sq.gr.spatial_autocorr(
            adata,
            mode="moran",
            n_perms=n_perms,
            two_tailed=True,
            corr_method="fdr_bh",
            seed=random_state,
            copy=True,
            n_jobs=1,
            backend="threading",
            show_progress_bar=False,
        )
        if table is None or table.empty:
            return None
        score_key = "I"
        adjusted_candidates = [
            key
            for key in ("pval_sim_fdr_bh", "pval_z_sim_fdr_bh", "pval_norm_fdr_bh")
            if key in table.columns
        ]
        adjusted_key = adjusted_candidates[0] if adjusted_candidates else ""
        rows = []
        ranked = table.sort_values(score_key, ascending=False)
        for gene, row in ranked.head(n_top).iterrows():
            item: Dict[str, object] = {
                "gene": str(gene),
                "morans_i": round(float(row.get(score_key, 0.0)), 6),
            }
            for source, target in (
                ("pval_sim", "pval_permutation"),
                ("pval_z_sim", "pval_permutation_z"),
                ("pval_norm", "pval_normality"),
            ):
                if source in table.columns and math.isfinite(float(row.get(source, math.nan))):
                    item[target] = round(float(row[source]), 8)
            if adjusted_key and math.isfinite(float(row.get(adjusted_key, math.nan))):
                item["pval_adj"] = round(float(row[adjusted_key]), 8)
                item["pval_adj_source"] = adjusted_key
            rows.append(item)
        significant = sum(1 for row in rows if float(row.get("pval_adj", 1.0)) <= 0.05)
        significant_all = (
            int((table[adjusted_key] <= 0.05).sum()) if adjusted_key and adjusted_key in table.columns else 0
        )
        return ToolResult(
            tool_name="spatial_variable_genes",
            summary=(
                "Ranked %d genes by Squidpy Moran's I spatial autocorrelation; %d passed FDR <= 0.05."
                % (len(rows), significant)
            ),
            metrics={
                "engine": "squidpy",
                "method": "moranI",
                "n_neighs": n_neighs,
                "n_perms": n_perms,
                "random_state": random_state,
                "multiple_testing": adjusted_key or "not_available",
                "significant_gene_count_top_n": significant,
                "significant_gene_count_all": significant_all,
                "top_genes": rows,
            },
            caveats=[
                "Moran's I detects global spatial autocorrelation; it does not identify the anatomical region driving a pattern.",
                "Results depend on the spatial graph, panel composition, segmentation, and field of view.",
            ]
            + _type_honesty_caveats(dataset),
        )
    except Exception:
        if params.get("strict_engine"):
            raise
        return None


def _scanpy_spatial_variable_genes(dataset: SpatialDataset, params: Dict[str, object]) -> Optional[ToolResult]:
    if params.get("engine") == "prototype":
        return None
    try:
        import scanpy as sc  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError("Scanpy is required for variable-gene fallback analysis.") from exc
        return None
    try:
        adata = _dataset_to_anndata(dataset)
        n_top = int(params.get("n_top", 50) or 50)
        sc.pp.highly_variable_genes(adata, n_top_genes=min(n_top, adata.n_vars), flavor=str(params.get("flavor", "seurat")))
        rows = []
        hvg = adata.var.sort_values("dispersions_norm" if "dispersions_norm" in adata.var else "means", ascending=False)
        for gene, row in hvg.head(n_top).iterrows():
            rows.append(
                {
                    "gene": str(gene),
                    "mean": round(float(row.get("means", 0.0)), 5),
                    "dispersion_norm": round(float(row.get("dispersions_norm", 0.0)), 5),
                    "highly_variable": bool(row.get("highly_variable", False)),
                }
            )
        return ToolResult(
            tool_name="spatial_variable_genes",
            summary="Ranked %d variable genes with Scanpy highly_variable_genes." % len(rows),
            metrics={"engine": "scanpy", "method": "highly_variable_genes_fallback", "top_genes": rows},
            caveats=[
                "This is an expression-variability fallback, not a spatial autocorrelation test; install Squidpy or inspect the spatial backend error."
            ],
        )
    except Exception as exc:
        if params.get("strict_engine"):
            raise
        return None


def _squidpy_neighborhood_enrichment(dataset: SpatialDataset, params: Dict[str, object]) -> Optional[ToolResult]:
    if params.get("engine") == "prototype":
        return None
    try:
        import squidpy as sq  # type: ignore
    except ImportError as exc:
        if params.get("strict_engine"):
            raise MissingPreconditionError("Squidpy is required for strict neighborhood enrichment.") from exc
        return None
    try:
        adata = _dataset_to_anndata(dataset)
        group_labels, group_key = resolve_group_labels(dataset, params)
        keep = [bool(label) for label in group_labels]
        if sum(keep) < 3:
            raise MissingPreconditionError(
                "neighborhood_enrichment needs at least three cells with populated group assignments."
            )
        adata = adata[keep].copy()
        retained_labels = [label for label, include in zip(group_labels, keep) if include]
        adata.obs["spatialmind_group"] = retained_labels
        adata.obs["spatialmind_group"] = adata.obs["spatialmind_group"].astype("category")
        n_neighs = int(params.get("n_neighs", min(6, max(2, len(dataset.records) - 1))) or 6)
        n_perms = int(params.get("n_perms", 100) or 100)
        n_jobs = int(params.get("n_jobs", 1) or 1)
        backend = str(params.get("backend", "threading") or "threading")
        random_state = int(params.get("random_state", 0) or 0)
        sq.gr.spatial_neighbors(adata, coord_type="generic", n_neighs=max(2, n_neighs))
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="invalid value encountered in divide", category=RuntimeWarning)
            sq.gr.nhood_enrichment(
                adata,
                cluster_key="spatialmind_group",
                n_perms=n_perms,
                seed=random_state,
                n_jobs=n_jobs,
                backend=backend,
                numba_parallel=False,
                show_progress_bar=False,
            )
        result = adata.uns.get("spatialmind_group_nhood_enrichment", {})
        clusters = [str(value) for value in adata.obs["spatialmind_group"].cat.categories]
        all_pairs = _nhood_enrichment_pairs(result.get("zscore"), result.get("pvalue"), clusters, limit=None)
        expected_pair_count = len(clusters) * (len(clusters) + 1) // 2
        nonfinite_pair_count = max(expected_pair_count - len(all_pairs), 0)
        top_pairs = all_pairs[:10]
        metrics = {
            "engine": "squidpy",
            "method": "nhood_enrichment",
            "group_key": group_key,
            "n_neighs": n_neighs,
            "n_perms": n_perms,
            "n_jobs": n_jobs,
            "backend": backend,
            "random_state": random_state,
            "analyzed_cell_count": int(adata.n_obs),
            "excluded_unassigned_cell_count": len(group_labels) - int(adata.n_obs),
            "top_pairs": top_pairs,
            "tested_pair_count": len(all_pairs),
            "undefined_pair_count": nonfinite_pair_count,
        }
        if params.get("include_all_pairs"):
            metrics["all_pairs"] = all_pairs
        caveats = list(dataset.notes)
        if nonfinite_pair_count:
            caveats.append(
                "%d cell-type pairs had zero/undefined permutation variance and were omitted." % nonfinite_pair_count
            )
        return ToolResult(
            tool_name="neighborhood_enrichment",
            summary="Computed neighborhood enrichment with Squidpy for %d cell-type pairs." % len(top_pairs),
            metrics=metrics,
            caveats=caveats,
        )
    except Exception as exc:
        if params.get("strict_engine"):
            raise
        return None


# Per-cell QC/morphology pseudo-features that the Xenium loader stores alongside
# real gene counts. They are library-size / area proxies on a different scale and
# must be excluded from the expression matrix, or they dominate PCA/clustering and
# rank as spurious markers. Mirrors ingestion.labels.NON_BIOLOGICAL_FEATURES.
EXPRESSION_EXCLUDED_FEATURES = {"TRANSCRIPT_COUNTS", "TOTAL_COUNTS", "CELL_AREA", "NUCLEUS_AREA"}


def expression_feature_names(dataset: SpatialDataset) -> List[str]:
    """Genes used for expression analysis, excluding QC/morphology pseudo-features."""
    biological = [gene for gene in dataset.genes if gene.upper() not in EXPRESSION_EXCLUDED_FEATURES]
    # Only drop the pseudo-features when real genes remain (keeps tiny fixtures usable).
    return biological if len(biological) >= 2 else list(dataset.genes)


def _dataset_to_anndata(dataset: SpatialDataset) -> Any:
    import anndata as ad  # type: ignore
    import numpy as np  # type: ignore
    import pandas as pd  # type: ignore

    genes = expression_feature_names(dataset)
    if not genes:
        raise MissingPreconditionError("Scanpy/Squidpy wrappers require numeric features.")
    matrix = np.array([[record.genes.get(gene, 0.0) for gene in genes] for record in dataset.records], dtype=float)
    source_matrix = np.array(
        [[record.raw_genes.get(gene, record.genes.get(gene, 0.0)) for gene in genes] for record in dataset.records],
        dtype=float,
    )
    obs = pd.DataFrame(
        {
            "sample_id": [record.sample_id for record in dataset.records],
            "cell_type": [record.cell_type for record in dataset.records],
            "region": [record.region or "" for record in dataset.records],
            "x": [record.x for record in dataset.records],
            "y": [record.y for record in dataset.records],
        },
        index=[record.cell_id or "cell_%d" % index for index, record in enumerate(dataset.records)],
    )
    obs["cell_type"] = obs["cell_type"].astype("category")
    adata = ad.AnnData(X=matrix, obs=obs)
    adata.var_names = genes
    adata.layers["source_values"] = source_matrix
    if dataset.metadata.get("raw_counts_available"):
        adata.layers["counts"] = source_matrix.copy()
    adata.obsm["spatial"] = np.array([[record.x, record.y] for record in dataset.records], dtype=float)
    adata.uns["spatialmind"] = {
        "sample_id": dataset.sample_id,
        "normalized": dataset.normalized,
        "source_value_semantics": dataset.metadata.get("source_value_semantics", "unspecified"),
        "raw_counts_available": bool(dataset.metadata.get("raw_counts_available")),
    }
    return adata


def _rank_genes_groups_table(adata: Any, group: str, limit: int) -> List[Dict[str, object]]:
    result = adata.uns.get("rank_genes_groups", {})
    rows = []
    names = result.get("names")
    if names is None:
        return rows
    for index, gene in enumerate(_group_values(names, group)[:limit]):
        item = {"gene": str(gene), "group": group}
        for source_key, output_key in (("scores", "score"), ("logfoldchanges", "logFC"), ("pvals_adj", "pval_adj"), ("pvals", "pval")):
            values = result.get(source_key)
            if values is None:
                continue
            try:
                item[output_key] = round(float(_group_values(values, group)[index]), 6)
            except (IndexError, TypeError, ValueError):
                continue
        rows.append(item)
    return rows


def _group_values(values: Any, group: str) -> List[Any]:
    if hasattr(values, "dtype") and getattr(values.dtype, "names", None):
        return list(values[group])
    if isinstance(values, dict):
        return list(values.get(group, []))
    return list(values)


def _nhood_enrichment_pairs(
    zscores: Any,
    pvalues: Any,
    clusters: List[str],
    limit: Optional[int] = 10,
) -> List[Dict[str, object]]:
    if zscores is None:
        return []
    pairs = []
    for left_index, left in enumerate(clusters):
        for right_index, right in enumerate(clusters):
            if right_index < left_index:
                continue
            try:
                zscore = float(zscores[left_index, right_index])
            except (TypeError, ValueError, IndexError):
                continue
            if not math.isfinite(zscore):
                continue
            item: Dict[str, object] = {"pair": "%s | %s" % (left, right), "zscore": round(zscore, 5)}
            if pvalues is not None:
                try:
                    pvalue = float(pvalues[left_index, right_index])
                    if math.isfinite(pvalue):
                        item["pval"] = round(pvalue, 6)
                except (TypeError, ValueError, IndexError):
                    pass
            pairs.append(item)
    pairs.sort(key=lambda item: abs(float(item["zscore"])), reverse=True)
    return pairs if limit is None else pairs[:limit]


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pseudo_pvalue(effect: float) -> float:
    return round(max(0.001, min(1.0, 1.0 / (1.0 + abs(effect)))), 4)


def _require_modality(dataset: SpatialDataset, tool_name: str, expected: List[str]) -> None:
    got = (dataset.modality or "").lower()
    if got not in {item.lower() for item in expected}:
        raise DataModalityError(tool_name, dataset.modality, " or ".join(expected))


def _scaffold_result(tool_name: str, summary: str, caveat: str, params: Dict[str, object]) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        summary=summary,
        metrics={"status": "registered_scaffold", "params": dict(params)},
        caveats=[caveat],
    )


def _quality_metrics_for_result(result: ToolResult, dataset: SpatialDataset, params: Dict[str, object]) -> QualityMetrics:
    qc = QCMetrics(
        record_count=metric(
            float(len(dataset.records)),
            "computed",
            "qc",
            "SpatialMind record count",
            data_subset="loaded_records",
        ),
        feature_count=metric(
            float(len(dataset.genes)),
            "computed",
            "qc",
            "SpatialMind feature count",
            data_subset="loaded_features",
        ),
        missing_feature_fraction=metric(
            float(dataset.qc_metrics.get("missing_feature_fraction", 0.0) or 0.0),
            "computed",
            "qc",
            "SpatialMind ingestion QC",
            data_subset="loaded_records",
        ),
    )
    quality = QualityMetrics(qc=qc)
    if result.tool_name in {"qc_and_cluster", "spatial_clustering"}:
        silhouette = result.metrics.get("silhouette")
        modularity = result.metrics.get("modularity")
        quality.clustering = ClusteringMetrics(
            silhouette=metric(
                float(silhouette) if silhouette is not None else None,
                "computed" if silhouette is not None else "not_applicable",
                "diagnostic",
                "silhouette on clustering representation",
                dict(params),
                caveat="Silhouette is diagnostic only and can understate continuous tissue gradients.",
            ),
            modularity=metric(
                float(modularity) if modularity is not None else None,
                "computed" if modularity is not None else "not_applicable",
                "diagnostic",
                "weighted kNN graph modularity",
                dict(params),
                caveat="Graph modularity is a diagnostic of this graph partition, not proof of biological identity.",
            ),
        )
    if result.tool_name in {"annotation", "cell_type_annotation", "reference_label_transfer"}:
        label_report = dataset.metadata.get("label_readiness", {}) if isinstance(dataset.metadata.get("label_readiness"), dict) else {}
        confidence = label_report.get("confidence_summary", {}).get("mean") if isinstance(label_report.get("confidence_summary"), dict) else None
        unassigned = _fraction_unassigned(dataset)
        marker_status = "computed" if result.tool_name == "annotation" else "not_applicable"
        quality.annotation = AnnotationMetrics(
            mean_confidence=metric(
                float(confidence) if confidence is not None else None,
                "computed" if confidence is not None else "not_applicable",
                "diagnostic",
                "annotation confidence",
                dict(params),
                caveat="Annotation confidence is diagnostic; it does not by itself validate labels.",
            ),
            marker_overlap=metric(
                _marker_overlap(dataset),
                marker_status,
                "diagnostic",
                "marker panel overlap",
                dict(params),
                caveat="Marker overlap supports label review but is not ground truth.",
            ),
            fraction_unassigned=metric(
                unassigned,
                "computed",
                "qc",
                "label completeness",
                dict(params),
            ),
        )
    if result.tool_name in {"differential_expression", "marker_detection"}:
        rows = result.metrics.get("ranked_genes", [])
        n_sig = sum(1 for row in rows if float(row.get("pval_adj", 1.0)) <= 0.05) if isinstance(rows, list) else 0
        quality.differential = DifferentialMetrics(
            n_significant=metric(float(n_sig), "computed", "statistical_evidence", "adjusted p-value count", dict(params)),
            pct_expressing=metric(None, "not_applicable", "statistical_evidence", "pct expressing", dict(params)),
            auroc=metric(None, "not_applicable", "statistical_evidence", "AUROC", dict(params)),
        )
    if result.tool_name in {"neighborhood_enrichment", "cell_neighborhood_enrichment"}:
        top_pairs = result.metrics.get("top_pairs", [])
        zscore = None
        if isinstance(top_pairs, list) and top_pairs:
            first = top_pairs[0]
            zscore = first.get("zscore") or first.get("neighbor_count")
        quality.spatial = SpatialMetrics(
            morans_i=metric(None, "not_applicable", "statistical_evidence", "Moran's I", dict(params)),
            cooccurrence_z=metric(
                float(zscore) if zscore is not None else None,
                "computed" if zscore is not None else "insufficient_data",
                "statistical_evidence",
                "neighborhood co-occurrence",
                dict(params),
                caveat="Co-occurrence depends on the selected neighbor graph/radius and permutation design.",
            ),
            mean_neighbors=metric(
                float(result.metrics.get("radius", result.metrics.get("n_neighs", 0)) or 0),
                "computed",
                "diagnostic",
                "neighbor graph diagnostic",
                dict(params),
                caveat="Mean-neighbor diagnostics inform graph quality but do not ground a biological claim.",
            ),
        )
    if result.tool_name == "spatial_variable_genes":
        top_genes = result.metrics.get("top_genes", [])
        top_morans_i = None
        if isinstance(top_genes, list) and top_genes:
            top_morans_i = top_genes[0].get("morans_i")
        n_neighs = result.metrics.get("n_neighs")
        quality.spatial = SpatialMetrics(
            morans_i=metric(
                float(top_morans_i) if top_morans_i is not None else None,
                "computed" if top_morans_i is not None else "insufficient_data",
                "statistical_evidence",
                "Squidpy Moran's I spatial autocorrelation",
                dict(params),
                caveat="Moran's I identifies spatial autocorrelation, not a causal spatial mechanism.",
            ),
            cooccurrence_z=metric(
                None,
                "not_applicable",
                "statistical_evidence",
                "neighborhood co-occurrence",
                dict(params),
            ),
            mean_neighbors=metric(
                float(n_neighs) if n_neighs is not None else None,
                "computed" if n_neighs is not None else "not_applicable",
                "diagnostic",
                "spatial-neighbor graph setting",
                dict(params),
                caveat="This is the requested graph degree, not a measured biological interaction count.",
            ),
        )
    return quality


def _quality_metrics_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return _quality_metrics_to_dict(asdict(value))
    if isinstance(value, dict):
        return {str(key): _quality_metrics_to_dict(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_quality_metrics_to_dict(item) for item in value]
    return value


def _fraction_unassigned(dataset: SpatialDataset) -> float:
    if not dataset.records:
        return 0.0
    placeholders = {"", "unknown", "unannotated", "unannotated cell", "unlabeled", "none", "nan"}
    count = sum(1 for record in dataset.records if record.cell_type.strip().lower() in placeholders)
    return round(count / float(len(dataset.records)), 4)


def _marker_overlap(dataset: SpatialDataset) -> Optional[float]:
    marker_set = {
        "PTPRC",
        "CD3D",
        "CD3E",
        "CD8A",
        "CD4",
        "MS4A1",
        "CD79A",
        "EPCAM",
        "KRT8",
        "KRT15",
        "KRT18",
        "KRT19",
        "ACTA2",
        "PECAM1",
        "VWF",
        "CD68",
        "LYZ",
        "C1QA",
        "MKI67",
    }
    if not dataset.genes:
        return None
    present = {gene.upper() for gene in dataset.genes}
    return round(len(marker_set & present) / float(len(marker_set)), 4)


def _type_honesty_caveats(dataset: SpatialDataset) -> List[str]:
    caveats = []
    feature_type = str(dataset.metadata.get("feature_type") or "")
    if feature_type == "gene_activity" or str(dataset.metadata.get("assay_subtype") or "") == "scatac_gene_activity":
        caveats.append("scATAC gene activity is accessibility-inferred and must not be described as measured expression.")
    if _is_targeted_panel(dataset):
        caveats.append("Xenium uses a targeted panel; a missing gene means not measured, not unexpressed.")
    return caveats


def _is_targeted_panel(dataset: SpatialDataset) -> bool:
    return bool(dataset.metadata.get("is_targeted_panel")) or str(dataset.metadata.get("feature_type") or "") == "targeted_panel"


def _first_or_none(items: List[str]) -> Optional[str]:
    return items[0] if items else None
