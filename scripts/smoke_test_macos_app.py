#!/usr/bin/env python3
"""Launch the built `.app` and prove it actually works.

Verifying that PyInstaller produced a bundle is not the same as verifying the
bundle runs: a missing hidden import shows up only at launch, and a windowed
macOS app fails silently. So this starts the real bundled executable, drives its
HTTP API against a synthetic dataset, and fails loudly if anything is missing.
"""

from pathlib import Path
import argparse
import gzip
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "dist" / "SpatialMind Studio.app"
BINARY = APP / "Contents" / "MacOS" / "SpatialMindStudio"
PORT = int(os.environ.get("SMOKE_PORT", "8791"))
BASE = "http://127.0.0.1:%d" % PORT
N_CELLS = 300


def make_dataset(root: Path) -> Path:
    import h5py
    import numpy as np
    from scipy.sparse import csc_matrix
    import tifffile
    import pandas as pd

    bundle = root / "Smoke_Section_outs"
    bundle.mkdir(parents=True)
    (bundle / "experiment.xenium").write_text(json.dumps({"run_name": "smoke", "panel_name": "smoke_10g"}))
    with gzip.open(bundle / "cells.csv.gz", "wt", newline="") as handle:
        handle.write("cell_id,x_centroid,y_centroid,transcript_counts\n")
        for i in range(N_CELLS):
            handle.write("cell-%d,%.2f,%.2f,%d\n" % (i, (i % 20) * 5.0, (i // 20) * 5.0, 40 + i % 30))
    values = np.random.RandomState(17).poisson(2, (40, N_CELLS))
    for i in range(N_CELLS):
        values[(i % 3) * 10:(i % 3 + 1) * 10, i] += 10
    matrix = csc_matrix(values)
    with h5py.File(bundle / "cell_feature_matrix.h5", "w") as handle:
        group = handle.create_group("matrix")
        for key, value in (("data", matrix.data), ("indices", matrix.indices), ("indptr", matrix.indptr), ("shape", matrix.shape)):
            group.create_dataset(key, data=value)
        group.create_dataset("barcodes", data=np.array([("cell-%d" % i).encode() for i in range(N_CELLS)]))
        features = group.create_group("features")
        features.create_dataset("name", data=np.array([("SMOKE_G%d" % i).encode() for i in range(40)]))
        features.create_dataset("feature_type", data=np.array([b"Gene Expression"] * 40))
    tifffile.imwrite(bundle / "morphology_focus.ome.tif", np.zeros((128, 128), dtype=np.uint8))
    pd.DataFrame({"cell_id": ["cell-0"] * 4, "vertex_x": [0., 1., 1., 0.],
                  "vertex_y": [0., 0., 1., 1.]}).to_parquet(bundle / "cell_boundaries.parquet")
    return bundle


def get(path: str, timeout: float = 20.0):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post(path: str, payload: dict, timeout: float = 30.0):
    request = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_health(process, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit("The app exited early with code %s.\n%s"
                             % (process.returncode, (process.stdout.read() if process.stdout else "")))
        try:
            return get("/api/health", timeout=3.0)
        except Exception as exc:
            last = exc
            time.sleep(0.6)
    raise SystemExit("The app never answered /api/health within %.0fs (last error: %s)" % (timeout, last))


CHECKS = []


def check(name):
    def decorator(func):
        CHECKS.append((name, func))
        return func
    return decorator


@check("health answers before any folder is scanned")
def _health(state):
    body = get("/api/health")
    assert body["status"] == "ok", body
    # The scan must not run at startup: on macOS a first read of a protected
    # folder blocks on a consent prompt, and doing it before the port is bound
    # made the app hang with no window and nothing to click.
    assert body["scanned"] is False, "the app scanned at startup; a blocked folder would hang it"
    summary = body["capability_summary"]
    assert summary.get("validated", 0) >= 1 and summary.get("unavailable", 0) >= 1, summary
    return "%d validated, %d scaffolds, scan deferred" % (summary.get("validated", 0), summary.get("unavailable", 0))


@check("the web UI is served from inside the bundle")
def _ui(state):
    with urllib.request.urlopen(BASE + "/", timeout=15) as response:
        html = response.read().decode("utf-8")
    assert "SpatialMind Studio" in html, "index.html did not come back"
    assert "/api/datasets" in html, "the UI is not wired to the API"
    return "%d KB" % (len(html) // 1024)


@check("the synthetic dataset is discovered")
def _discovery(state):
    body = get("/api/datasets")
    assert len(body["datasets"]) == 1, body
    state["dataset_id"] = body["datasets"][0]["dataset_id"]
    assert body["datasets"][0]["reviewable"], body
    return body["datasets"][0]["name"]


@check("ingestion builds a cell index")
def _cells(state):
    body = get("/api/datasets/%s/cells" % state["dataset_id"])
    assert body["n_cells"] == N_CELLS, body["n_cells"]
    assert len(body["x"]) == len(body["y"]) == body["displayed"]
    return "%d cells indexed" % body["n_cells"]


@check("the gate starts blocked")
def _gate_blocked(state):
    body = get("/api/datasets/%s" % state["dataset_id"])
    gate = body["gate"]
    assert gate["status"] == "blocked_missing_validation_inputs", gate["status"]
    assert gate["blocking_reasons"], "a blocked gate must give reasons"
    return "%d blockers" % len(gate["blocking_reasons"])


@check("the scientific stack is catalogued")
def _scientific_stack(state):
    body = get("/api/tools?dataset_id=%s" % state["dataset_id"])
    names = {tool["name"] for tool in body["tools"]}
    for required in ("qc_and_cluster", "spatial_variable_genes", "cell_neighborhood_enrichment"):
        assert required in names, "%s missing from the catalog" % required
    scaffolds = [tool for tool in body["tools"] if tool["capability"] == "unavailable"]
    # Source is unreadable in a frozen bundle, so scaffold detection has to work
    # from bytecode. When it does not, every tool reports as usable.
    assert scaffolds, ("no tool is marked unavailable: scaffold detection is broken in the bundle "
                       "(capability summary %s)" % get("/api/health")["capability_summary"])
    bad = [tool["name"] for tool in scaffolds if tool["plannable"]]
    assert not bad, "scaffolds marked plannable: %s" % ", ".join(bad)
    return "%d tools, %d scaffolds correctly disabled" % (len(names), len(scaffolds))


@check("a squidpy-backed analysis actually runs in the bundle")
def _squidpy_runs(state):
    """The catalog check above is a listing, not an import.

    `squidpy` reaches `spatialdata`, which reached `dask`, `datashader` and
    `plotly` -- four packages the spec excluded as "not on the Studio's import
    path". The bundle built, launched, passed every check here, and then failed
    the first time anyone asked for spatial statistics, with a message that read
    like a missing optional dependency rather than a broken build. Nothing short
    of running the tool catches that, so this runs it.
    """
    job = post("/api/runs", {
        "dataset_id": state["dataset_id"], "kind": "plan",
        "label": "smoke: spatial statistics",
        "tools": ["qc_and_cluster", "spatial_variable_genes"],
        "overrides": {"qc_and_cluster": {"engine": "scanpy", "strict_engine": True},
                      "spatial_variable_genes": {"engine": "squidpy", "strict_engine": True,
                                                  "n_perms": 20, "n_top": 5}},
    })
    job_id = job["job_id"]
    deadline = time.time() + 420
    state_name, error = job["state"], ""
    while time.time() < deadline:
        current = get("/api/runs/%s" % job_id, timeout=15.0)
        state_name, error = current["state"], current.get("error") or ""
        if state_name in {"succeeded", "failed"}:
            break
        time.sleep(2.0)
    assert state_name == "succeeded", "%s: %s" % (state_name, error[:400])
    entries = {entry["tool"]: entry for entry in (get("/api/runs/%s" % job_id)["result"] or {}).get("results", [])}
    for tool, engine in (("qc_and_cluster", "scanpy"), ("spatial_variable_genes", "squidpy")):
        assert entries.get(tool, {}).get("metrics", {}).get("engine") == engine, entries.get(tool)
    state["analysis_job"] = job_id
    return "qc_and_cluster + spatial_variable_genes on %d cells" % N_CELLS


@check("analysis delivers HTML, figures, PDF, Word and Excel exports")
def _exports(state):
    with urllib.request.urlopen(BASE + "/api/runs/%s/report" % state["analysis_job"], timeout=30) as response:
        assert b"<html" in response.read().lower(), "No HTML report"
    reports = get("/api/reports")["reports"]
    assert reports, "Report library is empty"
    report_id = reports[0]["report_id"]
    for format, magic in (("pdf", b"%PDF"), ("docx", b"PK")):
        with urllib.request.urlopen(BASE + "/api/reports/%s/export?format=%s" % (report_id, format), timeout=60) as response:
            assert response.read().startswith(magic), "Invalid %s export" % format
    with urllib.request.urlopen(BASE + "/api/reports/%s/results?format=xlsx" % report_id, timeout=60) as response:
        assert response.read().startswith(b"PK"), "Invalid Excel export"
    result = get("/api/runs/%s" % state["analysis_job"])["result"]
    assert result.get("figures"), "No analysis figures"
    return "HTML + figures + PDF + DOCX + XLSX"


@check("planning inserts dependencies and validates")
def _plan(state):
    body = post("/api/plan", {"dataset_id": state["dataset_id"], "tools": ["marker_detection"]})
    names = [step["tool"] for step in body["steps"]]
    assert names[0] == "qc_and_cluster" and names[-1] == "marker_detection", names
    assert body["plan_status"] == "valid", body
    return " -> ".join(names)


@check("the agent refuses a question only a scaffold could answer")
def _refusal(state):
    body = post("/api/ask", {"dataset_id": state["dataset_id"], "question": "Find malignant cells by copy number."})
    assert body["tools"] == [], body
    assert body["refusal"] and "cnv_inference" in body["refusal"], body
    return body["refusal"]


@check("a review assignment writes the CSV and moves the gate")
def _assign(state):
    ids = ["cell-%d" % i for i in range(N_CELLS)]
    post("/api/datasets/%s/assign" % state["dataset_id"],
         {"kind": "labels", "value": "Astrocyte", "cell_ids": ids[: N_CELLS // 2],
          "reviewer_id": "synthetic-smoke-reviewer", "evidence_ref": "fixture:synthetic-labels"})
    post("/api/datasets/%s/assign" % state["dataset_id"],
         {"kind": "labels", "value": "T cell", "cell_ids": ids[N_CELLS // 2:],
          "reviewer_id": "synthetic-smoke-reviewer", "evidence_ref": "fixture:synthetic-labels"})
    bounds = get("/api/datasets/%s/cells" % state["dataset_id"])["bounds"]
    mid = (bounds["y_min"] + bounds["y_max"]) / 2.0
    post("/api/datasets/%s/assign" % state["dataset_id"],
         {"kind": "regions", "value": "core", "reviewer_id": "synthetic-smoke-reviewer", "evidence_ref": "fixture:synthetic-roi",
          "bounds": {"x0": bounds["x_min"], "y0": bounds["y_min"], "x1": bounds["x_max"], "y1": mid}})
    body = post("/api/datasets/%s/assign" % state["dataset_id"],
                {"kind": "regions", "value": "edge", "reviewer_id": "synthetic-smoke-reviewer", "evidence_ref": "fixture:synthetic-roi",
                 "bounds": {"x0": bounds["x_min"], "y0": mid, "x1": bounds["x_max"], "y1": bounds["y_max"]}})
    assert body["gate"]["status"] == "validated_ready", body["gate"]["status"]
    assert (state["bundle"] / "expert_cell_labels.csv").exists(), "no label CSV was written"
    assert (state["bundle"] / "cell_regions.csv").exists(), "no region CSV was written"
    return "gate -> validated_ready"


@check("lanes change once the gate is open")
def _lanes(state):
    body = get("/api/tools?dataset_id=%s" % state["dataset_id"])
    by_name = {tool["name"]: tool for tool in body["tools"]}
    assert body["gate_open"], "gate should be open by now"
    assert by_name["region_summary"]["lane"] == "validated", by_name["region_summary"]["lane"]
    return "region_summary -> validated"


@check("clearing a table closes the gate again")
def _clear(state):
    body = post("/api/datasets/%s/clear" % state["dataset_id"], {"kind": "labels"})
    assert body["gate"]["status"] != "validated_ready", body["gate"]["status"]
    return "gate -> blocked"


def main() -> int:
    global APP, BINARY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=APP)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    APP = args.app.resolve()
    BINARY = APP / "Contents" / "MacOS" / "SpatialMindStudio"
    if not BINARY.exists():
        print("No built app at %s\nRun: python scripts/build_macos_app.py" % BINARY)
        return 2

    workspace = Path(tempfile.mkdtemp(prefix="spatialmind-smoke-"))
    data_root = workspace / "data"
    data_root.mkdir()
    bundle = make_dataset(data_root)

    env = dict(os.environ)
    env.update({
        "SPATIALMIND_DATA_ROOT": str(data_root),
        "SPATIALMIND_OUTPUT_ROOT": str(workspace / "outputs"),
        "SPATIALMIND_PORT": str(PORT),
        "SPATIALMIND_NO_BROWSER": "1",
        # The kernel warmup compiles for ~30s in the background. It is the right
        # thing for a person's session and pure noise for a timed check that
        # never runs a real analysis.
        "SPATIALMIND_NO_WARMUP": "1",
        "SPATIALMIND_SUPPORT_DIR": str(workspace / "support"),
    })

    print("Launching %s" % BINARY)
    log_path = args.report.with_suffix(".log") if args.report else workspace / "app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen([str(BINARY)], env=env, stdout=log_handle,
                               stderr=subprocess.STDOUT, text=True)
    failures = []
    results = []
    try:
        started = time.time()
        wait_for_health(process)
        print("App answered in %.1fs on port %d\n" % (time.time() - started, PORT))

        state = {"bundle": bundle}
        for name, func in CHECKS:
            try:
                detail = func(state)
                results.append({"check": name, "status": "passed", "detail": str(detail or "")})
                print("  PASS  %-52s %s" % (name, detail or ""))
            except Exception as exc:
                failures.append((name, exc))
                results.append({"check": name, "status": "failed", "error": str(exc)})
                print("  FAIL  %-52s %s" % (name, exc))
    except BaseException as exc:
        failures.append(("startup", exc))
        results.append({"check": "startup", "status": "failed", "error": str(exc)})
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
        log_handle.close()
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({"status": "failed" if failures else "passed",
                "architecture": platform.machine(), "checks": results,
                "passed": sum(item["status"] == "passed" for item in results),
                "total": len(CHECKS)}, indent=2), encoding="utf-8")
        shutil.rmtree(workspace, ignore_errors=True)

    print("\n%d of %d checks passed." % (len(CHECKS) - len(failures), len(CHECKS)))
    if failures:
        print("The built app is NOT usable:")
        for name, exc in failures:
            print("   - %s: %s" % (name, exc))
        return 1
    print("The built app is usable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
