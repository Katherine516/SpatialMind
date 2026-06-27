import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.ingestion import (
    apply_best_available_labels,
    apply_best_available_regions,
    load_xenium,
    summarize_xenium_expert_readiness,
    validate_cell_by_feature_contract,
    write_expert_label_template,
    write_region_label_template,
)


DATA_ROOT = Path("data")
OUTPUT_ROOT = Path("outputs/xenium_expert_mvp_readiness")
MAX_RECORDS = 1500


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    dataset_paths = _find_xenium_dirs(DATA_ROOT)
    summaries: List[Dict[str, Any]] = []
    for dataset_path in dataset_paths:
        slug = _slug(dataset_path)
        output_dir = OUTPUT_ROOT / slug
        output_dir.mkdir(parents=True, exist_ok=True)
        readiness = summarize_xenium_expert_readiness(str(dataset_path))
        dataset = load_xenium(str(dataset_path), max_records=MAX_RECORDS)
        fallback = "breast_marker_rule" if "breast" in dataset_path.name.lower() else None
        label_report = apply_best_available_labels(dataset, str(dataset_path), fallback=fallback)
        region_report = apply_best_available_regions(dataset, str(dataset_path))
        contract = validate_cell_by_feature_contract(dataset)
        template_path = write_expert_label_template(
            dataset,
            str(output_dir / "expert_label_template.csv"),
            max_rows=MAX_RECORDS,
            dataset_path=str(dataset_path),
        )
        region_template_path = write_region_label_template(
            dataset,
            str(output_dir / "region_label_template.csv"),
            max_rows=MAX_RECORDS,
            dataset_path=str(dataset_path),
        )
        summary = {
            "dataset_path": str(dataset_path),
            "output_dir": str(output_dir),
            "records_loaded": len(dataset.records),
            "features_loaded": len(dataset.genes),
            "cell_types": dataset.cell_types,
            "contract": asdict(contract),
            "readiness": readiness.to_dict(),
            "cluster_methods": readiness.cluster_methods,
            "label_report": label_report.to_dict(),
            "region_report": region_report.to_dict(),
            "expert_label_template": template_path,
            "region_label_template": region_template_path,
            "needs": readiness.needs,
        }
        _write_json(output_dir / "readiness.json", summary)
        summaries.append(summary)
    root_summary = {
        "dataset_count": len(summaries),
        "datasets": summaries,
        "global_needs": _global_needs(summaries),
    }
    _write_json(OUTPUT_ROOT / "summary.json", root_summary)
    _write_markdown_report(OUTPUT_ROOT / "xenium_expert_mvp_readiness.md", root_summary)
    print(json.dumps(root_summary, indent=2))


def _find_xenium_dirs(root: Path) -> List[Path]:
    candidates = []
    for path in root.rglob("*"):
        if path.is_dir() and (path / "experiment.xenium").exists() and ((path / "cells.csv.gz").exists() or (path / "cells.csv").exists()):
            candidates.append(path)
    return sorted(candidates)


def _global_needs(summaries: List[Dict[str, Any]]) -> List[str]:
    needs = []
    for summary in summaries:
        for item in summary.get("needs", []):
            if item not in needs:
                needs.append(item)
    if any(summary["label_report"]["status"] != "expert_labels_applied" for summary in summaries):
        item = "Expert-reviewed label files named `expert_cell_labels.csv` or `cell_labels.csv` with columns `cell_id`, `expert_label`, and optional `confidence`."
        if item not in needs:
            needs.append(item)
    if any(summary["region_report"]["status"] != "user_regions_applied" for summary in summaries):
        item = "User region files named `cell_regions.csv` or `region_labels.csv` with columns `cell_id`, `region`, and optional `region_confidence`."
        if item not in needs:
            needs.append(item)
    return needs


def _write_markdown_report(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Xenium Expert-Label MVP Readiness",
        "",
        "This report inventories local Xenium datasets for the expert-label-ready MVP. 10x clustering outputs are useful review evidence, but they are not biological ground-truth labels.",
        "",
        "## Dataset Summary",
        "",
        "| Dataset | Records Loaded | Features | Label Status | Region Status | Has 10x Clusters | Needs | Label Template | Region Template |",
        "| --- | ---: | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for dataset in summary["datasets"]:
        readiness = dataset["readiness"]
        label = dataset["label_report"]
        region = dataset["region_report"]
        needs = "<br>".join(readiness["needs"]) if readiness["needs"] else "None"
        lines.append(
            "| `%s` | %d | %d | `%s` | `%s` | %s | %s | `%s` | `%s` |"
            % (
                dataset["dataset_path"],
                dataset["records_loaded"],
                dataset["features_loaded"],
                label["status"],
                region["status"],
                "yes" if readiness["has_10x_analysis_clusters"] else "no",
                needs,
                dataset["expert_label_template"],
                dataset["region_label_template"],
            )
        )
    lines.extend(
        [
            "",
            "## What We Still Need",
            "",
        ]
    )
    for item in summary["global_needs"]:
        lines.append("- %s" % item)
    lines.extend(
        [
            "",
            "## Accepted Label File Format",
            "",
            "Place one of these files inside a Xenium output directory: `expert_cell_labels.csv`, `cell_labels.csv`, `cell_annotations.csv`, `annotations.csv`, or `labels.csv`.",
            "",
            "Required columns:",
            "",
            "- `cell_id`: Xenium cell identifier, for example `aaaafije-1`.",
            "- `expert_label`: final biological label.",
            "",
            "Optional columns:",
            "",
            "- `confidence`: numeric confidence score.",
            "- `notes`: reviewer notes or label source.",
            "",
            "## Accepted Region File Format",
            "",
            "Place one of these files inside a Xenium output directory: `cell_regions.csv`, `region_labels.csv`, `cell_region_labels.csv`, `expert_region_labels.csv`, or `regions.csv`.",
            "",
            "Required columns:",
            "",
            "- `cell_id`: Xenium cell identifier.",
            "- `region`: user-defined tissue region or ROI label.",
            "",
            "Optional columns:",
            "",
            "- `region_confidence`: numeric confidence score.",
            "- `notes`: reviewer notes or region source.",
            "",
            "The generated templates also include review evidence columns:",
            "",
            "- `graph_cluster`: 10x graph-based expression cluster from `analysis.tar.gz` when available.",
            "- `top_features`: strongest loaded gene features for that cell.",
            "- `marker_evidence`: selected lineage/tissue marker values detected in the loaded feature vector.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _slug(path: Path) -> str:
    return path.name.lower().replace(" ", "_").replace("/", "_")


if __name__ == "__main__":
    main()
