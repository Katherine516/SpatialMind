"""Local-only lifecycle and evidence boundaries; never modifies real datasets."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from spatialmind.agent.conversation import answer_question, synthesize_answer
from spatialmind.app import config, uploads
from spatialmind.app.server import create_studio_app
from spatialmind.knowledge.store import KnowledgeStore
from spatialmind.llm import StaticLLMProvider


class LocalLibraryChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.out = self.root / "outputs"
        self.app = create_studio_app(str(self.data), str(self.out))
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def link(self):
        external = self.root / "external.csv"
        external.write_text("cell_id,x,y\nc1,1,2\n")
        response = self.client.post("/api/uploads/link", json={"path": str(external)})
        self.assertEqual(response.status_code, 200, response.text)
        return external, response.json()["dataset_id"]

    def session(self, dataset_id=""):
        response = self.client.post("/api/chat/sessions", json={"dataset_id": dataset_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def test_fresh_user_has_no_datasets_but_can_ask(self):
        self.assertEqual(self.client.get("/api/datasets").json()["datasets"], [])
        session = self.session()
        response = self.client.post("/api/chat/sessions/%s/messages" % session, json={"question": "What is Moran's I?"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("autocorrelation", response.json()["answer"])
        self.assertTrue(response.json()["citations"])
        self.assertEqual(response.json()["provider"], "offline")
        self.assertEqual(self.app.state.studio.jobs.list(), [])

    def test_external_link_persists_and_remove_preserves_bytes(self):
        source, identity = self.link()
        original = source.read_bytes()
        restarted = TestClient(create_studio_app(str(self.data), str(self.out)))
        self.assertEqual(restarted.get("/api/datasets").json()["datasets"][0]["dataset_id"], identity)
        response = restarted.post("/api/datasets/%s/remove" % identity, json={"confirm_name": source.name})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["files_deleted"])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(restarted.get("/api/datasets?refresh=true").json()["datasets"], [])
        restarted.close()
        final = TestClient(create_studio_app(str(self.data), str(self.out)))
        self.assertEqual(final.get("/api/datasets").json()["datasets"], [])
        self.assertEqual(len(final.get("/api/library/removed").json()["datasets"]), 1)
        self.assertEqual(len(final.post("/api/datasets/%s/restore" % identity).json()["datasets"]), 1)
        self.assertEqual(source.read_bytes(), original)
        final.close()

    def test_discovered_data_are_not_resurrected_by_rescan(self):
        source = self.data / "existing.csv"
        source.write_text("x,y\n1,2\n")
        identity = self.client.get("/api/datasets").json()["datasets"][0]["dataset_id"]
        self.client.post("/api/datasets/%s/remove" % identity, json={"confirm_name": source.name})
        self.assertEqual(self.client.get("/api/datasets?refresh=true").json()["datasets"], [])
        self.assertTrue(source.exists())

    def test_wrong_confirmation_and_busy_task_block_removal(self):
        from types import SimpleNamespace
        source, identity = self.link()
        self.assertEqual(self.client.post("/api/datasets/%s/remove" % identity,
                                        json={"confirm_name": "wrong"}).status_code, 409)
        with patch.object(self.app.state.studio.jobs, "list", return_value=[SimpleNamespace(dataset_id=identity, state="running")]):
            self.assertEqual(self.client.post("/api/datasets/%s/remove" % identity,
                                            json={"confirm_name": source.name}).status_code, 409)

    def test_rename_is_display_only_and_survives_rescan(self):
        source, identity = self.link()
        self.client.patch("/api/datasets/" + identity, json={"name": "My section"})
        entry = self.client.get("/api/datasets?refresh=true").json()["datasets"][0]
        self.assertEqual(entry["display_name"], "My section")
        self.assertEqual(entry["path"], str(source.resolve()))

    def test_missing_registered_source_is_reported(self):
        source, identity = self.link()
        source.unlink()
        entry = self.client.get("/api/datasets?refresh=true").json()["datasets"][0]
        self.assertTrue(entry["missing"])

    def test_upload_is_managed_and_not_in_memory_payload(self):
        response = self.client.post("/api/uploads", files={"files": ("table.csv", b"x,y\n1,2\n")})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["datasets"][0]["location_mode"], "managed_copy")
        self.assertEqual(len(body["files"][0]["sha256"]), 64)
        self.assertTrue((Path(body["directory"]) / ".import.json").exists())

    def test_hidden_staging_is_not_discovered(self):
        hidden = self.data / "uploads" / ".import-interrupted"
        hidden.mkdir(parents=True)
        (hidden / "a.csv").write_text("x,y\n1,2\n")
        self.assertEqual(self.client.get("/api/datasets").json()["datasets"], [])

    def test_private_source_needs_real_review_record(self):
        identity = self.client.post("/api/knowledge/sources", json={
            "title": "Private zebra protocol", "body": "Zebratest methodology is a private fixture."}).json()["source_id"]
        endpoint = "/api/knowledge/source?source_id=" + identity
        self.assertEqual(self.client.get("/api/knowledge/search?q=zebratest").json()["passages"], [])
        self.assertEqual(self.client.patch(endpoint, json={"approve": True}).status_code, 400)
        self.assertEqual(self.client.patch(endpoint, json={"approve": True, "reviewer": "fixture-reviewer"}).status_code, 200)
        self.assertTrue(self.client.get("/api/knowledge/search?q=zebratest").json()["passages"])
        self.client.patch(endpoint, json={"enabled": False})
        self.assertEqual(self.client.get("/api/knowledge/search?q=zebratest").json()["passages"], [])

    def test_deleted_source_redacts_history_and_does_not_return_on_restart(self):
        identity = self.session()
        response = self.client.post("/api/chat/sessions/%s/messages" % identity, json={"question": "What is Moran's I?"}).json()
        source_id = response["citations"][0]["source_id"]
        self.client.delete("/api/knowledge/source", params={"source_id": source_id})
        messages = self.client.get("/api/chat/sessions/" + identity).json()["messages"]
        self.assertEqual(messages[-1]["support_status"], "source_removed")
        reopened = KnowledgeStore(self.app.state.studio.knowledge.path)
        self.assertEqual(reopened.source(source_id)["status"], "deleted")
        self.assertEqual(reopened.source(source_id)["body"], "")

    def test_sessions_persist_and_delete(self):
        identity = self.session()
        self.client.post("/api/chat/sessions/%s/messages" % identity, json={"question": "What is clustering?"})
        store = KnowledgeStore(self.app.state.studio.knowledge.path)
        self.assertEqual(len(store.session(identity)["messages"]), 2)
        self.client.delete("/api/chat/sessions/" + identity)
        self.assertEqual(self.client.get("/api/chat/sessions/" + identity).status_code, 404)

    def test_removed_dataset_cannot_supply_chat_context(self):
        source, dataset_id = self.link()
        identity = self.session(dataset_id)
        self.client.post("/api/datasets/%s/remove" % dataset_id, json={"confirm_name": source.name})
        self.assertEqual(self.client.post("/api/chat/sessions/%s/messages" % identity,
                                        json={"question": "Why is my dataset blocked?"}).status_code, 409)

    def test_analysis_request_does_not_execute(self):
        identity = self.session()
        result = self.client.post("/api/chat/sessions/%s/messages" % identity,
                                  json={"question": "Run neighborhood enrichment"}).json()
        self.assertEqual(result["mode"], "clarification")
        self.assertEqual(self.app.state.studio.jobs.list(), [])

    def test_unknown_question_abstains(self):
        identity = self.session()
        result = self.client.post("/api/chat/sessions/%s/messages" % identity,
                                  json={"question": "zzzzunknownphrase"}).json()
        self.assertEqual(result["support_status"], "insufficient_evidence")
        self.assertFalse(result["citations"])

    def test_followup_uses_previous_question_not_previous_model_output(self):
        identity = self.session()
        endpoint = "/api/chat/sessions/%s/messages" % identity
        self.client.post(endpoint, json={"question": "What is Moran's I?"})
        result = self.client.post(endpoint, json={"question": "Tell me more"}).json()
        self.assertIn("autocorrelation", result["answer"])

    def test_hosted_requires_explicit_consent(self):
        identity = self.session()
        with patch("spatialmind.app.knowledge_chat.build_llm_provider") as build:
            response = self.client.post("/api/chat/sessions/%s/messages" % identity,
                                        json={"question": "What is Moran's I?", "hosted": True})
            self.assertEqual(response.status_code, 400)
            build.assert_not_called()

    def test_general_query_does_not_load_a_cell_index(self):
        source, dataset_id = self.link()
        identity = self.session(dataset_id)
        with patch.object(self.app.state.studio, "gate", side_effect=AssertionError("Must not inspect cells")):
            response = self.client.post("/api/chat/sessions/%s/messages" % identity,
                                        json={"question": "What is Moran's I?"})
        self.assertEqual(response.status_code, 200, response.text)


class StreamSafetyTests(unittest.TestCase):
    def test_reads_are_bounded(self):
        class Bounded(io.BytesIO):
            def read(self, size=-1):
                if size < 1 or size > uploads.COPY_CHUNK_BYTES:
                    raise AssertionError("unbounded read")
                return super().read(size)
        with tempfile.TemporaryDirectory() as root:
            result = uploads.store_streams(root, "fixture", [("a.csv", Bounded(b"x,y\n1,2"))])
            self.assertTrue(Path(result["path"]).is_file())

    def test_path_escape_collision_and_limit_clean_staging(self):
        for files in [[("../outside.csv", io.BytesIO(b"x"))],
                      [("A.csv", io.BytesIO(b"x")), ("a.csv", io.BytesIO(b"y"))],
                      [("C:\\escape.csv", io.BytesIO(b"x"))]]:
            with tempfile.TemporaryDirectory() as root:
                with self.assertRaises(ValueError):
                    uploads.store_streams(root, "fixture", files)
                self.assertEqual(list((Path(root) / "uploads").iterdir()), [])
        with tempfile.TemporaryDirectory() as root, patch.object(uploads, "MAX_UPLOAD_BYTES", 2):
            with self.assertRaises(ValueError):
                uploads.store_streams(root, "fixture", [("a.csv", io.BytesIO(b"123"))])
            self.assertEqual(list((Path(root) / "uploads").iterdir()), [])

    def test_fresh_frozen_install_ignores_checkout_data(self):
        with tempfile.TemporaryDirectory() as home, patch.object(config, "is_frozen", return_value=True), \
                patch.object(config, "load", return_value={}), patch.object(Path, "home", return_value=Path(home)), \
                patch.dict(os.environ, {}, clear=True):
            selected = Path(config.default_data_root())
            self.assertEqual(selected, Path(home) / "SpatialMind" / "data")
            self.assertEqual(list(selected.iterdir()), [])


class ChatSecurityTests(unittest.TestCase):
    def test_loopback_security_bootstrap_origin_and_limits(self):
        with tempfile.TemporaryDirectory() as root:
            app = create_studio_app(root + "/data", root + "/out", secure=True)
            with TestClient(app, base_url="http://127.0.0.1:9876") as client:
                self.assertEqual(client.get("/healthz").status_code, 200)
                self.assertEqual(client.get("/api/datasets").status_code, 401)
                page = client.get("/")
                self.assertIn("window.STUDIO_TOKEN", page.text)
                self.assertEqual(client.get("/api/datasets").status_code, 200)
                self.assertEqual(client.post("/api/chat/sessions", json={}, headers={"Origin": "https://evil.example"}).status_code, 403)
                self.assertEqual(client.get("/", headers={"Host": "evil.example"}).status_code, 403)
                self.assertEqual(client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
                self.assertEqual(client.post("/api/chat/sessions", content=b"x", headers={"Content-Length": str(3 * 1024 ** 2)}).status_code, 413)

    def test_generation_rejects_invented_citations_and_measurements(self):
        with tempfile.TemporaryDirectory() as root:
            store = KnowledgeStore(Path(root) / "kb.sqlite")
            result = answer_question(store, "What is Moran's I?", {"dataset_id": "", "messages": []})
            with self.assertRaises(ValueError):
                synthesize_answer(StaticLLMProvider({"answer": "Claim", "evidence_ids": ["fake"]}), "question", result)
            ids = [c["evidence_id"] for c in result["citations"]]
            with self.assertRaises(ValueError):
                synthesize_answer(StaticLLMProvider({"answer": "The score is 0.99", "evidence_ids": ids}), "question", result)
            reply = synthesize_answer(StaticLLMProvider({"answer": "It describes spatial autocorrelation.", "evidence_ids": ids}), "question", result)
            self.assertEqual(reply["support_status"], "generated_with_citations")


if __name__ == "__main__":
    unittest.main()
