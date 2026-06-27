import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from spatialmind.ingestion import load_xenium
from spatialmind.ingestion.labels import load_xenium_analysis_clusters
from spatialmind.schemas import SpotRecord


ASTROCYTE_TERM_PATH = "data/cell_ontology_terms/CL_0000127_astrocyte.json"
DEFAULT_GLIOBLASTOMA_DATASET = "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs"


def write_astrocyte_label_suggestions(
    dataset_path: str = DEFAULT_GLIOBLASTOMA_DATASET,
    ontology_path: str = ASTROCYTE_TERM_PATH,
    output_dir: str = "outputs/glioblastoma_expert_review_packet",
    max_records: int = 2500,
) -> Dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    term = _read_json(Path(ontology_path))
    dataset = load_xenium(dataset_path, max_records=max_records)
    clusters = load_xenium_analysis_clusters(dataset_path)

    rows: List[Dict[str, str]] = []
    status_counts: Counter[str] = Counter()
    for record in dataset.records:
        suggestion = _astrocyte_suggestion(record, term)
        status_counts[suggestion["review_status"]] += 1
        rows.append(
            {
                "cell_id": record.cell_id or "",
                "x": "%.4f" % record.x,
                "y": "%.4f" % record.y,
                "current_label": record.cell_type,
                "graph_cluster": clusters.get(record.cell_id or "", ""),
                "suggested_label": suggestion["suggested_label"],
                "cl_id": str(term.get("obo_id") or "CL:0000127"),
                "secondary_state": suggestion["secondary_state"],
                "confidence": suggestion["confidence"],
                "evidence": suggestion["evidence"],
                "notes": suggestion["notes"],
                "review_status": suggestion["review_status"],
            }
        )

    suggestions_path = out / "expert_cell_labels_astrocyte_prefill_for_review.csv"
    fieldnames = [
        "cell_id",
        "x",
        "y",
        "current_label",
        "graph_cluster",
        "suggested_label",
        "cl_id",
        "secondary_state",
        "confidence",
        "evidence",
        "notes",
        "review_status",
    ]
    with suggestions_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "status": "machine_prefill_for_expert_review",
        "dataset_path": dataset_path,
        "ontology_path": ontology_path,
        "ontology_label": term.get("label"),
        "ontology_id": term.get("obo_id"),
        "records_loaded": len(dataset.records),
        "output_csv": str(suggestions_path),
        "review_status_counts": dict(status_counts),
        "measured_marker_basis": ["AQP4", "EGFR", "CD68"],
        "missing_ontology_markers_in_panel": ["GFAP", "GLUT1/SLC2A1", "MBP", "NGFR"],
        "important_boundary": (
            "This file contains machine suggestions based on measured marker evidence and the astrocyte ontology term. "
            "It is not an expert label file and should not be renamed to expert_cell_labels.csv until reviewed."
        ),
    }
    summary_path = out / "astrocyte_prefill_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _append_readme_note(out / "README.md", suggestions_path, summary_path)
    return summary


def _astrocyte_suggestion(record: SpotRecord, term: Dict[str, Any]) -> Dict[str, str]:
    genes = record.genes
    aqp4 = _value(genes, "AQP4")
    egfr = _value(genes, "EGFR")
    cd68 = _value(genes, "CD68")
    neural_glial = (record.cell_type or "").lower() == "neural/glial cell"
    positive = []
    if aqp4 > 0:
        positive.append("AQP4=%.3g" % aqp4)
    if egfr > 0:
        positive.append("EGFR=%.3g" % egfr)
    negative = "CD68=0" if cd68 <= 0 else "CD68=%.3g" % cd68

    if neural_glial and aqp4 > 0 and cd68 <= 0:
        confidence = "0.70" if egfr > 0 else "0.62"
        status = "needs_expert_review"
        label = str(term.get("label") or "astrocyte")
        notes = "Suggested from Neural/Glial current label plus AQP4 support and CD68-negative evidence."
    elif neural_glial and egfr > 0 and cd68 <= 0:
        confidence = "0.55"
        status = "needs_expert_review_low_confidence"
        label = str(term.get("label") or "astrocyte")
        notes = "Low-confidence suggestion from EGFR support and CD68-negative evidence; GFAP/NGFR/GLUT1 are not measured in this panel."
    else:
        confidence = ""
        status = "not_astrocyte_prefilled"
        label = ""
        notes = "Not prefilled as astrocyte by the conservative ontology-marker rule."
    return {
        "suggested_label": label,
        "secondary_state": "reactive_candidate" if label and egfr > 0 else "",
        "confidence": confidence,
        "evidence": ";".join(positive + [negative]),
        "notes": notes,
        "review_status": status,
    }


def _value(genes: Dict[str, float], name: str) -> float:
    try:
        return float(genes.get(name, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Ontology term JSON must be an object: %s" % path)
    return payload


def _append_readme_note(readme_path: Path, suggestions_path: Path, summary_path: Path) -> None:
    if not readme_path.exists():
        return
    marker = "## Astrocyte Ontology Prefill"
    content = readme_path.read_text(encoding="utf-8")
    note = (
        "\n%s\n\n"
        "An astrocyte ontology term was saved under `data/cell_ontology_terms/CL_0000127_astrocyte.json` and used to create a machine-prefilled review file:\n\n"
        "- `%s`\n"
        "- `%s`\n\n"
        "This is not a final expert label file. Reviewers should confirm or correct the suggested `astrocyte` labels before saving any completed table as `expert_cell_labels.csv`.\n"
        % (marker, suggestions_path, summary_path)
    )
    if marker in content:
        content = content[: content.index(marker)].rstrip() + "\n" + note
    else:
        content = content.rstrip() + "\n" + note
    readme_path.write_text(content, encoding="utf-8")
