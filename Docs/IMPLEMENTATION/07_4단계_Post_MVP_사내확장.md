# 07. 4단계 Post-MVP 사내확장

## 1. 목적과 경계

3단계에서 검증한 M-01~M-05 Agent Core를 유지하면서 입력, 자동 실행, Database, 배포, 인증·보안을 사내 운영환경으로 교체·확장한다.

Post-MVP는 AI Master Core E2E의 필수 완료 조건이 아니다. 아래 기능은 현재 구현 완료로 간주하지 않는다.

## 2. 목표 아키텍처

```text
M365 Outlook
-> Microsoft Graph 또는 사내 허용 Connector
-> 사내 n8n Mail Polling/Trigger
-> M-01 Mail Adapter
-> 동일 M-02/M-03 Agent Core
-> 회사 제공 LLM API
-> Validation
-> M-04 사내 승인 DB
-> M-05 사내 Dashboard/Review
-> Teams/Slack/사내 Messenger Reminder(선택)
```

## 3. 확장 원칙

- M-02와 M-03의 핵심 판단 규칙과 Action 계약을 유지한다.
- Outlook/Graph는 M-01 Adapter로 격리한다.
- SQLite 교체는 M-04 저장 Interface 내부에서 수행한다.
- 사내 UI·SSO는 M-05 영역에서 교체한다.
- n8n은 Mail Polling, Schedule, Reminder 등 정형 자동화만 담당하며 Agent 의미 판단을 대체하지 않는다.
- 운영 연동 전까지 실제 Mail 발송·삭제·이동은 하지 않는다.

## 4. Outlook 및 Microsoft Graph

### 검토 항목

- App Registration과 Tenant 승인
- 최소 권한: 초기 Read-only Mail
- 개인 Mailbox 범위와 조직 전체 Mailbox 금지
- Inbox/Sent Items, Delta Query, Conversation ID 매핑
- HTML 본문 정규화, 첨부파일 Metadata, 중복·재처리
- Token 저장·갱신과 감사 로그

### 단계

1. 합성 Payload로 Graph Adapter Contract Test
2. 테스트 Tenant/계정 Read-only 연동
3. 제한된 실제 사용자 파일럿
4. 승인된 범위에서 Sent Items 및 증분 수집

## 5. n8n 자동화

### 역할

- 주기적 Mail Polling 또는 Graph Trigger 수신
- Agent 처리 Queue 호출
- 기한 임박·장기 대기 Schedule
- 승인된 알림 채널 전송
- 실패 재처리와 운영 알림

### 금지

- n8n Keyword Rule만으로 Agent Action을 확정하지 않는다.
- 검증·사용자 승인 없이 중요 Task 상태를 바꾸지 않는다.
- API Key와 Mail 원문을 Workflow에 평문으로 저장하지 않는다.

## 6. 사내 Database와 서비스 배포

### SQLite 교체 검토

- 사내 승인 RDBMS와 표준 Driver
- Transaction, Unique Key(`mail_id`), Migration
- 사용자·조직별 데이터 격리
- History 불변성, 보존·삭제 정책
- Backup, 복구, 장애 전환

### Application 실행환경

- 사내 VM, Application Server 또는 승인 Container
- 개발/검증/운영 환경 분리
- 사내 DNS·TLS·Proxy·인증서
- SSO와 역할 기반 접근 제어
- Health Check, 중앙 Logging, Monitoring, Alert

## 7. 보안·개인정보 Gate

- 실제 Mail을 회사 LLM API로 전달할 수 있는 데이터 범위 승인
- 최소 Context 전송과 민감정보 Masking
- Secret Vault 또는 사내 표준 Secret 관리
- 사용자 동의, Mailbox 접근 권한, 관리자 감사
- 보존 기간, 삭제 요청, DLP, 암호화
- Prompt Injection과 악성 Link/첨부파일 자동 실행 방지
- 사용자 승인 없는 자동 메일 발송과 중요 상태 변경 금지

## 8. 단계적 도입

| 단계 | 범위 | 진입 조건 |
|---|---|---|
| P1 Adapter 검증 | Graph/DB/n8n Mock·계약 테스트 | Core E2E 회귀 통과 |
| P2 제한 파일럿 | 테스트 계정, Read-only, 소수 사용자 | 보안·권한 승인 |
| P3 승인 기반 쓰기 | Task/알림 반영, 취소·재처리 | 감사·Rollback 검증 |
| P4 운영 서비스 | 다중 사용자, SSO, SLA | 품질·보안·운영 Gate 충족 |

## 9. Post-MVP 추가 테스트

- Graph 권한·Token 만료·Delta 중복
- n8n 재시도와 Idempotency
- 사내 DB Transaction과 Migration
- 사용자·조직 권한 격리
- 장애·복구·모니터링
- 실제 환경 성능·비용·동시 사용자
- Core 15개 Business Case 회귀

## 10. 현재 범위 밖

- RAG/Vector DB 기반 사내 문서 검색
- Multi-Agent
- 자동 회신·발송
- 조직 전체 Mailbox 처리
- 첨부파일 정밀 분석

향후 실제 비즈니스 요구와 보안 승인, Core 평가 결과로 필요성이 입증될 때 별도 기획한다.
