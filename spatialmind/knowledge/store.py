"""Versioned sources and SQLite FTS retrieval. No remote fetches or execution."""

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .seed import SOURCES, VERSION
from .documents import MAX_TEXT_BYTES


class KnowledgeStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sources (
                  id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
                  version TEXT NOT NULL, sha256 TEXT NOT NULL, body TEXT NOT NULL,
                  status TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                  reviewer TEXT NOT NULL DEFAULT '', reviewed_at TEXT NOT NULL DEFAULT '');
                CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(source_id UNINDEXED, title, body);
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                  id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
                  payload TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(sources)")}
            if "metadata" not in columns:
                db.execute("ALTER TABLE sources ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            if "scope" not in columns:
                db.execute("ALTER TABLE sources ADD COLUMN scope TEXT NOT NULL DEFAULT 'general'")
        for key, title, url, body in SOURCES:
            self.add(title, body, url, identity="builtin:" + key + ":" + VERSION, status="bundled", version=VERSION)
        from .workspace import KnowledgeWorkspace
        self.workspace = KnowledgeWorkspace(self)
        for source in self.list_sources():
            self.workspace.export_source(source["id"])
        self.workspace.health()
        self.workspace.index()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, title, body, url="", identity=None, status="pending", version="1", metadata=None):
        if not title.strip() or len(title) > 200 or not body.strip() or len(body.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("Provide a title (1-200 characters) and text (up to 2 MiB).")
        if url and (urlsplit(url).scheme != "https" or not urlsplit(url).hostname or urlsplit(url).username):
            raise ValueError("Source links must be HTTPS URLs without credentials.")
        identity = identity or "source:" + uuid.uuid4().hex
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with self.connect() as db:
            inserted = db.execute("INSERT OR IGNORE INTO sources(id,title,url,version,sha256,body,status,metadata,scope) VALUES(?,?,?,?,?,?,?,?,?)",
                                  (identity, title.strip(), url, version, digest, body, status, json.dumps(metadata or {}), (metadata or {}).get("scope", "general"))).rowcount
            if inserted:
                # Paragraph boundaries preserve short procedures and source locators.
                for paragraph in re.split(r"\n\s*\n", body):
                    for offset in range(0, len(paragraph), 2400):
                        text = paragraph[offset:offset + 2400].strip()
                        if text:
                            db.execute("INSERT INTO passages(source_id,title,body) VALUES(?,?,?)", (identity, title, text))
        if hasattr(self, "workspace"):
            self.workspace.export_source(identity)
        return identity

    def list_sources(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,title,url,version,sha256,status,enabled,reviewer,reviewed_at,scope FROM sources ORDER BY title")]

    def source(self, source_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            raise KeyError(source_id)
        return dict(row, metadata=json.loads(row["metadata"]))

    def set_status(self, source_id, enabled, approve=False, reviewer=""):
        source = self.source(source_id)
        if source["status"] == "deleted":
            raise ValueError("Deleted sources cannot be restored or approved. Import a new source.")
        if approve and not reviewer.strip():
            raise ValueError("Record the real source reviewer's identity.")
        if approve and source["status"] == "bundled":
            raise ValueError("Bundled product notes are not specialist-reviewed sources.")
        with self.connect() as db:
            db.execute("UPDATE sources SET enabled=?,status=?,reviewer=?,reviewed_at=? WHERE id=?",
                       (int(enabled), "reviewed" if approve else source["status"],
                        reviewer.strip() if approve else source["reviewer"],
                        self.now() if approve else source["reviewed_at"], source_id))
        if not enabled:
            self.workspace.invalidate(source_id)
            self.redact_answers(source_id, "disabled")
        else:
            self.workspace.export_source(source_id)

    def delete(self, source_id):
        source = self.source(source_id)
        with self.connect() as db:
            db.execute("DELETE FROM passages WHERE source_id=?", (source_id,))
            # Tombstone prevents bundled notes reappearing on app restart.
            db.execute("UPDATE sources SET body='', enabled=0, status='deleted' WHERE id=?", (source_id,))
            # Stored answer excerpts may contain revoked content. Redact them too.
            rows = db.execute("SELECT id,payload FROM messages WHERE role='assistant'").fetchall()
            for row in rows:
                payload = json.loads(row["payload"])
                if any(c.get("source_id") == source_id for c in payload.get("citations", [])):
                    db.execute("UPDATE messages SET payload=? WHERE id=?", (json.dumps({
                        "answer": "This answer was removed because a cited source was deleted.",
                        "citations": [], "support_status": "source_removed"}), row["id"]))
        self.workspace.invalidate(source_id, deleted=True)
        return source["title"]

    def redact_answers(self, source_id, reason):
        with self.connect() as db:
            for row in db.execute("SELECT id,payload FROM messages WHERE role='assistant'").fetchall():
                payload = json.loads(row["payload"])
                if any(c.get("source_id") == source_id for c in payload.get("citations", [])):
                    db.execute("UPDATE messages SET payload=? WHERE id=?", (json.dumps({"answer": "This answer is unavailable because a source was " + reason + ".", "citations": [], "support_status": "source_removed"}), row["id"]))

    def revise(self, source_id, title, body, url=""):
        old = self.source(source_id)
        if old["status"] in {"deleted", "bundled"}:
            raise ValueError("Import a separate source instead of revising bundled or deleted content.")
        metadata = {"supersedes": source_id, "scope": old["scope"]}
        identity = self.add(title, body, url, version=str(int(old["version"]) + 1), metadata=metadata)
        self.set_status(source_id, False)
        self.workspace.event("source_revised", identity, {"supersedes": source_id})
        return identity

    def search(self, query, limit=4, scope="general"):
        stop = {"what", "which", "how", "does", "the", "and", "this", "that", "are", "can", "you",
                "explain", "please", "about", "more", "with", "from", "tell", "why", "is",
                "was", "were", "has", "have", "had", "did", "does", "would", "could", "should"}
        terms = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) > 2 and t.lower() not in stop][:24]
        if not terms:
            return []
        match = " OR ".join('"%s"' % term for term in dict.fromkeys(terms))
        with self.connect() as db:
            rows = db.execute("""SELECT p.rowid AS chunk_id,p.body AS passage,s.id AS source_id,
                s.title,s.url,s.version,s.sha256,s.status,s.scope,bm25(passages) AS rank
                FROM passages p JOIN sources s ON s.id=p.source_id
                WHERE passages MATCH ? AND s.enabled=1 AND s.status IN ('bundled','reviewed') AND s.scope IN ('general',?)
                ORDER BY rank LIMIT ?""", (match, scope, min(max(limit, 1), 8))).fetchall()
        valid = []
        for row in rows:
            try:
                self.workspace.check_run_source(self.source(row["source_id"]))
            except (ValueError, OSError, KeyError):
                self.set_status(row["source_id"], False)
                continue
            valid.append(dict(row, evidence_id="%s:%s" % (row["source_id"], row["chunk_id"])))
        return valid

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def create_session(self, dataset_id=""):
        identity = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (identity, dataset_id, "New conversation", self.now()))
        return self.session(identity)

    def sessions(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM sessions ORDER BY created_at DESC")]

    def session(self, session_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row:
                raise KeyError(session_id)
            messages = [dict(role=m["role"], **json.loads(m["payload"])) for m in db.execute(
                "SELECT role,payload FROM messages WHERE session_id=? ORDER BY id", (session_id,))]
        return dict(row, messages=messages)

    def append(self, session_id, question, answer):
        with self.connect() as db:
            if not db.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone():
                raise KeyError(session_id)
            if not db.execute("SELECT id FROM messages WHERE session_id=?", (session_id,)).fetchone():
                db.execute("UPDATE sessions SET title=? WHERE id=?", (question[:80], session_id))
            for role, payload in (("user", {"answer": question}), ("assistant", answer)):
                db.execute("INSERT INTO messages(session_id,role,payload,created_at) VALUES(?,?,?,?)",
                           (session_id, role, json.dumps(payload), self.now()))

    def delete_session(self, session_id):
        with self.connect() as db:
            db.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
