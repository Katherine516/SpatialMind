"""End-to-end checks for SpatialMind Studio, the packaged app.

These run against a synthetic Xenium bundle in a temp directory rather than the
real sections, because the interesting assertions here are about the *gate*
opening and closing as a reviewer works, and a test that mutated a real bundle
would leave label tables behind in the user's data folder.

What matters most: the app must never open the gate on its own, and the tool
catalog must never present a scaffold as usable.
"""

import gzip
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from spatialmind.app import review
from spatialmind.app.server import create_studio_app

N_CELLS = 600


def write_bundle(root, name="Synthetic_Section_outs"):
    """A minimal bundle: the four assets the gate checks, plus a cell table."""
    bundle = os.path.join(root, name)
    os.makedirs(bundle, exist_ok=True)
    with open(os.path.join(bundle, "experiment.xenium"), "w") as handle:
        json.dump({"run_name": name, "panel_name": "synthetic_20g", "pixel_size": 0.2125}, handle)
    with gzip.open(os.path.join(bundle, "cells.csv.gz"), "wt", newline="") as handle:
        handle.write("cell_id,x_centroid,y_centroid,transcript_counts\n")
        for i in range(N_CELLS):
            # Two spatial halves, so a rectangle can select exactly half the section.
            x = (i % 30) * 10.0
            y = float(i // 30) * 10.0
            handle.write("cell-%d,%.2f,%.2f,%d\n" % (i, x, y, 50 + (i % 40)))
    for asset in ("cell_feature_matrix.h5", "morphology_focus.ome.tif", "cell_boundaries.parquet"):
        with open(os.path.join(bundle, asset), "wb") as handle:
            handle.write(b"\0")
    return bundle


class NumbaCacheTests(unittest.TestCase):
    """Compiled kernels have to be cached somewhere the user can write.

    scanpy's Moran's I and neighbour kernels are `@numba.njit(cache=True)`, and
    numba writes that cache into `__pycache__` beside the installed package. In
    a checkout that is the virtualenv and it works silently. Inside a `.app` in
    /Applications it is owned by the installer and not writable by the person
    running it, so numba recompiles on every launch: measured at 35 seconds
    before the first result, on every analysis, forever.
    """

    def setUp(self):
        self._previous_cache = os.environ.pop("NUMBA_CACHE_DIR", None)
        self._previous_support = os.environ.get("SPATIALMIND_SUPPORT_DIR")
        self.root = tempfile.mkdtemp(prefix="numba-cache-test-")
        os.environ["SPATIALMIND_SUPPORT_DIR"] = self.root

    def tearDown(self):
        if self._previous_cache is None:
            os.environ.pop("NUMBA_CACHE_DIR", None)
        else:
            os.environ["NUMBA_CACHE_DIR"] = self._previous_cache
        if self._previous_support is None:
            os.environ.pop("SPATIALMIND_SUPPORT_DIR", None)
        else:
            os.environ["SPATIALMIND_SUPPORT_DIR"] = self._previous_support
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_writable_cache_directory_is_chosen_and_created(self):
        """In a fresh interpreter, which is the only place it can work.

        Run in a subprocess on purpose: by the time the rest of this suite has
        run, scanpy has pulled numba in, and numba reads NUMBA_CACHE_DIR once at
        import. Asserting this in-process would be asserting against whatever
        happened to be imported first.
        """
        script = (
            "import json, os, sys\n"
            "sys.path.insert(0, %r)\n"
            "from spatialmind.app import config\n"
            "chosen = config.configure_numba_cache()\n"
            "print(json.dumps({'chosen': chosen, 'env': os.environ.get('NUMBA_CACHE_DIR'),\n"
            "                  'numba_imported': 'numba' in sys.modules}))\n"
            % str(Path(__file__).resolve().parents[1])
        )
        env = dict(os.environ, SPATIALMIND_SUPPORT_DIR=self.root)
        env.pop("NUMBA_CACHE_DIR", None)
        out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout.strip().splitlines()[-1])

        self.assertFalse(result["numba_imported"], "configuring after numba loads would be a no-op")
        self.assertIsNotNone(result["chosen"])
        self.assertTrue(os.path.isdir(result["chosen"]), result["chosen"])
        self.assertTrue(os.access(result["chosen"], os.W_OK), "numba needs to be able to write here")
        self.assertEqual(result["env"], result["chosen"])

    def test_it_says_so_rather_than_pretending_once_numba_is_loaded(self):
        """Setting the variable after the import does nothing, so claiming a
        cache directory then would be a false report."""
        import numba  # noqa: F401  -- guaranteed in sys.modules from here
        from spatialmind.app import config

        self.assertIsNone(config.configure_numba_cache())

    def test_an_explicit_setting_is_left_alone(self):
        """Someone who pointed numba somewhere on purpose keeps it."""
        from spatialmind.app import config

        os.environ["NUMBA_CACHE_DIR"] = "/somewhere/deliberate"
        self.assertEqual(config.configure_numba_cache(), "/somewhere/deliberate")

    def test_the_frozen_entry_point_sets_it_before_importing_anything_heavy(self):
        """numba reads this at import time, so ordering is the whole point: a
        call placed after the first `import scanpy` does nothing at all."""
        entry = Path(__file__).resolve().parents[1] / "packaging" / "entry.py"
        text = entry.read_text(encoding="utf-8")
        self.assertIn("configure_numba_cache", text)
        self.assertLess(
            text.index("configure_numba_cache()"),
            text.index("from spatialmind.app.desktop import main"),
            "the cache has to be configured before anything that imports numba",
        )


class KernelWarmupTests(unittest.TestCase):
    """Compilation cannot be avoided in a frozen app, so it is moved off the wait.

    numba caching does not survive PyInstaller: a bundled module's `__file__`
    points into the archive, numba cannot build the source stamp its cache index
    needs, and it silently stops caching whatever NUMBA_CACHE_DIR says. So the
    kernels compile on every launch either way. Running the same tools once over
    120 synthetic cells compiles the same specialisations a real section needs,
    and doing it while the window is up spends that time against the user's own
    reading rather than their first progress bar.
    """

    def setUp(self):
        from spatialmind.app import warmup

        self.warmup = warmup
        warmup._done = False
        self._previous = os.environ.pop("SPATIALMIND_NO_WARMUP", None)

    def tearDown(self):
        self.warmup._done = False
        if self._previous is not None:
            os.environ["SPATIALMIND_NO_WARMUP"] = self._previous
        else:
            os.environ.pop("SPATIALMIND_NO_WARMUP", None)

    def test_the_warmup_plan_only_names_tools_this_build_has(self):
        """A plan naming a tool that is not registered would warm nothing and
        log a skip on every launch."""
        from spatialmind.tools import build_default_registry

        plannable = {tool.name for tool in build_default_registry().list_plannable()}
        for step in self.warmup.WARMUP_PLAN:
            self.assertIn(step["tool"], plannable, "warmup plan is out of step with the registry")

    def test_it_compiles_the_kernels_and_reports_what_it_did(self):
        outcome = self.warmup.warm_kernels()
        self.assertEqual(outcome["skipped"], [], "the warmup plan did not run cleanly")
        self.assertEqual(
            sorted(outcome["compiled"]),
            sorted(step["tool"] for step in self.warmup.WARMUP_PLAN),
        )

    def test_the_warmup_leaves_nothing_of_its_own_in_the_matrix_cache(self):
        """Its synthetic section must not be what a real run finds cached."""
        from spatialmind.tools import implementations

        self.warmup.warm_kernels()
        self.assertIsNone(implementations._ANNDATA_CACHE["adata"],
                          "a warmup matrix was left in the cache")

    def test_it_runs_once(self):
        first = self.warmup.start_background_warmup()
        second = self.warmup.start_background_warmup()
        self.assertIsNotNone(first)
        self.assertIsNone(second, "the warmup must not run again on a second call")
        first.join(timeout=180)
        self.assertFalse(first.is_alive(), "warmup thread did not finish")

    def test_it_can_be_turned_off(self):
        os.environ["SPATIALMIND_NO_WARMUP"] = "1"
        self.assertIsNone(self.warmup.start_background_warmup())

    def test_a_failing_warmup_is_not_a_failing_app(self):
        """A slower first analysis, never a crash on launch."""
        with patch.object(self.warmup, "_synthetic_dataset", side_effect=RuntimeError("boom")):
            outcome = self.warmup.warm_kernels()
        self.assertEqual(outcome["compiled"], [])
        self.assertEqual(len(outcome["skipped"]), len(self.warmup.WARMUP_PLAN))


class ReadOnlyBundleTests(unittest.TestCase):
    """Instrument output is not always writable, and the review has to survive it.

    A core facility hands over `outs/` on read-only media, on a share mounted
    read-only, or in an archived directory. Writing the review straight into the
    bundle met that with an unhandled `PermissionError` naming a temporary file
    that no longer existed: HTTP 500, no explanation, and the reviewer's work
    gone. The review now falls back to a sidecar under the app's support folder,
    and -- the part that actually matters -- the gate and the run read it, so the
    app cannot show a satisfied gate backed by tables nothing loads.
    """

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="spatialmind-readonly-test-")
        cls.support = os.path.join(cls.root, "support")
        # Without this the sidecar lands in the real ~/Library/Application Support.
        cls._previous_support = os.environ.get("SPATIALMIND_SUPPORT_DIR")
        os.environ["SPATIALMIND_SUPPORT_DIR"] = cls.support
        cls.data_root = os.path.join(cls.root, "data")
        os.makedirs(cls.data_root)
        cls.bundle = write_bundle(cls.data_root, name="ReadOnly_Section_outs")
        cls.app = create_studio_app(
            data_root=cls.data_root, output_root=os.path.join(cls.root, "outputs"))
        cls.client = TestClient(cls.app)
        cls.dataset_id = cls.client.get("/api/datasets").json()["datasets"][0]["dataset_id"]

    @classmethod
    def tearDownClass(cls):
        os.chmod(cls.bundle, 0o755)
        if cls._previous_support is None:
            os.environ.pop("SPATIALMIND_SUPPORT_DIR", None)
        else:
            os.environ["SPATIALMIND_SUPPORT_DIR"] = cls._previous_support
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        os.chmod(self.bundle, 0o755)
        for kind in ("labels", "regions"):
            self.client.post("/api/datasets/%s/clear" % self.dataset_id, json={"kind": kind})
        for name in ("expert_cell_labels.csv", "cell_regions.csv"):
            for directory in (self.bundle, review.sidecar_dir(self.bundle)):
                candidate = Path(directory) / name
                if candidate.exists():
                    candidate.unlink()

    def _freeze(self):
        os.chmod(self.bundle, stat.S_IRUSR | stat.S_IXUSR)

    def test_a_review_on_a_read_only_bundle_is_saved_and_says_where(self):
        self._freeze()
        body = self.client.post(
            "/api/datasets/%s/assign" % self.dataset_id,
            json={"kind": "labels", "value": "Astrocyte",
                  "cell_ids": ["cell-%d" % i for i in range(20)]})
        self.assertEqual(body.status_code, 200, body.text)
        assignment = body.json()["assignment"]
        self.assertEqual(assignment["location"], "app_support")
        self.assertTrue(assignment["path"].startswith(self.support), assignment["path"])
        self.assertFalse(os.path.exists(os.path.join(self.bundle, "expert_cell_labels.csv")))

    def test_the_gate_counts_a_review_that_had_to_go_to_the_sidecar(self):
        """The failure worth preventing: a gate that opens on tables no run reads."""
        self._freeze()
        ids = ["cell-%d" % i for i in range(N_CELLS)]
        self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                         json={"kind": "labels", "value": "Astrocyte", "cell_ids": ids[: N_CELLS // 2]})
        self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                         json={"kind": "labels", "value": "T cell", "cell_ids": ids[N_CELLS // 2:]})
        bounds = self.client.get("/api/datasets/%s/cells" % self.dataset_id).json()["bounds"]
        mid = (bounds["y_min"] + bounds["y_max"]) / 2.0
        self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                         json={"kind": "regions", "value": "core",
                               "bounds": {"x0": bounds["x_min"], "y0": bounds["y_min"],
                                          "x1": bounds["x_max"], "y1": mid}})
        body = self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                                json={"kind": "regions", "value": "edge",
                                      "bounds": {"x0": bounds["x_min"], "y0": mid,
                                                 "x1": bounds["x_max"], "y1": bounds["y_max"]}}).json()
        self.assertEqual(body["gate"]["status"], "validated_ready", body["gate"]["blocking_reasons"])
        self.assertGreater(body["label_coverage"]["coverage"], 0.9)

    def test_a_table_already_in_the_bundle_is_never_shadowed(self):
        """A reviewed table in the bundle is the truth even once the folder turns
        read-only; a sidecar that quietly took precedence would silently discard
        it."""
        in_bundle = Path(self.bundle) / "expert_cell_labels.csv"
        in_bundle.write_text(
            "cell_id,expert_label,confidence,notes,assignment_scope\n"
            "cell-0,Hand written,0.99,,cells\n",
            encoding="utf-8")
        self._freeze()
        self.assertEqual(str(review.table_path(self.bundle, "labels")), str(in_bundle))
        self.assertEqual(review.read_table(self.bundle, "labels")["cell-0"]["expert_label"], "Hand written")

    def test_a_write_that_cannot_land_anywhere_explains_itself(self):
        """The sidecar can fail too. What must not happen is a bare 500."""
        self._freeze()
        with patch("spatialmind.app.review._write_atomic_unguarded",
                   side_effect=OSError(28, "No space left on device")):
            response = self.client.post(
                "/api/datasets/%s/assign" % self.dataset_id,
                json={"kind": "labels", "value": "Astrocyte", "cell_ids": ["cell-1"]})
        self.assertEqual(response.status_code, 507, response.text)
        detail = response.json()["detail"]
        self.assertIn("Could not save the review", detail)
        self.assertIn("read-only, full, or on a disconnected volume", detail)


class StudioAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="spatialmind-studio-test-")
        cls.data_root = os.path.join(cls.root, "data")
        cls.output_root = os.path.join(cls.root, "outputs")
        os.makedirs(cls.data_root)
        cls.bundle = write_bundle(cls.data_root)
        cls.app = create_studio_app(data_root=cls.data_root, output_root=cls.output_root)
        cls.client = TestClient(cls.app)
        payload = cls.client.get("/api/datasets").json()
        cls.dataset_id = payload["datasets"][0]["dataset_id"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        # One job runs at a time per process, so a job left running by an earlier
        # test makes the next submission 409 for the wrong reason.
        deadline = time.time() + 30
        while time.time() < deadline:
            jobs = self.client.get("/api/runs").json()["jobs"]
            if not any(job["state"] in {"queued", "running"} for job in jobs):
                break
            time.sleep(0.05)
        for kind in ("labels", "regions"):
            self.client.post("/api/datasets/%s/clear" % self.dataset_id, json={"kind": kind})
        self.client.delete("/api/datasets/%s/context" % self.dataset_id)

    # ------------------------------------------------------------------ basics

    def test_health_reports_roots_and_registry(self):
        body = self.client.get("/api/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertGreaterEqual(body["capability_summary"].get("validated", 0), 1)
        self.assertGreaterEqual(body["capability_summary"].get("unavailable", 0), 1)

    def test_startup_defers_the_folder_scan(self):
        """The app must bind a port before it reads any folder.

        On macOS the first read of ~/Documents, ~/Desktop or ~/Downloads blocks
        until the user answers a consent prompt. Scanning during startup blocked
        the packaged app before it served anything: no window, no error, and a
        log that stopped mid-boot.
        """
        app = create_studio_app(data_root=self.data_root, output_root=self.output_root)
        client = TestClient(app)
        body = client.get("/api/health").json()
        self.assertFalse(body["scanned"], "startup must not scan the data root")
        self.assertEqual(body["datasets"], 0)
        listing = client.get("/api/datasets").json()
        self.assertEqual(len(listing["datasets"]), 1, "the first listing performs the scan")
        self.assertTrue(client.get("/api/health").json()["scanned"])

    def test_health_reports_window_mode_so_the_page_need_not_guess(self):
        """The page leaves room for the traffic lights only in a native window.

        It used to infer that from the user agent, which is guesswork that breaks
        whenever WebKit changes its string. The launcher sets the flag; the page
        reads it.
        """
        body = self.client.get("/api/health").json()
        self.assertIn("window_mode", body)
        self.assertFalse(body["window_mode"], "a bare server is not a window")

    def test_dataset_names_are_readable_without_losing_the_original(self):
        listing = self.client.get("/api/datasets").json()["datasets"][0]
        self.assertEqual(listing["name"], "Synthetic_Section_outs")
        self.assertEqual(listing["display_name"], "Synthetic Section")
        self.assertIn("relative_path", listing)

    def test_resources_endpoint_reports_what_labelling_still_needs(self):
        body = self.client.get("/api/resources").json()
        ids = {r["id"] for r in body["requirements"]}
        self.assertIn("reviewer", ids)
        self.assertIn("reference_malignant", ids)
        for requirement in body["requirements"]:
            self.assertIn(requirement["status"], {"have", "partial", "missing"})
            if requirement["status"] != "have":
                self.assertTrue(requirement["action"], "%s must say what to do" % requirement["id"])
        # No references in the fixture folder, so the normal-lineage row cannot claim coverage.
        self.assertEqual(body["references"], [])
        self.assertIn("reference_normal", body["outstanding"])

    def test_panel_ceiling_is_reported_before_any_labelling(self):
        """The panel caps reliability, and a reviewer should know before they start.

        In the last validated run every claim was limited by P_panel at 0.67
        while statistics, annotation and robustness scored 1.00, 0.86 and 0.96.
        Reliability is a weakest-link score, so perfect labels cannot raise it.
        """
        from spatialmind.app.resources import panel_adequacy

        # The fixture bundle carries no gene_panel.json, so the ceiling is unknown
        # rather than silently assumed.
        self.assertFalse(panel_adequacy(self.bundle).get("available"))
        body = self.client.get("/api/resources").json()
        panel = [r for r in body["requirements"] if r["id"] == "panel"]
        self.assertEqual(len(panel), 1, "the panel ceiling must always be reported")
        self.assertTrue(panel[0]["detail"])

    def test_scan_status_flags_a_permission_protected_root(self):
        from spatialmind.app.server import _is_protected_folder

        home = os.path.expanduser("~")
        self.assertTrue(_is_protected_folder(os.path.join(home, "Documents", "x")))
        self.assertTrue(_is_protected_folder(os.path.join(home, "Desktop")))
        self.assertFalse(_is_protected_folder(os.path.join(home, "SpatialMind", "data")))
        self.assertFalse(_is_protected_folder(self.data_root))

    def test_discovery_finds_the_bundle_and_marks_it_reviewable(self):
        body = self.client.get("/api/datasets").json()
        self.assertEqual(len(body["datasets"]), 1)
        self.assertTrue(body["datasets"][0]["reviewable"])
        self.assertEqual(body["datasets"][0]["data_type"], "xenium_directory")

    def test_unknown_dataset_is_404(self):
        self.assertEqual(self.client.get("/api/datasets/nope-00000000").status_code, 404)

    def test_cells_endpoint_returns_aligned_arrays(self):
        body = self.client.get("/api/datasets/%s/cells" % self.dataset_id).json()
        self.assertEqual(body["n_cells"], N_CELLS)
        for key in ("x", "y", "cluster", "label", "region"):
            self.assertEqual(len(body[key]), body["displayed"], "%s is out of step" % key)
        self.assertIn("x_min", body["bounds"])

    # ------------------------------------------------------------------ the gate

    def test_gate_starts_blocked_with_actionable_reasons(self):
        body = self.client.get("/api/datasets/%s" % self.dataset_id).json()
        gate = body["gate"]
        self.assertEqual(gate["status"], "blocked_missing_validation_inputs")
        self.assertTrue(gate["blocking_reasons"])
        failed = [c for c in gate["checks"] if not c["ok"]]
        self.assertTrue(failed, "a blocked gate must fail at least one check")
        for check in failed:
            self.assertTrue(check["action"], "every blocker must name the action that clears it")

    def test_assigning_labels_and_regions_opens_the_gate(self):
        cells = self.client.get("/api/datasets/%s/cells" % self.dataset_id).json()
        ids = ["cell-%d" % i for i in range(N_CELLS)]

        first = self.client.post(
            "/api/datasets/%s/assign" % self.dataset_id,
            json={"kind": "labels", "value": "Astrocyte", "cell_ids": ids[: N_CELLS // 2]},
        ).json()
        self.assertEqual(first["assignment"]["cells_written"], N_CELLS // 2)
        # One class over half the section is not enough on either count.
        self.assertNotEqual(first["gate"]["status"], "validated_ready")

        self.client.post(
            "/api/datasets/%s/assign" % self.dataset_id,
            json={"kind": "labels", "value": "Oligodendrocyte", "cell_ids": ids[N_CELLS // 2:]},
        )
        bounds = cells["bounds"]
        mid = (bounds["y_min"] + bounds["y_max"]) / 2.0
        self.client.post(
            "/api/datasets/%s/assign" % self.dataset_id,
            json={"kind": "regions", "value": "tumor_core",
                  "bounds": {"x0": bounds["x_min"], "y0": bounds["y_min"], "x1": bounds["x_max"], "y1": mid}},
        )
        final = self.client.post(
            "/api/datasets/%s/assign" % self.dataset_id,
            json={"kind": "regions", "value": "cortex_normal",
                  "bounds": {"x0": bounds["x_min"], "y0": mid, "x1": bounds["x_max"], "y1": bounds["y_max"]}},
        ).json()

        self.assertEqual(final["gate"]["status"], "validated_ready")
        self.assertGreaterEqual(final["label_coverage"]["coverage"], 0.7)
        self.assertGreaterEqual(final["region_coverage"]["coverage"], 0.7)
        self.assertTrue(os.path.exists(os.path.join(self.bundle, "expert_cell_labels.csv")))
        self.assertTrue(os.path.exists(os.path.join(self.bundle, "cell_regions.csv")))

    def test_clearing_closes_the_gate_again(self):
        ids = ["cell-%d" % i for i in range(N_CELLS)]
        self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                         json={"kind": "labels", "value": "Astrocyte", "cell_ids": ids})
        body = self.client.post("/api/datasets/%s/clear" % self.dataset_id, json={"kind": "labels"}).json()
        self.assertEqual(body["label_coverage"]["coverage"], 0.0)
        self.assertNotEqual(body["gate"]["status"], "validated_ready")
        self.assertFalse(os.path.exists(os.path.join(self.bundle, "expert_cell_labels.csv")))

    def test_assignment_merges_rather_than_overwrites(self):
        ids = ["cell-%d" % i for i in range(N_CELLS)]
        self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                         json={"kind": "labels", "value": "Astrocyte", "cell_ids": ids[:100]})
        second = self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                                  json={"kind": "labels", "value": "T cell", "cell_ids": ids[100:150]}).json()
        self.assertEqual(second["assignment"]["rows_total"], 150)
        self.assertEqual(sorted(second["assignment"]["distinct_values"]), ["Astrocyte", "T cell"])

    def test_empty_selection_is_rejected(self):
        response = self.client.post(
            "/api/datasets/%s/assign" % self.dataset_id,
            json={"kind": "labels", "value": "Astrocyte",
                  "bounds": {"x0": 1e9, "y0": 1e9, "x1": 1e9 + 1, "y1": 1e9 + 1}},
        )
        self.assertEqual(response.status_code, 400)

    def test_blank_value_is_rejected(self):
        response = self.client.post(
            "/api/datasets/%s/assign" % self.dataset_id,
            json={"kind": "labels", "value": "   ", "cell_ids": ["cell-1"]},
        )
        self.assertEqual(response.status_code, 400)

    # ------------------------------------------------------------------ the gate as an invariant

    def _open_the_gate(self):
        ids = ["cell-%d" % i for i in range(N_CELLS)]
        self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                         json={"kind": "labels", "value": "Astrocyte", "cell_ids": ids[: N_CELLS // 2]})
        self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                         json={"kind": "labels", "value": "Oligodendrocyte", "cell_ids": ids[N_CELLS // 2:]})
        bounds = self.client.get("/api/datasets/%s/cells" % self.dataset_id).json()["bounds"]
        mid = (bounds["y_min"] + bounds["y_max"]) / 2.0
        self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                         json={"kind": "regions", "value": "core",
                               "bounds": {"x0": bounds["x_min"], "y0": bounds["y_min"],
                                          "x1": bounds["x_max"], "y1": mid}})
        return self.client.post("/api/datasets/%s/assign" % self.dataset_id,
                                json={"kind": "regions", "value": "edge",
                                      "bounds": {"x0": bounds["x_min"], "y0": mid,
                                                 "x1": bounds["x_max"], "y1": bounds["y_max"]}}).json()

    def test_the_api_refuses_a_gated_tool_while_the_gate_is_shut(self):
        """The UI declining to send one is not the same as the server refusing.

        This endpoint accepted region_summary against a blocked section and
        started the job. The gate was a convention in the client, which means it
        was not a guarantee at all: anything driving the API directly -- a
        script, a notebook, a second front end -- walked straight past it.
        """
        response = self.client.post("/api/runs", json={
            "dataset_id": self.dataset_id, "kind": "plan", "tools": ["region_summary"]})
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["error"], "gate_blocked")
        self.assertIn("region_summary", detail["gated_tools"])
        self.assertTrue(detail["blocking_reasons"])

    def test_the_descriptive_lane_still_runs_while_the_gate_is_shut(self):
        """Refusing everything would be safe and useless."""
        response = self.client.post("/api/runs", json={
            "dataset_id": self.dataset_id, "kind": "plan", "tools": ["qc_and_cluster"]})
        self.assertNotEqual(response.status_code, 409,
                            "a descriptive plan must not be refused: %s" % response.text)
        self.assertEqual(response.status_code, 200, response.text)

    def test_a_gated_tool_is_accepted_once_the_gate_opens(self):
        opened = self._open_the_gate()
        self.assertEqual(opened["gate"]["status"], "validated_ready")
        response = self.client.post("/api/runs", json={
            "dataset_id": self.dataset_id, "kind": "plan", "tools": ["region_summary"]})
        self.assertNotEqual(response.status_code, 409,
                            "the gate is open; a gated tool must no longer be refused")

    def test_an_unknown_tool_name_does_not_slip_past_the_gate(self):
        from spatialmind.gatekeeper import gated_tool_names

        # Legacy AlgorithmEngine tools are not in the registry but name cell types.
        self.assertIn("cell_type_colocalization", gated_tool_names(["cell_type_colocalization"]))

    def test_non_xenium_data_is_recorded_as_unevaluated_not_as_passing(self):
        """The gate cannot be evaluated off a Xenium bundle. That is not a pass."""
        from spatialmind.gatekeeper import require_gate_open

        decision = require_gate_open(self.root, ["region_summary"])
        self.assertEqual(decision["status"], "gate_not_evaluated")
        self.assertIn("region_summary", decision["gated_tools"])
        self.assertIn("not gate-validated", decision["caveat"])

    # ------------------------------------------------------------------ dataset context

    def test_context_round_trips_and_is_attributed(self):
        payload = {"tissue": "human cortex", "fixation": "FFPE, 3-year-old block",
                   "expected_cell_types": ["astrocyte", "T cell"],
                   "question": "Is there immune infiltration?", "author": "K. Zhang"}
        saved = self.client.post("/api/datasets/%s/context" % self.dataset_id, json=payload).json()
        self.assertEqual(saved["context"]["tissue"], "human cortex")
        self.assertTrue(saved["context"]["recorded_at"], "context must record when it was written")

        fetched = self.client.get("/api/datasets/%s/context" % self.dataset_id).json()
        self.assertEqual(fetched["context"]["author"], "K. Zhang")
        self.assertTrue(all("K. Zhang" in line for line in fetched["caveats"]),
                        "every caveat must name who supplied it")
        self.assertTrue(all("not independently verified" in line for line in fetched["caveats"]))

    def test_context_cannot_move_the_gate(self):
        """The obvious way around a review requirement is to assert past it.

        Context is typed and scoped precisely so a sentence cannot do what
        labelling 1,600 cells does. This asserts the strongest version: a
        submitter claiming the tissue is fully characterised, naming cell types
        and regions, must leave the gate exactly where it was.
        """
        before = self.client.get("/api/datasets/%s" % self.dataset_id).json()["gate"]
        self.client.post("/api/datasets/%s/context" % self.dataset_id, json={
            "tissue": "human cortex",
            "condition": "glioblastoma with abundant malignant cells throughout",
            "expected_cell_types": ["malignant cell", "astrocyte", "T cell", "oligodendrocyte"],
            "known_artifacts": "none, this section is fully characterised",
            "author": "an optimistic submitter"})
        after = self.client.get("/api/datasets/%s" % self.dataset_id).json()["gate"]

        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["label_coverage"], before["label_coverage"])
        self.assertEqual(after["region_coverage"], before["region_coverage"])
        self.assertEqual(after["cell_classes"], before["cell_classes"],
                         "expected cell types must not become reviewed classes")

    def test_context_does_not_become_a_label(self):
        self.client.post("/api/datasets/%s/context" % self.dataset_id, json={
            "expected_cell_types": ["astrocyte", "malignant cell"], "author": "submitter"})
        coverage = self.client.get("/api/datasets/%s" % self.dataset_id).json()["label_coverage"]
        self.assertEqual(coverage["coverage"], 0.0, "an expectation created label coverage")
        self.assertFalse(coverage["values"], "an expectation became a label value")

    def test_expected_types_are_offered_for_review_without_being_assigned(self):
        """An expectation reaches the reviewer as an ordering, not as a label.

        The chip that appears first assigns exactly what any other chip assigns,
        and only when a human clicks it. Until then coverage stays at zero.
        """
        self.client.post("/api/datasets/%s/context" % self.dataset_id, json={
            "expected_cell_types": ["Microglial cell", "T cell"], "author": "submitter"})
        context = self.client.get("/api/datasets/%s/context" % self.dataset_id).json()
        self.assertEqual(context["review_priorities"], ["Microglial cell", "T cell"])

        detail = self.client.get("/api/datasets/%s" % self.dataset_id).json()
        self.assertEqual(detail["label_coverage"]["coverage"], 0.0,
                         "offering a type for review assigned it")
        self.assertEqual(detail["gate"]["cell_classes"], [])

    def test_report_limitations_carry_context_attributed(self):
        from spatialmind.dataset_context import DatasetContext
        from spatialmind.pilot.xenium import _limitations

        context = DatasetContext(fixation="FFPE, 3-year-old block",
                                 expected_cell_types=["astrocyte"], author="K. Zhang")
        payload = {"features_loaded": 300,
                   "label_report": {"status": "missing"}, "region_report": {"status": "missing"},
                   "user_context": context.to_dict(), "user_context_caveats": context.caveats()}
        lines = _limitations(payload)
        self.assertTrue(any("K. Zhang" in line and "not independently verified" in line for line in lines),
                        "a specimen fact reached the report without attribution")
        self.assertTrue(any("not evidence" in line and "astrocyte" in line for line in lines),
                        "an expectation reached the report without being marked as one")

    def test_a_gated_tool_is_still_refused_with_context_present(self):
        self.client.post("/api/datasets/%s/context" % self.dataset_id, json={
            "condition": "fully annotated by the submitter",
            "expected_cell_types": ["astrocyte", "T cell"], "author": "submitter"})
        response = self.client.post("/api/runs", json={
            "dataset_id": self.dataset_id, "kind": "plan", "tools": ["region_summary"]})
        self.assertEqual(response.status_code, 409,
                         "context let a gated tool through: %s" % response.text[:120])

    def test_unreadable_context_does_not_break_the_dataset(self):
        from spatialmind.dataset_context import context_path, load_context

        path = context_path(self.bundle)
        path.write_text("{ this is not json", encoding="utf-8")
        try:
            self.assertTrue(load_context(self.bundle).is_empty)
            body = self.client.get("/api/datasets/%s" % self.dataset_id)
            self.assertEqual(body.status_code, 200, "a corrupt context file broke the dataset")
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------ tools

    def test_catalog_lists_scaffolds_but_never_marks_them_plannable(self):
        body = self.client.get("/api/tools?dataset_id=%s" % self.dataset_id).json()
        tools = body["tools"]
        self.assertGreaterEqual(len(tools), 20)
        scaffolds = [t for t in tools if t["capability"] == "unavailable"]
        self.assertTrue(scaffolds)
        for tool in scaffolds:
            self.assertFalse(tool["plannable"], "%s is a scaffold and must not be plannable" % tool["name"])
            self.assertEqual(tool["lane"], "unavailable")

    def test_lane_is_blocked_for_label_gated_tools_while_the_gate_is_shut(self):
        body = self.client.get("/api/tools?dataset_id=%s" % self.dataset_id).json()
        by_name = {t["name"]: t for t in body["tools"]}
        self.assertEqual(by_name["region_summary"]["lane"], "blocked")
        self.assertEqual(by_name["annotation"]["lane"], "blocked")
        self.assertEqual(by_name["qc_and_cluster"]["lane"], "descriptive")
        self.assertEqual(by_name["spatial_variable_genes"]["lane"], "descriptive")

    # ------------------------------------------------------------------ planning

    def test_plan_inserts_missing_dependencies_in_order(self):
        body = self.client.post("/api/plan", json={"dataset_id": self.dataset_id, "tools": ["marker_detection"]}).json()
        names = [s["tool"] for s in body["steps"]]
        self.assertEqual(names[0], "qc_and_cluster")
        self.assertIn("annotation", names)
        self.assertEqual(names[-1], "marker_detection")
        self.assertEqual(body["plan_status"], "valid")

    def test_blocked_plan_still_validates_as_structurally_sound(self):
        body = self.client.post("/api/plan", json={"dataset_id": self.dataset_id, "tools": ["region_summary"]}).json()
        self.assertEqual(body["plan_status"], "valid", "the gate blocks inputs; it must not fake plan errors")
        self.assertGreaterEqual(body["blocked_steps"], 1)

    def test_cluster_grouping_keeps_marker_detection_in_the_descriptive_lane(self):
        body = self.client.post(
            "/api/plan",
            json={"dataset_id": self.dataset_id, "tools": ["marker_detection"],
                  "overrides": {"marker_detection": {"group_key": "leiden"}}},
        ).json()
        marker = [s for s in body["steps"] if s["tool"] == "marker_detection"][0]
        self.assertEqual(marker["lane"], "descriptive")

    # ------------------------------------------------------------------ ask

    def test_ask_refuses_when_the_only_tool_is_a_scaffold(self):
        body = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id, "question": "Find the malignant cells by copy number."}).json()
        self.assertEqual(body["tools"], [])
        self.assertIsNotNone(body["refusal"])
        self.assertIn("cnv_inference", body["refusal"])

    def test_ask_routes_a_spatial_question_to_the_descriptive_lane(self):
        body = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id, "question": "Which genes are spatially structured?"}).json()
        self.assertIn("spatial_variable_genes", body["tools"])
        lanes = {s["tool"]: s["lane"] for s in body["plan"]["steps"]}
        self.assertEqual(lanes["spatial_variable_genes"], "descriptive")

    def test_ask_says_so_rather_than_guessing(self):
        body = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id, "question": "What is the weather in Oslo?"}).json()
        self.assertEqual(body["tools"], [])

    def test_a_refusal_never_names_a_tool_on_one_ordinary_word(self):
        """The refusal has to be a reading of the question, not a substring hit.

        "healthy" was a keyword for `multi_sample_comparison`, so asking what a
        section named "Healthy Brain" looks like was answered "the tool for it
        (multi_sample_comparison) is a scaffold" -- specific, confident and
        wrong. For an app whose entire claim is that it refuses rather than
        guesses, a refusal that misidentifies its own reason is the worst
        available failure.
        """
        body = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id,
            "question": "What does this healthy brain section look like?"}).json()
        self.assertIsNone(body["refusal"], body["answer"])
        self.assertIn("qc_and_cluster", body["tools"])

    def test_a_decisive_phrase_still_names_the_scaffold(self):
        """Softening the ambiguous words must not cost the diagnosis that works."""
        body = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id,
            "question": "Show the difference across samples and between donors."}).json()
        self.assertEqual(body["tools"], [])
        self.assertIn("multi_sample_comparison", body["refusal"] or "")

    def test_a_mixed_question_answers_its_answerable_half_and_names_the_rest(self):
        """"Cell type abundance across samples" is one question the app can
        partly do: the within-section half routes, and the cross-sample half is
        named as a scaffold rather than quietly folded into the answer."""
        body = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id,
            "question": "Compare cell type abundance across samples."}).json()
        self.assertIn("annotation", body["tools"])
        self.assertIn("multi_sample_comparison", body["refusal"] or "")
        self.assertIn("scaffold", body["answer"])

    def test_a_suggestive_word_is_offered_as_a_guess_not_a_finding(self):
        body = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id,
            "question": "How good is the cell segmentation here?"}).json()
        self.assertIsNone(body["refusal"], body["answer"])
        self.assertEqual(body["possible_scaffolds"], ["tissue_segmentation"])
        self.assertIn("if you meant", body["answer"].lower())
        self.assertIn("guessing", body["answer"].lower())

    def test_the_most_natural_cell_question_has_a_route(self):
        """`Which cell populations are present?` fell through to "no route"."""
        body = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id,
            "question": "Which cell populations are present?"}).json()
        self.assertIn("annotation", body["tools"])

    def test_a_keyword_does_not_match_inside_a_longer_word(self):
        """"near" matched inside "linear" and "nearly", and bare "near" matched
        "near the top of the section" -- a question about position, routed to a
        permutation test on the spatial graph."""
        body = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id,
            "question": "Are any genes near the top of the section?"}).json()
        self.assertNotIn("cell_neighborhood_enrichment", body["tools"])

        adjacency = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id,
            "question": "Which cells sit near each other?"}).json()
        self.assertIn("cell_neighborhood_enrichment", adjacency["tools"])

    def test_both_routing_surfaces_agree(self):
        """Ask and the guided workflow had their own copies of the match, so a
        keyword fixed in one stayed broken in the other."""
        question = "What does this healthy brain section look like?"
        ask = self.client.post("/api/ask", json={
            "dataset_id": self.dataset_id, "question": question}).json()
        analyze = self.client.post("/api/workflow/analyze", json={
            "dataset_id": self.dataset_id, "prompt": question}).json()
        self.assertIsNone(ask["refusal"])
        self.assertNotEqual(analyze["status"], "unsupported", analyze["not_supported"])

    # ------------------------------------------------------------------ runs

    def test_run_requires_at_least_one_tool(self):
        response = self.client.post("/api/runs", json={"dataset_id": self.dataset_id, "kind": "plan", "tools": []})
        self.assertEqual(response.status_code, 400)

    def test_static_app_is_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("SpatialMind Studio", response.text)

    def test_the_page_offers_every_tab_the_workflow_needs(self):
        """The home tabs and the Create button are the whole entry point; a
        rename in the markup that the JS does not follow is invisible until a
        user clicks."""
        page = self.client.get("/").text
        for marker in ('data-p="datasets"', 'data-p="tools"', 'data-p="visualization"',
                       'data-p="runs"', 'data-p="reports"', 'id="createBtn"', 'id="wizard"'):
            self.assertIn(marker, page, marker)

    # -------------------------------------------------------------- workflow

    def test_facts_describe_the_dataset_the_wizard_reasons_over(self):
        body = self.client.get("/api/workflow/facts",
                               params={"dataset_id": self.dataset_id}).json()
        self.assertEqual(body["n_cells"], N_CELLS)
        self.assertIn("gate_open", body)
        self.assertIn("panel_size", body)

    def test_suggested_questions_match_the_gate_state(self):
        """A blocked section offered a cell-type question would teach the user
        that the gate is arbitrary."""
        body = self.client.get("/api/workflow/questions",
                               params={"dataset_id": self.dataset_id}).json()
        self.assertTrue(body["questions"])
        if not body["gate_open"]:
            for question in body["questions"]:
                self.assertEqual(question["lane"], "descriptive", question["question"])

    def test_every_suggested_question_survives_the_round_trip(self):
        """The wizard sends a suggestion back to /analyze with its own tools. If
        that contract breaks, the app refuses a question it just offered."""
        questions = self.client.get("/api/workflow/questions",
                                    params={"dataset_id": self.dataset_id}).json()["questions"]
        for question in questions:
            body = self.client.post("/api/workflow/analyze", json={
                "dataset_id": self.dataset_id,
                "text": question["question"],
                "tools": question["tools"],
            }).json()
            self.assertEqual(body["status"], "understood", question["question"])
            self.assertTrue(body["tools"], question["question"])

    def test_the_workflow_plan_marks_gated_steps_rather_than_hiding_them(self):
        body = self.client.post("/api/workflow/plan", json={
            "dataset_id": self.dataset_id,
            "tools": ["qc_and_cluster", "region_summary"],
            "answers": {"group_key": "leiden"},
        }).json()
        lanes = {step["tool"]: step["lane"] for step in body["steps"]}
        self.assertEqual(lanes["qc_and_cluster"], "descriptive")
        self.assertEqual(lanes["region_summary"], "blocked")
        self.assertTrue(body["blocking_reasons"])

    # --------------------------------------------------------------- intake

    def test_an_upload_lands_in_the_data_root_and_is_described(self):
        response = self.client.post("/api/uploads", files=[
            ("files", ("notes.csv", b"cell_id,x,y\nc1,1,2\n", "text/csv")),
        ], data={"name": "uploaded_table", "paths": "notes.csv"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        try:
            self.assertEqual(body["status"], "stored")
            self.assertTrue(os.path.exists(body["path"]))
            # Resolved on both sides: on macOS the Studio resolves its data root
            # through the /var -> /private/var symlink and the temp path does not.
            self.assertTrue(str(Path(body["path"]).resolve())
                            .startswith(str(Path(self.data_root).resolve())))
            self.assertEqual(body["intake"]["data_type"], "tidy_csv")
        finally:
            # The data root is shared by every test in this class, and an upload
            # left behind changes the dataset count the discovery tests assert.
            shutil.rmtree(body.get("directory") or body["path"], ignore_errors=True)
            self.client.get("/api/datasets", params={"refresh": True})

    def test_an_empty_upload_is_refused(self):
        response = self.client.post("/api/uploads", files=[
            ("files", (".DS_Store", b"junk", "application/octet-stream")),
        ], data={"name": "junk", "paths": ".DS_Store"})
        self.assertEqual(response.status_code, 400)

    def test_linking_a_missing_folder_is_refused(self):
        response = self.client.post("/api/uploads/link", json={"path": "/no/such/folder"})
        self.assertEqual(response.status_code, 400)

    # -------------------------------------------------------------- reports

    def test_reports_list_reports_its_root_and_a_well_formed_list(self):
        # Not asserted empty: other tests in this class submit runs, and a test
        # that depends on running first is a test that fails on reordering.
        body = self.client.get("/api/reports").json()
        self.assertTrue(body["output_root"])
        self.assertIsInstance(body["reports"], list)
        for row in body["reports"]:
            self.assertIn("report_id", row)
            self.assertIn("title", row)
            self.assertIn("pinned", row)

    def test_unknown_report_actions_are_404_rather_than_500(self):
        self.assertEqual(self.client.get("/api/reports/nope").status_code, 404)
        self.assertEqual(self.client.post("/api/reports/nope/pin", json={"pinned": True}).status_code, 404)
        self.assertEqual(self.client.delete("/api/reports/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/reports/nope/export",
                                         params={"format": "docx"}).status_code, 404)

    def test_sizing_reports_the_decisions_that_would_open_the_gate(self):
        body = self.client.get("/api/datasets/%s/sizing" % self.dataset_id).json()
        self.assertTrue(body["sizable"])
        self.assertIn("total_decisions", body)
        self.assertIn(body["cluster_source"],
                      ("this dataset's descriptive run", "the bundle's own 10x clusters"))
        # No run has been done against this synthetic bundle, so the region side
        # is uncounted and the total must say it is a lower bound.
        self.assertFalse(body["total_is_complete"])

    def test_sizing_uses_the_newest_matching_run_not_the_first_by_name(self):
        """The output root accumulates runs, often several on one section at
        different sample sizes. Picking by name sized the glioblastoma review
        against an older, smaller run -- 4 decisions where the full section
        needs 5."""
        import time

        root = Path(self.output_root)
        for name, counts, when in (("aaa_old_run", {"0": 90, "1": 10}, 1_600_000_000),
                                   ("zzz_new_run", {"0": 40, "1": 35, "2": 25}, 1_900_000_000)):
            directory = root / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "pilot_validation.json").write_text(
                json.dumps({"dataset_path": self.bundle}), encoding="utf-8")
            marker = directory / "descriptive_qc_and_cluster.json"
            marker.write_text(json.dumps({"metrics": {"cluster_counts": counts}}),
                              encoding="utf-8")
            os.utime(marker, (when, when))
        try:
            body = self.client.get("/api/datasets/%s/sizing" % self.dataset_id).json()
            self.assertTrue(body["run_dir"].endswith("zzz_new_run"))
            # The newer run's three even clusters need two decisions for 70%;
            # the older run's 90/10 split needs one.
            self.assertEqual(body["labels"]["decisions"], 2)
        finally:
            for name in ("aaa_old_run", "zzz_new_run"):
                shutil.rmtree(root / name, ignore_errors=True)

    def test_sizing_refuses_a_dataset_that_is_not_gated(self):
        for entry in self.client.get("/api/datasets").json()["datasets"]:
            if entry["reviewable"]:
                continue
            body = self.client.get("/api/datasets/%s/sizing" % entry["dataset_id"]).json()
            self.assertFalse(body["sizable"])
            break

    def test_visualizations_endpoint_answers_with_a_well_formed_list(self):
        figures = self.client.get("/api/visualizations").json()["figures"]
        self.assertIsInstance(figures, list)
        for figure in figures:
            self.assertTrue(figure["url"].startswith("/artifacts/"))
            self.assertIn(figure["kind"], ("image", "interactive"))


if __name__ == "__main__":
    unittest.main()
