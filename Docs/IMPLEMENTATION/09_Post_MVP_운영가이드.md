# 09. Post-MVP 운영 가이드

## 1. 목적과 현재 경계

이 문서는 Outlook Live 연동을 제외한 단일 사용자 Post-MVP 파일럿의 실행·점검·복구 방법을 정리한다. Agent 의미 판단은 기존 M-01~M-03이 담당하고, Windows Task Scheduler 또는 n8n은 정해진 명령을 주기적으로 호출하는 역할만 담당한다.

회사 SSO, 다중 사용자, 사내 승인 RDBMS, 중앙 Monitoring과 실제 알림 채널은 회사 인프라·권한이 확보되기 전까지 구현 완료로 간주하지 않는다.

## 2. 실행 구조

```text
Windows Task Scheduler 또는 n8n Schedule
-> scripts/run_gmail_sync.ps1
-> operations_cli sync-gmail
-> 제한된 Gmail Label Read-only 조회
-> 신규 mail_id만 기존 Agent Core 실행
-> SQLite Task/History/Processing Event
-> sync_runs 운영 결과 저장

사용자 Browser
-> scripts/run_dashboard.ps1
-> Streamlit 실제 업무 모드
-> 오늘/내 업무/검토 필요/메일/활동 기록/연결 및 설정
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

### Dashboard 실행

```powershell
.\scripts\run_dashboard.ps1
```

기본 주소는 `http://localhost:8501`이다. Streamlit 내부 자동 확인은 화면이 열려 있는 파일럿 편의 기능이며, 무인 실행은 위 1회 동기화 명령을 Scheduler가 호출하는 방식으로 분리한다.

### SQLite 백업

```powershell
.venv\Scripts\python.exe -m mailtaskagent.operations_cli backup
```

기본 백업은 `data/backups/`에 생성되며 Git에서 제외된다. Dashboard의 `연결 및 설정`에서도 동일한 복구용 백업을 생성할 수 있다.

## 4. Windows Task Scheduler 연결

1. 프로그램은 `powershell.exe`를 선택한다.
2. 인수는 `-NoProfile -ExecutionPolicy Bypass -File "<프로젝트 절대경로>\scripts\run_gmail_sync.ps1"`를 사용한다.
3. 시작 위치는 프로젝트 루트로 지정한다.
4. 초기 주기는 5~10분으로 제한한다.
5. Exit Code가 1 또는 2일 때만 운영자가 확인하도록 설정한다.

실제 Scheduler 등록은 사용자 PC의 실행 계정과 회사 보안정책을 확인한 뒤 수행한다.

## 5. n8n 연결 계약

- Schedule Trigger 뒤에 Execute Command 또는 회사 승인 Runner로 `run_gmail_sync.ps1`을 1회 실행한다.
- stdout JSON의 `status`, `failed_count`, `error_type`만 분기 조건으로 사용한다.
- LLM 판단, Keyword 분류, Task 상태 변경을 n8n Node에서 다시 구현하지 않는다.
- `.env`, OAuth Token, Mail 본문과 Task 제목을 n8n Credential·Execution Log에 복사하지 않는다.
- 재시도는 CLI 내부의 제한된 1회와 n8n 외부 재시도를 중복 적용하지 않는다.

## 6. 장애 확인과 복구

1. Dashboard `연결 및 설정`의 최근 자동 실행 기록에서 상태와 오류 종류를 확인한다.
2. `활동 기록`에서 실패 Mail의 마지막 Processing Event를 확인한다.
3. 인증·권한 오류는 자동 반복하지 않고 OAuth 상태를 확인한다.
4. Timeout·Connection·Rate Limit은 다음 Scheduler 실행에서 신규·실패 Mail만 다시 처리한다.
5. DB 복구가 필요하면 Dashboard를 종료하고 최신 `data/backups/*.db`를 별도 검증한 뒤 복구한다. 자동 덮어쓰기는 제공하지 않는다.

## 7. 보안·운영 Gate

- Gmail은 제한 Label, 최대 건수, Read-only Scope를 유지한다.
- 회사 LLM 전송 가능 Mail 범위를 별도로 승인받는다.
- 실제 업무 DB와 MVP 시연 DB를 분리한다.
- 외부 알림을 연결하기 전 수신자·채널·전송 필드를 승인받는다.
- SSO·다중 사용자·사내 RDBMS·TLS·중앙 로그는 회사 표준이 결정된 후 Adapter로 연결한다.
- 자동 회신·발송·삭제·이동은 현재 제공하지 않는다.
