import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from spatialmind.datasets import discover_dataset_candidates, inspect_dataset
from spatialmind.pilot import run_pilot


@dataclass
class LocalGapStatus:
    name: str
    status: str
    evidence: List[str]
    conduct_next: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_local_promotion_report(
    data_root: str,
    output_root: str,
    max_records: int = 800,
    readiness_only: bool = False,
) -> Dict[str, Any]:
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    xenium_dirs = _find_xenium_dirs(Path(data_root))
    inspections = []
    for path in discover_dataset_candidates(data_root):
        inspections.append(inspect_dataset(path).to_dict())

    xenium_reports = []
    for dataset_path in xenium_dirs:
        slug = _slug(Path(dataset_path))
        review_dir = output_dir / "review_packets" / slug
        pilot = run_pilot(dataset_path, review_dir, max_records=max_records, readiness_only=readiness_only)
        intake = pilot["label_intake"]
        xenium_reports.append(
            {
                "dataset_path": dataset_path,
                "slug": slug,
                "intake": intake,
                "pilot_status": pilot["status"],
                "pilot_report_html": pilot["report_html"],
                "pilot_report_md": pilot["report_md"],
                "review_figures": pilot.get("review_figures", []),
                "expert_label_template": pilot["expert_label_template"],
                "region_label_template": pilot["region_label_template"],
                "run_record_path": pilot.get("run_record_path", ""),
                "pilot_validation": str(review_dir / "pilot_validation.json"),
                "readiness_only": readiness_only,
            }
        )

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_root": data_root,
        "output_root": str(output_dir),
        "readiness_only": readiness_only,
        "dataset_count": len(inspections),
        "xenium_dataset_count": len(xenium_reports),
        "validated_ready_xenium_count": sum(1 for item in xenium_reports if item["intake"]["ready_for_validated_pilot"]),
        "dataset_inventory": inspections,
        "xenium_review_packets": xenium_reports,
        "gap_status": [item.to_dict() for item in _gap_statuses(xenium_reports, inspections)],
        "next_actions": _next_actions(xenium_reports),
    }
    _write_json(output_dir / "local_promotion_report.json", summary)
    _write_markdown(output_dir / "local_promotion_report.md", summary)
    return summary


def _gap_statuses(xenium_reports: List[Dict[str, Any]], inspections: List[Dict[str, Any]]) -> List[LocalGapStatus]:
    any_validated = any(item["intake"]["ready_for_validated_pilot"] for item in xenium_reports)
    any_xenium = bool(xenium_reports)
    has_demo = any(item["path"].endswith("demo_spatial.csv") for item in inspections)
    has_h5ad = any(item["data_type"] == "h5ad_anndata" for item in inspections)
    has_scrna_like = any(item["modality"] in {"scrna", "spatial_table", "tidy_csv"} for item in inspections)
    statuses = [
        LocalGapStatus(
            name="LLM API planner",
            status="not_configured_locally",
            evidence=["Deterministic planner and typed tool plan are present; no hosted LLM API key/model is configured in this workflow."],
            conduct_next=[
                "Add provider credentials through environment variables only.",
                "Route LLM output through existing ToolCallSpec validation before execution.",
                "Keep deterministic planner as offline fallback.",
            ],
        ),
        LocalGapStatus(
            name="Xenium raw data ingestion",
            status="fulfilled_locally" if any_xenium else "missing",
            evidence=["%d Xenium output folders discovered under data/." % len(xenium_reports)],
            conduct_next=["Keep these as local pilot fixtures; add more tissues only after the breast/brain/lymph workflows are validated."],
        ),
        LocalGapStatus(
            name="Expert cell labels",
            status="fulfilled_locally" if any_validated else "blocked_missing_human_review",
            evidence=[
                "%d/%d Xenium datasets pass expert-label intake."
                % (sum(1 for item in xenium_reports if item["intake"]["label_status"] == "expert_labels_applied"), len(xenium_reports))
            ],
            conduct_next=[
                "Open each generated expert_label_template.csv.",
                "Have a domain expert fill cell_id, expert_label, confidence, and notes.",
                "Save the completed file into the source Xenium folder as expert_cell_labels.csv.",
            ],
        ),
        LocalGapStatus(
            name="User tissue regions",
            status="fulfilled_locally" if any_validated else "blocked_missing_human_review",
            evidence=[
                "%d/%d Xenium datasets pass user-region intake."
                % (sum(1 for item in xenium_reports if item["intake"]["region_status"] == "user_regions_applied"), len(xenium_reports))
            ],
            conduct_next=[
                "Open each generated region_label_template.csv.",
                "Define at least two reviewed ROIs or tissue regions.",
                "Save the completed file into the source Xenium folder as cell_regions.csv.",
            ],
        ),
        LocalGapStatus(
            name="Review visualization",
            status="fulfilled_locally" if all(item["review_figures"] for item in xenium_reports) else "partial",
            evidence=["Review packets include current-label maps, composition charts, static SVGs, and interactive HTML views."],
            conduct_next=["Use these review figures to guide label and region annotation; do not treat them as validated findings."],
        ),
        LocalGapStatus(
            name="Benchmark and evaluation data",
            status="partial_software_qa_only",
            evidence=["Demo/eval cases are present; local Xenium datasets lack expert ground truth."],
            conduct_next=[
                "After labels are completed, freeze one tissue as a held-out benchmark.",
                "Track label F1/ARI, region-composition error, neighborhood reproducibility, and unsupported-claim refusal rate.",
            ],
        ),
        LocalGapStatus(
            name="scRNA/scATAC references",
            status="partial" if has_h5ad or has_scrna_like or has_demo else "missing",
            evidence=[
                "Local data contains %sH5AD files and %s demo/table references."
                % ("some " if has_h5ad else "no ", "some" if has_scrna_like or has_demo else "no")
            ],
            conduct_next=[
                "Use local references only for software QA until curated cell-type labels are available.",
                "Add tissue-matched scRNA references for breast, lymph node, healthy brain, and glioblastoma when available.",
            ],
        ),
        LocalGapStatus(
            name="Production orchestration",
            status="fulfilled_local_cli",
            evidence=["This promotion workflow runs dataset discovery, intake validation, pilot gating, review packet generation, and reporting."],
            conduct_next=[
                "Use this CLI as the local orchestrator.",
                "Promote to API/background jobs when users need concurrent runs.",
            ],
        ),
        LocalGapStatus(
            name="Durable storage and replay",
            status="partial_local_hashes",
            evidence=["Each pilot packet writes run records with input/report/template/figure hashes."],
            conduct_next=[
                "Add a replay CLI that verifies stored hashes before rerunning.",
                "Move run metadata into SQLite/PostgreSQL when multiple users begin using the agent.",
            ],
        ),
        LocalGapStatus(
            name="Governance and privacy",
            status="partial_local_only",
            evidence=["Workflow runs locally and reports missing label provenance; source dataset licenses/consent are not yet encoded."],
            conduct_next=[
                "Add a dataset manifest with license, source, consent class, PHI risk, and allowed use.",
                "Keep raw biomedical data out of LLM prompts by passing summaries and artifact IDs only.",
            ],
        ),
    ]
    return statuses


def _next_actions(xenium_reports: List[Dict[str, Any]]) -> List[str]:
    actions = []
    for item in xenium_reports:
        intake = item["intake"]
        if intake["ready_for_validated_pilot"]:
            actions.append("Run validated pilot on `%s`." % item["dataset_path"])
            continue
        if item.get("readiness_only"):
            actions.append(
                "Run the full promotion workflow for `%s` to generate review templates and figures."
                % item["dataset_path"]
            )
            actions.append(
                "Provide reviewed `expert_cell_labels.csv` and `cell_regions.csv` in `%s`."
                % item["dataset_path"]
            )
            continue
        actions.append(
            "Complete `%s` and place it as `expert_cell_labels.csv` in `%s`."
            % (item["expert_label_template"], item["dataset_path"])
        )
        actions.append(
            "Complete `%s` and place it as `cell_regions.csv` in `%s`."
            % (item["region_label_template"], item["dataset_path"])
        )
    return actions


def _write_markdown(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# SpatialMind Local Promotion Report",
        "",
        "Created: `%s`" % summary["created_at"],
        "",
        "- Data root: `%s`" % summary["data_root"],
        "- Dataset candidates: `%d`" % summary["dataset_count"],
        "- Xenium datasets: `%d`" % summary["xenium_dataset_count"],
        "- Validated-ready Xenium datasets: `%d`" % summary["validated_ready_xenium_count"],
        "- Readiness-only mode: `%s`" % summary.get("readiness_only", False),
        "",
        "## Gap Status",
        "",
        "| Gap | Status | Evidence | How To Conduct / Get It |",
        "| --- | --- | --- | --- |",
    ]
    for item in summary["gap_status"]:
        lines.append(
            "| %s | `%s` | %s | %s |"
            % (
                item["name"],
                item["status"],
                "<br>".join(item["evidence"]),
                "<br>".join(item["conduct_next"]),
            )
        )
    lines.extend(
        [
            "",
            "## Xenium Review Packets",
            "",
            "| Dataset | Intake | Pilot | Artifact | Figures | Label Template | Region Template |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in summary["xenium_review_packets"]:
        lines.append(
            "| `%s` | `%s` | `%s` | `%s` | %d | `%s` | `%s` |"
            % (
                item["dataset_path"],
                item["intake"]["status"],
                item["pilot_status"],
                item["pilot_report_md"] or item.get("pilot_validation", ""),
                len(item["review_figures"]),
                item["expert_label_template"],
                item["region_label_template"],
            )
        )
    lines.extend(["", "## Next Actions", ""])
    lines.extend("- %s" % action for action in summary["next_actions"])
    lines.append("")
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


def _find_xenium_dirs(root: Path) -> List[str]:
    candidates = []
    for path in root.rglob("*"):
        if path.is_dir() and (path / "experiment.xenium").exists() and ((path / "cells.csv.gz").exists() or (path / "cells.csv").exists()):
            candidates.append(str(path))
    return sorted(candidates)


def _slug(path: Path) -> str:
    return path.name.lower().replace(" ", "_").replace("/", "_")
