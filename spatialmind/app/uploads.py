"""Getting data into the workspace: uploaded files, and folders already on disk.

Two intake paths, because a Xenium bundle and a `.h5ad` are not the same
problem:

* **Upload** copies bytes through the browser. Right for a `.h5ad`, a tidy
  `.csv`, a manifest -- anything a person would drag in.
* **Link** registers a folder that is already on this machine, without copying
  it. Right for a Xenium output bundle, which is routinely 10 GB and whose
  morphology stack the pipeline catalogues and never parses. Pushing that
  through an HTTP form to land it 40 cm away on the same disk is a waste of
  minutes and of disk.

A folder upload (a browser's directory picker) keeps its relative paths, because
a Xenium bundle is only a dataset when `experiment.xenium` sits beside
`cells.csv.gz`; flattening the names would produce a pile of files the catalogue
cannot recognise.

Nothing here decides whether the data is *usable* -- `infer_data_type` and the
gate do that, afterwards, on the same footing as data that was always there. An
upload that lands as `unknown` is reported as unknown rather than rejected at
the door, so the user can see what the app made of it.
"""

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

UPLOAD_DIRNAME = "uploads"

# Extensions the ingestion layer can do something with. A file outside this set
# is still stored -- it may be one part of a bundle -- but it cannot by itself
# make a dataset, and the response says so.
KNOWN_SUFFIXES = {
    ".h5ad", ".xenium", ".csv", ".tsv", ".gz", ".json", ".zarr", ".h5",
    ".parquet", ".tif", ".tiff", ".svs", ".mtx", ".zip", ".txt", ".xlsx",
}

# Files that are never data and routinely ride along in a folder upload.
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "__macosx"}

MAX_NAME = 96


def safe_name(name: str) -> str:
    """A filesystem-safe single path component.

    Upload names are attacker-controlled in the general case and
    user-controlled here; either way `../` has no business becoming a path.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._+\- ]+", "_", str(name or "").strip())
    cleaned = cleaned.strip(". ").replace("..", "_")
    return (cleaned or "upload")[:MAX_NAME]


def safe_relative(path: str) -> Optional[str]:
    """A relative path from a folder upload, with every component sanitised.

    Returns None for anything that escapes, is absolute, or is junk.
    """
    raw = str(path or "").replace("\\", "/")
    if not raw or raw.startswith("/"):
        return None
    parts: List[str] = []
    for part in raw.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            return None
        if part.lower() in JUNK_NAMES:
            return None
        parts.append(safe_name(part))
    if not parts:
        return None
    return "/".join(parts)


def upload_root(data_root: str) -> Path:
    return Path(data_root) / UPLOAD_DIRNAME


def unique_directory(data_root: str, name: str) -> Path:
    """A fresh folder for one upload, never colliding with an existing dataset."""
    base = upload_root(data_root)
    base.mkdir(parents=True, exist_ok=True)
    candidate = base / safe_name(name)
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        attempt = base / ("%s_%d" % (safe_name(name), suffix))
        if not attempt.exists():
            return attempt
        suffix += 1


def store_files(data_root: str, dataset_name: str,
                files: Iterable[Tuple[str, bytes]]) -> Dict[str, Any]:
    """Write an upload into its own folder under `<data_root>/uploads`.

    `files` is (relative_path, content). A single file keeps its own name; a
    folder upload keeps its structure.
    """
    target = unique_directory(data_root, dataset_name)
    target.mkdir(parents=True, exist_ok=True)
    written: List[Dict[str, Any]] = []
    skipped: List[str] = []
    total = 0

    for relative, content in files:
        clean = safe_relative(relative)
        if not clean:
            skipped.append(str(relative))
            continue
        destination = target / clean
        try:
            destination.resolve().relative_to(target.resolve())
        except (ValueError, OSError):
            skipped.append(str(relative))
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        total += len(content)
        written.append({"path": clean, "bytes": len(content)})

    if not written:
        shutil.rmtree(target, ignore_errors=True)
        return {"status": "empty", "reason": "No usable files in the upload.",
                "skipped": skipped, "path": ""}

    return {
        "status": "stored",
        "path": str(_collapse_single_child(target)),
        "directory": str(target),
        "files": written,
        "skipped": skipped,
        "bytes": total,
    }


def _collapse_single_child(target: Path) -> Path:
    """The dataset is the thing uploaded, not the folder it was put in.

    Two cases, and both were wrong before:

    * A folder upload of `MyRun/` arrives as `uploads/MyRun/MyRun/...`, because
      browsers prefix every entry with the chosen folder's own name. The extra
      level makes a path that reads twice.
    * A single `.h5ad` or `.csv` landed as `uploads/name/file.csv`, and
      `infer_data_type` on that *folder* returns `unknown` -- so uploading one
      file produced a dataset the app could not recognise or run.

    In both cases the single child is the dataset.
    """
    children = [child for child in target.iterdir() if not child.name.startswith(".")]
    if len(children) == 1:
        return children[0]
    return target


def describe(path: str) -> Dict[str, Any]:
    """What the app made of an intake, using the same inference as discovery."""
    from ..ingestion import infer_data_type

    resolved = Path(path)
    try:
        data_type = infer_data_type(str(resolved))
    except Exception:
        data_type = "unknown"
    return {
        "path": str(resolved),
        "name": resolved.name,
        "data_type": data_type,
        "reviewable": data_type in ("xenium_directory", "xenium_experiment_file"),
        "usable": data_type != "unknown",
        "note": _intake_note(data_type, resolved),
    }


def _intake_note(data_type: str, path: Path) -> str:
    if data_type in ("xenium_directory", "xenium_experiment_file"):
        # `infer_data_type` calls a folder a Xenium directory when *any one* of
        # experiment.xenium, cells.csv.gz or cell_feature_matrix.h5 is present.
        # That is the right rule for routing and the wrong one for a promise: a
        # folder holding only cells.csv.gz was told it could run the validated
        # lane, and it cannot be loaded at all.
        missing = _missing_xenium_parts(path)
        if missing == ["experiment.xenium"]:
            # The one absence that is normal rather than broken: GEO deposits
            # carry no experiment file. Coordinates are already in microns, so
            # the section loads and gates; only the morphology viewer, which
            # needs a pixel size to align an image, is affected.
            return ("Recognised as a Xenium bundle with no `experiment.xenium`, which is how GEO "
                    "deposits them. It loads and can be gated; the morphology viewer cannot align "
                    "an image without a pixel size.")
        if missing:
            return ("Recognised as a Xenium bundle, but incomplete -- missing %s. Copy the rest of "
                    "the output folder before running anything against it." % ", ".join(missing))
        return ("Recognised as a Xenium bundle. It can be reviewed, gated and run through the "
                "validated lane.")
    if data_type == "h5ad_anndata":
        return ("Recognised as AnnData. Usable as a reference for label transfer; the validated "
                "Xenium lane needs a Xenium bundle.")
    if data_type == "tidy_csv":
        return "Recognised as a tidy table. Columns are checked when it is first loaded."
    if data_type == "10x_visium_directory":
        return "Recognised as a Visium directory."
    if data_type == "spatialdata_zarr":
        return "Recognised as a SpatialData zarr store."
    if data_type == "pathology_image":
        return "Recognised as a morphology image. Catalogued for provenance; not analysed on its own."
    if data_type == "manifest_json":
        return "Recognised as an ingestion manifest."
    missing = _missing_xenium_parts(path)
    if missing:
        return ("Not recognised. This looks like a partial Xenium bundle -- missing %s."
                % ", ".join(missing))
    return ("Not recognised as a supported dataset. It is stored and listed, but nothing can be "
            "run against it until it is a Xenium bundle, AnnData, tidy table, Visium folder or zarr store.")


# What the loader actually opens. `cells` has alternatives because the file
# format changed between Xenium Analyzer versions.
REQUIRED_XENIUM_FILES = {
    "experiment.xenium": ("experiment.xenium",),
    # `cells.parquet.gz` belongs here because the loader reads it: a GEO deposit
    # ships that and nothing else, and reporting it as a missing cell table told
    # the user to go and find a file they do not need.
    "a cell table": ("cells.csv.gz", "cells.csv", "cells.parquet", "cells.parquet.gz"),
    "cell_feature_matrix.h5": ("cell_feature_matrix.h5", "cell_feature_matrix.tar.gz"),
}
XENIUM_HINTS = {"experiment.xenium", "cells.csv.gz", "cells.parquet", "cells.parquet.gz",
                "cell_feature_matrix.h5", "transcripts.parquet", "metrics_summary.csv",
                "gene_panel.json"}


def _missing_xenium_parts(path: Path) -> List[str]:
    """Which files the loader needs and this folder does not have.

    "Not recognised" is a dead end; naming the missing file is something the
    user can act on, and a half-copied bundle is the common case.
    """
    if not path.is_dir():
        return []
    try:
        present = {child.name for child in path.iterdir()}
    except OSError:
        return []
    if not (present & XENIUM_HINTS):
        return []
    return [name for name, options in REQUIRED_XENIUM_FILES.items()
            if not any(option in present for option in options)]


def link_folder(path: str) -> Dict[str, Any]:
    """Register a folder that is already on this machine, without copying it.

    Returns the same shape as an upload so the wizard treats both identically.
    """
    resolved = Path(str(path or "").strip()).expanduser()
    if not resolved.exists():
        return {"status": "missing", "reason": "No such path: %s" % resolved, "path": ""}
    if not os.access(str(resolved), os.R_OK):
        return {"status": "unreadable",
                "reason": "%s exists but cannot be read by this app." % resolved, "path": ""}
    return {"status": "linked", "path": str(resolved.resolve()), "directory": str(resolved.resolve()),
            "files": [], "skipped": [], "bytes": 0}
