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
        help="Cells to analyze. Use --full-section for every cell in the run.",
    )
    parser.add_argument("--full-section", action="store_true", help="Analyze every cell (slower).")
    parser.add_argument("--report-format", default="html", choices=["html", "pdf", "both"])
    args = parser.parse_args()

    max_records = 10_000_000 if args.full_section else args.max_cells
    result = run_pilot(
        dataset_path=args.data,
        output_dir=Path(args.out),
        max_records=max_records,
        report_format=args.report_format,
    )

    descriptive = result.get("descriptive_analysis") or {}
    scope = result.get("analysis_scope") or {}
    print("SpatialMind analysis")
    print("  dataset      : %s" % args.data)
    print("  cells        : %s of %s (%s)" % (
        result.get("records_loaded"), scope.get("total_records", "?"), scope.get("scope", "?")))
    print("  features     : %s" % result.get("features_loaded"))
    if descriptive.get("status") == "computed":
        print("  clusters     : %s" % descriptive.get("cluster_count"))
        spatial = descriptive.get("spatial_genes") or {}
        if spatial.get("significant_gene_count_all") is not None:
            print("  spatial genes: %s significant" % spatial.get("significant_gene_count_all"))
        stages = descriptive.get("stage_seconds") or {}
        if stages.get("total"):
            print("  analysis time: %.0fs" % float(stages["total"]))
    else:
        print("  descriptive  : %s (%s)" % (descriptive.get("status"), descriptive.get("reason", "")))
    print()
    print("Report   : %s" % (result.get("report_html") or result.get("report_md")))
    print("Viewer   : %s" % str(Path(args.out) / "explorer_lite_viewer.html"))
    print("Full JSON: %s" % str(Path(args.out) / "pilot_validation.json"))
    if result.get("status") != "validated_ready":
        print()
        print("Cluster naming and cell-type claims need expert review; see the report's")
        print("'What Is Still Needed To Go Further' section.")


if __name__ == "__main__":
    main()
