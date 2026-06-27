import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from ..agent import SpatialAgent
from ..agent.loop import AgentResponse


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
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None


class BatchEngine:
    """Synchronous local scaffold for the v2 Celery batch engine."""

    def __init__(self, agent: Optional[SpatialAgent] = None, max_concurrent: int = 8) -> None:
        self.agent = agent or SpatialAgent()
        self.max_concurrent = max_concurrent
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
        job.comparison_result = {
            "status": "registered_scaffold",
            "successful_samples": len(job.results),
            "failed_samples": len(job.failed_samples),
        }
        job.completed_at = datetime.now(timezone.utc).isoformat()
