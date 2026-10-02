"""Reviewed, donor-disjoint reliability calibration with explicit held-out metrics."""

from .claim_truth import validate_claim_truth_table
from spatialmind.methods.reliability.calibration import (
    apply_calibration_model, fit_claim_reliability_calibration,
)


def probability_metrics(records):
    import numpy as np
    from sklearn.metrics import roc_auc_score

    y = np.asarray([row["reviewed_truth_label"] for row in records], dtype=int)
    p = np.asarray([row["calibrated_reliability"] for row in records], dtype=float)
    if not len(y) or not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError("Nonempty finite probabilities in [0, 1] are required.")
    bins, ece = [], 0.0
    for index in range(10):
        low, high = index / 10, (index + 1) / 10
        mask = (p >= low) & ((p < high) if index < 9 else (p <= high))
        if not mask.any():
            continue
        predicted, observed = float(p[mask].mean()), float(y[mask].mean())
        ece += float(mask.mean()) * abs(predicted - observed)
        bins.append({"low": low, "high": high, "count": int(mask.sum()),
                     "mean_predicted": predicted, "observed_correct": observed})
    return {"records": len(y), "brier_score": float(np.mean((p - y) ** 2)), "ece_10_bins": ece,
            "auroc": float(roc_auc_score(y, p)) if len(set(y)) == 2 else None,
            "calibration_curve": bins}


def evaluate_reviewed_calibration(path):
    validation = validate_claim_truth_table(str(path))
    blockers = list(validation["blockers"])
    records = validation["records"]
    groups = {name: [row for row in records if row.get("split") == name]
              for name in ("train", "validation", "test")}
    allowed_scopes = {"biological_claim", "biological_claim_candidate"}
    for row in records:
        if row.get("calibration_scope") not in allowed_scopes:
            blockers.append("Only reviewed biological claims may train this calibrator; controls are separate.")
        if not str(row.get("donor_id", "")).strip() or row.get("split") not in groups:
            blockers.append("Each biological claim requires a donor_id and prespecified train/validation/test split.")
    donors = {name: {row.get("donor_id", "").strip() for row in rows} for name, rows in groups.items()}
    for name, rows in groups.items():
        if not rows or {row["reviewed_truth_label"] for row in rows} != {0, 1}:
            blockers.append(name + " requires reviewed supported and unsupported biological claims.")
    for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
        if donors[left] & donors[right]:
            blockers.append("Donors overlap across " + left + " and " + right)
    if blockers:
        return {"status": "blocked", "blockers": sorted(set(blockers)),
                "review_validation": {key: value for key, value in validation.items() if key != "records"},
                "split_counts": {key: len(rows) for key, rows in groups.items()}, "test_scored": False}
    model = fit_claim_reliability_calibration(groups["train"])
    if model["status"] != "fit":
        return {"status": "blocked", "blockers": [model["reason"]], "test_scored": False}
    scored = {name: apply_calibration_model(rows, model) for name, rows in groups.items()}
    heldout = scored["test"]
    return {"status": "donor_heldout_evaluated_not_production_validated", "model": model,
            "protocol": {"selection": "fixed logistic C=10, seed=17; fit train only; no test tuning",
                         "donors": {key: sorted(values) for key, values in donors.items()}},
            "metrics": {name: probability_metrics(rows) for name, rows in scored.items()},
            "test_per_donor": {donor: probability_metrics([row for row in heldout if row["donor_id"].strip() == donor])
                               for donor in sorted(donors["test"])},
            "test_scored": True, "blockers": [],
            "caveat": "Reviewed correctness is not a diagnosis. Few donors and claims give unstable estimates; "
                      "no population generalization or production promotion follows automatically."}
