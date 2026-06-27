import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.ingestion import validate_xenium_label_intake


DEFAULT_DATASET = "data/Human_Breast_Biomarkers_S1_Top_outs"
DEFAULT_OUTPUT = "outputs/xenium_label_intake"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate expert labels and user regions for a Xenium pilot run.")
    parser.add_argument("--data", default=DEFAULT_DATASET, help="Xenium output directory.")
    parser.add_argument("--out", default=DEFAULT_OUTPUT, help="Output directory for intake reports.")
    parser.add_argument("--max-records", type=int, default=5000)
    parser.add_argument("--min-label-coverage", type=float, default=0.7)
    parser.add_argument("--min-region-coverage", type=float, default=0.7)
    parser.add_argument("--min-biological-labels", type=int, default=2)
    parser.add_argument("--min-user-regions", type=int, default=2)
    parser.add_argument("--allow-single-region", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = validate_xenium_label_intake(
        dataset_path=args.data,
        max_records=args.max_records,
        min_label_coverage=args.min_label_coverage,
        min_region_coverage=args.min_region_coverage,
        min_biological_labels=args.min_biological_labels,
        min_user_regions=args.min_user_regions,
        allow_single_region=args.allow_single_region,
    )
    payload = report.to_dict()
    json_path = output_dir / "label_intake_report.json"
    md_path = output_dir / "label_intake_report.md"
    _write_json(json_path, payload)
    _write_markdown(md_path, payload)
    payload["json_report"] = str(json_path)
    payload["markdown_report"] = str(md_path)
    print(json.dumps(payload, indent=2, sort_keys=True))


def _write_markdown(path: Path, report: Dict[str, Any]) -> None:
    lines = [
        "# Xenium Label Intake Report",
        "",
        "- Dataset: `%s`" % report["dataset_path"],
        "- Status: `%s`" % report["status"],
        "- Ready for validated pilot: `%s`" % report["ready_for_validated_pilot"],
        "- Loaded records: `%d`" % report["loaded_records"],
        "- Loaded features: `%d`" % report["loaded_features"],
        "",
        "## Coverage",
        "",
        "| Input | Status | Coverage | Classes | Source |",
        "| --- | --- | ---: | ---: | --- |",
        "| Expert labels | `%s` | %.4f | %d | `%s` |"
        % (
            report["label_status"],
            report["label_coverage"],
            report["biological_label_count"],
            report["label_table"] or "missing",
        ),
        "| User regions | `%s` | %.4f | %d | `%s` |"
        % (
            report["region_status"],
            report["region_coverage"],
            report["user_region_count"],
            report["region_table"] or "missing",
        ),
        "",
    ]
    if report["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend("- %s" % item for item in report["blockers"])
        lines.append("")
    if report["required_next_inputs"]:
        lines.extend(["## Required Next Inputs", ""])
        lines.extend("- %s" % item for item in report["required_next_inputs"])
        lines.append("")
    if report["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend("- %s" % item for item in report["warnings"])
        lines.append("")
    lines.extend(
        [
            "## Accepted Files",
            "",
            "- Expert labels: `expert_cell_labels.csv` with `cell_id,expert_label,confidence,notes`.",
            "- User regions: `cell_regions.csv` with `cell_id,region,region_confidence,notes`.",
            "- Default thresholds: 70% loaded-cell coverage for both files, at least two biological labels, and at least two user regions.",
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


if __name__ == "__main__":
    main()
