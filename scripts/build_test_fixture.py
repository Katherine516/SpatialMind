"""Cut a committable Xenium fixture out of a full section.

`tests/test_biological_plausibility.py` is the only suite that asserts the
pipeline still produces recognisable biology -- it is what would have caught
control probes driving PCA through 146 green tests. It reads from `data/`, which
is gitignored, so it skips on every machine that does not hold tens of GB of
instrument output, which includes every CI runner. A suite that skips everywhere
is not a suite.

This writes the ~6 MB of a bundle the loader actually reads, subsampled to a few
thousand cells and to the real gene panel plus a sample of the control probes.
The controls matter: the contamination check asserts the raw panel *contains*
controls, or it proves nothing.

    python scripts/build_test_fixture.py \
        "data/Xenium Human Brain/Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs" \
        --out tests/fixtures/xenium_healthy_brain_mini --cells 4000

Morphology and boundaries are not written: the plausibility suite never opens
them, and they are the large files. A fixture is therefore review-ready but not
gate-ready, which is the correct scope for it.
"""

import argparse
import csv
import gzip
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_cells(source: Path):
    import pandas as pd

    for name in ("cells.csv.gz", "cells.parquet"):
        path = source / name
        if not path.exists():
            continue
        return pd.read_parquet(path) if name.endswith(".parquet") else pd.read_csv(path)
    raise SystemExit("No cells.csv.gz or cells.parquet in %s" % source)


def build(source: Path, out: Path, cells: int, controls: int, seed: int) -> None:
    import h5py
    import numpy as np
    import pandas as pd
    from scipy import sparse

    out.mkdir(parents=True, exist_ok=True)
    table = _read_cells(source)
    total = len(table)
    step = max(1, total // cells)
    # Deterministic even-index, matching how the loader itself samples, so the
    # fixture is a scaled-down version of what a real run sees rather than a
    # differently-biased draw.
    picked = table.iloc[::step][:cells].copy()
    keep_ids = {str(value) for value in picked["cell_id"]}
    print("cells: %d of %d (step %d)" % (len(picked), total, step))

    with gzip.open(out / "cells.csv.gz", "wt", newline="") as handle:
        picked.to_csv(handle, index=False)

    matrix_path = source / "cell_feature_matrix.h5"
    with h5py.File(matrix_path, "r") as handle:
        group = handle["matrix"]
        barcodes = [b.decode() if isinstance(b, bytes) else str(b) for b in group["barcodes"][:]]
        names = [b.decode() if isinstance(b, bytes) else str(b) for b in group["features"]["name"][:]]
        ids = [b.decode() if isinstance(b, bytes) else str(b) for b in group["features"]["id"][:]]
        types = [b.decode() if isinstance(b, bytes) else str(b) for b in group["features"]["feature_type"][:]]
        shape = tuple(int(v) for v in group["shape"][:])
        csc = sparse.csc_matrix(
            (group["data"][:], group["indices"][:], group["indptr"][:]), shape=shape
        )

    col_index = [i for i, barcode in enumerate(barcodes) if barcode in keep_ids]
    sub = csc[:, col_index].tocsr()

    gene_rows = [i for i, kind in enumerate(types) if kind == "Gene Expression"]
    control_rows = [i for i, kind in enumerate(types) if kind != "Gene Expression"]
    if controls and len(control_rows) > controls:
        # The most-detected controls, not a random draw. Control probes are
        # sparse by design, and `SpatialDataset.genes` lists only features with a
        # nonzero count in the loaded cells -- a random 40 of 222 produced a
        # fixture whose raw panel contained no controls at all, which makes the
        # contamination check assert its own precondition and fail.
        detected = np.asarray((sub[control_rows, :] > 0).sum(axis=1)).ravel()
        order = np.argsort(-detected)[:controls]
        control_rows = sorted(control_rows[i] for i in order.tolist())
        print("controls kept: detected in %d-%d of %d cells"
              % (int(detected[order].min()), int(detected[order].max()), sub.shape[1]))
    row_index = sorted(gene_rows + control_rows)
    sub = sub[row_index, :].tocsc()
    print("features: %d genes + %d controls (of %d)" % (len(gene_rows), len(control_rows), len(types)))

    with h5py.File(out / "cell_feature_matrix.h5", "w") as handle:
        group = handle.create_group("matrix")
        group.create_dataset("barcodes", data=[barcodes[i].encode() for i in col_index])
        group.create_dataset("data", data=sub.data.astype("int32"), compression="gzip")
        group.create_dataset("indices", data=sub.indices.astype("int64"), compression="gzip")
        group.create_dataset("indptr", data=sub.indptr.astype("int64"), compression="gzip")
        group.create_dataset("shape", data=np.array(sub.shape, dtype="int32"))
        features = group.create_group("features")
        features.create_dataset("name", data=[names[i].encode() for i in row_index])
        features.create_dataset("id", data=[ids[i].encode() for i in row_index])
        features.create_dataset("feature_type", data=[types[i].encode() for i in row_index])
        features.create_dataset("genome", data=[b"unknown"] * len(row_index))

    for name in ("experiment.xenium", "gene_panel.json", "metrics_summary.csv"):
        if (source / name).exists():
            shutil.copy2(source / name, out / name)

    # `num_cells_detected` in metrics_summary.csv is the section total the loader
    # strides against when `max_records` is set. Copied verbatim it says 24,406
    # for a 4,000-cell fixture, so a default run sampled every sixth row and
    # loaded 655 cells.
    metrics_path = out / "metrics_summary.csv"
    if metrics_path.exists():
        rows = list(csv.reader(metrics_path.read_text(encoding="utf-8").splitlines()))
        if len(rows) >= 2 and "num_cells_detected" in rows[0]:
            column = rows[0].index("num_cells_detected")
            for row in rows[1:]:
                if len(row) > column:
                    row[column] = str(len(picked))
            with open(metrics_path, "w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerows(rows)

    # The manifest names assets this fixture deliberately omits. Left as-is, the
    # loader reports morphology and boundaries as present and a gate evaluation
    # on the fixture would be wrong about what it holds.
    manifest_path = out / "experiment.xenium"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["images"] = {}
        manifest["num_cells"] = int(len(picked))
        manifest["fixture"] = {
            "derived_from": source.name,
            "cells": int(len(picked)),
            "note": "Subsampled test fixture. No morphology or boundaries; not gate-ready.",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    (out / "README.md").write_text(
        "# %s\n\n"
        "Subsampled from `%s` by `scripts/build_test_fixture.py` so\n"
        "`tests/test_biological_plausibility.py` runs without the full dataset.\n\n"
        "- %d cells, deterministic even-index sample\n"
        "- %d panel genes plus %d control probes (the contamination check needs controls present)\n"
        "- no morphology, no boundaries: review-ready, not gate-ready\n"
        % (out.name, source.name, len(picked), len(gene_rows), len(control_rows)),
        encoding="utf-8",
    )

    size = sum(path.stat().st_size for path in out.rglob("*") if path.is_file())
    print("fixture: %s (%.1f MB)" % (out, size / 1e6))


def main() -> None:
    parser = argparse.ArgumentParser(description="Cut a committable Xenium test fixture.")
    parser.add_argument("source", help="Full Xenium output directory.")
    parser.add_argument("--out", default="tests/fixtures/xenium_mini", help="Fixture directory.")
    parser.add_argument("--cells", type=int, default=4000)
    parser.add_argument("--controls", type=int, default=40, help="Control probes to keep.")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    build(Path(args.source), Path(args.out), args.cells, args.controls, args.seed)


if __name__ == "__main__":
    main()
