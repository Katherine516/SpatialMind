"""The Reports tab: what a run left behind, and what the user did with it.

A run writes an immutable record -- hashed inputs, tool trace, artifacts -- and
replay verifies it. None of that may change. What people need on top of it is
mutable and personal: a name that means something in three weeks, a pin, a
delete for the seven exploratory runs, and the ability to *edit the report* and
send that.

So there are two layers, and they are kept apart on purpose:

* the run directory and its record, which this module never rewrites
* this sidecar index, which holds titles, pins, and edited report text

An edited report is stored beside the original and never over it. The export
then says "edited by hand after the run", because a document that carries a run
id has to be traceable back to what actually ran -- otherwise the provenance
chain that the rest of this project is built on ends at the last mile.
"""

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

INDEX_FILENAME = "reports_index.json"
EDITED_FILENAME = "report_edited.md"
REPORT_CANDIDATES = (
    "validated_xenium_pilot_report.md",
    "report.md",
)
HTML_CANDIDATES = (
    "validated_xenium_pilot_report.html",
    "report.html",
)


def _now() -> float:
    return time.time()


class ReportLibrary:
    """Sidecar index over the output root. Safe to delete; rebuilds from disk."""

    def __init__(self, output_root: str) -> None:
        self.output_root = Path(output_root)
        self.index_path = self.output_root / INDEX_FILENAME
        self._index: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ---- persistence -------------------------------------------------

    def _load(self) -> None:
        try:
            with open(self.index_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self._index = {str(k): dict(v) for k, v in (data.get("reports") or {}).items()}
        except (OSError, ValueError):
            self._index = {}

    def _save(self) -> None:
        self.output_root.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "updated_at": _now(), "reports": self._index}
        temporary = self.index_path.with_suffix(".tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(temporary, self.index_path)

    # ---- discovery ---------------------------------------------------

    def _report_paths(self, directory: Path) -> Dict[str, str]:
        found: Dict[str, str] = {}
        for name in REPORT_CANDIDATES:
            candidate = directory / name
            if candidate.exists():
                found["markdown"] = str(candidate)
                break
        for name in HTML_CANDIDATES:
            candidate = directory / name
            if candidate.exists():
                found["html"] = str(candidate)
                break
        if not found:
            # Any single HTML file is better than declaring a run reportless.
            for candidate in sorted(directory.glob("*.html")):
                found["html"] = str(candidate)
                break
        edited = directory / EDITED_FILENAME
        if edited.exists():
            found["edited"] = str(edited)
        for name in ("pilot_validation.json", "plan_results.json"):
            validation = directory / name
            if validation.exists():
                found["validation"] = str(validation)
                break
        return found

    def scan(self) -> List[Dict[str, Any]]:
        """Every run directory that produced a report, newest first.

        Directories are the source of truth. A report the user renamed keeps its
        name; one whose directory is gone drops out of the list rather than
        lingering as a dead entry the user cannot open.
        """
        if not self.output_root.exists():
            return []
        rows: List[Dict[str, Any]] = []
        live: set = set()
        for directory in sorted(self.output_root.iterdir()):
            if not directory.is_dir():
                continue
            paths = self._report_paths(directory)
            if not paths:
                continue
            report_id = directory.name
            live.add(report_id)
            entry = self._index.setdefault(report_id, {})
            entry.setdefault("created_at", directory.stat().st_mtime)
            entry.setdefault("pinned", False)
            rows.append(self._describe(report_id, directory, paths, entry))

        # Drop index entries whose directory is gone, so the list cannot show a
        # report that no longer exists.
        stale = [key for key in self._index if key not in live]
        for key in stale:
            self._index.pop(key, None)
        if stale:
            self._save()

        rows.sort(key=lambda row: (not row["pinned"], -row["created_at"]))
        return rows

    def _describe(self, report_id: str, directory: Path,
                  paths: Dict[str, str], entry: Dict[str, Any]) -> Dict[str, Any]:
        status, dataset, gate_status, run_id, run_title = _read_validation(paths.get("validation"))
        artifacts = [p for p in directory.rglob("*") if p.is_file()]
        return {
            "report_id": report_id,
            # A title the user set wins; otherwise what they asked the run for,
            # and only then the job id.
            "title": entry.get("title") or run_title or _default_title(report_id),
            "pinned": bool(entry.get("pinned")),
            "created_at": entry.get("created_at") or directory.stat().st_mtime,
            "edited_at": entry.get("edited_at"),
            "directory": str(directory),
            "has_markdown": "markdown" in paths,
            "has_html": "html" in paths,
            "edited": "edited" in paths,
            "status": status,
            "dataset": dataset,
            "gate_status": gate_status,
            "run_id": run_id,
            "artifact_count": len(artifacts),
            "bytes": sum(p.stat().st_size for p in artifacts),
        }

    # ---- reads -------------------------------------------------------

    def get(self, report_id: str) -> Optional[Dict[str, Any]]:
        directory = self._directory(report_id)
        if directory is None:
            return None
        paths = self._report_paths(directory)
        if not paths:
            return None
        entry = self._index.setdefault(report_id, {})
        entry.setdefault("created_at", directory.stat().st_mtime)
        described = self._describe(report_id, directory, paths, entry)
        described["paths"] = paths
        return described

    def markdown(self, report_id: str, *, original: bool = False) -> str:
        """The report text: the user's edit when there is one, else the run's."""
        described = self.get(report_id)
        if not described:
            return ""
        paths = described["paths"]
        if not original and paths.get("edited"):
            return Path(paths["edited"]).read_text(encoding="utf-8")
        if paths.get("markdown"):
            return Path(paths["markdown"]).read_text(encoding="utf-8")
        return ""

    def provenance(self, report_id: str) -> Dict[str, Any]:
        described = self.get(report_id) or {}
        return {
            "run_id": described.get("run_id") or report_id,
            "dataset": described.get("dataset") or "",
            "gate_status": described.get("gate_status") or "",
            "edited": bool(described.get("edited")),
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _directory(self, report_id: str) -> Optional[Path]:
        # Reject traversal outright: report ids come from the URL.
        if not report_id or "/" in report_id or "\\" in report_id or report_id.startswith("."):
            return None
        directory = self.output_root / report_id
        try:
            directory.resolve().relative_to(self.output_root.resolve())
        except (ValueError, OSError):
            return None
        return directory if directory.is_dir() else None

    # ---- writes ------------------------------------------------------

    def rename(self, report_id: str, title: str) -> bool:
        if self._directory(report_id) is None:
            return False
        clean = (title or "").strip()[:120]
        if not clean:
            return False
        self._index.setdefault(report_id, {})["title"] = clean
        self._save()
        return True

    def set_pinned(self, report_id: str, pinned: bool) -> bool:
        if self._directory(report_id) is None:
            return False
        self._index.setdefault(report_id, {})["pinned"] = bool(pinned)
        self._save()
        return True

    def save_edit(self, report_id: str, markdown: str) -> bool:
        """Write the user's version beside the run's, never over it."""
        directory = self._directory(report_id)
        if directory is None:
            return False
        (directory / EDITED_FILENAME).write_text(markdown or "", encoding="utf-8")
        entry = self._index.setdefault(report_id, {})
        entry["edited_at"] = _now()
        self._save()
        return True

    def revert_edit(self, report_id: str) -> bool:
        directory = self._directory(report_id)
        if directory is None:
            return False
        edited = directory / EDITED_FILENAME
        if edited.exists():
            edited.unlink()
        self._index.setdefault(report_id, {}).pop("edited_at", None)
        self._save()
        return True

    def delete(self, report_id: str) -> bool:
        """Remove the run directory and its index entry.

        This deletes the run record too, so replay of that run becomes
        impossible. The UI confirms before calling it; that is the only guard,
        and it is deliberate -- a Reports tab that cannot delete accumulates
        until it is useless.
        """
        directory = self._directory(report_id)
        if directory is None:
            return False
        shutil.rmtree(directory, ignore_errors=True)
        self._index.pop(report_id, None)
        self._save()
        return True


def _default_title(report_id: str) -> str:
    text = str(report_id).replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else "Untitled report"


def _read_validation(path: Optional[str]):
    """(status, dataset, gate_status, run_id, title) from a run's own JSON.

    Two shapes: a pilot writes `pilot_validation.json`, a Studio plan run writes
    `plan_results.json`. Both are read, because a Reports tab that understands
    one kind of run and calls the other "Job f846d36a14" is a list nobody can
    scan.
    """
    if not path:
        return "", "", "", "", ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return "", "", "", "", ""

    dataset = os.path.basename(str(payload.get("dataset_path") or "").rstrip("/"))
    if not dataset:
        entry = payload.get("dataset") or {}
        dataset = str(entry.get("display_name") or entry.get("name") or "")

    status = str(payload.get("status") or "")
    if not status and payload.get("results") is not None:
        # A plan run has no gate verdict of its own; its lane is the honest
        # equivalent, and it is what the badge should say.
        from . import plan_report

        status = plan_report.lane_for_payload(payload)

    run_id = str(payload.get("run_id") or "")
    if not run_id:
        record = payload.get("run_record_path") or ""
        if record:
            run_id = Path(str(record)).stem
    return status, dataset, status, run_id, str(payload.get("title") or "")
