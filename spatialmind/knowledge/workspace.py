"""Versioned, evidence-bound wiki. SQLite owns state; Markdown is a checked projection."""

import difflib
import hashlib
import json
import re
import uuid
from pathlib import Path
from threading import RLock


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def plain(value):
    # Do not export active HTML, images, links or Obsidian embeds from model/source text.
    return re.sub(r"([\\`*_{}\[\]()#!<>|])", r"\\\1", str(value)).replace("\n", " ")


class KnowledgeWorkspace:
    def __init__(self, store):
        self.store = store
        self.root = store.path.parent / "knowledge"
        self.lock = RLock()
        for folder in ("raw", "extracted", "assets", "drafts", "wiki", "manifests"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS wiki_pages (
                  id TEXT NOT NULL, revision INTEGER NOT NULL, title TEXT NOT NULL,
                  kind TEXT NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL,
                  payload TEXT NOT NULL, markdown TEXT NOT NULL, projection_hash TEXT NOT NULL,
                  reviewer TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                  PRIMARY KEY(id,revision));
                CREATE TABLE IF NOT EXISTS wiki_dependencies (
                  page_id TEXT NOT NULL, revision INTEGER NOT NULL, source_id TEXT NOT NULL,
                  source_hash TEXT NOT NULL, source_version TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS knowledge_events (
                  id INTEGER PRIMARY KEY, event TEXT NOT NULL, target TEXT NOT NULL,
                  detail TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS wiki_search USING fts5(page_id UNINDEXED, revision UNINDEXED, title, body);
            """)
            db.execute("INSERT INTO wiki_search(page_id,revision,title,body) SELECT id,revision,title,markdown FROM wiki_pages p WHERE status='published' AND NOT EXISTS (SELECT 1 FROM wiki_search s WHERE s.page_id=p.id AND s.revision=p.revision)")

    def event(self, event, target, detail):
        with self.store.connect() as db:
            db.execute("INSERT INTO knowledge_events(event,target,detail,created_at) VALUES(?,?,?,?)",
                       (event, target, json.dumps(detail), self.store.now()))

    def write(self, relative, content):
        path = self.root / relative
        path.resolve().relative_to(self.root.resolve())
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def source_key(self, identity):
        return digest(identity)

    def export_source(self, identity):
        source = self.store.source(identity)
        key = self.source_key(identity)
        text = source["body"] if source["status"] != "deleted" else "Source deleted."
        # Fenced text is escaped as prose instead: uploaded backticks cannot end a fence.
        self.write("extracted/%s.md" % key, "# %s\n\n%s\n" % (plain(source["title"]), "\n\n".join(plain(p) for p in text.split("\n\n"))))
        self.write("manifests/%s.json" % key, json.dumps({k: v for k, v in source.items() if k != "body"}, indent=2))

    def retain_original(self, identity, payload):
        source = self.store.source(identity)
        expected = source["metadata"].get("file_sha256")
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError("Original bytes do not match the extraction manifest.")
        path = self.original_path(source)
        path.resolve().relative_to(self.root.resolve())
        path.write_bytes(payload)
        source["metadata"]["original_retained"] = True
        with self.store.connect() as db:
            db.execute("UPDATE sources SET metadata=? WHERE id=?", (json.dumps(source["metadata"]), identity))
        self.export_source(identity)
        self.event("archive_original", identity, {"sha256": expected})

    def original_path(self, source):
        extension = source["metadata"].get("format", "bin")
        if extension not in {"docx", "xlsx", "pptx", "pdf", "txt", "md", "csv", "tsv"}:
            extension = "bin"
        return self.root / "raw" / (self.source_key(source["id"]) + "." + extension)

    def evidence(self, source_ids, per_source=8):
        if not 1 <= per_source <= 64:
            raise ValueError("Passage limit must be 1-64.")
        if not 1 <= len(source_ids) <= 12 or len(set(source_ids)) != len(source_ids):
            raise ValueError("Choose 1-12 distinct sources.")
        evidence = []
        for identity in source_ids:
            source = self.store.source(identity)
            if source["status"] not in {"reviewed", "bundled"} or not source["enabled"]:
                raise ValueError("Only enabled, reviewed or bundled sources can be compiled.")
            with self.store.connect() as db:
                rows = db.execute("SELECT rowid,body FROM passages WHERE source_id=? ORDER BY rowid LIMIT ?", (identity, per_source + 1)).fetchall()
            # Bounded input; explicitly record that the digest is not exhaustive.
            for row in rows[:per_source]:
                evidence.append({"source_id": identity, "sha256": source["sha256"], "version": source["version"],
                                 "title": source["title"], "status": source["status"], "passage": row["body"],
                                 "scope": source["scope"],
                                 "evidence_id": "%s:%s" % (identity, row["rowid"]), "chunk_id": row["rowid"],
                                 "url": source["url"], "source_truncated": len(rows) > per_source})
        if sum(len(e["passage"]) for e in evidence) > 48000:
            raise ValueError("Compilation evidence exceeds 48,000 characters; choose fewer sources.")
        return evidence

    def check_evidence(self, evidence):
        for item in evidence:
            source = self.store.source(item["source_id"])
            self.check_run_source(source)
            if not source["enabled"] or source["status"] not in {"reviewed", "bundled"}:
                raise ValueError("A source is disabled, deleted or awaiting review.")
            if source["sha256"] != item["sha256"] or source["version"] != item["version"]:
                raise ValueError("A cited source revision changed.")
            with self.store.connect() as db:
                row = db.execute("SELECT body FROM passages WHERE source_id=? AND rowid=?", (item["source_id"], item["chunk_id"])).fetchone()
            if not row or row["body"] != item["passage"] or item["evidence_id"] != "%s:%s" % (item["source_id"], item["chunk_id"]):
                raise ValueError("A citation no longer resolves to its exact passage.")

    def check_run_source(self, source):
        metadata = source["metadata"]
        if metadata.get("kind") != "run_artifact":
            return
        for key in ("artifact", "record"):
            path = Path(metadata[key + "_path"])
            if not path.is_file() or path.stat().st_size > 2 * 1024 ** 2 or hashlib.sha256(path.read_bytes()).hexdigest() != metadata[key + "_sha256"]:
                raise ValueError("Captured run evidence is missing or changed. Re-import and review it.")

    def draft(self, title, claims, evidence, kind="concept", scope="general", generation=None, page_id=None):
        if not title.strip() or len(title) > 200 or kind not in {"source_summary", "concept", "method", "hypothesis", "project_finding", "answer"}:
            raise ValueError("Provide a title and a supported page type.")
        if not scope or len(scope) > 200 or not 1 <= len(claims) <= 24:
            raise ValueError("Provide a scope and 1-24 claims.")
        with self.lock:
            self.check_evidence(evidence)
            if any(e.get("scope", "general") not in {"general", scope} for e in evidence):
                raise ValueError("Project evidence cannot be promoted to general or unrelated project knowledge.")
            allowed = {item["evidence_id"] for item in evidence}
            normalized = []
            for index, claim in enumerate(claims, 1):
                text, ids = claim.get("text"), claim.get("evidence_ids")
                if not isinstance(text, str) or not text.strip() or len(text) > 5000 or not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in allowed for i in ids):
                    raise ValueError("Every claim requires bounded text and resolvable evidence IDs.")
                numbers = set(re.findall(r"\d+(?:\.\d+)?", " ".join(e["passage"] for e in evidence if e["evidence_id"] in ids)))
                if not set(re.findall(r"\d+(?:\.\d+)?", text)).issubset(numbers):
                    raise ValueError("A claim contains numbers absent from its cited evidence.")
                normalized.append({"id": "C%d" % index, "text": text, "evidence_ids": list(dict.fromkeys(ids)),
                                   "support": "unassessed", "applicability": "unassessed", "contradictions": "not_assessed"})
            if page_id:
                previous = self.get(page_id)
                revision = previous["revision"] + 1
            else:
                page_id, revision = uuid.uuid4().hex, 1
            payload = {"claims": normalized, "evidence": evidence, "generation": generation or {"mode": "offline_digest"},
                       "limitations": ["Derived content is not independent evidence or biological validation.",
                                       "At most eight passages per source are included; this is not an exhaustive review."]}
            markdown = self.render(title, kind, scope, "draft", payload)
            with self.store.connect() as db:
                db.execute("INSERT INTO wiki_pages(id,revision,title,kind,scope,status,payload,markdown,projection_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (page_id, revision, title.strip(), kind, scope, "draft", json.dumps(payload), markdown, digest(markdown), self.store.now()))
                for item in {e["source_id"]: e for e in evidence}.values():
                    db.execute("INSERT INTO wiki_dependencies VALUES(?,?,?,?,?)", (page_id, revision, item["source_id"], item["sha256"], item["version"]))
            self.write("drafts/%s-r%d.md" % (page_id, revision), markdown)
            self.event("draft_created", page_id, {"revision": revision, "generation": payload["generation"]})
            self.index()
            return self.get(page_id)

    def render(self, title, kind, scope, state, payload):
        lines = ["# " + plain(title), "", "Type: %s | Scope: %s | State: %s" % (plain(kind), plain(scope), state), "",
                 "Derived content; not independent evidence or biological validation.", "", "## Claims", ""]
        for claim in payload["claims"]:
            lines += ["### " + claim["id"], "", plain(claim["text"]), "",
                      "Evidence: " + ", ".join(plain(i) for i in claim["evidence_ids"]),
                      "Support: %s | Applicability: %s | Contradictions: %s" % (plain(claim["support"]), plain(claim["applicability"]), plain(claim["contradictions"])), ""]
            if claim.get("note"):
                lines += ["Review note: " + plain(claim["note"]), ""]
        lines += ["## Sources", ""]
        for e in payload["evidence"]:
            lines += ["- %s: [%s](../extracted/%s.md) (version %s, SHA256 %s)" % (plain(e["evidence_id"]), plain(e["title"]), self.source_key(e["source_id"]), plain(e["version"]), e["sha256"])]
        lines += ["", "## Limitations", ""] + ["- " + plain(item) for item in payload["limitations"]]
        return "\n".join(lines) + "\n"

    def get(self, page_id, revision=None):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM wiki_pages WHERE id=? " + ("AND revision=?" if revision else "ORDER BY revision DESC LIMIT 1"),
                             (page_id, revision) if revision else (page_id,)).fetchone()
        if not row:
            raise KeyError(page_id)
        payload = json.loads(row["payload"])
        profile = {"exact_citation_checks": "required", "distinct_source_hashes": len({e["sha256"] for e in payload["evidence"]}),
                   "independent_corroboration": "not_established", "biological_validation": "not_established",
                   "semantic_support": "human_recorded" if row["status"] == "published" else "not_approved",
                   "reviewer": row["reviewer"], "probability_of_truth": None}
        return dict(row, payload=payload, evidence_profile=profile)

    def pages(self):
        self.health()
        with self.store.connect() as db:
            rows = db.execute("SELECT id,MAX(revision) AS revision FROM wiki_pages GROUP BY id").fetchall()
        return [self.get(row["id"], row["revision"]) for row in rows]

    def publish(self, page_id, revision, reviewer, assessments):
        with self.lock:
            self.health()
            page = self.get(page_id)
            if page["revision"] != revision or page["status"] != "draft":
                raise ValueError("Only the current unchanged draft can be published. Recompile stale pages.")
            if not reviewer.strip() or len(reviewer) > 200:
                raise ValueError("Record the real reviewer's identity.")
            self.check_evidence(page["payload"]["evidence"])
            claims = page["payload"]["claims"]
            if set(assessments) != {c["id"] for c in claims}:
                raise ValueError("Assess every claim individually before publication.")
            for claim in claims:
                assessment = assessments[claim["id"]]
                if assessment.get("support") not in {"supported", "qualified"} or assessment.get("applicability") not in {"general_guidance", "context_limited", "hypothesis_only"} or assessment.get("contradictions") not in {"none_identified", "disclosed"}:
                    raise ValueError("Review support, applicability and contradictions for every claim.")
                if not isinstance(assessment.get("note"), str) or not assessment["note"].strip() or len(assessment["note"]) > 2000:
                    raise ValueError("Each claim needs a short review note, including any qualification/conflict.")
                claim.update({key: assessment[key] for key in ("support", "applicability", "contradictions", "note")})
            markdown = self.render(page["title"], page["kind"], page["scope"], "published", page["payload"])
            with self.store.connect() as db:
                db.execute("UPDATE wiki_pages SET status='published',reviewer=?,payload=?,markdown=?,projection_hash=? WHERE id=? AND revision=?",
                           (reviewer.strip(), json.dumps(page["payload"]), markdown, digest(markdown), page_id, revision))
                db.execute("INSERT INTO wiki_search(page_id,revision,title,body) VALUES(?,?,?,?)", (page_id, revision, page["title"], markdown))
            self.write("drafts/%s-r%d.md" % (page_id, revision), markdown)
            self.write("wiki/%s.md" % page_id, markdown)
            self.event("published", page_id, {"revision": revision, "reviewer": reviewer, "assessments": assessments})
            self.index()
            return self.get(page_id)

    def invalidate(self, identity, deleted=False):
        with self.lock, self.store.connect() as db:
            rows = db.execute("SELECT p.* FROM wiki_pages p JOIN wiki_dependencies d ON p.id=d.page_id AND p.revision=d.revision WHERE d.source_id=?", (identity,)).fetchall()
            for row in rows:
                payload = json.loads(row["payload"])
                if deleted:
                    payload["claims"], payload["evidence"] = [], []
                text = "# Unavailable\n\nA source was %s. Recompile and review before reuse.\n" % ("deleted" if deleted else "revoked or revised")
                db.execute("UPDATE wiki_pages SET status='stale',payload=?,markdown=?,projection_hash=? WHERE id=? AND revision=?",
                           (json.dumps(payload), text, digest(text), row["id"], row["revision"]))
                db.execute("DELETE FROM wiki_search WHERE page_id=? AND revision=?", (row["id"], row["revision"]))
                self.write("drafts/%s-r%d.md" % (row["id"], row["revision"]), text)
                self.write("wiki/%s.md" % row["id"], text)
        if deleted:
            raw = self.original_path(self.store.source(identity))
            raw.resolve().relative_to(self.root.resolve())
            raw.unlink(missing_ok=True)
            with self.store.connect() as db:
                source = self.store.source(identity)
                source["metadata"]["original_retained"] = False
                db.execute("UPDATE sources SET metadata=? WHERE id=?", (json.dumps(source["metadata"]), identity))
        self.export_source(identity)
        self.event("source_deleted" if deleted else "source_revoked", identity, {"affected_revisions": len(rows)})
        self.index()

    def health(self, page_id=None):
        findings = []
        with self.lock, self.store.connect() as db:
            rows = db.execute("SELECT * FROM wiki_pages WHERE status IN ('draft','published')" + (" AND id=?" if page_id else ""), (page_id,) if page_id else ()).fetchall()
            for row in rows:
                reason = ""
                try:
                    self.check_evidence(json.loads(row["payload"])["evidence"])
                    paths = [self.root / "drafts" / ("%s-r%d.md" % (row["id"], row["revision"]))]
                    if row["status"] == "published":
                        latest = db.execute("SELECT MAX(revision) FROM wiki_pages WHERE id=? AND status='published'", (row["id"],)).fetchone()[0]
                        if latest == row["revision"]:
                            paths.append(self.root / "wiki" / (row["id"] + ".md"))
                    for path in paths:
                        path.resolve().relative_to(self.root.resolve())
                        if not path.is_file() or digest(path.read_text(encoding="utf-8")) != row["projection_hash"]:
                            reason = "Markdown missing or externally modified; approval is invalidated."
                except (KeyError, ValueError, OSError):
                    reason = "Evidence or projection is unavailable or changed."
                if reason:
                    db.execute("UPDATE wiki_pages SET status='stale' WHERE id=? AND revision=?", (row["id"], row["revision"]))
                    db.execute("DELETE FROM wiki_search WHERE page_id=? AND revision=?", (row["id"], row["revision"]))
                    findings.append({"page_id": row["id"], "revision": row["revision"], "issue": reason})
            stale = db.execute("SELECT id,revision FROM wiki_pages WHERE status='stale'").fetchall()
            unfinished = db.execute("SELECT target,created_at FROM knowledge_events WHERE event='compile_started' AND target NOT IN (SELECT target FROM knowledge_events WHERE event IN ('compile_completed','compile_failed'))").fetchall()
        if findings:
            self.index()
        return {"findings": findings, "stale_revisions": [dict(r) for r in stale],
                "unfinished_compilations": [dict(r) for r in unfinished],
                "semantic_contradictions": "Requires human assessment; not inferred from lexical similarity.",
                "security_scope": "Local integrity checks, not protection against a malicious OS user."}

    def index(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT p.* FROM wiki_pages p JOIN (SELECT id,MAX(revision) r FROM wiki_pages GROUP BY id) latest ON p.id=latest.id AND p.revision=latest.r").fetchall()
        lines = ["# SpatialMind Knowledge", "", "Generated index. Review state is authoritative in SpatialMind.", ""]
        for row in rows:
            target = "wiki/%s.md" % row["id"] if row["status"] == "published" else "drafts/%s-r%d.md" % (row["id"], row["revision"])
            lines.append("- [%s](%s): %s; %s" % (plain(row["title"]), target, row["status"], plain(row["scope"])))
            if row["status"] == "published":
                claims = json.loads(row["payload"])["claims"]
                if claims:
                    lines.append("  " + plain(claims[0]["text"][:160]))
        self.write("index.md", "\n".join(lines) + "\n")
        related = {row["id"]: self.related(row["id"]) for row in rows}
        self.write("manifests/backlinks.json", json.dumps(related, indent=2))

    def diff(self, page_id):
        current = self.get(page_id)
        previous = self.get(page_id, current["revision"] - 1)["markdown"] if current["revision"] > 1 else ""
        return "\n".join(difflib.unified_diff(previous.splitlines(), current["markdown"].splitlines(), fromfile="previous", tofile="draft"))

    def related(self, page_id):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute("SELECT DISTINCT p.id,p.title FROM wiki_dependencies a JOIN wiki_dependencies b ON a.source_id=b.source_id JOIN wiki_pages p ON p.id=b.page_id AND p.revision=b.revision WHERE a.page_id=? AND p.id<>? AND p.status='published'", (page_id, page_id))]

    def search(self, query, scope="general"):
        stop = {"what", "which", "how", "does", "the", "and", "this", "that", "are", "can", "you", "was", "were", "explain", "please", "about", "more", "with", "from", "tell", "why"}
        terms = list(dict.fromkeys(t.lower() for t in re.findall(r"\w{3,}", query) if t.lower() not in stop))[:24]
        if not terms:
            return []
        match = " OR ".join('"%s"' % t for t in terms)
        with self.store.connect() as db:
            candidates = db.execute("""SELECT p.id,p.revision FROM wiki_search s JOIN wiki_pages p
                ON p.id=s.page_id AND p.revision=s.revision WHERE wiki_search MATCH ?
                AND p.status='published' AND p.scope=? AND p.revision=(SELECT MAX(revision) FROM wiki_pages WHERE id=p.id)
                ORDER BY bm25(wiki_search) LIMIT 5""", (match, scope)).fetchall()
        matches = []
        for candidate in candidates:
            self.health(candidate["id"])
            page = self.get(candidate["id"], candidate["revision"])
            if page["status"] == "published":
                matches.append({k: page[k] for k in ("id", "title", "revision", "kind", "scope")})
        return matches
