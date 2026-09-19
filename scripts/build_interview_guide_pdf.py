"""Render the submission-and-interview checklist into a PDF to study from.

    python scripts/build_interview_guide_pdf.py

The checklist is Markdown rather than DOCX, so this reads it directly instead
of going through build_learning_guide_pdf's document path. It covers the subset
the file actually uses: headings, checkbox and bullet lists, numbered items,
tables, block quotes, bold, and inline code.

Needs reportlab and a Korean TrueType font.
"""

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Docs/USER_GUIDE/09285_백준현_AI_Master_제출및면접_체크리스트.md"
OUTPUT = ROOT / "Docs/USER_GUIDE/09285_백준현_AI_Master_제출및면접_체크리스트.pdf"
TITLE = "AI Master 제출 및 면접 준비"

ACCENT = colors.HexColor("#1F4FD8")
MUTED = colors.HexColor("#667085")
RULE = colors.HexColor("#D0D5DD")
HEAD_BG = colors.HexColor("#1D2939")
ZEBRA = colors.HexColor("#F7F8FA")
QUOTE_BG = colors.HexColor("#FFF6E5")
CODE_BG = colors.HexColor("#EEF1F6")


def inline(text: str) -> str:
    """Markdown emphasis to reportlab markup, escaping everything else first."""
    out = escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(
        r"`(.+?)`",
        lambda m: f'<font face="MALGUN-B" backColor="#EEF1F6"> {m.group(1)} </font>',
        out,
    )
    return out


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def build() -> Path:
    pdfmetrics.registerFont(TTFont("MALGUN", r"C:\Windows\Fonts\malgun.ttf"))
    pdfmetrics.registerFont(TTFont("MALGUN-B", r"C:\Windows\Fonts\malgunbd.ttf"))

    base = getSampleStyleSheet()
    st = {
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontName="MALGUN-B", fontSize=18,
                             leading=25, textColor=ACCENT, alignment=TA_LEFT,
                             spaceBefore=0, spaceAfter=4 * mm, keepWithNext=True),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontName="MALGUN-B", fontSize=13,
                             leading=19, textColor=colors.HexColor("#101828"),
                             spaceBefore=6 * mm, spaceAfter=2.5 * mm, keepWithNext=True),
        "h3": ParagraphStyle("H3", parent=base["Heading3"], fontName="MALGUN-B", fontSize=11,
                             leading=17, textColor=colors.HexColor("#344054"),
                             spaceBefore=4 * mm, spaceAfter=1.5 * mm, keepWithNext=True),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName="MALGUN", fontSize=9.6,
                               leading=15.5, textColor=colors.HexColor("#1D2939"),
                               spaceAfter=2.2 * mm, wordWrap="CJK"),
        # bulletFontName defaults to Helvetica, which has no circle glyphs — the
        # markers came out as whatever that font substituted. Pin it to the
        # Korean face that actually carries them.
        "bullet": ParagraphStyle("Bullet", parent=base["BodyText"], fontName="MALGUN", fontSize=9.6,
                                 leading=15.5, textColor=colors.HexColor("#1D2939"),
                                 leftIndent=7 * mm, bulletIndent=2.5 * mm,
                                 bulletFontName="MALGUN", bulletFontSize=9.6,
                                 spaceAfter=1.2 * mm, wordWrap="CJK"),
        "quote": ParagraphStyle("Quote", parent=base["BodyText"], fontName="MALGUN-B", fontSize=10,
                                leading=16, textColor=colors.HexColor("#7A4B00"),
                                wordWrap="CJK", spaceAfter=0),
    }
    cell = ParagraphStyle("Cell", parent=st["body"], fontSize=8.4, leading=12.6, spaceAfter=0)
    cell_head = ParagraphStyle("CellHead", parent=cell, fontName="MALGUN-B", textColor=colors.white)

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("MALGUN", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 11 * mm, "09285 백준현 · MailTaskAgent")
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, str(doc.page))
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
        canvas.restoreState()

    doc = BaseDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=17 * mm, bottomMargin=19 * mm,
        title=TITLE, author="백준현",
    )
    doc.addPageTemplates(PageTemplate(
        id="main",
        frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")],
        onPage=on_page,
    ))

    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    story: list = []
    i, first_h1 = 0, True

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped == "---":
            i += 1
            continue

        # --- table: a header row followed by a separator row ---
        if stripped.startswith("|") and i + 1 < len(lines) and re.fullmatch(
            r"\|[\s:|-]+\|", lines[i + 1].strip()
        ):
            header = split_row(stripped)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i].strip()))
                i += 1
            data = [[Paragraph(inline(c), cell_head) for c in header]]
            data += [[Paragraph(inline(c), cell) for c in r] for r in rows]
            cols = len(header)
            # First column carries the label; give it room, share the rest evenly.
            if cols > 2:
                widths = [doc.width * 0.22] + [doc.width * 0.78 / (cols - 1)] * (cols - 1)
            else:
                widths = [doc.width * 0.30, doc.width * 0.70][:cols]
            table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            style = [
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
            for r in range(2, len(data), 2):
                style.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
            table.setStyle(TableStyle(style))
            story += [Spacer(1, 1.5 * mm), table, Spacer(1, 3.5 * mm)]
            continue

        # --- block quote: the pulled-out question or claim ---
        if stripped.startswith(">"):
            block = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                block.append(lines[i].strip().lstrip(">").strip())
                i += 1
            text = " ".join(x for x in block if x)
            quote = Table([[Paragraph(inline(text), st["quote"])]], colWidths=[doc.width])
            quote.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), QUOTE_BG),
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor("#E6A23C")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story += [Spacer(1, 1.5 * mm), quote, Spacer(1, 3 * mm)]
            continue

        if stripped.startswith("### "):
            story.append(Paragraph(inline(stripped[4:]), st["h3"]))
        elif stripped.startswith("## "):
            story.append(Paragraph(inline(stripped[3:]), st["h2"]))
        elif stripped.startswith("# "):
            if not first_h1:
                story.append(PageBreak())
            first_h1 = False
            story.append(Paragraph(inline(stripped[2:]), st["h1"]))
        elif stripped.startswith(("- [x]", "- [ ]")):
            # Malgun has no ballot-box glyph, so U+2611/U+2610 fall back to a
            # blank square. Filled and hollow circles are in the Korean standard
            # set and always render.
            mark = "\u25cf" if stripped.startswith("- [x]") else "\u25cb"
            story.append(Paragraph(inline(stripped[5:].strip()), st["bullet"], bulletText=mark))
        elif stripped.startswith(("- ", "* ")):
            story.append(Paragraph(inline(stripped[2:]), st["bullet"], bulletText="\u2022"))
        elif re.match(r"^\d+\. ", stripped):
            num, rest = stripped.split(". ", 1)
            story.append(Paragraph(inline(rest), st["bullet"], bulletText=f"{num}."))
        else:
            # A wrapped paragraph: join until a blank line or a new block starts.
            para = [stripped]
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if not nxt or nxt.startswith(("#", "|", ">", "- ", "* ", "---")) or re.match(r"^\d+\. ", nxt):
                    break
                para.append(nxt)
                i += 1
            story.append(Paragraph(inline(" ".join(para)), st["body"]))
            continue
        i += 1

    doc.build(story)
    return OUTPUT


if __name__ == "__main__":
    out = build()
    print(f"{out.relative_to(ROOT).as_posix()} · {out.stat().st_size:,} bytes")
