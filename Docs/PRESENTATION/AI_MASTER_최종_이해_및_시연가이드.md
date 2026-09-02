# MailTaskAgent AI Master 현재 기준 이해 및 시연 가이드

## 1. 한 문장으로 설명하기

MailTaskAgent는 메일을 단순히 요약하는 서비스가 아니라, 새 메일과 같은 Thread의 이전 메일, 현재 업무 상태를 함께 보고 **다음 업무 Action을 결정하고 Task의 Lifecycle을 관리하는 Agentic AI**다.

## 2. 왜 만들었는가

업무 메일은 한 번 읽고 끝나지 않는다. 신규 요청이 들어오고, 같은 Thread에서 기한이 바뀌고, 내가 회신하면 상대 답변을 기다리며, 추가 회신이 오면 다시 진행하고, 마지막에는 완료된다. 사용자가 이 흐름을 매번 수동으로 기억하고 정리하면 누락과 중복 Task가 생긴다.

```text
Mail 수집
  → Mail 의미·Intent 구조화
  → 기존 Task 후보 검색
  → 다음 Agent Action 결정
  → Validation
  → 필요 시 사용자 확인
  → Task·History 반영
  → Dashboard 표시
```

## 3. Agentic AI인 이유

일반 Mail 요약기는 “이 메일의 내용은 무엇인가”까지만 답한다. MailTaskAgent는 현재 Task 상태까지 참고하여 “이제 무엇을 해야 하는가”를 7개 Action 중 하나로 결정하고, 그 결과를 다음 Mail 처리의 상태로 다시 사용한다.

| 구분 | 담당 역할 |
|---|---|
| 회사 LLM `gpt-4.1-mini` | Mail의 업무 관련 여부, Intent, 요청사항, 기한, 회신 필요 여부와 판단 근거 구조화 |
| Python M-02 | `conversation_id` 우선, 확정 불가 시 SQLite Task·최근 Mail·History top-k 검색 |
| Python M-03 | 현재 상태와 후보 수를 보고 최종 Agent Action 결정 |
| Task Context Agent | 동일 Thread로 확정할 수 없는 top-k 후보의 관계와 Action 제안, 최대 1회 Query Rewrite·재판단 |
| Pydantic·Application Logic | Schema, 허용 상태 전이, Task ID와 중요 변경 검증 |
| 사용자 | 복수 후보, 모호한 기한, 완료·취소 등 중요한 결정을 최종 확인 |
| SQLite | Task 현재 상태, Mail 연결, Processing Event와 변경 History 저장 |
| Streamlit | 사용자의 Task 관리, 검토 요청, Mail 타임라인과 운영 상태 표시 |

LLM이 DB를 직접 수정하지 않는 것이 핵심 안전 설계다.

## 4. M-01~M-05와 7개 Action

| 모듈 | 하는 일 |
|---|---|
| M-01 Mail Input & Analyzer | 합성 Dataset 또는 Gmail을 공통 Schema로 바꾸고 LLM으로 의미를 구조화 |
| M-02 Task Context Matcher | 같은 Thread를 우선하고 확정 불가 시 제한 Task Context top-k 검색 |
| M-03 Agent Action Decision | 검색 결과를 관찰·재판단하고 Python Guard로 7개 Action 중 하나를 결정 |
| M-04 Task State & History Manager | 검증된 결과를 SQLite Transaction으로 반영하고 History 저장 |
| M-05 User Review & Dashboard | 사용자가 애매하거나 중요한 결정을 승인·수정·거절하고 결과 확인 |

| Action | 의미 |
|---|---|
| `CREATE_TASK` | 새로운 업무 Task 생성 |
| `UPDATE_TASK` | 기존 Task의 제목·설명·기한 등 변경 |
| `LINK_TO_TASK` | Mail을 기존 Task에 연결 |
| `SET_WAITING` | 내가 회신해 상대 답변을 기다리는 상태로 변경 |
| `MARK_COMPLETED` | 완료 근거를 발견하고 완료 변경을 제안 |
| `ASK_USER` | 후보가 여러 개이거나 판단이 위험해 사용자에게 확인 |
| `IGNORE` | 광고·공지·업무 무관 Mail을 Task로 만들지 않음 |

Task 상태는 `TODO`, `IN_PROGRESS`, `WAITING_REPLY`, `COMPLETED`, `CANCELLED` 5개다.

## 5. 실제로 자동 동작하는 방식

- MVP 시연 모드에서는 합성 Mail을 이용해 동일 동작을 재현한다.
- 실제 업무 모드에서는 읽기 전용 Gmail Adapter가 연결된다.
- Gmail 연결 후 Agent는 기본 실행 상태이며 Windows Scheduler가 1분마다 신규 Mail을 확인한다.
- 한 번 처리한 `mail_id`는 다시 LLM에 보내거나 DB에 중복 반영하지 않는다.
- Task에 연결된 Gmail Thread는 수신 메일뿐 아니라 보낸 메일과 이후 회신도 함께 추적한다.
- Dashboard의 수동 동기화 버튼은 자동화의 필수 버튼이 아니라 시연, 즉시 확인과 장애 복구용이다.

현재 구조는 API Event가 발생하는 즉시 처리하는 Push 방식이 아니라 최대 약 1분 간격의 Polling 방식이다.

## 6. 대표 Lifecycle 예시

```text
1. 고객이 신규 요청 Mail 발송
   → CREATE_TASK → TODO

2. 같은 Thread에서 기한 변경 Mail 발송
   → UPDATE_TASK → 기존 Task 기한 갱신

3. 사용자가 답변 Mail 발송
   → SET_WAITING → WAITING_REPLY

4. 고객이 추가 자료 Mail 회신
   → UPDATE_TASK 또는 LINK_TO_TASK → IN_PROGRESS

5. 완료를 명확히 나타내는 Mail 도착
   → MARK_COMPLETED 제안 → 사용자 승인 → COMPLETED
```

완료는 두 가지 방식으로 처리한다. 사용자가 Dashboard에서 직접 완료할 수 있고, Mail 내용에서 완료 근거가 확인되면 Agent가 `MARK_COMPLETED`를 제안한다. 중요한 상태 변경이므로 현재 정책에서는 사용자가 승인한 뒤에만 최종 `COMPLETED`로 반영한다.

## 7. Human-in-the-loop 예시

같은 주제의 Task 후보가 두 개면 Agent가 임의로 하나를 바꾸지 않고 `ASK_USER`를 선택한다. Dashboard에서 후보와 점수·근거를 보여주고 사용자는 다음 중 하나를 확정한다.

- 기존 Task에 연결
- 신규 Task 생성
- 무시

Agent 제안과 사용자 최종 결정은 모두 History에 남는다.

## 8. 현재 완료된 증적

| 항목 | 결과 |
|---|---:|
| 회사 LLM Live 실행 단위 | 15/15 |
| Agent Action 단계 | 28/28 |
| 업무 요청 분류 | 15/15 |
| 요청사항·기한 필수 필드 | 26/26 |
| 기존 Task 연결 | 8/8 |
| 테스트 Gmail 수용시험 | 20/20 |
| Task Context Agent Live 합성 검증 | 3/3 |
| 전체 자동 테스트 | 136 passed |
| Gmail 재조회 | 신규 처리 0, 중복 차단 20, 실패 0 |
| Windows Scheduler | 반복 실행 성공, `LastTaskResult=0` |
| SQLite 무결성 | `quick_check=ok` |

위 수치는 정의된 합성·비식별 Dataset과 별도 테스트 Gmail의 결과다. 실제 회사 Mailbox 전체 성능이나 실제 시간 절감률로 확대해서 말하면 안 된다. 수동 업무 정리시간 Baseline은 아직 측정하지 않았다.

## 9. AI Master 최종 MVP 완료 범위

### 구현·검증 완료

- 문제 정의와 3개 핵심 사용자 시나리오
- M-01~M-05 단일 Agent Workflow
- 회사 LLM Live 연동과 Structured Output
- 7개 Action·5개 상태·Human-in-the-loop
- Task·Mail·History·Processing Event 저장
- 실제 업무/시연 모드가 분리된 Streamlit Dashboard
- 품질·보안·장애·UI·Gmail 회귀 테스트
- 읽기 전용 Gmail 개인 파일럿과 1분 자동 동기화
- SQLite 동시 접근·백업·손상 감지 안전장치
- 동일 Thread가 아닌 다른 표현의 Mail을 위한 SQLite Task Context top-k Retrieval
- 별도 Task Context Agent의 `SAME_TASK` / `NEW_TASK` / `AMBIGUOUS` 관계와 Action 제안
- 첫 판단이 모호하거나 저신뢰일 때 최대 1회 Query Rewrite·재검색·재판단
- 후보 밖 Task ID, API·Schema 실패와 두 번째 불확실 판단의 `ASK_USER` Fail-closed
- 기존 완료·취소·기한 단축 승인 Gate와 전체 회귀 유지
- Observe Input부터 Final Output까지의 Agentic Workflow Trace
- 신규 RAG 평가 Evidence와 전체 pytest 136개 통과

### 사내 운영 전 추가로 필요한 것

- M365 Outlook / Microsoft Graph 또는 사내 허용 Connector
- 사내 SSO·권한·보존기간·보안 심의
- 사내 서버 또는 승인 Container 환경
- 사내 운영 Database와 백업·모니터링 정책
- Slack 또는 사내 승인 Messenger 알림의 운영 설정
- 다중 사용자와 조직 Mailbox 지원
- Push/Event Subscription 기반 실시간 수신이 필요할 경우 별도 설계

따라서 AI Master 최종 MVP의 기술 Gate는 완료했다. 다만 실제 시간 절감률과 실제 Mailbox
전체 정확도는 아직 측정하지 않았고, Outlook과 위 사내 운영 항목은 그 이후 단계다.

## 10. 현재 의도적으로 구현하지 않은 기능

- Mail 한 건 안의 독립적인 여러 요청을 여러 Task로 자동 분해하는 기능
- 사내 문서·첨부파일 RAG, Vector DB·LangGraph·Multi-Agent
- 실제 Mail 자동 발송·삭제·이동
- Calendar 자동 생성
- Outlook·Microsoft Graph 사내 연결
- 다중 사용자 인증과 서버 운영 배포

현재 처리 계약은 Mail 한 건에서 대표 업무 요청 하나와 최종 Action 하나를 만든다. 다중 요청 분해는 필요성은 있지만 오분해 시 Task가 과도하게 생성될 수 있어, 실제 사용 데이터와 승인 UX를 먼저 정의한 뒤 Post-MVP에서 다루는 것이 안전하다.

## 11. 5분 시연 순서

1. 첫 화면에서 실제 업무 모드와 MVP 시연 모드가 분리된 이유를 20초 안에 설명한다.
2. 홈에서 Gmail 연결·Agent 실행·마지막 확인 상태를 보여준다.
3. 신규 요청 Mail로 `CREATE_TASK`와 생성된 Task를 보여준다.
4. 같은 Thread의 후속 Mail로 `UPDATE_TASK` 또는 `SET_WAITING`을 보여준다.
5. 복수 후보 Case에서 `ASK_USER`가 멈추고 사용자 선택 후에만 DB가 바뀌는 것을 보여준다.
6. Task 상세의 Mail 타임라인과 변경 전·후 History를 보여준다.
7. 운영 상태의 Agentic Workflow Trace에서 RAG 검색, 후보 관찰, 판단, Query Rewrite,
   Python Guard와 실행 결과 관찰을 보여준다.
8. 마지막에 15/15, 28/28, Task Context Live 3/3, Gmail 20/20, pytest 136 passed와 측정 한계를 설명한다.

## 12. 발표용 30초 결론

“MailTaskAgent는 Mail을 요약하는 도구가 아니라 Mail Thread와 현재 Task 상태를 함께 보고 다음
Action을 결정하는 개인 업무관리 Agent입니다. 회사 LLM Mail 분석 15개 실행 단위와 28개 Action
단계, Task Context Agent Live 3건, 테스트 Gmail 20건, 자동 테스트 136건을 통과했습니다.
다른 표현의 동일 업무는 SQLite Task Context를 검색하고 최대 한 번 재검색하며, 그래도
불확실하면 사용자에게 넘깁니다. Outlook·사내 인증·서버 배포와 사내 문서 RAG는 그 이후
Post-MVP 범위입니다.”
