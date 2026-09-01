# 07. 4단계 Post-MVP 사내확장

## 1. 목적과 경계

3단계에서 검증한 M-01~M-05 Agent Core를 유지하면서 먼저 테스트 Gmail 기반 실전 개인 사용성과 Priority Rule을 검증하고, 이후 입력, 자동 실행, Database, 배포, 인증·보안을 사내 운영환경으로 교체·확장한다.

Post-MVP는 AI Master 최종 MVP의 필수 완료 조건이 아니다. 아래 기능은 현재 구현 완료로 간주하지 않는다.

경량 Task Context Agentic RAG는 2026-09-01 멘토 피드백에 따라 Post-MVP가 아니라 최종 MVP
잔여 범위로 이동했다. 이 문서의 RAG는 사내 정책·매뉴얼·첨부파일 지식검색과 Vector DB를 뜻한다.

기존 Git Tag `ai-master-mvp-v1`는 RAG 적용 전 역사적 Core 복구 기준으로 유지한다. Tag 이름은
바꾸지 않지만 현재 최종 MVP 완료 표기로 사용하지 않으며, 이후 기능은 작은 단위로 테스트·커밋한다.

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
-> Slack Reminder(선택)
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

- 기술 처리량보다 사용자가 지금 해야 할 업무를 먼저 보여주는 업무 중심 홈
- `홈`, `내 업무`, `검토 요청`, `자동화 설정`, `운영 상태`, `설정`의 역할 기반 Navigation
- 사용자 Task 화면과 Gmail 배치·Mail 처리 내역·Agent 단계 로그의 운영 모니터링 분리
- VIP·고객사·중요 키워드와 광고·반복 메일 제외 기준은 `자동화 설정`에 독립 배치
- `홈` 상단의 얇은 상태 바와 하단의 최근 Mail 3건으로 최소 운영 상태만 확인
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

광고·뉴스레터·자동발송 제외 Rule은 정확한 발신자 Email·Domain·제목 Keyword로 제한한다.
사용자가 직접 등록·활성화한 Rule만 새 Mail에 적용하고 기존 `IGNORE` Action과 적용 근거를
History·Processing Result에 남긴다. 본문 Keyword만으로는 자동 제외하지 않는다.

2026-08-28 기준 위 제외 Rule의 추가·활성화·비활성화·삭제와 현재 입력 Source 일치 건수
미리보기를 구현했다. Rule 일치 시 회사 LLM 호출을 생략하고 M-01 Processing Event에
적용 근거를 남기며, 비활성 Rule은 기존 Analyzer로 전달되는 회귀를 검증했다.

### 사내 지식 RAG 적용 Gate

고객사 SLA, 사내 절차, 프로젝트 매뉴얼처럼 검색할 실제 문서 Corpus가 준비되고 정형 Rule만으로
설명할 수 없는 정책 해석 요구가 확인될 때만 문서 RAG와 Vector DB를 검토한다. 발신자,
Domain, Keyword, 날짜와 사용자 Preference는 RAG가 아니라 검증 가능한 Application Rule로
처리한다. 이 Gate는 최종 MVP의 SQLite Task Context RAG와 별개다.

## 5. Outlook 및 Microsoft Graph

### 검토 항목

- App Registration과 Tenant 승인
- 최소 권한: 메일 본문 분석이 필요하므로 Signed-in User 대상 Delegated `Mail.Read`.
  `Mail.ReadBasic`은 본문을 제공하지 않으며 `Mail.ReadWrite`, `Mail.Send`는 초기 범위에 추가하지 않는다.
- 개인 Mailbox 범위와 조직 전체 Mailbox 금지
- Inbox/Sent Items, Delta Query, Conversation ID 매핑
- HTML 본문 정규화, 첨부파일 Metadata, 중복·재처리
- Token 저장·갱신과 감사 로그

### 단계

1. 합성 Payload로 Graph Adapter Contract Test
2. 테스트 Tenant/계정 Read-only 연동
3. 제한된 실제 사용자 파일럿
4. 승인된 범위에서 Sent Items 및 증분 수집

### 2026-08-28 P1 Adapter Contract 진행 증적

- Microsoft Graph `message` 합성 Payload를 공통 `MailInput`으로 변환하는
  `OutlookGraphReadOnlySource`를 구현했다.
- Inbox와 Sent Items를 각각 `INBOUND`, `OUTBOUND`로 정규화하고 Graph `conversationId`를
  기존 M-02 Metadata Matching에 사용할 수 있게 매핑했다.
- `/me/mailFolders/{folder}/messages`의 읽기 전용 목록 요청, 필요한 속성만 요청하는
  `$select`, 최대 100건 `$top`, Text 본문 `Prefer` Header Contract를 검증했다.
- Outlook Adapter 테스트 4건과 전체 회귀 pytest `71 passed`를 확인했다.
- 실제 Microsoft Entra App Registration, OAuth Token과 사내 Tenant Live 호출은 아직
  수행하지 않았으며, 사용자·관리자 권한 승인 후 별도 Gate로 진행한다.

Gmail 실전 파일럿에서 다음 조건을 통과한 뒤 Outlook Adapter를 시작한다.

- 실제 업무 UI에서 Task 생성·수정·완료·검토 흐름이 사용자에게 이해 가능함
- Priority Rule의 근거와 사용자 Override가 History에 남음
- Gmail 신규·후속 Mail이 동일 Agent Core에서 중복 없이 처리됨
- 실제 Mail 원문·Secret이 저장소와 불필요한 로그에 노출되지 않음
- Gmail API 형식으로 변환한 전체 Business/Security Case가 Adapter→M-01~M-05 경로에서
  기존 기대 Action과 중복 방지 결과를 유지함

### Outlook 전 Gmail 실메일 20건 수용시험

현재 완료된 제한 Label 실메일 2건 Live 검증은 연결·기본 Thread 확인이며, 실제 사용성
수용시험 완료를 의미하지 않는다. Outlook Live 전에는 비식별 테스트 내용만 사용하는
수신 Inbox와 별도 송신 계정을 준비하고 아래 20건을 실제 Gmail Thread로 송수신한다.

| 묶음 | Mail 수 | 검증 내용 |
|---|---:|---|
| 신규 업무 | 4 | 기한 있음·없음, VIP 발신자, 중요 키워드와 `CREATE_TASK` |
| 후속 변경 | 5 | 동일 Thread 기한 연장, 추가 요청, 값 변경, 무변경 연결과 `UPDATE_TASK`·`LINK_TO_TASK` |
| 회신 대기 | 2 | OUTBOUND 자료 요청의 `SET_WAITING`, INBOUND 회신 후 재개 |
| 완료·취소 | 2 | 명확한 완료 제안과 사용자 승인, 취소의 사용자 확인 |
| 모호성 | 3 | 복수 후보, 모호한 기한, 불명확 완료의 `ASK_USER`와 DB 선반영 0건 |
| 비업무·보안 | 4 | 공지, 뉴스레터·자동발송 제외 기준, Prompt Injection의 `IGNORE` |

성공 조건은 20건 가져오기, 처리 실패 0건, 기대 7 Action 경로 재현, 동일 Thread 오연결 0건,
사용자 확인 전 중요 변경 0건, Secret·불필요한 원문 로그 노출 0건이다. 같은 Label을 즉시
재조회하여 신규 처리 0건과 중복 20건도 별도로 확인한다. 이 시험 전에는 Outlook Live를
다음 완료 단계로 선언하지 않는다.

발송 순서, Thread Reply 관계, INBOUND/OUTBOUND, 비식별 제목·본문, 기대 Action과 사전
분류 기준은 `data/gmail_live_pilot_cases.json`에 20건으로 고정했다. 7 Action 전체 포함,
연속 Sequence와 Secret·실제 주소 비포함은 자동 테스트로 검증한다. 각 본문에는
`GL-001`~`GL-020` 식별자만 넣고, `operations_cli gmail-pilot-report`가 실제 저장 결과의
방향·Thread·Action·사용자 확인 여부를 자동 대조한다. 미수신·미처리 Case는 `PENDING`,
기대값 불일치는 `FAILED`로 남기며 20건 전부 일치할 때만 `PASSED`다.

2026-08-28 별도 송신 Gmail 계정과 제한 Label을 사용한 실제 수용시험을 완료했다.
`SYNC-D841295049BF`에서 GL-001~017·019·020 19건을 신규 처리해 실패 0건을 확인했고,
발신자 제외 Rule을 활성화한 뒤 `SYNC-5FA2F26B1FDA`에서 GL-018 1건만 신규 처리했다.
두 번째 실행은 기존 Mail 21건을 모두 중복으로 차단했다. 최종 Pilot Report는 방향,
Thread, 7 Action, 사용자 확인 여부를 자동 대조해 `20/20 PASSED`, 실패·대기 0건이다.
실메일 과정에서 Gmail 인용 원문 제거, 변경 없는 `TASK_UPDATE`의 `LINK_TO_TASK`,
`추가` 표현의 관련 Task 검색과 최고 Token 점수 후보 제한을 보강했다.

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

### 2026-08-28 Outlook 제외 운영 자동화 진행 증적

- Streamlit 화면과 분리된 `operations_cli sync-gmail` 1회 실행 Command를 구현했다.
- Windows Task Scheduler와 n8n Schedule/Execute Command가 호출할 수 있도록
  `scripts/run_gmail_sync.ps1`을 제공한다.
- stdout은 Mail 본문·Secret을 포함하지 않는 단일 JSON Object이며 Exit Code는
  `0=SUCCESS`, `1=PARTIAL`, `2=FAILED`로 고정했다.
- Timeout·Connection·Rate Limit 계열만 한 번 재시도하고 Validation·정책 오류는 반복하지 않는다.
- `sync_runs`에 가져온 수, 신규·성공·실패·중복·재시도 수와 오류 종류를 저장하고
  Dashboard에서 최근 실행 상태를 확인할 수 있다.
- 실제 n8n 서버 설치, 외부 Webhook과 알림 채널 전송은 수행하지 않았다. 실행 계약과
  운영 절차는 `09_Post_MVP_운영가이드.md`에 분리했다.
- 2026-08-28 실제 제한 Gmail Label에서 운영 CLI를 Live로 실행해
  `SYNC-DC20B21A2F2C`는 가져옴 2·신규 2·성공 2·실패 0,
  즉시 재실행한 `SYNC-8606236AEC71`은 가져옴 2·신규 0·중복 2·실패 0을 확인했다.
  두 번째 실행은 기존 `mail_id`의 LLM·Task 변경을 재실행하지 않았다.

## 6.1 Slack 운영 알림

- 사내 알림 채널은 Slack으로 고정하고 Teams Adapter는 범위에 포함하지 않는다.
- Slack Incoming Webhook은 `.env`의 `SLACK_WEBHOOK_URL`에만 저장하며 기본값은 비활성이다.
- Gmail 동기화가 `PARTIAL` 또는 `FAILED`일 때만 자동 알림 후보가 되며 정상 실행은 알리지 않는다.
- 알림에는 실행 ID, 성공·실패·중복·재시도 건수와 오류 종류만 포함한다.
- Mail ID·원문·Task 제목·사용자 정보·API Key·OAuth Token·Webhook URL은 전송·출력하지 않는다.
- `operations_cli notify-slack`은 기본 Dry-run이며 `--send`와 명시적 활성화가 함께 있을 때만
  실제 Webhook을 호출한다.

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

### 서버 도입 순서 Gate

서버는 AI Master MVP 완료 조건이 아니라 Post-MVP 운영 안정화 단계다. 다음 순서를 바꾸지 않는다.

1. 로컬 테스트 Inbox와 별도 송신 Gmail로 실메일 20건을 송수신하고 자동 평가 `PASSED`
2. 로컬에서 같은 Label 재조회 시 신규 0건·중복 20건 확인
3. 단일 사용자 VM/Application Server에 동일 Commit과 별도 운영 DB 배포
4. 서버 Scheduler 상시 실행, Process 재시작 복구, Health Check, Backup·복원 검증
5. 서버에서 Gmail 제한 Label 수용시험과 장시간 실행 결과 재확인
6. 위 Gate 완료 후 Outlook/Microsoft Graph Live 연결 검토

VM 종류, OS, 사내 DNS·TLS·Proxy·SSO와 Secret 저장 방식이 정해지기 전에는 특정 Cloud나
Container를 구현 완료로 표시하지 않는다. 로컬 Windows Scheduler는 서버 배포 증거가 아니라
개인 파일럿의 백그라운드 실행 증거로만 사용한다.

### 현재 로컬 파일럿 구현

- SQLite Transaction과 `mail_id` 중복 방지 계약을 유지한다.
- Dashboard와 `operations_cli backup`에서 SQLite Online Backup API 기반 복구용 파일을
  생성한다. 자동 덮어쓰기·자동 복원은 하지 않는다.
- Task CSV와 History JSON을 사용자 요청 시에만 내려받을 수 있다. Mail 원문과 Secret은
  해당 내보내기에 포함하지 않는다.
- `operations_cli status`는 활성 Task, Priority 수, 검토 대기와 마지막 동기화 상태를
  기계 판독 가능한 JSON으로 제공한다.
- `operations_cli health`는 DB·LLM 설정·Gmail OAuth 준비 여부를 Secret 없이 확인하고
  `READY`, `DEGRADED`, `FAILED` Exit Code 계약을 제공한다.
- 사내 RDBMS, 다중 사용자 격리, SSO, TLS와 중앙 Monitoring은 회사 표준과 실행환경이
  정해지기 전까지 구현 완료로 표시하지 않는다.

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

### 2026-08-28 P0 구현·검증 증적

- RAG 적용 전 역사적 Core 기준선은 Git Tag `ai-master-mvp-v1`로 복구 가능 상태를 고정했다.
- 실제 업무 모드 Navigation을 `홈`, `내 업무`, `검토 요청`, `자동화 설정`, `운영 상태`, `설정`으로
  재구성했다. Task·검토 중심 사용자 화면과 Gmail 배치·Mail 처리 내역·Agent 단계 로그를
  확인하는 운영 화면을 분리하고, 연결·알림·백업만 `설정`에 유지한다.
- 기한·회신 대기 긴급도와 발신자 Email·Domain·Keyword·사용자 직접 지정 중요도를
  조합하는 설명 가능한 P1~P4 Priority 계산을 구현했다.
- `오늘` 화면에서 Priority 근거와 기한·요청자를 확인하고 Task를 직접 완료할 수 있으며,
  변경은 기존 사용자 수정 경로와 History를 재사용한다.
- 사용자 Rule의 추가·활성화·비활성화·삭제, 기한 임박·회신 대기 기준 설정과 Task별
  중요도 Override를 SQLite에 저장한다.
- Gmail OAuth 연결 후 Agent가 기본 1분 주기로 제한된 Gmail Label을 읽고, 미처리 `mail_id`만
  기존 Agent Core로 처리하도록 변경했다. 사용자는 필요할 때만 사이드바에서 일시정지·재실행한다.
  Gmail 작성·발송·삭제 권한은 추가하지 않았다.
- 제한 Label은 새 업무 유입에만 사용하고, 이미 Task가 생성·연결된 Gmail Thread는 DB의
  `conversation_id`로 후속 Message를 조회하도록 보강했다. 따라서 같은 Thread에서 사용자가
  보낸 회신은 `OUTBOUND`, 상대가 보낸 후속 회신은 `INBOUND`로 계속 처리되며, 보낸편지함
  전체나 연결되지 않은 사적 Mail은 추가 분석하지 않는다.
- `내 업무` 상세에 받은 메일·보낸 메일, 처리 시각, 상대방, Agent Action과 반영 상태를
  시간순으로 표시하는 Mail 진행 타임라인을 추가했다.
- 평소 실제 업무 화면은 저장된 Gmail Mail·Task를 SQLite에서 먼저 읽어 즉시 표시한다. 운영
  DB가 비어 있는 최초 연결에서만 Gmail을 바로 조회하며, 이후 네트워크 갱신은 1분 Fragment와
  Windows Scheduler가 담당하도록 화면 첫 진입과 동기화 책임을 분리했다.
- 추적 중인 Gmail Thread가 삭제되어 API가 404/410을 반환하면 해당 Thread만 건너뛰어 신규
  Mail 수집을 계속한다. 403 권한 오류와 기타 네트워크 오류는 성공으로 숨기지 않는다.
- 기존 Core 회귀와 Post-MVP Priority·UI·자동 동기화 테스트를 함께 실행해 pytest
  `67 passed`를 확인했다. 로컬 Streamlit 서버 기동도 확인했다.
- 브라우저가 열려 있는 단일 사용자 파일럿을 넘어선 서버 상시 실행, Outlook/Graph,
  RAG와 사내 배포는 아직 구현 완료로 표시하지 않는다.

## 11. 현재 범위 밖

- RAG/Vector DB 기반 사내 문서 검색
- Multi-Agent
- 자동 회신·발송
- 조직 전체 Mailbox 처리
- 첨부파일 정밀 분석

향후 실제 비즈니스 요구와 보안 승인, Core 평가 결과로 필요성이 입증될 때 별도 기획한다.

## 12. Outlook 제외 Post-MVP 현재 판정

| 항목 | 현재 판정 | 근거 또는 남은 외부 조건 |
|---|---|---|
| 실제 업무 UI·Task 직접 관리 | 구현·자동 테스트 완료 | 홈/내 업무/검토 요청/자동화 설정/운영 상태/설정, 직접 생성·수정·완료, 업무별 Mail 타임라인·변경 이력, 저장 DB 우선 빠른 시작 |
| Priority·고객사·Keyword Rule | 구현·자동 테스트 완료 | P1~P4, 근거, Override, 설정 저장 |
| 광고·뉴스레터 제외 Rule | 구현·자동 테스트 완료 | 정확한 Email·Domain·제목, IGNORE 근거, 본문 제외 금지 |
| Gmail 화면 자동 확인 | 구현·자동 테스트 완료 | 제한 Label 신규 유입 + Task 연결 Thread 양방향 추적, 신규 mail_id, 1~60분, Read-only |
| 무인 1회 Gmail 동기화 | 구현·자동 테스트 완료 | JSON·Exit Code·제한 재시도·sync_runs |
| 기한·대기 점검 계약 | 구현·자동 테스트 완료 | `operations_cli status`, P1~P4·검토 대기 JSON |
| Health Check | 구현·자동 테스트 완료 | DB·LLM·OAuth 준비 상태, Secret 미출력 |
| Backup·Migration·Task/History Export | 구현·자동 테스트 완료 | SQLite Online Backup 복구, MVP→Post-MVP Schema Migration, CSV/JSON |
| Windows Scheduler·n8n | 로컬 Scheduler 1분 등록·실행 검증, Dashboard·Scheduler 동시 Gmail 실행 단일 잠금, n8n 계약·가이드 완료 | 사내 서버 설치는 회사 정책 확인 필요 |
| 로컬 Dashboard 실행 | 실행 Script 완료 | 상시 서비스 등록·TLS·DNS는 배포환경 필요 |
| 사내 RDBMS·다중 사용자 | 설계 Gate만 완료 | 승인 DB 종류·접속정보·사용자 격리 정책 필요 |
| SSO·권한관리 | 설계 Gate만 완료 | 회사 IdP·App Registration·역할 정책 필요 |
| Slack 사내 알림 | Payload·Dry-run·실패 시 전송 계약 구현 | 실제 Webhook·채널 승인 후 Live 수신 확인 필요 |
| 중앙 Logging·Monitoring | 로컬 Event·sync_runs·Health까지 구현 | 회사 Monitoring 수집 규격·Endpoint 필요 |
| 사내 지식 RAG/Vector DB | 적용하지 않음 | 실제 정책 문서 Corpus와 필요성 없음. SQLite Task Context RAG는 최종 MVP 잔여 범위 |
| 자동 회신·발송·삭제 | 적용하지 않음 | 현재 안전 범위 밖 |
| Outlook Live | 사용자 요청에 따라 제외 | Graph 합성 Adapter Contract만 별도 보존 |

2026-08-29 최신 회귀는 Gmail API Message 형식의 전체 Business/Security Case,
Slack 최소 알림·Dry-run, 6개 역할 기반 운영 UI, Agent 기본 실행·일시정지 계약과 Task 연결
Thread의 양방향 후속 Mail 추적·Task 타임라인과 저장 DB 우선 화면 시작을 포함해 pytest
`122 passed`다. 로컬 SQLite 무결성 오류가 발생하면 자동 처리를 중지하고 백업 복구 절차를
안내하는 Fail-closed UI도 포함한다. 별도 송신
계정 기반 Gmail 실메일 수용시험은 `20/20 PASSED`다.
로컬 Windows 예약 작업 `MailTaskAgent-GmailSync`를 1분 주기로 등록했고 수동 실행 결과
`LastTaskResult=0`, 다음 실행 예약과 Gmail 중복 차단·실패 0건을 확인했다.
Task 연결 Thread 추적을 적용한 Live `SYNC-0BA30F517ECC`도 가져옴 22·신규 0·중복 22·
실패 0으로 완료됐으며, 실제 OUTBOUND 회신이 포함된 Task 타임라인을 브라우저에서 확인했다.
초기 PowerShell 실행 시 나타난 콘솔 창은 예약 작업을 `.venv\Scripts\pythonw.exe` 직접 실행으로
교체해 제거했으며, 교체 후에도 `LastTaskResult=0`과 다음 1분 실행 예약을 확인했다.
