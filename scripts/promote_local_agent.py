import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.promotion import build_local_promotion_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local SpatialMind promotion workflow over data/.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--out", default="outputs/agent_promotion")
    parser.add_argument("--max-records", type=int, default=800)
    parser.add_argument(
        "--readiness-only",
        action="store_true",
        help="Compute dataset/intake/pilot status only; skip templates, figures, rendered reports, tools, and run records.",
    )
    args = parser.parse_args()

    report = build_local_promotion_report(
        data_root=args.data_root,
        output_root=args.out,
        max_records=args.max_records,
        readiness_only=args.readiness_only,
    )
    summary = {
        "created_at": report["created_at"],
        "dataset_count": report["dataset_count"],
        "xenium_dataset_count": report["xenium_dataset_count"],
        "validated_ready_xenium_count": report["validated_ready_xenium_count"],
        "readiness_only": report["readiness_only"],
        "report_json": str(Path(args.out) / "local_promotion_report.json"),
        "report_md": str(Path(args.out) / "local_promotion_report.md"),
        "next_actions": report["next_actions"][:8],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
