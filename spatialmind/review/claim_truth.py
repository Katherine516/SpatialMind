import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from spatialmind.methods.reliability import score_claim_reliability
from spatialmind.pilot import run_pilot
from spatialmind.review.glioblastoma import DEFAULT_GLIOBLASTOMA_DATASET, DEFAULT_HEALTHY_BRAIN_DATASET


CLAIM_TRUTH_FIELDS = [
    "record_id",
    "dataset",
    "record_type",
    "calibration_scope",
    "claim_ref",
    "claim_type",
    "claim_status",
    "claim_text",
    "current_reliability",
    "S_statistical",
    "A_annotation",
    "P_panel",
    "R_spatial_robustness",
    "suggested_truth_label",
    "reviewed_truth_label",
    "use_for_calibration",
    "reviewer_id",
    "reviewed_at",
    "truth_basis",
    "source_citation",
    "split",
    "notes",
]

DEFAULT_BRAIN_DATASETS = [
    ("healthy_brain", DEFAULT_HEALTHY_BRAIN_DATASET),
    ("glioblastoma", DEFAULT_GLIOBLASTOMA_DATASET),
]


def prepare_claim_reliability_review_packet(
    output_dir: str = "outputs/claim_reliability_review_packet",
    datasets: Optional[Iterable[Tuple[str, str]]] = None,
    max_records: int = 800,
) -> Dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dataset_items = list(datasets or DEFAULT_BRAIN_DATASETS)
    rows: List[Dict[str, Any]] = []
    pilot_outputs = []
    for dataset_name, dataset_path in dataset_items:
        pilot_dir = out / "pilot_outputs" / dataset_name
        pilot = run_pilot(dataset_path=dataset_path, output_dir=pilot_dir, max_records=max_records)
        pilot_outputs.append(
            {
                "dataset": dataset_name,
                "dataset_path": dataset_path,
                "status": pilot.get("status"),
                "report_html": pilot.get("report_html"),
                "pilot_validation": str(pilot_dir / "pilot_validation.json"),
            }
        )
        rows.extend(_pilot_claim_truth_rows(dataset_name, pilot))
        rows.extend(_null_control_rows(dataset_name, pilot))
        rows.extend(_candidate_positive_rows(dataset_name))

    truth_draft = out / "spatial_claim_truth_draft_for_review.csv"
    _write_csv(truth_draft, rows)
    summary = {
        "created_at": _now(),
        "status": "awaiting_expert_claim_truth_review",
        "claim_truth_draft": str(truth_draft),
        "row_count": len(rows),
        "pilot_outputs": pilot_outputs,
        "required_reviewer_action": [
            "Complete reviewed_truth_label with 1 for correct/supported claims and 0 for false/unsupported claims.",
            "Set use_for_calibration to yes only for claims with enough evidence to judge claim correctness.",
            "Add truth_basis, source_citation, reviewer_id, and notes for each calibrated claim.",
            "Keep candidate positive spatial claims out of calibration until expert labels, ROI regions, and tool evidence exist.",
        ],
        "important_boundary": (
            "This packet does not create expert biology. It creates an auditable table that a domain expert can review. "
            "Calibration remains blocked until reviewed positive and negative spatial claims are returned."
        ),
    }
    _write_json(out / "claim_truth_review_summary.json", summary)
    _write_readme(out / "README.md", summary)
    return summary


def validate_claim_truth_table(path: str, min_reviewed_records: int = 4) -> Dict[str, Any]:
    rows = load_claim_truth_records(path)
    reviewed = [row for row in rows if row.get("reviewed_truth_label") in {0, 1}]
    usable = [row for row in reviewed if str(row.get("use_for_calibration", "")).strip().lower() in {"yes", "true", "1"}]
    positives = sum(1 for row in usable if row.get("reviewed_truth_label") == 1)
    negatives = sum(1 for row in usable if row.get("reviewed_truth_label") == 0)
    blockers = []
    if len(usable) < min_reviewed_records:
        blockers.append("Need at least %d reviewed calibration records; found %d." % (min_reviewed_records, len(usable)))
    if positives == 0:
        blockers.append("Need at least one reviewed supported/correct claim.")
    if negatives == 0:
        blockers.append("Need at least one reviewed unsupported/false claim.")
    return {
        "path": path,
        "status": "ready_for_calibration" if not blockers else "blocked",
        "row_count": len(rows),
        "reviewed_count": len(reviewed),
        "usable_for_calibration_count": len(usable),
        "positive_count": positives,
        "negative_count": negatives,
        "blockers": blockers,
        "records": usable,
    }


def load_claim_truth_records(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            record = dict(row)
            record["reviewed_truth_label"] = _truth_label(record.get("reviewed_truth_label"))
            record["truth_label"] = record["reviewed_truth_label"]
            record["truth_label_source"] = "expert_claim_truth_review" if record["reviewed_truth_label"] in {0, 1} else ""
            record["reliability"] = _safe_float(record.get("current_reliability"), 0.0)
            record["components"] = {
                "S_statistical": _safe_float(record.get("S_statistical"), 0.0),
                "A_annotation": _safe_float(record.get("A_annotation"), 0.0),
                "P_panel": _safe_float(record.get("P_panel"), 0.0),
                "R_spatial_robustness": _safe_float(record.get("R_spatial_robustness"), 0.0),
            }
            rows.append(record)
    return rows


def write_claim_truth_validation_report(path: str, output_dir: str = "outputs/claim_reliability_review_packet") -> Dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = validate_claim_truth_table(path)
    _write_json(out / "claim_truth_validation_report.json", report)
    lines = [
        "# Claim Truth Validation Report",
        "",
        "Status: `%s`" % report["status"],
        "",
        "- Rows: `%d`" % report["row_count"],
        "- Reviewed rows: `%d`" % report["reviewed_count"],
        "- Usable calibration rows: `%d`" % report["usable_for_calibration_count"],
        "- Positive claims: `%d`" % report["positive_count"],
        "- Negative claims: `%d`" % report["negative_count"],
        "",
    ]
    if report["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend("- %s" % item for item in report["blockers"])
        lines.append("")
    _write_text(out / "claim_truth_validation_report.md", "\n".join(lines))
    return report


def _pilot_claim_truth_rows(dataset_name: str, pilot: Dict[str, Any]) -> List[Dict[str, Any]]:
    reliability_by_ref = {item.get("claim_ref"): item for item in pilot.get("claim_reliability", [])}
    rows = []
    for index, claim in enumerate(pilot.get("claim_ledger", []), start=1):
        claim_ref = claim.get("claim_ref") or "claim_%03d" % index
        reliability = reliability_by_ref.get(claim_ref) or {}
        status = str(claim.get("status") or "")
        if status == "supported_non_biological_readiness":
            scope = "pipeline_readiness_control"
            suggested = "1"
            use_for_calibration = "no"
        elif status in {"refused", "dropped"}:
            scope = "blocked_biology_control"
            suggested = "0"
            use_for_calibration = "no"
        else:
            scope = "biological_claim_candidate"
            suggested = ""
            use_for_calibration = "review"
        rows.append(
            _base_row(
                record_id="%s_%s" % (dataset_name, claim_ref),
                dataset=dataset_name,
                record_type="pilot_claim",
                calibration_scope=scope,
                claim_ref=claim_ref,
                claim_type=str(claim.get("claim_type") or ""),
                claim_status=status,
                claim_text=str(claim.get("claim_text") or ""),
                reliability=reliability,
                suggested_truth_label=suggested,
                use_for_calibration=use_for_calibration,
            )
        )
    return rows


def _null_control_rows(dataset_name: str, pilot: Dict[str, Any]) -> List[Dict[str, Any]]:
    controls = [
        ("permuted_coordinates_null", "Spatial co-localization remains supported after permuting coordinates."),
        ("shuffled_labels_null", "Spatial co-localization remains supported after shuffling cell labels."),
    ]
    rows = []
    for name, text in controls:
        claim = {
            "claim_ref": "%s_%s" % (dataset_name, name),
            "claim_text": text,
            "claim_type": "spatial_colocalization",
            "status": "refused",
            "evidence_refs": [],
        }
        scored = score_claim_reliability(claim, pilot, [], claim_index=0)
        rows.append(
            _base_row(
                record_id=claim["claim_ref"],
                dataset=dataset_name,
                record_type="null_control",
                calibration_scope="null_control",
                claim_ref=claim["claim_ref"],
                claim_type="spatial_colocalization",
                claim_status="refused",
                claim_text=text,
                reliability={
                    "reliability": scored.reliability,
                    "S_statistical": scored.S_statistical,
                    "A_annotation": scored.A_annotation,
                    "P_panel": scored.P_panel,
                    "R_spatial_robustness": scored.R_spatial_robustness,
                },
                suggested_truth_label="0",
                use_for_calibration="review",
            )
        )
    return rows


def _candidate_positive_rows(dataset_name: str) -> List[Dict[str, Any]]:
    if dataset_name != "glioblastoma":
        return []
    candidates = [
        (
            "candidate_positive_001",
            "Neoplastic or glioblastoma-like cells are enriched in reviewed tumor-core regions compared with normal-appearing brain regions.",
        ),
        (
            "candidate_positive_002",
            "Myeloid or microglial cells are enriched near reviewed infiltrative-margin or reactive-glia-rich regions.",
        ),
        (
            "candidate_positive_003",
            "Endothelial or perivascular cells are enriched in reviewed vascular/perivascular regions.",
        ),
    ]
    rows = []
    for suffix, text in candidates:
        rows.append(
            _base_row(
                record_id="%s_%s" % (dataset_name, suffix),
                dataset=dataset_name,
                record_type="candidate_positive_spatial_claim",
                calibration_scope="candidate_positive_spatial_claim",
                claim_ref=suffix,
                claim_type="spatial_region_enrichment",
                claim_status="awaiting_validated_labels_regions",
                claim_text=text,
                reliability={},
                suggested_truth_label="",
                use_for_calibration="no",
                notes=(
                    "Do not use for calibration until expert_cell_labels.csv, cell_regions.csv, "
                    "and validated tool evidence are available."
                ),
            )
        )
    return rows


def _base_row(
    record_id: str,
    dataset: str,
    record_type: str,
    calibration_scope: str,
    claim_ref: str,
    claim_type: str,
    claim_status: str,
    claim_text: str,
    reliability: Dict[str, Any],
    suggested_truth_label: str,
    use_for_calibration: str,
    notes: str = "",
) -> Dict[str, Any]:
    return {
        "record_id": record_id,
        "dataset": dataset,
        "record_type": record_type,
        "calibration_scope": calibration_scope,
        "claim_ref": claim_ref,
        "claim_type": claim_type,
        "claim_status": claim_status,
        "claim_text": claim_text,
        "current_reliability": reliability.get("reliability", ""),
        "S_statistical": reliability.get("S_statistical", ""),
        "A_annotation": reliability.get("A_annotation", ""),
        "P_panel": reliability.get("P_panel", ""),
        "R_spatial_robustness": reliability.get("R_spatial_robustness", ""),
        "suggested_truth_label": suggested_truth_label,
        "reviewed_truth_label": "",
        "use_for_calibration": use_for_calibration,
        "reviewer_id": "",
        "reviewed_at": "",
        "truth_basis": "",
        "source_citation": "",
        "split": _stable_split(record_id),
        "notes": notes,
    }


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CLAIM_TRUTH_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CLAIM_TRUTH_FIELDS})


def _write_readme(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Claim Reliability Review Packet",
        "",
        "Status: `awaiting_expert_claim_truth_review`",
        "",
        "This packet is the next real validation step for SpatialMind v12. It asks a reviewer to mark individual claims, not whole reports.",
        "",
        "## File To Complete",
        "",
        "- `spatial_claim_truth_draft_for_review.csv`",
        "",
        "## How To Review",
        "",
        "- Fill `reviewed_truth_label` with `1` only when the claim is correct and supported by reviewed labels, reviewed regions, tool evidence, and domain knowledge.",
        "- Fill `reviewed_truth_label` with `0` when the claim is false, unsupported, or should be refused.",
        "- Set `use_for_calibration` to `yes` only when the claim has enough evidence to judge correctness.",
        "- Keep pipeline-readiness claims as controls; they are useful for refusal/readiness behavior, not biological calibration.",
        "- Keep candidate positive spatial claims out of calibration until the validated pilot can compute evidence from reviewed labels and regions.",
        "",
        "## Required Before Calibration",
        "",
        "- Reviewed `expert_cell_labels.csv` for the dataset.",
        "- Reviewed `cell_regions.csv` for the dataset.",
        "- At least one supported/correct reviewed claim.",
        "- At least one unsupported/false reviewed claim.",
        "- Preferably separate train, validation, and test splits across datasets.",
        "",
        "## Pilot Outputs",
        "",
    ]
    for item in summary["pilot_outputs"]:
        lines.append("- `%s`: `%s`, report `%s`" % (item["dataset"], item["status"], item["report_html"]))
    lines.extend(["", "Important: %s" % summary["important_boundary"], ""])
    _write_text(path, "\n".join(lines))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content + ("\n" if not content.endswith("\n") else ""), encoding="utf-8")


def _truth_label(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "supported", "correct"}:
        return 1
    if text in {"0", "false", "no", "unsupported", "incorrect"}:
        return 0
    return None


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _stable_split(record_id: str) -> str:
    bucket = sum(ord(char) for char in record_id) % 10
    if bucket < 7:
        return "train"
    if bucket < 9:
        return "validation"
    return "test"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
