from typing import Any, Dict, List, Optional


FEATURE_ORDER = ["S_statistical", "A_annotation", "P_panel", "R_spatial_robustness"]


def fit_claim_reliability_calibration(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    usable = [_training_row(record) for record in records]
    usable = [row for row in usable if row is not None]
    labels = [row["label"] for row in usable]
    if len(usable) < 4:
        return _not_fit("At least four reviewed claim-truth records are required.", len(usable), labels)
    if len(set(labels)) < 2:
        return _not_fit("Reviewed claim truth must contain both supported and unsupported/false claims.", len(usable), labels)
    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        return _not_fit("scikit-learn is not installed, so logistic calibration cannot be fit.", len(usable), labels)

    features = [[row["features"][name] for name in FEATURE_ORDER] for row in usable]
    model = LogisticRegression(C=10.0, solver="liblinear", random_state=17)
    model.fit(features, labels)
    probabilities = [float(value) for value in model.predict_proba(features)[:, 1]]
    return {
        "status": "fit",
        "method": "logistic_regression",
        "feature_order": list(FEATURE_ORDER),
        "weights": {name: round(float(weight), 6) for name, weight in zip(FEATURE_ORDER, model.coef_[0])},
        "intercept": round(float(model.intercept_[0]), 6),
        "record_count": len(usable),
        "positive_count": int(sum(labels)),
        "negative_count": int(len(labels) - sum(labels)),
        "training_auroc": _auroc(labels, probabilities),
        "training_calibration_curve": _calibration_curve(labels, probabilities),
        "important_caveat": (
            "This model is only as valid as the reviewed claim-truth table. "
            "Keep a held-out dataset split before using the calibrated score as a performance claim."
        ),
    }


def apply_calibration_model(records: List[Dict[str, Any]], model: Dict[str, Any]) -> List[Dict[str, Any]]:
    if model.get("status") != "fit":
        return records
    weights = model.get("weights") or {}
    intercept = float(model.get("intercept", 0.0))
    scored = []
    for record in records:
        row = dict(record)
        components = row.get("components") or {}
        linear = intercept + sum(float(weights.get(name, 0.0)) * _safe_float(components.get(name), 0.0) for name in FEATURE_ORDER)
        row["calibrated_reliability"] = round(1.0 / (1.0 + _exp_neg_guarded(linear)), 4)
        scored.append(row)
    return scored


def _training_row(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    label = _reviewed_label(record)
    if label is None:
        return None
    components = record.get("components") or {}
    if not all(name in components for name in FEATURE_ORDER):
        return None
    return {
        "label": label,
        "features": {name: _safe_float(components.get(name), 0.0) for name in FEATURE_ORDER},
    }


def _reviewed_label(record: Dict[str, Any]) -> Optional[int]:
    value = record.get("reviewed_truth_label")
    if value in (None, ""):
        value = record.get("truth_label")
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"1", "true", "supported", "correct", "yes"}:
            return 1
        if value in {"0", "false", "unsupported", "incorrect", "no"}:
            return 0
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    if numeric in {0, 1}:
        return numeric
    return None


def _not_fit(reason: str, record_count: int, labels: List[int]) -> Dict[str, Any]:
    return {
        "status": "not_fit",
        "reason": reason,
        "record_count": record_count,
        "positive_count": int(sum(labels)),
        "negative_count": int(len(labels) - sum(labels)),
        "feature_order": list(FEATURE_ORDER),
    }


def _calibration_curve(labels: List[int], scores: List[float]) -> List[Dict[str, Any]]:
    bins = [(0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01)]
    rows = []
    for low, high in bins:
        indexes = [i for i, score in enumerate(scores) if low <= score < high]
        if not indexes:
            rows.append({"bin": "[%.2f, %.2f)" % (low, high), "count": 0, "mean_predicted": None, "observed_correct": None})
            continue
        rows.append(
            {
                "bin": "[%.2f, %.2f)" % (low, high),
                "count": len(indexes),
                "mean_predicted": round(sum(scores[i] for i in indexes) / len(indexes), 4),
                "observed_correct": round(sum(labels[i] for i in indexes) / float(len(indexes)), 4),
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


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _exp_neg_guarded(value: float) -> float:
    from math import exp

    return exp(max(min(-value, 60.0), -60.0))
