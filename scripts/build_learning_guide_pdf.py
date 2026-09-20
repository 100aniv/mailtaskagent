"""Render the understanding-and-demo guide DOCX into its submission PDF.

    python scripts/build_learning_guide_pdf.py

Run it after scripts/build_learning_guide.py; it reads the DOCX that produced.
Needs reportlab and a Korean TrueType font.
"""

from pathlib import Path

from docx import Document
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph as PdfParagraph,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Docs" / "STUDY" / "02_이해와시연가이드.docx"
OUT_DIR = ROOT / "Docs" / "STUDY"
OUTPUT = OUT_DIR / "02_이해와시연가이드.pdf"


def iter_blocks(document):
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield DocxTable(child, document)


def rich_text(paragraph):
    parts = []
    for run in paragraph.runs:
        text = escape(run.text).replace("\n", "<br/>")
        if not text:
            continue
        if run.bold:
            text = f"<b>{text}</b>"
        parts.append(text)
    return "".join(parts) or escape(paragraph.text).replace("\n", "<br/>")


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("MALGUN", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(19 * mm, 12 * mm, "MailTaskAgent 이해와 시연 가이드")
    canvas.drawRightString(letter[0] - 19 * mm, 12 * mm, str(doc.page))
    canvas.restoreState()


def build():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(TTFont("MALGUN", r"C:\Windows\Fonts\malgun.ttf"))
    pdfmetrics.registerFont(TTFont("MALGUN-B", r"C:\Windows\Fonts\malgunbd.ttf"))

    base = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle(
            "TitleK",
            parent=base["Title"],
            fontName="MALGUN-B",
            fontSize=25,
            leading=34,
            textColor=colors.black,
            alignment=TA_LEFT,
            spaceAfter=8 * mm,
        ),
        "Heading 1": ParagraphStyle(
            "H1K",
            parent=base["Heading1"],
            fontName="MALGUN-B",
            fontSize=16,
            leading=22,
            textColor=colors.black,
            spaceBefore=7 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
        ),
        "Heading 2": ParagraphStyle(
            "H2K",
            parent=base["Heading2"],
            fontName="MALGUN-B",
            fontSize=12,
            leading=18,
            textColor=colors.black,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
        ),
        "Normal": ParagraphStyle(
            "BodyK",
            parent=base["BodyText"],
            fontName="MALGUN",
            fontSize=10.5,
            leading=17,
            textColor=colors.HexColor("#222222"),
            spaceAfter=2.2 * mm,
            wordWrap="CJK",
        ),
        "List Bullet": ParagraphStyle(
            "BulletK",
            parent=base["BodyText"],
            fontName="MALGUN",
            fontSize=10.5,
            leading=17,
            leftIndent=7 * mm,
            firstLineIndent=-4 * mm,
            bulletIndent=2 * mm,
            spaceAfter=1.5 * mm,
            wordWrap="CJK",
        ),
        "List Number": ParagraphStyle(
            "NumberK",
            parent=base["BodyText"],
            fontName="MALGUN",
            fontSize=10.5,
            leading=17,
            leftIndent=8 * mm,
            firstLineIndent=-5 * mm,
            spaceAfter=1.5 * mm,
            wordWrap="CJK",
        ),
    }
    caption = ParagraphStyle(
        "CaptionK", parent=styles["Normal"], fontSize=9, leading=14, textColor=colors.HexColor("#667085")
    )
    cell = ParagraphStyle("CellK", parent=styles["Normal"], fontSize=8.8, leading=13, spaceAfter=0)
    cell_b = ParagraphStyle("CellBoldK", parent=cell, fontName="MALGUN-B", textColor=colors.white)

    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=letter,
        leftMargin=19 * mm,
        rightMargin=19 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title="MailTaskAgent 이해와 시연 가이드",
        author="백준현",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=on_page))

    story = []
    source = Document(SOURCE)
    numbered = 0
    first_heading = True
    for block in iter_blocks(source):
        if isinstance(block, Paragraph):
            text = rich_text(block).strip()
            if not text:
                story.append(Spacer(1, 1.2 * mm))
                continue
            name = block.style.name if block.style else "Normal"
            if name == "Title":
                story.append(PdfParagraph(text, styles["Title"]))
            elif name == "Heading 1":
                plain = block.text.strip()
                if plain.startswith(("2 ", "7 ", "12 ")):
                    story.append(PageBreak())
                if not first_heading:
                    story.append(Spacer(1, 1 * mm))
                first_heading = False
                story.append(PdfParagraph(text, styles["Heading 1"]))
            elif name == "Heading 2":
                story.append(PdfParagraph(text, styles["Heading 2"]))
            elif name == "List Bullet":
                story.append(PdfParagraph(text, styles["List Bullet"], bulletText="•"))
            elif name == "List Number":
                numbered += 1
                story.append(PdfParagraph(f"{numbered}. {text}", styles["List Number"]))
            else:
                numbered = 0
                selected = caption if len(block.text) < 34 and block.text.endswith(("점", "말")) else styles["Normal"]
                story.append(PdfParagraph(text, selected))
        else:
            data = []
            for r_index, row in enumerate(block.rows):
                style = cell_b if r_index == 0 else cell
                data.append([PdfParagraph(escape(c.text).replace("\n", "<br/>"), style) for c in row.cells])
            cols = len(data[0]) if data else 1
            widths = [doc.width / cols] * cols
            table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            commands = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173B67")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "MALGUN-B"),
                ("FONTNAME", (0, 1), (-1, -1), "MALGUN"),
                ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#D9D9D9")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
            for r_index in range(1, len(data)):
                if r_index % 2 == 0:
                    commands.append(("BACKGROUND", (0, r_index), (-1, r_index), colors.HexColor("#F5F8FC")))
            table.setStyle(TableStyle(commands))
            story.extend([table, Spacer(1, 3 * mm)])

    doc.build(story)
    print(OUTPUT)


if __name__ == "__main__":
    build()
