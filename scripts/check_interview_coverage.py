"""Check that everything printed on the deck has an answer prepared.

    python scripts/check_interview_coverage.py

The AI interview is built from the submitted deck, so anything on a slide is a
question waiting to happen. This pulls the hooks out of the PPTX itself —
figures with denominators, percentages, the SCREAMING_CASE identifiers, the
technology names, and the cited paper — and reports any that Docs/STUDY's
interview Q&A does not mention. Run it whenever the deck changes.

Exits non-zero when something on a slide has no answer.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "output/02_발표_시연/09285_백준현_최종발표자료.pptx"
ANSWERS = [
    ROOT / "Docs/STUDY/03_면접_예상문답.md",
    ROOT / "Docs/STUDY/06_발표_15분_대본.md",
]

# Terms that appear on slides but are ordinary words in the answers, or are
# covered by a longer phrase that the extractor would double-count.
IGNORE = {
    "AI", "PDF", "DB", "API", "ID", "MTA", "M", "RAG", "LLM",
    "AI Master Project", "MailTaskAgent",
}


def deck_hooks() -> tuple[set[str], set[str], set[str]]:
    from pptx import Presentation

    text = []
    for slide in Presentation(str(DECK)).slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                text.append(shape.text_frame.text)
    body = "\n".join(text)

    # 15/15, 28/28, 8/15 — a figure is useless without its denominator, and the
    # denominator is exactly what gets asked about.
    ratios = set(re.findall(r"\b\d+/\d+\b", body))
    # CREATE_TASK, ASK_USER, STRUCTURED_RAG, WAITING_REPLY
    idents = {w for w in re.findall(r"\b[A-Z][A-Z_]{3,}\b", body)} - IGNORE
    # gpt-4.1-mini, Pydantic, SQLite, Streamlit, LangGraph, Vector DB, Yao
    names = {
        n for n in re.findall(
            r"\b(?:gpt-4\.1-mini|Pydantic|SQLite|Streamlit|LangGraph|Vector DB|"
            r"Gmail API|Tree of Thoughts|Yao|Deliberation|Self-Correction|"
            r"Query Rewrite|Guard|Reply Agent|Context Agent|Mail Analyzer)\b", body)
    } - IGNORE
    return ratios, idents, names


def main() -> int:
    if not DECK.exists():
        print(f"발표자료를 찾지 못했습니다: {DECK}")
        return 2

    answers = "\n".join(p.read_text(encoding="utf-8") for p in ANSWERS if p.exists())
    ratios, idents, names = deck_hooks()

    missing: list[str] = []
    for label, hooks in (("수치", ratios), ("식별자", idents), ("기술·용어", names)):
        gaps = sorted(h for h in hooks if h not in answers)
        covered = len(hooks) - len(gaps)
        print(f"[{label}] {covered}/{len(hooks)} 커버" + (f" · 누락 {gaps}" if gaps else ""))
        missing += gaps

    print()
    if missing:
        print(f"발표자료에 있는데 면접 자료에 없는 항목 {len(missing)}건: {missing}")
        return 1
    print("발표자료의 모든 항목에 답변이 준비되어 있습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
