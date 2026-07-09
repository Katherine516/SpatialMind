from collections.abc import Iterable
from dataclasses import asdict
from math import exp
from typing import Any, Dict, List, Optional

from spatialmind.contracts import ClaimReliability, MetricProvenance, ReliabilityComponent
from spatialmind.schemas import ToolResult


CORE_XENIUM_ASSET_KEYS = ("has_cell_table", "has_feature_matrix", "has_morphology", "has_boundaries")
DEFAULT_CELL_MARKERS = {
    "astrocyte": {"AQP4", "GFAP", "SLC1A3", "GJA1", "SOX9"},
    "neural/glial cell": {"AQP4", "GJA1", "MOG", "MOBP", "OLIG2", "SOX9"},
    "microglial cell": {"AIF1", "CX3CR1", "P2RY12", "CD68", "PTPRC"},
    "myeloid cell": {"AIF1", "CD68", "CTSS", "PTPRC", "MS4A6A"},
    "t/nk cell": {"CD3D", "CD3E", "CD4", "CD8A", "NKG7", "PTPRC"},
    "endothelial cell": {"PECAM1", "VWF", "KDR", "FLT1", "CLDN5"},
    "fibroblast/stromal cell": {"COL1A1", "COL1A2", "DCN", "LUM"},
    "neoplastic cell": {"EGFR", "MKI67", "TOP2A", "SOX2", "NES"},
}


def build_claim_reliability_table(
    payload: Dict[str, Any],
    results: List[ToolResult],
    method: str = "weakest_link",
) -> List[Dict[str, Any]]:
    """Attach v12 reliability records to every pilot claim ledger item."""
    rows = []
    for index, claim in enumerate(payload.get("claim_ledger") or []):
        score = score_claim_reliability(claim, payload, results, claim_index=index, method=method)
        rows.append(_jsonable(score))
    return rows


def score_claim_reliability(
    claim: Dict[str, Any],
    payload: Dict[str, Any],
    results: List[ToolResult],
    claim_index: int = 0,
    method: str = "weakest_link",
    calibration_model: Optional[Dict[str, Any]] = None,
) -> ClaimReliability:
    claim_type = str(claim.get("claim_type") or "unknown")
    components = {
        "S_statistical": _statistical_component(claim, results),
        "A_annotation": _annotation_component(claim, payload),
        "P_panel": _panel_component(claim, payload),
        "R_spatial_robustness": _spatial_robustness_component(claim, payload, results),
    }
    scores = {key: component.score for key, component in components.items()}
    if method == "calibrated":
        reliability, status, model = calibrated_score(scores, calibration_model)
    else:
        reliability, status, model = weakest_link_score(scores), "computed", None
    if str(claim.get("status")) in {"refused", "dropped"}:
        status = "blocked"
    interpretation = _interpret_reliability(reliability, claim, components)
    return ClaimReliability(
        claim_ref=str(claim.get("claim_ref") or "claim_%03d" % (claim_index + 1)),
        claim_type=claim_type,
        S_statistical=scores["S_statistical"],
        A_annotation=scores["A_annotation"],
        P_panel=scores["P_panel"],
        R_spatial_robustness=scores["R_spatial_robustness"],
        reliability=round(float(reliability), 4),
        method="calibrated" if method == "calibrated" else "weakest_link",
        status=status,
        components=components,
        provenance=MetricProvenance(
            method="spatialmind_claim_reliability_v0",
            parameters={
                "combiner": method,
                "component_order": ["S_statistical", "A_annotation", "P_panel", "R_spatial_robustness"],
                "calibration_model_status": "provided" if calibration_model else "not_fit",
            },
            data_subset="loaded_cells",
        ),
        interpretation=interpretation,
        calibration_model=model,
    )


def weakest_link_score(scores: Dict[str, float]) -> float:
    if not scores:
        return 0.0
    return round(min(_clip(value) for value in scores.values()), 4)


def calibrated_score(scores: Dict[str, float], calibration_model: Optional[Dict[str, Any]]) -> tuple[float, str, Dict[str, Any]]:
    if not calibration_model:
        baseline = weakest_link_score(scores)
        return baseline, "not_fit", {
            "status": "not_fit",
            "reason": "No ground-truth spatial claim calibration model is available; weakest-link score was used.",
        }
    weights = calibration_model.get("weights") or {}
    intercept = float(calibration_model.get("intercept", 0.0))
    linear = intercept + sum(float(weights.get(key, 0.0)) * _clip(value) for key, value in scores.items())
    return round(1.0 / (1.0 + exp(-linear)), 4), "computed", dict(calibration_model)


def _statistical_component(claim: Dict[str, Any], results: List[ToolResult]) -> ReliabilityComponent:
    claim_type = str(claim.get("claim_type") or "")
    if claim_type in {"visual_pattern", "cell_type_annotation"}:
        return ReliabilityComponent(
            name="S_statistical",
            score=1.0,
            status="not_applicable",
            evidence=["claim_type:%s" % claim_type],
            caveat="This claim does not require a spatial statistical test; other components control reliability.",
        )
    best = 0.0
    evidence: List[str] = []
    for result in results:
        for pair in _top_pairs(result):
            z = _safe_float(pair.get("zscore") or pair.get("neighbor_count"))
            p = _safe_float(pair.get("pval_adj") or pair.get("p_adj") or pair.get("pvalue") or pair.get("pval"))
            component = 0.0
            if z is not None:
                component = max(component, min(1.0, abs(z) / 5.0))
            if p is not None:
                component = max(component, 1.0 - min(1.0, p * 20.0))
            if component > best:
                best = component
                evidence = ["%s:%s" % (result.tool_name, pair.get("pair", "top_pair"))]
    if best <= 0.0:
        return ReliabilityComponent(
            name="S_statistical",
            score=0.0,
            status="blocked",
            evidence=[],
            caveat="No adjusted spatial statistic or effect-size evidence was available for this claim.",
        )
    return ReliabilityComponent(
        name="S_statistical",
        score=round(best, 4),
        status="computed",
        evidence=evidence,
        caveat="Statistical strength is heuristic until calibrated against ground-truth positive/negative controls.",
    )


def _annotation_component(claim: Dict[str, Any], payload: Dict[str, Any]) -> ReliabilityComponent:
    claim_type = str(claim.get("claim_type") or "")
    label_report = payload.get("label_report") or {}
    status = str(label_report.get("status") or "")
    matched = _safe_float(label_report.get("matched_cells")) or 0.0
    total = max(_safe_float(label_report.get("total_records")) or _safe_float(payload.get("records_loaded")) or 1.0, 1.0)
    coverage = _clip(matched / total)
    confidence = _safe_float((label_report.get("confidence_summary") or {}).get("mean"))
    if status == "expert_labels_applied":
        score = coverage * (confidence if confidence is not None else 0.85)
        caveat = "Expert labels were applied; score reflects coverage and reviewer confidence."
        component_status = "computed"
    elif claim_type == "visual_pattern" and "asset_readiness" in (claim.get("evidence_refs") or []):
        score = 0.75
        caveat = "Readiness claim is not a biological annotation claim; annotation quality only partially applies."
        component_status = "not_applicable"
    else:
        score = 0.0
        caveat = "Expert or validated reference-transferred labels are missing."
        component_status = "blocked"
    return ReliabilityComponent(
        name="A_annotation",
        score=round(_clip(score), 4),
        status=component_status,
        evidence=["label_status:%s" % (status or "missing"), "label_coverage:%.4f" % coverage],
        caveat=caveat,
    )


def _panel_component(claim: Dict[str, Any], payload: Dict[str, Any]) -> ReliabilityComponent:
    contract = payload.get("contract") or {}
    panel_name = str(contract.get("panel_name") or payload.get("metadata", {}).get("panel_name") or "")
    n_features = _safe_float(contract.get("n_features") or payload.get("features_loaded")) or 0.0
    claim_text = str(claim.get("claim_text") or "").lower()
    if str(claim.get("status")) in {"refused", "dropped"}:
        score = 0.5 if n_features else 0.0
        status = "computed" if n_features else "blocked"
        caveat = "Panel exists, but this refused claim cannot rely on panel adequacy alone."
    else:
        relevant = _markers_for_claim(claim_text)
        if not relevant:
            score = 0.8 if n_features else 0.0
            caveat = "No specific marker family was parsed from the claim; score reflects general panel availability."
        else:
            measured = {gene.upper() for gene in (payload.get("cell_types") or [])}
            measured.update(_features_from_payload(payload))
            overlap = len({gene.upper() for gene in relevant} & measured)
            score = overlap / float(max(len(relevant), 1))
            caveat = "Panel adequacy reflects marker coverage for parsed claim terms."
        status = "computed" if n_features else "blocked"
    return ReliabilityComponent(
        name="P_panel",
        score=round(_clip(score), 4),
        status=status,
        evidence=["panel:%s" % (panel_name or "unknown"), "n_features:%d" % int(n_features)],
        caveat=caveat + " Xenium targeted panels cannot support claims about unmeasured genes.",
    )


def _spatial_robustness_component(
    claim: Dict[str, Any],
    payload: Dict[str, Any],
    results: List[ToolResult],
) -> ReliabilityComponent:
    claim_type = str(claim.get("claim_type") or "")
    if claim_type in {"visual_pattern", "cell_type_annotation"}:
        return ReliabilityComponent(
            name="R_spatial_robustness",
            score=1.0,
            status="not_applicable",
            evidence=["claim_type:%s" % claim_type],
            caveat="This claim does not depend on neighborhood-radius robustness.",
        )
    sweep = payload.get("spatial_robustness")
    if isinstance(sweep, dict) and sweep.get("status") == "computed":
        score = _clip(_safe_float(sweep.get("score")) or 0.0)
        return ReliabilityComponent(
            name="R_spatial_robustness",
            score=round(score, 4),
            status="computed",
            evidence=[
                "settings:%s" % ",".join(str(value) for value in sweep.get("settings", [])),
                "sign_agreement:%.4f" % (_safe_float(sweep.get("mean_sign_agreement")) or 0.0),
                "topk_jaccard:%.4f" % (_safe_float(sweep.get("mean_topk_jaccard")) or 0.0),
            ],
            caveat="Robustness = sign agreement and top-K overlap of neighborhood enrichment across a graph-size perturbation sweep.",
        )
    top_pair_counts = []
    radii = set()
    engines = set()
    for result in results:
        metrics = result.metrics or {}
        if "radius" in metrics:
            radii.add(str(metrics.get("radius")))
        if "n_neighs" in metrics:
            radii.add("n_neighs:%s" % metrics.get("n_neighs"))
        if "engine" in metrics:
            engines.add(str(metrics.get("engine")))
        top_pair_counts.append(len(_top_pairs(result)))
    if not top_pair_counts:
        return ReliabilityComponent(
            name="R_spatial_robustness",
            score=0.0,
            status="blocked",
            evidence=[],
            caveat="Spatial robustness was not tested because no neighborhood result was available.",
        )
    richness = min(1.0, sum(top_pair_counts) / 10.0)
    perturbation = 0.35 if len(radii) <= 1 else min(1.0, 0.35 + 0.2 * len(radii))
    engine_bonus = 0.15 if "squidpy" in engines else 0.0
    score = min(1.0, richness * 0.45 + perturbation + engine_bonus)
    return ReliabilityComponent(
        name="R_spatial_robustness",
        score=round(_clip(score), 4),
        status="computed",
        evidence=["radii:%s" % ",".join(sorted(radii) or ["unknown"]), "engines:%s" % ",".join(sorted(engines) or ["prototype"])],
        caveat="Full v12 robustness requires rerunning neighborhood enrichment across a radius/permutation grid; this score is a first-pass proxy.",
    )


def _interpret_reliability(
    reliability: float,
    claim: Dict[str, Any],
    components: Dict[str, ReliabilityComponent],
) -> str:
    lowest = min(components.values(), key=lambda component: component.score)
    if reliability >= 0.8:
        level = "high"
    elif reliability >= 0.5:
        level = "moderate"
    elif reliability > 0.0:
        level = "low"
    else:
        level = "blocked"
    return (
        "Claim reliability is %s (%.2f). Limiting component: %s=%.2f. %s"
        % (level, reliability, lowest.name, lowest.score, lowest.caveat)
    )


def _top_pairs(result: ToolResult) -> List[Dict[str, Any]]:
    metrics = result.metrics or {}
    pairs = metrics.get("top_pairs")
    if isinstance(pairs, list):
        return [pair for pair in pairs if isinstance(pair, dict)]
    return []


def _markers_for_claim(claim_text: str) -> set[str]:
    markers: set[str] = set()
    for label, genes in DEFAULT_CELL_MARKERS.items():
        if label in claim_text:
            markers.update(genes)
    return markers


def _features_from_payload(payload: Dict[str, Any]) -> set[str]:
    features = set()
    contract = payload.get("contract") or {}
    for key in ("feature_names", "genes", "panel_features"):
        values = payload.get(key) or contract.get(key)
        if isinstance(values, Iterable) and not isinstance(values, (str, bytes, dict)):
            features.update(str(value).upper() for value in values)
    return features


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
