"""Render the interview Q&A into the PDF that gets printed and studied from.

    python scripts/build_interview_guide_pdf.py

The Markdown in Docs/STUDY is the source; the layout lives in md_render so the
study book and this file cannot drift apart.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.md_render import to_pdf  # noqa: E402

SOURCE = ROOT / "Docs/STUDY/03_면접_예상문답.md"
OUTPUT = ROOT / "Docs/STUDY/03_면접_예상문답.pdf"
TITLE = "AI Master 제출 및 면접 준비"
FOOTER = "09285 백준현 · 면접 예상문답"


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    return to_pdf(SOURCE.read_text(encoding="utf-8"), OUTPUT, TITLE, FOOTER)


if __name__ == "__main__":
    out = build()
    print(f"{out.relative_to(ROOT).as_posix()} · {out.stat().st_size:,} bytes")
