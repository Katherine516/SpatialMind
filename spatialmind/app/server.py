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
import re
import time

from ..ingestion import (
    apply_best_available_labels,
    apply_best_available_regions,
    load_xenium,
)
from ..pilot import run_pilot
from ..storage import StorageLayer
from ..tools import build_default_registry
from ..schemas import expression_feature_names
from ..viz.tables import write_result_tables
from .. import dataset_context, gatekeeper
from . import config
from . import gate as gate_module
from . import exports, library, plan_report, planner, resources, review, uploads, workflow
from .catalog import DEFAULT_DISPLAY_CELLS, IndexCache, discover_datasets, panel_genes
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




def _run_matches(run_dir: Path, dataset_path: str) -> bool:
    """Did this run analyse this dataset?

    Matched through the run's own validation record rather than by taking any
    run in the output root: sizing one section's review against another
    section's clustering would be worse than reporting none.
    """
    import json

    for name in ("pilot_validation.json", "plan_results.json"):
        record = run_dir / name
        if not record.exists():
            continue
        try:
            with open(record, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        ran_on = str(payload.get("dataset_path") or
                     (payload.get("dataset") or {}).get("path") or "")
        if not ran_on:
            continue
        try:
            return Path(ran_on).resolve() == Path(dataset_path).resolve()
        except OSError:
            return False
    return False


def _slug(text: str) -> str:
    """A filename a user can find again, from a report title."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "report")).strip("_")
    return (cleaned or "report")[:60]



def _human_bytes(count: int) -> str:
    value = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return "%.0f %s" % (value, unit)
        value /= 1024
    return "%.0f GB" % value


def _figure_title(filename: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
    stem = re.sub(r"^(descriptive|review|validated)_", "", stem)
    return stem.replace("_", " ").strip().capitalize() or filename


class Studio:
    """Holds the session state a local single-user app needs: what datasets
    exist, their cell indexes, and the one job that may be running."""

    def __init__(self, data_root: Optional[str] = None, output_root: Optional[str] = None) -> None:
        self.data_root = str(Path(data_root or config.default_data_root()).expanduser().resolve())
        self.output_root = str(Path(output_root or config.default_output_root()).expanduser().resolve())
        self.indexes = IndexCache()
        self.jobs = JobRunner()
        self.reports = library.ReportLibrary(self.output_root)
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
        tool_results = []
        started = time.time()
        for position, spec in enumerate(plan):
            step(job, "Running %s (%d of %d)." % (spec.tool_name, position + 1, len(plan)), position + 2)
            tool_started = time.time()
            result = registry.get(spec.tool_name).run(dataset, dict(spec.params))
            tool_results.append(result)
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
            "features_loaded": len(expression_feature_names(dataset)),
            "scope": "full_section" if not max_records else "sample",
            "wall_seconds": round(time.time() - started, 2),
            "run_record_path": record.run_record_path,
            "run_id": job.job_id,
            "title": job.label,
            "output_dir": str(output_dir),
        }

        # A run that leaves only JSON behind is not a finished piece of work. The
        # tables are what a collaborator opens, and the report is what they read
        # first; neither existed for a plan run, so the Studio could complete an
        # analysis and hand back nothing anyone could send on.
        step(job, "Writing result tables.", len(plan) + 2)
        try:
            payload["result_tables"] = write_result_tables(
                payload, dataset, output_dir, run_id=job.job_id, results=tool_results)
        except Exception as exc:  # a table failure must not lose a completed run
            payload["result_tables"] = {"status": "failed", "error": str(exc)}
            job.log.append("Result tables failed: %s" % exc)

        step(job, "Drawing figures.", len(plan) + 2)
        try:
            payload["figures"] = plan_report.write_figures(dataset, payload, output_dir)
        except Exception as exc:
            payload["figures"] = []
            job.log.append("Figures failed: %s" % exc)

        step(job, "Writing the report.", len(plan) + 2)
        try:
            gate = studio.gate(dataset_id) if entry.reviewable else None
        except Exception:
            gate = None
        try:
            payload["report_paths"] = plan_report.write(payload, output_dir, gate=gate)
        except Exception as exc:
            payload["report_paths"] = {}
            job.log.append("Report failed: %s" % exc)

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
            min_label_coverage=float(options.get("min_label_coverage", gatekeeper.DEFAULT_MIN_LABEL_COVERAGE)),
            min_region_coverage=float(options.get("min_region_coverage", gatekeeper.DEFAULT_MIN_REGION_COVERAGE)),
            allow_single_region=bool(options.get("allow_single_region", False)),
            report_format=str(options.get("report_format", "html")),
            readiness_only=readiness_only,
            require_complete_section=True,
            review_max_records=int(options.get("review_max_records") or 0),
            acknowledge_low_coverage=bool(options.get("acknowledge_low_coverage", False)),
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
        from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
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

    class ContextRequest(BaseModel):
        question: str = ""
        focus_genes: List[str] = Field(default_factory=list)
        tissue: str = ""
        condition: str = ""
        fixation: str = ""
        handling_notes: str = ""
        expected_cell_types: List[str] = Field(default_factory=list)
        known_artifacts: str = ""
        author: str = ""

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

        # `scope` is the human sentence for the UI; `scope_key` is the stable
        # token written to every row this assignment touches, so one reviewer
        # decision stays countable as one decision after the fact.
        if request.cell_ids:
            cell_ids = request.cell_ids
            scope = "%d cells" % len(cell_ids)
            scope_key = "cells:%d" % len(cell_ids)
        elif request.cluster is not None:
            cell_ids = index.ids_in_cluster(request.cluster)
            scope = "cluster %s" % request.cluster
            scope_key = "cluster:%s" % request.cluster
        elif request.bounds:
            b = request.bounds
            cell_ids = index.ids_in_rect(b.get("x0", 0.0), b.get("y0", 0.0), b.get("x1", 0.0), b.get("y1", 0.0))
            scope = "rectangle"
            scope_key = "rect:%.0f,%.0f,%.0f,%.0f" % (
                b.get("x0", 0.0), b.get("y0", 0.0), b.get("x1", 0.0), b.get("y1", 0.0)
            )
        else:
            raise HTTPException(status_code=400, detail="Provide cluster, bounds, or cell_ids.")

        if not cell_ids:
            raise HTTPException(status_code=400, detail="That selection (%s) contains no cells." % scope)
        try:
            result = review.assign(
                entry.path, request.kind, cell_ids, request.value,
                confidence=request.confidence, notes=request.notes, scope=scope_key,
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

    @app.get("/api/datasets/{dataset_id}/context")
    def get_context(dataset_id: str) -> Dict[str, Any]:
        """What the submitter told us about this dataset, and what it may affect."""
        entry = _entry_or_404(dataset_id)
        context = dataset_context.load_context(entry.path)
        return jsonable({
            "context": context.to_dict(),
            "influence": dataset_context.FIELD_INFLUENCE,
            "is_empty": context.is_empty,
            "caveats": context.caveats(),
            "review_priorities": context.review_priorities(),
        })

    @app.post("/api/datasets/{dataset_id}/context")
    def set_context(dataset_id: str, request: ContextRequest) -> Dict[str, Any]:
        entry = _entry_or_404(dataset_id)
        fields = request.model_dump() if hasattr(request, "model_dump") else request.dict()
        context = dataset_context.DatasetContext(**fields)
        path = dataset_context.save_context(entry.path, context)
        # The gate is recomputed and returned so the caller can see for itself
        # that nothing they wrote moved it.
        gate = studio.gate(dataset_id) if entry.reviewable else None
        return jsonable({
            "context": context.to_dict(),
            "saved_to": str(path),
            "caveats": context.caveats(),
            "review_priorities": context.review_priorities(),
            "gate": gate,
        })

    @app.delete("/api/datasets/{dataset_id}/context")
    def delete_context(dataset_id: str) -> Dict[str, Any]:
        entry = _entry_or_404(dataset_id)
        return {"cleared": dataset_context.clear_context(entry.path)}

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
            # A name this build does not have used to be dropped in silence, and
            # the job then reported `succeeded` with no error and no results.
            unknown = planner.unknown_tools(request.tools)
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail="No tool named %s in this build. Nothing was run."
                           % ", ".join("`%s`" % name for name in unknown))
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

    # ---------------------------------------------------------------- intake

    @app.post("/api/uploads")
    async def upload(files: List[UploadFile] = File(...),
                     name: str = Form(""),
                     paths: str = Form("")) -> Dict[str, Any]:
        """Store an uploaded file or folder, then say what the app made of it.

        `paths` carries the browser's relative paths for a folder upload, in the
        same order as `files`. A Xenium bundle is only a bundle when its files
        keep their names beside each other.
        """
        relatives = [item for item in (paths or "").split("\n") if item.strip()]
        payloads: List[Any] = []
        for index, item in enumerate(files):
            relative = relatives[index] if index < len(relatives) else (item.filename or "file")
            payloads.append((relative, await item.read()))
        if not payloads:
            raise HTTPException(status_code=400, detail="No files were uploaded.")

        label = name.strip() or Path(payloads[0][0]).parts[0] or "upload"
        stored = uploads.store_files(studio.data_root, label, payloads)
        if stored["status"] != "stored":
            raise HTTPException(status_code=400, detail=stored.get("reason", "Upload failed."))
        stored["intake"] = uploads.describe(stored["path"])
        stored["datasets"] = studio.refresh_datasets()
        return jsonable(stored)

    class LinkRequest(BaseModel):
        path: str

    @app.post("/api/uploads/link")
    def link(request: LinkRequest) -> Dict[str, Any]:
        """Register a folder already on this machine instead of copying it.

        A Xenium bundle is routinely 10 GB. Pushing that through a browser form
        to land it on the same disk costs minutes and twice the space.
        """
        linked = uploads.link_folder(request.path)
        if linked["status"] != "linked":
            raise HTTPException(status_code=400, detail=linked.get("reason", "Cannot use that path."))
        linked["intake"] = uploads.describe(linked["path"])
        inside_root = True
        try:
            Path(linked["path"]).relative_to(Path(studio.data_root))
        except ValueError:
            inside_root = False
        linked["in_data_root"] = inside_root
        linked["note"] = ("" if inside_root else
                          "That folder is outside the current data root, so it will not appear in "
                          "the dataset list until the data root is changed to a parent of it.")
        linked["datasets"] = studio.refresh_datasets()
        return jsonable(linked)

    @app.get("/api/datasets/{dataset_id}/sizing")
    def dataset_sizing(dataset_id: str) -> Dict[str, Any]:
        """How many decisions would open the gate on this section.

        The Readiness screen says what is missing. It did not say how much work
        the missing thing is, and the honest answer is small enough to change
        whether someone starts: the gate needs 70% coverage, a reviewer labels
        by cluster, and on the healthy brain section four cluster calls and six
        region calls reach it.
        """
        from ..review import sizing as review_sizing

        entry = _entry_or_404(dataset_id)
        if not entry.reviewable:
            return {"dataset_id": dataset_id, "sizable": False,
                    "reason": "Only Xenium bundles are gated."}

        # A descriptive run's own clustering beats the bundle's when there is
        # one: it is what carries the marker evidence a cluster call is made on.
        # Newest matching run, not the last one alphabetically. The output root
        # accumulates runs, several of them on the same section at different
        # sample sizes, and picking by name sized the glioblastoma review
        # against an older, smaller run: 4 decisions where the current full
        # section needs 5.
        run_dir = ""
        newest = -1.0
        root = Path(studio.output_root)
        if root.exists():
            # Both shapes: a pilot writes per-tool files, a plan run writes one
            # `plan_results.json`. Globbing only the first meant the app could
            # not size against a clustering it had just produced itself.
            for pattern in ("*/descriptive_qc_and_cluster.json", "*/plan_results.json"):
                for candidate in sorted(root.glob(pattern)):
                    if not _run_matches(candidate.parent, entry.path):
                        continue
                    stamp = candidate.stat().st_mtime
                    if stamp > newest:
                        run_dir, newest = str(candidate.parent), stamp
        clusters = review_sizing.read_run_clusters(run_dir) if run_dir else {}
        markers = review_sizing.read_run_markers(run_dir) if run_dir else {}
        source = "this dataset's descriptive run"
        if not clusters:
            clusters = studio.index(dataset_id).cluster_sizes()
            markers = {}
            source = "the bundle's own 10x clusters"

        label_plan = review_sizing.size_label_review(clusters)
        region_plan = None
        if run_dir:
            candidate = Path(run_dir) / "cell_regions_candidate.csv"
            if candidate.exists():
                region_plan = review_sizing.size_region_review(
                    review_sizing.read_candidate_regions(str(candidate)))

        summary = review_sizing.summarise(
            entry.display_name, label_plan, region_plan,
            markers=markers or None,
            tumour=review_sizing.tumour_context(entry.path))
        summary["sizable"] = True
        summary["cluster_source"] = source
        summary["run_dir"] = run_dir
        return jsonable(summary)

    # -------------------------------------------------------------- workflow

    def _facts(dataset_id: str) -> Dict[str, Any]:
        entry = _entry_or_404(dataset_id)
        if not entry.reviewable:
            return workflow.dataset_facts({"dataset": entry.to_dict()}, panel=[])
        detail = {
            "dataset": entry.to_dict(),
            "n_cells": studio.index(dataset_id).n_cells,
            "cluster_sizes": studio.index(dataset_id).cluster_sizes(),
            "gate": studio.gate(dataset_id),
        }
        return workflow.dataset_facts(detail, panel=panel_genes(entry.path))

    @app.get("/api/workflow/facts")
    def workflow_facts(dataset_id: str = Query(...)) -> Dict[str, Any]:
        facts = _facts(dataset_id)
        # The panel can be 5,000 genes on a Prime run; the UI needs the count and
        # a sample, not the whole list in every poll.
        panel = facts.get("panel") or []
        trimmed = dict(facts)
        trimmed["panel"] = panel[:400]
        trimmed["panel_size"] = len(panel)
        return jsonable(trimmed)

    @app.get("/api/workflow/questions")
    def workflow_questions(dataset_id: str = Query(...)) -> Dict[str, Any]:
        facts = _facts(dataset_id)
        return jsonable({
            "dataset_id": dataset_id,
            "gate_open": facts["gate_open"],
            "gate_status": facts["gate_status"],
            "questions": workflow.recommend_questions(facts),
        })

    class AnalyzeRequest(BaseModel):
        dataset_id: str
        text: str = ""
        # Set when the text is a suggestion the app itself offered, which
        # already knows the tools it resolves to.
        tools: List[str] = Field(default_factory=list)

    @app.post("/api/workflow/analyze")
    def workflow_analyze(request: AnalyzeRequest) -> Dict[str, Any]:
        facts = _facts(request.dataset_id)
        analysis = workflow.analyze_text(request.text, facts, tools=request.tools)
        analysis["gate_open"] = facts["gate_open"]
        return jsonable(analysis)

    class WorkflowPlanRequest(BaseModel):
        dataset_id: str
        tools: List[str] = Field(default_factory=list)
        answers: Dict[str, Any] = Field(default_factory=dict)

    @app.post("/api/workflow/plan")
    def workflow_plan(request: WorkflowPlanRequest) -> Dict[str, Any]:
        facts = _facts(request.dataset_id)
        overrides = workflow.apply_answers(request.tools, request.answers)
        described = workflow.recommend_tools(request.tools, facts["gate_open"], overrides=overrides)
        described["overrides"] = overrides
        described["gate_open"] = facts["gate_open"]
        described["blocking_reasons"] = facts["blocking_reasons"]
        return jsonable(described)

    # --------------------------------------------------------------- reports

    @app.get("/api/reports")
    def list_reports() -> Dict[str, Any]:
        return jsonable({"reports": studio.reports.scan(), "output_root": studio.output_root})

    @app.get("/api/reports/{report_id}")
    def get_report_detail(report_id: str, original: bool = Query(False)) -> Dict[str, Any]:
        described = studio.reports.get(report_id)
        if not described:
            raise HTTPException(status_code=404, detail="Unknown report: %s" % report_id)
        described["markdown"] = studio.reports.markdown(report_id, original=original)
        described["tables"] = exports.list_tables(Path(described["directory"]))
        return jsonable(described)

    class RenameRequest(BaseModel):
        title: str

    @app.post("/api/reports/{report_id}/rename")
    def rename_report(report_id: str, request: RenameRequest) -> Dict[str, Any]:
        if not studio.reports.rename(report_id, request.title):
            raise HTTPException(status_code=404, detail="Unknown report: %s" % report_id)
        return {"report_id": report_id, "title": request.title.strip()}

    class PinRequest(BaseModel):
        pinned: bool = True

    @app.post("/api/reports/{report_id}/pin")
    def pin_report(report_id: str, request: PinRequest) -> Dict[str, Any]:
        if not studio.reports.set_pinned(report_id, request.pinned):
            raise HTTPException(status_code=404, detail="Unknown report: %s" % report_id)
        return {"report_id": report_id, "pinned": request.pinned}

    class EditRequest(BaseModel):
        markdown: str

    @app.post("/api/reports/{report_id}/edit")
    def edit_report(report_id: str, request: EditRequest) -> Dict[str, Any]:
        """Save the user's version beside the run's, never over it.

        The run record stays byte-identical so replay keeps working; every
        export of an edited report says it was edited.
        """
        if not studio.reports.save_edit(report_id, request.markdown):
            raise HTTPException(status_code=404, detail="Unknown report: %s" % report_id)
        return {"report_id": report_id, "edited": True}

    @app.post("/api/reports/{report_id}/revert")
    def revert_report(report_id: str) -> Dict[str, Any]:
        if not studio.reports.revert_edit(report_id):
            raise HTTPException(status_code=404, detail="Unknown report: %s" % report_id)
        return {"report_id": report_id, "edited": False}

    @app.delete("/api/reports/{report_id}")
    def delete_report(report_id: str) -> Dict[str, Any]:
        if not studio.reports.delete(report_id):
            raise HTTPException(status_code=404, detail="Unknown report: %s" % report_id)
        return {"report_id": report_id, "deleted": True}

    EXPORT_FORMATS = {
        "docx": ("report.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "pdf": ("report.pdf", "application/pdf"),
        "txt": ("report.txt", "text/plain"),
        "md": ("report.md", "text/markdown"),
    }

    @app.get("/api/reports/{report_id}/export")
    def export_report(report_id: str, format: str = Query("docx")):
        described = studio.reports.get(report_id)
        if not described:
            raise HTTPException(status_code=404, detail="Unknown report: %s" % report_id)
        if format not in EXPORT_FORMATS:
            raise HTTPException(status_code=400, detail="format must be one of %s"
                                % ", ".join(sorted(EXPORT_FORMATS)))
        markdown = studio.reports.markdown(report_id)
        if not markdown:
            raise HTTPException(status_code=404, detail="This run produced no report text to export.")
        filename, media_type = EXPORT_FORMATS[format]
        directory = Path(described["directory"])
        target = directory / "exports" / filename
        provenance = studio.reports.provenance(report_id)
        title = described.get("title") or report_id
        try:
            if format == "docx":
                exports.write_docx(markdown, target, title=title, provenance=provenance,
                                   figure_root=directory)
            elif format == "pdf":
                exports.write_pdf(markdown, target, title=title, provenance=provenance)
            elif format == "txt":
                exports.write_text(markdown, target, provenance=provenance)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(markdown, encoding="utf-8")
        except ImportError as exc:
            raise HTTPException(status_code=501, detail="That export needs a package this build "
                                                        "does not ship: %s" % exc)
        download = "%s.%s" % (_slug(title), format)
        return FileResponse(str(target), media_type=media_type, filename=download)

    # An .xlsx of 163,920 cells x 35 columns takes ~75 seconds, nearly all of it
    # openpyxl serialising XML. Past this much source data the export becomes a
    # background task instead of a held-open request.
    SYNCHRONOUS_EXPORT_BYTES = 2 * 1024 * 1024

    def _result_tables(report_id: str, kind: str):
        described = studio.reports.get(report_id)
        if not described:
            raise HTTPException(status_code=404, detail="Unknown report: %s" % report_id)
        tables = exports.list_tables(Path(described["directory"]))
        if kind:
            tables = [table for table in tables if table["kind"] == kind]
        if not tables:
            raise HTTPException(status_code=404,
                                detail="This run wrote no result tables%s."
                                       % (" of kind '%s'" % kind if kind else ""))
        return described, tables

    def _write_results(described, tables, format: str, report_id: str):
        directory = Path(described["directory"])
        provenance = studio.reports.provenance(report_id)
        slug = _slug(described.get("title") or report_id)
        if format == "xlsx":
            target = directory / "exports" / "results.xlsx"
            exports.write_xlsx(tables, target, provenance=provenance)
            return target, "%s_results.xlsx" % slug, \
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if format == "csv":
            target = directory / "exports" / "results_csv.zip"
            exports.write_csv_bundle(tables, target, provenance=provenance)
            return target, "%s_results_csv.zip" % slug, "application/zip"
        raise HTTPException(status_code=400, detail="format must be xlsx or csv")

    class ResultsRequest(BaseModel):
        format: str = "xlsx"
        kind: str = ""

    @app.post("/api/reports/{report_id}/results")
    def start_results_export(report_id: str, request: ResultsRequest) -> Dict[str, Any]:
        """Export the numbers behind a report, in the background when it is big.

        `kind` narrows to one family -- cells, genes, regions, pairs, cell_types
        -- and empty means everything the run produced.
        """
        described, tables = _result_tables(report_id, request.kind)
        total = sum(int(table.get("bytes") or 0) for table in tables)
        if total <= SYNCHRONOUS_EXPORT_BYTES:
            target, filename, _media = _write_results(described, tables, request.format, report_id)
            return {"status": "ready", "report_id": report_id, "filename": filename,
                    "url": "/api/reports/%s/results?format=%s&kind=%s"
                           % (report_id, request.format, request.kind),
                    "bytes": target.stat().st_size}

        def work(job):
            step(job, "Reading %d result tables." % len(tables), 0)
            job.steps_total = 2
            target, filename, _media = _write_results(described, tables, request.format, report_id)
            step(job, "Wrote %s." % filename, 2)
            return {"filename": filename, "bytes": target.stat().st_size,
                    "download_url": "/api/reports/%s/results?format=%s&kind=%s"
                                    % (report_id, request.format, request.kind)}

        try:
            job = studio.jobs.submit(
                kind="export", label="Export %s (%s)" % (described.get("title") or report_id, request.format),
                dataset_id="", dataset_path=str(described["directory"]),
                params={"report_id": report_id, "format": request.format, "kind": request.kind},
                work=work, exclusive=False,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"status": "running", "job_id": job.job_id, "report_id": report_id,
                "note": "%s of tables; this runs in the background and appears under Tasks."
                        % _human_bytes(total)}

    @app.get("/api/reports/{report_id}/results")
    def export_results(report_id: str, format: str = Query("xlsx"),
                       kind: str = Query("")) -> Any:
        """Download a results export, writing it first if it is not there yet."""
        described, tables = _result_tables(report_id, kind)
        target, filename, media = _write_results(described, tables, format, report_id)
        return FileResponse(str(target), media_type=media, filename=filename)

    @app.get("/api/reports/{report_id}/table")
    def preview_table(report_id: str, name: str = Query(...),
                      limit: int = Query(200, ge=1, le=5000)) -> Dict[str, Any]:
        described = studio.reports.get(report_id)
        if not described:
            raise HTTPException(status_code=404, detail="Unknown report: %s" % report_id)
        for table in exports.list_tables(Path(described["directory"])):
            if table["name"] == name:
                header, rows, comments = exports.read_table(Path(table["path"]), limit=limit)
                return jsonable({"name": name, "header": header, "rows": rows,
                                 "provenance": comments, "truncated": len(rows) >= limit})
        raise HTTPException(status_code=404, detail="No table named %s in this run." % name)

    # --------------------------------------------------------- visualization

    FIGURE_SUFFIXES = (".png", ".svg", ".jpg", ".jpeg", ".gif")

    @app.get("/api/visualizations")
    def list_visualizations(report_id: str = Query("")) -> Dict[str, Any]:
        """Every figure any run produced, newest first.

        Interactive HTML views are listed alongside the static figures rather
        than in a separate place, because to a user they are the same thing:
        something to look at.
        """
        root = Path(studio.output_root)
        figures: List[Dict[str, Any]] = []
        directories = ([root / report_id] if report_id
                       else [d for d in sorted(root.iterdir()) if d.is_dir()] if root.exists() else [])
        for directory in directories:
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*")):
                if not path.is_file():
                    continue
                suffix = path.suffix.lower()
                interactive = suffix == ".html" and "interactive" in path.name.lower()
                if suffix not in FIGURE_SUFFIXES and not interactive:
                    continue
                figures.append({
                    "report_id": directory.name,
                    "name": path.name,
                    "title": _figure_title(path.name),
                    "url": "/artifacts/%s" % path.relative_to(root).as_posix(),
                    "kind": "interactive" if interactive else "image",
                    "bytes": path.stat().st_size,
                    "modified": path.stat().st_mtime,
                })
        figures.sort(key=lambda item: -item["modified"])
        return jsonable({"figures": figures})

    Path(studio.output_root).mkdir(parents=True, exist_ok=True)
    app.mount("/artifacts", StaticFiles(directory=studio.output_root), name="artifacts")
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="studio")

    app.state.studio = studio
    return app
