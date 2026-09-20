"""Convert published per-cell annotations into `expert_cell_labels.csv`.

The gate accepts exactly one label file, written by a human who takes
responsibility for it. That is the point, and it is why transferred labels land
in `*_candidate.csv` instead. A *published* annotation is the one case that is
neither: it was made by named experts, peer reviewed, and released under a
licence -- so it is expert truth, it is just not truth this reviewer produced.

This converts such a file, and records who made it. `reviewer_id` carries the
publication rather than a local name, because the provenance a reader needs is
"Janesick et al. 2023, supervised annotation" and not "imported on a Tuesday".

Currently supports Janesick et al. 2023 (Nat Commun 14:8353), whose Zenodo record
carries supervised per-cell types for both Xenium breast replicates:

    python scripts/import_published_labels.py \\
        --workbook Cell_Barcode_Type_Matrices.xlsx \\
        --sheet "Xenium R1 Fig1-5 (supervised)" \\
        --bundle data/Xenium_Breast_Cancer_Rep1_Janesick2023

`Unlabeled` is dropped rather than written through. It is the authors' own
"we could not call this one", and carrying it into `expert_label` would turn an
explicit abstention into a class name -- the same mistake as letting a loader
guess count as a label.

## Why `unmatched to bundle` is not enough on its own

Pre-2023 Xenium bundles number cells `1, 2, 3, ...`. Any annotation of any
section with fewer cells joins to such a bundle at **100%**, because every id in
`1..N` exists. A published breast annotation was checked against this workspace's
breast section and reported `unmatched to bundle: 0` while being a different
tissue block entirely -- the domains turned out to be statistically independent
of the section's own published cell types.

So a dense-integer bundle gets a second check: agreement with an annotation
already in the bundle, via Cramer's V. Two descriptions of the same tissue are
strongly dependent; two descriptions of different tissue are independent, and V
lands near zero no matter how cleanly the ids line up.
"""

import argparse
import csv
import gzip
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LABEL_FIELDS = ["cell_id", "expert_label", "confidence", "notes",
                "assignment_scope", "reviewer_id", "source"]

# Classes that are an explicit abstention rather than a cell type.
ABSTENTIONS = {"unlabeled", "unassigned", "unknown", "na", ""}

# Measured on this workspace's one section with two independent annotations
# (Xenium breast Rep1), against a published breast annotation known to belong to
# a different tissue block:
#
#     published cell types x this section's regions     V = 0.223   same section
#     published cell types x foreign IDC domains        V = 0.048   different
#     published cell types x foreign ILC domains        V = 0.054   different
#     this section's regions x foreign IDC domains      V = 0.183   different
#
# The last line is why there is no single clean cut. Xenium numbers cells in
# spatial order, so two blocky annotations share structure through the id
# ordering alone even across sections -- and a coarse region table compared with
# a fine cell-type table is a weak pairing to begin with. Below 0.10 the two are
# independent and that is decidable. Between 0.10 and 0.30 a real pairing and a
# foreign one overlap, so the tool stops and says so rather than pretending to
# know.
INDEPENDENT_BELOW = 0.10
WEAK_BELOW = 0.30
CALIBRATION_NOTE = (
    "  (V is confounded here: Xenium ids run in spatial order, so two blocky annotations agree "
    "above chance even across sections. Comparing cell types with cell types separates far "
    "better than cell types with regions.)"
)


def read_bundle_cell_ids(bundle: Path) -> set:
    """Cell ids as the loader will see them, so a mismatch is caught here."""
    for name in ("cells.csv.gz", "cells.csv"):
        path = bundle / name
        if not path.exists():
            continue
        opener = gzip.open if name.endswith(".gz") else open
        with opener(path, "rt", newline="") as handle:
            return {str(row["cell_id"]).strip() for row in csv.DictReader(handle)}
    raise SystemExit("No cells.csv.gz in %s" % bundle)



def ids_are_dense_integers(ids) -> bool:
    """True when ids are integers filling most of `1..max`.

    On such a bundle a match count carries almost no information: an annotation
    of a different, smaller section matches every row.
    """
    try:
        numbers = [int(value) for value in ids]
    except (TypeError, ValueError):
        return False
    if not numbers:
        return False
    span = max(numbers) - min(numbers) + 1
    return span > 0 and len(set(numbers)) / span > 0.9


def cramers_v(pairs) -> float:
    """Association between two categorical labellings of the same cells, 0..1.

    Chi-square normalised by n and the smaller dimension. 0 means the two
    labellings are independent -- which, for two descriptions of one tissue, is
    not a weak result but a contradiction.
    """
    from collections import Counter

    joint = Counter(pairs)
    if not joint:
        return 0.0
    rows = Counter()
    cols = Counter()
    for (a, b), n in joint.items():
        rows[a] += n
        cols[b] += n
    total = sum(joint.values())
    if total == 0 or len(rows) < 2 or len(cols) < 2:
        return 0.0
    chi2 = 0.0
    for a, row_total in rows.items():
        for b, col_total in cols.items():
            expected = row_total * col_total / total
            if expected <= 0:
                continue
            observed = joint.get((a, b), 0)
            chi2 += (observed - expected) ** 2 / expected
    return (chi2 / (total * (min(len(rows), len(cols)) - 1))) ** 0.5


def read_existing_annotation(bundle: Path):
    """Per-cell annotations already in the bundle, to corroborate against.

    Returns `(same_kind, other_kind)`. Only the same-kind comparison -- cell
    types against cell types -- is decisive enough to refuse on; see the
    calibration above. A region table is reported and never blocks.
    """
    def read(name, value_key):
        path = bundle / name
        if not path.exists():
            return None
        with open(path, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not rows or value_key not in rows[0]:
            return None
        id_key = next((k for k in ("cell_id", "cell") if k in rows[0]), None)
        if not id_key:
            return None
        return name, {str(r[id_key]).strip(): str(r[value_key]).strip() for r in rows}

    return read("expert_cell_labels.csv", "expert_label"), read("cell_regions.csv", "region")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import published per-cell annotations.")
    parser.add_argument("--workbook", required=True, help="Published annotation workbook (.xlsx) or table (.csv).")
    parser.add_argument("--sheet", default="", help="Worksheet name, for a workbook.")
    parser.add_argument("--bundle", required=True, help="Xenium output folder the labels belong to.")
    parser.add_argument("--barcode-column", default="Barcode")
    parser.add_argument("--label-column", default="Cluster")
    parser.add_argument("--reviewer-id", default="Janesick et al. 2023, Nat Commun 14:8353")
    parser.add_argument("--source", default="https://zenodo.org/records/10076046 (CC BY 4.0)")
    parser.add_argument("--confidence", type=float, default=1.0,
                        help="Recorded per row. 1.0 for a published supervised annotation.")
    parser.add_argument("--dry-run", action="store_true", help="Report the join and write nothing.")
    parser.add_argument("--accept-weak-agreement", action="store_true",
                        help="Proceed when agreement with the bundle's existing annotation is in the "
                             "ambiguous band. Use only after checking the pairing by hand.")
    args = parser.parse_args()

    bundle = Path(args.bundle)
    cell_ids = read_bundle_cell_ids(bundle)

    path = Path(args.workbook)
    if path.suffix.lower() in (".xlsx", ".xls"):
        import pandas as pd

        frame = pd.read_excel(path, sheet_name=args.sheet or 0)
        rows = frame.to_dict("records")
    else:
        with open(path, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

    written, abstained, unmatched = [], 0, 0
    counts: Counter = Counter()
    for row in rows:
        cell_id = str(row.get(args.barcode_column, "")).strip()
        label = str(row.get(args.label_column, "")).strip()
        if label.lower() in ABSTENTIONS:
            abstained += 1
            continue
        # A label whose cell is not in this bundle is a sign the annotation and
        # the section do not belong together -- the single most important thing
        # to catch, and silent if it is not counted.
        if cell_id not in cell_ids:
            unmatched += 1
            continue
        written.append((cell_id, label))
        counts[label] += 1

    coverage = len(written) / max(len(cell_ids), 1)
    print("bundle cells      : %d" % len(cell_ids))
    print("annotation rows   : %d" % len(rows))
    print("abstentions       : %d (the authors' own 'unlabeled')" % abstained)
    print("unmatched to bundle: %d" % unmatched)
    print("labels written    : %d  -> %.2f%% coverage" % (len(written), 100 * coverage))
    print("classes           : %d" % len(counts))
    if unmatched:
        print("\nWARNING: %d labels had no matching cell. Check that the annotation and this "
              "bundle are the same section and the same Xenium Analyzer version." % unmatched)
    if coverage < 0.7:
        print("\nNOTE: coverage is below the 0.70 gate default; the pilot will still block.")

    # A clean join is not evidence on a bundle numbered 1..N. Say so, and check
    # the annotation against whatever this bundle already knows about its cells.
    if ids_are_dense_integers(cell_ids):
        print("\nThis bundle numbers cells 1..N, so ANY annotation of a section with at most "
              "%d cells joins at 100%%. The match count above is not evidence of provenance." % len(cell_ids))
        same_kind, other_kind = read_existing_annotation(bundle)
        written_by_cell = dict(written)

        def agreement(entry):
            name, table = entry
            shared = [(table[cell_id], label)
                      for cell_id, label in written_by_cell.items() if cell_id in table]
            return name, len(shared), cramers_v(shared)

        if other_kind:
            name, n, association = agreement(other_kind)
            print("Against %s (different kind of annotation): %d shared cells, Cramer's V = %.3f"
                  % (name, n, association))
            print(CALIBRATION_NOTE)
            print("  Reported only. A cell-type table and a region table do not separate cleanly "
                  "enough for this to decide anything.")

        if not same_kind:
            print("\nNo existing cell-type annotation here to compare against, so nothing "
                  "corroborates the join. Confirm by hand that the publication and this section "
                  "are the same tissue block.")
        else:
            name, n, association = agreement(same_kind)
            print("\nAgainst %s (same kind): %d shared cells, Cramer's V = %.3f"
                  % (name, n, association))
            if association < INDEPENDENT_BELOW:
                print("\nREFUSING: at V < %.2f two cell-type annotations of the same cells are "
                      "independent, which they cannot be. This is a different section whose ids "
                      "happen to overlap." % INDEPENDENT_BELOW)
                raise SystemExit(2)
            if association < WEAK_BELOW and not args.accept_weak_agreement:
                print("\nSTOPPING: V = %.3f is in the band where a real pairing and a foreign one "
                      "overlap. Re-run with --accept-weak-agreement if you have checked by hand."
                      % association)
                raise SystemExit(2)
            print("Consistent with the annotation already in this bundle.")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    target = bundle / "expert_cell_labels.csv"
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(LABEL_FIELDS)
        for cell_id, label in written:
            writer.writerow([
                cell_id, label, "%.2f" % args.confidence,
                "published supervised annotation",
                # One decision per cell: the authors called each cell individually.
                "published:%s" % cell_id,
                args.reviewer_id,
                args.source,
            ])
    print("\nwrote %s" % target)


if __name__ == "__main__":
    main()
