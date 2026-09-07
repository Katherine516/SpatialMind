"""Background execution for the Studio.

Analysis takes minutes -- 72 seconds for the descriptive lane on a full section,
longer with permutations -- so nothing runs inside a request. Jobs run on a
worker thread and the UI polls. One job runs at a time per process: two Scanpy
pipelines on the same machine contend for the same cores and finish no sooner.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable, Dict, List, Optional
import traceback
import uuid

STATES = ("queued", "running", "succeeded", "failed", "cancelled")


@dataclass
class Job:
    job_id: str
    kind: str
    label: str
    dataset_id: str
    dataset_path: str
    params: Dict[str, Any] = field(default_factory=dict)
    state: str = "queued"
    progress: str = "Queued."
    steps_done: int = 0
    steps_total: int = 0
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    result: Optional[Dict[str, Any]] = None
    error: str = ""
    log: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "label": self.label,
            "dataset_id": self.dataset_id,
            "dataset_path": self.dataset_path,
            "params": self.params,
            "state": self.state,
            "progress": self.progress,
            "steps_done": self.steps_done,
            "steps_total": self.steps_total,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "log": self.log[-40:],
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobRunner:
    def __init__(self, max_history: int = 50) -> None:
        self._jobs: Dict[str, Job] = {}
        self._order: List[str] = []
        self._lock = Lock()
        self._max_history = max_history
        self._active: Optional[str] = None

    def submit(self, kind: str, label: str, dataset_id: str, dataset_path: str,
               params: Dict[str, Any], work: Callable[[Job], Dict[str, Any]]) -> Job:
        with self._lock:
            if self._active is not None:
                active = self._jobs.get(self._active)
                if active is not None and active.state in {"queued", "running"}:
                    raise RuntimeError(
                        "A job is already running (%s). Wait for it to finish or cancel it." % active.label
                    )
            job = Job(
                job_id="job_%s" % uuid.uuid4().hex[:10],
                kind=kind,
                label=label,
                dataset_id=dataset_id,
                dataset_path=dataset_path,
                params=params,
                created_at=_now(),
            )
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            while len(self._order) > self._max_history:
                self._jobs.pop(self._order.pop(0), None)
            self._active = job.job_id

        thread = Thread(target=self._run, args=(job, work), name=job.job_id, daemon=True)
        thread.start()
        return job

    def _run(self, job: Job, work: Callable[[Job], Dict[str, Any]]) -> None:
        job.state = "running"
        job.started_at = _now()
        job.progress = "Starting."
        try:
            job.result = work(job)
            job.state = "succeeded"
            job.progress = "Done."
        except Exception as exc:  # surfaced to the UI verbatim; the trace goes to the log
            job.state = "failed"
            job.error = "%s: %s" % (type(exc).__name__, exc)
            job.progress = "Failed."
            job.log.append(traceback.format_exc())
        finally:
            job.finished_at = _now()
            with self._lock:
                if self._active == job.job_id:
                    self._active = None

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list(self) -> List[Job]:
        return [self._jobs[job_id] for job_id in reversed(self._order) if job_id in self._jobs]

    def active(self) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(self._active) if self._active else None


def step(job: Job, message: str, done: Optional[int] = None) -> None:
    job.progress = message
    if done is not None:
        job.steps_done = done
    job.log.append("%s  %s" % (_now(), message))
