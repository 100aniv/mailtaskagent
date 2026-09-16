"""Fill the official AI Master template with this project's content.

    python scripts/build_architecture_diagram.py
    python scripts/build_template_deck.py

This is an alternative to Docs/PRESENTATION/build_final_deck.mjs, not a
replacement. The self-designed deck says the same things on a 1280x720 canvas
of its own; this one keeps the official 720x405 template's layout, colours and
section order and drops the content into its placeholders, for the case where
the reviewer expects the supplied template.

Every run is replaced by position rather than by matching its placeholder text,
so a template whose wording differs fails loudly instead of silently keeping
the example text. Speaker notes are carried over from the other deck's script.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from pptx import Presentation
from pptx.util import Pt

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "Docs/USER_GUIDE/REFERENCE/official_guides/AI_Master_Project_최종발표_멘티명_사번.pptx"
DIAGRAM = ROOT / "tmp/template-deck/architecture.png"
OUTPUT = ROOT / "Docs/PRESENTATION/2. 최종/09285_백준현_AI_Master_최종발표자료_공식템플릿_v1.pptx"

MENTEE = "백준현, 09285"
MENTOR = "이유경"
TITLE = "MailTaskAgent · 메일 기반 개인 업무관리 Agent"


def set_run(shape, paragraph_index: int, run_index: int, text: str) -> None:
    """Replace one run's text, keeping its formatting."""
    paragraph = shape.text_frame.paragraphs[paragraph_index]
    run = paragraph.runs[run_index]
    run.text = text


def clear_runs(shape, paragraph_index: int, keep: int = 0) -> None:
    """Empty every run in a paragraph past the first `keep` of them."""
    for run in shape.text_frame.paragraphs[paragraph_index].runs[keep:]:
        run.text = ""


def append_paragraph_like(shape, source_index: int, text: str):
    """Add a paragraph that copies an existing one's formatting.

    The template's boxes have no spare paragraphs, so a field it does not ask
    for — the Next Step the 성장 가능성 lens wants — needs a new one that still
    looks like the rest of the box.
    """
    body = shape.text_frame._txBody
    source = shape.text_frame.paragraphs[source_index]._p
    clone = copy.deepcopy(source)
    body.append(clone)
    paragraph = shape.text_frame.paragraphs[-1]
    for run in paragraph.runs[1:]:
        run._r.getparent().remove(run._r)
    if paragraph.runs:
        paragraph.runs[0].text = text
    elif text:
        raise ValueError(f"빈 문단을 복제해 텍스트를 넣을 수 없습니다: {text[:20]}")
    return paragraph


def shape_by_name(slide, name: str):
    for shape in slide.shapes:
        if shape.name == name:
            return shape
    raise KeyError(f"템플릿에 도형이 없습니다: {name}")


def group_shape_by_name(group, name: str):
    for shape in group.shapes:
        if shape.name == name:
            return shape
    raise KeyError(f"그룹에 도형이 없습니다: {name}")


def fit(shape, size_pt: float) -> None:
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            run.font.size = Pt(size_pt)


def build_cover(slide) -> None:
    # The template ships with the 3기 cohort baked in; this project is 7기.
    set_run(shape_by_name(slide, "Text 1"), 0, 0, "AI Master Project 7기")
    set_run(shape_by_name(slide, "Text 4"), 0, 1, TITLE)
    fit(shape_by_name(slide, "Text 4"), 10)
    set_run(shape_by_name(slide, "Text 5"), 0, 1, MENTEE)
    set_run(shape_by_name(slide, "Text 6"), 0, 1, MENTOR)


def build_overview(slide) -> None:
    problem = shape_by_name(slide, "Text 10")
    set_run(problem, 0, 0, "어떤 문제를 해결하고자 했는가?")
    set_run(
        problem, 1, 0,
        "같은 업무 요청이 여러 메일과 Thread에 흩어져 도착합니다. 무엇이 새 업무이고 무엇이 "
        "기존 업무의 변경인지 사람이 매번 과거 메일을 다시 찾아 판단해야 합니다.",
    )
    set_run(problem, 3, 0, "왜 이 문제가 중요한가? (비즈니스 임팩트)")
    set_run(
        problem, 4, 0,
        "놓치면 기한을 넘기고, 잘못 붙이면 엉뚱한 업무의 상태가 바뀝니다. 개인의 활성 업무가 "
        "수십 건이면 이 판단만으로 하루에 수십 번 문맥을 바꿔야 합니다.",
    )

    features = shape_by_name(slide, "Text 14")
    set_run(features, 0, 0, "무엇을 만들었는가?")
    set_run(
        features, 1, 0,
        "메일을 Task로 만들고 기존 업무와 연결한 뒤 다음 Action까지 제안하는 단일 Agent "
        "시스템입니다. 위험한 변경은 사용자 확인으로 넘깁니다.",
    )
    set_run(features, 3, 0, "에이전트")
    set_run(features, 3, 1, " 구성:")
    set_run(
        features, 4, 0,
        "Mail Analyzer [의미·Intent 구조화]  →  Context Agent [가설 생성]  →  "
        "Context Agent [가설 평가]  →  Python Guard [안전 검증]  →  Reply Agent [회신·승인 발송]",
    )
    set_run(features, 7, 0, "핵심")
    set_run(features, 7, 1, " 기술 스택:")
    set_run(
        features, 8, 0,
        "회사 gpt-4.1-mini / SQLite Task Context RAG / Python + Pydantic Guard / "
        "Gmail API / Streamlit",
    )

    achievements = [
        (
            "Text 17",
            "28/28",
            "Action 단계 정확도 (회사 LLM Live 15 Case, 정량적 지표)",
        ),
        (
            "Text 19",
            "15/15",
            "시나리오 통과 (같은 15 Case, 정량적 지표)",
        ),
        (
            "Text 21",
            "53.3%",
            "자동 반영 8/15. 나머지 7/15(46.7%)는 Guard가 사용자 확인으로 이관. 정의된 합성 15 Case "
            "기준이며 Mailbox 전체 자동화율이 아닙니다. 사용자 체감 시간은 사용자가 1명이라 순서 효과를 "
            "걷어낼 수 없어 미측정으로 남겼습니다.",
        ),
    ]
    for name, value, caption in achievements:
        shape = shape_by_name(slide, name)
        set_run(shape, 0, 0, value)
        set_run(shape, 1, 0, caption)
        clear_runs(shape, 1, keep=1)

    key = shape_by_name(slide, "Text 24")
    set_run(
        key, 0, 0,
        "\"규칙으로 열거할 수 없는 '이 메일이 어느 업무인가'만 Agent가 판단하고,",
    )
    set_run(key, 1, 0, "실행 권한은 Python Guard와 사용자가 가집니다.\"")


def build_architecture(slide) -> None:
    box = shape_by_name(slide, "Text 8")
    for paragraph in box.text_frame.paragraphs:
        for run in paragraph.runs:
            run.text = ""

    picture = slide.shapes.add_picture(
        str(DIAGRAM), Pt(30), Pt(63), width=Pt(344), height=Pt(316),
    )
    # The placeholder frame must stay on top of nothing, but the picture must sit
    # inside the card rather than over the header, so drop it just above the card.
    slide.shapes._spTree.remove(picture._element)
    card = shape_by_name(slide, "Shape 7")
    card._element.addnext(picture._element)

    heading = shape_by_name(slide, "Text 9")
    set_run(heading, 0, 0, "기술 아키텍처 고려 사항  ")
    set_run(heading, 0, 1, "왜 이 선택이었는지를 중심으로 설명합니다")

    # The card body is 286x62pt at 8pt, which the template itself fills with two
    # lines of 선택 이유 and one of the second field — roughly 35 characters a line.
    choices = [
        (
            "Text 14", "Text 15",
            "회사 gpt-4.1-mini + Pydantic Schema",
            "선택 이유:",
            "메일 의미와 Task 관계는 규칙으로 열거할 수 없지만, 출력은 고정 Schema여야 합니다. "
            "사내 승인 모델이라 외부 반출이 없습니다.",
            " 활용:",
            "관계·Action을 계약으로 받고 위반은 재시도로 재생성.",
        ),
        (
            "Text 20", "Text 21",
            "SQLite Task Context RAG",
            "선택 이유:",
            "찾을 대상이 외부 문서가 아니라 내 활성 Task·최근 Mail·History·과거 사용자 결정입니다. "
            "Vector DB 구성 비용이 더 컸습니다.",
            " 성과:",
            "제한 top-k 검색으로 Live 15 Case Action 28/28.",
        ),
        (
            "Text 26", "Text 27",
            "Python + Pydantic Safety Guard",
            "선택 이유:",
            "LLM이 DB를 직접 바꾸면 틀렸을 때 비용이 업무 데이터 오변경입니다. "
            "상태가 닫혀 있어 LangGraph 없이 충분했습니다.",
            " 포인트:",
            "후보 범위·Intent·상태 전이 검증, 완료·취소는 승인.",
        ),
    ]
    for title_name, body_name, tech, why_label, why, how_label, how in choices:
        set_run(shape_by_name(slide, title_name), 0, 0, tech)
        body = shape_by_name(slide, body_name)
        set_run(body, 0, 0, why_label)
        set_run(body, 1, 0, why)
        set_run(body, 3, 1, how_label)
        set_run(body, 4, 0, how)


def build_hurdle(slide) -> None:
    hurdle = shape_by_name(slide, "Text 9")
    set_run(
        hurdle, 0, 0,
        "이미 Agent를 쓰고 있었지만, 그 Agent가 관계 하나·대상 하나·Action 하나에 설명 한 줄만 돌려줬습니다.",
    )
    set_run(
        hurdle, 1, 0,
        "모델이 실제로 후보를 견주고 골랐는지, 결론을 먼저 정하고 그럴듯한 설명을 붙였는지 밖에서 구분할 "
        "방법이 없었습니다. 멘토 피드백도 매번 \"Rule Base처럼 보인다\"였습니다.",
    )

    approach = shape_by_name(slide, "Text 13")
    set_run(approach, 0, 0, "어떻게 해결했는가? (설계 결정)")
    set_run(
        approach, 1, 0,
        "가설 생성과 평가를 서로 다른 LLM 호출로 분리했습니다. 생성 단계는 후보 2~3개를 근거와 함께 내고 "
        "점수를 매기지 않고, Python이 후보 ID와 관계 계약을 검증한 뒤, 평가 단계가 지지도를 매겨 하나를 "
        "고릅니다. 상위 두 지지도의 차이는 Python이 계산합니다.",
    )
    set_run(approach, 3, 0, "핵심")
    set_run(approach, 3, 1, " 알고리즘 / 아키텍처 결정")
    set_run(
        approach, 4, 0,
        "Bounded Multi-Hypothesis Deliberation — Tree of Thoughts(Yao et al., NeurIPS 2023)의 후보 "
        "생성·평가 분리를 참고하되 후보 2~3개·평가 1회로 제한했습니다. Full Tree of Thoughts 구현이 "
        "아닙니다. 그 판단을 SQLite Task Context RAG와 제한적 ReAct-style Self-Correction이 "
        "Observe → Retrieve → Reason → Act → Observe로 감쌉니다.",
    )
    set_run(approach, 6, 0, "왜 이 접근이 필요했는가?")
    set_run(
        approach, 7, 0,
        "메일 한 건을 업무로 옮기는 판단은 단계가 깊지 않은 대신 틀렸을 때 비용이 업무 데이터 오변경입니다. "
        "그래서 넓게 펼치는 대신 후보를 제한하고, 결정론 Guard와 사용자 승인으로 막았습니다.",
    )

    # p5 is the template's own blank spacer between fields.
    append_paragraph_like(approach, 5, "")
    append_paragraph_like(approach, 6, "다음 단계 (Next Step)")
    append_paragraph_like(
        approach, 7,
        "Gmail 검증 결과를 바탕으로 Outlook Graph Adapter와 사내 인증·운영 서버로 전환하고, "
        "검색을 어휘 겹침 너머로 넓히는 것이 다음 과제입니다.",
    )

    group = next(shape for shape in slide.shapes if shape.shape_type == 6)
    results = [
        ("Text 18", "Text 20", "100%",
         "Action 단계 정확도",
         "회사 LLM Live 15 Case에서 28/28. 숙고 On·Off 동일하며 소요시간만 약 30% 증가"),
        ("Text 22", "Text 24", "3/3",
         "재현되는 개선 1건",
         "유사 Task 2건 구분 Case에서 숙고 On은 3회 모두 사용자 확인, Off는 3회 모두 오연결"),
        ("Text 26", "Text 28", "0건",
         "계약 위반 판단 유실",
         "검증을 재시도 루프 밖에 두어 실제 Gmail 35건 재생에서 4건 유실 → 루프 안으로 옮겨 0건"),
    ]
    for value_name, caption_name, value, headline, detail in results:
        set_run(group_shape_by_name(group, value_name), 0, 0, value)
        caption = group_shape_by_name(group, caption_name)
        set_run(caption, 0, 0, headline)
        set_run(caption, 1, 0, detail)


NOTES = {
    1: (
        "[시간 배분] 문제·기능 2분, 아키텍처 3분, 핵심 과제 4분으로 약 9분이다. "
        "10분 제한에 1분 여유를 남긴 배분이므로 슬라이드를 넘기기 전에 시간을 확인한다."
    ),
    2: (
        "문제부터 말씀드리겠습니다. 하나의 업무가 여러 메일과 여러 Thread에 흩어져 도착하고, 기한 변경이나 "
        "자료 회신 같은 후속 메일은 표현이 매번 달라집니다. 그래서 사용자는 메일이 올 때마다 과거 메일을 "
        "다시 찾아, 이게 새 업무인지 기존 업무의 변경인지 직접 판단해야 합니다. 놓치면 기한을 넘기고, 잘못 "
        "붙이면 엉뚱한 업무의 상태가 바뀝니다. 제가 풀려는 것은 이 판단입니다.\n\n"
        "가운데 다섯 역할이 실제로 도는 순서입니다. 메일 분석기가 의미와 의도를 구조화하고, 컨텍스트 "
        "에이전트가 관계와 대상, 행동 후보를 두세 개 만듭니다. 같은 에이전트를 한 번 더 부르는데 이번엔 "
        "평가만 시킵니다. 만드는 호출과 고르는 호출이 다릅니다. 그다음 파이썬 가드가 후보와 상태 전이, "
        "중요 변경을 검증하고 기준에 못 미치면 사용자 확인으로 넘깁니다. 마지막이 회신 에이전트입니다.\n\n"
        "오른쪽 수치는 분모가 서로 다르니 합쳐 읽지 말아 주십시오. 28/28과 15/15는 회사 LLM Live 15개 "
        "Case의 결과이고, 53.3퍼센트도 같은 15개 Case에서 자동 반영된 비율입니다. 회사 메일함 전체 "
        "자동화율이 아닙니다. 사용자 체감 시간은 신뢰할 Baseline을 얻지 못해 추정치 대신 미측정으로 "
        "남겼습니다. 사용자가 저 한 명이라 순서 효과를 걷어낼 방법이 없었습니다."
    ),
    3: (
        "왼쪽 그림이 실제로 도는 흐름입니다. 위에서 아래로 한 번 지나가는 직선이 아니라 화살표가 두 번 "
        "되돌아옵니다. 보라색은 셀프 커렉션이고, 청록색은 실행 결과를 다시 읽는 관찰입니다.\n\n"
        "엠 영이가 이 프로젝트의 알에이지입니다. 외부 문서를 찾는 지식 알에이지가 아니라, 판단에 필요한 과거 "
        "업무 맥락을 제 에스큐엘라이트에서 찾아오는 태스크 컨텍스트 알에이지입니다. 활성 업무 다섯 건, 각 "
        "업무의 최근 메일 세 건과 변경 이력 다섯 건, 사용자가 과거에 확정한 결정을 함께 가져옵니다. 지난 "
        "결정이 다음 판단의 근거로 다시 들어갑니다.\n\n"
        "네 용어의 역할이 다릅니다. 알에이지는 맥락을 가져오는 단계, 리액트는 그 맥락을 관찰해 행동을 정하고 "
        "실행 결과를 다시 관찰하는 바깥 루프, 셀프 커렉션은 그 루프 안에서 확신이 부족할 때 검색어를 바꿔 한 "
        "번 다시 찾고 다시 판단하는 부분입니다. 파이썬 가드는 에이전트의 판단을 대신하는 자리가 아니라 그 "
        "판단을 실행해도 되는지 확인하는 경계입니다.\n\n"
        "오른쪽 기술 선택 세 가지입니다. 벡터 디비를 쓰지 않은 이유는 개인의 활성 업무가 수십 건 규모라 "
        "조회만으로 충분했고 구성요소를 늘리는 비용이 더 컸기 때문입니다. 대신 검색이 어휘 겹침에 의존한다는 "
        "한계가 남습니다. 랭그래프도 쓰지 않았습니다. 에이전트가 하나이고 상태가 태스크 다섯 개와 행동 일곱 "
        "개로 닫혀 있어 파이썬 상태와 가드만으로 검증이 더 쉬웠습니다. 분기와 중단, 재개가 복잡해지는 시점에 "
        "다시 검토하겠습니다."
    ),
    4: (
        "이 슬라이드의 난제부터 말씀드리겠습니다. 저는 이미 Agent를 쓰고 있었는데, 그 Agent가 결론을 하나만 "
        "돌려줬습니다. 이러면 모델이 후보를 실제로 견줬는지, 결론을 먼저 정하고 설명을 붙였는지 밖에서 구분할 "
        "방법이 없습니다. 막힌 곳은 판단의 품질이 아니라 검증 가능성이었습니다.\n\n"
        "숙고와 리액트의 관계를 먼저 정리하겠습니다. 숙고는 한 번의 판단 안에서 후보를 견주는 안쪽 단계이고, "
        "리액트는 그 판단을 검색과 실행, 재관찰로 감싸는 바깥 루프입니다. 숙고가 리액트를 대체한 것이 아니라 "
        "리액트의 판단 단계를 두 호출로 쪼갠 것입니다. 트리 오브 소트를 구현한 것이 아니라 후보 생성과 평가를 "
        "분리한다는 아이디어만 참고했습니다.\n\n"
        "효과는 같은 코드에서 기능만 껐다 켜서 측정했습니다. 기존 열다섯 개 Case는 양쪽이 똑같이 15/15, "
        "Action 28/28이고 소요시간만 약 삼십 퍼센트 늘었습니다. 숙고가 실제 발동하는 전용 네 개 케이스는 "
        "회차마다 출력이 달라져 각 설정을 세 번씩 돌렸고, 세 번 모두 재현되는 차이는 한 건입니다. 요청자가 "
        "같고 대상 시스템만 다른 유사 업무가 둘 있을 때, 단일 결론 경로는 세 번 모두 둘 중 하나에 그대로 "
        "연결했고 두 단계 경로는 세 번 모두 사용자 확인으로 닫았습니다. 제가 개선했다고 말하는 범위는 이 한 "
        "건입니다.\n\n"
        "실패도 말씀드리겠습니다. 응답 검증을 재시도 루프 밖에 두어서, 모델이 필드 하나를 배열로 돌려준 "
        "것만으로 판단 전체가 실패했습니다. 저장해 둔 실제 지메일 서른다섯 건을 다시 흘려보냈을 때 판단 네 "
        "건이 사라졌고, 합성 테스트가 아니라 실제 데이터 재생에서 잡혔습니다. 검증을 루프 안으로 옮긴 뒤 "
        "유실은 0건입니다.\n\n"
        "남은 한계도 말씀드리겠습니다. 화면의 신뢰도와 지지도는 모델의 자기보고 값이지 검증된 정답 확률이 "
        "아닙니다. 다음 단계는 Gmail 검증 결과를 바탕으로 Outlook Graph Adapter와 사내 인증·운영 서버로 "
        "전환하는 것입니다."
    ),
}


def main() -> None:
    if not DIAGRAM.exists():
        raise SystemExit("먼저 scripts/build_architecture_diagram.py를 실행하세요.")

    prs = Presentation(str(TEMPLATE))
    slides = list(prs.slides)
    if len(slides) != 4:
        raise SystemExit(f"템플릿 슬라이드가 4장이 아닙니다: {len(slides)}")

    build_cover(slides[0])
    build_overview(slides[1])
    build_architecture(slides[2])
    build_hurdle(slides[3])

    for index, slide in enumerate(slides, start=1):
        slide.notes_slide.notes_text_frame.text = NOTES[index]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUTPUT))

    spoken = sum(len(text) for text in NOTES.values())
    print(f"{OUTPUT.relative_to(ROOT).as_posix()}")
    print(f"  슬라이드 {len(slides)}장 · 발표자 노트 {spoken:,}자 "
          f"(분당 340~420자 기준 {spoken / 420:.1f}~{spoken / 340:.1f}분)")


if __name__ == "__main__":
    main()
