"""Portable ingestion identities tied to exact bytes, not filesystem locations."""

import hashlib
import json
from pathlib import Path


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def observation_id(source_sha256, source_cell_id):
    if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256):
        raise ValueError("A complete lowercase source SHA256 is required.")
    if not str(source_cell_id).strip():
        raise ValueError("Source observation ID is required.")
    key = json.dumps([source_sha256, str(source_cell_id)], separators=(",", ":"))
    return "smcell:" + hashlib.sha256(key.encode()).hexdigest()


def verified_cache_manifest(path):
    path = Path(path)
    manifest = json.loads(path.with_suffix(path.suffix + ".manifest.json").read_text())
    if file_sha256(path) != manifest["cache_sha256"]:
        raise ValueError("Reference cache content changed.")
    return manifest
