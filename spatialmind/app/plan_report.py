"""A report for a Studio plan run.

The validated pilot writes a long report because it makes claims and has to
qualify every one. A plan run is narrower -- the user picked tools and got
output -- but it still leaves the building with numbers in it, so it needs the
same three things: what ran, what the gate said, and who supplied the inputs.

This is deliberately not the pilot's report generator. That one is built around
a claim ledger and a reliability score, and a plan run has neither; rendering an
empty ledger would suggest claims were assessed and passed, which is worse than
saying no claim was made.

What it does share with the pilot is the rule that matters: **the lane is stated
before the numbers.** A descriptive run says on its first page that its groups
are data-derived and name no cell type, because that is the sentence a reader
skips if it comes last.
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

LANE_DESCRIPTIVE = "descriptive"
LANE_VALIDATED = "validated"


def lane_for_payload(payload: Dict[str, Any]) -> str:
    label_status = (payload.get("label_report") or {}).get("status") or ""
    region_status = (payload.get("region_report") or {}).get("status") or ""
    if label_status == "expert_labels_applied" and region_status == "user_regions_applied":
        return LANE_VALIDATED
    if label_status == "expert_labels_applied":
        return LANE_VALIDATED
    return LANE_DESCRIPTIVE


def build_markdown(payload: Dict[str, Any], gate: Optional[Dict[str, Any]] = None) -> str:
    dataset = payload.get("dataset") or {}
    name = dataset.get("display_name") or dataset.get("name") or "dataset"
    lane = lane_for_payload(payload)
    lines: List[str] = []

    lines.append("# %s" % (payload.get("title") or ("Analysis of %s" % name)))
    lines.append("")
    lines.append("%s \u00b7 run `%s` \u00b7 %s"
                 % (name, payload.get("run_id") or "", time.strftime("%Y-%m-%d %H:%M")))
    lines.append("")

    # The lane, first, in its own words.
    lines.append("## What this run is")
    lines.append("")
    if lane == LANE_VALIDATED:
        lines.append(
            "This is a **validated-lane** run: reviewed cell labels were applied, so groups below "
            "are named cell types and not clusters.")
    else:
        lines.append(
            "This is a **descriptive** run. No reviewed label table was applied, so every group "
            "below is data-derived -- a Leiden cluster, not a cell type. Nothing here names a cell "
            "type, and no biological claim is made or implied.")
    lines.append("")

    records = payload.get("records_loaded") or 0
    scope = payload.get("scope") or ""
    lines.append("- Cells analysed: `%s`%s" % (format(records, ","),
                                               "" if scope == "full_section" else
                                               " (a deterministic sample, not the whole section)"))
    lines.append("- Tools run: %s" % ", ".join("`%s`" % t for t in (payload.get("tools") or [])))
    lines.append("- Wall time: `%.1f s`" % float(payload.get("wall_seconds") or 0))
    lines.append("")

    lines.extend(_gate_section(payload, gate))
    lines.extend(_figures_section(payload))
    lines.extend(_results_section(payload))
    lines.extend(_tables_section(payload))
    lines.extend(_limitations_section(payload, lane))
    return "\n".join(lines) + "\n"


def _figures_section(payload: Dict[str, Any]) -> List[str]:
    figures = payload.get("figures") or []
    if not figures:
        return []
    lines = ["## Figures", ""]
    for figure in figures:
        lines.append("![%s](%s)" % (figure.get("caption") or figure.get("name"), figure.get("name")))
        lines.append("")
        if figure.get("caption"):
            lines.append("_%s_" % figure["caption"])
            lines.append("")
    return lines


def _label_audit_section(payload: Dict[str, Any]) -> List[str]:
    """Where the reviewed labels and the cells' own markers disagree.

    Placed in the gate section deliberately: a reader deciding how much to trust
    a validated run reads the gate first, and a gate that says `validated_ready`
    over labels the measurements contradict is the thing they most need to see.
    """
    audit = {}
    for result in payload.get("results") or []:
        candidate = (result.get("metrics") or {}).get("label_marker_audit")
        if candidate:
            audit = candidate
            break
    if audit.get("status") != "computed" or not audit.get("labels_disagreeing"):
        return []

    flagged = sorted((item for item in audit["labels"] if item.get("disagrees")),
                     key=lambda item: -item["disagreement_share"])
    lines = ["", "### Markers disagree with %d of %d reviewed labels"
             % (audit["labels_disagreeing"], audit["labels_checked"]), ""]
    lines.append(
        "The labels below are the reviewer's. The markers are what the instrument measured. "
        "Where a label's own cells carry marker evidence for a different lineage, the label is "
        "the part to re-check -- a confident wrong label is harder to notice than a blank one. "
        "This is reported, not enforced: nothing here was blocked or rewritten.")
    lines.append("")
    lines.append("| Reviewed label | Cells with marker evidence | Disagree | Label says | Markers say |")
    lines.append("| --- | ---: | ---: | --- | --- |")
    for item in flagged:
        lines.append("| `%s` | %s | %.0f%% | %s | %s |" % (
            item["label"], format(item["cells_with_marker_evidence"], ","),
            100 * item["disagreement_share"], item["claimed_lineage"], item["markers_suggest"]))
    return lines


def _gate_section(payload: Dict[str, Any], gate: Optional[Dict[str, Any]]) -> List[str]:
    label = payload.get("label_report") or {}
    region = payload.get("region_report") or {}
    lines = ["## Inputs and the gate", ""]
    lines.append("- Label status: `%s`" % (label.get("status") or "not applied"))
    lines.append("- Region status: `%s`" % (region.get("status") or "not applied"))

    # Who supplied the reviewed tables. The gate counts a reviewed table and
    # cannot read who wrote it, so the source is reported rather than enforced.
    for report, noun in ((label, "Labels"), (region, "Regions")):
        reviewers = report.get("reviewers") or {}
        if reviewers:
            lines.append("- %s supplied by: %s" % (
                noun, "; ".join("%s (%s cells)" % (who, format(int(count), ","))
                                for who, count in sorted(reviewers.items(),
                                                         key=lambda kv: -kv[1]))))
    if _composition_derived(region):
        lines.append("")
        lines.append(
            "These regions were named from the reviewed cell composition rather than from "
            "morphology, so any composition summary over them is partly circular. Neighbourhood "
            "results *within* a region are not affected.")

    lines.extend(_label_audit_section(payload))

    if gate:
        lines.append("")
        lines.append("- Gate status: `%s`" % gate.get("status", "unknown"))
        for reason in (gate.get("blocking_reasons") or []):
            lines.append("  - %s" % reason)
    lines.append("")
    return lines


def _composition_derived(region_report: Dict[str, Any]) -> bool:
    reviewers = " ".join(region_report.get("reviewers") or {}).lower()
    return "composition" in reviewers or "derived" in reviewers


def _results_section(payload: Dict[str, Any]) -> List[str]:
    lines = ["## Results", ""]
    for result in (payload.get("results") or []):
        lines.append("### `%s`" % result.get("tool"))
        lines.append("")
        lines.append(str(result.get("summary") or "").strip() or "_No summary._")
        lines.append("")
        params = result.get("params") or {}
        if params:
            lines.append("Parameters: %s" % ", ".join(
                "`%s=%s`" % (key, value) for key, value in sorted(params.items())))
            lines.append("")
        lines.extend(_metric_highlights(result.get("metrics") or {}))
        caveats = list(result.get("caveats") or [])
        if result.get("label_caveat"):
            caveats.append(str(result["label_caveat"]))
        for caveat in caveats:
            lines.append("- %s" % caveat)
        if caveats:
            lines.append("")
        lines.append("Ran in %.1f s." % float(result.get("seconds") or 0))
        lines.append("")
    return lines


def _metric_highlights(metrics: Dict[str, Any], limit: int = 12) -> List[str]:
    """A small table of whatever the tool reported, without pretending to rank it.

    Long lists are cut and the cut is stated: a reader who sees ten rows and no
    note assumes ten is all there was.
    """
    rows: List[Any] = []
    for key, value in metrics.items():
        if isinstance(value, (int, float, str, bool)) or value is None:
            rows.append((key, value))
    if not rows:
        return []
    lines = ["| Metric | Value |", "| --- | --- |"]
    for key, value in rows[:limit]:
        lines.append("| `%s` | %s |" % (key, value))
    if len(rows) > limit:
        lines.append("| _\u2026%d more_ | _see the result tables_ |" % (len(rows) - limit))
    lines.append("")
    return lines


def _tables_section(payload: Dict[str, Any]) -> List[str]:
    manifest = payload.get("result_tables") or {}
    tables = manifest.get("tables") or []
    if not tables:
        return []
    lines = ["## Result tables", "",
             "Long-format tables, one row per gene, cell, group or pair. Each repeats the run id, "
             "dataset and gate status in its own header, because a table is usually read apart "
             "from the report that qualifies it.", "",
             "| Table | Rows |", "| --- | ---: |"]
    for table in tables:
        lines.append("| `%s` | %s |" % (table.get("table"), format(int(table.get("rows") or 0), ",")))
    lines.append("")
    return lines


def _limitations_section(payload: Dict[str, Any], lane: str) -> List[str]:
    lines = ["## Limitations", ""]
    items: List[str] = []
    features = payload.get("features_loaded") or 0
    if features:
        items.append(
            "Xenium uses a targeted panel (%d measured genes); a gene that is absent was not "
            "measured, which is not the same as not expressed." % features)
    if lane == LANE_DESCRIPTIVE:
        items.append(
            "Groups are unsupervised clusters. They are not cell types, and a cluster that looks "
            "like a known population has not been shown to be one.")
    items.append(
        "Spatial adjacency is adjacency. It does not establish interaction, signalling, causation "
        "or mechanism.")
    items.append(
        "This is a single section. Condition-level differences need independent donors, which one "
        "section cannot supply no matter how many cells it holds.")
    if (payload.get("scope") or "") != "full_section":
        items.append(
            "This run used a deterministic cell sample rather than the whole section; final "
            "biological claims need a full-section run.")
    for item in items:
        lines.append("- %s" % item)
    lines.append("")
    return lines


def write(payload: Dict[str, Any], output_dir: Path,
          gate: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Write `report.md` and `report.html` for a plan run."""
    markdown = build_markdown(payload, gate=gate)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "report.md"
    md_path.write_text(markdown, encoding="utf-8")
    html_path = output_dir / "report.html"
    html_path.write_text(_html(markdown, payload), encoding="utf-8")
    return {"markdown": str(md_path), "html": str(html_path)}


def _html(markdown: str, payload: Dict[str, Any]) -> str:
    """A self-contained HTML rendering, so the file is openable on its own."""
    from html import escape

    body: List[str] = []
    in_list = False
    in_table = False
    for raw in markdown.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            if in_list:
                body.append("</ul>")
                in_list = False
            if in_table:
                body.append("</table>")
                in_table = False
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            body.append("<h%d>%s</h%d>" % (min(level, 4), _inline(stripped[level:].strip()),
                                           min(level, 4)))
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if not in_table:
                body.append("<table>")
                in_table = True
            tag = "th" if len(body) and body[-1] == "<table>" else "td"
            body.append("<tr>" + "".join("<%s>%s</%s>" % (tag, _inline(c), tag) for c in cells) + "</tr>")
            continue
        if stripped.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append("<li>%s</li>" % _inline(stripped[2:]))
            continue
        body.append("<p>%s</p>" % _inline(stripped))
    if in_list:
        body.append("</ul>")
    if in_table:
        body.append("</table>")

    dataset = payload.get("dataset") or {}
    title = escape(str(payload.get("title") or ("Analysis of %s" %
                   (dataset.get("display_name") or "dataset"))))
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>%s</title><style>"
        "body{font:15px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "max-width:52rem;margin:2.4rem auto;padding:0 1.2rem;color:#16211f;background:#fff}"
        "h1{font-size:1.65rem} h2{font-size:1.2rem;margin-top:2rem;border-bottom:1px solid #dfe5e4;"
        "padding-bottom:.3rem} h3{font-size:1rem;margin-top:1.4rem;color:#0d6068}"
        "table{border-collapse:collapse;margin:.7rem 0;font-size:.9rem;width:100%%}"
        "th,td{border:1px solid #dfe5e4;padding:.28rem .55rem;text-align:left}"
        "th{background:#f2f6f6} code{background:#f2f6f6;padding:.05rem .3rem;border-radius:3px;"
        "font-family:ui-monospace,Menlo,monospace;font-size:.88em}"
        "li{margin:.2rem 0}"
        "</style></head><body>%s</body></html>" % (title, "".join(body))
    )


def _inline(text: str) -> str:
    from html import escape
    import re

    out = escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    return out


# --------------------------------------------------------------------- figures

# Above this many cells a scatter plot is a solid block of colour and slow to
# draw; the sample is deterministic so the same run always renders the same map.
FIGURE_MAX_POINTS = 60000


def write_figures(dataset: Any, payload: Dict[str, Any], output_dir: Path) -> List[Dict[str, str]]:
    """A spatial map of whatever grouping this run actually has.

    One figure, not a gallery. A plan run's grouping is either reviewed cell
    types or Leiden clusters, and which one it is decides the caption: a map of
    clusters that is captioned as cell types is the single most misleading
    figure this app could produce.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return []

    records = list(getattr(dataset, "records", []) or [])
    if not records:
        return []

    lane = lane_for_payload(payload)
    if lane == LANE_VALIDATED:
        groups = [str(getattr(r, "cell_type", "") or "unassigned") for r in records]
        title = "Reviewed cell types"
        caption = "Cells coloured by the reviewed label table."
    else:
        groups = [str((getattr(r, "metadata", None) or {}).get("cluster")
                      or getattr(r, "cell_type", "") or "unassigned") for r in records]
        title = "Data-derived clusters"
        caption = ("Cells coloured by unsupervised cluster. These are not cell types and are "
                   "not named as any.")

    step = max(1, len(records) // FIGURE_MAX_POINTS)
    xs = [float(r.x) for r in records[::step]]
    ys = [float(r.y) for r in records[::step]]
    keys = groups[::step]
    order = sorted(set(keys))
    if len(order) > 40:
        # Beyond this a legend is unreadable and the colours stop being distinct.
        return []
    palette = plt.get_cmap("tab20")
    colour = {name: palette(index % 20) for index, name in enumerate(order)}

    figure, axes = plt.subplots(figsize=(8.0, 7.0), dpi=130)
    axes.scatter(xs, ys, s=2.0, c=[colour[k] for k in keys], linewidths=0)
    axes.set_aspect("equal")
    axes.invert_yaxis()
    axes.set_xlabel("x (um)")
    axes.set_ylabel("y (um)")
    axes.set_title("%s  (n=%s%s)" % (title, format(len(records), ","),
                                     ", shown 1 in %d" % step if step > 1 else ""))
    handles = [plt.Line2D([], [], marker="o", linestyle="", markersize=5,
                          color=colour[name], label=name) for name in order]
    axes.legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5),
                fontsize=7, frameon=False)
    figure.text(0.02, 0.01, caption, fontsize=7, color="#555555")

    path = Path(output_dir) / "spatial_map.png"
    figure.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return [{"name": path.name, "path": str(path), "caption": caption}]
