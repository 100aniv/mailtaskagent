# 02. Node 및 모듈 흐름설계

## 1. 전체 처리 흐름

```text
START
  -> Observe Input: M-01 load/normalize/check duplicate/analyze
  -> Reason/Plan: exact thread 확인 또는 Task Context 검색 경로 선택
  -> Act/Tool: M-02 exact thread or retrieve ranked task contexts
  -> Observe Context: 후보 Task·최근 Mail·History·사용자 결정 확인
  -> Reason: M-03 Task Context relation judgment when exact thread is unavailable
     -> low confidence/ambiguous: rewrite query and retrieve exactly once
     -> Observe Retry Result: 재검색 후보로 다시 판단
     -> still uncertain/error: ASK_USER fail-closed
  -> Act: M-03 Python policy decides exactly one final Action
  -> Guard: Action Validation
     -> IGNORE: M-04 처리 이력 -> M-05 결과
     -> ASK_USER/중요 변경: M-05 사용자 확인
        -> 승인·수정: M-04 적용 및 이력
        -> 거절·무시: M-04 결정 이력만 저장
     -> 유효 Action: M-04 Transaction 적용 및 이력
     -> 검증 실패: DB 변경 중단 -> 오류 기록/제한 재시도/사용자 확인
  -> Observe Result: 저장 Task를 다시 조회하고 History/Event 기록
  -> Final Output: M-05 Dashboard와 Agentic Workflow Trace 갱신
END
```

## 2. Agent State 계약

공식 상세 설계의 State 이름을 그대로 사용한다.

| 필드 | 생산 모듈 | 소비 모듈 | 설명 |
|---|---|---|---|
| `case_id` | Workflow | 전체 | 처리 Case ID |
| `current_mail` | M-01 | M-02, M-03 | 정규화된 현재 Mail |
| `thread_history` | M-02 | M-03 | 관련 선행·후행 Mail |
| `mail_analysis` | M-01 | M-02, M-03 | 업무 요청과 구조화 필드 |
| `candidate_tasks` | M-02 | M-03, M-05 | 관련 Task 후보 목록 |
| `current_task_context` | M-02 | M-03, Validation | 선택 Task 상태와 History |
| `proposed_action` | M-03 | Validation, M-05 | 제안 Action과 변경값 |
| `validation_result` | Validation | M-04, M-05 | 실행 허용·확인·실패 |
| `confidence` | M-03 | Validation, M-05 | 판단 신뢰도 |
| `needs_user_confirmation` | Validation | M-05 | 사용자 확인 필요 여부 |
| `user_decision` | M-05 | M-04 | 승인·수정·거절 결과 |
| `execution_result` | M-04 | M-05 | DB 적용 결과 |
| `error` | 각 모듈 | Error Handler, M-05 | 오류 정보 |
| `audit_log` | 전체 | M-04, 운영 검토 | 판단과 함수 실행 기록 |

한 Mail 처리가 끝나면 단기 State는 종료한다. Mail, Task, Link, History, 사용자 결정은 SQLite에 장기 저장하고 다음 처리 때 필요한 범위만 다시 조회한다.

Task Context RAG State에는 `retrieval_query`, `retrieved_task_contexts`,
`task_context_decision`, `rag_retry_count`, `match_route`를 사용한다. 2026-09-02 이
Schema와 저장 인자, Workflow 전체 분기와 테스트를 완료했다.
`rag_retry_count`는 0 또는 1만 허용하고, `match_route`는 기존 Metadata 경로와 RAG 경로,
Fail-closed 경로를 실행 증적에서 구분하기 위한 값으로 사용한다.

## 3. M-01 Mail Input & Analyzer

### 입력

- 기본: 합성·비식별 JSON Mail
- 선택: 테스트 Gmail Adapter가 생성한 동일 Schema

테스트 Gmail Adapter는 제한 Label Query로 신규 후보를 가져오고, Task DB에 저장된 Gmail
`conversation_id`의 실제 `threadId`를 조회해 같은 업무의 후속 수신·발신 Mail을 합친다.
Message ID로 중복을 제거한 뒤 발생 시각 순서의 공통 `MailInput`을 M-01에 전달한다.

### 책임

1. Source별 입력을 공통 Mail Schema로 변환한다.
2. `mail_id` 중복을 확인한다.
3. Metadata와 기준 시각을 검증한다.
4. 사용자가 활성화한 정확한 발신자 Email·Domain·제목 Keyword 제외 Rule을 확인한다.
   일치하면 LLM을 호출하지 않고 `NON_TASK` 분석과 Rule 근거를 생성해 기존 `IGNORE` 경로로 보낸다.
5. Rule이 없으면 회사 제공 LLM API로 업무 요청, 요청사항, 요청자, 기한, 회신 필요,
   변경·완료·취소 의도를 구조화한다.
6. API 오류와 잘못된 JSON을 실행 가능한 결과로 취급하지 않는다.

제외 Rule은 새 Mail에만 적용하며 이미 처리된 결과를 소급 변경하지 않는다. 본문 Keyword는
Prompt Injection과 오탐 위험 때문에 자동 제외 조건으로 사용하지 않는다.

### 주요 함수 계약

- `check_duplicate_mail(mail_id)` -> 중복 여부, 기존 결과
- `analyze_mail(mail)` -> `MailAnalysis`
- LLM Client는 URL, Key, Model, Timeout을 환경 변수로 받는다.

## 4. M-02 Task Context Matcher

### 검색 우선순위

1. 동일 `conversation_id`
2. 동일·유사 제목
3. 동일 요청자
4. 활성 Task 여부
5. 요청 요약과 Task 내용의 구조적 관련성

Metadata로 관계가 명확하면 Rule 결과를 우선한다. 현재 기준선은 `conversation_id`와
제목·요청자·요청요약 Token 기반 점수로 최고 동점 후보를 검색하며, 복수 후보나 근거 부족은
`ASK_USER`로 전환한다.

최종 MVP에서는 동일 `conversation_id`의 단일 활성 Task를 기존 결정론적 경로로 확정한다.
확정할 수 없는 경우 `tasks`, `mails`, `mail_task_links`, `histories`에서 활성 Task top-k와
후보당 최근 Mail 3건·History 5건 이하를 조회한다. Token 일치가 없어도 동일 요청자와 최근
활성 Task를 제한적으로 포함하며, 전체 Mailbox나 전체 Task를 LLM에 전달하지 않는다.

### 주요 함수 계약

- `search_candidate_tasks(conversation_id, subject, sender, request_summary, open_only, limit)`
- `get_task_context(task_id, history_limit)`
- 구현 완료: `retrieve_task_contexts(query, requester, top_k, conversation_id, mail_limit, history_limit, body_limit)`

기본 제한값은 top-k 5, 후보당 최근 Mail 최대 3건, History 최대 5건이다. top-k는 1~10으로
제한하며 Mail 본문은 후보 판단에 필요한 길이만 잘라 전달한다. 검색 점수는 Token 일치,
요청자 일치, Thread 일치와 최근성을 조합한 설명 가능한 순위 점수이고 LLM 신뢰도가 아니다.

### 출력

후보별 `task_id`, 상태, Match 근거, Match 점수를 반환한다. 동일 `conversation_id`는
점수 1.0과 명시적인 근거를 부여하고, 그 외 후보는 제목·요청자·요청 요약에서 일치한
Token 비율과 실제 일치 항목을 함께 표시한다. 후보가 복수이거나 근거가 부족하면
M-03이 `ASK_USER`를 선택한다. 현재 점수는 설명 가능한 1차 Rule 점수이며 LLM 확률값이
아니다.

구현된 Retrieval은 최고 동점만이 아니라 top-k 순위 전체와 점수·근거를 반환한다.

## 5. M-03 Agent Action Decision

### 입력 Context

- `current_mail`
- `mail_analysis`
- `candidate_tasks`
- 선택 Task의 현재 상태와 최근 History
- 사용자가 마지막으로 확정한 값
- 최종 MVP에서는 검색된 Task Context와 별도 Task Context Agent의 관계·대상·Action Proposal

### 출력 계약

Task Context Agent는 정의된 7개 중 정확히 하나의 `recommended_action`, 대상 Task ID, 이유와
신뢰도를 Pydantic `TaskContextDecision`으로 반환한다. `STRUCTURED_RAG` 경로에서는 이 값을
실제 Agent Action Proposal로 사용하며, Python `build_guarded_agent_proposal()`이 생성/변경
Payload를 구성하고 안전 정책을 검증한 `GuardedActionResult`를 반환한다.

최종 MVP의 별도 Task Context Agent 출력은 `relation`, `selected_task_id`,
`recommended_action`, `confidence`, `reason`, `rewritten_query`로 고정한다. 후보 밖 Task ID,
Schema 오류, API 실패는 자동 연결하지 않고 `ASK_USER`로 Fail-closed한다. 첫 판단이
`AMBIGUOUS`이거나 신뢰도 기준 미만이면 rewritten query로 정확히 최대 1회만 재검색·재판단한다.

### 기본 결정 규칙

- 신규 요청 + 후보 없음 -> `CREATE_TASK`
- 기존 Task 필드·기한 변경 -> `UPDATE_TASK`
- 관련 Mail 연결만 필요 -> `LINK_TO_TASK`
- 상대방 회신·자료 대기 -> `SET_WAITING`
- 완료가 명확함 -> `MARK_COMPLETED` 제안
- 후보 복수·모호한 기한·완료·취소 -> `ASK_USER`
- 업무 무관 -> `IGNORE`

## 6. Action Validation

Validation은 독립된 Guard이며 LLM 판단을 그대로 실행하지 않는다.

| 검증 | 실패 시 처리 |
|---|---|
| Action Enum | 실행 중단, 제한 재시도 |
| 대상 Task 존재 여부 | `ASK_USER` 또는 실패 |
| 날짜 형식·기준 시각 | 모호하면 사용자 확인 |
| 필수 Payload | 실행 중단 |
| 허용 상태 전이 | 사용자 확인 또는 차단 |
| 동일 Mail 처리 여부 | 기존 결과 반환, 중복 실행 금지 |
| 중요 변경 승인 정책 | M-05 Review로 분기 |

구조화 출력 오류는 최대 1회 재시도를 기본값으로 한다. 재시도 횟수는 설정으로 분리하되 무한 재시도는 금지한다.

Task Context RAG의 재검색 횟수도 최대 1회로 고정한다. 완료·취소·기한 단축과 복수 후보의
기존 사용자 승인 Gate는 RAG 판단으로 우회할 수 없다.

### 2026-09-02 구현 결과와 설정 계약

1. 기존 동일 Thread 결정 경로와 기존 15개 Business Case를 회귀 기준선으로 고정한다.
2. `TaskRelation`과 `TaskContextDecision`의 Pydantic 검증을 단위 테스트로 고정한다.
3. M-02 Retrieval의 활성 Task 제한, top-k 정렬, Mail/History 개수와 본문 길이 제한을 검증한다.
4. 회사 LLM용 Task Context Agent와 결정론적 Mock을 같은 출력 계약으로 구성한다.
5. Workflow에서 동일 Thread 단일 후보는 기존 경로를 유지하고, 확정 불가 Case에만 RAG를 호출한다.
6. 첫 판단이 저신뢰 또는 `AMBIGUOUS`이고 유효한 `rewritten_query`가 있을 때만 1회 재시도한다.
7. 두 판단 결과의 Agent Action Proposal을 Python M-03이 Payload로 구체화하고 후보 범위·관계·
   Intent·상태 전이·중요 변경을 검증한다. 통과하면 Proposal을 실행하고 실패하면 `ASK_USER`로 이관한다.
8. 처리 결과에는 Query, 제한 후보, 판단, 재시도 수와 Route를 남기되 Secret과 전체 Mailbox는 남기지 않는다.
9. RAG와 Agent Action Guard 전용 테스트를 포함한 전체 pytest 149개를 통과하고 새 Evidence를 생성했다.

환경설정은 `TASK_CONTEXT_RAG_ENABLED`, `TASK_CONTEXT_RAG_TOP_K`,
`TASK_CONTEXT_RAG_CONFIDENCE_THRESHOLD`, `TASK_CONTEXT_RAG_MAX_RETRIES`를 사용한다. 기본 계획값은
각각 `true`, `5`, `0.75`, `1`이며 최대 재시도는 설정으로 늘리지 않고 정확히 1로 고정한다.
기능을 끄면 검증된 기존 Metadata·Token 경로로 돌아가야 한다.

## 7. M-04 Task State & History Manager

### 데이터 단위

- `mails`: 원본 식별자, Thread, 방향, 주요 Metadata, 처리 상태
- `tasks`: 제목, 요청자, 설명, 기한, 회신 필요, 상태, 대기 시작, 생성·수정 시각
- `mail_task_links`: Task-Mail 관계, 유형, 근거, 신뢰도
- `histories`: Action, 변경 전·후, 근거 Mail, 이유, 신뢰도, 사용자 결정, 시각
- `processing_results`: 중복 방지용 Case/처리 결과와 오류
- `processing_events`: M-01~M-05 단계, 성공·실패, 소요 시간, 정제된 상세 실행 로그

### Transaction 원칙

- Task 변경, Link, History는 하나의 Transaction으로 처리한다.
- 실패 시 일부만 저장하지 않고 Rollback한다.
- `IGNORE`, 거절, 오류도 Task 변경 없이 처리 이력은 남긴다.
- 사용자 확정값은 최신 확정 상태로 보존하고 Agent가 임의 덮어쓰지 않는다.
- Processing Event는 Task Transaction과 분리해 기록하여 실패 시에도 중단 단계와 오류를 확인할 수 있게 한다. Secret과 인증 정보는 저장 전에 제거한다.
- `RAG_RETRIEVAL`, `RAG_DECISION`, `QUERY_REWRITE`,
  `RAG_RETRIEVAL_RETRY`, `RAG_REDECISION`, `RAG_FALLBACK` 또는 `ASK_USER` Event에
  Query, 후보 ID·점수·근거, 선택 ID, 신뢰도, Action, Retry 수와 판단 근거만 기록한다.

### 주요 함수 계약

- `apply_task_action(action, task_id, task_payload, changes, source_mail_id)`
- `save_processing_history(case_id, mail_id, task_id, action, before, after, reason, confidence, user_decision)`

## 8. M-05 User Review & Dashboard

### Review

- `ASK_USER` 질문, 후보 Task, 변경 제안, 근거, 신뢰도 표시
- 승인, 수정 후 승인, 거절, 무시 선택
- 사용자 선택을 M-04에 전달하고 History에 남김

### Dashboard

- 현재 Task: TODO, 진행 중, 회신 대기, 완료, 취소
- 기한 임박·초과 및 장기 대기
- 처리한 Mail과 연결 History
- 확인 대기 항목과 오류/재처리 대상
- 사용자의 직접 수정·완료·취소
- Task별 수신·발신 Mail, Agent Action과 상태 변화의 시간순 진행 타임라인

## 9. 권장 코드 모듈 경계

아래는 구현 시 권장 구조이며 실제 파일 생성은 다음 작업에서 수행한다.

```text
src/
  schemas/         Mail, Task, Action, State Pydantic 모델
  config/          환경 변수와 설정
  llm/             회사 LLM API Client와 Prompt
  mail/            M-01, JSON Adapter, 선택 Gmail Adapter
  matcher/         M-02
  agent/           M-03, Workflow, Validation
  storage/         M-04, SQLite Schema/Repository, Transaction
  ui/              M-05 Streamlit
  observability/   Logging
tests/
  unit/
  integration/
  e2e/
```

Repository 계층이나 Framework는 초기부터 과도하게 추상화하지 않는다. 단, SQLite 호출은 M-04 내부로 모아 UI·LLM 코드에서 직접 SQL을 실행하지 않게 한다.
