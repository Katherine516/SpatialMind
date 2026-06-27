import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.review.ontology_labels import (
    ASTROCYTE_TERM_PATH,
    DEFAULT_GLIOBLASTOMA_DATASET,
    write_astrocyte_label_suggestions,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write astrocyte Cell Ontology-based label suggestions for expert review.")
    parser.add_argument("--data", default=DEFAULT_GLIOBLASTOMA_DATASET)
    parser.add_argument("--ontology", default=ASTROCYTE_TERM_PATH)
    parser.add_argument("--out", default="outputs/glioblastoma_expert_review_packet")
    parser.add_argument("--max-records", type=int, default=2500)
    args = parser.parse_args()

    result = write_astrocyte_label_suggestions(
        dataset_path=args.data,
        ontology_path=args.ontology,
        output_dir=args.out,
        max_records=args.max_records,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
