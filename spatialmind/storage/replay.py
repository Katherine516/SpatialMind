import json
import sqlite3
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .run_store import _file_md5


@dataclass
class FileCheck:
    path: str
    expected_md5: str
    observed_md5: str = ""
    status: str = "missing"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReplayVerificationReport:
    run_id: str
    record_path: str
    status: str
    checks: List[FileCheck] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "record_path": self.record_path,
            "status": self.status,
            "checks": [item.to_dict() for item in self.checks],
            "warnings": self.warnings,
        }


def init_run_database(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                record_path TEXT NOT NULL,
                query TEXT,
                created_at TEXT,
                run_type TEXT,
                dataset_paths TEXT,
                indexed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_files (
                run_id TEXT,
                role TEXT,
                path TEXT,
                expected_md5 TEXT,
                PRIMARY KEY (run_id, role, path)
            )
            """
        )


def index_run_records(output_root: str, db_path: str) -> Dict[str, Any]:
    init_run_database(db_path)
    record_paths = sorted(Path(output_root).rglob("runs/*.json"))
    indexed = 0
    with sqlite3.connect(db_path) as conn:
        for record_path in record_paths:
            payload = _load_json(record_path)
            run_id = str(payload.get("run_id") or record_path.stem)
            conn.execute(
                """
                INSERT OR REPLACE INTO runs
                (run_id, record_path, query, created_at, run_type, dataset_paths, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(record_path),
                    str(payload.get("query") or ""),
                    str(payload.get("created_at") or ""),
                    "mvp_run_record",
                    json.dumps(list((payload.get("input_file_md5") or {}).keys())),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            for role, key in [
                ("input", "input_file_md5"),
                ("artifact", "artifact_md5"),
                ("figure", "figure_md5"),
                ("table", "table_md5"),
            ]:
                for path, expected in (payload.get(key) or {}).items():
                    stored_path = path
                    if role == "artifact":
                        stored_path = (payload.get("artifact_paths") or {}).get(path, "")
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO run_files
                        (run_id, role, path, expected_md5)
                        VALUES (?, ?, ?, ?)
                        """,
                        (run_id, role, stored_path or path, str(expected)),
                    )
            indexed += 1
    return {"db_path": db_path, "output_root": output_root, "run_records_indexed": indexed}


def verify_run_record(record_path: str) -> ReplayVerificationReport:
    payload = _load_json(Path(record_path))
    run_id = str(payload.get("run_id") or Path(record_path).stem)
    checks: List[FileCheck] = []
    warnings: List[str] = []
    for key in ("input_file_md5", "figure_md5", "table_md5"):
        for path, expected in (payload.get(key) or {}).items():
            checks.append(_check_file(path, str(expected)))
    artifact_paths = payload.get("artifact_paths") or {}
    for artifact_id, expected in (payload.get("artifact_md5") or {}).items():
        path = artifact_paths.get(artifact_id)
        if not path:
            warnings.append("Artifact `%s` has a stored hash but no artifact path in this run record." % artifact_id)
            continue
        checks.append(_check_file(path, str(expected)))
    if not checks:
        warnings.append("Run record contains no path-backed hash fields to verify.")
        return ReplayVerificationReport(run_id=run_id, record_path=record_path, status="unverifiable", warnings=warnings)
    failed = [item for item in checks if item.status != "ok"]
    status = "verified" if not failed else "failed"
    return ReplayVerificationReport(run_id=run_id, record_path=record_path, status=status, checks=checks, warnings=warnings)


def replay_run_record(record_path: str, output_dir: Optional[str] = None, verify_only: bool = True) -> Dict[str, Any]:
    verification = verify_run_record(record_path)
    if verification.status != "verified":
        return {"status": "blocked_verification_failed", "verification": verification.to_dict()}
    if verify_only:
        return {"status": "verified_only", "verification": verification.to_dict()}

    payload = _load_json(Path(record_path))
    query = str(payload.get("query") or "")
    input_paths = list((payload.get("input_file_md5") or {}).keys())
    if "Validated Xenium pilot" not in query or not input_paths:
        return {
            "status": "blocked_replay_not_supported",
            "verification": verification.to_dict(),
            "reason": "Automatic replay is currently implemented for validated Xenium pilot run records only.",
        }
    params = dict(payload.get("params") or {})
    replay_output = output_dir or "outputs/replay/%s" % str(payload.get("run_id") or Path(record_path).stem)
    return {
        "status": "verified_replay_ready",
        "verification": verification.to_dict(),
        "replay_output_dir": replay_output,
        "dataset_path": input_paths[0],
        "params": {
            "max_records": int(params.get("max_records") or 5000),
            "min_label_coverage": float(params.get("min_label_coverage") or 0.7),
            "min_region_coverage": float(params.get("min_region_coverage") or 0.7),
            "allow_single_region": bool(params.get("allow_single_region") or False),
        },
    }


def _check_file(path: str, expected: str) -> FileCheck:
    check = FileCheck(path=path, expected_md5=expected)
    if not Path(path).exists():
        return check
    check.observed_md5 = _file_md5(path)
    check.status = "ok" if check.observed_md5 == expected else "md5_mismatch"
    return check


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
