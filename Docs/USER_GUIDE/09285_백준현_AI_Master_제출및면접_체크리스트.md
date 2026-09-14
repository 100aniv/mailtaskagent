# 09285 백준현 AI Master 제출 및 면접 체크리스트

## 제출 전 확인

- [x] 최종 제출 커밋과 GitHub `main`이 동일
- [x] 전체 pytest 179개 재실행 통과
- [x] SQLite 운영·시연 DB `integrity_check=ok`
- [x] 회사 LLM Live 15/15 Case, 28/28 Action 결과 확인
- [x] 실제 Gmail 신규 업무 자동 생성과 35/35 중복 방지 증적 확인
- [x] Reply Planning 3/3, 사용자 입력 기반 Draft 1/1과 승인 Gmail 발송 증적 확인
- [x] 발송 전 사용자 승인·원본 Thread·Allowlist 수신자·중복 방지 Guard 확인
- [x] `.env`, OAuth Token, 실제 DB, 개인 메일 본문, 임시 파일이 제출본에서 제외됨
- [x] README의 설치·실행·검증 명령을 깨끗한 환경에서 재현
- [x] AI_MASTER 01~07의 공식 제목·항목 순서 유지
- [x] 문서의 Python 3.12.14, 179 passed, 60.852초가 최신 증적과 일치
- [ ] 발표자료 4장, 발표 10분 이내
- [x] 시연영상 5분 이하, 500MB 이하, MP4
- [x] 파일명 `09285_백준현_시연영상.mp4`
- [x] 최종 영상 2분 50.96초·52.74MB·1600×900, 포인터와 클릭 표시, 전체 디코딩 오류 0 확인
- [x] Git 추적 파일만 사용한 깨끗한 Python 3.12.14 환경에서 179개 테스트와 Gmail 미연결 Streamlit 기동 재현
- [ ] 다른 플레이어에서 영상·음성·자막 재생 확인
- [ ] 7기 최신 업로드 위치·마감·면접 방식은 최종 공지에서 별도 확인

## 30초 프로젝트 설명

> MailTaskAgent는 Gmail의 수신·발신 메일을 업무로 구조화하고 기존 Task와의 관계를 판단해 7개 Task Action 중 다음 행동을 제안하는 개인 업무관리 Agent입니다. 다른 표현의 후속 메일은 SQLite Task Context RAG로 관련 Task와 최근 History를 검색하고, 저신뢰 판단은 Query Rewrite로 한 번 재검토합니다. Python Guard는 위험하거나 모호한 Action을 `ASK_USER`로 전환하고 실행 후 실제 DB 상태를 다시 관찰합니다. 회신이 필요하면 Reply Agent가 7개 회신 방식 중 하나와 필요한 사용자 입력을 선택하고, 회사 LLM Draft를 사용자가 승인한 경우에만 검증된 원본 Gmail Thread로 발송합니다.

## 핵심 면접 질문

### 왜 단순 Workflow가 아니라 Agentic AI인가

현재 Mail과 검색한 Task Context에 따라 경로와 Action이 달라진다. Agent가 관계와 Action을 제안하고, 저신뢰이면 Query를 재작성해 다시 검색·판단한다. 실행 결과를 관찰하고 사용자 결정을 다음 History로 기억한다.

일반 Workflow로 구현할 수 없는 것은 아니다. 확정 가능한 동일 Thread와 안전 정책은 규칙으로 처리하고, 규칙으로 모든 표현을 열거하기 어려운 Task 관계·다음 Action·회신 방식만 LLM Agent에 제한적으로 위임한 하이브리드 구조다.

### 답장 초안 기능도 Agentic AI인가

문장 생성만으로는 생성형 AI 기능이다. 이 프로젝트에서는 Reply Agent가 `NO_REPLY`, `SIMPLE_ACK`, `DATE_REPLY`, `VALUE_REPLY`, `APPROVE_REPLY`, `DRAFT_REPLY`, `ASK_USER` 중 회신 방식을 선택하고 필요한 사용자 입력을 요청한다. 회사 LLM이 확인된 입력으로 Draft를 만들고, Python Guard와 사용자가 발송을 승인하며, 성공 후 OUTBOUND Mail·History와 `WAITING_REPLY`를 관찰하므로 판단과 행동이 연결된다.

### RAG는 무엇을 검색하는가

외부 문서나 Vector DB가 아니라 SQLite의 활성 Task, 제목·설명·요청자·상태·기한, 최근 연결 Mail 최대 3건, History 최대 5건을 검색한다. 현재 데이터 규모와 구조에 맞춘 경량 RAG다.

### Agent와 Python의 역할은 무엇인가

LLM은 Mail 의미와 Task 관계·Action을 제안한다. Python은 후보 ID, Intent, Payload, 상태 전이, 완료·취소·기한 단축 같은 위험 정책을 검증한다. LLM이 DB를 직접 변경하지 않는다.

### 재판단을 왜 한 번만 하는가

표현이 달라 첫 검색이 실패할 때 회복 기회를 주되, 무한 반복·비용 증가·불안정한 자동 변경을 막기 위해 최대 1회로 제한했다. 두 번째도 불확실하면 ASK_USER로 종료한다.

### 신뢰도가 1.0이어도 왜 사용자 승인이 필요한가

신뢰도는 LLM 자기보고 값이며 검증된 정확도 확률이 아니다. 완료, 취소, 기한 단축, 실제 메일 발송은 영향도가 높으므로 정책 기반 승인이 우선한다.

### 실제 발견한 실패와 해결은 무엇인가

실제 Gmail 신규 요청을 회사 LLM이 INBOUND인데 WAITING으로 구조화한 사례를 발견했다. Python Guard가 ASK_USER로 차단해 DB 오변경은 없었다. 이후 direction과 intent의 의미 계약을 재검증하는 재시도를 추가했고, 새 Gmail Root Mail이 사용자 개입 없이 CREATE_TASK 되는 것을 다시 확인했다.

### 179 passed와 Live 15/15는 무엇을 의미하는가

179 passed는 코드 계약과 회귀 테스트 범위를, Live 15/15와 Action 28/28은 정의한 합성 Case에서 회사 LLM 출력이 기대 구조와 단계를 충족했음을 뜻한다. 실제 회사 Mailbox 전체 정확도 100%를 의미하지 않는다.

### AI 도구의 도움과 본인의 역할은 무엇인가

AI 도구는 코드 작성, 비교 검토, 테스트 자동화와 자료 초안을 도왔다. 프로젝트 범위, 7 Action·5 Status, LLM과 Python의 책임 경계, 위험 변경 승인 정책, 실제 Gmail 시나리오와 최종 채택 여부는 요구사항과 실행 증거를 기준으로 결정하고 검증했다.

### Outlook 사내 적용에 무엇이 더 필요한가

Microsoft Graph App Registration, 사내 인증·권한, 운영 서버 또는 VM, 운영 Database, Scheduler 또는 Event Subscription, 중앙 Logging과 Slack 알림, 회사 보안정책 검토가 필요하다. Gmail Adapter로 검증한 Workflow를 유지하고 Mail Adapter를 교체하는 방향이다.

## 설명할 때 피해야 할 표현

- “LLM 신뢰도 1.0이므로 100% 정확합니다.”
- “모든 메일이 RAG를 거칩니다.”
- “같은 Thread에서는 LLM을 전혀 호출하지 않습니다.”
- “Outlook 운영까지 완료했습니다.”
- “메일 한 통이 모든 상태를 순서대로 거쳐야 완료됩니다.”
