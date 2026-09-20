"""A packet for naming tissue regions from morphology, not from cell counts.

This workspace's one validated section has expert labels and machine regions.
The regions were made by accepting the descriptive lane's spatial domains and
naming each from its own reviewed cell composition, which makes a region summary
over them partly circular: a domain called `tumor_rich` is tumour-rich by
construction, and that it is, is not a finding.

Only a pathologist removes that. This module makes it a short session rather
than a project: each domain is rendered on the section's own morphology image,
with a scale bar and a locator, and the reviewer writes a name.

**The packet is blinded by default, and that is the whole point.** Showing
"this domain is 80% Invasive_Tumor" and then asking what to call it reproduces
exactly the circularity the exercise exists to remove -- the reviewer would be
reading back the naming rule rather than the tissue. `--unblind` exists for a
second pass, after names are written, and says on the page that it is one.

Two honest limits, stated in the packet itself:

* Xenium ships DAPI morphology, not H&E. Nuclear architecture shows ducts,
  stromal density and cellularity; it does not show cytoplasm, and a call that
  needs H&E or IHC is a call this image cannot support. The sheet has an
  `uncertain` column for exactly that.
* The domain boundaries are the algorithm's, not the reviewer's. They can be
  accepted, renamed or merged; they cannot be redrawn here. A reviewer who wants
  different boundaries should say so in `notes` and draw them in Review Studio.
"""

import csv
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..viz.morphology import load_morphology_plane

NAMING_SHEET = "region_naming_sheet.csv"
PACKET_PAGE = "region_review.html"
CROP_DIRNAME = "crops"

# Columns the reviewer fills in. `pathologist_label` is the only required one.
SHEET_FIELDS = [
    "domain_id", "n_cells", "area_um2", "centroid_x_um", "centroid_y_um",
    "pathologist_label", "confidence", "uncertain", "notes",
]

# Padding around a domain's bounding box, so the reviewer sees what it borders.
# A crop tight to the domain hides the thing that decides most calls: what is
# next to it.
CROP_PADDING_FRACTION = 0.35
MIN_CROP_UM = 400.0

# A domain below this is not enough tissue to name from morphology.
MIN_CELLS_TO_REVIEW = 50


def _read_region_table(path: Path) -> Dict[str, str]:
    """cell_id -> domain, from a candidate or an applied region table."""
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    keys = rows[0].keys()
    id_key = next((k for k in ("cell_id", "cell") if k in keys), None)
    value_key = next((k for k in ("candidate_region", "region", "domain") if k in keys), None)
    if not id_key or not value_key:
        raise ValueError("%s needs a cell id column and a region/domain column." % path)
    return {str(r[id_key]).strip(): str(r[value_key]).strip()
            for r in rows if str(r.get(value_key) or "").strip()}


def _read_coordinates(bundle: Path) -> Dict[str, Tuple[float, float]]:
    """cell_id -> (x, y) in microns, from the bundle's own cell table."""
    import gzip

    for name in ("cells.csv.gz", "cells.csv"):
        path = bundle / name
        if not path.exists():
            continue
        opener = gzip.open if name.endswith(".gz") else open
        with opener(path, "rt", newline="") as handle:
            reader = csv.DictReader(handle)
            return {
                str(row["cell_id"]).strip(): (float(row["x_centroid"]), float(row["y_centroid"]))
                for row in reader
            }
    raise FileNotFoundError("No cells.csv.gz in %s" % bundle)


def _read_labels(bundle: Path) -> Dict[str, str]:
    path = bundle / "expert_cell_labels.csv"
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        return {str(r["cell_id"]).strip(): str(r.get("expert_label") or "").strip()
                for r in csv.DictReader(handle)}


def summarise_domains(assignments: Dict[str, str],
                      coordinates: Dict[str, Tuple[float, float]],
                      labels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Geometry per domain, and composition only when it was asked for.

    Area is the bounding box, not a hull: it is reported so the reviewer knows
    roughly how much tissue a crop covers, and a figure that looks precise would
    invite being used as one.
    """
    grouped: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    composition: Dict[str, Counter] = defaultdict(Counter)
    for cell_id, domain in assignments.items():
        point = coordinates.get(cell_id)
        if point is None:
            continue
        grouped[domain].append(point)
        if labels:
            label = labels.get(cell_id)
            if label:
                composition[domain][label] += 1

    domains: List[Dict[str, Any]] = []
    for domain, points in sorted(grouped.items()):
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        entry = {
            "domain_id": domain,
            "n_cells": len(points),
            "bbox_um": [x0, y0, x1, y1],
            "area_um2": round((x1 - x0) * (y1 - y0), 1),
            "centroid_x_um": round(sum(xs) / len(xs), 1),
            "centroid_y_um": round(sum(ys) / len(ys), 1),
            "reviewable": len(points) >= MIN_CELLS_TO_REVIEW,
        }
        if labels:
            total = sum(composition[domain].values()) or 1
            entry["composition"] = [
                {"label": name, "cells": count, "fraction": round(count / total, 4)}
                for name, count in composition[domain].most_common(8)
            ]
        domains.append(entry)
    domains.sort(key=lambda d: -d["n_cells"])
    return domains


def _crop_box(bbox: Sequence[float], extent: Tuple[float, float]) -> Tuple[float, float, float, float]:
    """A padded, clamped crop in microns around one domain."""
    x0, y0, x1, y1 = bbox
    width = max(x1 - x0, MIN_CROP_UM)
    height = max(y1 - y0, MIN_CROP_UM)
    pad_x = width * CROP_PADDING_FRACTION
    pad_y = height * CROP_PADDING_FRACTION
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    half_w = width / 2.0 + pad_x
    half_h = height / 2.0 + pad_y
    return (
        max(cx - half_w, 0.0), max(cy - half_h, 0.0),
        min(cx + half_w, extent[0]), min(cy + half_h, extent[1]),
    )


def _render_crops(plane: Dict[str, Any], domains: List[Dict[str, Any]],
                  points_by_domain: Dict[str, List[Tuple[float, float]]],
                  output_dir: Path) -> Dict[str, Dict[str, str]]:
    """One tissue crop and one locator per domain."""
    from PIL import Image, ImageDraw

    image = plane["image"]
    extent = (float(plane["width_um"]), float(plane["height_um"]))
    px_per_um_x = image.width / extent[0]
    px_per_um_y = image.height / extent[1]

    crops_dir = output_dir / CROP_DIRNAME
    crops_dir.mkdir(parents=True, exist_ok=True)
    rendered: Dict[str, Dict[str, str]] = {}

    for domain in domains:
        name = domain["domain_id"]
        box_um = _crop_box(domain["bbox_um"], extent)
        box_px = (
            int(box_um[0] * px_per_um_x), int(box_um[1] * px_per_um_y),
            int(math.ceil(box_um[2] * px_per_um_x)), int(math.ceil(box_um[3] * px_per_um_y)),
        )
        crop = image.crop(box_px).convert("RGB")
        # Upscale a small crop so the reviewer is not squinting at 90 pixels.
        if crop.width < 520 and crop.width:
            scale = 520.0 / crop.width
            crop = crop.resize((int(crop.width * scale), max(int(crop.height * scale), 1)),
                               Image.BICUBIC)
        _draw_domain_cells(crop, points_by_domain.get(name, []), box_um)
        _draw_scale_bar(crop, box_um)
        crop_path = crops_dir / ("%s_tissue.png" % _slug(name))
        crop.save(crop_path)

        locator = image.copy().convert("RGB")
        draw = ImageDraw.Draw(locator)
        draw.rectangle(
            [box_um[0] * px_per_um_x, box_um[1] * px_per_um_y,
             box_um[2] * px_per_um_x, box_um[3] * px_per_um_y],
            outline=(255, 90, 60), width=max(2, locator.width // 300))
        locator.thumbnail((260, 260))
        locator_path = crops_dir / ("%s_locator.png" % _slug(name))
        locator.save(locator_path)

        rendered[name] = {
            "tissue": "%s/%s" % (CROP_DIRNAME, crop_path.name),
            "locator": "%s/%s" % (CROP_DIRNAME, locator_path.name),
            "crop_um": [round(v, 1) for v in box_um],
        }
    return rendered


def _draw_domain_cells(crop: Any, points: Sequence[Tuple[float, float]],
                       box_um: Tuple[float, float, float, float]) -> None:
    """Mark which cells belong to the domain, without hiding the tissue.

    A filled overlay would be easier to see and would also cover the nuclear
    architecture, which is the only thing in this image worth reading.
    """
    from PIL import Image, ImageDraw

    if not points:
        return
    width_um = max(box_um[2] - box_um[0], 1e-6)
    height_um = max(box_um[3] - box_um[1], 1e-6)
    layer = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    step = max(1, len(points) // 4000)
    radius = max(1, crop.width // 400)
    for x_um, y_um in points[::step]:
        x = (x_um - box_um[0]) / width_um * crop.width
        y = (y_um - box_um[1]) / height_um * crop.height
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(90, 220, 255, 110))
    crop.paste(Image.alpha_composite(crop.convert("RGBA"), layer).convert("RGB"), (0, 0))


def _draw_scale_bar(crop: Any, box_um: Tuple[float, float, float, float]) -> None:
    """A scale bar, because "how big is this" decides several of these calls."""
    from PIL import ImageDraw

    width_um = max(box_um[2] - box_um[0], 1e-6)
    for candidate in (1000.0, 500.0, 250.0, 100.0, 50.0):
        if candidate <= width_um * 0.4:
            bar_um = candidate
            break
    else:
        bar_um = width_um * 0.25
    bar_px = bar_um / width_um * crop.width
    margin = max(8, crop.width // 60)
    y = crop.height - margin
    draw = ImageDraw.Draw(crop)
    draw.rectangle([margin, y - 5, margin + bar_px, y], fill=(255, 255, 255))
    draw.text((margin, y - 20), "%d um" % int(bar_um), fill=(255, 255, 255))


def _slug(text: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_")[:60] or "domain"


def build_region_review_packet(
    dataset_path: str,
    region_table: str,
    output_dir: str,
    blinded: bool = True,
    max_dimension: int = 3000,
) -> Dict[str, Any]:
    """Render every domain on tissue and write a sheet to name them on.

    Returns a manifest. Raises only for inputs that cannot be read at all; a
    missing morphology image degrades to a sheet without crops rather than
    failing, because the sheet is still the thing that gets filled in.
    """
    bundle = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    assignments = _read_region_table(Path(region_table))
    if not assignments:
        raise ValueError("%s assigned no cells to any region." % region_table)
    coordinates = _read_coordinates(bundle)
    labels = _read_labels(bundle) if not blinded else {}
    domains = summarise_domains(assignments, coordinates, labels=labels or None)

    points_by_domain: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for cell_id, domain in assignments.items():
        point = coordinates.get(cell_id)
        if point is not None:
            points_by_domain[domain].append(point)

    plane = load_morphology_plane(str(bundle), max_dimension=max_dimension)
    crops: Dict[str, Dict[str, str]] = {}
    if plane.get("status") == "loaded":
        crops = _render_crops(plane, domains, points_by_domain, output)

    sheet_path = output / NAMING_SHEET
    with open(sheet_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        for domain in domains:
            writer.writerow({
                "domain_id": domain["domain_id"],
                "n_cells": domain["n_cells"],
                "area_um2": domain["area_um2"],
                "centroid_x_um": domain["centroid_x_um"],
                "centroid_y_um": domain["centroid_y_um"],
                "pathologist_label": "",
                "confidence": "",
                "uncertain": "",
                "notes": "",
            })

    page_path = output / PACKET_PAGE
    page_path.write_text(_render_page(bundle, domains, crops, plane, blinded), encoding="utf-8")

    manifest = {
        "status": "written",
        "dataset": str(bundle),
        "region_table": str(region_table),
        "blinded": blinded,
        "domains": len(domains),
        "reviewable_domains": sum(1 for d in domains if d["reviewable"]),
        "cells_assigned": len(assignments),
        "morphology": plane.get("status"),
        "morphology_source": plane.get("source", ""),
        "naming_sheet": str(sheet_path),
        "page": str(page_path),
    }
    (output / "packet_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _render_page(bundle: Path, domains: List[Dict[str, Any]],
                 crops: Dict[str, Dict[str, str]], plane: Dict[str, Any],
                 blinded: bool) -> str:
    from html import escape

    cards: List[str] = []
    for domain in domains:
        name = domain["domain_id"]
        rendered = crops.get(name, {})
        composition = ""
        if not blinded and domain.get("composition"):
            rows = "".join(
                "<tr><td>%s</td><td class='n'>%s</td><td class='n'>%.1f%%</td></tr>"
                % (escape(item["label"]), format(item["cells"], ","), 100 * item["fraction"])
                for item in domain["composition"])
            composition = (
                "<details open><summary>Cell composition &mdash; not the thing to name from</summary>"
                "<table class='comp'>%s</table></details>" % rows)
        small = "" if domain["reviewable"] else (
            "<p class='warn'>Only %d cells. Probably too little tissue to name from morphology; "
            "leaving it blank is a valid answer.</p>" % domain["n_cells"])
        cards.append(
            "<article class='card'>"
            "<header><h2>%s</h2><span class='meta'>%s cells &middot; %s &micro;m&sup2; &middot; "
            "centroid (%s, %s)</span></header>"
            "%s"
            "<div class='imgs'>%s%s</div>"
            "%s%s"
            "<label>Name this region<input data-domain='%s' placeholder='e.g. invasive carcinoma, "
            "DCIS, fibrous stroma, normal duct'></label>"
            "</article>"
            % (escape(name), format(domain["n_cells"], ","), format(int(domain["area_um2"]), ","),
               domain["centroid_x_um"], domain["centroid_y_um"],
               small,
               ("<figure><img src='%s' alt='tissue'><figcaption>Tissue, with the domain's cells "
                "marked</figcaption></figure>" % escape(rendered["tissue"])) if rendered else
               "<p class='warn'>No morphology image available for this bundle.</p>",
               ("<figure class='loc'><img src='%s' alt='locator'><figcaption>Where it sits</figcaption>"
                "</figure>" % escape(rendered["locator"])) if rendered else "",
               composition, "",
               escape(name)))

    banner = (
        "<p class='blind'><b>Blinded.</b> Cell composition is deliberately not shown. These domains "
        "were originally named from their own cell composition, which makes any composition summary "
        "over them circular; naming them from tissue architecture instead is the point of this "
        "packet.</p>"
        if blinded else
        "<p class='unblind'><b>Unblinded.</b> Cell composition is shown. Use this for a second pass "
        "<i>after</i> names are written &mdash; naming a domain from the composition it was defined "
        "by reproduces the circularity this packet exists to remove.</p>")

    source = plane.get("source", "")
    dapi_note = (
        "<p>Morphology here is <b>%s</b>. Xenium images DAPI, not H&amp;E: nuclear architecture "
        "shows ducts, stromal density and cellularity, and shows no cytoplasm. A call that needs "
        "H&amp;E or IHC is one this image cannot support &mdash; mark it <code>uncertain</code> "
        "rather than guessing.</p>" % escape(source)) if source else ""

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Region review &mdash; %s</title><style>"
        "body{font:15px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;"
        "background:#f6f8f8;color:#16211f}"
        "header.top{background:#0d2b2e;color:#eaf4f3;padding:20px 26px}"
        "header.top h1{margin:0 0 6px;font-size:22px}"
        "header.top p{margin:6px 0;max-width:78ch;font-size:13.5px;color:#b9d4d2}"
        ".blind{background:#123c2a;border-left:3px solid #4fbf8b;padding:10px 14px;border-radius:4px}"
        ".unblind{background:#43320f;border-left:3px solid #e0a84e;padding:10px 14px;border-radius:4px}"
        "main{padding:22px 26px;display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));"
        "gap:18px}"
        ".card{background:#fff;border:1px solid #dde5e4;border-radius:10px;padding:16px}"
        ".card h2{margin:0;font-size:16px;font-family:ui-monospace,Menlo,monospace}"
        ".meta{font-size:12px;color:#5d716f}"
        ".imgs{display:flex;gap:12px;align-items:flex-start;margin:12px 0}"
        ".imgs figure{margin:0;flex:1}.imgs figure.loc{flex:0 0 150px}"
        ".imgs img{width:100%%;border:1px solid #dde5e4;border-radius:6px;display:block;background:#000}"
        "figcaption{font-size:11px;color:#6b7f7d;margin-top:4px}"
        "label{display:block;margin-top:12px;font-size:13px;font-weight:600}"
        "label input{display:block;width:100%%;margin-top:5px;padding:8px 10px;font:inherit;"
        "font-weight:400;border:1px solid #c9d5d4;border-radius:6px}"
        ".warn{color:#9a5a18;font-size:12.5px;margin:6px 0}"
        "details{margin-top:10px;font-size:12.5px}summary{cursor:pointer;color:#5d716f}"
        "table.comp{border-collapse:collapse;margin-top:6px;width:100%%;font-size:12px}"
        "table.comp td{border-bottom:1px solid #eef2f2;padding:2px 6px}td.n{text-align:right;"
        "font-variant-numeric:tabular-nums}"
        "code{background:#eef2f2;padding:1px 5px;border-radius:3px;font-size:.9em}"
        "</style></head><body>"
        "<header class='top'><h1>Name these regions from the tissue</h1>"
        "<p>%d domains on <code>%s</code>. Write a name in each box, then copy them into "
        "<code>%s</code> and run <code>scripts/apply_region_naming.py</code>.</p>"
        "%s%s"
        "<p>The boundaries are the algorithm's. Accept, rename or merge them; if you want them drawn "
        "differently, say so in <code>notes</code> and draw them in Review Studio instead.</p>"
        "</header><main>%s</main></body></html>"
        % (escape(bundle.name), len(domains), escape(bundle.name), NAMING_SHEET,
           banner, dapi_note, "".join(cards))
    )


def apply_region_naming(
    dataset_path: str,
    naming_sheet: str,
    region_table: str,
    reviewer_id: str,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Turn a filled naming sheet into `cell_regions.csv`.

    The reviewer's name goes into every row, because the gate counts a reviewed
    region table and cannot read who wrote it -- the report prints that column,
    so it is the only place the distinction between a pathologist and a script
    survives.

    Domains left blank are dropped rather than carried through under their old
    machine name. A half-named table that still says `tumor_rich` for the rest
    would be the worst of both.
    """
    bundle = Path(dataset_path)
    assignments = _read_region_table(Path(region_table))

    with open(naming_sheet, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    named: Dict[str, Dict[str, str]] = {}
    for row in rows:
        label = str(row.get("pathologist_label") or "").strip()
        if not label:
            continue
        named[str(row.get("domain_id") or "").strip()] = {
            "label": label,
            "confidence": str(row.get("confidence") or "").strip() or "0.9",
            "uncertain": str(row.get("uncertain") or "").strip(),
            "notes": str(row.get("notes") or "").strip(),
        }

    if not named:
        return {"status": "empty", "reason": "No domain in %s has a pathologist_label." % naming_sheet}

    target = Path(output_path) if output_path else (bundle / "cell_regions.csv")
    written = 0
    dropped_domains = sorted(set(assignments.values()) - set(named))
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cell_id", "region", "region_confidence", "notes",
                         "assignment_scope", "reviewer_id"])
        for cell_id, domain in assignments.items():
            entry = named.get(domain)
            if not entry:
                continue
            note = entry["notes"] or "named from morphology"
            if entry["uncertain"]:
                note = "%s; reviewer marked uncertain" % note
            writer.writerow([cell_id, entry["label"], entry["confidence"], note,
                             "domain:%s" % domain, reviewer_id])
            written += 1

    coverage = written / max(len(assignments), 1)
    return {
        "status": "written",
        "path": str(target),
        "reviewer_id": reviewer_id,
        "domains_named": len(named),
        "domains_left_blank": dropped_domains,
        "cells_written": written,
        "coverage_of_assigned": round(coverage, 4),
        "distinct_regions": len({entry["label"] for entry in named.values()}),
    }
