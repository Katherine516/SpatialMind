import csv
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from spatialmind.ingestion import (
    apply_best_available_labels,
    apply_best_available_regions,
    load_scrna,
    load_xenium,
    validate_xenium_label_intake,
)
from spatialmind.methods.replication import assess_condition_replication
from spatialmind.ingestion.labels import MARKER_EVIDENCE_FEATURES, NON_BIOLOGICAL_FEATURES, load_xenium_analysis_clusters
from spatialmind.schemas import SpatialDataset
from spatialmind.tools.exceptions import MissingPreconditionError
from spatialmind.tools.implementations import annotation, marker_detection, neighborhood_enrichment, reference_label_transfer, region_summary


DEFAULT_GLIOBLASTOMA_DATASET = (
    "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs"
)
DEFAULT_HEALTHY_BRAIN_DATASET = "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs"
DEFAULT_GLIOBLASTOMA_PILOT_OUTPUT = "outputs/xenium_brain_glioblastoma_pilot"
DEFAULT_HEALTHY_BRAIN_PILOT_OUTPUT = "outputs/xenium_brain_healthy_pilot"


def prepare_glioblastoma_review_packet(
    dataset_path: str = DEFAULT_GLIOBLASTOMA_DATASET,
    output_dir: str = "outputs/glioblastoma_expert_review_packet",
    max_records: int = 2500,
    pilot_output_dir: str = DEFAULT_GLIOBLASTOMA_PILOT_OUTPUT,
) -> Dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dataset = load_xenium(dataset_path, max_records=max_records)
    clusters = load_xenium_analysis_clusters(dataset_path)

    label_draft = out / "expert_cell_labels_draft_for_review.csv"
    region_draft = out / "cell_regions_draft_for_review.csv"
    _write_label_review_draft(dataset, clusters, label_draft, max_records=max_records)
    _write_region_review_draft(dataset, clusters, region_draft, max_records=max_records)

    copied_assets = _copy_review_assets(Path(pilot_output_dir), out)
    summary = {
        "created_at": _now(),
        "status": "awaiting_expert_review",
        "dataset_path": dataset_path,
        "records_loaded": len(dataset.records),
        "features_loaded": len(dataset.genes),
        "label_draft": str(label_draft),
        "region_draft": str(region_draft),
        "cell_type_counts_from_loader": dict(Counter(record.cell_type for record in dataset.records)),
        "graph_cluster_count": len(set(clusters.values())),
        "review_assets": copied_assets,
        "required_completed_files": [
            "expert_cell_labels.csv",
            "cell_regions.csv",
        ],
        "important_boundary": (
            "Draft files contain current loader labels and spatial bins for review support only. "
            "They are not expert labels or user ROI labels until reviewed and saved under the required filenames."
        ),
    }
    _write_json(out / "review_packet_summary.json", summary)
    _write_packet_readme(out / "README.md", summary)
    return summary


def build_glioblastoma_benchmark(
    dataset_path: str = DEFAULT_GLIOBLASTOMA_DATASET,
    output_dir: str = "outputs/glioblastoma_benchmark",
    max_records: int = 2500,
    min_label_coverage: float = 0.7,
    min_region_coverage: float = 0.7,
) -> Dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    intake = validate_xenium_label_intake(
        dataset_path,
        max_records=max_records,
        min_label_coverage=min_label_coverage,
        min_region_coverage=min_region_coverage,
    )
    payload: Dict[str, Any] = {
        "created_at": _now(),
        "dataset_path": dataset_path,
        "status": "ready" if intake.ready_for_validated_pilot else "blocked_missing_reviewed_labels",
        "intake": intake.to_dict(),
        "benchmark": {},
    }
    if intake.ready_for_validated_pilot:
        dataset = _load_validated_dataset(dataset_path, max_records=max_records)
        payload["benchmark"] = _benchmark_from_validated_dataset(dataset)
        payload["validated_tool_results"] = _run_validated_tools(dataset)
    else:
        payload["required_next_inputs"] = intake.required_next_inputs
        payload["blockers"] = intake.blockers

    _write_json(out / "benchmark_report.json", payload)
    _write_benchmark_markdown(out / "benchmark_report.md", payload)
    return payload


def build_reference_assist_report(
    target_path: str = DEFAULT_GLIOBLASTOMA_DATASET,
    output_dir: str = "outputs/glioblastoma_reference_assist",
    reference_path: Optional[str] = None,
    max_records: int = 2500,
    min_shared_features: int = 20,
) -> Dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = load_xenium(target_path, max_records=max_records)
    payload: Dict[str, Any] = {
        "created_at": _now(),
        "target_path": target_path,
        "reference_path": reference_path,
        "status": "blocked_missing_curated_reference",
        "required_reference": {
            "format": "h5ad, csv, or Xenium-derived reference table with validated labels",
            "tissue": "human brain or glioblastoma-relevant brain tumor microenvironment",
            "minimum_fields": ["cell_id or observation_id", "cell_type", "features"],
            "preferred_metadata": ["source", "license", "consent/PHI status", "disease_state", "region"],
        },
    }
    if reference_path:
        reference, reference_ready, reference_status, reference_blockers, reference_format = _load_reference_dataset(
            reference_path,
            max_records=max_records,
        )
        payload["reference_format"] = reference_format
        if reference is None:
            payload["reference_status"] = reference_status
            payload["reference_ready_for_label_transfer"] = False
            payload["blockers"] = list(reference_blockers)
        else:
            shared = sorted({gene.upper() for gene in target.genes} & {gene.upper() for gene in reference.genes})
            payload.update(
                {
                    "reference_status": reference_status,
                    "reference_ready_for_label_transfer": reference_ready,
                    "reference_label_classes": len(reference.cell_types),
                    "shared_feature_count": len(shared),
                    "shared_features_preview": shared[:50],
                }
            )
            if reference_ready and len(shared) >= min_shared_features:
                try:
                    result = reference_label_transfer(
                        target,
                        {
                            "reference_dataset": reference,
                            "reference_features": reference.genes,
                            "min_shared_features": min_shared_features,
                        },
                    )
                except MissingPreconditionError as exc:
                    # A refused reference is a valid outcome, not a crash: shared
                    # features can clear the bar while the reference still has no
                    # class for populations present in the section.
                    payload["status"] = "blocked_unusable_reference"
                    payload.setdefault("blockers", []).append(str(exc))
                else:
                    payload["status"] = "reference_assist_ready"
                    payload["reference_assist_result"] = result.__dict__
            else:
                payload["blockers"] = list(reference_blockers)
                if len(shared) < min_shared_features:
                    payload.setdefault("blockers", []).append(
                        "Only %d shared features; at least %d are required." % (len(shared), min_shared_features)
                    )
    _write_json(out / "reference_assist_report.json", payload)
    _write_reference_markdown(out / "reference_assist_report.md", payload)
    return payload


def build_brain_comparison_report(
    healthy_path: str = DEFAULT_HEALTHY_BRAIN_DATASET,
    glioblastoma_path: str = DEFAULT_GLIOBLASTOMA_DATASET,
    output_dir: str = "outputs/brain_comparison",
    max_records: int = 2500,
) -> Dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    healthy = validate_xenium_label_intake(healthy_path, max_records=max_records)
    glioblastoma = validate_xenium_label_intake(glioblastoma_path, max_records=max_records)
    # One section per condition cannot support a condition-level claim: cells
    # within a section are not independent biological replicates. Labels alone
    # must not unlock healthy-versus-disease inference.
    replication = assess_condition_replication(
        {
            "healthy": [{"section_id": healthy_path, "cell_count": getattr(healthy, "loaded_cells", 0)}],
            "glioblastoma": [{"section_id": glioblastoma_path, "cell_count": getattr(glioblastoma, "loaded_cells", 0)}],
        }
    )
    labels_ready = healthy.ready_for_validated_pilot and glioblastoma.ready_for_validated_pilot
    if not labels_ready:
        status = "blocked_missing_validated_inputs"
    elif not replication["supports_condition_inference"]:
        status = "blocked_insufficient_biological_replication"
    else:
        status = "ready"
    payload: Dict[str, Any] = {
        "created_at": _now(),
        "status": status,
        "replication": replication,
        "healthy": healthy.to_dict(),
        "glioblastoma": glioblastoma.to_dict(),
        "comparison": {},
    }
    if not replication["supports_condition_inference"]:
        payload["blockers"] = list(replication["blockers"])
        payload["required_next_inputs"] = list(replication["required_next_inputs"])
    if labels_ready and replication["supports_condition_inference"]:
        healthy_dataset = _load_validated_dataset(healthy_path, max_records=max_records)
        glioblastoma_dataset = _load_validated_dataset(glioblastoma_path, max_records=max_records)
        payload["comparison"] = _compare_validated_brain_datasets(healthy_dataset, glioblastoma_dataset)
    elif labels_ready:
        # Labels exist but the design is n=1 per condition. Describe each section
        # separately; never subtract one condition from the other.
        healthy_dataset = _load_validated_dataset(healthy_path, max_records=max_records)
        glioblastoma_dataset = _load_validated_dataset(glioblastoma_path, max_records=max_records)
        payload["per_section_summary"] = {
            "healthy": dict(Counter(record.cell_type for record in healthy_dataset.records)),
            "glioblastoma": dict(Counter(record.cell_type for record in glioblastoma_dataset.records)),
            "note": replication["allowed_interpretation"],
        }
    _write_json(out / "brain_comparison_report.json", payload)
    _write_comparison_markdown(out / "brain_comparison_report.md", payload)
    return payload


def _load_reference_dataset(
    reference_path: str,
    max_records: int,
    min_label_classes: int = 2,
) -> Tuple[Optional[SpatialDataset], bool, str, List[str], str]:
    """Load a label-transfer reference from a Xenium folder, .h5ad, or tabular file.

    Public brain/glioblastoma references are distributed as AnnData, so restricting
    this to Xenium output folders would block every curated reference. Returns
    ``(dataset, ready, status, blockers, format)``.
    """
    suffix = Path(reference_path).suffix.lower()
    if suffix in {".h5ad", ".csv", ".tsv", ".txt"}:
        reference_format = "anndata" if suffix == ".h5ad" else "table"
        try:
            reference = load_scrna(reference_path)
        except Exception as exc:
            return (
                None,
                False,
                "blocked_unreadable_reference",
                ["Reference %s could not be loaded: %s" % (reference_path, exc)],
                reference_format,
            )
        labels = [label for label in reference.cell_types if label and label.lower() not in {"unannotated cell", "unknown"}]
        if len(labels) < min_label_classes:
            return (
                reference,
                False,
                "blocked_missing_reference_labels",
                [
                    "Reference has %d usable cell-type classes; at least %d are required."
                    % (len(labels), min_label_classes)
                ],
                reference_format,
            )
        return reference, True, "reference_labels_available", [], reference_format

    reference = load_xenium(reference_path, max_records=max_records)
    intake = validate_xenium_label_intake(reference_path, max_records=max_records)
    return reference, intake.ready_for_validated_pilot, intake.status, list(intake.blockers), "xenium_directory"


def _write_label_review_draft(
    dataset: SpatialDataset,
    clusters: Dict[str, str],
    output_path: Path,
    max_records: int,
) -> None:
    fieldnames = [
        "cell_id",
        "x",
        "y",
        "current_label",
        "graph_cluster",
        "top_features",
        "marker_evidence",
        "suggested_label",
        "expert_label",
        "confidence",
        "notes",
        "review_status",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in dataset.records[:max_records]:
            current = record.cell_type or ""
            suggested = "" if current.lower().startswith("unannotated") else current
            writer.writerow(
                {
                    "cell_id": record.cell_id or "",
                    "x": "%.4f" % record.x,
                    "y": "%.4f" % record.y,
                    "current_label": current,
                    "graph_cluster": clusters.get(record.cell_id or "", ""),
                    "top_features": _top_feature_summary(record.genes),
                    "marker_evidence": _marker_evidence(record.genes),
                    "suggested_label": suggested,
                    "expert_label": "",
                    "confidence": "",
                    "notes": "",
                    "review_status": "needs_expert_review",
                }
            )


def _write_region_review_draft(
    dataset: SpatialDataset,
    clusters: Dict[str, str],
    output_path: Path,
    max_records: int,
) -> None:
    bins = _spatial_bins(dataset)
    fieldnames = [
        "cell_id",
        "x",
        "y",
        "current_label",
        "current_region",
        "graph_cluster",
        "draft_spatial_zone",
        "region",
        "region_confidence",
        "notes",
        "review_status",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in dataset.records[:max_records]:
            writer.writerow(
                {
                    "cell_id": record.cell_id or "",
                    "x": "%.4f" % record.x,
                    "y": "%.4f" % record.y,
                    "current_label": record.cell_type,
                    "current_region": record.region or "",
                    "graph_cluster": clusters.get(record.cell_id or "", ""),
                    "draft_spatial_zone": bins.get(record.cell_id or "", ""),
                    "region": "",
                    "region_confidence": "",
                    "notes": "",
                    "review_status": "needs_roi_review",
                }
            )


def _load_validated_dataset(dataset_path: str, max_records: int) -> SpatialDataset:
    dataset = load_xenium(dataset_path, max_records=max_records)
    apply_best_available_labels(dataset, dataset_path, fallback=None)
    apply_best_available_regions(dataset, dataset_path)
    return dataset


def _run_validated_tools(dataset: SpatialDataset) -> Dict[str, Any]:
    cell_types = dataset.cell_types
    group1 = cell_types[0] if cell_types else ""
    group2 = cell_types[1] if len(cell_types) > 1 else group1
    results = {
        "annotation": annotation(dataset, {"method": "expert_labels"}),
        "region_summary": region_summary(dataset, {"top_n_features": 8}),
        "neighborhood_enrichment": neighborhood_enrichment(dataset, {"radius": 18.0}),
    }
    if group1 and group2 and group1 != group2:
        results["marker_detection"] = marker_detection(
            dataset,
            {"group_key": "cell_type", "group1": group1, "group2": group2},
        )
    return {name: result.__dict__ for name, result in results.items()}


def _benchmark_from_validated_dataset(dataset: SpatialDataset) -> Dict[str, Any]:
    label_counts = Counter(record.cell_type for record in dataset.records)
    region_counts = Counter(record.region or "unassigned" for record in dataset.records)
    by_region: Dict[str, Counter] = defaultdict(Counter)
    for record in dataset.records:
        by_region[record.region or "unassigned"][record.cell_type] += 1
    return {
        "record_count": len(dataset.records),
        "label_counts": dict(label_counts),
        "region_counts": dict(region_counts),
        "region_label_matrix": {region: dict(counts) for region, counts in by_region.items()},
        "recommended_split": _stable_split([record.cell_id or str(index) for index, record in enumerate(dataset.records)]),
    }


def _compare_validated_brain_datasets(healthy: SpatialDataset, glioblastoma: SpatialDataset) -> Dict[str, Any]:
    healthy_counts = Counter(record.cell_type for record in healthy.records)
    glioblastoma_counts = Counter(record.cell_type for record in glioblastoma.records)
    all_labels = sorted(set(healthy_counts) | set(glioblastoma_counts))
    healthy_total = sum(healthy_counts.values()) or 1
    glioblastoma_total = sum(glioblastoma_counts.values()) or 1
    label_fraction_delta = {
        label: round((glioblastoma_counts[label] / glioblastoma_total) - (healthy_counts[label] / healthy_total), 4)
        for label in all_labels
    }
    return {
        "healthy_record_count": len(healthy.records),
        "glioblastoma_record_count": len(glioblastoma.records),
        "healthy_label_counts": dict(healthy_counts),
        "glioblastoma_label_counts": dict(glioblastoma_counts),
        "glioblastoma_minus_healthy_label_fraction": label_fraction_delta,
        "healthy_regions": dict(Counter(record.region or "unassigned" for record in healthy.records)),
        "glioblastoma_regions": dict(Counter(record.region or "unassigned" for record in glioblastoma.records)),
    }


def _stable_split(cell_ids: Iterable[str]) -> Dict[str, List[str]]:
    splits = {"train": [], "validation": [], "test": []}
    for cell_id in sorted(cell_ids):
        bucket = sum(ord(char) for char in cell_id) % 10
        if bucket < 7:
            splits["train"].append(cell_id)
        elif bucket < 9:
            splits["validation"].append(cell_id)
        else:
            splits["test"].append(cell_id)
    return {name: values[:100] for name, values in splits.items()}


def _spatial_bins(dataset: SpatialDataset, bins_per_axis: int = 4) -> Dict[str, str]:
    bounds = dataset.bounds()
    span_x = max(bounds["max_x"] - bounds["min_x"], 1.0)
    span_y = max(bounds["max_y"] - bounds["min_y"], 1.0)
    labels = {}
    for record in dataset.records:
        bx = min(bins_per_axis - 1, int(((record.x - bounds["min_x"]) / span_x) * bins_per_axis))
        by = min(bins_per_axis - 1, int(((record.y - bounds["min_y"]) / span_y) * bins_per_axis))
        labels[record.cell_id or ""] = "spatial_bin_x%d_y%d" % (bx + 1, by + 1)
    return labels


def _copy_review_assets(pilot_output: Path, output_dir: Path) -> Dict[str, str]:
    assets = {}
    for name in [
        "review_current_label_map.png",
        "review_cell_type_composition.svg",
        "validated_xenium_pilot_report.html",
        "validated_xenium_pilot_report.md",
    ]:
        source = pilot_output / name
        if source.exists():
            target = output_dir / name
            shutil.copyfile(source, target)
            assets[name] = str(target)
    return assets


def _write_packet_readme(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Glioblastoma Expert-Review Packet",
        "",
        "Status: `awaiting_expert_review`",
        "",
        "This packet is designed for a neuropathology/spatial-omics reviewer. It contains draft files prefilled with loader labels, 10x graph clusters, marker evidence, and spatial coordinates. These drafts are review aids only.",
        "",
        "## Files To Complete",
        "",
        "1. Open `expert_cell_labels_draft_for_review.csv`, fill `expert_label`, `confidence`, and `notes`, then save the reviewed result as `expert_cell_labels.csv` in the Xenium dataset folder.",
        "2. Open `cell_regions_draft_for_review.csv`, fill `region`, `region_confidence`, and `notes`, then save the reviewed result as `cell_regions.csv` in the Xenium dataset folder.",
        "",
        "Required dataset folder:",
        "",
        "```text",
        str(summary["dataset_path"]),
        "```",
        "",
        "## Review Guidance",
        "",
        "- Use `current_label` and `suggested_label` as starting points, not truth.",
        "- Use `graph_cluster`, `top_features`, and `marker_evidence` to prioritize ambiguous groups.",
        "- Use the copied review map and report to define biologically meaningful glioblastoma regions such as tumor core, infiltrative margin, reactive glia-rich region, vascular/perivascular region, necrotic/hypoxic region, or normal-appearing brain if present.",
        "- Leave uncertain cells blank or mark them as `Uncertain` with lower confidence rather than forcing a label.",
        "",
        "## Downstream Gate",
        "",
        "Validated annotation, marker detection, region summary, neighborhood enrichment, benchmark construction, reference assist, and healthy-vs-glioblastoma comparison remain blocked until the reviewed files are available.",
    ]
    _write_text(path, "\n".join(lines) + "\n")


def _write_benchmark_markdown(path: Path, payload: Dict[str, Any]) -> None:
    lines = ["# Glioblastoma Benchmark Report", "", "Status: `%s`" % payload["status"], ""]
    if payload["status"] != "ready":
        lines.extend(["## Blockers", ""])
        lines.extend("- %s" % item for item in payload.get("blockers", []))
        lines.extend(["", "## Required Next Inputs", ""])
        lines.extend("- %s" % item for item in payload.get("required_next_inputs", []))
    else:
        benchmark = payload["benchmark"]
        lines.extend(
            [
                "## Benchmark Summary",
                "",
                "- Records: `%d`" % benchmark["record_count"],
                "- Label classes: `%d`" % len(benchmark["label_counts"]),
                "- Region classes: `%d`" % len(benchmark["region_counts"]),
            ]
        )
    _write_text(path, "\n".join(lines) + "\n")


def _write_reference_markdown(path: Path, payload: Dict[str, Any]) -> None:
    lines = ["# Tissue-Matched Reference-Assist Report", "", "Status: `%s`" % payload["status"], ""]
    if payload.get("reference_path"):
        lines.append("Reference: `%s`" % payload["reference_path"])
        lines.append("Shared features: `%s`" % payload.get("shared_feature_count", "not evaluated"))
        lines.append("")
    else:
        lines.extend(
            [
                "No curated tissue-matched reference was provided. A healthy brain Xenium sample can be used for panel/QC context, but not as a label-transfer reference until it has reviewed labels and license/consent metadata.",
                "",
                "Required reference properties:",
                "",
            ]
        )
        for key, value in payload["required_reference"].items():
            lines.append("- `%s`: %s" % (key, value))
    if payload.get("blockers"):
        lines.extend(["", "## Blockers", ""])
        lines.extend("- %s" % item for item in payload["blockers"])
    _write_text(path, "\n".join(lines) + "\n")


def _write_comparison_markdown(path: Path, payload: Dict[str, Any]) -> None:
    lines = ["# Healthy Brain vs Glioblastoma Comparison Report", "", "Status: `%s`" % payload["status"], ""]
    if payload["status"] != "ready":
        lines.extend(["Comparison is intentionally blocked until both datasets have validated expert labels and reviewed regions.", ""])
        for name in ("healthy", "glioblastoma"):
            intake = payload[name]
            lines.extend(["## %s Intake" % name.capitalize(), ""])
            lines.extend("- %s" % item for item in intake.get("blockers", []))
            lines.append("")
    else:
        lines.extend(["## Validated Comparison", "", json.dumps(payload["comparison"], indent=2, sort_keys=True)])
    _write_text(path, "\n".join(lines) + "\n")


def _top_feature_summary(features: Dict[str, float], limit: int = 8) -> str:
    pairs = []
    for name, value in features.items():
        if name in NON_BIOLOGICAL_FEATURES:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            pairs.append((numeric, name))
    pairs.sort(reverse=True)
    return ";".join("%s=%.3g" % (name, value) for value, name in pairs[:limit])


def _marker_evidence(features: Dict[str, float]) -> str:
    values = []
    for marker in MARKER_EVIDENCE_FEATURES:
        value = features.get(marker)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            values.append("%s=%.3g" % (marker, numeric))
    return ";".join(values)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
