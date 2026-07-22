import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.methods.reliability import apply_calibration_model, fit_claim_reliability_calibration, score_claim_reliability
from spatialmind.pilot import run_pilot
from spatialmind.review import validate_claim_truth_table


HUMAN_BRAIN_XENIUM = [
    (
        "healthy_brain",
        "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs/experiment.xenium",
    ),
    (
        "glioblastoma",
        "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs/experiment.xenium",
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Train/evaluate local claim reliability records on human brain Xenium data.")
    parser.add_argument("--out", default="outputs/training/human_brain_claim_reliability")
    parser.add_argument("--max-records", type=int, default=800)
    parser.add_argument("--claim-truth", default="", help="Optional completed spatial_claim_truth CSV with reviewed truth labels.")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, Any]] = []
    pilot_outputs = []
    for slug, dataset_path in HUMAN_BRAIN_XENIUM:
        pilot_dir = out / ("%s_pilot" % slug)
        pilot = run_pilot(dataset_path=dataset_path, output_dir=pilot_dir, max_records=args.max_records)
        pilot_outputs.append(
            {
                "dataset": slug,
                "dataset_path": dataset_path,
                "pilot_status": pilot["status"],
                "report_html": pilot["report_html"],
                "pilot_validation": str(pilot_dir / "pilot_validation.json"),
            }
        )
        records.extend(_records_from_pilot(slug, pilot))
        records.extend(_null_control_records(slug, pilot))

    truth_validation = None
    calibration_model: Dict[str, Any] = {
        "status": "not_fit",
        "reason": (
            "No reviewed claim-truth table was provided. Local controls validate the reliability pipeline, "
            "but they are not enough for biological claim calibration."
        ),
    }
    if args.claim_truth:
        truth_validation = validate_claim_truth_table(args.claim_truth)
        reviewed_records = truth_validation.get("records", [])
        calibration_model = fit_claim_reliability_calibration(reviewed_records)
        records.extend(reviewed_records)
        records = apply_calibration_model(records, calibration_model)

    summary = _summarize(records, pilot_outputs, calibration_model=calibration_model, truth_validation=truth_validation)
    _write_json(out / "claim_reliability_training_records.json", records)
    _write_json(out / "claim_reliability_training_summary.json", summary)
    _write_json(out / "claim_reliability_calibration_model.json", calibration_model)
    (out / "claim_reliability_training_report.md").write_text(_markdown(summary, records), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def _records_from_pilot(dataset_slug: str, pilot: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    reliability_by_ref = {item.get("claim_ref"): item for item in pilot.get("claim_reliability", [])}
    for index, claim in enumerate(pilot.get("claim_ledger", []), start=1):
        claim_ref = claim.get("claim_ref") or "claim_%03d" % index
        reliability = reliability_by_ref.get(claim_ref) or (pilot.get("claim_reliability") or [{}])[index - 1]
        expected = _expected_correctness(claim)
        rows.append(
            {
                "record_id": "%s_%s" % (dataset_slug, claim_ref),
                "dataset": dataset_slug,
                "record_type": "pilot_claim",
                "claim_text": claim.get("claim_text"),
                "claim_status": claim.get("status"),
                "truth_label": expected,
                "truth_label_source": "local_control_rule",
                "reliability": reliability.get("reliability", 0.0),
                "components": {
                    "S_statistical": reliability.get("S_statistical", 0.0),
                    "A_annotation": reliability.get("A_annotation", 0.0),
                    "P_panel": reliability.get("P_panel", 0.0),
                    "R_spatial_robustness": reliability.get("R_spatial_robustness", 0.0),
                },
                "interpretation": reliability.get("interpretation", ""),
                "usable_for": ["reliability_pipeline_regression", "refusal_policy_training"],
                "not_usable_for": ["biological_claim_calibration"] if expected == 0 else ["spatial_biology_calibration"],
            }
        )
    return rows


def _null_control_records(dataset_slug: str, pilot: Dict[str, Any]) -> List[Dict[str, Any]]:
    controls = [
        (
            "permuted_coordinates_null",
            "Null control: spatial co-localization after permuting coordinates should not be trusted.",
        ),
        (
            "shuffled_labels_null",
            "Null control: spatial co-localization after shuffling labels should not be trusted.",
        ),
    ]
    rows = []
    for control_name, claim_text in controls:
        claim = {
            "claim_ref": "%s_%s" % (dataset_slug, control_name),
            "claim_text": claim_text,
            "claim_type": "spatial_colocalization",
            "status": "refused",
            "evidence_refs": [],
            "allowed_wording": "",
        }
        scored = score_claim_reliability(claim, pilot, [], claim_index=0)
        rows.append(
            {
                "record_id": claim["claim_ref"],
                "dataset": dataset_slug,
                "record_type": "null_control",
                "claim_text": claim_text,
                "claim_status": "refused",
                "truth_label": 0,
                "truth_label_source": control_name,
                "reliability": scored.reliability,
                "components": {
                    "S_statistical": scored.S_statistical,
                    "A_annotation": scored.A_annotation,
                    "P_panel": scored.P_panel,
                    "R_spatial_robustness": scored.R_spatial_robustness,
                },
                "interpretation": scored.interpretation,
                "usable_for": ["null_control_regression", "robustness_failure_training"],
                "not_usable_for": ["positive_spatial_biology_calibration"],
            }
        )
    return rows


def _expected_correctness(claim: Dict[str, Any]) -> int:
    if claim.get("status") == "supported_non_biological_readiness":
        return 1
    return 0


def _summarize(
    records: List[Dict[str, Any]],
    pilot_outputs: List[Dict[str, Any]],
    calibration_model: Optional[Dict[str, Any]] = None,
    truth_validation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    labels = [int(record["truth_label"]) for record in records]
    scores = [float(record["reliability"]) for record in records]
    calibration_model = calibration_model or {"status": "not_fit"}
    if calibration_model.get("status") == "fit":
        calibrated_blocker = ""
    elif truth_validation:
        calibrated_blocker = "; ".join(truth_validation.get("blockers", [])) or calibration_model.get("reason", "")
    else:
        calibrated_blocker = (
            "Local human brain Xenium data lacks expert-reviewed spatial claim truth labels. "
            "This run trains/evaluates the reliability pipeline and null-control behavior, not a publishable calibrated model."
        )
    return {
        "record_count": len(records),
        "positive_controls": sum(labels),
        "negative_controls": len(labels) - sum(labels),
        "mean_reliability": round(sum(scores) / float(len(scores) or 1), 4),
        "auroc_local_controls": _auroc(labels, scores),
        "calibration_curve": _calibration_curve(labels, scores),
        "combiner": "weakest_link",
        "calibrated_model_status": calibration_model.get("status", "not_fit"),
        "calibrated_model_blocker": calibrated_blocker,
        "calibration_model": calibration_model,
        "claim_truth_validation": _summary_truth_validation(truth_validation),
        "pilot_outputs": pilot_outputs,
        "recommended_next_step": (
            "Add reviewed expert_cell_labels.csv/cell_regions.csv plus literature-anchored positive spatial claims; "
            "then fit the calibrated logistic combiner and rerun cross-dataset validation."
        ),
    }


def _summary_truth_validation(truth_validation: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not truth_validation:
        return None
    return {
        "status": truth_validation.get("status"),
        "row_count": truth_validation.get("row_count"),
        "reviewed_count": truth_validation.get("reviewed_count"),
        "usable_for_calibration_count": truth_validation.get("usable_for_calibration_count"),
        "positive_count": truth_validation.get("positive_count"),
        "negative_count": truth_validation.get("negative_count"),
        "blockers": truth_validation.get("blockers", []),
    }


def _calibration_curve(labels: List[int], scores: List[float]) -> List[Dict[str, Any]]:
    bins = [(0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01)]
    rows = []
    for low, high in bins:
        idx = [i for i, score in enumerate(scores) if low <= score < high]
        if not idx:
            rows.append({"bin": "[%.2f, %.2f)" % (low, high), "count": 0, "mean_predicted": None, "observed_correct": None})
            continue
        rows.append(
            {
                "bin": "[%.2f, %.2f)" % (low, high),
                "count": len(idx),
                "mean_predicted": round(sum(scores[i] for i in idx) / len(idx), 4),
                "observed_correct": round(sum(labels[i] for i in idx) / float(len(idx)), 4),
            }
        )
    return rows


def _auroc(labels: List[int], scores: List[float]) -> float:
    positives = [score for label, score in zip(labels, scores) if label == 1]
    negatives = [score for label, score in zip(labels, scores) if label == 0]
    if not positives or not negatives:
        return 0.0
    wins = 0.0
    total = 0
    for pos in positives:
        for neg in negatives:
            total += 1
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return round(wins / float(total or 1), 4)


def _markdown(summary: Dict[str, Any], records: List[Dict[str, Any]]) -> str:
    lines = [
        "# Human Brain Claim Reliability Training Run",
        "",
        "## Summary",
        "",
        "- Records: `%d`" % summary["record_count"],
        "- Positive controls: `%d`" % summary["positive_controls"],
        "- Negative controls: `%d`" % summary["negative_controls"],
        "- AUROC on local controls: `%.4f`" % summary["auroc_local_controls"],
        "- Calibrated model status: `%s`" % summary["calibrated_model_status"],
        "",
        summary["calibrated_model_blocker"],
        "",
        "## Pilot Outputs",
        "",
    ]
    for item in summary["pilot_outputs"]:
        lines.append("- `%s`: `%s`, report `%s`" % (item["dataset"], item["pilot_status"], item["report_html"]))
    if summary.get("claim_truth_validation"):
        validation = summary["claim_truth_validation"]
        lines.extend(
            [
                "",
                "## Reviewed Claim Truth",
                "",
                "- Status: `%s`" % validation["status"],
                "- Rows: `%s`" % validation["row_count"],
                "- Reviewed rows: `%s`" % validation["reviewed_count"],
                "- Usable calibration rows: `%s`" % validation["usable_for_calibration_count"],
                "- Positive claims: `%s`" % validation["positive_count"],
                "- Negative claims: `%s`" % validation["negative_count"],
            ]
        )
        if validation.get("blockers"):
            lines.extend(["", "Blockers:"])
            lines.extend("- %s" % item for item in validation["blockers"])
    lines.extend(["", "## Calibration Model", "", "- Status: `%s`" % summary["calibrated_model_status"]])
    if summary.get("calibrated_model_blocker"):
        lines.append("- Blocker: %s" % summary["calibrated_model_blocker"])
    lines.extend(["", "## Example Records", ""])
    for record in records[:8]:
        lines.extend(
            [
                "### `%s`" % record["record_id"],
                "",
                "- Truth label: `%s` from `%s`" % (record.get("truth_label"), record.get("truth_label_source")),
                "- Reliability: `%.4f`" % float(record.get("reliability") or 0.0),
                "- Components: `%s`" % json.dumps(record.get("components") or {}, sort_keys=True),
                "- Interpretation: %s" % record.get("interpretation", ""),
                "",
            ]
        )
    lines.extend(["## Recommended Next Step", "", summary["recommended_next_step"], ""])
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
