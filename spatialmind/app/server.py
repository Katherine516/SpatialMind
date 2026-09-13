"""The SpatialMind Studio application: HTTP surface over the existing agent.

Nothing here reimplements analysis. Ingestion, the gate, the registry, plan
validation and report generation are the same code the CLI runs; this module
gives them a session, a job queue and a browser.
"""

from dataclasses import asdict, is_dataclass
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Dict, List, Optional
import os
import time

from ..ingestion import (
    apply_best_available_labels,
    apply_best_available_regions,
    load_xenium,
)
from ..pilot import run_pilot
from ..storage import StorageLayer
from ..tools import build_default_registry
from .. import gatekeeper
from . import config
from . import gate as gate_module
from . import planner, resources, review
from .catalog import DEFAULT_DISPLAY_CELLS, IndexCache, discover_datasets
from .jobs import JobRunner, step

# macOS gates these behind a consent prompt; a scan of one blocks until answered.
PROTECTED_FOLDERS = ("Documents", "Desktop", "Downloads")


def _is_protected_folder(path: str) -> bool:
    try:
        parts = Path(path).resolve().relative_to(Path.home()).parts
    except (ValueError, OSError):
        return str(path).startswith("/Volumes/")
    return bool(parts) and parts[0] in PROTECTED_FOLDERS

STATIC_DIR = Path(__file__).parent / "static"


def jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class Studio:
    """Holds the session state a local single-user app needs: what datasets
    exist, their cell indexes, and the one job that may be running."""

    def __init__(self, data_root: Optional[str] = None, output_root: Optional[str] = None) -> None:
        self.data_root = str(Path(data_root or config.default_data_root()).expanduser().resolve())
        self.output_root = str(Path(output_root or config.default_output_root()).expanduser().resolve())
        self.indexes = IndexCache()
        self.jobs = JobRunner()
        self._datasets: Dict[str, Any] = {}
        self._scanned = False
        self._scan_thread: Optional[Thread] = None
        self._scan_lock = Lock()
        self._scan_error = ""
        # Set by the launcher when the UI is a native window rather than a browser
        # tab. The page needs it to leave room for the traffic lights, and asking
        # the server beats sniffing the user agent.
        self.window_mode = False
        # Deliberately not scanning here. On macOS the first read of a folder
        # under ~/Documents, ~/Desktop or ~/Downloads blocks on a TCC consent
        # prompt, and a scan in the constructor blocked the whole app before it
        # ever bound a port -- no window, no error, nothing to click. Scanning
        # lazily means the UI is already up when the prompt appears.

    def ensure_scanned(self, timeout: float = 6.0) -> bool:
        """Scan on a worker thread; report whether it finished in time.

        A blocked TCC prompt stops the scan inside the OS call, so it cannot be
        cancelled -- but it must not take the request thread with it, or the UI
        just spins with nothing to say. The caller gets False and can tell the
        user what macOS is waiting for.
        """
        if self._scanned:
            return True
        with self._scan_lock:
            if self._scan_thread is None or not self._scan_thread.is_alive():
                if self._scanned:
                    return True
                self._scan_error = ""
                self._scan_thread = Thread(target=self._scan_worker, name="dataset-scan", daemon=True)
                self._scan_thread.start()
            thread = self._scan_thread
        thread.join(timeout)
        return self._scanned

    def _scan_worker(self) -> None:
        try:
            self.refresh_datasets()
        except Exception as exc:
            self._scan_error = "%s: %s" % (type(exc).__name__, exc)

    def scan_status(self) -> Dict[str, Any]:
        pending = self._scan_thread is not None and self._scan_thread.is_alive()
        return {
            "scanned": self._scanned,
            "scanning": pending,
            "scan_error": self._scan_error,
            "waiting_on_permission": pending and _is_protected_folder(self.data_root),
        }

    def set_data_root(self, data_root: str) -> List[Dict[str, Any]]:
        """Point the app at a different folder and remember the choice."""
        path = Path(data_root).expanduser()
        if not path.is_dir():
            raise ValueError("Not a folder: %s" % path)
        self.data_root = str(path.resolve())
        self._scanned = False
        self._scan_thread = None
        self._scan_error = ""
        self.indexes.invalidate()
        config.save({"data_root": self.data_root})
        return self.refresh_datasets()

    def refresh_datasets(self) -> List[Dict[str, Any]]:
        entries = discover_datasets(self.data_root)
        self._datasets = {entry.dataset_id: entry for entry in entries}
        self._scanned = True
        return [entry.to_dict() for entry in entries]

    def entry(self, dataset_id: str):
        self.ensure_scanned()
        entry = self._datasets.get(dataset_id)
        if entry is None:
            raise KeyError(dataset_id)
        return entry

    def index(self, dataset_id: str, cluster_method: str = ""):
        entry = self.entry(dataset_id)
        if not entry.reviewable:
            raise ValueError("%s is a %s dataset; the review flow needs a Xenium bundle." % (entry.name, entry.data_type))
        return self.indexes.get(entry.path, cluster_method=cluster_method)

    def gate(self, dataset_id: str, cluster_method: str = "") -> Dict[str, Any]:
        entry = self.entry(dataset_id)
        index = self.index(dataset_id, cluster_method)
        return gate_module.evaluate(index, sample_id=entry.name)

    def gate_open(self, dataset_id: str) -> bool:
        try:
            return self.gate(dataset_id)["status"] == "validated_ready"
        except Exception:
            return False

    def job_output_dir(self, job_id: str) -> Path:
        path = Path(self.output_root) / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path


# --------------------------------------------------------------------------- jobs

def make_plan_worker(studio: Studio, dataset_id: str, tool_names: List[str],
                     overrides: Dict[str, Dict[str, Any]], max_records: int):
    """Execute exactly the tools the user chose, in dependency order."""

    def work(job) -> Dict[str, Any]:
        entry = studio.entry(dataset_id)
        plan = planner.build_plan(tool_names, overrides=overrides)
        job.steps_total = len(plan) + 2

        step(job, "Loading %s cells and the targeted panel." % ("all" if not max_records else format(max_records, ",")), 0)
        dataset = load_xenium(entry.path, max_records=max_records)
        dataset.metadata["analysis_dataset_path"] = entry.path

        step(job, "Applying reviewed labels and regions.", 1)
        label_report = apply_best_available_labels(dataset, entry.path, fallback=None)
        region_report = apply_best_available_regions(dataset, entry.path)

        registry = build_default_registry()
        results = []
        started = time.time()
        for position, spec in enumerate(plan):
            step(job, "Running %s (%d of %d)." % (spec.tool_name, position + 1, len(plan)), position + 2)
            tool_started = time.time()
            result = registry.get(spec.tool_name).run(dataset, dict(spec.params))
            results.append(
                {
                    "tool": spec.tool_name,
                    "params": dict(spec.params),
                    "summary": result.summary,
                    "metrics": jsonable(result.metrics),
                    "caveats": list(result.caveats),
                    "label_caveat": result.label_caveat,
                    "seconds": round(time.time() - tool_started, 2),
                }
            )

        step(job, "Writing the run record.", len(plan) + 2)
        output_dir = studio.job_output_dir(job.job_id)
        storage = StorageLayer(root=str(output_dir))
        record = storage.write_mvp_run_record(
            query=job.label,
            tool_trace=results,
            params={"tools": tool_names, "overrides": overrides, "max_records": max_records},
            input_files=[entry.path],
            run_id=job.job_id,
        )
        payload = {
            "dataset": entry.to_dict(),
            "tools": tool_names,
            "results": results,
            "label_report": jsonable(label_report.to_dict()),
            "region_report": jsonable(region_report.to_dict()),
            "records_loaded": len(dataset.records),
            "wall_seconds": round(time.time() - started, 2),
            "run_record_path": record.run_record_path,
            "output_dir": str(output_dir),
        }
        (output_dir / "plan_results.json").write_text(_dumps(payload), encoding="utf-8")
        return payload

    return work


def make_pilot_worker(studio: Studio, dataset_id: str, options: Dict[str, Any]):
    """The canonical pilot: gate, descriptive or validated lane, figures, report."""

    def work(job) -> Dict[str, Any]:
        entry = studio.entry(dataset_id)
        output_dir = studio.job_output_dir(job.job_id)
        job.steps_total = 1
        readiness_only = bool(options.get("readiness_only"))
        full_section = bool(options.get("full_section", True))
        step(job, "Running the pilot. Ingestion, gate, then the lane the gate allows.", 0)
        payload = run_pilot(
            dataset_path=entry.path,
            output_dir=output_dir,
            max_records=0 if full_section else int(options.get("max_records") or 5000),
            min_label_coverage=float(options.get("min_label_coverage", 0.7)),
            min_region_coverage=float(options.get("min_region_coverage", 0.7)),
            allow_single_region=bool(options.get("allow_single_region", False)),
            report_format=str(options.get("report_format", "html")),
            readiness_only=readiness_only,
            require_complete_section=True,
            review_max_records=int(options.get("review_max_records") or 5000),
            query=job.label,
        )
        step(job, "Pilot finished.", 1)
        result = jsonable(payload)
        result["output_dir"] = str(output_dir)
        return result

    return work


def _dumps(payload: Any) -> str:
    import json

    return json.dumps(jsonable(payload), indent=2)


# --------------------------------------------------------------------------- app

def create_studio_app(data_root: Optional[str] = None, output_root: Optional[str] = None):
    try:
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Install fastapi, pydantic and uvicorn to run SpatialMind Studio.") from exc

    studio = Studio(data_root=data_root, output_root=output_root)
    app = FastAPI(title="SpatialMind Studio", version="1.0")

    class AssignRequest(BaseModel):
        kind: str = Field(description="labels or regions")
        value: str
        cluster: Optional[str] = None
        bounds: Optional[Dict[str, float]] = None
        cell_ids: Optional[List[str]] = None
        confidence: float = 0.9
        notes: str = ""

    class ClearRequest(BaseModel):
        kind: str

    class ConfigRequest(BaseModel):
        data_root: str

    class AskRequest(BaseModel):
        question: str
        dataset_id: str

    class PlanRequest(BaseModel):
        dataset_id: str
        tools: List[str]
        overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    class RunRequest(BaseModel):
        dataset_id: str
        kind: str = "plan"
        label: str = "SpatialMind Studio run"
        tools: List[str] = Field(default_factory=list)
        overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
        max_records: int = 0
        options: Dict[str, Any] = Field(default_factory=dict)

    def _entry_or_404(dataset_id: str):
        try:
            return studio.entry(dataset_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown dataset: %s" % dataset_id)

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        payload = {
            "status": "ok",
            "data_root": studio.data_root,
            "output_root": studio.output_root,
            "datasets": len(studio._datasets),
            "capability_summary": planner.capability_summary(),
            "window_mode": studio.window_mode,
        }
        payload.update(studio.scan_status())
        return payload

    @app.post("/api/config")
    def set_config(request: ConfigRequest) -> Dict[str, Any]:
        try:
            entries = studio.set_data_root(request.data_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"data_root": studio.data_root, "datasets": entries}

    @app.get("/api/datasets")
    def list_datasets(refresh: bool = Query(False)) -> Dict[str, Any]:
        if refresh:
            entries = studio.refresh_datasets()
        elif not studio.ensure_scanned():
            status = studio.scan_status()
            status.update({"data_root": studio.data_root, "datasets": []})
            return status
        else:
            entries = [e.to_dict() for e in studio._datasets.values()]
        payload = {"data_root": studio.data_root, "datasets": entries}
        payload.update(studio.scan_status())
        return payload

    @app.get("/api/datasets/{dataset_id}")
    def dataset_detail(dataset_id: str) -> Dict[str, Any]:
        entry = _entry_or_404(dataset_id)
        if not entry.reviewable:
            return {"dataset": entry.to_dict(), "reviewable": False}
        index = studio.index(dataset_id)
        gate = studio.gate(dataset_id)
        return jsonable(
            {
                "dataset": entry.to_dict(),
                "reviewable": True,
                "n_cells": index.n_cells,
                "cluster_method": index.cluster_method,
                "cluster_methods": index.cluster_methods,
                "cluster_sizes": index.cluster_sizes(),
                "bounds": index.bounds(),
                "index_build_seconds": index.built_seconds,
                "gate": gate,
                "label_coverage": review.coverage(entry.path, "labels", index.cell_ids),
                "region_coverage": review.coverage(entry.path, "regions", index.cell_ids),
            }
        )

    @app.get("/api/datasets/{dataset_id}/cells")
    def dataset_cells(dataset_id: str, limit: int = Query(DEFAULT_DISPLAY_CELLS, ge=500, le=80000)) -> Dict[str, Any]:
        entry = _entry_or_404(dataset_id)
        index = studio.index(dataset_id)
        sample = index.display_sample(limit=limit)
        labels = review.read_table(entry.path, "labels")
        regions = review.read_table(entry.path, "regions")
        return jsonable(
            {
                "n_cells": index.n_cells,
                "displayed": len(sample["cell_ids"]),
                "step": sample["step"],
                "bounds": index.bounds(),
                "cluster_method": index.cluster_method,
                "x": sample["x"],
                "y": sample["y"],
                "cluster": sample["cluster"],
                "label": [labels.get(cid, {}).get("expert_label", "") for cid in sample["cell_ids"]],
                "region": [regions.get(cid, {}).get("region", "") for cid in sample["cell_ids"]],
            }
        )

    @app.post("/api/datasets/{dataset_id}/assign")
    def assign(dataset_id: str, request: AssignRequest) -> Dict[str, Any]:
        entry = _entry_or_404(dataset_id)
        index = studio.index(dataset_id)
        if request.kind not in review.KINDS:
            raise HTTPException(status_code=400, detail="kind must be 'labels' or 'regions'")

        if request.cell_ids:
            cell_ids = request.cell_ids
            scope = "%d cells" % len(cell_ids)
        elif request.cluster is not None:
            cell_ids = index.ids_in_cluster(request.cluster)
            scope = "cluster %s" % request.cluster
        elif request.bounds:
            b = request.bounds
            cell_ids = index.ids_in_rect(b.get("x0", 0.0), b.get("y0", 0.0), b.get("x1", 0.0), b.get("y1", 0.0))
            scope = "rectangle"
        else:
            raise HTTPException(status_code=400, detail="Provide cluster, bounds, or cell_ids.")

        if not cell_ids:
            raise HTTPException(status_code=400, detail="That selection (%s) contains no cells." % scope)
        try:
            result = review.assign(
                entry.path, request.kind, cell_ids, request.value,
                confidence=request.confidence, notes=request.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return jsonable(
            {
                "assignment": result.to_dict(),
                "scope": scope,
                "label_coverage": review.coverage(entry.path, "labels", index.cell_ids),
                "region_coverage": review.coverage(entry.path, "regions", index.cell_ids),
                "gate": studio.gate(dataset_id),
            }
        )

    @app.post("/api/datasets/{dataset_id}/clear")
    def clear(dataset_id: str, request: ClearRequest) -> Dict[str, Any]:
        entry = _entry_or_404(dataset_id)
        index = studio.index(dataset_id)
        if request.kind not in review.KINDS:
            raise HTTPException(status_code=400, detail="kind must be 'labels' or 'regions'")
        outcome = review.unassign(entry.path, request.kind, cell_ids=None)
        return jsonable(
            {
                "cleared": outcome,
                "label_coverage": review.coverage(entry.path, "labels", index.cell_ids),
                "region_coverage": review.coverage(entry.path, "regions", index.cell_ids),
                "gate": studio.gate(dataset_id),
            }
        )

    @app.get("/api/resources")
    def label_resources(dataset_id: str = Query("")) -> Dict[str, Any]:
        """What producing expert labels still needs, and what is already here."""
        dataset_path, gate = "", None
        if dataset_id:
            try:
                dataset_path = studio.entry(dataset_id).path
                gate = studio.gate(dataset_id)
            except (KeyError, ValueError):
                dataset_path, gate = dataset_path or "", None
        return jsonable(resources.inventory(studio.data_root, dataset_path or None, gate))

    @app.get("/api/tools")
    def tools(dataset_id: str = Query("")) -> Dict[str, Any]:
        gate_open = studio.gate_open(dataset_id) if dataset_id else False
        return jsonable(
            {
                "gate_open": gate_open,
                "capability_summary": planner.capability_summary(),
                "tools": planner.tool_catalog(gate_open),
                "recipes": planner.RECIPES,
            }
        )

    @app.post("/api/plan")
    def plan(request: PlanRequest) -> Dict[str, Any]:
        _entry_or_404(request.dataset_id)
        gate_open = studio.gate_open(request.dataset_id)
        return jsonable(planner.describe_plan(request.tools, gate_open, overrides=request.overrides))

    @app.post("/api/ask")
    def ask(request: AskRequest) -> Dict[str, Any]:
        _entry_or_404(request.dataset_id)
        gate_open = studio.gate_open(request.dataset_id)
        return jsonable(planner.propose(request.question, gate_open))

    @app.post("/api/runs")
    def start_run(request: RunRequest) -> Dict[str, Any]:
        entry = _entry_or_404(request.dataset_id)
        if request.kind == "plan":
            if not request.tools:
                raise HTTPException(status_code=400, detail="A plan run needs at least one tool.")
            # The UI declines to submit gate-blocked steps. That is a convention,
            # and a convention is not a guarantee: this endpoint accepted and ran
            # region_summary against a blocked section until it asked here too.
            try:
                gatekeeper.require_gate_open(
                    entry.path, request.tools,
                    gate=studio.gate(request.dataset_id) if entry.reviewable else None,
                    overrides=request.overrides,
                )
            except gatekeeper.GateBlockedError as exc:
                raise HTTPException(status_code=409, detail=exc.to_dict())
            worker = make_plan_worker(studio, request.dataset_id, request.tools, request.overrides, request.max_records)
        elif request.kind == "pilot":
            worker = make_pilot_worker(studio, request.dataset_id, request.options)
        else:
            raise HTTPException(status_code=400, detail="kind must be 'plan' or 'pilot'")
        try:
            job = studio.jobs.submit(
                kind=request.kind, label=request.label, dataset_id=request.dataset_id,
                dataset_path=entry.path, params={"tools": request.tools, "options": request.options},
                work=worker,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return jsonable(job.to_dict())

    @app.get("/api/runs")
    def list_runs() -> Dict[str, Any]:
        return jsonable({"jobs": [job.to_dict() for job in studio.jobs.list()]})

    @app.get("/api/runs/{job_id}")
    def get_run(job_id: str) -> Dict[str, Any]:
        job = studio.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job: %s" % job_id)
        return jsonable(job.to_dict())

    @app.get("/api/runs/{job_id}/report")
    def get_report(job_id: str):
        job = studio.jobs.get(job_id)
        if job is None or not job.result:
            raise HTTPException(status_code=404, detail="No report for %s yet." % job_id)
        for key in ("report_path", "html_report_path", "report_html_path"):
            candidate = job.result.get(key)
            if candidate and os.path.exists(str(candidate)):
                return FileResponse(str(candidate))
        reports = job.result.get("report_paths") or {}
        for candidate in reports.values():
            if candidate and os.path.exists(str(candidate)):
                return FileResponse(str(candidate))
        directory = Path(studio.output_root) / job_id
        for candidate in sorted(directory.glob("*.html")):
            return FileResponse(str(candidate))
        raise HTTPException(status_code=404, detail="This run produced no HTML report.")

    @app.get("/api/runs/{job_id}/artifacts")
    def list_artifacts(job_id: str) -> Dict[str, Any]:
        directory = Path(studio.output_root) / job_id
        if not directory.exists():
            return {"job_id": job_id, "artifacts": []}
        artifacts = [
            {
                "name": path.name,
                "url": "/artifacts/%s/%s" % (job_id, path.name),
                "bytes": path.stat().st_size,
            }
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        ]
        return {"job_id": job_id, "artifacts": artifacts}

    Path(studio.output_root).mkdir(parents=True, exist_ok=True)
    app.mount("/artifacts", StaticFiles(directory=studio.output_root), name="artifacts")
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="studio")

    app.state.studio = studio
    return app
