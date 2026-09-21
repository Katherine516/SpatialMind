import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from ..agent import SpatialAgent
from ..agent.loop import AgentResponse
from ..ingestion import infer_data_type


class BatchStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class BatchJob:
    job_id: str
    query: str
    dataset_ids: List[str]
    status: BatchStatus
    results: Dict[str, AgentResponse] = field(default_factory=dict)
    failed_samples: Dict[str, str] = field(default_factory=dict)
    comparison_result: Optional[dict] = None
    batch_report_path: Optional[str] = None
    # Named in the job so an HTTP caller sees what executed it, rather than
    # inferring a distributed queue from the endpoint's shape.
    engine: str = "synchronous_in_process"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None


class BatchEngine:
    """Synchronous, in-process fan-out over datasets. Not the v2 Celery engine.

    Exposed at `POST /batch/jobs`, which made three things untrue at once: the
    job reported `COMPLETE` when its cross-sample comparison had never been
    implemented, `max_concurrent` named a concurrency this loop does not have,
    and -- unlike `POST /runs` -- a Xenium bundle went to the legacy agent
    instead of `run_pilot`, so the same path answered the same question two
    different ways depending on which endpoint you asked.

    The routing and the status are fixed here. What remains genuinely scaffolded
    is the cross-sample comparison, which now says so in its own field instead of
    under a `COMPLETE` job.
    """

    def __init__(self, agent: Optional[SpatialAgent] = None) -> None:
        self.agent = agent or SpatialAgent()
        self._jobs: Dict[str, BatchJob] = {}

    def submit(self, query: str, dataset_ids: List[str]) -> BatchJob:
        job = BatchJob(job_id=str(uuid.uuid4()), query=query, dataset_ids=list(dataset_ids), status=BatchStatus.PENDING)
        self._jobs[job.job_id] = job
        self._run(job)
        return job

    def get(self, job_id: str) -> BatchJob:
        if job_id not in self._jobs:
            raise KeyError("Unknown batch job: %s" % job_id)
        return self._jobs[job_id]

    def _run(self, job: BatchJob) -> None:
        job.status = BatchStatus.RUNNING
        for dataset_id in job.dataset_ids:
            # `POST /runs` routes a Xenium bundle to `run_pilot`; this path did
            # not, so the same section answered the same question two ways
            # depending on the endpoint -- and the batch answer came from the v1
            # stack, without the validated plan, the claim ledger or the report.
            # Refusing is the honest option here: a batch job has nowhere to put
            # a pilot's artifacts, so it cannot route to `run_pilot` instead.
            if infer_data_type(dataset_id) in {"xenium_directory", "xenium_experiment_file"}:
                job.failed_samples[dataset_id] = (
                    "Xenium bundles are not run through the batch engine: it would use the legacy "
                    "path rather than the validated pilot, and produce no report. Use POST /runs "
                    "(or `run_pilot`) per section."
                )
                continue
            try:
                job.results[dataset_id] = self.agent.run(job.query, dataset_id=dataset_id, session_id=job.job_id)
            except Exception as exc:
                job.failed_samples[dataset_id] = str(exc)
        if job.results and job.failed_samples:
            job.status = BatchStatus.PARTIAL
        elif job.failed_samples:
            job.status = BatchStatus.FAILED
        else:
            job.status = BatchStatus.COMPLETE
        # A per-dataset fan-out is not a comparison. Saying so in a field called
        # `comparison_result` on a job marked COMPLETE reads as a comparison that
        # ran; the caller asked to compare datasets and got n independent runs.
        job.comparison_result = {
            "status": "not_implemented",
            "reason": (
                "Cross-sample comparison is not implemented. This job ran each dataset "
                "independently and compared nothing. Condition-level differences across "
                "samples also require biological replication -- see "
                "`spatialmind.methods.replication`."
            ),
            "successful_samples": len(job.results),
            "failed_samples": len(job.failed_samples),
        }
        job.engine = "synchronous_in_process"
        job.completed_at = datetime.now(timezone.utc).isoformat()
