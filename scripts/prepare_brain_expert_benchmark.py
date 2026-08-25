import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.review import prepare_brain_expert_benchmark, validate_brain_benchmark_packet


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare or validate leakage-aware healthy-brain and glioblastoma expert benchmark cohorts."
    )
    parser.add_argument("--out", default="outputs/brain_expert_benchmark", help="Packet output directory.")
    parser.add_argument("--cohort-size", type=int, default=750, help="Review cells per dataset.")
    parser.add_argument("--pool-size", type=int, default=10000, help="Cells analyzed per dataset before selection; 0 loads all.")
    parser.add_argument("--resolution", type=float, default=0.5)
    parser.add_argument("--n-neighbors", type=int, default=15)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--spatial-bins", type=int, default=4)
    parser.add_argument("--healthy-candidates", default=None, help="Optional healthy-brain candidate-label CSV.")
    parser.add_argument("--glioblastoma-candidates", default=None, help="Optional glioblastoma candidate-label CSV.")
    parser.add_argument("--validate-existing", default=None, help="Validate an existing packet instead of generating one.")
    parser.add_argument("--minimum-review-coverage", type=float, default=0.9)
    args = parser.parse_args()

    if args.validate_existing:
        result = validate_brain_benchmark_packet(
            args.validate_existing,
            minimum_review_coverage=args.minimum_review_coverage,
        )
    else:
        candidate_paths = {
            key: value
            for key, value in {
                "healthy_brain": args.healthy_candidates,
                "glioblastoma": args.glioblastoma_candidates,
            }.items()
            if value
        }
        result = prepare_brain_expert_benchmark(
            output_dir=args.out,
            candidate_label_paths=candidate_paths,
            cohort_size=args.cohort_size,
            pool_size=args.pool_size,
            resolution=args.resolution,
            n_neighbors=args.n_neighbors,
            random_state=args.random_state,
            spatial_bins_per_axis=args.spatial_bins,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
