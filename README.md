# MailTaskAgent

현재 Mail, 기존 Mail Context, 현재 Task State를 함께 보고 다음 Agent Action을 결정하는
메일 기반 개인 업무관리 Agent다. 합성 Mail 기반 3단계 Core E2E를 완성하고 회사 LLM API
Live로 상태 흐름과 세부 KPI를 검증했으며, 읽기 전용 Gmail 개인 파일럿까지 확장한 상태다.

> **2026-09-02 상태:** Core E2E에 SQLite 기반 경량 Task Context Agentic RAG, 최대 1회
> Query Rewrite·재판단, Python Guard, 실행 결과 재조회와 안전한 Agent Trace를 결합했다.
> 전체 pytest `136 passed`와 Task Context Agent 회사 LLM Live 합성 검증 `3/3`을 통과했다.
> Outlook·사내 인증·서버와 사내 문서 RAG는 그 이후 Post-MVP다.

## 현재 구현 범위

- 합성·비식별 JSON Mail 입력
- Azure OpenAI 호환 회사 LLM API 또는 명시적인 Mock 분석
- 고정 7 Action Schema와 `CREATE_TASK`, `UPDATE_TASK`, `LINK_TO_TASK`,
  `SET_WAITING`, `MARK_COMPLETED`, `ASK_USER`, `IGNORE` 실행 경로
- `TODO`, `IN_PROGRESS`, `WAITING_REPLY`, `COMPLETED`, `CANCELLED` 상태 전이
- `conversation_id` 우선 기존 Task 매칭과 후보별 점수·근거 표시
- 동일 Thread로 확정할 수 없을 때 SQLite의 활성 Task·최근 Mail 3건·History 5건을
  top-k로 검색하는 Structured Task Context RAG
- 별도 Task Context Agent의 `SAME_TASK`·`NEW_TASK`·`AMBIGUOUS` 관계 판단과 저신뢰 시
  최대 1회 Query Rewrite·재검색, 실패 시 `ASK_USER` Fail-closed
- LLM 제안을 다시 검증하는 Python Guard와 DB 반영 결과 재조회, 검증 가능한 Agent Trace
- Pydantic 구조화 결과 검증
- 잘못된 LLM 구조화 출력 1회 재시도
- SQLite Task/History/중복 처리
- 실제 업무 모드의 `홈`, `내 업무`, `검토 요청`, `자동화 설정`, `운영 상태`, `설정` Dashboard와
  분리된 MVP 시연 화면
- 기한·회신 대기 긴급도와 고객사 Domain·발신자·Keyword·사용자 중요도를 조합한
  설명 가능한 `🔴 즉시 처리`~`⚪ 일반 업무` Priority
- 사용자가 등록한 정확한 발신자 Email·Domain·제목 Keyword의 광고·뉴스레터 제외 Rule,
  LLM 호출 생략과 기존 `IGNORE` 근거 저장
- Gmail 연결 전에는 `실제 업무 모드`와 `MVP 시연 모드`를 선택하고, 연결 후에는 실제 업무
  모드로 바로 진입. MVP 시연 모드는 사이드바에서 열며 실제 업무 DB와 시연 DB를 분리
- Mock 회귀와 회사 LLM Live를 구분한 15개 시나리오 품질 검증 Dashboard
- 2026-08-27 회사 LLM Live 평가 15/15 Case·28/28 Action 단계 일치 증적
- 세부 Ground Truth 기준 업무 요청 분류 15/15, 요청사항·기한 26/26,
  기존 Task 연결 8/8 Live 증적
- 합성메일 미처리 전체 자동 정리와 분류·Action·Task 연결 현황
- 멘토용 빠른 시연 4종을 실제 업무 화면과 분리
- M-01~M-05 단계별 Agent 실행 로그와 오류 추적
- 관련 후보 2개인 Mail의 `ASK_USER` 사용자 확인
- 기존 Task 연결, 신규 Task 생성, 무시 선택 및 사용자 결정 History
- 완료 제안 후 사용자 승인 시에만 `COMPLETED` 반영
- Dashboard에서 Task 제목·설명·기한·상태·회신 필요 여부 직접 수정과 History 저장
- 기대결과를 분리한 대표 Business Case 15개와 제품형 Dashboard·Gmail Adapter Contract,
  운영/시연 모드 및 DB 격리 회귀를 포함한 AI Master MVP pytest 60건
- Post-MVP Priority Rule·사용자 Override·실전 UI·Gmail 자동 동기화, 운영 CLI·재시도·
  SQLite Backup·Mail 제외 Rule과 합성 Microsoft Graph Adapter Contract를 포함한
  Outlook 전 Gmail 전체 Case 수용시험·Slack 최소 알림·6개 역할 기반 운영 UI를 포함한
  Agent 기본 실행·일시정지 통합, Task 연결 Gmail Thread의 양방향 후속 Mail 추적,
  저장 DB 우선 화면 시작·삭제 Thread 장애 격리와 Gmail 실메일 20건 자동 평가를 포함한
  로컬 SQLite 무결성 오류 시 자동 처리 중지·복구 안내와 업무별 변경 이력 UI까지 포함한
  SQLite WAL·동시 동기화 단일 실행 잠금, Task Context RAG·ReAct·Agent Trace까지 포함한
  전체 pytest 136건
- SC-001·002·003 동일 Case의 사람 수동 정리시간과 Live Agent 시간을 비교하는 측정 UI
- 기한 단축은 사용자 날짜 확인·수정 후 승인, 모호한 날짜·완료는 자동 반영 차단
- Core와 분리된 읽기 전용 테스트 Gmail Adapter Contract와 합성 Payload 회귀
- Outlook 전 전체 Business/Security Case의 Gmail API Message→Agent Core 수용시험
- Secret·Mail 원문·Task 제목을 제외한 Slack Incoming Webhook 최소 알림과 Dry-run

## API 키 입력 위치

프로젝트 루트의 `.env` 파일을 열고 아래 줄의 등호 뒤에만 발급받은 키를 입력한다.

```text
COMPANY_LLM_API_KEY=atl-발급받은키
```

키를 채팅, 소스코드, README, 로그에 붙이지 않는다. `.env`는 `.gitignore`에 포함되어 있다.
키가 비어 있으면 Mock 모드, 키가 있으면 LIVE 모드로 자동 전환된다.

현재 설정된 API 정보:

```text
Base URL: https://skax.ai-talentlab.com
API version: 2024-12-01-preview
Model: gpt-4.1-mini
```

## 처음 설치

Python 3.12.13이 설치된 Windows PowerShell에서 실행한다.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

회사 LLM Live 모드를 사용할 때만 `.env`의 `COMPANY_LLM_API_KEY`를 채운다. 키 없이
기능을 확인하려면 `COMPANY_LLM_USE_MOCK=true`로 설정한다. 설치 명령은 프로젝트를
Editable Package로 함께 등록하므로 별도의 `PYTHONPATH` 설정 없이 아래 CLI를 실행할 수 있다.

## 실행

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m streamlit run app.py
.venv\Scripts\python.exe -m mailtaskagent.evaluation_cli --mode MOCK
```

브라우저에서 `http://localhost:8501`을 연다. Gmail 연결 전에는 목적에 맞는 모드를 선택하고,
연결 후에는 실제 업무 모드로 바로 진입한다. 실제 업무 모드는 `홈`, `내 업무`, `검토 요청`,
`자동화 설정`, `운영 상태`, `설정`의 6개 역할 기반 메뉴를 제공하고,
`MVP 시연 모드`는 품질 검증·데모 도구를 별도로 제공한다. 기본 `홈`은 우선순위·검토 요청,
최근 변경과 최근 메일 3건만 보여주고, Agent 실행·Gmail 연결·마지막 확인·오류는 얇은 상태 바로
분리한다. `내 업무`는 내부 Task ID 표 대신 검색·상태 필터·카드·상세 편집·완료 처리를 제공한다.
운영 DB에 처리 이력이 있으면 저장된 화면을 먼저 표시해 매번 Gmail 조회를 기다리지 않는다.
Gmail 연결 후 Agent는 기본 실행되며 사이드바에서 일시정지·재실행할 수 있다. `자동화 설정`에서는
VIP·고객사·중요 키워드, 광고·반복 메일 제외와 실행 주기를 관리한다. Gmail 배치 실행,
메일 처리 내역, Agent 단계 로그와 실메일 20건 진행률은 `운영 상태`에서 확인하고,
`설정`에는 연결·알림·백업만 둔다. 멘토용 재현 버튼은
`데모 도구`로 분리했다. `품질 검증`에서는 Mock 15개
회귀를 즉시 실행하고, LIVE 모드에서는 같은 기대값으로 회사 LLM 결과를 별도 검증할 수 있다.

## Post-MVP 운영 명령

Streamlit 화면이 닫혀 있어도 Windows Task Scheduler 또는 n8n이 아래 1회 실행 명령을
주기적으로 호출할 수 있다.

```powershell
# 제한 Gmail Label 신규 Mail과 Task 연결 Thread의 후속 수신·발신 mail_id 처리
.venv\Scripts\python.exe -m mailtaskagent.operations_cli sync-gmail

# 활성 업무, Priority, 검토 대기와 마지막 동기화 상태
.venv\Scripts\python.exe -m mailtaskagent.operations_cli status

# DB·LLM 설정·Gmail OAuth 준비 상태(Secret 값 미출력)
.venv\Scripts\python.exe -m mailtaskagent.operations_cli health

# data/backups/에 SQLite 복구용 백업 생성
.venv\Scripts\python.exe -m mailtaskagent.operations_cli backup

# Slack Payload만 확인(외부 전송 없음)
.venv\Scripts\python.exe -m mailtaskagent.operations_cli notify-slack

# GL-001~020 실제 저장 결과의 방향·Thread·Action·사용자 확인 자동 대조
.venv\Scripts\python.exe -m mailtaskagent.operations_cli gmail-pilot-report
```

동일 명령의 PowerShell Wrapper는 `scripts/`에 있다. 동기화 stdout은 Mail 본문·Secret을
포함하지 않는 단일 JSON이며 Exit Code는 `0=정상`, `1=일부 실패`, `2=실패`다. 상세 운영
절차와 n8n/Windows Scheduler 계약은 `Docs/IMPLEMENTATION/09_Post_MVP_운영가이드.md`를
참고한다.

Windows 예약 작업은 `.\scripts\manage_scheduler.ps1`로 관리한다. 현재 로컬 파일럿에는
`MailTaskAgent-GmailSync`가 1분 주기로 등록되어 있으며 사이드바의 Agent 상태를 따른다.
콘솔 창이 나타나지 않도록 예약 작업은 `.venv\Scripts\pythonw.exe`로 실행한다.

회사 LLM Live 전체 평가는 API 호출이 발생하므로 필요할 때만 아래처럼 실행한다.

```powershell
.venv\Scripts\python.exe -m mailtaskagent.evaluation_cli --mode LIVE
```

최신 Live 증적은 `evidence/live_evaluation_2026-08-27.json`이며 Prompt 보강 전 결과는
`evidence/live_evaluation_2026-08-27_before_prompt.json`에 분리해 보존한다. 시간 기대효과는
[Microsoft Work Trend Index](https://www.microsoft.com/en-us/worklab/work-trend-index/will-ai-fix-work)와
[McKinsey Global Institute](https://www.mckinsey.com/mgi/media-center/social-media-productivity-payoff)의
Mail·커뮤니케이션 업무 통계를 적용한 외부 Benchmark로 계산한다. 주 40시간·연 48주 기준
주 1.2~2.8시간, 연 57.6~134.4시간의 절감 잠재 시나리오이며 MailTaskAgent 실측값은 아니다.
계산 증적은 `evidence/external_email_time_benchmark_2026-08-27.json`에 저장했다. 향후 실제
사용자 측정을 수행할 경우 수동 Action 6/6인 결과만 실측 KPI 후보로 계산한다.

`데모 도구`에서는 아래 흐름을 한 번에 실행할 수 있다.

- 신규 업무 생성 -> 후속 기한 변경
- 자료 요청 -> 회신 대기 -> 자료 도착 후 업무 재개
- 후보 2개 -> `ASK_USER` -> 사용자 최종 선택
- 완료 제안 -> 사용자 승인 -> `COMPLETED`

현재 버튼은 합성 Mail 도착을 재현하는 테스트 트리거다. 테스트 Gmail은 Core MVP 이후
읽기 전용 연결과 Live E2E, 화면이 열린 동안의 제한 Label 자동 정리를 구현했다. Microsoft
Graph는 Inbox/Sent Items 합성 Payload를 공통 Mail Schema로 바꾸는 읽기 전용 Adapter
Contract까지 구현했으며, 실제 회사 Tenant OAuth와 Live 호출은 권한 승인 후 진행한다.
n8n과 iCloud Mail은 현재 구현 완료 범위에 포함하지 않는다.

## 선택적 테스트 Gmail Adapter

읽기 전용 Gmail Adapter의 코드와 합성 Gmail API Payload 테스트를 구현했다. 2026-08-27
별도 테스트 계정에 OAuth 읽기 전용으로 연결하고, `MailTaskAgent-Demo` 라벨의 비식별 합성
Mail 2건을 회사 LLM Live Agent Core로 처리해 `CREATE_TASK` 후 동일 Thread의
`UPDATE_TASK`와 기한 변경을 검증했다. Agent Core와 SQLite 구조는 변경하지 않았다.

Google 공식 Python Quickstart 방식으로 Gmail API와 Desktop OAuth Client를 준비한 뒤 진행한다.

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-gmail.txt
```

다운로드한 OAuth Client JSON은 채팅이나 GitHub에 올리지 말고 아래 로컬 경로에만 둔다.

```text
.secrets/gmail_credentials.json
```

`.secrets/`는 Git에서 제외된다. 처음 실행할 때 브라우저에서 사용자가 직접 읽기 전용 권한을
승인하면 `.secrets/gmail_token.json`이 생성된다.

```powershell
# 제목·방향·시각만 확인하고 Agent는 실행하지 않음
.venv\Scripts\python.exe -m mailtaskagent.gmail_cli

# 확인한 합성 Gmail을 기존 Agent Core로 처리
.venv\Scripts\python.exe -m mailtaskagent.gmail_cli --process
```

기본 쿼리 `label:MailTaskAgent-Demo`, 최대 25건이며 빈 쿼리와 100건 초과 입력은 차단한다.
Gmail 연결 후 Agent는 기본 1분 주기로 제한 Label을 확인하고, SQLite에 처리 결과가 없는
새 `mail_id`만 기존 Agent Core로 넘긴다. 한 번 Task로 연결된 Gmail Thread는 이후 Label
상속 여부와 관계없이 Inbox·Sent 후속 Message를 함께 조회하므로 보낸 회신도 업무 상태에
이어진다. 보낸편지함 전체는 분석하지 않는다. 사이드바에서 일시정지·재실행할 수 있다.
화면이 열려 있을 때는 Streamlit Polling이 동작하고, 등록된 로컬 Scheduler는 화면이 닫혀도
같은 1회 동기화 명령을 실행한다. Gmail 작성·발송·삭제 권한은 사용하지 않는다. 서버 상시
실행과 Outlook/Microsoft Graph는 후속 사내 적용 단계다.
실제 Gmail Live E2E 증적은 `evidence/gmail_live_e2e_2026-08-27.json`에 저장한다.
공식 참고 문서는 [Gmail API Python Quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python)와
[messages.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)다.

## Outlook / Microsoft Graph Adapter Contract

현재는 실제 회사 Mailbox에 접속하지 않고 합성 Graph `message` Payload로 Inbox·Sent Items,
Conversation, 발신자·수신자, 시각과 Text/HTML 본문을 공통 `MailInput`으로 정규화한다.
목록 요청은 `/me/mailFolders/{folder}/messages`와 필요한 속성의 `$select`, 최대 100건
`$top`만 사용하도록 Contract Test로 고정했다.

실제 연결에는 회사 Microsoft Entra App Registration과 Signed-in User Delegated
`Mail.Read` 승인이 필요하다. `Mail.ReadBasic`은 메일 본문을 읽을 수 없어 Agent 분석에
부족하며, 초기 파일럿에는 `Mail.ReadWrite`와 `Mail.Send`를 요청하지 않는다. 실제 Token과
Client 정보는 `.secrets/` 또는 회사 Secret 관리 방식으로만 보관한다. 참고 문서는
[Microsoft Graph List messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0)와
[Permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)다.

내일 시연 설명과 순서는 `Docs/IMPLEMENTATION/08_멘토_시연_브리핑.md`를 참고한다.

멘토 리뷰용 발표자료는 `Docs/PRESENTATION/MailTaskAgent_멘토리뷰_2026-08-26.pptx`,
운영 UI 콘셉트는 `prototype/final_ui_mockup.html`에서 확인한다.
