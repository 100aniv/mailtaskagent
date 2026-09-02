# 09. Post-MVP 운영 가이드

## 1. 목적과 현재 경계

이 문서는 Outlook Live 연동을 제외한 단일 사용자 Post-MVP 파일럿의 실행·점검·복구 방법을 정리한다. Agent 의미 판단은 기존 M-01~M-03이 담당하고, Windows Task Scheduler 또는 n8n은 정해진 명령을 주기적으로 호출하는 역할만 담당한다.

회사 SSO, 다중 사용자, 사내 승인 RDBMS, 중앙 Monitoring과 실제 알림 채널은 회사 인프라·권한이 확보되기 전까지 구현 완료로 간주하지 않는다.

## 2. 실행 구조

```text
Windows Task Scheduler 또는 n8n Schedule
-> scripts/run_gmail_sync.ps1
-> operations_cli sync-gmail
-> 제한된 Gmail Label 신규 유입 + Task 연결 Gmail Thread Read-only 조회
-> 신규 mail_id만 기존 Agent Core 실행
-> SQLite Task/History/Processing Event
-> sync_runs 운영 결과 저장

사용자 Browser
-> scripts/run_dashboard.ps1
-> Streamlit 실제 업무 모드
-> 홈/내 업무/검토 요청/자동화 설정/운영 상태/설정
```

## 3. 운영 명령 계약

### Gmail 1회 동기화

```powershell
.\scripts\run_gmail_sync.ps1
```

또는:

```powershell
.venv\Scripts\python.exe -m mailtaskagent.operations_cli sync-gmail
```

표준 출력은 한 개의 JSON Object이며 Mail 본문, API Key, OAuth Token을 포함하지 않는다.

신규 업무 후보는 제한 Label에서만 들어온다. 해당 Mail이 Task로 생성되거나 기존 Task에
연결되면 이후 실행부터 DB의 Gmail `conversation_id`로 정확한 Thread를 함께 조회한다. 이때
Inbox와 Sent Message를 모두 정규화하므로 사용자가 보낸 회신과 상대방의 후속 회신이 같은
Task에 이어진다. 보낸편지함 전체를 별도로 조회하지 않는다.

```json
{
  "run_id": "SYNC-...",
  "source": "GMAIL",
  "status": "SUCCESS",
  "fetched_count": 2,
  "pending_count": 1,
  "succeeded_count": 1,
  "failed_count": 0,
  "duplicate_count": 1,
  "retry_count": 0,
  "failed_mail_ids": [],
  "error_type": null
}
```

Exit Code는 `0=SUCCESS`, `1=PARTIAL`, `2=FAILED`다. Timeout, Connection, Rate Limit 계열만 한 번 재시도하며 Validation·정책 오류는 반복 실행하지 않는다.

### 업무·운영 상태 확인

```powershell
.\scripts\run_status.ps1
```

활성 Task, P1~P4 수, 사용자 검토 대기, 마지막 동기화 상태를 JSON으로 반환한다. Mail 원문은 포함하지 않는다. Task 제목은 업무정보이므로 외부 Webhook이나 공개 채널로 전송하지 않는다.

### Health Check

```powershell
.\scripts\run_health.ps1
```

로컬 DB, LLM 실행 설정, Gmail OAuth Credentials·Token 준비 여부와 마지막 동기화 상태를
JSON으로 반환한다. `READY`는 Exit Code 0, 준비가 부족한 `DEGRADED`는 Exit Code 1,
실행 자체가 실패한 경우는 Exit Code 2다. Key·Token 값과 경로 내용은 출력하지 않는다.

2026-08-28 로컬 파일럿에서 Health Check `READY`와 제한 Gmail Label Live 동기화
성공 2건을 확인했다. 같은 Source를 즉시 재실행했을 때 신규 0건·중복 2건으로 집계되어
LLM과 Task 변경이 재실행되지 않았다.

2026-08-29 Task 연결 Gmail Thread의 Inbox·Sent 조회를 적용한 뒤 Live 동기화
`SYNC-0BA30F517ECC`에서 가져옴 22·신규 0·중복 22·실패 0을 확인했다.

같은 날 별도 송신 계정을 사용한 실메일 20건 수용시험은 방향·Thread·7 Action·사용자
확인 여부 `20/20 PASSED`, 처리 실패 0건으로 완료했다. 마지막 GL-018 단독 동기화는
신규 1건·성공 1건·기존 21건 중복 차단을 확인했다. Dashboard `운영 상태`의
`Gmail 실메일 수용시험`에서도 20/20 결과를 확인할 수 있다.

### Dashboard 실행

```powershell
.\scripts\run_dashboard.ps1
```

기본 주소는 `http://localhost:8501`이다. Streamlit 내부 자동 확인은 화면이 열려 있는 파일럿 편의 기능이며, 무인 실행은 위 1회 동기화 명령을 Scheduler가 호출하는 방식으로 분리한다.

Dashboard와 Scheduler가 같은 시각에 동기화를 시작하면 운영 DB별 OS 파일 잠금으로 한 실행만
진행하고 다른 실행은 `SKIPPED`·`SyncAlreadyRunning`으로 종료한다. 잠금은 Process 종료 시
운영체제가 해제하므로 비정상 종료 뒤에도 오래된 잠금 파일 때문에 자동수집이 영구 중단되지 않는다.

운영 DB에 처리 Mail이 있으면 Dashboard는 SQLite 데이터를 먼저 표시하고 Gmail 응답을 기다리지
않는다. DB가 비어 있는 최초 연결에서만 제한 Label을 즉시 조회한다. 이후 화면 갱신은 1분
Fragment, 화면이 닫힌 동안의 수집은 Windows Scheduler가 같은 동기화 명령으로 담당한다.

### SQLite 백업

```powershell
.venv\Scripts\python.exe -m mailtaskagent.operations_cli backup
```

기본 백업은 `data/backups/`에 생성되며 Git에서 제외된다. Dashboard의 `연결 및 설정`에서도 동일한 복구용 백업을 생성할 수 있다.
기존 MVP SQLite 파일은 Application 시작 시 Post-MVP Column과 운영 Table을 자동 추가하며,
기존 Task 데이터는 삭제하지 않는다. 이 Migration과 Backup 복구 가능성은 자동 테스트로 검증한다.

### Slack 알림 미리보기와 전송

기본 명령은 외부로 전송하지 않고, 실제 Payload에 Mail 원문·Task 제목·Secret이 없는지 확인한다.

```powershell
.venv\Scripts\python.exe -m mailtaskagent.operations_cli notify-slack
```

승인된 Slack Incoming Webhook을 `.env`에 입력하고 알림을 활성화한 뒤에만 실제 전송한다.

```text
SLACK_NOTIFICATIONS_ENABLED=true
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

```powershell
.venv\Scripts\python.exe -m mailtaskagent.operations_cli notify-slack --send
```

Webhook URL은 Secret이므로 채팅·GitHub·로그·화면에 붙이지 않는다. Gmail 동기화의 자동
Slack 알림은 `PARTIAL`·`FAILED`에만 시도하며 정상 실행은 알리지 않는다.

2026-08-28 `SYNC-2C70870653B4` 재검증은 제한 Gmail 2건을 모두 중복으로 판정해 LLM과
Task 변경을 재실행하지 않았고, 정상 실행의 Slack 상태는 `NOT_REQUIRED`였다.

## 4. Windows Task Scheduler 연결

먼저 실제 시스템을 변경하지 않는 Preview를 확인한다.

```powershell
.\scripts\manage_scheduler.ps1 -Mode Preview -IntervalMinutes 1
```

회사 정책과 API 호출 주기를 확인한 뒤에만 사용자가 아래 Install을 실행한다.

```powershell
.\scripts\manage_scheduler.ps1 -Mode Install -IntervalMinutes 1
```

중지·제거:

```powershell
.\scripts\manage_scheduler.ps1 -Mode Remove
```

1. 로컬 Windows 예약 작업은 콘솔 창이 나타나지 않도록 `.venv\Scripts\pythonw.exe`를 사용한다.
2. 인수는 `-m mailtaskagent.operations_cli sync-gmail`을 사용한다. 수동 점검과 n8n 호출은 기존 `run_gmail_sync.ps1`을 유지한다.
3. 시작 위치는 프로젝트 루트로 지정한다.
4. 로컬 실전 파일럿은 1분 Polling으로 시작하며 새 `mail_id`만 LLM을 호출한다.
5. 사이드바에서 Agent를 일시정지하면 Scheduler도 `PAUSED`로 종료하고 Gmail·LLM을 호출하지 않는다.
6. Exit Code가 1 또는 2일 때만 운영자가 확인하도록 설정한다.
7. SQLite는 WAL Journal, 30초 `busy_timeout`, Foreign Key 검사와 `synchronous=FULL`을 사용한다.
   Scheduler 중복 실행은 위 단일 실행 잠금으로 차단하고, Dashboard의 Task 수정과 짧게 겹치는
   쓰기는 SQLite가 대기 후 순차 반영한다.

2026-09-01 운영 DB 복구 후 위 동시 실행 방어를 적용했다. 당시 전체 pytest `122 passed`, Health
Check `READY`, 실제 Gmail 재조회 가져옴 26·신규 0·중복 26·실패 0, SQLite `quick_check=ok`와
WAL 적용을 확인한 뒤 1분 Scheduler를 재등록했다. 당시 손상 파일은 원인 분석을 위해 별도
보존하고 정상 백업을 새로 생성했으며, 확인되지 않은 단일 원인을 단정하지 않는다.

2026-09-02 Task Context RAG·최대 1회 ReAct 재판단·Agent Action Proposal·Python Safety Guard·
Agent Trace를 추가한 뒤 기존 운영 방어를 포함한 전체 회귀는 `149 passed`다.

2026-09-02 최종 Acceptance 재점검 중 운영 DB 손상을 실제로 감지해 Scheduler를 즉시 중지하고
손상 원본을 `data/recovery/`에 보존했다. `quick_check=ok`인 최신 백업으로 복구한 뒤
`integrity_check=ok`, Health Check `READY`, Gmail Pilot `20/20 PASSED`, Gmail 재조회
가져옴 26·신규 0·중복 26·실패 0을 확인했다. 이후 Streamlit `HTTP 200`, Scheduler 수동
예약 실행 `LastTaskResult=0`과 새 정상 백업 생성을 확인한 뒤 1분 Scheduler를 재활성화했다.
이는 자동 복원이 아니라 원본 보존·검증된 백업 복구·재검증 절차를 실제로 수행한 결과다.

2026-08-28 현재 로컬 파일럿에는 `MailTaskAgent-GmailSync`가 1분 주기로 등록되어 있다.
수동 실행 결과 `LastTaskResult=0`과 다음 실행 예약을 확인했으며, 최신 실행은 제한 Gmail
2건을 모두 중복으로 처리해 신규·실패 0건이었다. 다른 PC나 사내 서버 등록은 실행 계정과
회사 보안정책을 확인한 뒤 수행한다.

초기 등록에서 `powershell.exe`가 1분마다 콘솔 창을 잠깐 표시하는 문제가 확인되어 예약 작업의
실행 파일을 콘솔 없는 `.venv\Scripts\pythonw.exe`로 변경했다. 처리 결과와 오류는 stdout 대신
기존 SQLite `sync_runs`와 Processing Event, Dashboard에서 확인한다.

## 5. n8n 연결 계약

- Schedule Trigger 뒤에 Execute Command 또는 회사 승인 Runner로 `run_gmail_sync.ps1`을 1회 실행한다.
- stdout JSON의 `status`, `failed_count`, `error_type`만 분기 조건으로 사용한다.
- LLM 판단, Keyword 분류, Task 상태 변경을 n8n Node에서 다시 구현하지 않는다.
- `.env`, OAuth Token, Mail 본문과 Task 제목을 n8n Credential·Execution Log에 복사하지 않는다.
- 재시도는 CLI 내부의 제한된 1회와 n8n 외부 재시도를 중복 적용하지 않는다.

## 6. 장애 확인과 복구

1. Dashboard `운영 상태`의 최근 자동 실행 기록에서 상태와 오류 종류를 확인한다.
   Dashboard 시작 시 SQLite 무결성 오류가 감지되면 자동 처리를 중지하고 원본 보존·백업
   복구 안내만 표시한다. 오류 화면에서 자동 복원이나 DB 덮어쓰기는 수행하지 않는다.
2. `활동 기록`에서 실패 Mail의 마지막 Processing Event를 확인한다.
3. 인증·권한 오류는 자동 반복하지 않고 OAuth 상태를 확인한다.
4. Timeout·Connection·Rate Limit은 다음 Scheduler 실행에서 신규·실패 Mail만 다시 처리한다.
5. DB 복구가 필요하면 Dashboard를 종료하고 최신 `data/backups/*.db`를 별도 검증한 뒤 복구한다. 자동 덮어쓰기는 제공하지 않는다.
6. 실행 중인 Dashboard나 Scheduler가 SQLite를 열고 있을 때 DB 파일을 직접 덮어쓰지 않는다.
   두 프로세스를 먼저 중지하고 `PRAGMA integrity_check`가 `ok`인 백업만 복원한 뒤 재가동한다.
7. 반복 수용시험은 운영 DB를 교체하지 않고 별도 `DATABASE_PATH`의 격리 DB에서 수행한 뒤,
   통과본만 위 중지·무결성 확인 절차에 따라 반영한다.

## 7. 보안·운영 Gate

- Gmail은 제한 Label, 최대 건수, Read-only Scope를 유지한다.
- Task 연결 Thread 조회는 Gmail `conversation_id`만 사용하고 최대 100개로 제한한다.
- 사용자가 삭제한 연결 Thread의 404/410은 해당 Thread만 건너뛰며, 인증·권한·네트워크 오류는
  전체 실행 실패로 기록해 운영자가 확인할 수 있게 한다.
- 회사 LLM 전송 가능 Mail 범위를 별도로 승인받는다.
- 실제 업무 DB와 MVP 시연 DB를 분리한다.
- 외부 알림을 연결하기 전 수신자·채널·전송 필드를 승인받는다.
- 사내 알림 채널은 Slack으로 한정하며 Mail 원문·Task 제목·사용자 정보는 보내지 않는다.
- SSO·다중 사용자·사내 RDBMS·TLS·중앙 로그는 회사 표준이 결정된 후 Adapter로 연결한다.
- 자동 회신·발송·삭제·이동은 현재 제공하지 않는다.
