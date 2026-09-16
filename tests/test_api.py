"""Tests for the production HTTP service.

`spatialmind.api` carried the FastAPI service that `POST /runs` is served from
and had no tests of any kind -- not under that name, not under any other. That
mattered more once the validation gate became an invariant, because enforcement
flows through both of this module's run paths and nothing verified either: the
Studio's API gained five gate-bypass tests and the production API gained none.

These stay cheap on purpose. Routing is asserted by substituting the expensive
callee, so a routing test costs nothing and cannot pass by accident of timing.
"""

import os
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

import spatialmind.api.app as api_module
from spatialmind.api.app import create_app

ROOT = os.path.dirname(os.path.dirname(__file__))
DEMO_CSV = os.path.join(ROOT, "data", "demo_spatial.csv")
MANIFEST = os.path.join(ROOT, "data", "demo_manifest.json")
XENIUM = os.path.join(ROOT, "data", "Xenium Human Brain",
                      "Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs")


class ApiServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = TestClient(cls.app)
        cls.outputs = tempfile.mkdtemp(prefix="spatialmind-api-test-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.outputs, ignore_errors=True)

    # ------------------------------------------------------------------ basics

    def test_health_names_the_service(self):
        body = self.client.get("/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "spatialmind")

    def test_every_documented_route_is_mounted(self):
        paths = {route.path for route in self.app.routes if hasattr(route, "path")}
        for path in ("/health", "/runs", "/runs/{run_id}", "/runs/{run_id}/figures",
                     "/sessions/{session_id}/query", "/sessions/{session_id}/approve-qc",
                     "/batch/jobs", "/batch/jobs/{job_id}/status",
                     "/pilot/xenium/intake", "/pilot/xenium/run", "/promotion/local"):
            self.assertIn(path, paths, "%s is not mounted" % path)

    # ------------------------------------------------------------------ routing

    def test_a_xenium_bundle_goes_to_the_gated_pilot_not_the_orchestrator(self):
        """The data type decides the path, and a section must take the gated one.

        `SpatialMindAgent` runs `AlgorithmEngine`, whose tools are not in the
        30-tool registry and two of which name cell types. Sending a real section
        there rather than to `run_pilot` would be the difference between a gated
        analysis and an ungated one.
        """
        if not os.path.isdir(XENIUM):
            self.skipTest("the Xenium section is not present in this checkout")

        calls = {"pilot": 0, "orchestrator": 0}

        def fake_pilot(*args, **kwargs):
            calls["pilot"] += 1
            return {"status": "blocked_missing_validation_inputs", "blocking_reasons": ["stub"]}

        class FakeAgent:
            def __init__(self, *args, **kwargs):
                calls["orchestrator"] += 1

            def run(self, *args, **kwargs):  # pragma: no cover - must not be reached
                raise AssertionError("a Xenium bundle must not reach the orchestrator")

        original_pilot, original_agent = api_module.run_pilot, api_module.SpatialMindAgent
        api_module.run_pilot, api_module.SpatialMindAgent = fake_pilot, FakeAgent
        try:
            response = self.client.post("/runs", json={
                "prompt": "Summarise this section.", "data_path": XENIUM,
                "output_root": self.outputs, "readiness_only": True})
        finally:
            api_module.run_pilot, api_module.SpatialMindAgent = original_pilot, original_agent

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(calls["pilot"], 1, "a Xenium bundle must route to run_pilot")
        self.assertEqual(calls["orchestrator"], 0, "the orchestrator must not be constructed")

    def test_non_xenium_data_goes_to_the_orchestrator(self):
        calls = {"pilot": 0}

        def fake_pilot(*args, **kwargs):  # pragma: no cover - must not be reached
            calls["pilot"] += 1
            raise AssertionError("a CSV must not reach the pilot")

        original = api_module.run_pilot
        api_module.run_pilot = fake_pilot
        try:
            response = self.client.post("/runs", json={
                "prompt": "Show cell type abundance in sample BRCA_04.",
                "data_path": DEMO_CSV, "output_root": self.outputs})
        finally:
            api_module.run_pilot = original

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(calls["pilot"], 0)
        self.assertIn("run_id", response.json())

    # ------------------------------------------------------------------ the gate

    def test_the_orchestrator_path_records_a_gate_decision(self):
        """The gate reaches this endpoint, and its verdict is written down.

        `SpatialMindAgent` consulted no gate at all before `require_gate_open`
        was added. On non-Xenium data the gate cannot be evaluated -- which is
        not a pass -- so the run is permitted and the decision is recorded in
        provenance rather than left silent.
        """
        import json

        response = self.client.post("/runs", json={
            "prompt": "Show cell type abundance in sample BRCA_04.",
            "data_path": DEMO_CSV, "output_root": self.outputs})
        self.assertEqual(response.status_code, 200, response.text)

        with open(response.json()["provenance_path"], encoding="utf-8") as handle:
            provenance = json.load(handle)
        decision = provenance.get("gate_decision")
        self.assertIsNotNone(decision, "the run recorded no gate decision")
        self.assertEqual(decision["status"], "gate_not_evaluated")
        self.assertIn("not gate-validated", decision["caveat"])

    # ------------------------------------------------------------------ QC gate

    def test_a_session_query_is_refused_until_qc_is_approved(self):
        response = self.client.post("/sessions/session-unapproved/query", json={
            "prompt": "Which genes are spatially structured?", "data_path": MANIFEST})
        self.assertEqual(response.status_code, 403)
        self.assertIn("QC", response.json()["detail"])

    def test_approving_qc_unlocks_that_session_only(self):
        approved = self.client.post("/sessions/session-approved/approve-qc").json()
        self.assertTrue(approved["qc_approved"])

        allowed = self.client.post("/sessions/session-approved/query", json={
            "prompt": "Which genes are spatially structured?", "data_path": MANIFEST})
        self.assertEqual(allowed.status_code, 200, allowed.text)

        # Approval is per session, not global.
        other = self.client.post("/sessions/session-other/query", json={
            "prompt": "Which genes are spatially structured?", "data_path": MANIFEST})
        self.assertEqual(other.status_code, 403)

    def test_qc_can_be_approved_inline_for_one_request(self):
        response = self.client.post("/sessions/session-inline/query", json={
            "prompt": "Which genes are spatially structured?",
            "data_path": MANIFEST, "qc_approved": True})
        self.assertEqual(response.status_code, 200, response.text)

    # ------------------------------------------------------------------ batch and runs

    def test_a_batch_job_is_submitted_and_can_be_polled(self):
        submitted = self.client.post("/batch/jobs", json={
            "query": "Which genes are spatially structured?", "dataset_ids": [MANIFEST]})
        self.assertEqual(submitted.status_code, 200, submitted.text)
        job = submitted.json()
        self.assertIn("job_id", job)

        status = self.client.get("/batch/jobs/%s/status" % job["job_id"])
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["job_id"], job["job_id"])

    def test_an_unknown_run_id_does_not_return_a_fabricated_run(self):
        try:
            response = self.client.get("/runs/run_does_not_exist")
        except Exception:
            return  # an unhandled lookup error is acceptable; a fabricated run is not
        self.assertNotEqual(response.status_code, 200,
                            "an unknown run id returned a run: %s" % response.text[:120])


if __name__ == "__main__":
    unittest.main()
