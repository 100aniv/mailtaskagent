"""Draw the architecture diagram that goes in the official template's slide 3.

    python scripts/build_architecture_diagram.py

The official template leaves a tall portrait box for the system diagram, which
the deck's own wide node row does not fit. This draws the same five nodes
vertically so the two feedback arrows — the Self-Correction retry and the
post-execution re-read — are visible as arrows rather than described in text.

Colours are the template's own: navy #1A365D and teal #4ECDC4, sampled from a
render of the unmodified template.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "template-deck" / "architecture.png"

# The box the template reserves, in points, and the factor we render at.
BOX_W, BOX_H = 344.0, 316.0
SCALE = 4
W, H = int(BOX_W * SCALE), int(BOX_H * SCALE)

NAVY = "#1A365D"
TEAL = "#4ECDC4"
INK = "#1A1A1A"
MUTED = "#6B7280"
LINE = "#D8DEE6"
PALE = "#F8F9FA"
AGENT_BG = "#F3EFFF"
AGENT_LINE = "#7657D6"

FONT_DIR = Path("C:/Windows/Fonts")


def font(size: float, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "malgunbd.ttf" if bold else "malgun.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), int(size * SCALE))


def pt(value: float) -> int:
    return int(round(value * SCALE))


NODES = [
    ("M-01", "Mail Analyzer", "회사 gpt-4.1-mini가 의미·Intent·기한을 구조화", False),
    ("M-02", "Task Context RAG", "SQLite에서 활성 Task·최근 Mail 3건·History 5건 검색", False),
    ("M-03", "Context Agent", "가설 2~3개 생성 → 계약 검증 → 평가로 하나 선택", True),
    ("Guard", "Python Policy", "후보 범위·상태 전이·중요 변경 검증, 미달이면 ASK_USER", False),
    ("M-04", "DB Tool", "승인된 Action만 저장하고 저장 결과를 다시 조회", False),
    ("M-05", "Review·Trace", "사용자 확인 화면과 판단 근거 Trace", False),
]


def rounded(draw, box, fill, outline, radius=5):
    draw.rounded_rectangle(box, radius=pt(radius), fill=fill, outline=outline, width=max(1, SCALE // 2))


def arrow_down(draw, x, y0, y1, color=NAVY):
    draw.line([(x, y0), (x, y1 - pt(3))], fill=color, width=max(2, SCALE // 2))
    head = pt(3)
    draw.polygon([(x - head, y1 - pt(4)), (x + head, y1 - pt(4)), (x, y1)], fill=color)


def feedback(draw, x_side, y_from, y_to, x_node_edge, color, label, label_lines, on_left):
    """A squared-off arrow running back up the outside of the node column."""
    width = max(2, SCALE // 2)
    draw.line([(x_node_edge, y_from), (x_side, y_from)], fill=color, width=width)
    draw.line([(x_side, y_from), (x_side, y_to)], fill=color, width=width)
    draw.line([(x_side, y_to), (x_node_edge - pt(2), y_to)], fill=color, width=width)
    head = pt(3)
    tip_x = x_node_edge if on_left else x_node_edge
    draw.polygon(
        [(tip_x - (head if on_left else -head), y_to - head),
         (tip_x - (head if on_left else -head), y_to + head),
         (tip_x, y_to)],
        fill=color,
    )
    # The label sits on the arrow's own vertical run, so clear the line behind it.
    small = font(5.2, True)
    line_height = pt(6.5)
    top = (y_from + y_to) / 2 - pt(7)
    widest = max(draw.textlength(line, font=small) for line in label_lines)
    draw.rectangle(
        (x_side - widest / 2 - pt(2), top - pt(1.5),
         x_side + widest / 2 + pt(2), top + len(label_lines) * line_height),
        fill="white",
    )
    for index, line in enumerate(label_lines):
        text_width = draw.textlength(line, font=small)
        draw.text((x_side - text_width / 2, top + index * line_height), line, font=small, fill=color)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(image)

    header = font(6.6, True)
    draw.text((pt(8), pt(4)), "Observe → Retrieve → Reason → Act → Observe", font=header, fill=NAVY)
    sub = font(5.4)
    draw.text((pt(8), pt(14)), "제한적 ReAct · 재검색과 재판단은 최대 1회", font=sub, fill=MUTED)

    left_margin = pt(52)
    right_margin = pt(40)
    node_x0, node_x1 = left_margin, W - right_margin
    top = pt(28)
    node_h = pt(37)
    gap = pt(10.5)

    id_font = font(6.4, True)
    title_font = font(7.4, True)
    desc_font = font(5.3)

    centers = []
    for index, (node_id, title, desc, highlight) in enumerate(NODES):
        y0 = top + index * (node_h + gap)
        y1 = y0 + node_h
        centers.append((y0, y1))
        rounded(
            draw, (node_x0, y0, node_x1, y1),
            AGENT_BG if highlight else PALE,
            AGENT_LINE if highlight else LINE,
        )
        pill_w = pt(30)
        rounded(
            draw, (node_x0 + pt(6), y0 + pt(6), node_x0 + pt(6) + pill_w, y0 + pt(17)),
            AGENT_LINE if highlight else NAVY, None, radius=3,
        )
        id_width = draw.textlength(node_id, font=id_font)
        draw.text(
            (node_x0 + pt(6) + (pill_w - id_width) / 2, y0 + pt(7.4)),
            node_id, font=id_font, fill="white",
        )
        draw.text((node_x0 + pt(42), y0 + pt(5.6)), title, font=title_font, fill=NAVY)
        draw.text((node_x0 + pt(42), y0 + pt(18)), desc, font=desc_font, fill=MUTED)
        if index:
            arrow_down(draw, (node_x0 + node_x1) // 2, centers[index - 1][1], y0)

    # Self-Correction: M-03 back up to M-02.
    feedback(
        draw,
        x_side=pt(22),
        y_from=centers[2][0] + node_h // 2,
        y_to=centers[1][0] + node_h // 2,
        x_node_edge=node_x0,
        color=AGENT_LINE,
        label="Self-Correction",
        label_lines=["Self-", "Correction", "최대 1회"],
        on_left=True,
    )

    # Act–Observe: the saved result is read back and re-observed.
    feedback(
        draw,
        x_side=W - pt(16),
        y_from=centers[4][0] + node_h // 2,
        y_to=centers[2][0] + node_h // 2,
        x_node_edge=node_x1,
        color=TEAL,
        label="Observe",
        label_lines=["Observe", "저장 결과", "재조회"],
        on_left=False,
    )

    footer = font(5.2)
    draw.text(
        (pt(8), H - pt(14)),
        "Vector DB·외부 Embedding 없이 SQLite Structured Retrieval · LLM은 제안만, DB 변경은 Python",
        font=footer, fill=MUTED,
    )

    image.save(OUTPUT)
    print(f"{OUTPUT.relative_to(ROOT).as_posix()}  {image.size[0]}x{image.size[1]}px "
          f"({BOX_W:.0f}x{BOX_H:.0f}pt)")


if __name__ == "__main__":
    main()
