"""Say what a set of sections can and cannot support, before anyone runs one.

Cells within one tissue section are not independent biological replicates. A
healthy-versus-disease difference computed from one section per condition is
pseudoreplication: the apparent sample size is the cell count, but the real
sample size is one donor per group, so nothing about the conditions generalises
no matter how many cells were measured.

This reads a design manifest -- which sections, which donor, which condition --
and reports what the design supports, using the same
`assess_condition_replication` the pipeline uses. It is meant to be run
*before* acquiring more data, because the answer usually changes what to
acquire.

    python scripts/assess_replication.py --design docs/replication_design.json

A design manifest is a JSON object mapping a condition to its sections:

    {"breast_carcinoma": [
        {"section_id": "B1_1", "donor_id": "B1", "cell_count": 124709,
         "labels": "none"}]}

`labels` is optional and is reported, not tested: the gate decides that per
section. It is here because a design that satisfies replication and has no
expert labels supports nothing in the validated lane, and a report that only
counted donors would say the design was fine.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.methods.replication import assess_condition_replication


def main() -> None:
    parser = argparse.ArgumentParser(description="Report what a set of sections supports.")
    parser.add_argument("--design", required=True, help="Design manifest JSON.")
    parser.add_argument("--json", action="store_true", help="Print the full assessment as JSON.")
    args = parser.parse_args()

    with open(args.design, encoding="utf-8") as handle:
        design = json.load(handle)
    sections_by_condition = design.get("conditions") or design
    result = assess_condition_replication(sections_by_condition)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    print("DESIGN")
    for condition, summary in sorted((result.get("conditions") or {}).items()):
        print("  %-22s %d section(s), %d donor(s), %s cells"
              % (condition, summary["section_count"], summary["donor_count"],
                 format(summary["cell_count"], ",")))

    labelled = _label_status(sections_by_condition)
    if labelled:
        print("\nLABELS")
        for condition, counts in sorted(labelled.items()):
            print("  %-22s %s" % (condition, ", ".join(
                "%s: %d" % (state, n) for state, n in sorted(counts.items()))))

    blockers = result.get("blockers") or []
    print("\nVERDICT")
    if blockers:
        for blocker in blockers:
            print("  x %s" % blocker)
    else:
        print("  Condition-level inference is supported by this design.")

    print("\n  unit of analysis : %s" % result.get("unit_of_analysis", "?"))
    print("  interpretation   : %s" % result.get("allowed_interpretation", "?"))
    print("  statistics       : %s" % result.get("recommended_statistics", "?"))

    for item in (result.get("required_next_inputs") or []):
        print("\n  next: %s" % item)

    # Replication and labels are separate gates, and satisfying one says nothing
    # about the other. A design that passes here and has no reviewed labels
    # still produces descriptive results only.
    unlabelled = sum(counts.get("none", 0) for counts in labelled.values())
    if unlabelled:
        print("\n  %d section(s) carry no expert labels. Replication is about design; the "
              "validated lane is about review. This design would run descriptively." % unlabelled)


def _label_status(sections_by_condition):
    status = {}
    for condition, sections in sections_by_condition.items():
        counts = {}
        for section in sections:
            state = str(section.get("labels") or "unknown")
            counts[state] = counts.get(state, 0) + 1
        if counts:
            status[condition] = counts
    return status


if __name__ == "__main__":
    main()
