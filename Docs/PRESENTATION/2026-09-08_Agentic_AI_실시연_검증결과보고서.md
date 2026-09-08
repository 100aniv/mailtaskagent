# MailTaskAgent Agentic AI 실시연 검증 결과보고서

## 1. 검증 개요

| 항목 | 내용 |
|---|---|
| 검증 일자 | 2026-09-08 |
| 실행 환경 | 로컬 Streamlit `http://localhost:8501` |
| LLM | 회사 제공 `gpt-4.1-mini` Live |
| 입력 데이터 | 합성·비식별 Mail |
| 대상 시나리오 | `애매한 메일 → 사용자 확인` |
| 입력 순서 | `MAIL-001 → MAIL-008 → MAIL-006` |
| 핵심 검증 목적 | RAG 검색, 제한적 ReAct 재판단, Agent Action Proposal, Python Guard, Human-in-the-loop |

이번 검증은 단순 화면 확인이 아니라 실제 Streamlit 시연 화면에서 시나리오를 실행한 뒤,
화면의 Agentic Workflow Trace와 SQLite 저장 결과를 서로 대조했다.

## 2. 실제 실행 결과

```text
MAIL-001 → CREATE_TASK
MAIL-008 → CREATE_TASK
MAIL-006 → ASK_USER
```

`MAIL-006`은 “지난번 DDC 관련 건”이라는 표현만 있어 `TASK-001`, `TASK-002` 중 어느 업무인지
확정할 근거가 부족했다. Agent는 임의로 한 Task를 연결하지 않고 사용자 확인으로 전환했다.

| 판단 단계 | 실제 결과 |
|---|---|
| M-01 Mail 분석 | `UNCERTAIN`, 신뢰도 `80% (0.80)` |
| M-02 Context 경로 | `STRUCTURED_RAG` |
| 최초 검색 후보 | `TASK-001`, `TASK-002` |
| 최초 Task Context 판단 | `AMBIGUOUS`, 신뢰도 `80% (0.80)` |
| Reflection | Query Rewrite 후 재검색 1회 |
| 최종 Task Context 판단 | `AMBIGUOUS`, 신뢰도 `60% (0.60)` |
| 자동 판단 기준 | `75% (0.75)` |
| Agent Action Proposal | `ASK_USER` |
| Python Safety Guard | `ESCALATED` |
| 최종 Action | `ASK_USER` |

## 3. Agentic AI 실행 흐름 확인

실제 운영 로그에서 다음 Event가 시간순으로 기록된 것을 확인했다.

```text
Mail Input
→ Pydantic Schema Validation
→ M-01 회사 LLM Mail 분석
→ M-02 SQLite Task Context 검색
→ Task·최근 Mail·History 관찰
→ M-03 LLM 관계 판단
→ Query Rewrite
→ RAG 재검색
→ Context 재관찰
→ LLM 재판단
→ Agent Action Proposal
→ Python Safety Guard
→ ASK_USER
→ 저장 결과 관찰
→ Final Output
```

이는 고정된 Python 규칙만 순서대로 실행한 것이 아니다. LLM Agent가 검색된 두 Task의 Context를
관찰하고 관계와 Action을 판단했으며, 모호성에 따라 검색 Query를 동적으로 재작성했다. Python은
Agent 대신 새 Action을 선택하지 않고 후보 범위, 상태 전이, 위험 변경과 Payload 안전성만
검증했다.

원시 Chain-of-Thought는 기록하지 않았다. 대신 입력 요약, 검색 Query, 후보 ID·점수·근거,
구조화된 판단 결과, 신뢰도, Guard 결과와 실제 DB 결과만 표시했다.

## 4. Fail-closed와 DB 안전성 확인

실행 직후 SQLite를 직접 조회한 결과는 다음과 같다.

| 확인 항목 | 결과 |
|---|---|
| 전체 Task | 2건 (`MAIL-001`, `MAIL-008`에서 생성) |
| 전체 Mail | 3건 |
| Task 연결 | 2건 |
| `MAIL-006`의 Task 연결 | **0건** |
| `MAIL-006` 처리 결과 | `ASK_USER`, `task_id = null` |
| `MAIL-006` History | `ASK_USER`, `user_decision = null` |
| 기존 Task 상태 | 두 Task 모두 `TODO`, 자동 변경 없음 |

따라서 사용자 승인 전에는 모호한 Mail이 기존 Task에 연결되거나 Task 상태를 바꾸지 않는다는
Fail-closed 정책이 실제 DB에서도 확인됐다. `M-04 DB_TRANSACTION`은 Mail, 처리 결과와 감사용
History를 저장했지만 기존 Task 내용은 변경하지 않았다.

## 5. 신뢰도 표시 보강 결과

멘토가 LLM 판단 과정을 바로 이해할 수 있도록 화면에서 신뢰도를 단계별로 분리했다.

| 화면 표시 | 의미 |
|---|---|
| M-01 Mail 분석 신뢰도 | 현재 Mail의 Intent·요청·기한 구조화 확실성 |
| Task Context Agent 신뢰도 | 검색한 Task·Mail·History를 근거로 한 관계·Action 판단 확실성 |
| Reply Agent 신뢰도 | 필요한 회신 방식과 Draft 판단 확실성 |

운영 로그의 `이번 판단 한눈에 보기`에서는 다음 네 단계를 한 화면에 연결해 표시한다.

1. LLM Mail 분석
2. Task Context 선택
3. Agent Action Proposal과 신뢰도 기준 통과 여부
4. Python Guard와 실제 Final Action

신뢰도는 `90% (0.90)`처럼 백분율과 원래 값을 함께 표시한다. 이 값은 LLM의 구조화된 자신감
표현이며, 실제 운영 정확도 90%라고 주장하는 수치는 아니다.

## 6. 성공 판단과 안전한 중단 Evidence

`품질 검증` 화면에 기존 Task Context Agent 회사 LLM Live Evidence를 추가 표시했다.

| Evidence | 결과 |
|---|---|
| Live 합성 Case | `3/3` 통과 |
| `LIVE-RAG-01` | 다른 Thread·다른 표현을 `SAME_TASK`로 판단 |
| Agent Action Proposal | `UPDATE_TASK` |
| Agent 신뢰도 | `90% (0.90)` |
| 자동 판단 기준 | `75% (0.75)` |
| Query Rewrite 제한 | 최대 1회 |

따라서 화면에서 다음 두 종류의 Agentic 판단을 함께 설명할 수 있다.

- 충분한 근거가 있을 때: 관련 Task를 선택하고 `UPDATE_TASK`를 제안한 뒤 Guard가 검증
- 근거가 부족할 때: Query Rewrite·재검색 후에도 모호하면 `ASK_USER`로 안전하게 중단

## 7. 자동 테스트 결과

```text
170 passed
```

- 신규 UI 표시 검증 포함
- 기존 M-01~M-05 회귀 유지
- 기존 RAG·ReAct·Agent Proposal·Guard 테스트 유지
- Gmail 읽기·승인 발송 테스트 유지
- Streamlit UI Smoke Test 유지

## 8. 멘토 피드백 반영 판정

| 멘토 피드백 | 반영 결과 |
|---|---|
| Rule 기반 Workflow처럼 보임 | Agent Proposal과 Python Guard 역할을 화면에서 분리 |
| RAG 필요 | SQLite Task·Mail·History Context RAG 적용 |
| ReAct Pattern 필요 | 관찰 → 검색 → 판단 → Query Rewrite → 재관찰 → 재판단 구현 |
| 어떤 Input과 추론 과정인지 보여야 함 | 정제된 입력, Context, 구조화 판단 근거와 신뢰도 Trace 제공 |
| 행동 후 결과를 보고 판단해야 함 | DB 실행 후 실제 저장 상태 재조회 |
| 불확실한 판단의 안전성 | `ASK_USER`와 사용자 승인 전 Task 무변경 확인 |

## 9. 최종 판정과 남은 경계

AI Master 제출 범위인 Mail-to-Task Agent의 Agentic AI 보강은 구현과 실제 시연 검증을 완료했다.
이번 검증으로 RAG, 제한적 ReAct, Agent Action Proposal, Python Safety Guard, Human-in-the-loop와
Trace가 화면과 DB 양쪽에서 일치함을 확인했다.

다음 항목은 현재 검증 결과를 과장하지 않기 위해 별도 경계로 유지한다.

- Live `3/3`은 합성 Case 결과이며 실제 회사 Mailbox 전체 정확도를 의미하지 않는다.
- 신뢰도는 모델의 구조화 점수이며 통계적으로 보정된 정답 확률이 아니다.
- Outlook/Microsoft Graph, 사내 인증, 서버 운영과 회사 문서 RAG는 Post-MVP다.
- 실제 사람의 업무시간 단축 KPI는 사용자 측정 전이므로 달성값으로 말하지 않는다.

## 10. 시연에서 말할 핵심 문장

> MailTaskAgent는 메일을 단순 분류하는 Workflow가 아닙니다. 현재 Mail을 LLM이 구조화하고,
> SQLite에서 관련 Task와 최근 Mail·History를 검색한 뒤 Task Context Agent가 관계와 다음
> Action을 제안합니다. 판단이 모호하면 Query를 한 번 재작성해 다시 관찰하고, 그래도
> 확실하지 않으면 ASK_USER로 멈춥니다. Python은 Agent 대신 판단하는 것이 아니라 제안된
> Action의 안전성을 검증하고, 실행 뒤 실제 DB 상태를 다시 확인합니다.
