"""Reading and writing the two files that clear the gate.

`expert_cell_labels.csv` and `cell_regions.csv` live inside the Xenium bundle
because that is where the loader looks for them. Writes here are merges, never
overwrites: a reviewer adding a second label must not erase the first, and a
table a human hand-authored outside the app has to survive contact with it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import csv
import os
import tempfile

from .catalog import resolve_xenium_root

LABEL_FILENAME = "expert_cell_labels.csv"
REGION_FILENAME = "cell_regions.csv"
LABEL_FIELDS = ["cell_id", "expert_label", "confidence", "notes"]
REGION_FIELDS = ["cell_id", "region", "region_confidence", "notes"]

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "cells_written": self.cells_written,
            "rows_total": self.rows_total,
            "path": self.path,
            "distinct_values": self.distinct_values,
        }


def table_path(dataset_path: str, kind: str) -> Path:
    filename = KINDS[kind][0]
    return resolve_xenium_root(Path(dataset_path)) / filename


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
            "notes": notes or "assigned in SpatialMind Studio",
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


def _write_atomic(path: Path, fields: List[str], rows: Dict[str, Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
