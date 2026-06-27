from dataclasses import dataclass, field
from typing import Dict


@dataclass
class MethodCitation:
    method_name: str
    paper_citation: str
    documentation_url: str
    default_params: Dict[str, object] = field(default_factory=dict)
    software_version: str = ""
