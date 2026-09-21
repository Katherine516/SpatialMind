#!/usr/bin/env python3
"""End-to-end evaluation of SpatialMind Studio against real sections.

Drives the app the way a user does -- discover, gate, review, plan, run -- and
records what each stage cost and what it produced. Two datasets are used
deliberately:

  * an unlabelled section, which must stay blocked and run the descriptive lane;
  * a section carrying the repo's SYNTHETIC_GATE_DEMO labels, which must open
    the gate and run the validated lane.

The second measures the *machinery*, not biology. Those labels are promoted
transfer candidates and say so in every row; no biological claim from that run
is licensed, and the report says so too.

    python scripts/evaluate_studio_workflow.py --out outputs/studio_evaluation
"""

from pathlib import Path
from typing import Any, Dict, List
import argparse
import json
import os
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UNLABELLED = ROOT / "data" / "Xenium Human Brain" / "Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs"
LABELLED = ROOT / "outputs" / "workflow_demo_20260826" / "05_reviewed_section"


class Timer:
    def __init__(self):
        self.marks: List[Dict[str, Any]] = []

    def run(self, stage: str, func, **meta):
        started = time.time()
        error = ""
        value = None
        try:
            value = func()
        except Exception as exc:
            error = "%s: %s" % (type(exc).__name__, exc)
        seconds = round(time.time() - started, 2)
        record = {"stage": stage, "seconds": seconds, "error": error}
        record.update(meta)
        self.marks.append(record)
        status = "FAIL" if error else "ok"
        print("  %-38s %7.2fs  %s" % (stage, seconds, error or status))
        return value


def measure_latency(client, path: str, repeats: int = 5) -> Dict[str, Any]:
    samples = []
    for _ in range(repeats):
        started = time.time()
        response = client.get(path)
        samples.append((time.time() - started) * 1000)
        ok = response.status_code == 200
    return {
        "path": path,
        "status_ok": ok,
        "median_ms": round(statistics.median(samples), 1),
        "max_ms": round(max(samples), 1),
        "samples": len(samples),
    }


def evaluate(out_dir: Path) -> Dict[str, Any]:
    from fastapi.testclient import TestClient

    from spatialmind.app import planner, resources, review
    from spatialmind.app.server import Studio, create_studio_app, make_plan_worker
    from spatialmind.app.jobs import Job

    out_dir.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "datasets": {},
        "stages": [],
        "latency": [],
        "honesty": {},
        "notes": [],
    }
    timer = Timer()

    # ---------------------------------------------------------------- discovery
    print("\nDISCOVERY AND GATE")
    app = timer.run("create_studio_app", lambda: create_studio_app(
        data_root=str(ROOT / "data"), output_root=str(out_dir / "runs")))
    client = TestClient(app)
    studio: Studio = app.state.studio

    listing = timer.run("discover datasets", lambda: client.get("/api/datasets").json())
    entries = listing["datasets"]
    report["datasets"]["discovered"] = len(entries)
    report["datasets"]["reviewable"] = sum(1 for e in entries if e["reviewable"])

    healthy = next(e for e in entries if "Healthy" in e["relative_path"])
    index = timer.run("build cell index (24k cells)",
                      lambda: studio.index(healthy["dataset_id"]),
                      cells=None)
    timer.marks[-1]["cells"] = index.n_cells
    report["datasets"]["unlabelled_cells"] = index.n_cells

    gate_blocked = timer.run("evaluate gate (unlabelled)", lambda: studio.gate(healthy["dataset_id"]))
    report["gate_blocked"] = {
        "status": gate_blocked["status"],
        "blockers": len(gate_blocked["blocking_reasons"]),
        "label_coverage": gate_blocked["label_coverage"],
        "region_coverage": gate_blocked["region_coverage"],
    }

    timer.run("cells endpoint (display sample)",
              lambda: client.get("/api/datasets/%s/cells" % healthy["dataset_id"]).json())

    # ---------------------------------------------------------------- routing
    print("\nPLANNING AND ROUTING")
    questions = [
        ("spatial structure", "Which genes are spatially structured across this section?"),
        ("cell-type adjacency", "Which cell types sit next to each other?"),
        ("scaffold: copy number", "Find the malignant cells by copy number."),
        ("scaffold: ligand-receptor", "Predict ligand-receptor communication."),
        ("out of scope", "What is the weather in Oslo?"),
    ]
    routing = []
    for name, question in questions:
        answer = client.post("/api/ask", json={"dataset_id": healthy["dataset_id"], "question": question}).json()
        routing.append({
            "question": name,
            "tools": answer["tools"],
            "refused": bool(answer["refusal"]),
            "refusal": answer["refusal"] or "",
        })
        print("  %-28s tools=%-2d refused=%s" % (name, len(answer["tools"]), bool(answer["refusal"])))
    report["routing"] = routing

    plan = client.post("/api/plan", json={"dataset_id": healthy["dataset_id"],
                                          "tools": ["region_summary", "marker_detection"]}).json()
    report["plan_validation"] = {
        "requested": 2,
        "steps_after_dependency_insertion": len(plan["steps"]),
        "plan_status": plan["plan_status"],
        "blocked_steps": plan["blocked_steps"],
    }
    print("  dependency insertion: 2 requested -> %d steps, status=%s, %d blocked"
          % (len(plan["steps"]), plan["plan_status"], plan["blocked_steps"]))

    # ---------------------------------------------------------------- descriptive lane
    print("\nDESCRIPTIVE LANE (unlabelled, full section)")
    descriptive_tools = ["qc_and_cluster", "spatial_variable_genes"]
    worker = make_plan_worker(studio, healthy["dataset_id"], descriptive_tools,
                              {"marker_detection": {"group_key": "leiden"}}, 0)
    job = Job(job_id="eval_descriptive", kind="plan", label="evaluation: descriptive lane",
              dataset_id=healthy["dataset_id"], dataset_path=healthy["path"])
    descriptive = timer.run("run descriptive lane", lambda: worker(job))
    if descriptive:
        report["descriptive_run"] = {
            "records_loaded": descriptive["records_loaded"],
            "wall_seconds": descriptive["wall_seconds"],
            "tools": [{"tool": r["tool"], "seconds": r["seconds"], "summary": r["summary"]}
                      for r in descriptive["results"]],
        }
        for r in descriptive["results"]:
            print("    %-24s %6.1fs  %s" % (r["tool"], r["seconds"], r["summary"][:70]))

    # ---------------------------------------------------------------- validated lane
    print("\nVALIDATED LANE (synthetic gate-demo labels, machinery only)")
    if LABELLED.exists():
        # A second app rather than set_data_root: that persists the choice to the
        # user's config, and an evaluation must not reconfigure their app.
        app2 = create_studio_app(data_root=str(LABELLED.parent), output_root=str(out_dir / "runs"))
        client2 = TestClient(app2)
        studio2: Studio = app2.state.studio
        entries2 = client2.get("/api/datasets").json()["datasets"]
        reviewed = next((e for e in entries2 if "05_reviewed_section" in e["relative_path"]), None)
        if reviewed:
            gate_open = timer.run("evaluate gate (labelled)", lambda: studio2.gate(reviewed["dataset_id"]))
            report["gate_open"] = {
                "status": gate_open["status"],
                "blockers": len(gate_open["blocking_reasons"]),
                "label_coverage": gate_open["label_coverage"],
                "region_coverage": gate_open["region_coverage"],
                "cell_classes": len(gate_open["cell_classes"]),
                "regions": len(gate_open["regions"]),
            }
            validated_tools = ["qc_and_cluster", "annotation", "marker_detection",
                               "region_summary", "cell_neighborhood_enrichment"]
            worker2 = make_plan_worker(studio2, reviewed["dataset_id"], validated_tools, {}, 0)
            job2 = Job(job_id="eval_validated", kind="plan", label="evaluation: validated lane",
                       dataset_id=reviewed["dataset_id"], dataset_path=reviewed["path"])
            validated = timer.run("run validated lane", lambda: worker2(job2))
            if validated:
                report["validated_run"] = {
                    "records_loaded": validated["records_loaded"],
                    "wall_seconds": validated["wall_seconds"],
                    "tools": [{"tool": r["tool"], "seconds": r["seconds"], "summary": r["summary"],
                               "caveats": len(r["caveats"])} for r in validated["results"]],
                }
                for r in validated["results"]:
                    print("    %-24s %6.1fs  %s" % (r["tool"], r["seconds"], r["summary"][:70]))
    else:
        report["notes"].append("No labelled section found; validated lane not measured.")

    # ---------------------------------------------------------------- latency
    print("\nAPI LATENCY")
    for path in ("/api/health", "/api/datasets", "/api/tools", "/api/resources"):
        sample = measure_latency(client, path)
        report["latency"].append(sample)
        print("  %-20s median %6.1f ms  max %6.1f ms" % (path, sample["median_ms"], sample["max_ms"]))

    # ---------------------------------------------------------------- honesty
    print("\nHONESTY SURFACE")
    summary = planner.capability_summary()
    catalog = planner.tool_catalog(gate_open=False)
    report["honesty"] = {
        "tools_registered": len(catalog),
        "tools_plannable": summary.get("validated", 0),
        "tools_scaffold": summary.get("unavailable", 0),
        "scaffolds_marked_plannable": sum(1 for t in catalog if t["capability"] == "unavailable" and t["plannable"]),
        "questions_asked": len(routing),
        "questions_refused": sum(1 for r in routing if r["refused"]),
        "lanes_blocked_while_gate_shut": sum(1 for t in catalog if t["lane"] == "blocked"),
    }
    for key, value in report["honesty"].items():
        print("  %-34s %s" % (key, value))

    report["stages"] = timer.marks
    (out_dir / "studio_evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nWrote %s" % (out_dir / "studio_evaluation.json"))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the Studio end to end.")
    parser.add_argument("--out", default="outputs/studio_evaluation")
    args = parser.parse_args()
    evaluate(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
