"""Exercise the review boundary and real-section delivery without changing inputs.

The breast run is sampled and exploratory. No label-accuracy claim is measured.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from fastapi.testclient import TestClient
    from spatialmind.app.server import create_studio_app, make_plan_worker
    from spatialmind.app.jobs import Job
    from spatialmind.app.planner import RECIPES
    from spatialmind.storage.replay import verify_run_record, replay_run_record

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="outputs/correctness_release_20260927")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    app = create_studio_app(data_root=str(ROOT / "data"), output_root=str(out / "runs"))
    client = TestClient(app)
    studio = app.state.studio
    entries = client.get("/api/datasets").json()["datasets"]
    healthy = next(row for row in entries if "Healthy" in row["relative_path"])
    breast = next(row for row in entries if "Janesick2023" in row["relative_path"])
    report = {"scope": "Correctness regression and real-section execution, not biological accuracy", "api": [], "runs": []}
    for name, tools, overrides, expected in [
        ("marker_without_review", ["marker_detection"], {}, 409),
        ("annotation_override", ["annotation"], {"annotation": {"group_key": "cluster"}}, 409),
        ("cluster_neighborhood", ["cell_neighborhood_enrichment"], {"cell_neighborhood_enrichment": {"group_key": "leiden"}}, 200),
        ("invalid_group", ["marker_detection"], {"marker_detection": {"group_key": "typo"}}, 400),
    ]:
        job = Job("no_execution", "plan", name, healthy["dataset_id"], healthy["path"])
        with patch.object(studio.jobs, "submit", return_value=job):
            response = client.post("/api/runs", json={"dataset_id": healthy["dataset_id"], "tools": tools, "overrides": overrides})
        report["api"].append({"case": name, "actual": response.status_code, "expected": expected})
        assert response.status_code == expected, response.text

    descriptive = next(recipe for recipe in RECIPES if recipe["id"] == "descriptive")
    checks = [
        ("healthy_descriptive", healthy, descriptive["tools"], descriptive["overrides"], 0),
        ("breast_reviewed_sample", breast,
         ["qc_and_cluster", "annotation", "marker_detection", "region_summary", "cell_neighborhood_enrichment"],
         {"cell_neighborhood_enrichment": {"n_perms": 50}}, 5000),
    ]
    for name, entry, names, overrides, limit in checks:
        job = Job(name, "plan", name, entry["dataset_id"], entry["path"])
        started = time.monotonic()
        payload = make_plan_worker(studio, entry["dataset_id"], names, overrides, limit)(job)
        verified = verify_run_record(payload["run_record_path"])
        assert verified.status == "verified", verified.to_dict()
        assert payload["delivery_status"] == "complete", job.log
        record = json.loads(Path(payload["run_record_path"]).read_text())
        row = {"name": name, "seconds": round(time.monotonic() - started, 3),
               "records_loaded": payload["records_loaded"], "features_loaded": payload["features_loaded"],
               "report_paths": payload["report_paths"], "gate": payload["gate"]["status"],
               "matched_labels": payload["label_report"]["matched_cells"],
               "verified_checks": len(verified.checks),
               "output_hash_counts": {key: len(record[key]) for key in ("artifact_md5", "figure_md5", "table_md5")},
               "replay_status": replay_run_record(payload["run_record_path"], verify_only=False)["status"],
               "tools": [{"name": result["tool"], "params": result["params"],
                          "reviewed_only": result["metrics"].get("reviewed_only"),
                          "scope_analyzed_cells": result["metrics"].get("scope_analyzed_cells"),
                          "excluded_unreviewed_cell_count": result["metrics"].get("excluded_unreviewed_cell_count"),
                          "group_key": result["metrics"].get("group_key"), "summary": result["summary"]}
                         for result in payload["results"]]}
        report["runs"].append(row)
        (out / "evaluation.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(row, indent=2), flush=True)


if __name__ == "__main__":
    main()
