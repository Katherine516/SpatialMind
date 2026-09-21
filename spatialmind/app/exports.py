"""Export a report and its result tables in the formats people actually send.

The pipeline already writes Markdown, HTML and PDF. What it did not do is let a
user *edit* the report before sending it, or hand the numbers to someone who
works in Excel. Both are the last mile of every real analysis, and both were
being done by hand.

One rule runs through this module: **an export carries its provenance**. A table
pulled out of a run and mailed on is read without the report that qualifies it,
so every sheet and every CSV repeats the run id, the dataset and the gate
status. The report exports keep the limitations section for the same reason --
a Word file with the findings and not the caveats is worse than no export.
"""

import csv
import gzip
import io
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Long-format result tables a run writes; see `spatialmind.viz.tables`.
TABLE_DIRNAME = "tables"

_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_SEPARATOR_ROW = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")


def _clean_inline(text: str) -> str:
    """Strip the markdown that Word would otherwise show as literal characters."""
    text = _IMAGE.sub(r"[figure: \1]", text)
    text = _BOLD.sub(r"\1", text)
    text = _INLINE_CODE.sub(r"\1", text)
    return text.strip()


def _split_row(line: str) -> List[str]:
    match = _TABLE_ROW.match(line)
    if not match:
        return []
    return [_clean_inline(cell) for cell in match.group(1).split("|")]


def parse_markdown(markdown: str) -> List[Dict[str, Any]]:
    """Markdown into a small block list: heading, paragraph, bullets, table, image.

    Deliberately not a general parser. It handles exactly what the pilot report
    emits, and anything it does not recognise falls through as a paragraph --
    which is wrong-looking but never lossy, and losing a caveat is the one
    failure that matters here.
    """
    blocks: List[Dict[str, Any]] = []
    lines = (markdown or "").splitlines()
    index = 0
    paragraph: List[str] = []
    bullets: List[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append({"kind": "paragraph", "text": _clean_inline(" ".join(paragraph))})
            paragraph.clear()
        if bullets:
            blocks.append({"kind": "bullets", "items": list(bullets)})
            bullets.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            flush()
            index += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            flush()
            blocks.append({"kind": "heading", "level": len(heading.group(1)),
                           "text": _clean_inline(heading.group(2))})
            index += 1
            continue

        image = _IMAGE.match(stripped)
        if image:
            flush()
            blocks.append({"kind": "image", "alt": image.group(1), "src": image.group(2)})
            index += 1
            continue

        if _TABLE_ROW.match(stripped):
            flush()
            header = _split_row(stripped)
            rows: List[List[str]] = []
            index += 1
            if index < len(lines) and _SEPARATOR_ROW.match(lines[index]):
                index += 1
            while index < len(lines) and _TABLE_ROW.match(lines[index]):
                rows.append(_split_row(lines[index]))
                index += 1
            blocks.append({"kind": "table", "header": header, "rows": rows})
            continue

        bullet = _BULLET.match(line)
        if bullet:
            if paragraph:
                flush()
            bullets.append(_clean_inline(bullet.group(1)))
            index += 1
            continue

        if bullets:
            flush()
        paragraph.append(stripped)
        index += 1

    flush()
    return blocks


def write_docx(markdown: str, path: Path, *, title: str = "",
               provenance: Optional[Dict[str, Any]] = None,
               figure_root: Optional[Path] = None) -> Path:
    """Render a report to .docx, figures included where they can be found."""
    from docx import Document
    from docx.shared import Inches, Pt

    document = Document()
    if title:
        document.add_heading(title, level=0)
    if provenance:
        line = document.add_paragraph()
        run = line.add_run(_provenance_sentence(provenance))
        run.italic = True
        run.font.size = Pt(9)

    first_heading = True
    for block in parse_markdown(markdown):
        kind = block["kind"]
        if kind == "heading":
            # The report's own H1 repeats the title we just wrote as the document
            # title, so the first page said the same sentence twice.
            if first_heading and block["level"] == 1 and \
                    block["text"].strip().lower() == (title or "").strip().lower():
                first_heading = False
                continue
            first_heading = False
            # Word's level 0 is the document title, already used above.
            document.add_heading(block["text"], level=min(max(block["level"], 1), 4))
        elif kind == "paragraph":
            document.add_paragraph(block["text"])
        elif kind == "bullets":
            for item in block["items"]:
                document.add_paragraph(item, style="List Bullet")
        elif kind == "table":
            header = block["header"]
            if not header:
                continue
            table = document.add_table(rows=1, cols=len(header))
            table.style = "Light Grid Accent 1"
            for cell, text in zip(table.rows[0].cells, header):
                cell.text = text
            for row in block["rows"]:
                cells = table.add_row().cells
                for cell, text in zip(cells, row):
                    cell.text = text
            document.add_paragraph()
        elif kind == "image":
            placed = _resolve_figure(block["src"], figure_root)
            if placed:
                try:
                    document.add_picture(str(placed), width=Inches(6.0))
                    continue
                except Exception:
                    pass
            document.add_paragraph("[figure: %s]" % (block["alt"] or block["src"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path


def _resolve_figure(src: str, root: Optional[Path]) -> Optional[Path]:
    if not root:
        return None
    candidate = Path(src)
    if not candidate.is_absolute():
        candidate = Path(root) / src
    if candidate.exists() and candidate.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif"):
        return candidate
    return None


def _provenance_sentence(provenance: Dict[str, Any]) -> str:
    bits = []
    if provenance.get("run_id"):
        bits.append("Run %s" % provenance["run_id"])
    if provenance.get("dataset"):
        bits.append("dataset %s" % provenance["dataset"])
    if provenance.get("gate_status"):
        bits.append("gate %s" % provenance["gate_status"])
    if provenance.get("edited"):
        bits.append("edited by hand after the run")
    return " | ".join(bits) if bits else ""


def write_pdf(markdown: str, path: Path, *, title: str = "",
              provenance: Optional[Dict[str, Any]] = None) -> Path:
    """Render a report to PDF with reportlab, which the app already ships."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)
    from xml.sax.saxutils import escape

    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=7.5, leading=9.5)
    note = ParagraphStyle("note", parent=styles["Normal"], fontSize=8, textColor=colors.grey,
                          italic=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(str(path), pagesize=LETTER,
                                 leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                                 topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                                 title=title or "SpatialMind report")
    story: List[Any] = []
    if title:
        story.append(Paragraph(escape(title), styles["Title"]))
    if provenance:
        story.append(Paragraph(escape(_provenance_sentence(provenance)), note))
        story.append(Spacer(1, 8))

    for block in parse_markdown(markdown):
        kind = block["kind"]
        if kind == "heading":
            level = min(max(block["level"], 1), 4)
            story.append(Spacer(1, 6))
            story.append(Paragraph(escape(block["text"]), styles["Heading%d" % level]))
        elif kind == "paragraph":
            story.append(Paragraph(escape(block["text"]), styles["BodyText"]))
        elif kind == "bullets":
            for item in block["items"]:
                story.append(Paragraph("&bull; %s" % escape(item), styles["BodyText"]))
        elif kind == "table":
            header = block["header"]
            if not header:
                continue
            # Wide tables are unreadable at letter width; cap the columns and say so.
            columns = min(len(header), 8)
            data = [[Paragraph("<b>%s</b>" % escape(c), small) for c in header[:columns]]]
            for row in block["rows"][:60]:
                data.append([Paragraph(escape(c), small) for c in row[:columns]])
            table = Table(data, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9cdd4")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(table)
            if len(block["rows"]) > 60 or len(header) > columns:
                story.append(Paragraph(
                    "Truncated for print: %d rows, %d columns. The full table is in the CSV/Excel export."
                    % (len(block["rows"]), len(header)), note))
            story.append(Spacer(1, 8))
        elif kind == "image":
            story.append(Paragraph("[figure: %s]" % escape(block["alt"] or block["src"]), note))

    document.build(story)
    return path


def read_table(path: Path, limit: int = 0) -> Tuple[List[str], List[List[str]], List[str]]:
    """Read one result table. Returns (header, rows, provenance comment lines).

    Result tables carry `#`-prefixed provenance at the top. It is kept and
    re-emitted rather than skipped, because the whole point of putting it there
    was that a table gets read away from its report.
    """
    opener = gzip.open if str(path).endswith(".gz") else open
    comments: List[str] = []
    header: List[str] = []
    rows: List[List[str]] = []
    with opener(path, "rt", newline="", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                comments.append(line.rstrip("\n").lstrip("# ").strip())
                continue
            break_line = line
            break
        else:
            return header, rows, comments
        delimiter = "\t" if "\t" in break_line else ","
        header = next(csv.reader([break_line], delimiter=delimiter), [])
        reader = csv.reader(handle, delimiter=delimiter)
        for index, row in enumerate(reader):
            if limit and index >= limit:
                break
            rows.append(row)
    return header, rows, comments


def list_tables(run_dir: Path) -> List[Dict[str, Any]]:
    """Every result table in a run directory, newest layout first."""
    tables_dir = Path(run_dir) / TABLE_DIRNAME
    found: List[Dict[str, Any]] = []
    if not tables_dir.exists():
        return found
    for path in sorted(tables_dir.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        found.append({
            "name": path.name,
            "path": str(path),
            "bytes": path.stat().st_size,
            "kind": _table_kind(path.name),
        })
    return found


def _table_kind(name: str) -> str:
    """What a table is *about*, so the UI can offer "all cells" vs "all genes"."""
    lowered = name.lower()
    if lowered.startswith("cells."):
        return "cells"
    if "gene" in lowered:
        return "genes"
    if "marker" in lowered:
        return "genes"
    if "region" in lowered:
        return "regions"
    if "pair" in lowered:
        return "pairs"
    if "cell_type" in lowered or "point_pattern" in lowered:
        return "cell_types"
    return "other"


def write_xlsx(tables: Sequence[Dict[str, Any]], path: Path, *,
               provenance: Optional[Dict[str, Any]] = None, row_limit: int = 1_000_000) -> Path:
    """Every result table as one workbook, one sheet each, provenance first.

    Excel's hard ceiling is 1,048,576 rows. A `cells.tsv.gz` from a full section
    is well under that, but a future one need not be, so a sheet that is cut
    says so in the sheet itself rather than silently ending.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    summary = workbook.active
    summary.title = "About"
    summary["A1"] = "SpatialMind analysis results"
    summary["A1"].font = Font(bold=True, size=13)
    row = 3
    for key, value in (provenance or {}).items():
        summary.cell(row=row, column=1, value=str(key)).font = Font(bold=True)
        summary.cell(row=row, column=2, value=str(value))
        row += 1
    row += 1
    summary.cell(row=row, column=1, value="Sheets").font = Font(bold=True)
    row += 1

    used: set = {"About"}
    for table in tables:
        source = Path(table["path"])
        header, rows, comments = read_table(source, limit=row_limit)
        sheet_name = _unique_sheet_name(source.name, used)
        used.add(sheet_name)
        summary.cell(row=row, column=1, value=sheet_name)
        summary.cell(row=row, column=2, value="%s (%s rows)" % (source.name, format(len(rows), ",")))
        row += 1

        sheet = workbook.create_sheet(sheet_name)
        line = 1
        for comment in comments:
            cell = sheet.cell(row=line, column=1, value=comment)
            cell.font = Font(italic=True, size=9)
            line += 1
        if comments:
            line += 1
        for column, name in enumerate(header, start=1):
            sheet.cell(row=line, column=column, value=name).font = Font(bold=True)
        sheet.freeze_panes = sheet.cell(row=line + 1, column=1)
        line += 1
        for record in rows:
            for column, value in enumerate(record, start=1):
                sheet.cell(row=line, column=column, value=_coerce(value))
            line += 1
        if len(rows) >= row_limit:
            sheet.cell(row=line, column=1,
                       value="TRUNCATED at %s rows. Use the CSV export for the whole table."
                             % format(row_limit, ",")).font = Font(bold=True)
        for column in range(1, min(len(header), 40) + 1):
            sheet.column_dimensions[get_column_letter(column)].width = 18

    summary.column_dimensions["A"].width = 26
    summary.column_dimensions["B"].width = 72
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(str(path))
    return path


def _unique_sheet_name(filename: str, used: Iterable[str]) -> str:
    """Excel sheet names: 31 characters, and no []:*?/\\ ."""
    base = re.sub(r"\.(tsv|csv)(\.gz)?$", "", filename)
    base = re.sub(r"[\[\]:*?/\\]", "_", base)[:31] or "sheet"
    name = base
    taken = set(used)
    suffix = 2
    while name in taken:
        tail = "_%d" % suffix
        name = base[:31 - len(tail)] + tail
        suffix += 1
    return name


def _coerce(value: str) -> Any:
    """Numbers as numbers, so Excel can sort and chart them."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        return float(text)
    except ValueError:
        return text


def write_csv_bundle(tables: Sequence[Dict[str, Any]], path: Path,
                     provenance: Optional[Dict[str, Any]] = None) -> Path:
    """All result tables as one .zip of CSVs, each keeping its provenance header."""
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as archive:
        if provenance:
            archive.writestr("PROVENANCE.txt", "\n".join(
                "%s: %s" % (key, value) for key, value in provenance.items()))
        for table in tables:
            source = Path(table["path"])
            header, rows, comments = read_table(source)
            buffer = io.StringIO()
            for comment in comments:
                buffer.write("# %s\n" % comment)
            writer = csv.writer(buffer)
            if header:
                writer.writerow(header)
            writer.writerows(rows)
            name = re.sub(r"\.(tsv)(\.gz)?$", ".csv", source.name)
            if not name.endswith(".csv"):
                name += ".csv"
            archive.writestr(name, buffer.getvalue())
    return path


def write_text(markdown: str, path: Path, provenance: Optional[Dict[str, Any]] = None) -> Path:
    """Plain text, for pasting into anything."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    if provenance:
        lines.append(_provenance_sentence(provenance))
        lines.append("")
    for block in parse_markdown(markdown):
        kind = block["kind"]
        if kind == "heading":
            lines.extend(["", block["text"].upper() if block["level"] <= 2 else block["text"],
                          "-" * len(block["text"])])
        elif kind == "paragraph":
            lines.extend([block["text"], ""])
        elif kind == "bullets":
            lines.extend("  - %s" % item for item in block["items"])
            lines.append("")
        elif kind == "table":
            widths = [max(len(str(cell)) for cell in column)
                      for column in zip(*([block["header"]] + block["rows"]))] if block["rows"] else \
                     [len(cell) for cell in block["header"]]
            def row_text(cells: Sequence[str]) -> str:
                return "  ".join(str(cell).ljust(width) for cell, width in zip(cells, widths))
            lines.append(row_text(block["header"]))
            lines.append("  ".join("-" * width for width in widths))
            lines.extend(row_text(row) for row in block["rows"])
            lines.append("")
        elif kind == "image":
            lines.append("[figure: %s]" % (block["alt"] or block["src"]))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
