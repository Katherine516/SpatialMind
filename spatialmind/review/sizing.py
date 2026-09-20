"""How much review actually opens the gate on a section.

`scripts/plan_expert_review.py` answers this in cells: 70% of whatever the run
loads, so 17,324 cells on the healthy brain section. That number is correct and
it is the wrong unit. Nobody labels 17,324 cells one at a time, and the Review
Studio's own gesture is a cluster click -- so the cost is **decisions**, and the
decisions are few:

    healthy brain    24,406 cells, 16 clusters  ->  7 decisions reach 70%
    glioblastoma     40,887 cells, 24 clusters  -> 10 decisions
    breast S1       209,467 cells, 19 clusters  ->  8 decisions
    lymph node      377,985 cells, 31 clusters  -> 10 decisions

Which is the honest sizing and also the dangerous one, so this module reports
both sides of it.

**What a cluster decision asserts.** Labelling cluster 3 "oligodendrocyte"
claims that all 2,528 of its cells are oligodendrocytes. That is a real
biological judgement and it is wrong at the margins of every cluster. Seven
decisions is therefore the *floor* -- what the gate arithmetic requires -- and
not an estimate of careful work. A reviewer who checks marker evidence per
cluster, splits the mixed ones and refuses the ambiguous ones does more than
seven things, and should.

**What it costs downstream.** The gate counts coverage; it does not count depth.
Seven cluster-level decisions produce `review_decisions: 7` against ~17,000
covered cells, and the reliability caveat says so on every claim -- "coverage is
not review depth". That is the trade being made visible, not a warning against
making it.
"""

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# The gate's defaults. Imported rather than repeated so a threshold change here
# cannot drift from the gate that enforces it.
from ..gatekeeper import DEFAULT_MIN_LABEL_COVERAGE, DEFAULT_MIN_REGION_COVERAGE

# The gate needs two distinct biological classes, and marker statistics need
# enough cells in each group to test. A class under this is a class the
# validated lane will skip.
MIN_CELLS_FOR_MARKERS = 50

# Labels that are not a decision: 10x leaves some cells unassigned, and an
# unassigned cluster cannot be given a cell type.
UNASSIGNED = {"", "unassigned", "none", "nan", "na", "-1"}


def _is_assignable(name: Any) -> bool:
    return str(name).strip().lower() not in UNASSIGNED


def decisions_for_coverage(sizes: Dict[Any, int],
                           coverage: float = DEFAULT_MIN_LABEL_COVERAGE) -> Dict[str, Any]:
    """How many groups, largest first, cover `coverage` of the cells.

    Largest first because that is what a reviewer does and what minimises the
    work; it is also what makes the resulting `review_decisions` smallest, which
    is exactly why the report states that number rather than hiding it.
    """
    assignable = {name: int(count) for name, count in sizes.items() if _is_assignable(name)}
    total = sum(int(count) for count in sizes.values())
    if total <= 0:
        return {"total_cells": 0, "decisions": 0, "covered_cells": 0,
                "achieved_coverage": 0.0, "reachable": False, "groups": []}

    ordered = sorted(assignable.items(), key=lambda kv: -kv[1])
    chosen: List[Tuple[Any, int]] = []
    covered = 0
    for name, count in ordered:
        if covered / total >= coverage:
            break
        chosen.append((name, count))
        covered += count

    reachable = (covered / total) >= coverage
    # One group covering everything is not a cluster solution, it is the absence
    # of one: the bundle shipped no clustering and the whole section is a single
    # bucket. Reporting "1 decision reaches 100%" for that would be the most
    # encouraging and least true line in the plan.
    no_solution = len(ordered) <= 1 and covered >= total
    return {
        "no_cluster_solution": no_solution,
        "total_cells": total,
        "assignable_cells": sum(assignable.values()),
        "available_groups": len(ordered),
        "decisions": len(chosen),
        "covered_cells": covered,
        "achieved_coverage": round(covered / total, 4) if total else 0.0,
        "required_coverage": coverage,
        "reachable": reachable,
        "smallest_chosen": chosen[-1][1] if chosen else 0,
        "groups": [{"group": str(name), "cells": count} for name, count in chosen],
        # What each decision commits to, on average. The point of printing it is
        # that a reviewer should see the number before clicking.
        "cells_per_decision": int(covered / len(chosen)) if chosen else 0,
    }


def marker_readiness(sizes: Dict[Any, int],
                     min_cells: int = MIN_CELLS_FOR_MARKERS) -> Dict[str, Any]:
    """Which groups are big enough for the validated lane to test at all.

    A section can clear the coverage gate and then fail with
    `blocked_analysis_backend` because a labelled class has too few cells for
    one-vs-rest marker statistics. Checking here means that is a sentence in a
    plan rather than a failure after the review.
    """
    assignable = {name: int(count) for name, count in sizes.items() if _is_assignable(name)}
    testable = {name: count for name, count in assignable.items() if count >= min_cells}
    return {
        "min_cells_for_markers": min_cells,
        "groups": len(assignable),
        "testable_groups": len(testable),
        "too_small": sorted(
            ({"group": str(name), "cells": count}
             for name, count in assignable.items() if count < min_cells),
            key=lambda item: item["cells"]),
        # The gate needs two distinct biological classes; anything under that
        # cannot open regardless of coverage.
        "meets_two_class_minimum": len(testable) >= 2,
    }


def size_label_review(cluster_sizes: Dict[Any, int],
                      coverage: float = DEFAULT_MIN_LABEL_COVERAGE) -> Dict[str, Any]:
    plan = decisions_for_coverage(cluster_sizes, coverage=coverage)
    plan["markers"] = marker_readiness(cluster_sizes)
    plan["kind"] = "labels"
    return plan


def size_region_review(region_sizes: Dict[Any, int],
                       coverage: float = DEFAULT_MIN_REGION_COVERAGE) -> Dict[str, Any]:
    plan = decisions_for_coverage(region_sizes, coverage=coverage)
    plan["kind"] = "regions"
    # Regions have their own floor: a single reviewed region supports no
    # contrast, and the gate refuses it unless explicitly waived.
    plan["meets_two_region_minimum"] = plan["decisions"] >= 2
    return plan


def read_candidate_regions(path: str) -> Dict[str, int]:
    """Domain sizes from a `cell_regions_candidate.csv` written by a run."""
    import csv

    counts: Counter = Counter()
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("candidate_region") or row.get("region") or "").strip()
            if name:
                counts[name] += 1
    return dict(counts)



def read_run_clusters(run_dir: str) -> Dict[str, int]:
    """Cluster sizes from a descriptive run's own clustering.

    A bundle usually ships 10x's graphclust *and* a run produces its own Leiden
    solution, and they are not the same size -- on the healthy brain section, 16
    against 9. Which one the reviewer labels against changes the decision count,
    so both are worth reporting rather than silently picking one.
    """
    import json

    path = Path(run_dir) / "descriptive_qc_and_cluster.json"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            metrics = (json.load(handle) or {}).get("metrics") or {}
    except (OSError, ValueError):
        return {}
    counts = metrics.get("cluster_counts") or metrics.get("cluster_sizes") or {}
    return {str(name): int(count) for name, count in counts.items()}


def read_run_markers(run_dir: str, top_n: int = 6) -> Dict[str, List[str]]:
    """Top marker genes per cluster, from a run's marker detection.

    This is what makes a cluster decision reviewable rather than a guess: the
    reviewer sees GJA1, AQP4, SOX9 and calls it, instead of naming a number.
    """
    import json

    path = Path(run_dir) / "descriptive_marker_detection.json"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            metrics = (json.load(handle) or {}).get("metrics") or {}
    except (OSError, ValueError):
        return {}
    markers: Dict[str, List[str]] = {}
    for group, rows in (metrics.get("markers_by_group") or {}).items():
        genes = []
        for row in rows[:top_n]:
            gene = str((row or {}).get("gene") or "").strip()
            if gene:
                genes.append(gene)
        markers[str(group)] = genes
    return markers


def summarise(dataset_name: str, label_plan: Dict[str, Any],
              region_plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One section's plan, with the blockers it still has."""
    blockers: List[str] = []
    if label_plan.get("no_cluster_solution"):
        blockers.append(
            "No clustering to review: this bundle ships no cluster solution, so there is nothing "
            "to label cluster by cluster. Run the descriptive lane first.")
    if not label_plan.get("reachable"):
        blockers.append(
            "Labelling every cluster still covers only %.1f%% of cells; the gate needs %.0f%%."
            % (100 * label_plan["achieved_coverage"], 100 * label_plan["required_coverage"]))
    # `.get`, not `[...]`: a caller can hand over a bare coverage plan, and
    # crashing on a missing key would lose every other blocker in the report.
    markers = label_plan.get("markers") or {}
    if markers and not markers.get("meets_two_class_minimum"):
        blockers.append(
            "Fewer than two groups have %d cells, which is the floor for marker statistics."
            % markers.get("min_cells_for_markers", MIN_CELLS_FOR_MARKERS))
    if region_plan is None:
        blockers.append(
            "No region candidates yet. Run the descriptive lane to write "
            "`cell_regions_candidate.csv`, then name the domains.")
    else:
        if not region_plan.get("reachable"):
            blockers.append(
                "Naming every proposed domain covers only %.1f%% of cells; the gate needs %.0f%%."
                % (100 * region_plan["achieved_coverage"], 100 * region_plan["required_coverage"]))
        if not region_plan.get("meets_two_region_minimum"):
            blockers.append("Fewer than two regions would be named; a contrast needs two.")

    total_decisions = label_plan["decisions"] + (region_plan["decisions"] if region_plan else 0)
    # A total with an uncounted side is a lower bound, and ranking it against a
    # complete total would make the least-measured section look like the
    # cheapest one. It did: Breast S1 came first at 8 decisions purely because
    # nobody had proposed its regions yet.
    complete = region_plan is not None and not label_plan.get("no_cluster_solution")
    return {
        "dataset": dataset_name,
        "labels": label_plan,
        "regions": region_plan,
        "total_decisions": total_decisions,
        "total_is_complete": complete,
        "blockers": blockers,
        "opens_gate": not blockers,
    }


def format_plan(summary: Dict[str, Any]) -> str:
    """The plan as a reviewer would want to read it."""
    lines: List[str] = []
    labels = summary["labels"]
    regions = summary.get("regions")

    lines.append(summary["dataset"])
    lines.append("=" * len(summary["dataset"]))
    lines.append("")
    lines.append("LABELS   %s cells in %d clusters"
                 % (format(labels["total_cells"], ","), labels["available_groups"]))
    lines.append("         %d decision(s) reach %.1f%% coverage (gate needs %.0f%%)"
                 % (labels["decisions"], 100 * labels["achieved_coverage"],
                    100 * labels["required_coverage"]))
    lines.append("         each decision names ~%s cells at once; smallest is %s"
                 % (format(labels["cells_per_decision"], ","),
                    format(labels["smallest_chosen"], ",")))
    for group in labels["groups"]:
        lines.append("           %-14s %9s cells" % (group["group"], format(group["cells"], ",")))
    markers = labels.get("markers") or {}
    if markers:
        lines.append("         %d of %d clusters have >=%d cells, the floor for marker statistics"
                     % (markers["testable_groups"], markers["groups"],
                        markers["min_cells_for_markers"]))
        if markers["too_small"]:
            lines.append("           too small: %s" % ", ".join(
                "%s (%d)" % (item["group"], item["cells"]) for item in markers["too_small"][:5]))

    lines.append("")
    if regions:
        lines.append("REGIONS  %d proposed domain(s)" % regions["available_groups"])
        lines.append("         %d decision(s) reach %.1f%% coverage (gate needs %.0f%%)"
                     % (regions["decisions"], 100 * regions["achieved_coverage"],
                        100 * regions["required_coverage"]))
        for group in regions["groups"]:
            lines.append("           %-14s %9s cells" % (group["group"], format(group["cells"], ",")))
    else:
        lines.append("REGIONS  not proposed yet")

    lines.append("")
    if summary.get("total_is_complete"):
        lines.append("TOTAL    %d decision(s) to open the gate" % summary["total_decisions"])
    else:
        lines.append("TOTAL    at least %d decision(s); one side is not counted yet, so this is a "
                     "lower bound" % summary["total_decisions"])
    if summary["blockers"]:
        lines.append("")
        lines.append("STILL BLOCKED")
        for blocker in summary["blockers"]:
            lines.append("  x %s" % blocker)

    lines.append("")
    lines.append("WHAT THIS BUYS, AND WHAT IT DOES NOT")
    lines.append("  A cluster decision asserts that every cell in that cluster is the class you")
    lines.append("  named. That is a real biological judgement and it is wrong at the margins of")
    lines.append("  every cluster, so %d is the arithmetic floor and not an estimate of careful"
                 % summary["total_decisions"])
    lines.append("  work. The run will record `review_decisions: %d` against %s covered cells,"
                 % (labels["decisions"], format(labels["covered_cells"], ",")))
    lines.append("  and every claim will carry the caveat that coverage is not review depth.")
    return "\n".join(lines)


# ------------------------------------------------------------------ worksheet

WORKSHEET_FIELDS = [
    "cluster", "n_cells", "share_of_section", "top_markers",
    "loader_guess", "expert_label", "confidence", "uncertain", "notes",
]
WORKSHEET_NAME = "cluster_label_worksheet.csv"


def read_run_cell_clusters(run_dir: str) -> List[Tuple[str, str]]:
    """(cell_id, cluster) for every cell a run clustered, from its cells table."""
    import csv
    import gzip

    directory = Path(run_dir) / "tables"
    for name in ("cells.tsv", "cells.tsv.gz"):
        path = directory / name
        if not path.exists():
            continue
        opener = gzip.open if name.endswith(".gz") else open
        rows: List[Tuple[str, str]] = []
        with opener(path, "rt", newline="", encoding="utf-8") as handle:
            # Result tables carry `#` provenance lines before the header.
            lines = (line for line in handle if not line.startswith("#"))
            for row in csv.DictReader(lines, delimiter="\t"):
                cell_id = str(row.get("cell_id") or "").strip()
                cluster = str(row.get("cluster") or "").strip()
                if cell_id and cluster:
                    rows.append((cell_id, cluster))
        return rows
    return []


def write_cluster_worksheet(run_dir: str, output_path: str,
                            loader_guesses: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One row per cluster, with the marker evidence to decide on.

    The run already writes a per-cell label template with 24,362 rows. That
    matches the gate's arithmetic and not the work: the review is a handful of
    cluster calls, and a 24,362-row file invites either per-cell labelling
    nobody will do or a spreadsheet fill-down that hides how few decisions were
    actually made.

    Markers are shown, and shown first. Unlike a region's cell composition --
    which is circular, because the domains were named from it -- a cluster's
    differential markers are the evidence for a cell-type call, not a restatement
    of one.
    """
    import csv

    sizes = read_run_clusters(run_dir)
    markers = read_run_markers(run_dir)
    if not sizes:
        return {"status": "unavailable",
                "reason": "No clustering found in %s; run the descriptive lane first." % run_dir}

    total = sum(sizes.values()) or 1
    guesses = loader_guesses or {}
    rows = sorted(sizes.items(), key=lambda kv: -kv[1])

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=WORKSHEET_FIELDS)
        writer.writeheader()
        for cluster, count in rows:
            writer.writerow({
                "cluster": cluster,
                "n_cells": count,
                "share_of_section": "%.1f%%" % (100.0 * count / total),
                "top_markers": ", ".join(markers.get(cluster, [])),
                # The loader's marker rule is a guess, and it is in its own
                # column so it cannot be mistaken for the evidence beside it.
                "loader_guess": guesses.get(cluster, ""),
                "expert_label": "",
                "confidence": "",
                "uncertain": "",
                "notes": "",
            })

    plan = decisions_for_coverage(sizes)
    return {
        "status": "written",
        "path": str(target),
        "clusters": len(rows),
        "total_cells": total,
        "decisions_for_gate": plan["decisions"],
        "coverage_at_that": plan["achieved_coverage"],
        "with_markers": sum(1 for cluster, _ in rows if markers.get(cluster)),
    }


def apply_cluster_labels(run_dir: str, worksheet: str, reviewer_id: str,
                         output_path: str) -> Dict[str, Any]:
    """Expand a filled worksheet into `expert_cell_labels.csv`.

    Every row records `assignment_scope=cluster:<id>`, so the gate's
    `review_decisions` counts the calls that were actually made -- four, not the
    17,909 cells they covered. That number is what the reliability caveat prints,
    and writing per-cell rows without it would turn four judgements into
    seventeen thousand apparent ones.
    """
    import csv

    with open(worksheet, newline="", encoding="utf-8") as handle:
        named = {}
        for row in csv.DictReader(handle):
            label = str(row.get("expert_label") or "").strip()
            if not label:
                continue
            named[str(row.get("cluster") or "").strip()] = {
                "label": label,
                "confidence": str(row.get("confidence") or "").strip() or "0.9",
                "uncertain": str(row.get("uncertain") or "").strip(),
                "notes": str(row.get("notes") or "").strip(),
            }
    if not named:
        return {"status": "empty", "reason": "No cluster in %s has an expert_label." % worksheet}

    assignments = read_run_cell_clusters(run_dir)
    if not assignments:
        return {"status": "unavailable",
                "reason": "No per-cell cluster assignments in %s/tables." % run_dir}

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cell_id", "expert_label", "confidence", "notes",
                         "assignment_scope", "reviewer_id"])
        for cell_id, cluster in assignments:
            entry = named.get(cluster)
            if not entry:
                continue
            note = entry["notes"] or "named from cluster marker evidence"
            if entry["uncertain"]:
                note = "%s; reviewer marked uncertain" % note
            writer.writerow([cell_id, entry["label"], entry["confidence"], note,
                             "cluster:%s" % cluster, reviewer_id])
            written += 1

    classes = {entry["label"] for entry in named.values()}
    coverage = written / max(len(assignments), 1)
    return {
        "status": "written",
        "path": str(target),
        "reviewer_id": reviewer_id,
        "clusters_named": len(named),
        "clusters_left_blank": sorted(
            {cluster for _, cluster in assignments} - set(named)),
        "cells_written": written,
        "coverage_of_clustered": round(coverage, 4),
        "distinct_classes": len(classes),
        "meets_two_class_minimum": len(classes) >= 2,
    }
