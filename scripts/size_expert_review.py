"""How many decisions open the gate on a section, and what each one asserts.

    python scripts/size_expert_review.py --all
    python scripts/size_expert_review.py --data "data/.../Healthy_outs" \
        --regions outputs/brain_healthy_review/cell_regions_candidate.csv

`scripts/plan_expert_review.py` sizes the same review in cells -- 70% of what
the run loads. That is correct and it is the wrong unit: the Review Studio's
gesture is a cluster click, so the cost is decisions, and there are far fewer of
those than the cell count suggests. This reports decisions, what each one
commits to, and what the shortcut costs in claim strength.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatialmind.app.catalog import IndexCache, discover_datasets
from spatialmind.review.sizing import (
    WORKSHEET_NAME,
    format_plan,
    read_candidate_regions,
    read_run_clusters,
    size_label_review,
    size_region_review,
    summarise,
    write_cluster_worksheet,
)


def _find_candidates(dataset_path: str, explicit: str) -> str:
    """The region candidates belonging to *this* section, or nothing.

    Matched through each run's own `pilot_validation.json`, not by taking the
    first file found: globbing `outputs/*/cell_regions_candidate.csv` and
    returning the first hit would size one section's region review against
    another section's domains, which is worse than reporting none.
    """
    if explicit:
        return explicit
    try:
        wanted = Path(dataset_path).resolve()
    except OSError:
        return ""
    root = Path("outputs")
    if not root.exists():
        return ""
    newest = ""
    newest_time = -1.0
    for candidate in sorted(root.glob("*/cell_regions_candidate.csv")):
        validation = candidate.parent / "pilot_validation.json"
        if not validation.exists():
            continue
        try:
            with open(validation, encoding="utf-8") as handle:
                payload = json.load(handle)
            ran_on = Path(str(payload.get("dataset_path") or "")).resolve()
        except (OSError, ValueError):
            continue
        if ran_on != wanted:
            continue
        stamp = candidate.stat().st_mtime
        if stamp > newest_time:
            newest, newest_time = str(candidate), stamp
    return newest


def size_one(path: str, name: str, cache: IndexCache, regions_path: str,
             coverage: float, run_dir: str = "") -> dict:
    resolved_regions = _find_candidates(path, regions_path)
    run = run_dir or (str(Path(resolved_regions).parent) if resolved_regions else "")

    # A bundle ships 10x's graphclust and a run makes its own Leiden solution,
    # and they are not the same size. Size against the run's when there is one:
    # it is coarser (9 against 16 on the healthy brain section, so 4 decisions
    # against 7) and it is the one with marker evidence attached, which is what
    # makes a cluster call reviewable rather than a guess.
    run_clusters = read_run_clusters(run) if run else {}
    if run_clusters:
        label_plan = size_label_review(run_clusters, coverage=coverage)
        label_plan["cluster_source"] = "%s (this run's clustering)" % run
    else:
        label_plan = size_label_review(cache.get(path).cluster_sizes(), coverage=coverage)
        label_plan["cluster_source"] = "the bundle's own 10x clusters"

    region_plan = None
    if resolved_regions and Path(resolved_regions).exists():
        region_plan = size_region_review(read_candidate_regions(resolved_regions),
                                         coverage=coverage)
        region_plan["source"] = resolved_regions
    summary = summarise(name, label_plan, region_plan)
    summary["run_dir"] = run
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Size the review that opens the gate.")
    parser.add_argument("--data", default="", help="One Xenium output folder.")
    parser.add_argument("--all", action="store_true",
                        help="Every reviewable dataset under --data-root, cheapest first.")
    parser.add_argument("--data-root", default="data", help="Where to look with --all.")
    parser.add_argument("--regions", default="",
                        help="A cell_regions_candidate.csv to size the region side against.")
    parser.add_argument("--coverage", type=float, default=0.7, help="Gate coverage requirement.")
    parser.add_argument("--run", default="",
                        help="A descriptive run directory, to size against its own clustering.")
    parser.add_argument("--worksheet", action="store_true",
                        help="Also write the per-cluster worksheet into the run directory.")
    parser.add_argument("--json", action="store_true", help="Emit the full plan as JSON.")
    args = parser.parse_args()

    cache = IndexCache(max_entries=1)
    plans = []
    if args.all:
        for entry in discover_datasets(args.data_root):
            if not entry.reviewable:
                continue
            try:
                plans.append(size_one(entry.path, entry.display_name, cache,
                                      args.regions, args.coverage))
            except Exception as exc:
                print("%-44s could not be sized: %s" % (entry.name[:44], exc), file=sys.stderr)
    elif args.data:
        plans.append(size_one(args.data, Path(args.data).name, cache, args.regions,
                              args.coverage, run_dir=args.run))
    else:
        raise SystemExit("Pass --data <folder> or --all.")

    if args.json:
        print(json.dumps(plans, indent=2, sort_keys=True))
        return

    # Cheapest first, but a plan whose region side has never been proposed has a
    # total that is a lower bound, so it sorts after the ones that are fully
    # counted rather than ahead of them on an uncounted number.
    plans.sort(key=lambda p: (not p.get("total_is_complete"),
                              p["total_decisions"], p["labels"]["total_cells"]))
    for plan in plans:
        print(format_plan(plan))
        if plan["labels"].get("cluster_source"):
            print("         clusters from: %s" % plan["labels"]["cluster_source"])
        print()
        if args.worksheet and plan.get("run_dir"):
            written = write_cluster_worksheet(
                plan["run_dir"], str(Path(plan["run_dir"]) / WORKSHEET_NAME))
            if written.get("status") == "written":
                print("WORKSHEET  %s" % written["path"])
                print("           %d cluster(s), %d with marker evidence; name the top %d to "
                      "reach the gate." % (written["clusters"], written["with_markers"],
                                           written["decisions_for_gate"]))
            else:
                print("WORKSHEET  not written: %s" % written.get("reason"))
            print()
        print("-" * 72)
        print()

    if len(plans) > 1:
        counted = [p for p in plans if p.get("total_is_complete")]
        uncounted = [p for p in plans if not p.get("total_is_complete")]
        print("CHEAPEST TO OPEN")
        if counted:
            best = counted[0]
            print("  %s, at %d decision(s)." % (best["dataset"], best["total_decisions"]))
        else:
            print("  Nothing is fully counted yet; every section is missing a side.")
        if uncounted:
            print("  Not comparable until their regions are proposed: %s."
                  % ", ".join(p["dataset"] for p in uncounted))
            print("  Their totals are lower bounds and would otherwise rank ahead on an")
            print("  uncounted number.")
        print("  Fewest decisions is also not the same as best supported: a section whose")
        print("  lineages a reference atlas can propose is easier to review than one where")
        print("  every call is made from markers alone, however few clusters it has.")


if __name__ == "__main__":
    main()
