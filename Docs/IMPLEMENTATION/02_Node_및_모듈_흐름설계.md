# 02. Node 및 모듈 흐름설계

## 1. 전체 처리 흐름

```text
START
  -> M-01 load/normalize/check duplicate/analyze
  -> M-02 load thread & task context/search candidates
  -> M-03 decide exactly one Action
  -> Action Validation
     -> IGNORE: M-04 처리 이력 -> M-05 결과
     -> ASK_USER/중요 변경: M-05 사용자 확인
        -> 승인·수정: M-04 적용 및 이력
        -> 거절·무시: M-04 결정 이력만 저장
     -> 유효 Action: M-04 Transaction 적용 및 이력
     -> 검증 실패: DB 변경 중단 -> 오류 기록/제한 재시도/사용자 확인
  -> M-05 Dashboard 갱신
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

## 3. M-01 Mail Input & Analyzer

### 입력

- 기본: 합성·비식별 JSON Mail
- 선택: 테스트 Gmail Adapter가 생성한 동일 Schema

### 책임

1. Source별 입력을 공통 Mail Schema로 변환한다.
2. `mail_id` 중복을 확인한다.
3. Metadata와 기준 시각을 검증한다.
4. 회사 제공 LLM API로 업무 요청, 요청사항, 요청자, 기한, 회신 필요, 변경·완료·취소 의도를 구조화한다.
5. API 오류와 잘못된 JSON을 실행 가능한 결과로 취급하지 않는다.

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
5. 요청 요약과 Task 내용의 의미 관련성

Metadata로 관계가 명확하면 Rule 결과를 우선한다. 현재 구현은 `conversation_id`와 제목·요청자·요청요약 Token 기반 점수로 후보를 검색하며, 복수 후보나 근거 부족은 `ASK_USER`로 전환한다. 제한적 LLM 의미 비교는 이 방식의 실측 정확도가 목표에 미달할 때만 검토한다.

### 주요 함수 계약

- `search_candidate_tasks(conversation_id, subject, sender, request_summary, open_only, limit)`
- `get_task_context(task_id, history_limit)`

### 출력

후보별 `task_id`, 상태, Match 근거, Match 점수를 반환한다. 동일 `conversation_id`는
점수 1.0과 명시적인 근거를 부여하고, 그 외 후보는 제목·요청자·요청 요약에서 일치한
Token 비율과 실제 일치 항목을 함께 표시한다. 후보가 복수이거나 근거가 부족하면
M-03이 `ASK_USER`를 선택한다. 현재 점수는 설명 가능한 1차 Rule 점수이며 LLM 확률값이
아니다.

## 5. M-03 Agent Action Decision

### 입력 Context

- `current_mail`
- `mail_analysis`
- `candidate_tasks`
- 선택 Task의 현재 상태와 최근 History
- 사용자가 마지막으로 확정한 값

### 출력 계약

Python Application Logic이 정의된 7개 중 정확히 하나의 Action, 대상 Task ID, 생성/변경 Payload, 이유, 신뢰도, 사용자 확인 필요 여부를 Pydantic `ActionProposal`로 반환한다.

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
