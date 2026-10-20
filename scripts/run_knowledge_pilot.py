"""Build a non-approved knowledge example and evaluate retrieval without model calls."""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.app.knowledge_runs import import_run
from spatialmind.app.library import ReportLibrary
from spatialmind.knowledge.compiler import compile_page
from spatialmind.knowledge.evaluation import evaluate
from spatialmind.knowledge.seed import VERSION
from spatialmind.knowledge.store import KnowledgeStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--report-root")
    parser.add_argument("--report-id")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    store = KnowledgeStore(output / "knowledge.sqlite")
    examples = [("Spatial neighborhood methods", ["moran", "neighborhood"], "method"),
                ("Cell identity and annotation boundaries", ["clustering", "ontology", "review"], "concept"),
                ("Evidence and claim reliability", ["reliability", "panel"], "concept")]
    pages = [compile_page(store, title, ["builtin:%s:%s" % (s, VERSION) for s in sources], kind=kind) for title, sources, kind in examples]
    run = {"status": "not_requested"}
    if args.report_root and args.report_id:
        library = ReportLibrary(args.report_root)
        described = library.get(args.report_id)
        try:
            if not described or not described["paths"].get("validation"):
                raise ValueError("Report has no structured validation artifact.")
            payload = json.loads(Path(described["paths"]["validation"]).read_text())
            dataset = payload.get("dataset") or {}
            if not dataset.get("dataset_id") or not dataset.get("path"):
                raise ValueError("This pilot example requires an explicit Studio dataset ID and path.")
            studio = SimpleNamespace(output_root=args.report_root, reports=library,
                                     entry=lambda _: SimpleNamespace(path=dataset["path"], missing=not Path(dataset["path"]).exists()))
            run = import_run(studio, store, args.report_id, dataset["dataset_id"])
        except (ValueError, OSError, KeyError) as exc:
            run = {"status": "blocked", "reason": str(exc)}
    evaluation = evaluate(store, json.loads((ROOT / "eval/knowledge/development.json").read_text()))
    result = {"status": "drafts_created_no_expert_approval", "pages": [{"id": p["id"], "title": p["title"], "status": p["status"]} for p in pages],
              "run_import": run, "retrieval": evaluation, "health": store.workspace.health()}
    (output / "pilot_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# SpatialMind Knowledge Compilation Pilot", "", "All generated pages remain drafts. No human review, model call or biological training was performed.", "", "## Drafts", ""]
    lines += ["- [%s](knowledge/drafts/%s-r%d.md)" % (p["title"], p["id"], p["revision"]) for p in pages]
    lines += ["", "## Run Evidence", "", "Status: " + run["status"], run.get("reason", "Imported run evidence remains pending review."),
              "", "## Retrieval Smoke Evaluation", "", "Developer-authored and development-tuned; not an independent specialist benchmark.",
              "", "- Cases: %s" % evaluation["cases"], "- Source recall at 5 passages: %s" % evaluation["source_recall_at_5_passages"],
              "- Unanswerable retrieval abstention: %s" % evaluation["unanswerable_retrieval_abstention"],
              "- Biological accuracy: not measured", "", "## Required Next Inputs", "",
              "- Specialist-reviewed questions, citation judgments and applicability/contradiction assessments.",
              "- Approved source permissions and sharing choices before hosted compilation.",
              "- Native Intel/Apple Silicon packaging acceptance before a new DMG release."]
    (output / "pilot_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output / "pilot_report.md"), "run_status": run["status"], "pages": len(pages)}, indent=2))


if __name__ == "__main__":
    main()
