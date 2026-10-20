"""Persistent local registrations. Removing a record never deletes source data."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path


class DatasetLibrary:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                hidden INTEGER NOT NULL DEFAULT 0, explicit INTEGER NOT NULL DEFAULT 0,
                location_mode TEXT NOT NULL DEFAULT 'linked')""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, payload, explicit=False, location_mode="linked"):
        payload = dict(payload)
        path = str(Path(payload["path"]).resolve())
        with self.connect() as db:
            old = db.execute("SELECT * FROM datasets WHERE path=?", (path,)).fetchone()
            if old:
                payload["dataset_id"] = old["id"]
                prior = json.loads(old["payload"])
                payload["display_name"] = prior.get("display_name", payload.get("display_name"))
                db.execute("UPDATE datasets SET payload=?, hidden=CASE WHEN ? THEN 0 ELSE hidden END, "
                           "explicit=MAX(explicit, ?) WHERE id=?",
                           (json.dumps(payload), int(explicit), int(explicit), old["id"]))
            else:
                identity = payload.get("dataset_id") or "dataset_" + uuid.uuid4().hex
                if db.execute("SELECT id FROM datasets WHERE id=?", (identity,)).fetchone():
                    identity = "dataset_" + uuid.uuid4().hex
                payload["dataset_id"] = identity
                db.execute("INSERT INTO datasets(id,path,payload,explicit,location_mode) VALUES(?,?,?,?,?)",
                           (identity, path, json.dumps(payload), int(explicit), location_mode))
        return payload["dataset_id"]

    def list(self, removed=False):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM datasets WHERE hidden=? ORDER BY rowid", (int(removed),)).fetchall()
        result = []
        for row in rows:
            item = json.loads(row["payload"])
            missing = not Path(row["path"]).exists()
            # Discovery entries that disappeared were not explicit user registrations.
            if missing and not row["explicit"] and not removed:
                continue
            item.update(path=row["path"], location_mode=row["location_mode"],
                        missing=missing, removed=bool(row["hidden"]))
            result.append(item)
        return result

    def hide(self, dataset_id, hidden=True):
        with self.connect() as db:
            count = db.execute("UPDATE datasets SET hidden=? WHERE id=?", (int(hidden), dataset_id)).rowcount
        if not count:
            raise KeyError(dataset_id)

    def rename(self, dataset_id, name):
        if not name.strip() or len(name) > 150:
            raise ValueError("A display name must contain 1-150 characters.")
        with self.connect() as db:
            row = db.execute("SELECT payload FROM datasets WHERE id=?", (dataset_id,)).fetchone()
            if not row:
                raise KeyError(dataset_id)
            payload = json.loads(row[0])
            payload["display_name"] = name.strip()
            db.execute("UPDATE datasets SET payload=? WHERE id=?", (json.dumps(payload), dataset_id))
