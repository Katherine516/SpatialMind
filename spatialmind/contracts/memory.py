from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional


@dataclass
class MemoryItem:
    category: Literal["raw_result", "validated_finding", "user_prior", "user_correction", "failed_run", "speculative_note"]
    content: str
    confidence: float
    source: Literal["tool_run", "user_explicit", "correction_inferred", "replicate_validated"]
    run_id: Optional[str] = None
    validation_status: Literal["unvalidated", "user_confirmed", "replicate_confirmed", "contradicted"] = "unvalidated"
    expiration_policy: Literal["never", "30d", "90d", "14d", "decay"] = "90d"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        if self.expiration_policy == "never":
            return False
        days = {"14d": 14, "30d": 30, "90d": 90, "decay": 90}[self.expiration_policy]
        return (now or datetime.now(timezone.utc)) > self.created_at + timedelta(days=days)

    def is_citable(self, now: Optional[datetime] = None) -> bool:
        if self.category in {"speculative_note", "failed_run"}:
            return False
        if self.validation_status == "contradicted":
            return False
        return not self.is_expired(now=now)
