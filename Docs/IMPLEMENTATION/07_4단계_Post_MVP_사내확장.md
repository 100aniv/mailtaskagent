# 07. 4단계 Post-MVP 사내확장

## 1. 목적과 경계

3단계에서 검증한 M-01~M-05 Agent Core를 유지하면서 먼저 테스트 Gmail 기반 실전 개인 사용성과 Priority Rule을 검증하고, 이후 입력, 자동 실행, Database, 배포, 인증·보안을 사내 운영환경으로 교체·확장한다.

Post-MVP는 AI Master Core E2E의 필수 완료 조건이 아니다. 아래 기능은 현재 구현 완료로 간주하지 않는다.

제출용 MVP 복구 기준은 Git Tag `ai-master-mvp-v1`이며, Post-MVP 기능 실패가 해당 Tag의 시연·제출 가능 상태에 영향을 주지 않도록 기능 단위로 테스트·커밋한다.

## 2. 목표 아키텍처

```text
테스트 Gmail 실전 파일럿
-> 사용자 Priority Rule과 운영 UI 검증
-> M365 Outlook / Microsoft Graph 또는 사내 허용 Connector
-> 선택적 정형 Polling/Trigger
-> 동일 M-01 Mail Adapter
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

## 4. 실전 개인 사용 UI와 Priority Rule

### 목표

- 기술 처리량보다 사용자가 지금 해야 할 업무를 먼저 보여주는 `오늘` 중심 화면
- `오늘`, `내 업무`, `검토 필요`, `메일`, `활동 기록`, `연결 및 설정`의 사용자 언어 Navigation
- Task 행에서 완료, 상태·기한·중요도 변경과 원본 Mail·판단 근거 확인
- 기한·회신 대기 기반 긴급도와 고객사·VIP·키워드·사용자 지정 기반 중요도 분리
- `🔴 즉시 처리`, `🟠 우선 처리`, `🔵 예정 업무`, `⚪ 일반 업무`의 색상+문자 Label

### Priority 기본 원칙

1. 사용자 직접 지정값을 가장 우선한다.
2. 정확한 발신자 주소, 등록 고객사 Domain, 연락처 Group 순으로 중요도 Rule을 적용한다.
3. 명시된 기한 초과·오늘·3일 이내·7일 이내와 회신 대기 기준으로 긴급도를 계산한다.
4. 키워드는 보조 신호로만 사용하며 키워드 하나만으로 완료·취소·기한을 확정하지 않는다.
5. 적용 Rule, 최종 Priority와 판단 근거를 Task와 History에서 확인할 수 있어야 한다.
6. 색상만으로 의미를 전달하지 않고 Emoji·Label·텍스트를 함께 표시한다.

### 사용자 설정 대상

- 고객사명, Domain, 정확한 Email 주소와 연락처 이름
- 중요도 상승 Keyword와 광고·자동 발송 제외 Keyword
- 기한 임박 구간과 회신 대기 확인 일수
- Task별 중요도 직접 지정과 자동 계산 복귀
- Rule 활성화·비활성화, 우선순위와 적용 전 미리보기

### RAG 적용 Gate

고객사 SLA, 사내 절차, 프로젝트 매뉴얼처럼 검색할 실제 문서 Corpus가 준비되고 정형 Rule만으로 설명할 수 없는 정책 해석 요구가 확인될 때만 RAG를 검토한다. 발신자, Domain, Keyword, 날짜와 사용자 Preference는 RAG가 아니라 검증 가능한 Application Rule로 처리한다.

## 5. Outlook 및 Microsoft Graph

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

Gmail 실전 파일럿에서 다음 조건을 통과한 뒤 Outlook Adapter를 시작한다.

- 실제 업무 UI에서 Task 생성·수정·완료·검토 흐름이 사용자에게 이해 가능함
- Priority Rule의 근거와 사용자 Override가 History에 남음
- Gmail 신규·후속 Mail이 동일 Agent Core에서 중복 없이 처리됨
- 실제 Mail 원문·Secret이 저장소와 불필요한 로그에 노출되지 않음

## 6. n8n 자동화

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

## 7. 사내 Database와 서비스 배포

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

## 8. 보안·개인정보 Gate

- 실제 Mail을 회사 LLM API로 전달할 수 있는 데이터 범위 승인
- 최소 Context 전송과 민감정보 Masking
- Secret Vault 또는 사내 표준 Secret 관리
- 사용자 동의, Mailbox 접근 권한, 관리자 감사
- 보존 기간, 삭제 요청, DLP, 암호화
- Prompt Injection과 악성 Link/첨부파일 자동 실행 방지
- 사용자 승인 없는 자동 메일 발송과 중요 상태 변경 금지

## 9. 단계적 도입

| 단계 | 범위 | 진입 조건 |
|---|---|---|
| P0 실전 UX·Rule | 테스트 Gmail, 운영 UI, Priority Rule·사용자 Override | Core E2E 회귀 통과 |
| P1 Adapter 검증 | Graph/DB/정형 자동화 Mock·계약 테스트 | P0 사용자 Workflow 검증 |
| P2 제한 파일럿 | 테스트 계정, Read-only, 소수 사용자 | 보안·권한 승인 |
| P3 승인 기반 쓰기 | Task/알림 반영, 취소·재처리 | 감사·Rollback 검증 |
| P4 운영 서비스 | 다중 사용자, SSO, SLA | 품질·보안·운영 Gate 충족 |

## 10. Post-MVP 추가 테스트

- Priority 자동 계산·수동 Override·Rule 충돌·근거 저장
- 고객사 Domain·정확한 발신자·Keyword·기한·회신 대기 경계값
- 실제 업무/시연 DB 격리와 MVP 60개 회귀
- Graph 권한·Token 만료·Delta 중복
- n8n 재시도와 Idempotency
- 사내 DB Transaction과 Migration
- 사용자·조직 권한 격리
- 장애·복구·모니터링
- 실제 환경 성능·비용·동시 사용자
- Core 15개 Business Case 회귀

## 11. 현재 범위 밖

- RAG/Vector DB 기반 사내 문서 검색
- Multi-Agent
- 자동 회신·발송
- 조직 전체 Mailbox 처리
- 첨부파일 정밀 분석

향후 실제 비즈니스 요구와 보안 승인, Core 평가 결과로 필요성이 입증될 때 별도 기획한다.
