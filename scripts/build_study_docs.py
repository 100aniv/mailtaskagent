"""Render the Markdown study documents in Docs/STUDY into DOCX and PDF.

    python scripts/build_study_docs.py

Replaces the per-file builder that existed for the interview Q&A; the layout
itself lives in md_render. Both formats are produced for each document — the
PDF to print and the DOCX to mark up while rehearsing. The merged book has its
own script because it is assembled from the seven Task documents first.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.md_render import to_docx, to_pdf  # noqa: E402

STUDY = ROOT / "Docs/STUDY"

DOCUMENTS = [
    ("03_면접_예상문답", "AI Master 제출 및 면접 준비", "09285 백준현 · 면접 예상문답"),
    ("06_발표_15분_대본", "최종발표 15분 대본", "09285 백준현 · 발표 15분 대본"),
]


def build() -> list[Path]:
    made = []
    for stem, title, footer in DOCUMENTS:
        md = (STUDY / f"{stem}.md").read_text(encoding="utf-8")
        made.append(to_docx(md, STUDY / f"{stem}.docx", title))
        made.append(to_pdf(md, STUDY / f"{stem}.pdf", title, footer))
    return made


if __name__ == "__main__":
    for path in build():
        print(f"{path.relative_to(ROOT).as_posix()} · {path.stat().st_size:,} bytes")
