from dataclasses import dataclass, field
from typing import Dict, List, Literal


ReadinessStatus = Literal["ready", "blocked", "partial"]


@dataclass
class WorkflowReadiness:
    workflow: str
    status: ReadinessStatus
    reason: str

    @property
    def ready(self) -> bool:
        return self.status == "ready"


@dataclass
class DatasetReadinessReport:
    sample_id: str
    modality: str
    workflows: List[WorkflowReadiness]
    warnings: List[str] = field(default_factory=list)
    qc_passed: bool = True

    def workflow_status(self, workflow: str) -> WorkflowReadiness:
        for item in self.workflows:
            if item.workflow == workflow:
                return item
        return WorkflowReadiness(workflow=workflow, status="blocked", reason="Workflow is not recognized by readiness policy.")

    def blocked_workflows(self) -> List[WorkflowReadiness]:
        return [item for item in self.workflows if item.status == "blocked"]

    def as_dict(self) -> Dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "modality": self.modality,
            "qc_passed": self.qc_passed,
            "warnings": list(self.warnings),
            "workflows": [item.__dict__ for item in self.workflows],
        }


@dataclass
class IngestionReport:
    sample_id: str
    format_detected: str
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
