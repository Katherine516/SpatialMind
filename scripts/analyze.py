"""Analyze a Xenium run and produce a report, figures, and a review viewer.

The wet-lab entry point: point it at an instrument output folder and it returns
QC, expression clusters, per-cluster markers, spatially variable genes, cluster
co-occurrence, figures, and a browser-based viewer -- with no expert labels
required. Naming clusters as cell types stays an expert step.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.pilot import run_pilot


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a Xenium run and produce a report.")
    parser.add_argument("data", help="Xenium output folder or experiment.xenium file.")
    parser.add_argument("--out", default="outputs/analysis", help="Output directory.")
    parser.add_argument(
        "--max-cells",
        type=int,
        default=20000,
        help="Cells to analyze (>=6000 recommended; below that clusters may be incomplete).",
    )
    parser.add_argument("--full-section", action="store_true", help="Analyze every cell (slower).")
    parser.add_argument("--report-format", default="html", choices=["html", "pdf", "both"])
    parser.add_argument("--review-templates", action="store_true",
                        help="Also write expert label/region templates (~1.5 MB). Off by default.")
    args = parser.parse_args()

    max_records = 10_000_000 if args.full_section else args.max_cells
    result = run_pilot(
        dataset_path=args.data,
        output_dir=Path(args.out),
        max_records=max_records,
        report_format=args.report_format,
        review_artifacts=args.review_templates,
    )

    descriptive = result.get("descriptive_analysis") or {}
    scope = result.get("analysis_scope") or {}
    print("SpatialMind analysis")
    print("  dataset      : %s" % args.data)
    print("  cells        : %s of %s (%s)" % (
        result.get("records_loaded"), scope.get("total_records", "?"), scope.get("scope", "?")))
    print("  features     : %s" % result.get("features_loaded"))
    run_qc = {row["key"]: row for row in (result.get("run_qc") or {}).get("metrics", [])}
    if run_qc:
        decoded = run_qc.get("fraction_transcripts_decoded_q20")
        assigned = run_qc.get("fraction_transcripts_assigned")
        negctl = run_qc.get("negative_control_probe_rate")
        parts = []
        if decoded: parts.append("decoded Q20 %.3f" % decoded["value"])
        if assigned: parts.append("assigned %.3f" % assigned["value"])
        if negctl: parts.append("neg-control %.4f" % negctl["value"])
        if parts:
            print("  run QC       : %s" % ", ".join(parts))
        flagged = [r["label"] for r in run_qc.values() if r.get("status") == "attention"]
        if flagged:
            print("  QC ATTENTION : %s" % ", ".join(flagged))
    if descriptive.get("status") == "computed":
        print("  clusters     : %s" % descriptive.get("cluster_count"))
        spatial = descriptive.get("spatial_genes") or {}
        if spatial.get("significant_gene_count_all") is not None:
            print("  spatial genes: %s significant" % spatial.get("significant_gene_count_all"))
        warning = descriptive.get("sampling_warning")
        if warning:
            print("  WARNING      : %s" % warning)
        stages = descriptive.get("stage_seconds") or {}
        if stages.get("total"):
            print("  analysis time: %.0fs" % float(stages["total"]))
        quality = descriptive.get("timing_quality") or {}
        if quality.get("status") == "contended":
            print("  TIMING       : machine was busy; stage seconds are inflated (%.1fx CPU)"
                  % quality.get("wall_to_cpu_ratio", 0))
    else:
        print("  descriptive  : %s (%s)" % (descriptive.get("status"), descriptive.get("reason", "")))
    print()
    print("Report   : %s" % (result.get("report_html") or result.get("report_md")))
    print("Viewer   : %s" % str(Path(args.out) / "explorer_lite_viewer.html"))
    print("Full JSON: %s" % str(Path(args.out) / "pilot_validation.json"))
    if result.get("status") != "validated_ready":
        print()
        print("Cluster naming and cell-type claims need expert review; see the report's")
        print("'What Expert Review Would Add' section.")


if __name__ == "__main__":
    main()
