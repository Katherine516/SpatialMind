from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ToolCallSpec:
    tool_name: str
    params: Dict[str, object] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)

    def dependency_keys(self) -> List[str]:
        """Return the normalized dependency list used by MVP executors."""
        keys = []
        for key in list(self.depends_on) + list(self.requires):
            if key and key not in keys:
                keys.append(key)
        return keys


@dataclass
class ExecutionPlan:
    steps: List[ToolCallSpec]
    reasoning: str = ""
    clarification_needed: bool = False
    clarification_question: Optional[str] = None


@dataclass
class NoAnalysisResponse:
    blocking_reasons: List[str]
    recommended_next_step: str
    query: str = ""
    dataset_id: str = ""
