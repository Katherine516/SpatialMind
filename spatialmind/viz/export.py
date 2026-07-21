import html
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence


REPORT_FORMATS = ("html", "pdf", "both")


class ReportExportError(RuntimeError):
    """Raised when a requested report format cannot be produced."""


@dataclass
class ReportPaths:
    html: str = ""
    pdf: str = ""

    def primary(self, report_format: str) -> str:
        normalized = normalize_report_format(report_format)
        if normalized == "pdf":
            return self.pdf
        return self.html

    def to_dict(self) -> Dict[str, str]:
        return {key: value for key, value in {"html": self.html, "pdf": self.pdf}.items() if value}


@dataclass
class PdfTable:
    headers: Sequence[str]
    rows: Sequence[Sequence[object]]
    column_widths: Sequence[float] = field(default_factory=list)


@dataclass
class PdfFigure:
    path: str
    caption: str = ""


@dataclass
class PdfSection:
    title: str
    paragraphs: List[str] = field(default_factory=list)
    bullets: List[str] = field(default_factory=list)
    tables: List[PdfTable] = field(default_factory=list)
    figures: List[PdfFigure] = field(default_factory=list)
    page_break_before: bool = False


def normalize_report_format(value: str) -> str:
    normalized = str(value or "html").strip().lower()
    if normalized not in REPORT_FORMATS:
        raise ValueError("report format must be one of: %s" % ", ".join(REPORT_FORMATS))
    return normalized


def write_pdf_report(
    path: str,
    title: str,
    sections: Sequence[PdfSection],
    metadata: Sequence[Sequence[object]] = (),
) -> str:
    """Write a self-contained, paginated PDF report using ReportLab."""

    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Image,
            KeepTogether,
            ListFlowable,
            ListItem,
            Paragraph,
            PageBreak,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except (ImportError, OSError) as exc:
        raise ReportExportError(
            "PDF output requires reportlab==4.2.5. Install the core requirements and retry."
        ) from exc

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "SpatialMindTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=27,
        textColor=colors.HexColor("#17202A"),
        alignment=TA_CENTER,
        spaceAfter=8 * mm,
    )
    heading_style = ParagraphStyle(
        "SpatialMindHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#1F4E5F"),
        spaceBefore=5 * mm,
        spaceAfter=2.5 * mm,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "SpatialMindBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor("#25313C"),
        spaceAfter=2.5 * mm,
    )
    small_style = ParagraphStyle(
        "SpatialMindSmall",
        parent=body_style,
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#52616B"),
    )
    table_header_style = ParagraphStyle(
        "SpatialMindTableHeader",
        parent=small_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    document = SimpleDocTemplate(
        str(temporary_path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=17 * mm,
        bottomMargin=17 * mm,
        title=title,
        author="SpatialMind",
    )
    story = [Paragraph(_escape(title), title_style)]

    if metadata:
        metadata_rows = [
            [Paragraph(_escape(str(row[0])), table_header_style), Paragraph(_escape(str(row[1])), small_style)]
            for row in metadata
        ]
        metadata_table = Table(metadata_rows, colWidths=[42 * mm, 126 * mm], repeatRows=0)
        metadata_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#1F4E5F")),
                    ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#F4F7F8")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAB7BF")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CDD5DA")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.extend([metadata_table, Spacer(1, 4 * mm)])

    for section in sections:
        if section.page_break_before:
            story.append(PageBreak())
        story.append(Paragraph(_escape(section.title), heading_style))
        story.extend(Paragraph(_escape(paragraph), body_style) for paragraph in section.paragraphs if paragraph)
        if section.bullets:
            items = [ListItem(Paragraph(_escape(item), body_style), leftIndent=4 * mm) for item in section.bullets if item]
            if items:
                story.extend([ListFlowable(items, bulletType="bullet", leftIndent=6 * mm), Spacer(1, 2 * mm)])
        for table_spec in section.tables:
            story.append(
                _build_table(
                    table_spec,
                    body_style=small_style,
                    header_style=table_header_style,
                    available_width=178 * mm,
                    colors=colors,
                    Table=Table,
                    TableStyle=TableStyle,
                    Paragraph=Paragraph,
                )
            )
            story.append(Spacer(1, 3 * mm))
        for figure in section.figures:
            figure_flowables = _build_figure(figure, body_style, Image, Paragraph, mm)
            if figure_flowables:
                story.extend([KeepTogether(figure_flowables), Spacer(1, 3 * mm)])

    def _page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#687780"))
        canvas.drawString(16 * mm, 9 * mm, "SpatialMind")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, "Page %d" % doc.page)
        canvas.restoreState()

    try:
        document.build(story, onFirstPage=_page, onLaterPages=_page)
        _validate_pdf(temporary_path)
        os.replace(str(temporary_path), str(output_path))
    except Exception as exc:
        temporary_path.unlink(missing_ok=True)
        if isinstance(exc, ReportExportError):
            raise
        raise ReportExportError("Could not generate PDF report: %s" % exc) from exc
    return str(output_path)


def _build_table(spec, body_style, header_style, available_width, colors, Table, TableStyle, Paragraph):
    headers = [Paragraph(_escape(str(value)), header_style) for value in spec.headers]
    rows = [[Paragraph(_escape(str(value)), body_style) for value in row] for row in spec.rows]
    column_count = max(len(headers), 1)
    if spec.column_widths:
        total = float(sum(spec.column_widths) or 1.0)
        widths = [available_width * float(value) / total for value in spec.column_widths]
    else:
        widths = [available_width / column_count] * column_count
    table = Table([headers] + rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E5F")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7F8")]),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAB7BF")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CDD5DA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _build_figure(spec, body_style, Image, Paragraph, mm):
    path = Path(spec.path)
    if not path.exists() or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return []
    image = Image(str(path))
    max_width = 172 * mm
    max_height = 178 * mm
    scale = min(max_width / float(image.imageWidth), max_height / float(image.imageHeight), 1.0)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    flowables = [image]
    if spec.caption:
        flowables.append(Paragraph(_escape(spec.caption), body_style))
    return flowables


def _validate_pdf(path: Path) -> None:
    if not path.exists() or path.stat().st_size < 1024:
        raise ReportExportError("PDF renderer produced an empty or incomplete file.")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ReportExportError("PDF renderer did not produce a valid PDF document.")


def _escape(value: str) -> str:
    return html.escape(str(value), quote=False).replace("\n", "<br/>")
