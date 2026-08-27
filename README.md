# MailTaskAgent

현재 Mail, 기존 Mail Context, 현재 Task State를 함께 보고 다음 Agent Action을 결정하는
메일 기반 개인 업무관리 Agent다. 현재는 합성 Mail 기반 3단계 Core E2E를 구현하고
회사 LLM API Live로 상태 흐름과 세부 KPI를 검증한 상태다.

## 현재 구현 범위

- 합성·비식별 JSON Mail 입력
- Azure OpenAI 호환 회사 LLM API 또는 명시적인 Mock 분석
- 고정 7 Action Schema와 `CREATE_TASK`, `UPDATE_TASK`, `LINK_TO_TASK`,
  `SET_WAITING`, `MARK_COMPLETED`, `ASK_USER`, `IGNORE` 실행 경로
- `TODO`, `IN_PROGRESS`, `WAITING_REPLY`, `COMPLETED`, `CANCELLED` 상태 전이
- `conversation_id` 우선 기존 Task 매칭과 후보별 점수·근거 표시
- Pydantic 구조화 결과 검증
- 잘못된 LLM 구조화 출력 1회 재시도
- SQLite Task/History/중복 처리
- `오늘의 업무` 요약·우선순위·주의 항목을 중심으로 한 제품형 업무 현황과
  메일 처리함, 확인 필요, 운영 로그 Dashboard
- 첫 화면에서 `실제 업무 모드`와 `MVP 시연 모드` 선택, 동일 Agent Core를 사용하되
  실제 업무 DB와 시연 DB를 분리하여 합성 시연 데이터가 운영 화면에 섞이지 않도록 구성
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
  운영/시연 모드 및 DB 격리 회귀를 포함한 pytest 60건
- SC-001·002·003 동일 Case의 사람 수동 정리시간과 Live Agent 시간을 비교하는 측정 UI
- 기한 단축은 사용자 날짜 확인·수정 후 승인, 모호한 날짜·완료는 자동 반영 차단
- Core와 분리된 읽기 전용 테스트 Gmail Adapter Contract와 합성 Payload 회귀

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

브라우저에서 `http://localhost:8501`을 열고 첫 화면에서 목적에 맞는 모드를 선택한다.
`실제 업무 모드`는 업무 현황·메일 처리함·확인 필요·운영 로그만 제공하고, `MVP 시연 모드`는
품질 검증·데모 도구를 추가로 제공한다. 기본 `업무 현황`은 `오늘의 업무` 요약,
우선 처리 업무, 기한·회신 대기 주의 항목과 확인 대기 건을 먼저 보여준다. `메일 처리함`에서는
Source로 들어온 합성메일 전체의 분류와 처리 결과를 확인하거나 미처리 메일을 한 번에 자동
정리할 수 있다. 멘토용 재현 버튼은 `데모 도구`로 분리했다. `품질 검증`에서는 Mock 15개
회귀를 즉시 실행하고, LIVE 모드에서는 같은 기대값으로 회사 LLM 결과를 별도 검증할 수 있다.

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

현재 버튼은 합성 Mail 도착을 재현하는 테스트 트리거다. 실제 Outlook/Microsoft Graph와
n8n 자동 수집은 Core E2E 완성 후 Post-MVP에서 공통 Mail Schema Adapter로 연결한다.
테스트 Gmail은 Core MVP 이후 선택적 고도화로 연결과 Live E2E 검증을 완료했다. iCloud Mail은
현재 확정 범위에 포함하지 않는다.

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
실제 Gmail Live E2E 증적은 `evidence/gmail_live_e2e_2026-08-27.json`에 저장한다.
공식 참고 문서는 [Gmail API Python Quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python)와
[messages.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)다.

내일 시연 설명과 순서는 `Docs/IMPLEMENTATION/08_멘토_시연_브리핑.md`를 참고한다.

멘토 리뷰용 발표자료는 `Docs/PRESENTATION/MailTaskAgent_멘토리뷰_2026-08-26.pptx`,
운영 UI 콘셉트는 `prototype/final_ui_mockup.html`에서 확인한다.
