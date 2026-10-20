"""Evidence lifecycle tests. Fixture reviewer IDs never approve real biology."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from spatialmind.agent.conversation import answer_question
from spatialmind.app.knowledge_runs import import_run
from spatialmind.app.server import create_studio_app
from spatialmind.knowledge.compiler import compile_page, file_answer
from spatialmind.knowledge.store import KnowledgeStore
from spatialmind.llm import StaticLLMProvider
from spatialmind.storage.run_store import _file_md5


def assess(page):
    return {c["id"]: {"support": "supported", "applicability": "context_limited", "contradictions": "none_identified", "note": "Synthetic fixture assertion checked."} for c in page["payload"]["claims"]}


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = KnowledgeStore(self.root / "knowledge.sqlite")
        self.ws = self.store.workspace
        self.source = self.store.add("Fixture source", "Fixturegene marker evidence has 12 measurements.")
        self.store.set_status(self.source, True, True, "fixture-source-reviewer")

    def tearDown(self):
        self.temp.cleanup()

    def draft(self):
        return compile_page(self.store, "Fixturegene concept", [self.source])

    def publish(self):
        page = self.draft()
        return self.ws.publish(page["id"], page["revision"], "fixture-page-reviewer", assess(page))

    def test_draft_publish_and_restart(self):
        page = self.draft()
        self.assertEqual(page["status"], "draft")
        self.assertEqual(self.ws.search("Fixturegene"), [])
        self.ws.publish(page["id"], 1, "fixture-reviewer", assess(page))
        reopened = KnowledgeStore(self.store.path)
        self.assertEqual(len(reopened.workspace.search("Fixturegene")), 1)
        self.assertIn("../extracted/", (self.ws.root / "wiki" / (page["id"] + ".md")).read_text())
        self.assertIsNone(reopened.workspace.get(page["id"])["evidence_profile"]["probability_of_truth"])

    def test_pending_source_cannot_compile(self):
        identity = self.store.add("Pending", "Pending fixture")
        with self.assertRaisesRegex(ValueError, "reviewed"):
            compile_page(self.store, "Draft", [identity])

    def test_review_requires_every_claim_and_real_reviewer(self):
        page = self.draft()
        for reviewer, assessments in (("", assess(page)), ("fixture", {}), ("fixture", {"C1": {"support": "supported"}})):
            with self.assertRaises(ValueError):
                self.ws.publish(page["id"], 1, reviewer, assessments)

    def test_stale_revision_cannot_publish(self):
        page = self.draft()
        newer = compile_page(self.store, "Revised title", [self.source], page_id=page["id"])
        self.assertEqual(newer["revision"], 2)
        self.assertIn("Revised title", self.ws.diff(page["id"]))
        with self.assertRaises(ValueError):
            self.ws.publish(page["id"], 1, "fixture", assess(page))

    def test_disable_invalidates_and_reenable_does_not_reapprove(self):
        page = self.publish()
        self.store.set_status(self.source, False)
        self.assertEqual(self.ws.get(page["id"])["status"], "stale")
        self.assertEqual(self.ws.search("Fixturegene"), [])
        self.store.set_status(self.source, True)
        self.assertEqual(self.ws.get(page["id"])["status"], "stale")

    def test_delete_scrubs_all_page_revisions_and_export(self):
        page = self.publish()
        compile_page(self.store, "Second revision", [self.source], page_id=page["id"])
        self.store.delete(self.source)
        for revision in (1, 2):
            saved = self.ws.get(page["id"], revision)
            self.assertEqual(saved["payload"]["claims"], [])
            self.assertNotIn("12 measurements", saved["markdown"])
        for path in self.ws.root.rglob("*.md"):
            self.assertNotIn("12 measurements", path.read_text())
        with self.assertRaisesRegex(ValueError, "Deleted"):
            self.store.set_status(self.source, True, True, "fixture")

    def test_revise_source_preserves_old_identity_and_requires_review(self):
        page = self.publish()
        new = self.store.revise(self.source, "New revision", "Fixturegene has 14 measurements.")
        self.assertEqual(self.store.source(new)["status"], "pending")
        self.assertEqual(self.store.source(new)["version"], "2")
        self.assertFalse(self.store.source(self.source)["enabled"])
        self.assertEqual(self.ws.get(page["id"])["status"], "stale")

    def test_external_markdown_edit_invalidates_approval(self):
        page = self.publish()
        target = self.ws.root / "wiki" / (page["id"] + ".md")
        target.write_text("Unreviewed external edit")
        findings = self.ws.health()
        self.assertTrue(findings["findings"])
        self.assertEqual(self.ws.search("Fixturegene"), [])
        self.assertEqual(target.read_text(), "Unreviewed external edit")

    def test_missing_draft_after_crash_is_not_publishable(self):
        page = self.draft()
        (self.ws.root / "drafts" / (page["id"] + "-r1.md")).unlink()
        with self.assertRaises(ValueError):
            self.ws.publish(page["id"], 1, "fixture", assess(page))

    def test_hosted_consent_is_per_request_and_private_source(self):
        evidence = self.ws.evidence([self.source])
        provider = StaticLLMProvider({"claims": [{"text": "Fixturegene has 12 measurements.", "evidence_ids": [evidence[0]["evidence_id"]]}]})
        with patch.object(provider, "generate_answer_json", wraps=provider.generate_answer_json) as call:
            for kwargs in ({}, {"consent": True}):
                with self.assertRaises(ValueError):
                    compile_page(self.store, "Draft", [self.source], provider=provider, **kwargs)
            call.assert_not_called()
            page = compile_page(self.store, "Draft", [self.source], provider=provider, consent=True, allowed_private_ids=[self.source])
            self.assertEqual(page["status"], "draft")
            self.assertEqual(page["payload"]["generation"]["provider"], "static")

    def test_model_cannot_invent_citations_numbers_or_reviews(self):
        evidence = self.ws.evidence([self.source])
        for claim in ({"text": "Invented claim", "evidence_ids": ["fake"]},
                      {"text": "There are 999 cells", "evidence_ids": [evidence[0]["evidence_id"]]},
                      {"text": "Bad ID", "evidence_ids": [{}]}):
            with self.assertRaises(ValueError):
                compile_page(self.store, "Draft", [self.source], provider=StaticLLMProvider({"claims": [claim]}), consent=True, allowed_private_ids=[self.source])

    def test_project_source_cannot_leak_to_general_or_other_project(self):
        source = self.store.add("Project A", "Fixtureprivate only", metadata={"scope": "dataset:A"})
        self.store.set_status(source, True, True, "fixture")
        self.assertFalse(self.store.search("Fixtureprivate"))
        self.assertFalse(self.store.search("Fixtureprivate", scope="dataset:B"))
        self.assertTrue(self.store.search("Fixtureprivate", scope="dataset:A"))
        with self.assertRaises(ValueError):
            compile_page(self.store, "General", [source])
        page = compile_page(self.store, "Project", [source], scope="dataset:A")
        self.ws.publish(page["id"], 1, "fixture", assess(page))
        self.assertFalse(self.ws.search("Fixtureprivate"))

    def test_multisource_answers_and_filing_remain_derived(self):
        second = self.store.add("Second fixture", "Fixturegene has an alternative interpretation.")
        self.store.set_status(second, True, True, "fixture")
        session = self.store.create_session()
        answer = answer_question(self.store, "Fixturegene", session)
        self.assertEqual(len({e["source_id"] for e in answer["citations"]}), 2)
        self.store.append(session["id"], "Fixturegene", answer)
        page = file_answer(self.store, session["id"], 1, "Saved comparison")
        self.assertEqual(page["kind"], "answer")
        self.assertEqual(page["status"], "draft")
        self.assertEqual(page["evidence_profile"]["independent_corroboration"], "not_established")
        self.store.set_status(second, False)
        self.assertEqual(self.store.session(session["id"])["messages"][-1]["support_status"], "source_removed")

    def test_related_pages_and_bounded_source_selection(self):
        first, second = self.publish(), self.publish()
        self.assertIn(second["id"], {p["id"] for p in self.ws.related(first["id"])})
        with self.assertRaises(ValueError):
            compile_page(self.store, "Duplicate", [self.source, self.source])
        self.assertTrue((self.ws.root / "manifests" / "backlinks.json").exists())

    def test_archive_is_opt_in_hash_checked_and_deleted(self):
        raw = b"fixture original"
        source = self.store.add("Uploaded", "Extracted text", metadata={"file_sha256": hashlib.sha256(raw).hexdigest()})
        self.assertEqual(list((self.ws.root / "raw").iterdir()), [])
        with self.assertRaises(ValueError):
            self.ws.retain_original(source, b"wrong")
        self.ws.retain_original(source, raw)
        self.assertEqual(len(list((self.ws.root / "raw").iterdir())), 1)
        self.store.delete(source)
        self.assertEqual(list((self.ws.root / "raw").iterdir()), [])

    def test_reviewed_wiki_navigation_reads_original_evidence(self):
        page = compile_page(self.store, "Distincttopic concept", [self.source])
        self.ws.publish(page["id"], 1, "fixture", assess(page))
        answer = answer_question(self.store, "Distincttopic", self.store.create_session())
        self.assertEqual(answer["related_pages"][0]["id"], page["id"])
        self.assertEqual(answer["citations"][0]["source_id"], self.source)

    def test_evaluation_requires_completed_gold(self):
        from spatialmind.knowledge.evaluation import evaluate
        with self.assertRaisesRegex(ValueError, "template"):
            evaluate(self.store, {"review_status": "unreviewed_template"})
        result = evaluate(self.store, {"cases": [{"id": "fixture", "question": "Fixturegene", "expected_source_ids": [self.source]},
                                                   {"id": "unknown", "question": "zzzzunknown", "expected_source_ids": []}]})
        self.assertEqual(result["source_recall_at_5_passages"], 1.0)
        self.assertEqual(result["unanswerable_retrieval_abstention"], 1.0)
        self.assertIsNone(result["biological_accuracy"])


class WikiAPITests(unittest.TestCase):
    def test_routes_compile_publish_and_revision_conflict(self):
        with tempfile.TemporaryDirectory() as root, TestClient(create_studio_app(root + "/data", root + "/out")) as client:
            source = client.get("/api/knowledge/sources").json()["sources"][0]
            request = {"title": "Fixture concept", "source_ids": [source["id"]]}
            response = client.post("/api/knowledge/compile", json=request)
            self.assertEqual(response.status_code, 200, response.text)
            page = response.json()
            self.assertEqual(client.post("/api/knowledge/wiki/%s/publish" % page["id"], json={"revision": 1, "reviewer": "fixture", "assessments": assess(page)}).status_code, 200)
            self.assertEqual(client.get("/api/knowledge/wiki").json()["pages"][0]["status"], "published")
            self.assertEqual(client.get("/api/knowledge/wiki/" + page["id"]).status_code, 200)
            self.assertEqual(client.get("/api/knowledge/health").status_code, 200)
            self.assertEqual(client.post("/api/knowledge/compile", json=dict(request, hosted=True)).status_code, 400)


class RunEvidenceTests(unittest.TestCase):
    def test_verified_run_bridge_and_changed_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            data = root / "data.csv"
            data.write_text("x,y\n1,2\n")
            out = root / "out"
            out.mkdir()
            artifact, record = out / "plan_results.json", out / "record.json"
            payload = {"run_record_path": str(record), "records_loaded": 1, "scope": "full_section", "gate": {"status": "blocked"}, "results": []}
            artifact.write_text(json.dumps(payload))
            record.write_text(json.dumps({"run_id": "fixture-run", "params": {}, "input_file_md5": {str(data): _file_md5(str(data))},
                                          "artifact_paths": {"result": str(artifact)}, "artifact_md5": {"result": _file_md5(str(artifact))}}))
            studio = SimpleNamespace(output_root=str(out), entry=lambda _: SimpleNamespace(path=str(data), missing=False),
                                     reports=SimpleNamespace(get=lambda _: {"paths": {"validation": str(artifact)}}))
            store = KnowledgeStore(root / "kb.sqlite")
            imported = import_run(studio, store, "fixture-report", "fixture-data")
            self.assertEqual(imported["status"], "pending")
            self.assertEqual(imported["verification"]["status"], "verified")
            source = imported["source_id"]
            store.set_status(source, True, True, "fixture-reviewer")
            self.assertNotIn(source, {p["source_id"] for p in store.search("records_loaded")})
            self.assertIn(source, {p["source_id"] for p in store.search("records_loaded", scope="dataset:fixture-data")})
            artifact.write_text("modified")
            self.assertNotIn(source, {p["source_id"] for p in store.search("records_loaded", scope="dataset:fixture-data")})
            self.assertFalse(store.source(source)["enabled"])


if __name__ == "__main__":
    unittest.main()
