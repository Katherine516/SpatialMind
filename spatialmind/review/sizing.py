"""How much review actually opens the gate on a section.

`scripts/plan_expert_review.py` answers this in cells: 70% of whatever the run
loads, so 17,324 cells on the healthy brain section. That number is correct and
it is the wrong unit. Nobody labels 17,324 cells one at a time, and the Review
Studio's own gesture is a cluster click -- so the cost is **decisions**, and the
decisions are few. Measured across this workspace's four blocked sections:

                  cells run   clusters  labels  regions  total
    healthy brain      24,362        9        4       6     10
    glioblastoma       40,786       11        5       6     11
    lymph node        372,099        8        2       9     11
    breast S1         201,426        9        5      11     16

**Which clustering you count against changes the answer**, so a plan says which
it used. A bundle ships 10x's graphclust and a descriptive run makes its own
Leiden solution, and they are not the same size -- 16 against 9 on the healthy
brain section, so 7 decisions against 4. The run's is preferred because it is
the one carrying differential markers, which is what makes a cluster call
reviewable rather than a guess.

This is the honest sizing and also the dangerous one, so the module reports both
sides of it.

**What a cluster decision asserts.** Labelling cluster 5 "oligodendrocyte"
claims that all 4,763 of its cells are oligodendrocytes. That is a real
biological judgement and it is wrong at the margins of every cluster. Ten
decisions is therefore the *floor* -- what the gate arithmetic requires -- and
not an estimate of careful work. A reviewer who checks marker evidence per
cluster, splits the mixed ones and refuses the ambiguous ones does more than ten
things, and should.

**What the minimum buys.** Two named classes clear the gate's two-class
condition and leave exactly one cell-type pair to test. The lymph node reaches
70% on T cells and B cells alone, so its cheapest review is also its thinnest
result; `pair_count` exists so the plan says that rather than reporting the
cheapness alone.

**What it costs downstream.** The gate counts coverage; it does not count depth.
Four cluster-level decisions produce `review_decisions: 4` against 17,909
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


def pair_count(classes: int) -> int:
    """Unordered pairs among `classes` labelled groups.

    The gate needs two classes; two classes give one pair. The decision count
    and the analysis it enables are not the same number, and only one of them
    was ever printed.
    """
    return max(classes, 0) * max(classes - 1, 0) // 2


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




def _tool_metrics(run_dir: str, tool: str) -> Dict[str, Any]:
    """One tool's metrics from a run, whichever kind of run it was.

    A pilot writes `descriptive_<tool>.json` per tool; a Studio plan run writes
    one `plan_results.json` holding every tool's output. Reading only the first
    meant the app could not size a review against a clustering it had just
    produced itself.
    """
    import json

    directory = Path(run_dir)
    path = directory / ("descriptive_%s.json" % tool)
    if path.exists():
        try:
            with open(path, encoding="utf-8") as handle:
                return (json.load(handle) or {}).get("metrics") or {}
        except (OSError, ValueError):
            return {}

    combined = directory / "plan_results.json"
    if not combined.exists():
        return {}
    try:
        with open(combined, encoding="utf-8") as handle:
            payload = json.load(handle) or {}
    except (OSError, ValueError):
        return {}
    for result in (payload.get("results") or []):
        if str(result.get("tool")) == tool:
            return result.get("metrics") or {}
    return {}


def read_run_clusters(run_dir: str) -> Dict[str, int]:
    """Cluster sizes from a descriptive run's own clustering.

    A bundle usually ships 10x's graphclust *and* a run produces its own Leiden
    solution, and they are not the same size -- on the healthy brain section, 16
    against 9. Which one the reviewer labels against changes the decision count,
    so both are worth reporting rather than silently picking one.
    """
    import json

    metrics = _tool_metrics(run_dir, "qc_and_cluster")
    counts = metrics.get("cluster_counts") or metrics.get("cluster_sizes") or {}
    return {str(name): int(count) for name, count in counts.items()}


def read_run_markers(run_dir: str, top_n: int = 6) -> Dict[str, List[str]]:
    """Top marker genes per cluster, from a run's marker detection.

    This is what makes a cluster decision reviewable rather than a guess: the
    reviewer sees GJA1, AQP4, SOX9 and calls it, instead of naming a number.
    """
    import json

    metrics = _tool_metrics(run_dir, "marker_detection")
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
              region_plan: Optional[Dict[str, Any]] = None,
              markers: Optional[Dict[str, Sequence[str]]] = None,
              tumour: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
    # Named `readiness`, not `markers`: the parameter of that name holds marker
    # *genes*, and shadowing it here fed a dict of counts to `marker_overlap`.
    readiness = label_plan.get("markers") or {}
    if readiness and not readiness.get("meets_two_class_minimum"):
        blockers.append(
            "Fewer than two groups have %d cells, which is the floor for marker statistics."
            % readiness.get("min_cells_for_markers", MIN_CELLS_FOR_MARKERS))
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

    # Separability is not a blocker: the gate opens on coverage, and it should.
    # It changes what the decisions *cost* to make well, which is the thing a
    # decision count on its own hides.
    separability = marker_overlap(markers) if markers else None

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
        "separability": separability,
        "cluster_markers": dict(markers) if markers else {},
        "tumour": tumour or {"neoplastic": False, "evidence": ""},
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
    if labels.get("no_cluster_solution"):
        # The UI says this and the CLI printed "1 decision -> 0 pairs", which is
        # arithmetic about a bucket rather than a plan. Same answer in both.
        lines.append("         Nothing to review cluster by cluster: this bundle ships no cluster")
        lines.append("         solution. Run the descriptive lane and the sizing appears.")
        lines.append("")
        if summary["blockers"]:
            lines.append("STILL BLOCKED")
            for blocker in summary["blockers"]:
                lines.append("  x %s" % blocker)
        return "\n".join(lines)
    lines.append("         %d decision(s) reach %.1f%% coverage (gate needs %.0f%%)"
                 % (labels["decisions"], 100 * labels["achieved_coverage"],
                    100 * labels["required_coverage"]))
    lines.append("         each decision names ~%s cells at once; smallest is %s"
                 % (format(labels["cells_per_decision"], ","),
                    format(labels["smallest_chosen"], ",")))
    # What the minimum buys, which is not the same as whether it passes. Two
    # named classes clear the gate's two-class condition and leave exactly one
    # cell-type pair to test -- a lymph node reaches 70% on T cells and B cells
    # alone, so the cheapest review there is also the thinnest result.
    pairs = pair_count(labels["decisions"])
    lines.append("         naming only these gives %d class(es) -> %d cell-type pair(s) to test"
                 % (labels["decisions"], pairs))
    if pairs <= 1:
        lines.append("           One pair is the whole neighbourhood analysis. Naming a few more")
        lines.append("           clusters costs a decision each and multiplies what can be asked.")
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

    separability = summary.get("separability")
    if separability and separability["pairs"]:
        lines.append("")
        lines.append("MARKERS DO NOT SEPARATE THESE")
        for pair in separability["pairs"][:6]:
            lines.append("  clusters %s and %s share %s (overlap %.2f)"
                         % (pair["clusters"][0], pair["clusters"][1],
                            ", ".join(pair["shared"][:5]), pair["overlap"]))
        lines.append("  Naming these apart is not a marker call. It needs CNV, a reference that")
        lines.append("  carries the class in question, or morphology -- and `cnv_inference` is a")
        lines.append("  scaffold in this build, so it is not one of the options.")

    tumour = summary.get("tumour") or {}
    if tumour.get("neoplastic"):
        lines.append("")
        biggest = labels["groups"][0]["group"] if labels.get("groups") else ""
        lines.extend(malignant_caveat(tumour["evidence"],
                                      summary.get("cluster_markers"), biggest))
    elif tumour.get("known") is False:
        lines.append("")
        lines.append("TISSUE UNKNOWN")
        lines.append("  This bundle carries no `experiment.xenium`, so nothing here knows whether the")
        lines.append("  section is neoplastic. If it is, every lineage call below is provisional for")
        lines.append("  the reason a tumour section always is, and this plan has not said so.")

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
    # What a reference proposes, kept in its own column and never in
    # `expert_label`. A transferred label is a draft the gate refuses; writing
    # it into the answer column would turn "confirm this" into "this is done",
    # which is the one substitution this whole project exists to prevent.
    "reference_proposes",
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
                            loader_guesses: Optional[Dict[str, str]] = None,
                            candidates: Optional[str] = None) -> Dict[str, Any]:
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

    proposals: Dict[str, Dict[str, Any]] = {}
    if candidates and Path(candidates).exists():
        proposals = candidates_by_cluster(read_run_cell_clusters(run_dir),
                                          read_candidate_labels(candidates))

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
                "reference_proposes": format_candidate(proposals.get(cluster)),
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
        "with_proposals": sum(1 for cluster, _ in rows if proposals.get(cluster)),
        "mixed_proposals": sorted(name for name, entry in proposals.items()
                                  if not entry.get("consensus")),
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


# -------------------------------------------------------- marker separability

# Jaccard overlap of two clusters' top markers. Calibrated below against real
# sections rather than picked: on the healthy brain section every pair sits
# under this, and a pair above it is two groups a reviewer cannot tell apart
# from the evidence in front of them.
MARKER_OVERLAP_THRESHOLD = 0.34


def marker_overlap(markers: Dict[str, Sequence[str]],
                   threshold: float = MARKER_OVERLAP_THRESHOLD) -> Dict[str, Any]:
    """Cluster pairs whose top markers are largely the same genes.

    A cluster decision is only as good as the markers' ability to separate that
    cluster from its neighbours. Naming one `oligodendrocyte` off MOG and
    CLDN11 is safe because nothing else in the section carries them; naming one
    `malignant` off PTPRZ1, BCAN and OLIG2 is not, because OPCs carry those too
    -- and in a tumour section both are present.

    This does not say which label is right. It says where the marker evidence
    stops being sufficient on its own, which is where a reviewer needs CNV, a
    reference that carries the malignant class, or morphology.
    """
    names = [str(name) for name in markers]
    sets = {name: {str(gene).upper() for gene in (markers.get(name) or [])} for name in names}
    pairs: List[Dict[str, Any]] = []
    worst: Dict[str, float] = {name: 0.0 for name in names}

    for index, first in enumerate(names):
        for second in names[index + 1:]:
            left, right = sets[first], sets[second]
            if not left or not right:
                continue
            union = left | right
            if not union:
                continue
            score = len(left & right) / len(union)
            worst[first] = max(worst[first], score)
            worst[second] = max(worst[second], score)
            if score >= threshold:
                pairs.append({
                    "clusters": [first, second],
                    "overlap": round(score, 3),
                    "shared": sorted(left & right),
                })

    pairs.sort(key=lambda item: -item["overlap"])
    return {
        "threshold": threshold,
        "pairs": pairs,
        "max_overlap_by_cluster": {name: round(value, 3) for name, value in worst.items()},
        "separable": not pairs,
    }


# --------------------------------------------------------------- tumour context

# Words a section uses about itself when it is neoplastic. This is a heuristic
# on the bundle's own `run_name`/`region_name`, not a biological determination:
# it decides whether to print a caveat, never whether a cell is malignant.
NEOPLASM_WORDS = (
    "glioblastoma", "glioma", "carcinoma", "tumor", "tumour", "cancer",
    "sarcoma", "lymphoma", "melanoma", "neoplasm", "neoplastic", "metasta",
    "adenoma", "blastoma", "myeloma", "leukemia", "leukaemia",
)


def tumour_context(dataset_path: str) -> Dict[str, Any]:
    """Does this section describe itself as neoplastic?

    Read so the plan can say the thing that matters most about reviewing a
    tumour section from markers, and which the cluster-overlap check cannot
    see: a malignant cell mimicking a lineage carries that lineage's markers,
    so every normal-lineage call in such a section is provisional.
    """
    import json

    path = Path(dataset_path)
    candidate = path / "experiment.xenium" if path.is_dir() else path
    try:
        with open(candidate, encoding="utf-8") as handle:
            metadata = json.load(handle) or {}
    except (OSError, ValueError):
        # No metadata is not "healthy": it is "cannot tell". A GEO deposit ships
        # no experiment file, and the whole GSE311609 series is tumour, so a
        # flat False here would quietly drop the caveat on exactly that data.
        return {"neoplastic": False, "evidence": "", "known": False}

    for key in ("run_name", "region_name", "panel_tissue_type"):
        value = str(metadata.get(key) or "")
        lowered = value.lower()
        for word in NEOPLASM_WORDS:
            if word in lowered:
                return {"neoplastic": True, "evidence": "%s = %s" % (key, value),
                        "word": word, "known": True}
    return {"neoplastic": False, "evidence": "", "known": True}


def malignant_caveat(evidence: str,
                     markers: Optional[Dict[str, Sequence[str]]] = None,
                     largest: str = "") -> List[str]:
    """What the overlap check is blind to on a neoplastic section.

    The example is drawn from the section's own clusters, not written in. A
    fixed one asserted PTPRZ1/BCAN/OLIG2 -- a brain example -- on a breast
    section, where the ambiguity is real and the genes are EPCAM, CD24 and the
    keratins.
    """
    lines = [
        "THE CALL THIS CANNOT SIZE",
        "  This section names itself neoplastic (%s)." % evidence,
        "",
        "  The overlap check above compares clusters with each other. It cannot see the",
        "  ambiguity that matters most here, because that one is not a within-section",
        "  comparison: a malignant cell mimicking a lineage carries that lineage's",
        "  markers, so a cluster reads as that lineage and as tumour-of-that-lineage",
        "  equally, and nothing in the marker table separates the two.",
    ]
    genes = list((markers or {}).get(largest) or [])
    if largest and genes:
        lines.extend([
            "",
            "  On this section that applies to every cluster named from lineage markers,",
            "  starting with the largest: cluster %s (%s)." % (largest, ", ".join(genes[:5])),
        ])
    lines.extend([
        "",
        "  So every normal-lineage call in this section is provisional in a way the",
        "  same call on a healthy section is not. Resolving it needs CNV inference",
        "  (`cnv_inference` is a scaffold in this build), a reference that carries the",
        "  malignant class, or a pathologist on the morphology. The decision count",
        "  above does not include that work.",
    ])
    return lines



# ------------------------------------------------- candidates per cluster

# Below this share of a cluster, the transferred labels do not agree well enough
# for "the reference proposes X" to be a fair summary. Calibrated in
# `docs/cell_label_resources.md`: a reference whose sampling swings the
# malignant count 13.5x is not something to report a bare majority from.
CANDIDATE_CONSENSUS_FLOOR = 0.5


def read_candidate_labels(path: str) -> Dict[str, Dict[str, Any]]:
    """cell_id -> {label, confidence} from a candidate label file.

    These are transferred labels. The gate refuses them and should: the point
    of reading them here is to pre-fill a worksheet so a reviewer confirms or
    corrects nine rows instead of naming nine from scratch.
    """
    import csv

    found: Dict[str, Dict[str, Any]] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            cell_id = str(row.get("cell_id") or "").strip()
            label = str(row.get("candidate_label") or "").strip()
            if not cell_id or not label:
                continue
            try:
                confidence = float(row.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            found[cell_id] = {"label": label, "confidence": confidence}
    return found


def candidates_by_cluster(assignments: Sequence[Tuple[str, str]],
                          candidates: Dict[str, Dict[str, Any]],
                          floor: float = CANDIDATE_CONSENSUS_FLOOR) -> Dict[str, Dict[str, Any]]:
    """What the reference proposes for each cluster, and how much it agrees.

    A majority label alone would read as a recommendation. The share behind it
    and the runner-up are reported with it, because a cluster split 45/40
    between two classes is the one a reviewer most needs to look at and the one
    a bare majority hides.
    """
    per_cluster: Dict[str, Counter] = {}
    confidence: Dict[str, List[float]] = {}
    for cell_id, cluster in assignments:
        entry = candidates.get(cell_id)
        if not entry:
            continue
        per_cluster.setdefault(cluster, Counter())[entry["label"]] += 1
        confidence.setdefault(cluster, []).append(entry["confidence"])

    summary: Dict[str, Dict[str, Any]] = {}
    for cluster, counts in per_cluster.items():
        total = sum(counts.values()) or 1
        ranked = counts.most_common()
        top_label, top_count = ranked[0]
        share = top_count / total
        scores = confidence.get(cluster) or [0.0]
        summary[cluster] = {
            "label": top_label,
            "share": round(share, 4),
            "cells_with_candidate": total,
            "mean_confidence": round(sum(scores) / len(scores), 4),
            "runner_up": (ranked[1][0] if len(ranked) > 1 else ""),
            "runner_up_share": round(ranked[1][1] / total, 4) if len(ranked) > 1 else 0.0,
            "classes_seen": len(ranked),
            # Strictly greater, not >=: an exact 50/50 split is the coin toss
            # this floor exists to catch, and it passed.
            "consensus": share > floor,
        }
    return summary


def format_candidate(entry: Optional[Dict[str, Any]]) -> str:
    """The proposal as one worksheet cell, with its own uncertainty attached."""
    if not entry:
        return ""
    if not entry.get("consensus"):
        return "mixed: %s %.0f%% / %s %.0f%% -- look at this one" % (
            entry["label"], 100 * entry["share"],
            entry["runner_up"] or "other", 100 * entry["runner_up_share"])
    text = "%s (%.0f%% of cells, mean conf %.2f)" % (
        entry["label"], 100 * entry["share"], entry["mean_confidence"])
    if entry.get("runner_up"):
        text += "; then %s %.0f%%" % (entry["runner_up"], 100 * entry["runner_up_share"])
    return text
