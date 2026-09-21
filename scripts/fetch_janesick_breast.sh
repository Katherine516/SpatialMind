#!/bin/sh
# Fetch the Xenium breast cancer replicate 1 section and its published per-cell
# cell type annotations. About 650 MB.
#
# Seven files rather than the 9.86 GB `_outs.zip`: the agent reads roughly 6 MB
# of a Xenium bundle, and the rest of that archive is transcript tables and a
# full-resolution morphology stack it catalogues for provenance and never parses.
#
# Instrument data  10x Genomics, Xenium Analyzer 1.0.1 (December 2022)
# Annotations      Janesick et al. 2023, Nat Commun 14:8353, CC BY 4.0
#
# The Analyzer version matters. These annotations key on integer cell ids, the
# pre-2023 Xenium format; a bundle reprocessed with a later Analyzer uses
# `aaaafije-1` style ids and will not join. scripts/import_published_labels.py
# reports `unmatched to bundle`, which is what catches that.
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEST="$ROOT/data/Xenium_Breast_Cancer_Rep1_Janesick2023"
BASE="https://cf.10xgenomics.com/samples/xenium/1.0.1/Xenium_FFPE_Human_Breast_Cancer_Rep1/Xenium_FFPE_Human_Breast_Cancer_Rep1"
ZENODO="https://zenodo.org/records/10076046/files/Cell_Barcode_Type_Matrices.xlsx?download=1"

mkdir -p "$DEST"

for f in experiment.xenium metrics_summary.csv gene_panel.json \
         cells.csv.gz cell_feature_matrix.h5 cell_boundaries.csv.gz \
         morphology_mip.ome.tif; do
  if [ -s "$DEST/$f" ]; then
    echo "have $f"
    continue
  fi
  echo "fetching $f ..."
  curl -L --retry 3 --fail --progress-bar -o "$DEST/$f" "${BASE}_${f}"
done

if [ -s "$DEST/Cell_Barcode_Type_Matrices.xlsx" ]; then
  echo "have Cell_Barcode_Type_Matrices.xlsx"
else
  echo "fetching Cell_Barcode_Type_Matrices.xlsx ..."
  curl -L --retry 3 --fail --progress-bar -o "$DEST/Cell_Barcode_Type_Matrices.xlsx" "$ZENODO"
fi

echo
echo "Fetched to $DEST"
echo "Next:"
echo "  python scripts/import_published_labels.py \\"
echo "      --workbook $DEST/Cell_Barcode_Type_Matrices.xlsx \\"
echo "      --sheet 'Xenium R1 Fig1-5 (supervised)' --bundle $DEST"
