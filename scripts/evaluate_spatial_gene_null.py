"""Repeat a prespecified exchangeable spatial null; not tissue validation."""

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def evaluate(repeats=50, permutations=199):
    import numpy as np
    from spatialmind.schemas import SpatialDataset, SpotRecord
    from spatialmind.tools.implementations import spatial_variable_genes, clear_anndata_cache

    trials = []
    for seed in range(repeats):
        rng = np.random.default_rng(seed)
        # Gene-specific means are fixed across cells; positions carry no signal.
        counts = rng.poisson(np.linspace(1., 8., 60), size=(100, 60))
        records = [SpotRecord("null", float(i % 10), float(i // 10), "Unannotated",
                   {"G%d" % g: float(v) for g, v in enumerate(row)}, cell_id=str(i))
                   for i, row in enumerate(counts)]
        data = SpatialDataset("null", records, "synthetic", coordinate_system="microns")
        result = spatial_variable_genes(data, {"strict_engine": True, "n_top": 5,
            "n_perms": permutations, "n_neighs": 6, "random_state": seed})
        metrics = result.metrics
        trials.append({"seed": seed, "tested": len(metrics["all_tested_genes"]),
                       "rejections": metrics["significant_gene_count_all"]})
        clear_anndata_cache()
    n = len(trials)
    rate = sum(t["rejections"] > 0 for t in trials) / n
    z = 1.959963984540054
    center = (rate + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {"scope": "All-null exchangeable Poisson simulation on a 10x10 grid; not real-tissue FDR validation",
            "settings": {"repeats": repeats, "permutations": permutations, "genes": 60, "cells": 100,
                         "alpha": 0.05, "graph": "6-neighbor generic", "seeds": "0..repeats-1"},
            "family_rejection_rate": rate, "wilson_95_interval": [max(0., center-half), min(1., center+half)],
            "interpretation": "Under the complete null, FDR equals the probability of at least one rejection. "
                              "This bounded simulation does not prove control under tissue dependence or non-null mixtures.",
            "trials": trials}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument("--permutations", type=int, default=199)
    args = parser.parse_args()
    if args.repeats < 1 or args.permutations < 10:
        parser.error("Use at least one repeat and ten permutations.")
    report = evaluate(args.repeats, args.permutations)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "trials"}, indent=2))
