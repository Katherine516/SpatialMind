from dataclasses import dataclass, field
from typing import List, Literal

from .claims import BiologicalClaim
from .tool_io import ToolResult


@dataclass
class VizArtifact:
    artifact_id: str
    viz_type: str
    caption: str
    data_source: str
    png_path: str = ""
    html_path: str = ""
    format: Literal["svg", "png", "html", "pdf"] = "html"


@dataclass
class AgentResponse:
    session_id: str
    query: str
    tool_trace: List[ToolResult]
    interpretation: str
    claims: List[BiologicalClaim] = field(default_factory=list)
    viz_artifacts: List[VizArtifact] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
