import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.ingestion import load_xenium
from spatialmind.viz import XeniumExplorerLiteViewer


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local Explorer-lite Xenium review viewer.")
    parser.add_argument("--data", required=True, help="Xenium output directory or experiment.xenium file.")
    parser.add_argument("--out", default="outputs/xenium_explorer_lite", help="Output directory.")
    parser.add_argument("--max-records", type=int, default=5000)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dataset = load_xenium(args.data, max_records=args.max_records)
    dataset.metadata["analysis_dataset_path"] = args.data
    viewer = XeniumExplorerLiteViewer().render(dataset, str(out), dataset_path=args.data)
    payload = {
        "dataset_path": args.data,
        "output_dir": str(out),
        "viewer_html": viewer,
        "records_loaded": len(dataset.records),
        "features_loaded": len(dataset.genes),
        "cell_types": dataset.cell_types,
    }
    summary = out / "explorer_lite_summary.json"
    with summary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
