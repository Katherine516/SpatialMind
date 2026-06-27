import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from spatialmind.datasets import discover_dataset_candidates, inspect_dataset


@dataclass
class DatasetGovernanceRecord:
    dataset_path: str
    data_type: str
    modality: str
    sample_id: str
    source: str = "local_data_folder"
    source_url: str = ""
    license: str = "needs_review"
    consent_class: str = "needs_review"
    phi_risk: str = "unknown"
    allowed_use: List[str] = field(default_factory=lambda: ["local_software_validation"])
    restrictions: List[str] = field(default_factory=lambda: ["do_not_send_raw_data_to_llm", "do_not_claim_clinical_validity"])
    reviewer: str = ""
    notes: str = "Metadata generated locally; license/consent/PHI fields require human review."

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_dataset_governance_manifest(data_root: str, output_path: str) -> Dict[str, Any]:
    records = []
    for path in discover_dataset_candidates(data_root):
        inspection = inspect_dataset(path)
        records.append(
            DatasetGovernanceRecord(
                dataset_path=inspection.path,
                data_type=inspection.data_type,
                modality=inspection.modality,
                sample_id=inspection.sample_id,
                phi_risk=_initial_phi_risk(inspection.data_type, inspection.path),
            ).to_dict()
        )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_root": data_root,
        "status": "needs_human_governance_review",
        "records": records,
        "review_instructions": [
            "Fill source_url and license from the dataset provider or publication.",
            "Fill consent_class from IRB/dbGaP/DUO terms when human data is involved.",
            "Set phi_risk to low/medium/high after checking filenames, metadata, images, and raw clinical fields.",
            "Keep raw data out of LLM prompts; pass only aggregate summaries, artifact IDs, and approved excerpts.",
        ],
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(_jsonable(manifest), indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _initial_phi_risk(data_type: str, path: str) -> str:
    lowered = path.lower()
    if data_type == "xenium_directory":
        return "medium"
    if any(token in lowered for token in ["human", "patient", "clinical", "ffpe"]):
        return "medium"
    return "unknown"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
