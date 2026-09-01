### 핵심 구현 내용

이번 PoC 단계에서 실제 코드로 구현된 핵심 기능들을 **동작 원리**와 **사용 기술** 중심으로 상세히 기술합니다.

**1.1 에이전트 워크플로우 (Agent Workflow)**

* **구현 기능:** 합성 Mail 입력부터 의미 분석, Task 후보 검색, 7개 Action 결정, Validation, 사용자 확인, Task·History 저장까지 연결한 단일 Agent Workflow

* **동작 원리:** M-01이 회사 LLM API로 Mail Intent와 요청사항·기한을 구조화하고, M-02가 `conversation_id`와 제목·요청자·요약을 이용해 기존 Task 후보를 찾습니다. M-03의 Python Application Logic이 현재 Task 상태와 후보 수를 바탕으로 `CREATE_TASK`, `UPDATE_TASK`, `LINK_TO_TASK`, `SET_WAITING`, `MARK_COMPLETED`, `ASK_USER`, `IGNORE` 중 하나를 결정합니다. Pydantic Validation을 통과한 결과만 M-04가 SQLite에 반영하며, 중요하거나 불명확한 변경은 M-05 사용자 확인 이후 반영합니다. Streamlit 첫 화면에서는 실제 업무 모드와 MVP 시연 모드를 선택하고, 동일 Agent Core를 공유하되 실제 업무 DB와 시연 DB를 분리합니다.

* **주요 기술:** Python 3.12.13 로컬 실행 환경, OpenAI Python SDK의 `AzureOpenAI` 호환 Client, 회사 LLM `gpt-4.1-mini`, Pydantic, SQLite, Streamlit

**1.2 도구(Tool) 및 함수 연동**

* **구현 기능:** Mail 분석, 중복 확인, Task 후보 검색, Action 실행, 사용자 검토, 품질평가 함수와 읽기 전용 Gmail Input Adapter 연동

* **동작 원리:** `MailTaskWorkflow.process()`가 처리 순서를 관리합니다. `MailAnalyzer.analyze()`의 구조화 결과를 Pydantic으로 검증하고, `SQLiteStorage.search_candidate_tasks()`가 동일 Thread 우선 후보와 매칭 점수·근거를 반환합니다. `decide_action()`이 Action을 제안하며 `SQLiteStorage.apply()`가 하나의 Transaction 안에서 Task·Link·History를 저장합니다. `resolve_review()`는 사용자가 확정한 결과만 반영하고, `run_scenario_evaluation()`은 각 Case를 격리 DB에서 재현해 기대값과 비교합니다. `GmailReadOnlySource.load()`는 제한 Label의 신규 Gmail과 Task DB에 연결된 정확한 Thread의 수신·발신 후속 Mail을 기존 `MailInput`으로 정규화합니다. 실제 OAuth 연결 후 별도 테스트 계정의 비식별 합성 Mail 20건을 회사 LLM Live로 처리해 20/20 수용시험과 재조회 중복 차단·실패 0건을 확인했습니다.

* **주요 기술:** Python 함수 기반 Orchestration, Pydantic Schema Validation, SQLite Transaction, Streamlit Form·Session State, pytest Parameterized Test, 선택적 Google Gmail API Python Client와 `gmail.readonly` OAuth Scope

**1.3 데이터 및 메모리 (RAG & Context)**

* **구현 기능:** Mail, Task, Mail–Task Link, Processing Result, Task History, Processing Event를 SQLite에 구조화하여 저장

* **동작 원리:** 한 건의 Mail을 처리하는 동안 동일 Thread의 선행 Mail, Mail 분석 결과, 후보 Task, 선택 Task의 최근 History, Action 제안, Validation과 실행 결과를 Pydantic 객체로 유지합니다. 처리가 끝나면 Task 현재 상태, 원본 Mail ID, 변경 전·후 값, 판단 근거, 신뢰도, 사용자 결정을 SQLite에 저장하고 다음 Mail 처리 시 필요한 Context만 다시 조회합니다. 동일 `mail_id`는 기존 결과를 반환하여 LLM과 DB 변경을 재실행하지 않습니다.

* **주요 기술:** SQLite, Pydantic State Model, `conversation_id` Metadata 우선 검색, 설명 가능한 Token 기반 후보 점수. 현재 시연 기준선에는 RAG·Embedding·Vector DB를 사용하지 않았습니다. 멘토 피드백에 따라 최종 MVP에는 SQLite Task·Mail·History를 검색 Source로 쓰는 경량 Task Context Agentic RAG를 추가할 예정이며, 사내 문서검색 RAG·Embedding·Vector DB는 Post-MVP로 유지합니다.

* **최종 MVP 잔여 구현:** 동일 Thread로 확정할 수 없는 경우 top-k Task Context를 검색하고,
  별도 Task Context Agent가 `SAME_TASK`, `NEW_TASK`, `AMBIGUOUS` 관계와 7개 Action 중 제안값을
  구조화합니다. 첫 판단이 모호하거나 저신뢰면 Query를 최대 1회 재작성·재검색하고, 재판단도
  불확실하거나 API·Schema 오류가 나면 `ASK_USER`로 Fail-closed합니다. Python M-03과 기존
  완료·취소·기한 단축 승인 Gate는 그대로 최종 Guard로 유지합니다. 이 항목은 아직 코드·테스트
  결과가 없으므로 아래 PoC 검증 수치에 포함하지 않습니다.

### 주요 문제 해결 및 기술 리서치

구현 과정에서 마주친 기술적 문제와 이를 해결하기 위해 **찾아본 자료(리서치)** 및 **적용한 방법**을 기록합니다.

| **이슈 구분** | **문제 상황 및 원인** | **리서치 및 해결 과정 (Reference & Solution)** |
|---|---|---|
| **프롬프트·환각** | 회사 LLM이 “다음 주 중”을 특정 날짜로 임의 해석하거나 “거의 끝난 것 같다”를 완료로 판단할 수 있음 | **리서치:** Structured Output, 명시적 System Prompt와 Deterministic Guard 적용 방식을 검토했습니다. **적용:** 모호한 날짜·완료 표현을 Prompt에 명시하고, 원문 Marker를 Python Logic이 다시 확인하여 `ASK_USER`로 차단했습니다. |
| **구조화 출력** | LLM JSON이 Pydantic Schema와 맞지 않으면 후속 로직이 잘못 실행될 위험 | **리서치:** JSON Object 응답과 Pydantic Validation, 제한된 Retry 패턴을 검토했습니다. **적용:** Schema 오류 시 1회 재시도하고 최종 실패 시 DB를 변경하지 않도록 했습니다. |
| **Task 연결** | 같은 DDC 주제의 활성 Task가 여러 개면 하나를 임의 선택할 위험 | **리서치:** Metadata 우선 Entity Resolution과 Human-in-the-loop 방식을 검토했습니다. **적용:** 동일 `conversation_id`를 최우선으로 하고 후보별 점수·근거를 표시하며, 복수 후보는 `ASK_USER`로 전환했습니다. |
| **상태·안전** | 완료·취소·기한 단축은 오판 시 업무 상태를 크게 훼손할 수 있음 | **리서치:** 중요 변경 승인 Gate와 Audit History 방식을 적용했습니다. **적용:** 사용자 승인 전 Task를 변경하지 않고 Agent 제안과 사용자 최종 결정을 모두 History에 저장했습니다. |
| **운영 추적** | 결과만 보면 어느 단계에서 실패했는지 알 수 없음 | **리서치:** 단계별 Event Logging과 Secret Redaction 방식을 검토했습니다. **적용:** Mail 입력부터 DB 반영까지 단계·시각·처리시간·오류를 SQLite Processing Event와 Streamlit 운영 로그에 표시하고 Secret을 저장 전에 마스킹했습니다. |
| **운영 안정성** | Dashboard와 1분 주기 Gmail Scheduler가 동시에 SQLite에 쓰면 잠금 충돌이나 비정상 종료 위험이 있음 | **리서치:** SQLite WAL·Busy Timeout·동기화 수준과 Process 단일 실행 잠금을 검토했습니다. **적용:** WAL, 30초 Busy Timeout, `synchronous=FULL`, OS 단일 실행 잠금과 Online Backup·무결성 점검을 적용했습니다. |

### 핵심 동작 검증

위에서 구현한 기능이 의도대로 동작하는지 보여주는 **대표적인 실행 결과**를 첨부합니다.

**[검증 시나리오: 신규 업무 생성 후 후속 Mail의 기한 변경]**

* **입력:** `MAIL-001` “DDC 서버 4대의 패치 적용 여부를 이번 주 금요일까지 확인해 주세요.” 이후 동일 Thread의 `MAIL-002` “다음 주 월요일까지 공유해도 됩니다.”

* **에이전트 동작:**

  1. M-01이 `MAIL-001`을 `NEW_TASK`, 기한 `2026-08-21`로 구조화

  2. M-02가 기존 후보 없음 확인 → M-03이 `CREATE_TASK` 결정

  3. M-04가 `TASK-001 / TODO`와 생성 History 저장

  4. `MAIL-002`에서 동일 `conversation_id`의 `TASK-001`을 점수 1.0으로 매칭

  5. M-03이 `UPDATE_TASK`와 기한 `2026-08-21 → 2026-08-24` 결정

  6. Validation 후 동일 Task 갱신 및 변경 전·후 History 저장

* **최종 결과:**

`TASK-001` 한 건만 유지되며 기한은 `2026-08-24`로 변경됩니다. Agent Action, 판단 근거, 원본 Mail ID, 변경 전·후 값과 처리 시각은 Dashboard의 Task History와 운영 로그에서 확인할 수 있습니다. 복수 후보·모호한 기한·완료·취소 Case는 자동 변경하지 않고 사용자 확인으로 전환됩니다.

최종 회귀 검증은 `pytest 122 passed`이며, 회사 LLM Live 15/15 실행 단위·28/28 Action 단계, 별도 테스트 Gmail 비식별 합성 Mail 20/20 수용시험, Windows Scheduler 반복 실행 성공(`LastTaskResult=0`)과 SQLite `quick_check=ok`를 확인했습니다.
