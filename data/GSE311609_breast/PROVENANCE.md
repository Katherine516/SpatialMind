# GSE311609 — Xenium breast carcinoma, independent donors

Fetched to give this workspace a **second donor**, which is what
`assess_condition_replication` needs and what one section, however many cells it
holds, can never supply.

## What is here

| Sample | Donor | Cells | GEO |
| --- | --- | --- | --- |
| `breast_breast_B1_B1_1` | B1 | 124,709 | GSM9509172 |
| `breast_breast_B2_B2` | B2 | 148,150 | GSM9509160 |

Four files per sample — `cells.parquet.gz`, `cell_feature_matrix.h5`, and both
boundary tables — about 23 MB each. The morphology stack (240 MB focus, 2.8 GB
full) and the transcript table are not fetched; neither is on this project's
read path, and the focus image is opt-in with `--with-morphology`.

**Source.** NCBI GEO [GSE311609](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE311609),
from *Resolving sensitivity, specificity and signal contamination in Xenium
spatial transcriptomics*, Nature Methods (2026). Public, no controlled access.

```bash
python scripts/fetch_geo_xenium.py --series GSE311609 --match breast_B --list
python scripts/fetch_geo_xenium.py --series GSE311609 --match breast_B2_B2 \
    --dest data/GSE311609_breast
```

The series holds **19 breast sections from 17 donors** (plus 22 NSCLC sections
from 10 donors) at about 300 MB for the whole breast arm. Two were taken because
two donors is what the replication check needs; the rest is one command away.

## What it does not have, and why that matters

**No cell type labels of any kind.** GEO deposits none for this series. The
paper's cell types came from RCTD against matched snRNA-seq — label transfer,
which this project treats as a candidate needing review, not as expert truth.
Every section here therefore arrives blocked on a reviewer, exactly like the
brain and lymph node sections.

So acquiring donors moved one constraint and not the other:

```text
breast_carcinoma   3 sections, 3 donors      replication satisfied
                   expert labels: 1 of 3     validated lane still blocked
```

**No `experiment.xenium`.** Pixel size, panel name and run metadata are absent.
Coordinates are already in microns so the loader reads these bundles anyway, but
the morphology viewer cannot align an image without a pixel size, and the panel
is identified only by the 541 feature names in the matrix.

It also means nothing in the tooling can tell these are tumour sections — the
review sizing correctly reported `TISSUE UNKNOWN`. Each bundle therefore carries
a `tissue_context.json` saying so, with who said it and on what basis.
Fabricating an `experiment.xenium` to fix that would be inventing instrument
output; a separate file that names its author is the same pattern as
`reviewer_id` on a label table, and the plan prints "Asserted neoplastic by
hand" rather than "names itself".

**No morphology, yet.** Only the analysis files were fetched. The gate's
first condition needs a morphology image, so these sections cannot open it until
that is downloaded — one command, ~240 MB each, and NCBI throttled it when
tried:

```bash
python scripts/fetch_geo_xenium.py --series GSE311609 --match breast_B2_B2 \
    --dest data/GSE311609_breast --with-morphology
```

The fetch unwraps the gzipped OME-TIFF on arrival, because `tifffile` cannot
read one and every asset check looks for `morphology_focus.ome.tif`.

## What the review would cost

Both donors have had the descriptive lane run, so their reviews are sized:

```text
                     cells    clusters  labels  regions  total
breast_breast_B1_B1_1   124,513      9        4       7     11
breast_breast_B2_B2     130,791      8        3      11     14
```

Labels are cheap on both; B2's regions are not — 27 proposed domains, 11 of them
needed to cover 70%.

**One condition.** Everything here is breast carcinoma. A condition *comparison*
needs two conditions with at least two donors each; `scripts/assess_replication.py`
says so against `docs/replication_design.json`.

## The format that had to be fixed to read these

These bundles ship `cells.parquet.gz`, not `cells.csv.gz`. The asset check
already counted parquet as a present cell table while the loader read only CSV,
so a bundle like this passed readiness and then failed to load. That is fixed;
it is also why no GEO-deposited Xenium series could be used before.
