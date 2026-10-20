"""Explicit run-to-knowledge bridge; never parses edited report prose as results."""

import hashlib
import json
from pathlib import Path

from ..storage.replay import verify_run_record


def import_run(studio, store, report_id, dataset_id):
    entry = studio.entry(dataset_id)
    if entry.missing:
        raise ValueError("Selected dataset is missing.")
    report = studio.reports.get(report_id)
    if not report or not report["paths"].get("validation"):
        raise ValueError("Select a report with structured plan/pilot results.")
    artifact = Path(report["paths"]["validation"]).resolve()
    artifact.relative_to(Path(studio.output_root).resolve())
    if artifact.stat().st_size > 2 * 1024 ** 2:
        raise ValueError("Structured report exceeds the 2 MiB knowledge import limit.")
    raw = artifact.read_bytes()
    payload = json.loads(raw)
    record_path = Path(payload.get("run_record_path") or "").resolve()
    record_path.relative_to(Path(studio.output_root).resolve())
    if not record_path.is_file() or record_path.stat().st_size > 2 * 1024 ** 2:
        raise ValueError("A bounded, path-backed run record is required.")
    record_raw = record_path.read_bytes()
    record = json.loads(record_raw)
    dataset_path = Path(entry.path).resolve()
    inputs = record.get("input_file_md5") or {}
    # Restrict replay's read set before letting it open paths from a stored record.
    if str(dataset_path) not in {str(Path(p).resolve()) for p in inputs}:
        raise ValueError("Run inputs do not identify the selected dataset.")
    for p in inputs:
        resolved = Path(p).resolve()
        if resolved != dataset_path:
            resolved.relative_to(dataset_path if dataset_path.is_dir() else dataset_path.parent)
    for p in list((record.get("artifact_paths") or {}).values()) + list((record.get("figure_md5") or {})) + list((record.get("table_md5") or {})):
        Path(p).resolve().relative_to(Path(studio.output_root).resolve())
    matched = [key for key, p in (record.get("artifact_paths") or {}).items() if Path(p).resolve() == artifact]
    if not matched or any((record.get("artifact_md5") or {}).get(key) != hashlib.md5(raw).hexdigest() for key in matched):
        raise ValueError("The structured result is not covered by the run record's artifact hash.")
    verification = verify_run_record(str(record_path))
    if verification.status != "verified":
        raise ValueError("Run replay verification failed: " + verification.status)
    if artifact.read_bytes() != raw or record_path.read_bytes() != record_raw:
        raise ValueError("Run evidence changed during verification. Retry against a stable snapshot.")
    scope = "dataset:" + dataset_id
    metadata = {"scope": scope, "kind": "run_artifact", "report_id": report_id,
                "run_id": record.get("run_id"), "verified_at": store.now(),
                "artifact_path": str(artifact), "artifact_sha256": hashlib.sha256(raw).hexdigest(),
                "record_path": str(record_path), "record_sha256": hashlib.sha256(record_raw).hexdigest(),
                "input_hash_scope": record.get("input_hash_scope", {}), "params": record.get("params", {})}
    # Bounded projection of exact JSON fields, not a prose interpretation or a
    # flattened claim ledger. Pointers make the selected values auditable.
    fields, omitted = [], []

    def take(pointer, value):
        encoded = json.dumps(value, ensure_ascii=True)
        if len(fields) >= 40 or len(encoded) > 500 or len(pointer) > 200:
            omitted.append(pointer)
        else:
            fields.append("[%s]\n%s" % (pointer, encoded))

    for key in ("run_id", "status", "scope", "records_loaded", "features_loaded", "tools", "gate"):
        if key in payload:
            take("/" + key, payload[key])
    for index, result in enumerate(payload.get("results") or []):
        if not isinstance(result, dict):
            continue
        for key in ("tool", "tool_name", "status", "summary", "method", "limitations"):
            if key in result:
                take("/results/%d/%s" % (index, key), result[key])
        for key, value in (result.get("metrics") or {}).items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                take("/results/%d/metrics/%s" % (index, escaped), value)
            else:
                omitted.append("/results/%d/metrics/%s" % (index, key))
    metadata["projection"] = {"included_fields": len(fields), "omitted_fields": omitted,
                              "other_sections": "Only the listed JSON pointers are imported. Nested metrics, claim ledgers and tables stay in the original report."}
    body = "Historical run %s. Hash verification is not biological validation.\n\n%s\n\nThis is a selected-field snapshot, not the complete report. Nested metrics, claim ledgers and tables must be inspected in the original artifact." % (record.get("run_id"), "\n\n".join(fields))
    identity = store.add("Run evidence: " + report_id[:160], body, metadata=metadata)
    return {"source_id": identity, "status": "pending", "verification": verification.to_dict(), "metadata": metadata}
