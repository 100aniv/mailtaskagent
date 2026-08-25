# MailTaskAgent Codex 작업 지침

## 프로젝트 정의

MailTaskAgent는 메일을 단순 요약하는 도구가 아니다. 새 메일, 선행·후행 메일, 현재 Task 상태를 함께 보고 다음 Action을 결정하여 개인 업무의 Lifecycle을 관리하는 Agentic AI 프로젝트다.

```text
Mail -> Mail Analyzer -> Task Matcher -> Action Decision
     -> Validation -> 필요 시 User Review -> Task Update
     -> History -> Streamlit Dashboard
```

최종 Agent Action은 아래 7개로 고정한다.

`CREATE_TASK`, `UPDATE_TASK`, `LINK_TO_TASK`, `SET_WAITING`, `MARK_COMPLETED`, `ASK_USER`, `IGNORE`

## 문서 경계

- `Docs/AI_MASTER/`: AI Master Task 1~4 제출 관점 문서다.
- `Docs/IMPLEMENTATION/`: 멘토 리뷰본, PoC, 최종 E2E의 실제 개발 명세다.
- 제출 문서와 구현 명세를 복제하지 말고 필요한 경우 상대 문서를 링크한다.
- `Docs/AI_MASTER/00_MasterPJT_7기_OT자료공유.pdf`는 교육 원본이므로 수정하지 않는다.

## 현재 구현 Gate

멘토 리뷰용 Vertical Slice를 먼저 완성한다.

1. Streamlit 화면
2. 더미 Mail 2~3건 선택
3. LLM Mail 분석 및 구조화
4. 신규 Mail -> `CREATE_TASK`
5. 후속 Mail -> 기존 Task 검색 -> `UPDATE_TASK`
6. SQLite 저장
7. 현재 Task와 판단 근거 표시
8. 가능하면 불확실한 Mail -> `ASK_USER`

이 Gate가 끝나기 전에는 Gmail/Outlook, n8n, Slack, RAG, LangGraph, FastAPI, PostgreSQL, Calendar, 서버 배포, Repository Pattern을 추가하지 않는다.

## 개발 원칙

- 초기 스택은 Python + LLM Client + Pydantic + SQLite + Streamlit + pytest로 제한한다.
- 실제 메일 대신 합성·비식별 데이터만 사용한다.
- `conversation_id` 등 확정 가능한 Metadata를 먼저 사용하고 의미 판단이 필요할 때만 LLM을 사용한다.
- LLM은 의미 분석과 Action 제안만 담당한다. 실제 DB 변경은 검증된 Application Logic이 수행한다.
- 기한, 담당자, 완료 여부를 근거 없이 추정하지 않는다.
- 중요 변경과 낮은 신뢰도 결과는 `ASK_USER` 또는 승인 대기로 보낸다.
- 모든 변경에 원본 Mail ID, 변경 전·후 값, 판단 근거, 시각을 남긴다.
- API Key와 실제 메일 원문을 저장소·로그에 남기지 않는다.

## 변경 관리

1. 범위 변경은 `Docs/IMPLEMENTATION/01_SCOPE.md`에 먼저 반영한다.
2. State, Action, Node 변경은 `02_NODE_FLOW.md`, `04_FINAL_E2E_SCOPE.md`, `05_TEST_CASES.md`를 함께 갱신한다.
3. PoC와 최종 E2E를 같은 의미로 사용하지 않는다.
4. 기능은 작은 Task로 나누고, 각 단계의 실행·테스트 성공 후 다음 단계로 이동한다.
