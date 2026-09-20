"""Merge the seven submitted Task documents into one book to study from.

    python scripts/build_study_book.py

The submission is seven separate documents because the portal asked for seven.
Read end to end they repeat themselves, jump between heading depths, and never
define their own vocabulary — which is fine for a portal and useless for
revision. This produces one ordered document with a glossary in front, a short
orientation before each chapter, and every number in the project collected at
the back with its denominator.

Chapter bodies are the submitted text, unedited; only heading depth is shifted
so the seven sit at the same level under one table of contents. The mentor
feedback files are deliberately left out: they are comments about the
documents, not statements about the project, and the answers they prompted are
already in the interview guide.

Writes Markdown, then DOCX and PDF through scripts/md_render.py.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.md_render import to_docx, to_pdf  # noqa: E402

SRC = ROOT / "Docs/AI_MASTER"
OUT_DIR = ROOT / "Docs/STUDY"
STEM = "01_MailTaskAgent_프로젝트_통합본"
TITLE = "MailTaskAgent 프로젝트 통합본"
FOOTER = "09285 백준현 · MailTaskAgent 통합본"

CHAPTERS = [
    ("01_역량및기술스택", "내가 가진 역량과 이 프로젝트의 기술 스택",
     "면접에서 '무엇을 할 줄 아느냐'는 질문의 근거가 되는 장이다. 인프라 운영 경력에서 "
     "출발해 이 프로젝트에서 무엇을 직접 했는지가 적혀 있다."),
    ("02_문제정의및서비스기획", "문제 정의와 서비스 기획",
     "**가장 자주 질문받을 장이다.** 누가 어떤 불편을 겪는지, KPI를 무엇으로 잡았는지, "
     "그중 하나는 왜 아직 못 쟀는지가 전부 여기 있다. KPI 표와 그 아래 측정 설계 표는 "
     "그대로 외워도 된다."),
    ("03_시나리오수립", "대표 시나리오",
     "메일 한 통이 실제로 어떻게 업무가 되는지 JSON 입출력까지 붙은 장이다. "
     "`MAIL-001`부터 `MAIL-009`까지 한 Thread가 생성·기한변경·자료요청·완료로 이어진다. "
     "면접에서 '예를 들어 달라'고 하면 여기서 꺼낸다."),
    ("04_상세설계및개발환경", "상세 설계와 개발 환경",
     "가장 긴 장이고 전부 외울 필요는 없다. **맨 앞 3줄 요약, 분기 우선순위 7단계, "
     "기술 선택 표** 세 개만 확실히 알면 설계 질문은 대부분 답한다."),
    ("05_POC모듈구현", "PoC 모듈 구현",
     "무엇을 어떻게 만들었는지. 맨 앞 4칸짜리 대표 시나리오 표가 '입력 → 판단 → Action → "
     "저장'을 한눈에 보여준다. 뒤쪽 '실제로 겪음 / 사전 통제 설계' 구분은 "
     "'실제로 어떤 문제를 겪었나' 질문에 그대로 쓴다."),
    ("06_테스트및고도화", "테스트와 고도화",
     "숫자의 출처가 모여 있는 장이다. 각 수치가 **무엇을 분모로 하는지** 표로 정의돼 있다. "
     "속도 60.852초가 '배치 시간이지 체감 응답시간이 아니다'라는 단서를 놓치면 안 된다."),
    ("07_E2E서비스개발", "E2E 서비스 개발",
     "전체를 이어 붙인 결과와 KPI 달성도. **요구사항 ↔ 본문 ↔ 발표자료 ↔ 시연영상 연결표**가 "
     "여기 있어서, '그건 어디서 확인하냐'는 질문에 슬라이드 번호와 영상 시각으로 답할 수 있다."),
]

HOW_TO_READ = """# 이 문서를 읽는 법

이 책은 AI Master 포털에 Task별로 제출한 일곱 개 문서를 순서대로 합친 것이다. 본문은 제출한
그대로이고, 앞에 **용어 사전**과 장마다 **짧은 안내**를 붙였으며 뒤에 **숫자 사전**을 달았다.

**프로젝트를 처음 본다면 이 순서로 읽는다.**

| 순서 | 무엇을 | 걸리는 시간 |
|---|---|---|
| 1 | 바로 아래 `30초 설명`과 `3분 설명` | 5분 |
| 2 | `용어 사전` — 모르는 단어를 여기서 먼저 없앤다 | 20분 |
| 3 | 2장(문제 정의) → 3장(시나리오) → 5장(구현) | 1시간 |
| 4 | 6장(테스트) → 7장(E2E) — 숫자의 출처를 확인한다 | 40분 |
| 5 | 4장(상세 설계)은 필요할 때만 펼친다 | — |
| 6 | 부록 `숫자 사전`을 소리 내어 외운다 | 20분 |

1장은 자기소개용이라 마지막에 한 번 훑으면 된다.

**멘토 피드백 문서는 넣지 않았다.** 그건 이 문서들에 대한 평가지 프로젝트 설명이 아니고,
거기서 나온 답변은 이미 면접 예상문답에 정리해 뒀다.

## 30초 설명

> MailTaskAgent는 메일로 들어오는 업무 요청을 Task로 만들고, 뒤따라오는 메일에 맞춰 기한·상태를
> 이어서 관리하는 개인 업무관리 Agent다. 같은 Thread는 규칙으로 확정하고, 다른 표현으로 온 후속
> 메일만 SQLite에 쌓인 내 Task·최근 메일·History를 검색해 Agent가 관계와 다음 Action을 제안한다.
> 제안은 그대로 실행되지 않는다. Python Guard가 검증하고, 완료·취소·기한 단축처럼 되돌리기 어려운
> 변경은 신뢰도와 무관하게 사용자 승인을 받는다. 확신이 없으면 조용히 넘어가지 않고 `ASK_USER`로
> 사람에게 올린다.

## 3분 설명

**무엇이 문제였나.** 업무 요청이 메일로 들어온다. 한 업무가 한 통으로 끝나지 않고 기한 변경,
자료 요청, 자료 회신, 완료 통보로 이어진다. 사람이 매번 "이게 새 업무인가, 아까 그 업무의
변경인가"를 판단하고 과거 Thread를 다시 찾아 손으로 반영해야 한다. 놓치면 기한을 넘기고,
잘못 붙이면 엉뚱한 업무가 바뀐다.

**왜 규칙만으로 안 되나.** "월요일까지 주셔도 됩니다"라는 문장 하나로는 새 요청인지 기존 업무의
기한 변경인지 알 수 없다. 메일 문맥과 현재 업무 상태를 함께 봐야 한다. 표현은 매번 다르므로
규칙으로 전부 열거할 수 없다.

**그래서 어떻게 만들었나.** 다섯 단계 Workflow(M-01~M-05)를 실행 뼈대로 고정하고, 그 안에서
규칙으로 확정할 수 없는 판단 하나만 Agent에게 맡겼다. 동일 Thread는 Metadata로 확정하고, 확정이
안 될 때만 SQLite에서 내 활성 Task·최근 메일·History를 top-k로 검색한다. Agent는 관계와 Action
후보를 2~3개 만들고, 별도 평가 단계가 지지도를 매긴다. 상위 둘의 차이가 0.15에 못 미치면 검색어를
한 번 고쳐 다시 찾고, 그래도 갈리면 `ASK_USER`로 끝낸다.

**무엇이 안전장치인가.** LLM은 DB를 직접 바꾸지 않는다. Python Guard가 후보 범위·Intent·상태
전이를 검증하고, Pydantic 계약을 통과한 결과만 하나의 Transaction으로 저장한 뒤 다시 조회해
실제 상태를 확인한다. 완료·취소·기한 단축은 항상 사람이 승인한다.

**무엇을 검증했나.** 정답을 미리 정의한 합성·비식별 메일 15건에서 분류 15/15, 필수 필드 26/26,
Task 연결 8/8, Action 결정 지점 28/28, E2E 15/15. 테스트 Gmail 계정에서 수용시험 20/20과 실제
Thread 5-message E2E. 회귀 테스트 228 passed.

**무엇을 못 했나.** 업무 정리 시간을 실제로 몇 % 줄였는지는 **측정하지 못했다.** 사용자가 한 명이라
같은 사람이 같은 메일을 두 번 처리하게 되고, 두 번째에는 답을 이미 알아서 순서 효과를 걷어낼 수
없었다. 그래서 달성으로 쓰지 않고 미측정으로 남겼다.
"""

GLOSSARY = """# 용어 사전

모르는 단어가 하나라도 있으면 그 문장은 외워도 면접에서 못 쓴다. 여기서 먼저 없앤다.

## 가장 자주 묻는 다섯 단어

| 용어 | 쉬운 뜻 | 이 프로젝트에서는 | 면접에서 주의 |
|---|---|---|---|
| **Workflow** | 정해진 순서대로 도는 처리 절차 | M-01~M-05 다섯 단계와 각 단계의 입출력, 실패 시 멈출 지점이 고정돼 있다 | Agent와 경쟁 관계가 아니라 **실행 뼈대**다. 이게 고정이라 안전성을 테스트로 보장한다 |
| **Agent** | 스스로 판단해 다음 행동을 고르는 주체 | 이 메일이 어느 업무에 속하는지, 어떤 Action을 제안할지를 고른다 | 판단만 한다. **DB 변경 권한은 없다** |
| **Agentic AI** | 판단 → 행동 → 결과 관찰이 이어지는 구조 | 검색·판단·재검색·실행·재조회가 하나로 이어진다 | "전부 AI가 한다"가 아니다. 규칙으로 되는 건 규칙이 하는 **하이브리드**다 |
| **RAG** | 답하기 전에 필요한 자료를 먼저 찾아오는 방식 | SQLite에서 내 활성 Task, 최근 연결 메일 3건, History 5건을 검색한다 | **Vector DB도 외부 문서도 쓰지 않는다.** 그냥 "RAG 썼습니다"라고만 하면 안 된다 |
| **Guard** | 실행 직전에 막아서는 검증 코드 | 후보 범위·Intent·상태 전이·중요 변경을 Python이 검사한다 | LLM이 아니라 **결정론적 Python**이다 |

## 구조와 흐름

| 용어 | 뜻 |
|---|---|
| **M-01 ~ M-05** | 다섯 단계. M-01 의미 구조화 → M-02 Task Context 검색 → M-03 Agent 제안과 Python Guard → M-04 저장·재조회 → M-05 사용자 확인 |
| **Action (7개)** | Agent가 고를 수 있는 다음 행동. `CREATE_TASK`, `UPDATE_TASK`, `LINK_TO_TASK`, `SET_WAITING`, `MARK_COMPLETED`, `ASK_USER`, `IGNORE` |
| **Status (5개)** | 업무의 상태. `TODO`, `IN_PROGRESS`, `WAITING_REPLY`, `COMPLETED`, `CANCELLED` |
| **Intent** | 메일이 무엇을 하려는 것인지. 새 요청인지, 기한 변경인지, 자료 회신인지, 완료 통보인지 |
| **Thread / conversation_id** | 같은 대화에 묶인 메일 묶음과 그 식별자. 이게 일치하면 규칙만으로 업무를 확정한다 |
| **Task Context** | 판단에 필요한 주변 정보. 활성 Task, 그 Task의 최근 메일과 변경 이력 |
| **top-k** | 관련 있어 보이는 후보를 점수 순으로 k개만 가져오는 것. 전부 보지 않는다 |
| **Adapter** | 메일을 가져오는 입구. 지금은 Gmail 읽기 전용. 사내 적용 시 Outlook(Graph)로 **이 부분만** 교체한다 |

## 판단과 안전장치

| 용어 | 뜻 | 왜 중요한가 |
|---|---|---|
| **Structured Output** | 모델 답을 자유 문장이 아니라 정해진 형식(JSON)으로 받는 것 | 형식이 어긋나면 뒤 로직이 아예 안 돌게 만들 수 있다 |
| **Pydantic** | 그 형식을 파이썬에서 검사하는 도구 | 계약 위반을 실행 전에 잡는다 |
| **Schema** | 정해 둔 그 형식 자체 | 필드 이름·타입·필수 여부 |
| **가설(후보)** | Agent가 만든 "이 메일은 이 업무의 이런 변경 같다" 안 | 한 번에 2~3개만 만든다 |
| **지지도** | 평가 단계가 각 후보에 매긴 상대 점수 | **검증된 정확도가 아니다.** 모델이 매긴 값일 뿐 |
| **선택 차이 (selection margin)** | 1등과 2등 지지도의 차 | Python이 계산한다. 0.15 미만이면 확신 없다고 본다 |
| **Query Rewrite** | 검색어를 고쳐 다시 찾는 것 | **최대 1회.** 무한 반복과 비용 증가를 막는다 |
| **Self-Correction** | 결과가 시원찮을 때 스스로 다시 해 보는 것 | 여기서는 재검색 1회로 제한했다 |
| **Fail-closed** | 막히면 실행하지 않고 멈추는 설계 | 반대는 Fail-open(일단 실행). 업무 데이터에는 위험하다 |
| **ASK_USER** | 자동 반영하지 않고 사람에게 올리는 것 | 이 프로젝트의 기본 안전장치 |
| **Human-in-the-loop** | 중간에 사람이 개입하는 구조 | 완료·취소·기한 단축은 신뢰도와 무관하게 항상 승인 |
| **Prompt Injection** | 메일 본문에 "이전 지시는 무시하고 ~하라" 같은 명령을 심는 공격 | 본문의 명령을 **데이터로만** 다루고 실행하지 않는다 |
| **Idempotency (중복 방지)** | 같은 입력을 두 번 넣어도 결과가 한 번과 같은 성질 | 같은 `mail_id`는 LLM을 다시 부르지 않고 기존 결과를 돌려준다 |

## 저장과 운영

| 용어 | 뜻 |
|---|---|
| **SQLite** | 파일 하나로 끝나는 가벼운 데이터베이스. 개인용 PoC에 맞다 |
| **Transaction** | 여러 변경을 전부 성공하거나 전부 취소하는 묶음. 반쯤 저장되는 사고를 막는다 |
| **WAL / Busy Timeout** | SQLite에서 읽기와 쓰기가 부딪히지 않게 하는 설정과, 잠겨 있을 때 기다리는 시간(30초) |
| **History** | 업무가 어떻게 바뀌었는지의 기록. 변경 전·후 값과 판단 근거가 남는다 |
| **Processing Event** | 처리 단계별 기록. 어느 단계에서 얼마나 걸렸고 어디서 실패했는지 |
| **Allowlist** | 메일을 보내도 되는 수신자 목록. 여기 없으면 발송하지 않는다 |
| **OAuth / Scope** | 계정 접근 권한과 그 범위. 읽기용과 발송용 토큰을 분리했다 |
| **Streamlit** | 파이썬만으로 화면을 만드는 도구. Dashboard가 이걸로 돼 있다 |

## 검증 용어

| 용어 | 뜻 | 이 프로젝트에서 |
|---|---|---|
| **Ground Truth (정답셋)** | 미리 정해 둔 정답 | 15 Case의 기대 Action·상태·필드를 구현 **전에** 확정했다 |
| **E2E** | 처음부터 끝까지 한 번에 도는 검증 | 메일 입력부터 화면 반영까지 |
| **회귀 테스트** | 예전에 되던 게 여전히 되는지 자동 확인 | `pytest 228 passed` |
| **Mock / Live** | 가짜 모델로 도는 것 / 실제 회사 LLM으로 도는 것 | Mock은 어휘 겹침만 봐서 판단 차이가 안 드러난다 |
| **KPI** | 목표를 수치로 잰 지표 | 다섯 개는 달성, 시간 단축 하나는 미측정 |
| **Baseline** | 비교 기준이 되는 이전 값 | 시간 KPI는 이게 **없다.** 그래서 못 쟀다 |

## 쓰면 안 되는 말

| 틀린 말 | 맞는 말 |
|---|---|
| "Tree of Thoughts를 구현했다" | 후보 생성과 평가를 나눈다는 **아이디어만 참고**했다. 트리도 백트래킹도 없다 |
| "Full ReAct Agent다" | 재검색을 1회로 **제한한** Self-Correction이다 |
| "Vector DB로 RAG를 했다" | Vector DB와 Embedding은 안 썼다. SQLite 검색이다 |
| "정확도 100%다" | **정의된 합성 15 Case에서** 100%다 |
| "업무 시간을 주 1.2~2.8시간 줄였다" | 그건 외부 통계로 계산한 잠재치지 실측이 아니다 |
| "신뢰도 1.0이니 정확하다" | 신뢰도는 모델의 자기보고지 검증된 확률이 아니다 |
"""

NUMBERS = """# 부록 A. 숫자 사전

**분모 없이 말하면 반드시 되물음이 온다.** 숫자를 말할 때는 오른쪽 칸을 같이 말한다.

## 검증 수치

| 숫자 | 무엇 | 분모와 범위 |
|---|---|---|
| **228 passed** | 저장소 전체 자동 회귀 테스트 | 코드 계약과 회귀 범위. 이전 기준선은 171 → 179 |
| **15/15** | 분류 정확도이자 E2E 성공률 | 정의된 합성·비식별 메일 15건의 처리 실행 단위, 회사 LLM Live 1회 |
| **26/26** | 요청사항·기한 등 필수 필드 추출 | 같은 15 Case가 가진 필수 필드 26개 |
| **8/8** | 신규/기존 Task 연결 | 같은 15 Case 중 **정답 Task가 하나로 확정되는** 8개 단계만 분모 |
| **28/28** | Action 단계 일치율 | 같은 15 Case가 거치는 Action 결정 지점 28개 |
| **20/20** | 테스트 Gmail 수용시험 | 별도 테스트 계정의 비식별 합성 메일 20건 |
| **3/3** | Task Context Agent Live | 다른 Thread·다른 표현의 관계 판단 전용 합성 Case |
| **3/3 · 1/1** | Reply Planning · 사용자 입력 기반 Draft | 회신 방식 판단 3건, 초안 생성 1건 |
| **33/33 → 35/35** | 이미 처리한 메일의 중복 재조회 차단 | 실제 Gmail. 새 root 메일 자동 생성 검증 후 분모가 늘었다 |

> **다섯 개 정확도 수치는 서로 다른 다섯 번의 실험이 아니다.** 같은 15 Case 한 번의 실행을 다섯
> 각도로 본 값이다. 분모를 합쳐 읽거나 달성률을 100% 초과로 환산하지 않는다.

## 동작 수치

| 숫자 | 무엇 | 주의 |
|---|---|---|
| **60.852초** (이전 76.554초) | 15 Case 평가 Suite를 처음부터 끝까지 한 번 도는 **배치** 시간 | 사용자 체감 응답시간이 아니다. 메일 1건 기준 약 5.1초 → 4.1초 |
| **8/15 자동 (53.3%)** · **7/15 확인 (46.7%)** | 자동 반영과 사용자 확인 비율 | 확인이 많은 건 성능이 아니라 **승인 Gate 정책** 때문 |
| **후보 2~3개** | 한 번에 만드는 가설 수 | 트리로 펼치지 않는다 |
| **0.15** | 선택 차이 기준. 미만이면 확신 없다고 본다 | Python이 계산한다 |
| **최대 1회** | Query Rewrite 재검색 횟수 | 두 번째도 불확실하면 `ASK_USER`로 종료 |
| **7 Action / 5 Status** | 고를 수 있는 행동과 업무 상태의 개수 | 고정이다. 그래서 테스트로 묶을 수 있다 |

## 목표선과 미측정

| 항목 | 목표 | 결과 |
|---|---|---|
| 분류 정확도 / 필드 추출 / E2E 성공률 | 90% 이상 | 100% |
| Task 연결 / Action 일치율 | 85% 이상 | 100% |
| **업무 정리 소요시간** | 기존 대비 30% 이상 단축 | **미측정** — 비교할 Baseline이 없다 |

> 08 최종 산출물 문서에 달성률이 **111% / 118%** 로 적혀 있다. 이건 목표 90%·85% 대비 100%를
> 환산한 값이지 성능이 111%라는 뜻이 아니다. 물어보면 이렇게 정정한다.

## 제출물

| 항목 | 값 |
|---|---|
| 발표자료 | 표지 + 3장, 총 4쪽 PDF |
| 시연영상 | 2분 38.6초 · 7.34MB · 1600×900 (기준 5분·500MB 이하) |
| 발표 시간 | 10분 이내. 대사 실측 3,814자 기준 약 9.1~11.2분 |
"""


def shift_headings(text: str) -> str:
    """Put every chapter's shallowest heading at level 3, keeping relative depth."""
    levels = [len(m) for m in re.findall(r"^(#{1,6}) ", text, re.M)]
    if not levels:
        return text
    delta = 3 - min(levels)
    if delta == 0:
        return text

    def fix(m: re.Match) -> str:
        level = min(len(m.group(1)) + delta, 6)
        return "#" * level + " "

    return re.sub(r"^(#{1,6}) ", fix, text, flags=re.M)


def build() -> tuple[Path, Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parts = [f"{HOW_TO_READ}\n\n{GLOSSARY}\n"]

    toc = ["# 본문 — 제출한 일곱 개 문서", "",
           "아래 일곱 장은 AI Master 포털에 제출한 원문 그대로다. 장 제목 아래 회색 안내만 새로 붙였다.",
           "", "| 장 | 내용 | 먼저 볼 것 |", "|---|---|---|"]
    priority = {"02": "★ 1순위", "03": "★ 1순위", "05": "★ 1순위",
                "06": "2순위", "07": "2순위", "04": "필요할 때", "01": "마지막"}
    for name, title, _ in CHAPTERS:
        num = name[:2]
        toc.append(f"| {int(num)}장 | {title} | {priority[num]} |")
    parts.append("\n".join(toc) + "\n")

    for index, (name, title, note) in enumerate(CHAPTERS, start=1):
        body = (SRC / f"{name}.md").read_text(encoding="utf-8").strip()
        parts.append(f"## {index}장. {title}\n\n> **이 장은** {note}\n\n{shift_headings(body)}\n")

    parts.append(NUMBERS)

    md = "\n\n".join(parts).replace("\r\n", "\n").rstrip() + "\n"
    md_path = OUT_DIR / f"{STEM}.md"
    md_path.write_text(md, encoding="utf-8")

    docx_path = to_docx(md, OUT_DIR / f"{STEM}.docx", TITLE)
    pdf_path = to_pdf(md, OUT_DIR / f"{STEM}.pdf", TITLE, FOOTER)
    return md_path, docx_path, pdf_path


if __name__ == "__main__":
    for p in build():
        print(f"{p.relative_to(ROOT).as_posix()} · {p.stat().st_size:,} bytes")
