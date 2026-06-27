import hashlib
import json
import os
import platform
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from spatialmind.versioning import collect_versions


@dataclass
class RunRecord:
    run_id: str
    session_id: str
    dataset_id: str
    query: str
    tool_trace: List[Dict[str, Any]]
    result_path: str
    viz_paths: List[str]
    interpretation: str
    params: Dict[str, Any]
    env_versions: Dict[str, str]
    provenance_hash: str
    created_at: str
    duration_seconds: float
    run_dir: str
    provenance_path: str
    artifacts: Dict[str, str]
    batch_job_id: str = ""
    fusion_dataset_key: str = ""


@dataclass
class ReportRecord:
    report_id: str
    run_id: str
    html_path: str
    pdf_path: str = ""
    created_at: str = ""


@dataclass
class MVPRunRecord:
    run_id: str
    query: str
    tool_trace: List[Dict[str, Any]]
    params: Dict[str, Any]
    random_seed: int
    env_versions: Dict[str, str]
    input_file_md5: Dict[str, str]
    artifact_paths: Dict[str, str]
    artifact_md5: Dict[str, str]
    figure_paths: List[str]
    figure_md5: Dict[str, str]
    table_paths: List[str]
    table_md5: Dict[str, str]
    created_at: str
    run_record_path: str = ""


class StorageLayer:
    """Versioned local storage for run artifacts and provenance."""

    def __init__(self, root: str = "outputs") -> None:
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def start_run(self, sample_id: str) -> Dict[str, str]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = "%s_%s_%s" % (sample_id or "sample", stamp, uuid.uuid4().hex[:8])
        run_dir = os.path.join(self.root, run_id)
        os.makedirs(run_dir, exist_ok=True)
        return {"run_id": run_id, "run_dir": run_dir}

    def write_json(self, run_dir: str, filename: str, payload: Any) -> str:
        path = os.path.join(run_dir, filename)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(_to_jsonable(payload), handle, indent=2, sort_keys=True)
        return path

    def write_text(self, run_dir: str, filename: str, content: str) -> str:
        path = os.path.join(run_dir, filename)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def write_provenance(self, run_dir: str, payload: Dict[str, Any]) -> str:
        provenance = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
        }
        provenance.update(payload)
        provenance["provenance_hash"] = _stable_hash(provenance)
        return self.write_json(run_dir, "provenance.json", provenance)

    def get_run(self, run_id: str) -> RunRecord:
        run_dir = os.path.join(self.root, run_id)
        provenance_path = os.path.join(run_dir, "provenance.json")
        if not os.path.exists(provenance_path):
            raise FileNotFoundError("No stored run found for run_id=%s" % run_id)
        with open(provenance_path, encoding="utf-8") as handle:
            provenance = json.load(handle)
        artifacts = dict(provenance.get("artifacts") or {})
        return RunRecord(
            run_id=str(provenance.get("run_id") or run_id),
            session_id=str(provenance.get("session_id") or ""),
            dataset_id=str(provenance.get("dataset_id") or provenance.get("sample_id") or ""),
            query=str(provenance.get("query") or provenance.get("prompt") or ""),
            tool_trace=list(provenance.get("tool_trace") or []),
            result_path=str(provenance.get("result_s3_key") or artifacts.get("report") or ""),
            viz_paths=[str(value) for key, value in artifacts.items() if key.startswith("spatial") or "figure" in key],
            interpretation=str(provenance.get("interpretation") or ""),
            params=dict(provenance.get("params") or {}),
            env_versions=dict(provenance.get("env_versions") or {"python": str(provenance.get("python") or "")}),
            provenance_hash=str(provenance.get("provenance_hash") or _stable_hash(provenance)),
            created_at=str(provenance.get("created_at_utc") or ""),
            duration_seconds=float(provenance.get("duration_seconds") or 0.0),
            run_dir=run_dir,
            provenance_path=provenance_path,
            artifacts=artifacts,
            batch_job_id=str(provenance.get("batch_job_id") or ""),
            fusion_dataset_key=str(provenance.get("fusion_dataset_key") or ""),
        )

    def list_runs(self) -> List[str]:
        if not os.path.exists(self.root):
            return []
        run_ids = []
        for name in sorted(os.listdir(self.root)):
            if os.path.exists(os.path.join(self.root, name, "provenance.json")):
                run_ids.append(name)
        return run_ids

    def list_figures(self, run_id: str) -> List[str]:
        run_dir = os.path.join(self.root, run_id)
        if not os.path.isdir(run_dir):
            raise FileNotFoundError("No stored run found for run_id=%s" % run_id)
        figure_extensions = (".svg", ".png", ".html")
        return [
            os.path.join(run_dir, name)
            for name in sorted(os.listdir(run_dir))
            if name.lower().endswith(figure_extensions)
        ]

    def write_mvp_run_record(
        self,
        query: str,
        tool_trace: List[Any],
        params: Dict[str, Any],
        input_files: List[str],
        artifacts: Optional[Dict[str, str]] = None,
        figures: Optional[List[str]] = None,
        tables: Optional[List[str]] = None,
        random_seed: int = 42,
        run_id: Optional[str] = None,
    ) -> MVPRunRecord:
        os.makedirs(os.path.join(self.root, "runs"), exist_ok=True)
        run_id = run_id or "mvp_%s_%s" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8])
        artifacts = artifacts or {}
        figures = figures or []
        tables = tables or []
        record = MVPRunRecord(
            run_id=run_id,
            query=query,
            tool_trace=[_to_jsonable(item) for item in tool_trace],
            params=_to_jsonable(params),
            random_seed=random_seed,
            env_versions=_safe_versions(),
            input_file_md5={path: _file_md5(path) for path in input_files if os.path.exists(path)},
            artifact_paths={key: path for key, path in artifacts.items() if os.path.exists(path)},
            artifact_md5={key: _file_md5(path) for key, path in artifacts.items() if os.path.exists(path)},
            figure_paths=[path for path in figures if os.path.exists(path)],
            figure_md5={path: _file_md5(path) for path in figures if os.path.exists(path)},
            table_paths=[path for path in tables if os.path.exists(path)],
            table_md5={path: _file_md5(path) for path in tables if os.path.exists(path)},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        path = os.path.join(self.root, "runs", "%s.json" % run_id)
        record.run_record_path = path
        self.write_json(os.path.join(self.root, "runs"), "%s.json" % run_id, record)
        return record


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value


def _stable_hash(payload: Dict[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("provenance_hash", None)
    serialized = json.dumps(_to_jsonable(normalized), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _file_md5(path: str) -> str:
    digest = hashlib.md5()
    if os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for name in sorted(files):
                file_path = os.path.join(root, name)
                rel_path = os.path.relpath(file_path, path)
                digest.update(rel_path.encode("utf-8"))
                digest.update(str(os.path.getsize(file_path)).encode("utf-8"))
        return digest.hexdigest()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_versions() -> Dict[str, str]:
    try:
        return collect_versions()
    except Exception:
        return {"python": platform.python_version()}
