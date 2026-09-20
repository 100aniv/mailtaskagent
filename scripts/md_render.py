"""Render the study documents from Markdown into DOCX and PDF.

The interview checklist grew its own PDF builder, and the study book needs the
same thing plus a Word version. Rather than a second copy, both formats are
produced here from one parse of the Markdown, covering the subset these
documents use: headings, bullet and checkbox lists, numbered items, tables,
block quotes, fenced code, bold and inline code.

    from scripts.md_render import parse, to_pdf, to_docx

Needs python-docx, reportlab and a Korean TrueType font.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

FONT_REGULAR = r"C:\Windows\Fonts\malgun.ttf"
FONT_BOLD = r"C:\Windows\Fonts\malgunbd.ttf"

INK = "1D2939"
ACCENT = "1F4FD8"
MUTED = "667085"
RULE = "D0D5DD"
HEAD_BG = "1D2939"
ZEBRA = "F7F8FA"
QUOTE_BG = "FFF6E5"
QUOTE_EDGE = "E6A23C"
QUOTE_INK = "7A4B00"
CODE_BG = "EEF1F6"


@dataclass
class Block:
    kind: str                      # h1 h2 h3 h4 para bullet number quote table code rule
    text: str = ""
    marker: str = ""               # bullet glyph or list number
    rows: list[list[str]] = field(default_factory=list)


def parse(md: str) -> list[Block]:
    """Markdown subset to a flat block list, in document order."""
    lines = md.splitlines()
    out: list[Block] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if not line:
            i += 1
            continue

        if line.startswith("```"):
            i += 1
            body = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            out.append(Block("code", "\n".join(body)))
            continue

        if re.fullmatch(r"(---+|\*\*\*+|___+)", line):
            out.append(Block("rule"))
            i += 1
            continue

        # A header row followed by the |---|---| separator.
        if line.startswith("|") and i + 1 < len(lines) and re.fullmatch(
            r"\|[\s:|-]+\|", lines[i + 1].strip()
        ):
            def cells(s: str) -> list[str]:
                return [c.strip() for c in s.strip().strip("|").split("|")]

            rows = [cells(line)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(cells(lines[i].strip()))
                i += 1
            out.append(Block("table", rows=rows))
            continue

        if line.startswith(">"):
            body = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                body.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(Block("quote", " ".join(x for x in body if x)))
            continue

        m = re.match(r"^(#{1,6}) +(.*)$", line)
        if m:
            out.append(Block(f"h{min(len(m.group(1)), 4)}", m.group(2).strip()))
            i += 1
            continue

        def wrapped(start: int) -> tuple[str, int]:
            """A list item plus the indented lines that continue it.

            These documents wrap long bullets onto indented lines. Without this
            the continuation became its own unindented paragraph, which is how
            the first build rendered chapter 2's pain points.
            """
            parts_, j = [], start
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip():
                    break
                if not nxt.startswith((" ", "\t")):
                    break
                if re.match(r"^\s*([-*] |\d+\. |#{1,6} |\||>)", nxt):
                    break
                parts_.append(nxt.strip())
                j += 1
            return " ".join(parts_), j

        if line.startswith(("- [x]", "- [ ]")):
            tail, i2 = wrapped(i + 1)
            out.append(Block("bullet", " ".join(filter(None, [line[5:].strip(), tail])),
                             marker="\u25cf" if line.startswith("- [x]") else "\u25cb"))
            i = i2
            continue

        if line.startswith(("- ", "* ")):
            tail, i2 = wrapped(i + 1)
            out.append(Block("bullet", " ".join(filter(None, [line[2:].strip(), tail])),
                             marker="\u2022"))
            i = i2
            continue

        m = re.match(r"^(\d+)\. +(.*)$", line)
        if m:
            tail, i2 = wrapped(i + 1)
            out.append(Block("number", " ".join(filter(None, [m.group(2).strip(), tail])),
                             marker=f"{m.group(1)}."))
            i = i2
            continue

        # Paragraph: join wrapped lines until a blank line or a new block.
        para = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt or nxt.startswith(("#", "|", ">", "- ", "* ", "```")) \
                    or re.match(r"^\d+\. ", nxt) or re.fullmatch(r"(---+|\*\*\*+|___+)", nxt):
                break
            para.append(nxt)
            i += 1
        out.append(Block("para", " ".join(para)))
    return out


# --------------------------------------------------------------------------- PDF

def _pdf_inline(text: str) -> str:
    out = escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"`(.+?)`",
                 lambda m: f'<font face="MALGUN-B" backColor="#{CODE_BG}"> {m.group(1)} </font>',
                 out)
    return out


def to_pdf(md: str, out_path: Path, title: str, footer: str) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
                                    Paragraph, Spacer, Table, TableStyle, XPreformatted)

    pdfmetrics.registerFont(TTFont("MALGUN", FONT_REGULAR))
    pdfmetrics.registerFont(TTFont("MALGUN-B", FONT_BOLD))
    # Without the family mapping, <b> inside a paragraph has no bold face to
    # switch to and reportlab falls back to the regular one.
    pdfmetrics.registerFontFamily("MALGUN", normal="MALGUN", bold="MALGUN-B",
                                  italic="MALGUN", boldItalic="MALGUN-B")
    base = getSampleStyleSheet()

    def style(name, size, leading, **kw):
        return ParagraphStyle(name, parent=base["BodyText"], fontName=kw.pop("font", "MALGUN"),
                              fontSize=size, leading=leading, wordWrap="CJK",
                              textColor=colors.HexColor("#" + kw.pop("ink", INK)), **kw)

    st = {
        "h1": style("h1", 18, 25, font="MALGUN-B", ink=ACCENT, alignment=TA_LEFT,
                    spaceAfter=4 * mm, keepWithNext=True),
        "h2": style("h2", 13.5, 20, font="MALGUN-B", ink="101828",
                    spaceBefore=6 * mm, spaceAfter=2.5 * mm, keepWithNext=True),
        "h3": style("h3", 11, 17, font="MALGUN-B", ink="344054",
                    spaceBefore=4 * mm, spaceAfter=1.5 * mm, keepWithNext=True),
        "h4": style("h4", 10, 16, font="MALGUN-B", ink="475467",
                    spaceBefore=3 * mm, spaceAfter=1.2 * mm, keepWithNext=True),
        "para": style("para", 9.6, 15.5, spaceAfter=2.2 * mm),
        "bullet": style("bullet", 9.6, 15.5, leftIndent=7 * mm, bulletIndent=2.5 * mm,
                        bulletFontName="MALGUN", bulletFontSize=9.6, spaceAfter=1.2 * mm),
        "quote": style("quote", 10, 16, font="MALGUN-B", ink=QUOTE_INK, spaceAfter=0),
        "code": style("code", 8.4, 12.8, font="MALGUN", ink="344054", spaceAfter=0,
                      backColor=colors.HexColor("#" + CODE_BG), borderPadding=6,
                      leftIndent=2, rightIndent=2),
    }
    cell = style("cell", 8.4, 12.6, spaceAfter=0)
    cell_head = ParagraphStyle("cellhead", parent=cell, fontName="MALGUN-B",
                               textColor=colors.white)

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("MALGUN", 7.5)
        canvas.setFillColor(colors.HexColor("#" + MUTED))
        canvas.drawString(18 * mm, 11 * mm, footer)
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, str(doc.page))
        canvas.setStrokeColor(colors.HexColor("#" + RULE))
        canvas.setLineWidth(0.4)
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
        canvas.restoreState()

    doc = BaseDocTemplate(str(out_path), pagesize=A4,
                          leftMargin=18 * mm, rightMargin=18 * mm,
                          topMargin=17 * mm, bottomMargin=19 * mm,
                          title=title, author="백준현")
    doc.addPageTemplates(PageTemplate(
        id="main",
        frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")],
        onPage=on_page))

    story: list = []
    first_h1 = True
    for b in parse(md):
        if b.kind == "table":
            data = [[Paragraph(_pdf_inline(c), cell_head) for c in b.rows[0]]]
            data += [[Paragraph(_pdf_inline(c), cell) for c in r] for r in b.rows[1:]]
            cols = len(b.rows[0])
            widths = ([doc.width * 0.22] + [doc.width * 0.78 / (cols - 1)] * (cols - 1)
                      if cols > 2 else [doc.width * 0.30, doc.width * 0.70][:cols])
            tbl = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            rules = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + HEAD_BG)),
                     ("VALIGN", (0, 0), (-1, -1), "TOP"),
                     ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#" + RULE)),
                     ("TOPPADDING", (0, 0), (-1, -1), 3),
                     ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                     ("LEFTPADDING", (0, 0), (-1, -1), 5),
                     ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
            for r in range(2, len(data), 2):
                rules.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#" + ZEBRA)))
            tbl.setStyle(TableStyle(rules))
            story += [Spacer(1, 1.5 * mm), tbl, Spacer(1, 3.5 * mm)]
        elif b.kind == "quote":
            q = Table([[Paragraph(_pdf_inline(b.text), st["quote"])]], colWidths=[doc.width])
            q.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#" + QUOTE_BG)),
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor("#" + QUOTE_EDGE)),
                ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            story += [Spacer(1, 1.5 * mm), q, Spacer(1, 3 * mm)]
        elif b.kind == "code":
            # A table cell cannot split, and 04's architecture diagram is taller
            # than a page. XPreformatted keeps the spacing and breaks across
            # pages, carrying its own background.
            story += [Spacer(1, 1.5 * mm),
                      XPreformatted(escape(b.text), st["code"]),
                      Spacer(1, 3 * mm)]
        elif b.kind == "rule":
            story.append(Spacer(1, 2 * mm))
        elif b.kind in ("bullet", "number"):
            story.append(Paragraph(_pdf_inline(b.text), st["bullet"], bulletText=b.marker))
        elif b.kind == "h1":
            if not first_h1:
                story.append(PageBreak())
            first_h1 = False
            story.append(Paragraph(_pdf_inline(b.text), st["h1"]))
        elif b.kind in ("h2", "h3", "h4"):
            story.append(Paragraph(_pdf_inline(b.text), st[b.kind]))
        else:
            story.append(Paragraph(_pdf_inline(b.text), st["para"]))

    doc.build(story)
    return out_path


# -------------------------------------------------------------------------- DOCX

def _docx_runs(paragraph, text: str) -> None:
    """Write **bold** and `code` as runs on an existing python-docx paragraph."""
    for piece in re.split(r"(\*\*.+?\*\*|`.+?`)", text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            paragraph.add_run(piece[2:-2]).bold = True
        elif piece.startswith("`") and piece.endswith("`"):
            run = paragraph.add_run(piece[1:-1])
            run.font.name = "Consolas"
            run.bold = True
        else:
            paragraph.add_run(piece)


def to_docx(md: str, out_path: Path, title: str) -> Path:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "맑은 고딕"
    normal.font.size = Pt(10)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")

    for name, size, color in (("Heading 1", 17, ACCENT), ("Heading 2", 13, "101828"),
                              ("Heading 3", 11, "344054"), ("Heading 4", 10, "475467")):
        s = doc.styles[name]
        s.font.name = "맑은 고딕"
        s.font.size = Pt(size)
        s.font.bold = True
        s.font.color.rgb = RGBColor.from_string(color)
        s._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")

    heading = doc.add_paragraph(title, style="Title")
    heading.alignment = WD_ALIGN_PARAGRAPH.LEFT

    def shade(cell, hex_color: str) -> None:
        el = OxmlElement("w:shd")
        el.set(qn("w:val"), "clear")
        el.set(qn("w:fill"), hex_color)
        cell._tc.get_or_add_tcPr().append(el)

    for b in parse(md):
        if b.kind == "table":
            t = doc.add_table(rows=len(b.rows), cols=len(b.rows[0]))
            t.style = "Table Grid"
            for r, row in enumerate(b.rows):
                for c, text in enumerate(row):
                    cell = t.cell(r, c)
                    cell.text = ""
                    p = cell.paragraphs[0]
                    _docx_runs(p, text)
                    for run in p.runs:
                        run.font.size = Pt(8.5)
                        if r == 0:
                            run.bold = True
                            run.font.color.rgb = RGBColor.from_string("FFFFFF")
                    shade(cell, HEAD_BG if r == 0 else (ZEBRA if r % 2 == 0 else "FFFFFF"))
            doc.add_paragraph()
        elif b.kind == "quote":
            p = doc.add_paragraph(style="Intense Quote")
            _docx_runs(p, b.text)
        elif b.kind == "code":
            p = doc.add_paragraph()
            run = p.add_run(b.text)
            run.font.name = "Consolas"
            run.font.size = Pt(8.5)
            p.paragraph_format.left_indent = Pt(14)
        elif b.kind == "rule":
            continue
        elif b.kind == "bullet":
            _docx_runs(doc.add_paragraph(style="List Bullet"), b.text)
        elif b.kind == "number":
            _docx_runs(doc.add_paragraph(style="List Number"), b.text)
        elif b.kind.startswith("h"):
            level = int(b.kind[1])
            _docx_runs(doc.add_paragraph(style=f"Heading {level}"), b.text)
        else:
            _docx_runs(doc.add_paragraph(), b.text)

    doc.save(str(out_path))
    return out_path
