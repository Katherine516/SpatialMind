"""What a user can tell the agent about a dataset, and what it may change.

A researcher knows things the files do not carry: that a block sat in a drawer
for three years, that they care about immune infiltration, that they expect
tumour cells in the upper third. Refusing that is wasteful. Accepting it
carelessly is worse, because free text is the obvious way around a gate whose
whole purpose is to refuse unverified assertions -- a user writes "this section
contains abundant malignant cells" and, if that reaches any evidential path, the
review requirement has been bypassed with prose.

So context is typed rather than free-form, and every field is classified by what
it is allowed to influence:

    INTENT      what the user wants to know. Steers planning. No evidential
                weight whatsoever.
    SPECIMEN    checkable facts about handling, not about biology. Appears as a
                report caveat, attributed to whoever wrote it.
    EXPECTATION what the user believes is in the tissue. Orders review only --
                which cells a reviewer is shown first. Never a label, never
                evidence, never visible to the gate or to claim scoring.

The rule that makes this safe: **context can change what the agent looks at
first and what caveats it prints; it can never change what the agent believes.**
Nothing here is read by `gatekeeper`, `pilot_gate` or `score_claim_reliability`,
and a test asserts that.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

CONTEXT_FILENAME = "dataset_context.json"

# Which influence each field is permitted. Kept beside the fields rather than in
# prose so a reviewer can see the classification without reading this module.
FIELD_INFLUENCE = {
    "question": "intent",
    "focus_genes": "intent",
    "tissue": "specimen",
    "condition": "specimen",
    "fixation": "specimen",
    "handling_notes": "specimen",
    "expected_cell_types": "expectation",
    "known_artifacts": "expectation",
}


@dataclass
class DatasetContext:
    """User-supplied context for one dataset. Every field is optional."""

    # --- intent: steers planning, carries no evidence ---
    question: str = ""
    focus_genes: List[str] = field(default_factory=list)

    # --- specimen: checkable handling facts, become attributed caveats ---
    tissue: str = ""
    condition: str = ""
    fixation: str = ""
    handling_notes: str = ""

    # --- expectation: orders review, never becomes a label ---
    expected_cell_types: List[str] = field(default_factory=list)
    known_artifacts: str = ""

    # --- attribution: unsigned context is anonymous hearsay ---
    author: str = ""
    recorded_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def is_empty(self) -> bool:
        return not any(
            getattr(self, name) for name in FIELD_INFLUENCE
        )

    def caveats(self) -> List[str]:
        """Report caveats from the specimen fields, always attributed.

        Only specimen facts become caveats. An expectation must never read as a
        finding, so it is deliberately excluded here even though it would make
        the report look better informed.
        """
        who = self.author.strip() or "an unnamed submitter"
        lines: List[str] = []
        specimen = [
            ("tissue", "Tissue recorded by the submitter: %s."),
            ("condition", "Condition recorded by the submitter: %s."),
            ("fixation", "Fixation recorded by the submitter: %s."),
            ("handling_notes", "Handling note from the submitter: %s."),
        ]
        for name, template in specimen:
            value = str(getattr(self, name) or "").strip()
            if value:
                lines.append((template % value) + " Supplied by %s and not independently verified." % who)
        return lines

    def review_priorities(self) -> List[str]:
        """Cell types the reviewer asked to see first. Ordering only."""
        return [str(name).strip() for name in self.expected_cell_types if str(name).strip()]

    def planning_hints(self) -> Dict[str, Any]:
        """Intent fields a planner may read. Contains no assertion about biology."""
        return {
            "question": self.question.strip(),
            "focus_genes": [str(g).strip() for g in self.focus_genes if str(g).strip()],
        }

    def attributed_notes(self) -> List[str]:
        """Lines safe to attach to `SpatialDataset.notes`.

        Attribution is not decoration. A note that reads "FFPE, degraded" beside
        the agent's own processing steps is indistinguishable from something the
        pipeline measured; the same line naming its author is not.
        """
        notes = list(self.caveats())
        expectations = self.review_priorities()
        if expectations:
            notes.append(
                "Submitter expects these cell types: %s. This is an expectation used to order "
                "review, not evidence, and no label follows from it."
                % ", ".join(expectations)
            )
        if self.known_artifacts.strip():
            notes.append(
                "Submitter flagged possible artifacts: %s. Treated as a review hint only."
                % self.known_artifacts.strip()
            )
        return notes


def context_path(dataset_path: str) -> Path:
    root = Path(dataset_path)
    if str(root).lower().endswith(".xenium"):
        root = root.parent
    return root / CONTEXT_FILENAME


def load_context(dataset_path: str) -> DatasetContext:
    """Read the context beside a dataset. A missing or broken file is empty context."""
    path = context_path(dataset_path)
    if not path.exists():
        return DatasetContext()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        # Unreadable context must not stop an analysis; it just supplies nothing.
        return DatasetContext()
    known = {f for f in DatasetContext().to_dict()}
    return DatasetContext(**{k: v for k, v in payload.items() if k in known})


def save_context(dataset_path: str, context: DatasetContext) -> Path:
    path = context_path(dataset_path)
    context.recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context.to_dict(), indent=2), encoding="utf-8")
    return path


def clear_context(dataset_path: str) -> bool:
    path = context_path(dataset_path)
    if path.exists():
        path.unlink()
        return True
    return False


def apply_to_dataset(dataset, dataset_path: str) -> DatasetContext:
    """Attach context to a loaded dataset as attributed notes.

    Stored under its own metadata key rather than merged into anything the
    pipeline computes, so no downstream reader can mistake it for a measurement.
    """
    context = load_context(dataset_path)
    if context.is_empty:
        return context
    dataset.notes.extend(context.attributed_notes())
    dataset.metadata["user_context"] = context.to_dict()
    dataset.metadata["user_context_influence"] = dict(FIELD_INFLUENCE)
    return context
