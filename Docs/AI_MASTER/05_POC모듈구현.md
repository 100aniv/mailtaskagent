이번 PoC 단계의 목표는 메일 한 건이 들어와 Task로 반영되기까지의 경로를 **끊김 없이 한 번
돌리는 것**입니다.

* **목표:** 메일 분석 → 후보 검색 → Action 결정 → Python Guard → 사용자 확인 → DB 반영을
  단일 Agent Workflow로 연결하고, 각 단계의 판단 근거를 추적 가능하게 남깁니다.
* **범위:** 합성·비식별 Mail과 별도 테스트 Gmail, 7개 Task Action, 5개 Task 상태,
  SQLite 저장과 Streamlit 확인 화면.
* **비범위:** 사내 Outlook·Graph 연동, 다중 사용자·SSO, Embedding·Vector DB 기반 문서검색 RAG,
  Mail 1건에서 복수 요청을 자동 분해하는 기능. 모두 Post-MVP로 남겼습니다.
* **해석 범위:** 아래 수치는 정의된 합성·비식별 테스트셋과 제한적 Live 증적 기준이며
  실제 Mailbox 전체 성능으로 일반화하지 않습니다.

**대표 시나리오 한 눈에 — 메일 한 통이 Task가 되기까지**

| 입력 메일 | Agent 판단 | 최종 Action | 저장 결과 |
|---|---|---|---|
| `MAIL-001` "DDC 서버 4대의 패치 적용 여부를 이번 주 금요일까지 확인해 주세요" | 업무 요청으로 분류하고 기한을 `2026-08-21`로 해석. 동일 Thread·유사 Task 후보 **0건** | `CREATE_TASK` | `TASK-001` · `TODO` · 기한 `2026-08-21`, 생성 History 기록 |
| `MAIL-002` "다음 주 월요일까지 공유해도 됩니다" (동일 Thread) | `conversation_id` 일치로 `TASK-001` 확정(점수 1.0). **기한이 뒤로 밀리는 변경**이라 승인 Gate 비대상 | `UPDATE_TASK` | `TASK-001` 유지 · 기한 `2026-08-24`, 변경 전·후 History 기록 |

기한이 **앞당겨지는** 변경이었다면 같은 경로에서 `ASK_USER`로 전환됩니다. 자동 반영 여부를
가른 것은 Action의 종류가 아니라 변경의 위험도입니다. 단계별 상세와 증적은 아래
`핵심 동작 검증`에 있습니다.

### 핵심 구현 내용

이번 PoC 단계에서 실제 코드로 구현된 핵심 기능들을 **동작 원리**와 **사용 기술** 중심으로 상세히 기술합니다.

**1.1 에이전트 워크플로우 (Agent Workflow)**

* **구현 기능:** 합성 Mail 입력부터 의미 분석, Task 후보 검색, 7개 Action 결정, Validation, 사용자 확인, Task·History 저장까지 연결한 단일 Agent Workflow

* **동작 원리:** M-01이 회사 LLM API로 Mail Intent와 요청사항·기한을 구조화하고, M-02가 `conversation_id`와 제목·요청자·요약을 이용해 기존 Task 후보를 찾습니다. 동일 Thread로 확정할 수 없는 `STRUCTURED_RAG` 경로에서는 가설 생성 Agent가 관계·대상 Task와 `CREATE_TASK`, `UPDATE_TASK`, `LINK_TO_TASK`, `SET_WAITING`, `MARK_COMPLETED`, `ASK_USER`, `IGNORE` 중 하나를 묶은 후보를 2~3개 만들고, Python이 후보 ID·관계·Action 계약을 검증한 뒤 별도 평가 Agent가 후보별 지지도를 매겨 하나를 선택합니다. 상위 두 지지도의 차이는 Python이 계산하며 기준 미만이면 재검색 후 그래도 갈리지 않으면 사용자 확인으로 넘깁니다. Python M-03은 실행 Payload와 후보 범위·Intent·상태 전이·중요 변경을 검증하여 승인하거나 `ASK_USER`로 이관합니다. Pydantic Validation을 통과한 결과만 M-04가 SQLite에 반영하며, 중요하거나 불명확한 변경은 M-05 사용자 확인 이후 반영합니다. Streamlit 첫 화면에서는 실제 업무 모드와 MVP 시연 모드를 선택하고, 동일 Agent Core를 공유하되 실제 업무 DB와 시연 DB를 분리합니다.

* **주요 기술:** Python 3.12.14 최종 검증 환경, OpenAI Python SDK의 `AzureOpenAI` 호환 Client, 회사 LLM `gpt-4.1-mini`, Pydantic, SQLite, Streamlit

**1.2 도구(Tool) 및 함수 연동**

* **구현 기능:** Mail 분석, 중복 확인, Task 후보 검색, Action 실행, 사용자 검토, 품질평가 함수와 읽기 전용 Gmail Input Adapter 연동

* **동작 원리:** `MailTaskWorkflow.process()`가 처리 순서를 관리합니다. `MailAnalyzer.analyze()`의 구조화 결과를 Pydantic으로 검증하고, `SQLiteStorage.search_candidate_tasks()`와 `retrieve_task_contexts()`가 동일 Thread 또는 top-k 후보와 매칭 점수·근거를 반환합니다. 확정 경로는 기존 `decide_action()`을 유지하고, `STRUCTURED_RAG` 경로는 `TaskContextAgent.judge()`의 Action Proposal을 `build_guarded_agent_proposal()`이 Payload로 구체화하고 안전 검증합니다. `SQLiteStorage.apply()`가 승인된 Proposal만 하나의 Transaction 안에서 Task·Link·History로 저장하고 실제 상태를 재조회합니다. `resolve_review()`는 사용자가 확정한 결과만 반영하고, `run_scenario_evaluation()`은 각 Case를 격리 DB에서 재현해 기대값과 비교합니다. `GmailReadOnlySource.load()`는 제한 Label의 신규 Gmail과 Task DB에 연결된 정확한 Thread의 수신·발신 후속 Mail을 기존 `MailInput`으로 정규화합니다. 실제 OAuth 연결 후 별도 테스트 계정의 비식별 합성 Mail 20건을 회사 LLM Live로 처리해 20/20 수용시험과 재조회 중복 차단·실패 0건을 확인했습니다.

* **주요 기술:** Python 함수 기반 Orchestration, Pydantic Schema Validation, SQLite Transaction, Streamlit Form·Session State, pytest Parameterized Test, 선택적 Google Gmail API Python Client와 `gmail.readonly` OAuth Scope

**1.3 데이터 및 메모리 (RAG & Context)**

* **구현 기능:** Mail, Task, Mail–Task Link, Processing Result, Task History, Processing Event를 SQLite에 구조화하여 저장

* **동작 원리:** 한 건의 Mail을 처리하는 동안 동일 Thread의 선행 Mail, Mail 분석 결과, 후보 Task, 선택 Task의 최근 History, Action 제안, Validation과 실행 결과를 Pydantic 객체로 유지합니다. 처리가 끝나면 Task 현재 상태, 원본 Mail ID, 변경 전·후 값, 판단 근거, 신뢰도, 사용자 결정을 SQLite에 저장하고 다음 Mail 처리 시 필요한 Context만 다시 조회합니다. 동일 `mail_id`는 기존 결과를 반환하여 LLM과 DB 변경을 재실행하지 않습니다.

* **주요 기술:** SQLite, Pydantic State Model, `conversation_id` Metadata 우선 검색, 설명 가능한 Token 기반 후보 점수, SQLite Task·Mail·History를 Source로 쓰는 경량 Task Context Agentic RAG, 가설 생성과 평가를 분리한 Bounded Multi-Hypothesis Deliberation과 최대 1회 Query Rewrite입니다. Tree of Thoughts를 구현한 것이 아니라 후보 수·평가·재검색을 각각 제한한 방식입니다. 사내 문서검색 RAG·Embedding·Vector DB는 Post-MVP로 유지합니다.

* **최종 MVP Agentic 보강:** 동일 Thread로 확정할 수 없는 경우 top-k Task Context를 검색하고,
  별도 Task Context Agent가 `SAME_TASK`, `NEW_TASK`, `AMBIGUOUS` 관계·대상 Task와 7개 Action 중
  실행 Proposal을 선택합니다. 첫 판단이 모호하거나 저신뢰면 Query를 최대 1회 재작성·재검색하고,
  재판단도 불확실하거나 API·Schema 오류가 나면 `ASK_USER`로 Fail-closed합니다. Python M-03은
  Action을 다시 선택하는 대신 Payload를 구성하고 후보 범위·관계·Intent·상태 전이와 완료·취소·
  기한 단축 승인 Gate를 검증합니다. Agent 실행 과정은 `processing_events`와 Streamlit의 Agentic
  Workflow Trace에서 Agent Proposal, Python Guard, Final Action으로 구분해 확인할 수 있습니다.

**이번 PoC에서 구현을 마친 것과 후속으로 남긴 것**

| 구분 | 항목 |
|---|---|
| **구현 완료** | SQLite Task Context 검색(top-k, 최근 Mail 3건·History 5건), 가설 생성과 평가를 분리한 Bounded Multi-Hypothesis Deliberation, 최대 1회 Query Rewrite, 7개 Action 결정, Python Safety Guard와 `ASK_USER` Fail-closed, 완료·취소·기한 단축 승인 Gate, Transaction 저장과 실행 결과 재조회, Gmail 읽기 Adapter와 사용자 승인 발송, Processing Event 기반 Agent Trace |
| **후속 과제(Post-MVP)** | Embedding·Vector DB, 사내 문서·첨부파일 검색 RAG, Outlook·Microsoft Graph Adapter, 다중 사용자와 SSO, Mail 1건의 복수 요청 자동 분해, Push Notification 기반 수집 |

### 주요 문제 해결 및 기술 리서치

구현 과정에서 마주친 기술적 문제와 이를 해결하기 위해 **찾아본 자료(리서치)** 및 **적용한 방법**을 기록합니다.

| **이슈 구분** | **문제 상황 및 원인** | **리서치 및 해결 과정 (Reference & Solution)** |
|---|---|---|
| **프롬프트·환각** | 회사 LLM이 “다음 주 중”을 특정 날짜로 임의 해석하거나 “거의 끝난 것 같다”를 완료로 판단할 수 있음 | **리서치:** Structured Output, 명시적 System Prompt와 Deterministic Guard 적용 방식을 검토했습니다. **적용:** 모호한 날짜·완료 표현을 Prompt에 명시하고, 원문 Marker를 Python Logic이 다시 확인하여 `ASK_USER`로 차단했습니다. |
| **구조화 출력** | LLM JSON이 Pydantic Schema와 맞지 않으면 후속 로직이 잘못 실행될 위험 | **리서치:** JSON Object 응답과 Pydantic Validation, 제한된 Retry 패턴을 검토했습니다. **적용:** Schema 오류 시 1회 재시도하고 최종 실패 시 DB를 변경하지 않도록 했습니다. |
| **Task 연결** | 같은 DDC 주제의 활성 Task가 여러 개면 하나를 임의 선택할 위험 | **리서치:** Metadata 우선 Entity Resolution과 Human-in-the-loop 방식을 검토했습니다. **적용:** 동일 `conversation_id`를 최우선으로 하고 후보별 점수·근거를 표시하며, 복수 후보를 구분할 근거가 부족하거나 신뢰도가 낮으면 `ASK_USER`로 전환했습니다. |
| **상태·안전** | 완료·취소·기한 단축은 오판 시 업무 상태를 크게 훼손할 수 있음 | **리서치:** 중요 변경 승인 Gate와 Audit History 방식을 적용했습니다. **적용:** 사용자 승인 전 Task를 변경하지 않고 Agent 제안과 사용자 최종 결정을 모두 History에 저장했습니다. |
| **운영 추적** | 결과만 보면 어느 단계에서 실패했는지 알 수 없음 | **리서치:** 단계별 Event Logging과 Secret Redaction 방식을 검토했습니다. **적용:** Mail 입력부터 DB 반영까지 단계·시각·처리시간·오류를 SQLite Processing Event와 Streamlit 운영 로그에 표시하고 Secret을 저장 전에 마스킹했습니다. |
| **운영 안정성** | Dashboard와 1분 주기 Gmail Scheduler가 동시에 SQLite에 쓰면 잠금 충돌이나 비정상 종료 위험이 있음 | **리서치:** SQLite WAL·Busy Timeout·동기화 수준과 Process 단일 실행 잠금을 검토했습니다. **적용:** WAL, 30초 Busy Timeout, `synchronous=FULL`, OS 단일 실행 잠금과 Online Backup·무결성 점검을 적용했습니다. |

**실제로 부딪힌 문제와, 미리 막아 둔 설계**

위 표의 여섯 가지는 성격이 갈립니다. 구현 중 실제로 터진 것과, 터지기 전에 막아 둔 것을
구분하면 어디까지가 경험이고 어디까지가 예방인지 분명해집니다.

| 구분 | 항목 | 어떻게 드러났나 |
|---|---|---|
| **실제로 겪음** | 프롬프트·환각 | 첫 Live 실행에서 모호한 기한과 불명확한 완료 표현을 모델이 확정해 버리는 것을 관찰하고 Prompt와 Guard를 고쳤습니다 |
| **실제로 겪음** | 구조화 출력 | 응답 JSON이 Schema와 어긋나 후속 로직이 멈추는 경우가 생겨 재시도와 Fail-closed를 넣었습니다 |
| **실제로 겪음** | 운영 안정성 | Dashboard와 Scheduler가 같은 DB를 동시에 쓰다 잠금 경합이 실제로 발생해 WAL·Busy Timeout·단일 실행 잠금을 적용했습니다 |
| **사전 통제 설계** | Task 연결 | 같은 주제의 활성 Task가 여럿일 때 임의 선택할 위험을 미리 보고, 겪기 전에 Metadata 우선과 `ASK_USER` 전환을 넣었습니다 |
| **사전 통제 설계** | 상태·안전 | 완료·취소·기한 단축의 오판 비용이 크다고 판단해 실제 사고 없이 승인 Gate를 먼저 두었습니다 |
| **사전 통제 설계** | 운영 추적 | 실패 지점을 못 찾는 상황을 겪기 전에 단계별 Event 기록과 Secret 마스킹을 설계에 포함했습니다 |

**현재 구성의 한계와 트레이드오프**

* **SQLite 선택:** 단일 사용자 PoC에서 설치·백업·무결성 점검이 단순해 선택했습니다. 대신
  Dashboard와 1분 주기 Scheduler가 동시에 쓰면 잠금 경합이 생기므로 WAL·Busy Timeout·단일 실행
  잠금으로 막았습니다. 다중 사용자 동시 쓰기는 이 구성으로 감당하지 않습니다.
* **Gmail Live 검증 규모:** 별도 테스트 계정의 비식별 합성 Mail 20건과 실제 Thread 5-message
  E2E가 전부입니다. 실제 업무 메일함의 다양성과 규모를 대표하지 않습니다.
* **합성 중심 검증:** 기대값을 미리 정의할 수 있어야 자동 평가가 가능하므로 대부분의 Case가
  합성입니다. 사람이 쓴 실제 문장의 모호함은 이 방식으로 충분히 재현되지 않습니다.

### 핵심 동작 검증

위에서 구현한 기능이 의도대로 동작하는지 보여주는 **대표적인 실행 결과**를 첨부합니다.

**[검증 시나리오: 신규 업무 생성 후 후속 Mail의 기한 변경]**

* **입력:** `MAIL-001` “DDC 서버 4대의 패치 적용 여부를 이번 주 금요일까지 확인해 주세요.” 이후 동일 Thread의 `MAIL-002` “다음 주 월요일까지 공유해도 됩니다.”

* **에이전트 동작 (입력 → 중간 판단 → 최종 Action → 저장 결과):**

| 단계 | 무엇이 들어왔나 | Agent가 무엇을 보고 판단했나 | 결정 |
|---|---|---|---|
| 1 | `MAIL-001` 원문 | M-01이 업무 요청으로 분류하고 “이번 주 금요일”을 `occurred_at` 기준으로 `2026-08-21`로 해석 | `NEW_TASK`·기한 확정 |
| 2 | 위 분석 결과 | M-02가 동일 `conversation_id`와 유사 Task를 찾았으나 **후보 0건** | 연결할 기존 Task 없음 |
| 3 | 후보 없음 | 새로 만들 근거는 충분하고 되돌리기 어려운 변경이 아니므로 승인 불필요 | `CREATE_TASK` |
| 4 | 실행 결과 | M-04가 저장 후 DB를 다시 조회해 실제 상태 확인 | `TASK-001` · `TODO` 저장, 생성 History 기록 |
| 5 | `MAIL-002` 원문 | M-02가 동일 `conversation_id`를 발견해 **점수 1.0**으로 `TASK-001` 확정. Metadata로 확정되므로 top-k 검색과 Agent 판단을 호출하지 않음 | 대상 Task 확정 |
| 6 | 확정된 Task + 새 기한 | **기한이 뒤로 밀리는 변경**이라 승인 Gate 대상이 아니고, 기존 Task의 상태를 훼손하지 않으므로 신규 생성보다 갱신이 맞다고 판단 | `UPDATE_TASK` · 기한 `2026-08-21 → 2026-08-24` |
| 7 | 실행 결과 | Pydantic 검증 통과 후 동일 Task 갱신, 변경 전·후 값 기록 | `TASK-001` 유지, 기한 `2026-08-24`, 변경 History 저장 |

  6단계가 이 시나리오의 핵심입니다. **기한 단축이었다면** 되돌리기 어려운 중요 변경이므로
  같은 경로에서 `ASK_USER`로 전환됩니다. 자동 반영 여부를 가른 것은 Action의 종류가 아니라
  변경의 위험도입니다.

* **최종 결과:**

`TASK-001` 한 건만 유지되며 기한은 `2026-08-24`로 변경됩니다. Agent Action, 판단 근거, 원본 Mail ID, 변경 전·후 값과 처리 시각은 Dashboard의 Task History와 운영 로그에서 확인할 수 있습니다. 복수 후보를 구분할 근거가 부족하거나 신뢰도가 낮은 Case, 모호한 기한, 완료·취소 Case는 자동 변경하지 않고 사용자 확인으로 전환됩니다.

**검증 수치와 각각이 확인한 것**

| 수치 | 무엇을 검증했나 | 성공 기준 |
|---|---|---|
| `pytest 228 passed` | 저장소의 자동 회귀 테스트 전체 (2026-09-15 최종 격리 보강 포함) | 실패 0건. 기준선은 2026-09-13 179 passed, 2026-09-09 UI 171 passed |
| 회사 LLM Live **15/15 실행 단위** | 합성·비식별 Mail 15건에서 분리한 대표 처리 실행 | 기대 Action·상태·후보 수·Task/History 수 전부 일치 |
| **28/28 Action 단계** | 위 15개 실행이 거치는 개별 Action 결정 지점 | 각 지점의 선택이 기대값과 일치 |
| **60.852초** | 위 15개 실행 단위를 한 번 도는 배치 시간 | 기준선 비교용이며 사용자 체감 응답시간이 아님 |
| Task Context Agent Live **3/3** | 다른 Thread·다른 표현의 후속 Mail 관계 판단 전용 합성 Case | 관계·대상 Task·Action이 기대값과 일치 |
| 테스트 Gmail **20/20 수용시험** | 별도 테스트 계정의 비식별 합성 Mail 20건 | 수신·분석·Task 반영 성공, 재조회 중복 차단, 실패 0건 |
| Reply Planning **3/3**, Draft **1/1** | 회신 방식 판단과 사용자 입력 기반 초안 생성 | 판단→입력→초안→승인 흐름 통과 |
| 실제 Gmail **33/33 → 35/35** | 이미 처리한 Mail을 다시 읽었을 때의 중복 재조회 차단 | 재처리 0건 |

2026-09-13 실제 Gmail 5-message E2E의 첫 Mail은 `ASK_USER`로 안전하게 이관됐고, 사용자 확정 뒤
원본 발신자·Thread 잠금, Send Allowlist, 승인 발송, `WAITING_REPLY`, 기한 단축 승인, 자료 도착 후
`IN_PROGRESS`, 완료 승인 후 `COMPLETED`, 33/33 중복 재조회 방지를 확인했습니다. 이후 별도의 새
Gmail root Mail은 무개입 `CREATE_TASK`로 `TASK-010`·`TODO`·기한 `2026-09-16`을 저장했고 35/35
중복 재조회 방지를 확인했습니다. Windows Scheduler 반복 실행과 SQLite 무결성 `ok`도 함께
확인했습니다. Read-only 동기화와 승인 발송의 OAuth Token은 서로 분리합니다.
