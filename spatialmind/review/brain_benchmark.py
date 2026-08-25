import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from spatialmind.ingestion import load_xenium
from spatialmind.ingestion.labels import MARKER_EVIDENCE_FEATURES, NON_BIOLOGICAL_FEATURES
from spatialmind.schemas import SpatialDataset, SpotRecord
from spatialmind.tools import build_mvp_registry
from spatialmind.tools.implementations import expression_feature_names
from spatialmind.viz import VisualizationLayer, XeniumExplorerLiteViewer

from .glioblastoma import DEFAULT_GLIOBLASTOMA_DATASET, DEFAULT_HEALTHY_BRAIN_DATASET


DEFAULT_BRAIN_DATASETS = {
    "healthy_brain": DEFAULT_HEALTHY_BRAIN_DATASET,
    "glioblastoma": DEFAULT_GLIOBLASTOMA_DATASET,
}

LABEL_REVIEW_FIELDS = [
    "cell_id",
    "x",
    "y",
    "expression_cluster",
    "proposed_spatial_block",
    "provisional_split",
    "sampling_weight",
    "current_weak_label",
    "candidate_label",
    "candidate_confidence",
    "reference_review_priority",
    "marker_disagreement",
    "lineage_absent_from_reference",
    "distant_from_reference",
    "qc_stratum",
    "raw_transcript_count",
    "detected_expression_features",
    "top_features",
    "marker_evidence",
    "cluster_markers",
    "selection_priority",
    "selection_reasons",
    "expert_label",
    "cl_id",
    "secondary_state",
    "confidence",
    "reviewer_id",
    "reviewed_at",
    "review_status",
    "notes",
]

REGION_REVIEW_FIELDS = [
    "cell_id",
    "x",
    "y",
    "expression_cluster",
    "proposed_spatial_block",
    "provisional_split",
    "current_weak_label",
    "candidate_label",
    "qc_stratum",
    "region",
    "region_confidence",
    "region_reviewer_id",
    "region_reviewed_at",
    "review_status",
    "notes",
]

SPLIT_FIELDS = [
    "cell_id",
    "dataset_key",
    "expression_cluster",
    "proposed_spatial_block",
    "provisional_split",
    "split_unit",
    "split_status",
    "sampling_weight",
]


def prepare_brain_expert_benchmark(
    output_dir: str,
    dataset_paths: Optional[Mapping[str, str]] = None,
    candidate_label_paths: Optional[Mapping[str, str]] = None,
    cohort_size: int = 750,
    pool_size: int = 10000,
    resolution: float = 0.5,
    n_neighbors: int = 15,
    random_state: int = 42,
    spatial_bins_per_axis: int = 4,
) -> Dict[str, Any]:
    """Prepare leakage-aware expert-review cohorts without inventing labels or ROIs."""
    if cohort_size < 30:
        raise ValueError("cohort_size must be at least 30 so clusters and spatial blocks can be represented.")
    if spatial_bins_per_axis < 3:
        raise ValueError("spatial_bins_per_axis must be at least 3.")
    datasets = dict(dataset_paths or DEFAULT_BRAIN_DATASETS)
    candidates = dict(candidate_label_paths or {})
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    per_dataset: Dict[str, Dict[str, Any]] = {}
    combined_manifest: List[Dict[str, Any]] = []

    for dataset_key, dataset_path in datasets.items():
        dataset_out = root / dataset_key
        dataset_out.mkdir(parents=True, exist_ok=True)
        summary, selected = _prepare_dataset_cohort(
            dataset_key=dataset_key,
            dataset_path=dataset_path,
            output_dir=dataset_out,
            candidate_path=candidates.get(dataset_key),
            cohort_size=cohort_size,
            pool_size=pool_size,
            resolution=resolution,
            n_neighbors=n_neighbors,
            random_state=random_state,
            spatial_bins_per_axis=spatial_bins_per_axis,
        )
        per_dataset[dataset_key] = summary
        for row in selected:
            combined_manifest.append(
                {
                    "dataset_key": dataset_key,
                    "dataset_path": dataset_path,
                    "cell_id": row["cell_id"],
                    "expression_cluster": row["expression_cluster"],
                    "proposed_spatial_block": row["proposed_spatial_block"],
                    "provisional_split": row["provisional_split"],
                    "review_status": row["review_status"],
                }
            )

    _write_csv(
        root / "combined_review_cohort_manifest.csv",
        combined_manifest,
        [
            "dataset_key",
            "dataset_path",
            "cell_id",
            "expression_cluster",
            "proposed_spatial_block",
            "provisional_split",
            "review_status",
        ],
    )
    payload = {
        "created_at": _now(),
        "status": "awaiting_expert_review",
        "cohort_size_requested_per_dataset": cohort_size,
        "analysis_pool_size_requested_per_dataset": pool_size,
        "resolution": resolution,
        "n_neighbors": n_neighbors,
        "random_state": random_state,
        "split_policy": (
            "Provisional train/validation/test assignments are made by spatial block, never by individual cell. "
            "Replace them with specimen- or reviewed-ROI-level splits when independent units are available."
        ),
        "datasets": per_dataset,
        "combined_manifest": str(root / "combined_review_cohort_manifest.csv"),
        "important_boundary": (
            "Machine-generated clusters, candidate labels, spatial blocks, and split assignments are review aids. "
            "No expert_label or region field is prefilled, and this packet is not biological ground truth."
        ),
    }
    _write_json(root / "brain_benchmark_packet_summary.json", payload)
    _write_packet_readme(root / "README.md", payload)
    payload["validation"] = validate_brain_benchmark_packet(str(root))
    _write_json(root / "brain_benchmark_packet_summary.json", payload)
    return payload


def validate_brain_benchmark_packet(
    packet_dir: str,
    minimum_review_coverage: float = 0.9,
) -> Dict[str, Any]:
    """Validate packet integrity and materialize frozen truth splits after review."""
    root = Path(packet_dir)
    dataset_reports: Dict[str, Dict[str, Any]] = {}
    ready_datasets = 0
    for dataset_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        label_path = dataset_dir / "expert_cell_labels_for_review.csv"
        region_path = dataset_dir / "cell_regions_for_review.csv"
        split_path = dataset_dir / "benchmark_split_manifest.csv"
        if not (label_path.exists() and region_path.exists() and split_path.exists()):
            continue
        labels = _read_csv(label_path)
        regions = _read_csv(region_path)
        splits = _read_csv(split_path)
        report = _validate_dataset_tables(labels, regions, splits, minimum_review_coverage)
        dataset_reports[dataset_dir.name] = report
        if report["status"] == "ready_for_frozen_benchmark":
            ready_datasets += 1
            _write_reviewed_truth_outputs(dataset_dir, labels, regions, splits)

    status = "ready" if dataset_reports and ready_datasets == len(dataset_reports) else "awaiting_expert_review"
    report = {
        "created_at": _now(),
        "status": status,
        "minimum_review_coverage": minimum_review_coverage,
        "dataset_count": len(dataset_reports),
        "ready_dataset_count": ready_datasets,
        "datasets": dataset_reports,
        "required_next_step": (
            "Complete expert labels and reviewed regions in each dataset packet, including reviewer IDs, then rerun validation."
            if status != "ready"
            else "Frozen benchmark splits are ready for annotation and claim-reliability evaluation."
        ),
    }
    _write_json(root / "benchmark_validation.json", report)
    summary_path = root / "brain_benchmark_packet_summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary = None
        if isinstance(summary, dict):
            summary["status"] = status
            summary["validation"] = report
            for dataset_key, dataset_report in dataset_reports.items():
                dataset_summary = summary.get("datasets", {}).get(dataset_key)
                if isinstance(dataset_summary, dict):
                    dataset_summary["status"] = dataset_report["status"]
            _write_json(summary_path, summary)
    return report


def _prepare_dataset_cohort(
    dataset_key: str,
    dataset_path: str,
    output_dir: Path,
    candidate_path: Optional[str],
    cohort_size: int,
    pool_size: int,
    resolution: float,
    n_neighbors: int,
    random_state: int,
    spatial_bins_per_axis: int,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    dataset = load_xenium(dataset_path, max_records=pool_size, max_features_per_record=0)
    registry = build_mvp_registry()
    clustering = registry.get("qc_and_cluster").run(
        dataset,
        {
            "cluster_on": "expression",
            "resolution": resolution,
            "n_neighbors": n_neighbors,
            "random_state": random_state,
            "strict_engine": True,
        },
    )
    markers = registry.get("marker_detection").run(
        dataset,
        {"group_key": "cluster", "n_top": 12, "strict_engine": True},
    )
    assignments = dataset.metadata.get("cluster_assignments", {})
    marker_rows = markers.metrics.get("markers_by_group", {})
    cluster_markers = {
        str(cluster): [str(item.get("gene")) for item in rows[:8] if item.get("gene")]
        for cluster, rows in marker_rows.items()
    }
    candidate_rows = _load_candidates(candidate_path)
    spatial_blocks = _spatial_blocks(dataset, bins_per_axis=spatial_bins_per_axis)
    split_by_block = _assign_spatial_block_splits(spatial_blocks.values(), dataset_key)
    evidence_rows = _build_evidence_rows(
        dataset,
        assignments,
        cluster_markers,
        candidate_rows,
        spatial_blocks,
        split_by_block,
    )
    selected = _stratified_select(evidence_rows, min(cohort_size, len(evidence_rows)), dataset_key)
    selected = _rebalance_qc_strata(selected, evidence_rows, dataset_key)
    selected_ids = {row["cell_id"] for row in selected}
    pool_cluster_counts = Counter(row["expression_cluster"] for row in evidence_rows)
    selected_cluster_counts = Counter(row["expression_cluster"] for row in selected)
    for row in selected:
        denominator = selected_cluster_counts[row["expression_cluster"]] or 1
        row["sampling_weight"] = round(pool_cluster_counts[row["expression_cluster"]] / float(denominator), 6)
    selected.sort(key=lambda row: (row["provisional_split"], _sort_cluster(row["expression_cluster"]), row["cell_id"]))

    _write_csv(output_dir / "expert_cell_labels_for_review.csv", selected, LABEL_REVIEW_FIELDS)
    region_rows = [{field: row.get(field, "") for field in REGION_REVIEW_FIELDS} for row in selected]
    for row in region_rows:
        row.update(
            {
                "region": "",
                "region_confidence": "",
                "region_reviewer_id": "",
                "region_reviewed_at": "",
                "review_status": "needs_roi_review",
                "notes": "",
            }
        )
    _write_csv(output_dir / "cell_regions_for_review.csv", region_rows, REGION_REVIEW_FIELDS)
    split_rows = [
        {
            "cell_id": row["cell_id"],
            "dataset_key": dataset_key,
            "expression_cluster": row["expression_cluster"],
            "proposed_spatial_block": row["proposed_spatial_block"],
            "provisional_split": row["provisional_split"],
            "split_unit": "proposed_spatial_block",
            "split_status": "provisional_until_reviewed_roi_or_specimen_split",
            "sampling_weight": row["sampling_weight"],
        }
        for row in selected
    ]
    _write_csv(output_dir / "benchmark_split_manifest.csv", split_rows, SPLIT_FIELDS)
    cluster_summary = [
        {
            "expression_cluster": cluster,
            "pool_cells": pool_cluster_counts[cluster],
            "selected_cells": selected_cluster_counts[cluster],
            "top_markers": ";".join(cluster_markers.get(cluster, [])),
        }
        for cluster in sorted(pool_cluster_counts, key=_sort_cluster)
    ]
    _write_csv(
        output_dir / "cluster_marker_summary.csv",
        cluster_summary,
        ["expression_cluster", "pool_cells", "selected_cells", "top_markers"],
    )

    selected_records = []
    record_by_id = {record.cell_id or str(index): record for index, record in enumerate(dataset.records)}
    for row in selected:
        record = record_by_id[row["cell_id"]]
        selected_records.append(
            SpotRecord(
                sample_id=record.sample_id,
                x=record.x,
                y=record.y,
                cell_type="UNREVIEWED expression cluster %s" % row["expression_cluster"],
                genes=dict(record.genes),
                region="PROXY %s" % row["proposed_spatial_block"],
                cell_id=record.cell_id,
                raw_genes=dict(record.raw_genes),
            )
        )
    review_dataset = SpatialDataset(
        sample_id=dataset.sample_id,
        records=selected_records,
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
    VisualizationLayer().render_distribution_svg(review_dataset, str(output_dir), review_dataset.cell_types)
    XeniumExplorerLiteViewer().render(
        review_dataset,
        str(output_dir),
        dataset_path=dataset_path,
        filename="expert_review_viewer.html",
        include_morphology=True,
        include_boundaries=True,
    )

    candidate_coverage = sum(1 for row in selected if row.get("candidate_label"))
    split_counts = Counter(row["provisional_split"] for row in selected)
    summary = {
        "dataset_key": dataset_key,
        "dataset_path": dataset_path,
        "sample_id": dataset.sample_id,
        "pool_cells": len(dataset.records),
        "total_dataset_cells": dataset.metadata.get("n_obs_total"),
        "cohort_cells": len(selected),
        "pool_features": len(dataset.genes),
        "expression_clusters": dict(pool_cluster_counts),
        "selected_clusters": dict(selected_cluster_counts),
        "cluster_count": len(pool_cluster_counts),
        "split_counts": dict(split_counts),
        "spatial_block_count": len(set(row["proposed_spatial_block"] for row in selected)),
        "candidate_path": candidate_path if candidate_path and Path(candidate_path).exists() else None,
        "candidate_evidence_coverage": round(candidate_coverage / float(len(selected) or 1), 4),
        "high_priority_selected": sum(1 for row in selected if int(row["selection_priority"]) >= 4),
        "qc_tail_selected": sum(1 for row in selected if row["qc_stratum"] != "typical"),
        "clustering": {
            key: clustering.metrics.get(key)
            for key in (
                "engine",
                "method",
                "resolution",
                "n_neighbors",
                "silhouette",
                "modularity",
                "analyzed_cell_count",
                "excluded_zero_feature_cell_count",
            )
        },
        "marker_engine": markers.metrics.get("engine"),
        "selection_algorithm": (
            "Square-root cluster allocation, round-robin spatial-block coverage within cluster, then priority ordering "
            "for reference disagreement, out-of-reference risk, low confidence, and weak labels. QC tails are retained "
            "but capped so at least 60% of the cohort represents typical-QC cells unless critical review flags prevent it."
        ),
        "cohort_id_sha256": _cohort_hash(row["cell_id"] for row in selected),
        "review_files": {
            "labels": str(output_dir / "expert_cell_labels_for_review.csv"),
            "regions": str(output_dir / "cell_regions_for_review.csv"),
            "splits": str(output_dir / "benchmark_split_manifest.csv"),
            "cluster_markers": str(output_dir / "cluster_marker_summary.csv"),
            "viewer": str(output_dir / "expert_review_viewer.html"),
            "cluster_map": str(output_dir / "spatial_distribution.svg"),
        },
        "status": "awaiting_expert_review",
    }
    _write_json(output_dir / "cohort_selection_summary.json", summary)
    _write_dataset_instructions(output_dir / "EXPERT_REVIEW_INSTRUCTIONS.md", summary)
    return summary, selected


def _build_evidence_rows(
    dataset: SpatialDataset,
    assignments: Mapping[str, str],
    cluster_markers: Mapping[str, Sequence[str]],
    candidate_rows: Mapping[str, Mapping[str, str]],
    spatial_blocks: Mapping[str, str],
    split_by_block: Mapping[str, str],
) -> List[Dict[str, Any]]:
    expression_features = set(expression_feature_names(dataset))
    transcript_values = [float(record.genes.get("TRANSCRIPT_COUNTS", 0.0) or 0.0) for record in dataset.records]
    area_values = [float(record.genes.get("CELL_AREA", 0.0) or 0.0) for record in dataset.records]
    transcript_low, transcript_high = _quantile(transcript_values, 0.1), _quantile(transcript_values, 0.9)
    area_low, area_high = _quantile(area_values, 0.1), _quantile(area_values, 0.9)
    rows: List[Dict[str, Any]] = []
    for index, record in enumerate(dataset.records):
        cell_id = record.cell_id or str(index)
        cluster = str(assignments.get(cell_id, "QC_EXCLUDED")) or "QC_EXCLUDED"
        transcript_count = float(record.genes.get("TRANSCRIPT_COUNTS", 0.0) or 0.0)
        cell_area = float(record.genes.get("CELL_AREA", 0.0) or 0.0)
        detected = sum(1 for feature in expression_features if float(record.genes.get(feature, 0.0) or 0.0) > 0)
        qc_stratum = _qc_stratum(
            detected,
            transcript_count,
            cell_area,
            transcript_low,
            transcript_high,
            area_low,
            area_high,
        )
        candidate = dict(candidate_rows.get(cell_id, {}))
        reasons: List[str] = []
        priority = 0
        if str(candidate.get("review_priority", "")).lower() == "high":
            priority += 6
            reasons.append("reference_high_priority")
        if _as_bool(candidate.get("marker_disagreement")):
            priority += 5
            reasons.append("marker_disagreement")
        if _as_bool(candidate.get("lineage_absent_from_reference")):
            priority += 5
            reasons.append("lineage_absent_from_reference")
        if _as_bool(candidate.get("distant_from_reference")):
            priority += 3
            reasons.append("distant_from_reference")
        confidence = _as_float(candidate.get("confidence"))
        if confidence is not None and confidence < 0.6:
            priority += 3
            reasons.append("low_reference_confidence")
        if qc_stratum != "typical":
            reasons.append(qc_stratum)
        if "unannotated" in (record.cell_type or "").lower():
            priority += 1
            reasons.append("weak_label_unannotated")
        block = spatial_blocks[cell_id]
        rows.append(
            {
                "cell_id": cell_id,
                "x": round(float(record.x), 4),
                "y": round(float(record.y), 4),
                "expression_cluster": cluster,
                "proposed_spatial_block": block,
                "provisional_split": split_by_block[block],
                "sampling_weight": "",
                "current_weak_label": record.cell_type or "",
                "candidate_label": candidate.get("candidate_label", ""),
                "candidate_confidence": candidate.get("confidence", ""),
                "reference_review_priority": candidate.get("review_priority", ""),
                "marker_disagreement": candidate.get("marker_disagreement", ""),
                "lineage_absent_from_reference": candidate.get("lineage_absent_from_reference", ""),
                "distant_from_reference": candidate.get("distant_from_reference", ""),
                "qc_stratum": qc_stratum,
                "raw_transcript_count": round(transcript_count, 4),
                "detected_expression_features": detected,
                "top_features": _top_features(record.genes),
                "marker_evidence": _marker_evidence(record.genes),
                "cluster_markers": ";".join(cluster_markers.get(cluster, [])),
                "selection_priority": priority,
                "selection_reasons": ";".join(reasons) if reasons else "balanced_cluster_spatial_sampling",
                "expert_label": "",
                "cl_id": "",
                "secondary_state": "",
                "confidence": "",
                "reviewer_id": "",
                "reviewed_at": "",
                "review_status": "needs_expert_review",
                "notes": "",
            }
        )
    return rows


def _stratified_select(rows: Sequence[Dict[str, Any]], target_size: int, seed: str) -> List[Dict[str, Any]]:
    if target_size >= len(rows):
        return [dict(row) for row in rows]
    by_cluster: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cluster[str(row["expression_cluster"])].append(dict(row))
    quotas = _sqrt_cluster_quotas({key: len(value) for key, value in by_cluster.items()}, target_size)
    selected: List[Dict[str, Any]] = []
    selected_ids = set()
    for cluster in sorted(by_cluster, key=_sort_cluster):
        buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in by_cluster[cluster]:
            buckets[str(row["proposed_spatial_block"])].append(row)
        for block_rows in buckets.values():
            block_rows.sort(key=lambda row: (-int(row["selection_priority"]), _stable_key(seed, row["cell_id"])))
        block_names = sorted(buckets, key=lambda value: _stable_key(seed, cluster, value))
        chosen = 0
        while chosen < quotas.get(cluster, 0):
            progressed = False
            for block in block_names:
                if chosen >= quotas.get(cluster, 0):
                    break
                if buckets[block]:
                    row = buckets[block].pop(0)
                    selected.append(row)
                    selected_ids.add(row["cell_id"])
                    chosen += 1
                    progressed = True
            if not progressed:
                break
    if len(selected) < target_size:
        remainder = [dict(row) for row in rows if row["cell_id"] not in selected_ids]
        remainder.sort(key=lambda row: (-int(row["selection_priority"]), _stable_key(seed, row["cell_id"])))
        selected.extend(remainder[: target_size - len(selected)])
    return selected[:target_size]


def _rebalance_qc_strata(
    selected: Sequence[Dict[str, Any]],
    all_rows: Sequence[Dict[str, Any]],
    seed: str,
    minimum_typical_fraction: float = 0.6,
    minimum_per_tail: int = 5,
) -> List[Dict[str, Any]]:
    """Keep QC exceptions represented without letting them dominate the benchmark."""
    result = [dict(row) for row in selected]
    selected_ids = {row["cell_id"] for row in result}
    target_typical = int(math.ceil(len(result) * minimum_typical_fraction))

    def replace_with(candidate: Dict[str, Any], donor_index: int) -> None:
        selected_ids.discard(result[donor_index]["cell_id"])
        result[donor_index] = dict(candidate)
        selected_ids.add(candidate["cell_id"])

    typical_candidates = [
        row for row in all_rows if row.get("qc_stratum") == "typical" and row["cell_id"] not in selected_ids
    ]
    typical_candidates.sort(key=lambda row: (-int(row.get("selection_priority", 0)), _stable_key(seed, row["cell_id"])))
    for candidate in typical_candidates:
        if sum(1 for row in result if row.get("qc_stratum") == "typical") >= target_typical:
            break
        donors = [
            (index, row)
            for index, row in enumerate(result)
            if row.get("qc_stratum") != "typical"
            and int(row.get("selection_priority", 0)) < 4
            and row.get("expression_cluster") == candidate.get("expression_cluster")
        ]
        if not donors:
            continue
        donors.sort(key=lambda item: (int(item[1].get("selection_priority", 0)), _stable_key(seed, item[1]["cell_id"])))
        replace_with(candidate, donors[0][0])

    tail_names = sorted({str(row.get("qc_stratum")) for row in all_rows if row.get("qc_stratum") != "typical"})
    for tail_name in tail_names:
        available = [row for row in all_rows if row.get("qc_stratum") == tail_name]
        target_tail = min(minimum_per_tail, len(available))
        current_tail = sum(1 for row in result if row.get("qc_stratum") == tail_name)
        if current_tail >= target_tail:
            continue
        candidates = [row for row in available if row["cell_id"] not in selected_ids]
        candidates.sort(key=lambda row: (-int(row.get("selection_priority", 0)), _stable_key(seed, row["cell_id"])))
        for candidate in candidates:
            if current_tail >= target_tail:
                break
            typical_count = sum(1 for row in result if row.get("qc_stratum") == "typical")
            if typical_count <= target_typical:
                break
            donors = [
                (index, row)
                for index, row in enumerate(result)
                if row.get("qc_stratum") == "typical"
                and int(row.get("selection_priority", 0)) < 4
                and row.get("expression_cluster") == candidate.get("expression_cluster")
            ]
            if not donors:
                continue
            donors.sort(key=lambda item: (int(item[1].get("selection_priority", 0)), _stable_key(seed, item[1]["cell_id"])))
            replace_with(candidate, donors[0][0])
            current_tail += 1
    return result


def _sqrt_cluster_quotas(counts: Mapping[str, int], target_size: int) -> Dict[str, int]:
    clusters = [cluster for cluster, count in counts.items() if count > 0]
    if not clusters:
        return {}
    weights = {cluster: math.sqrt(counts[cluster]) for cluster in clusters}
    total_weight = sum(weights.values()) or 1.0
    quotas = {
        cluster: min(counts[cluster], max(1, int(math.floor(target_size * weights[cluster] / total_weight))))
        for cluster in clusters
    }
    while sum(quotas.values()) < target_size:
        eligible = [cluster for cluster in clusters if quotas[cluster] < counts[cluster]]
        if not eligible:
            break
        eligible.sort(
            key=lambda cluster: (
                -(target_size * weights[cluster] / total_weight - quotas[cluster]),
                _sort_cluster(cluster),
            )
        )
        for cluster in eligible:
            if sum(quotas.values()) >= target_size:
                break
            quotas[cluster] += 1
    while sum(quotas.values()) > target_size:
        eligible = [cluster for cluster in clusters if quotas[cluster] > 1]
        if not eligible:
            break
        eligible.sort(key=lambda cluster: (target_size * weights[cluster] / total_weight - quotas[cluster], _sort_cluster(cluster)))
        quotas[eligible[0]] -= 1
    return quotas


def _spatial_blocks(dataset: SpatialDataset, bins_per_axis: int) -> Dict[str, str]:
    bounds = dataset.bounds()
    span_x = max(bounds["max_x"] - bounds["min_x"], 1.0)
    span_y = max(bounds["max_y"] - bounds["min_y"], 1.0)
    result = {}
    for index, record in enumerate(dataset.records):
        bx = min(bins_per_axis - 1, int(((record.x - bounds["min_x"]) / span_x) * bins_per_axis))
        by = min(bins_per_axis - 1, int(((record.y - bounds["min_y"]) / span_y) * bins_per_axis))
        result[record.cell_id or str(index)] = "block_x%d_y%d" % (bx + 1, by + 1)
    return result


def _assign_spatial_block_splits(blocks: Iterable[str], seed: str) -> Dict[str, str]:
    unique = sorted(set(blocks), key=lambda block: _stable_key(seed, block))
    if not unique:
        return {}
    n_test = max(1, int(round(len(unique) * 0.15)))
    n_validation = max(1, int(round(len(unique) * 0.15)))
    if n_test + n_validation >= len(unique):
        n_test = 1
        n_validation = 1 if len(unique) >= 3 else 0
    n_train = len(unique) - n_validation - n_test
    labels = ["train"] * n_train + ["validation"] * n_validation + ["test"] * n_test
    return dict(zip(unique, labels))


def _validate_dataset_tables(
    labels: Sequence[Dict[str, str]],
    regions: Sequence[Dict[str, str]],
    splits: Sequence[Dict[str, str]],
    minimum_review_coverage: float,
) -> Dict[str, Any]:
    label_ids = [row.get("cell_id", "") for row in labels]
    region_ids = [row.get("cell_id", "") for row in regions]
    split_ids = [row.get("cell_id", "") for row in splits]
    id_sets_match = set(label_ids) == set(region_ids) == set(split_ids)
    duplicate_label_ids = len(label_ids) - len(set(label_ids))
    duplicate_region_ids = len(region_ids) - len(set(region_ids))
    duplicate_split_ids = len(split_ids) - len(set(split_ids))
    blank_id_tables = [
        name
        for name, values in (("label", label_ids), ("region", region_ids), ("split", split_ids))
        if any(not value.strip() for value in values)
    ]
    reviewed_labels = [row for row in labels if row.get("expert_label", "").strip()]
    reviewed_regions = [row for row in regions if row.get("region", "").strip()]
    reviewed_label_ids = {row.get("cell_id", "") for row in reviewed_labels}
    reviewed_region_ids = {row.get("cell_id", "") for row in reviewed_regions}
    jointly_reviewed_ids = reviewed_label_ids & reviewed_region_ids
    label_reviewer_coverage = sum(1 for row in reviewed_labels if row.get("reviewer_id", "").strip())
    region_reviewer_coverage = sum(1 for row in reviewed_regions if row.get("region_reviewer_id", "").strip())
    total = len(labels) or 1
    label_coverage = len(reviewed_labels) / float(total)
    region_coverage = len(reviewed_regions) / float(total)
    jointly_reviewed_coverage = len(jointly_reviewed_ids) / float(total)
    block_splits: Dict[str, set] = defaultdict(set)
    split_by_id: Dict[str, str] = {}
    for row in splits:
        block_splits[row.get("proposed_spatial_block", "")].add(row.get("provisional_split", ""))
        split_by_id[row.get("cell_id", "")] = row.get("provisional_split", "")
    leaking_blocks = sorted(block for block, values in block_splits.items() if len(values) > 1)
    split_names = {row.get("provisional_split", "") for row in splits}
    jointly_reviewed_splits = {split_by_id.get(cell_id, "") for cell_id in jointly_reviewed_ids}
    blockers = []
    if not id_sets_match:
        blockers.append("Cell IDs differ across label, region, and split tables.")
    if duplicate_label_ids:
        blockers.append("Label table contains %d duplicate cell IDs." % duplicate_label_ids)
    if duplicate_region_ids:
        blockers.append("Region table contains %d duplicate cell IDs." % duplicate_region_ids)
    if duplicate_split_ids:
        blockers.append("Split table contains %d duplicate cell IDs." % duplicate_split_ids)
    if blank_id_tables:
        blockers.append("Blank cell IDs occur in: %s table(s)." % ", ".join(blank_id_tables))
    if leaking_blocks:
        blockers.append("Spatial blocks cross splits: %s." % ", ".join(leaking_blocks))
    if not {"train", "validation", "test"}.issubset(split_names):
        blockers.append("Train, validation, and test must all be represented.")
    if label_coverage < minimum_review_coverage:
        blockers.append("Expert-label coverage %.1f%% is below %.1f%%." % (100 * label_coverage, 100 * minimum_review_coverage))
    if region_coverage < minimum_review_coverage:
        blockers.append("Reviewed-region coverage %.1f%% is below %.1f%%." % (100 * region_coverage, 100 * minimum_review_coverage))
    if jointly_reviewed_coverage < minimum_review_coverage:
        blockers.append(
            "Joint label-and-region coverage %.1f%% is below %.1f%%."
            % (100 * jointly_reviewed_coverage, 100 * minimum_review_coverage)
        )
    if jointly_reviewed_ids and not {"train", "validation", "test"}.issubset(jointly_reviewed_splits):
        blockers.append("Jointly reviewed cells must represent train, validation, and test splits.")
    if reviewed_labels and label_reviewer_coverage < len(reviewed_labels):
        blockers.append("Every reviewed expert label requires reviewer_id.")
    if reviewed_regions and region_reviewer_coverage < len(reviewed_regions):
        blockers.append("Every reviewed region requires region_reviewer_id.")
    return {
        "status": "ready_for_frozen_benchmark" if not blockers else "awaiting_expert_review",
        "record_count": len(labels),
        "id_sets_match": id_sets_match,
        "duplicate_label_ids": duplicate_label_ids,
        "duplicate_region_ids": duplicate_region_ids,
        "duplicate_split_ids": duplicate_split_ids,
        "blank_id_table_count": len(blank_id_tables),
        "label_coverage": round(label_coverage, 4),
        "region_coverage": round(region_coverage, 4),
        "joint_label_region_coverage": round(jointly_reviewed_coverage, 4),
        "jointly_reviewed_record_count": len(jointly_reviewed_ids),
        "label_reviewer_coverage": round(label_reviewer_coverage / float(len(reviewed_labels) or 1), 4),
        "region_reviewer_coverage": round(region_reviewer_coverage / float(len(reviewed_regions) or 1), 4),
        "split_counts": dict(Counter(row.get("provisional_split", "") for row in splits)),
        "spatial_block_leakage_count": len(leaking_blocks),
        "blockers": blockers,
    }


def _write_reviewed_truth_outputs(
    output_dir: Path,
    labels: Sequence[Dict[str, str]],
    regions: Sequence[Dict[str, str]],
    splits: Sequence[Dict[str, str]],
) -> None:
    region_by_id = {row["cell_id"]: row for row in regions}
    split_by_id = {row["cell_id"]: row for row in splits}
    truth_rows = []
    for label in labels:
        region = region_by_id[label["cell_id"]]
        if not label.get("expert_label", "").strip() or not region.get("region", "").strip():
            continue
        split = split_by_id[label["cell_id"]]
        truth_rows.append(
            {
                "cell_id": label["cell_id"],
                "expert_label": label.get("expert_label", ""),
                "cl_id": label.get("cl_id", ""),
                "secondary_state": label.get("secondary_state", ""),
                "region": region.get("region", ""),
                "label_confidence": label.get("confidence", ""),
                "region_confidence": region.get("region_confidence", ""),
                "reviewer_id": label.get("reviewer_id", ""),
                "region_reviewer_id": region.get("region_reviewer_id", ""),
                "split": split.get("provisional_split", ""),
                "split_unit": split.get("split_unit", ""),
                "expression_cluster": label.get("expression_cluster", ""),
                "proposed_spatial_block": label.get("proposed_spatial_block", ""),
            }
        )
    fields = list(truth_rows[0]) if truth_rows else []
    _write_csv(output_dir / "reviewed_benchmark_truth.csv", truth_rows, fields)
    split_dir = output_dir / "frozen_splits"
    split_dir.mkdir(parents=True, exist_ok=True)
    for split_name in ("train", "validation", "test"):
        _write_csv(split_dir / (split_name + ".csv"), [row for row in truth_rows if row["split"] == split_name], fields)


def _load_candidates(path: Optional[str]) -> Dict[str, Dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
    candidates: Dict[str, Dict[str, str]] = {}
    for source_row in _read_csv(Path(path)):
        cell_id = source_row.get("cell_id", "")
        if not cell_id:
            continue
        row = dict(source_row)
        # Older review packets called machine-generated evidence
        # ``suggested_label``. Normalize it into the benchmark's candidate-only
        # field; never populate the expert ground-truth column automatically.
        row["candidate_label"] = (
            row.get("candidate_label")
            or row.get("suggested_label")
            or row.get("predicted_label")
            or ""
        )
        row["confidence"] = row.get("confidence") or row.get("candidate_confidence") or ""
        candidates[cell_id] = row
    return candidates


def _qc_stratum(
    detected: int,
    transcripts: float,
    area: float,
    transcript_low: float,
    transcript_high: float,
    area_low: float,
    area_high: float,
) -> str:
    if detected == 0:
        return "zero_expression"
    if transcripts <= transcript_low:
        return "low_transcript_count"
    if transcripts >= transcript_high:
        return "high_transcript_count"
    if area <= area_low:
        return "small_cell_area"
    if area >= area_high:
        return "large_cell_area"
    return "typical"


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = int(round((len(ordered) - 1) * fraction))
    return float(ordered[index])


def _top_features(features: Mapping[str, float], limit: int = 8) -> str:
    pairs = []
    for name, value in features.items():
        if name in NON_BIOLOGICAL_FEATURES:
            continue
        numeric = _as_float(value)
        if numeric is not None and numeric > 0:
            pairs.append((numeric, name))
    pairs.sort(reverse=True)
    return ";".join("%s=%.3g" % (name, value) for value, name in pairs[:limit])


def _marker_evidence(features: Mapping[str, float]) -> str:
    values = []
    for marker in MARKER_EVIDENCE_FEATURES:
        numeric = _as_float(features.get(marker))
        if numeric is not None and numeric > 0:
            values.append("%s=%.3g" % (marker, numeric))
    return ";".join(values)


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stable_key(*parts: str) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def _cohort_hash(cell_ids: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(cell_ids)).encode("utf-8")).hexdigest()


def _sort_cluster(value: str) -> Tuple[int, Any]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_dataset_instructions(path: Path, summary: Mapping[str, Any]) -> None:
    lines = [
        "# Expert Review Instructions: %s" % summary["dataset_key"],
        "",
        "This cohort contains `%d` cells selected from an analysis pool of `%d`." % (summary["cohort_cells"], summary["pool_cells"]),
        "",
        "## Cell Labels",
        "",
        "Complete `expert_cell_labels_for_review.csv`. Use `candidate_label`, clusters, markers, and QC only as evidence. Fill `expert_label`, `cl_id`, `secondary_state`, `confidence`, `reviewer_id`, `reviewed_at`, and `review_status`. Use an explicit `unknown` label when evidence is insufficient.",
        "",
        "## Regions",
        "",
        "Complete `cell_regions_for_review.csv` while viewing morphology in `expert_review_viewer.html`. `proposed_spatial_block` is only a sampling/split proxy; replace it with a biological/pathology region such as cortical layer, white matter, tumor core, infiltrative margin, necrotic/hypoxic area, or vascular niche when supported.",
        "",
        "## Split Rule",
        "",
        "Do not move individual neighboring cells between splits. The current split keeps spatial blocks intact. Replace the proxy split only with a stronger specimen- or reviewed-ROI-level split.",
        "",
        "## Completion Gate",
        "",
        "At least 90% of cohort cells need both a reviewed label and a reviewed region on the same cell, every reviewed row needs reviewer provenance, and jointly reviewed cells must remain represented in train, validation, and test. Re-run `scripts/prepare_brain_expert_benchmark.py --validate-existing <packet>` after review.",
        "",
        "Do not rename these drafts to the Xenium folder's `expert_cell_labels.csv` or `cell_regions.csv`; they cover a benchmark cohort, not the full validated-pilot population.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_packet_readme(path: Path, payload: Mapping[str, Any]) -> None:
    lines = [
        "# Healthy Brain and Glioblastoma Expert Benchmark Packet",
        "",
        "Status: `awaiting_expert_review`",
        "",
        "This packet freezes machine-selected review cohorts before experts enter labels. It contains no fabricated expert truth.",
        "",
        "## Cohorts",
        "",
    ]
    for key, summary in payload["datasets"].items():
        lines.extend(
            [
                "- `%s`: %d cells from a %d-cell pool; %d expression clusters; candidate evidence coverage %.1f%%."
                % (
                    key,
                    summary["cohort_cells"],
                    summary["pool_cells"],
                    summary["cluster_count"],
                    100 * summary["candidate_evidence_coverage"],
                )
            ]
        )
    lines.extend(
        [
            "",
            "## Workflow",
            "",
            "1. Open each dataset's `expert_review_viewer.html` and `spatial_distribution.svg`.",
            "2. Complete `expert_cell_labels_for_review.csv` and `cell_regions_for_review.csv` without overwriting machine-evidence columns.",
            "3. Preserve `benchmark_split_manifest.csv`; it was frozen before review.",
            "4. Validate with `.venv/bin/python scripts/prepare_brain_expert_benchmark.py --validate-existing %s`." % path.parent,
            "5. At least 90% of cells must have both fields completed with reviewer IDs, and jointly reviewed cells must represent all three splits.",
            "6. When all gates pass, the validator writes only jointly reviewed rows to `reviewed_benchmark_truth.csv` and frozen train/validation/test CSVs.",
            "",
            "## Scientific Boundary",
            "",
            "Spatial blocks are leakage-control proxies, not anatomical ROIs. One healthy section and one glioblastoma section cannot establish condition-level biological generalization. Add independent donors/sections before treating the test set as external validation.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
