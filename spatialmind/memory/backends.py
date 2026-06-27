import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


@dataclass
class SessionContext:
    session_id: str
    dataset_id: str
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    loaded_sdata_key: str = ""
    prior_tool_calls: List[Dict[str, object]] = field(default_factory=list)
    user_corrections: List[str] = field(default_factory=list)


@dataclass
class AnalysisRecord:
    id: str
    dataset_id: str
    query: str
    tools_used: List[str]
    key_findings: str
    result_path: str
    timestamp: str
    tags: List[str] = field(default_factory=list)


class PriorType(str, Enum):
    CELL_TYPE_ALIAS = "cell_type_alias"
    TISSUE_CONTEXT = "tissue_context"
    PREFERRED_TOOL = "preferred_tool"
    KNOWN_ARTIFACT = "known_artifact"
    BIOLOGY_NOTE = "biology_note"


class PriorSource(str, Enum):
    USER_EXPLICIT = "user_explicit"
    CORRECTION_INFERRED = "correction_inferred"


@dataclass
class UserPrior:
    user_id: str
    prior_type: str
    key: str
    value: str
    confidence: float
    source: str
    updated_at: str


class SessionMemory:
    """JSON-backed stand-in for the planned Redis session memory."""

    def __init__(self, root: str = ".spatialmind/sessions") -> None:
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def get(self, session_id: str) -> Optional[SessionContext]:
        path = self._path(session_id)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return SessionContext(**payload)

    def upsert(self, context: SessionContext) -> None:
        with open(self._path(context.session_id), "w", encoding="utf-8") as handle:
            json.dump(asdict(context), handle, indent=2, sort_keys=True)

    def append_message(self, session_id: str, dataset_id: str, role: str, content: str) -> SessionContext:
        context = self.get(session_id) or SessionContext(session_id=session_id, dataset_id=dataset_id)
        context.conversation_history.append({"role": role, "content": content})
        self.upsert(context)
        return context

    def _path(self, session_id: str) -> str:
        return os.path.join(self.root, "%s.json" % session_id)


class LongTermMemory:
    """JSON-backed stand-in for the planned ChromaDB analysis memory."""

    def __init__(self, root: str = ".spatialmind") -> None:
        self.root = root
        os.makedirs(self.root, exist_ok=True)
        self.path = os.path.join(self.root, "analysis_records.json")

    def store(self, dataset_id: str, query: str, tools_used: List[str], key_findings: str, result_path: str) -> AnalysisRecord:
        record = AnalysisRecord(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            query=query,
            tools_used=tools_used,
            key_findings=key_findings,
            result_path=result_path,
            timestamp=datetime.now(timezone.utc).isoformat(),
            tags=_extract_tags(query + " " + key_findings),
        )
        records = self._load_records()
        records.append(record)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump([asdict(item) for item in records], handle, indent=2, sort_keys=True)
        return record

    def search(self, query: str, dataset_id: str = "", limit: int = 5) -> List[AnalysisRecord]:
        terms = {term.lower().strip(".,;:") for term in query.split() if len(term) > 3}
        scored = []
        for record in self._load_records():
            haystack = " ".join([record.query, record.key_findings, " ".join(record.tags)]).lower()
            score = sum(1 for term in terms if term in haystack)
            if dataset_id and dataset_id == record.dataset_id:
                score += 3
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:limit]]

    def _load_records(self) -> List[AnalysisRecord]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as handle:
            return [AnalysisRecord(**item) for item in json.load(handle)]


class UserPriorStore:
    """JSON-backed stand-in for the planned PostgreSQL user prior store."""

    def __init__(self, root: str = ".spatialmind") -> None:
        self.root = root
        os.makedirs(self.root, exist_ok=True)
        self.path = os.path.join(self.root, "user_priors.json")

    def upsert(
        self,
        user_id: str,
        prior_type: PriorType,
        key: str,
        value: str,
        confidence: float = 1.0,
        source: PriorSource = PriorSource.USER_EXPLICIT,
    ) -> UserPrior:
        priors = self._load()
        kept = [
            prior
            for prior in priors
            if not (prior.user_id == user_id and prior.prior_type == prior_type.value and prior.key == key)
        ]
        prior = UserPrior(
            user_id=user_id,
            prior_type=prior_type.value,
            key=key,
            value=value,
            confidence=max(0.0, min(1.0, confidence)),
            source=source.value,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        kept.append(prior)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump([asdict(item) for item in kept], handle, indent=2, sort_keys=True)
        return prior

    def search(self, user_id: str, query: str, limit: int = 5) -> List[UserPrior]:
        terms = {term.lower().strip(".,;:") for term in query.split() if len(term) > 2}
        scored = []
        for prior in self._load():
            if prior.user_id != user_id:
                continue
            haystack = " ".join([prior.key, prior.value, prior.prior_type]).lower()
            score = sum(1 for term in terms if term in haystack) + prior.confidence
            if score > prior.confidence:
                scored.append((score, prior))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [prior for _, prior in scored[:limit]]

    def _load(self) -> List[UserPrior]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as handle:
            return [UserPrior(**item) for item in json.load(handle)]


class MemoryLayer:
    """Simple JSON memory that can later be replaced by Redis and a vector DB."""

    def __init__(self, root: str = ".spatialmind") -> None:
        self.root = root
        os.makedirs(self.root, exist_ok=True)
        self.path = os.path.join(self.root, "runs.json")

    def recall(self, prompt: str, sample_id: str) -> List[Dict[str, object]]:
        runs = self._load()
        terms = {term.lower() for term in prompt.split() if len(term) > 3}
        scored = []
        for run in runs:
            haystack = " ".join(
                [
                    str(run.get("prompt", "")),
                    str(run.get("sample_id", "")),
                    str(run.get("summary", "")),
                ]
            ).lower()
            score = sum(1 for term in terms if term in haystack)
            if sample_id and run.get("sample_id") == sample_id:
                score += 3
            if score:
                scored.append((score, run))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [run for _, run in scored[:3]]

    def remember(self, run_id: str, sample_id: str, prompt: str, summary: str, report_path: str) -> None:
        runs = self._load()
        runs.append(
            {
                "run_id": run_id,
                "sample_id": sample_id,
                "prompt": prompt,
                "summary": summary,
                "report_path": report_path,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(runs, handle, indent=2, sort_keys=True)

    def _load(self) -> List[Dict[str, object]]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)


def _extract_tags(text: str) -> List[str]:
    tags = []
    lowered = text.lower()
    for tag in ["cd8", "tumor", "macrophage", "endothelial", "stroma", "colocalization", "differential", "trajectory"]:
        if tag in lowered:
            tags.append(tag)
    return tags
