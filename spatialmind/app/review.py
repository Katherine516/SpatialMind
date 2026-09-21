"""Reading and writing the two files that clear the gate.

`expert_cell_labels.csv` and `cell_regions.csv` belong inside the Xenium bundle,
because that is where the loader looks for them and because a review that
travels with the data can be reopened anywhere. Writes here are merges, never
overwrites: a reviewer adding a second label must not erase the first, and a
table a human hand-authored outside the app has to survive contact with it.

A bundle is not always writable. Instrument output arrives from a core facility
on read-only media, on a share mounted read-only, or in an archived directory,
and the app used to meet that with an unhandled `PermissionError` naming a
temporary file -- losing the review and explaining nothing. So when the bundle
cannot be written, the table goes to a sidecar under the app's support directory
and `sidecar_paths` hands it back to the loader, which takes extra paths for
exactly this reason. The bundle stays preferred: the sidecar is a fallback that
announces itself, not a new default.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import csv
import hashlib
import os
import tempfile

from . import config
from .catalog import resolve_xenium_root

LABEL_FILENAME = "expert_cell_labels.csv"
REGION_FILENAME = "cell_regions.csv"
# `assignment_scope` records what the reviewer actually decided, not just what
# the decision covered. One click on a cluster writes thousands of rows, and
# every downstream consumer read those rows as thousands of per-cell expert
# calls -- the annotation-quality score among them. Appended to the documented
# column set rather than replacing it: readers resolve columns by name, so a
# table written before this column existed still loads.
# `reviewer_id` is the column the loader has always looked for -- it accepts
# `reviewer_id`, `reviewer`, `annotator` or `curator` -- and the one the Studio
# never wrote. A table imported from a paper carried its authorship (the
# Janesick section names `Janesick et al. 2023, Nat Commun 14:8353` on all
# 159,226 rows); a review made in this app's own screen named nobody, so a
# section could reach `validated_ready` with no record of who validated it.
# Appended to the documented column set rather than inserted, because readers
# resolve columns by name and a table written before this existed still loads.
LABEL_FIELDS = ["cell_id", "expert_label", "confidence", "notes", "assignment_scope", "reviewer_id"]
REGION_FIELDS = ["cell_id", "region", "region_confidence", "notes", "assignment_scope", "reviewer_id"]

# Used when a caller supplies nothing. Deliberately not a person's name and
# deliberately not blank: "someone using this app, unidentified" is a true
# statement about the review and a blank is not.
UNIDENTIFIED_REVIEWER = "unidentified (SpatialMind Studio)"

KINDS = {
    "labels": (LABEL_FILENAME, LABEL_FIELDS, "expert_label"),
    "regions": (REGION_FILENAME, REGION_FIELDS, "region"),
}


@dataclass
class AssignmentResult:
    kind: str
    value: str
    cells_written: int
    rows_total: int
    path: str
    distinct_values: List[str]
    # "bundle" or "app_support". A reviewer whose work went somewhere other than
    # their data folder has to be told, or they will look for it and not find it.
    location: str = "bundle"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "cells_written": self.cells_written,
            "rows_total": self.rows_total,
            "path": self.path,
            "distinct_values": self.distinct_values,
            "location": self.location,
        }


def bundle_table_path(dataset_path: str, kind: str) -> Path:
    """Where the table belongs, whether or not it can be written there."""
    return resolve_xenium_root(Path(dataset_path)) / KINDS[kind][0]


def sidecar_dir(dataset_path: str) -> Path:
    """One folder per bundle under the app's support directory.

    Keyed by the resolved bundle path so two sections with the same folder name
    -- `Section_outs` is what the instrument writes for all of them -- cannot
    read each other's review. The folder name keeps the readable part so a
    person browsing the directory can tell what they are looking at.
    """
    root = resolve_xenium_root(Path(dataset_path))
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return config.support_dir() / "review" / ("%s-%s" % (root.name[:48], digest))


def sidecar_table_path(dataset_path: str, kind: str) -> Path:
    return sidecar_dir(dataset_path) / KINDS[kind][0]


def _is_writable(directory: Path) -> bool:
    return os.access(str(directory), os.W_OK | os.X_OK)


def table_path(dataset_path: str, kind: str) -> Path:
    """The table this bundle is actually using, for reads and for writes.

    A table already in the bundle wins even when the bundle has since become
    read-only: it is the reviewed truth, and a sidecar must not silently shadow
    it. Otherwise the bundle if it can be written, and the sidecar if it cannot.
    """
    in_bundle = bundle_table_path(dataset_path, kind)
    if in_bundle.exists():
        return in_bundle
    sidecar = sidecar_table_path(dataset_path, kind)
    if sidecar.exists():
        return sidecar
    return in_bundle if _is_writable(in_bundle.parent) else sidecar


def writes_to_sidecar(dataset_path: str, kind: str) -> bool:
    return table_path(dataset_path, kind) == sidecar_table_path(dataset_path, kind)


def sidecar_paths(dataset_path: str) -> List[str]:
    """Sidecar tables that exist, for the loader's `extra_paths`.

    Without this the app would show a satisfied gate while the run that the gate
    unlocked loaded no labels at all.
    """
    found = []
    for kind in KINDS:
        path = sidecar_table_path(dataset_path, kind)
        if path.exists():
            found.append(str(path))
    return found


def read_table(dataset_path: str, kind: str) -> Dict[str, Dict[str, str]]:
    path = table_path(dataset_path, kind)
    if not path.exists():
        return {}
    rows: Dict[str, Dict[str, str]] = {}
    with open(path, "r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            cell_id = str(row.get("cell_id", "")).strip()
            if cell_id:
                rows[cell_id] = {key: str(row.get(key, "") or "") for key in KINDS[kind][1]}
    return rows


def assign(
    dataset_path: str,
    kind: str,
    cell_ids: Iterable[str],
    value: str,
    confidence: float = 0.9,
    notes: str = "",
    scope: str = "cells",
    reviewer_id: str = "",
) -> AssignmentResult:
    """Merge one assignment into the table and rewrite it atomically."""
    if kind not in KINDS:
        raise ValueError("Unknown assignment kind: %s" % kind)
    filename, fields, value_field = KINDS[kind]
    confidence_field = fields[2]
    value = str(value).strip()
    if not value:
        raise ValueError("An assignment needs a non-empty %s." % value_field)

    rows = read_table(dataset_path, kind)
    written = 0
    for cell_id in cell_ids:
        cell_id = str(cell_id).strip()
        if not cell_id:
            continue
        rows[cell_id] = {
            "cell_id": cell_id,
            value_field: value,
            confidence_field: "%.2f" % float(confidence),
            "reviewer_id": str(reviewer_id).strip() or UNIDENTIFIED_REVIEWER,
            "notes": notes or "assigned in SpatialMind Studio",
            # One scope string per assignment, identical across every row it
            # wrote, so the count of distinct scopes is the count of decisions.
            "assignment_scope": scope,
        }
        written += 1

    path = table_path(dataset_path, kind)
    _write_atomic(path, fields, rows)
    return AssignmentResult(
        kind=kind,
        value=value,
        cells_written=written,
        rows_total=len(rows),
        path=str(path),
        distinct_values=sorted({row.get(value_field, "") for row in rows.values() if row.get(value_field)}),
        location="app_support" if path == sidecar_table_path(dataset_path, kind) else "bundle",
    )


def unassign(dataset_path: str, kind: str, cell_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Drop specific cells, or delete the table when no cells are named."""
    filename, fields, _ = KINDS[kind]
    path = table_path(dataset_path, kind)
    if cell_ids is None:
        existed = path.exists()
        if existed:
            path.unlink()
        return {"kind": kind, "cleared": existed, "rows_total": 0, "path": str(path)}
    rows = read_table(dataset_path, kind)
    for cell_id in cell_ids:
        rows.pop(str(cell_id).strip(), None)
    if rows:
        _write_atomic(path, fields, rows)
    elif path.exists():
        path.unlink()
    return {"kind": kind, "cleared": False, "rows_total": len(rows), "path": str(path)}


def coverage(dataset_path: str, kind: str, known_cell_ids: Iterable[str]) -> Dict[str, Any]:
    """Coverage counts only rows whose cell id exists in this section.

    A table carrying ids from another run would otherwise inflate coverage past
    the point where the gate should have opened.
    """
    rows = read_table(dataset_path, kind)
    known = set(known_cell_ids)
    total = len(known)
    value_field = KINDS[kind][2]
    matched = [row for cell_id, row in rows.items() if cell_id in known and row.get(value_field)]
    values: Dict[str, int] = {}
    for row in matched:
        value = row[value_field]
        values[value] = values.get(value, 0) + 1
    return {
        "kind": kind,
        "rows_in_file": len(rows),
        "matched_cells": len(matched),
        "unmatched_rows": len(rows) - len(matched),
        "total_cells": total,
        "coverage": round(len(matched) / float(max(total, 1)), 4),
        "values": dict(sorted(values.items(), key=lambda kv: -kv[1])),
        "exists": table_path(dataset_path, kind).exists(),
    }


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


class ReviewWriteError(RuntimeError):
    """A review could not be saved, phrased for the person who made it."""


def _write_atomic(path: Path, fields: List[str], rows: Dict[str, Dict[str, str]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic_unguarded(path, fields, rows)
    except OSError as exc:
        # The raw error names a temporary file that no longer exists, which tells
        # a reviewer nothing about the folder that actually refused the write.
        raise ReviewWriteError(
            "Could not save the review to %s: %s. The folder may be read-only, full, or on a "
            "disconnected volume. Copy the bundle somewhere writable and reopen it from there, or "
            "grant this app access to that folder." % (path.parent, exc.strerror or exc)
        ) from exc


def _write_atomic_unguarded(path: Path, fields: List[str], rows: Dict[str, Dict[str, str]]) -> None:
    handle = tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=str(path.parent), prefix=".%s." % path.name, delete=False
    )
    try:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for cell_id in sorted(rows):
            row = rows[cell_id]
            writer.writerow({key: row.get(key, "") for key in fields})
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        # NamedTemporaryFile creates 0600. These tables sit beside the rest of the
        # bundle and get read by other tools and other accounts, so give them the
        # ordinary file mode the umask would have produced.
        os.chmod(handle.name, 0o666 & ~_umask())
        os.replace(handle.name, str(path))
    except Exception:
        handle.close()
        if os.path.exists(handle.name):
            os.unlink(handle.name)
        raise
