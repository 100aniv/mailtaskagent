# MailTaskAgent 발표자료

## 파일 구성

- **제출본**: `2. 최종/09285_백준현_AI_Master_최종발표자료_v11.pptx` / `_v11.pdf`
  4장 발표자료와 발표자 노트. 같은 폴더의 v3·v6·v7·v9는 작업 이력이며 제출하지 않는다.
- `build_final_deck.mjs`: v11을 다시 만드는 Builder. 장표 문구와 발표자 노트의 단일 출처이며,
  PPTX를 직접 편집하면 다음 빌드에서 조용히 되돌아간다.
  `PRESENTATION_SKILL_DIR`, `PRESENTATION_PYTHON`, `RUNTIME_NODE_MODULES`가 필요하다.
- `build_presentation_pdf.py`: 내보낸 슬라이드 PNG 4장을 제출용 PDF로 합친다.
- `2. 최종/09285_백준현_최종시연_스크립트.md`: 실제 Gmail 중심 5분 시연 대사와 장애 대응
- `../../output/submission/09285_백준현_시연영상.mp4`: 실제 Gmail 업무·후보 비교·Self-Correction·Guard 증적을 담은 2분 33.6초 자막·한국어 Neural 음성 제출 영상
- `../../output/submission/09285_백준현_시연영상_검수.json`: 시간·해상도·용량·전체 디코딩·개인정보·시각 QA 기록
- `AI_MASTER_최종_이해_및_시연가이드.md`: 최종 MVP 구현 범위와 사용자 학습·시연 설명 자료
- `2026-09-02_멘토시연_이해자료_및_스크립트.md`: 2026-09-02 당시 멘토 시연 기록
- `MailTaskAgent_멘토리뷰_2026-08-26.pptx`: 2026-08-26 멘토 리뷰용 설명 자료
- `build_mentor_deck.mjs`: 발표자료를 다시 생성하는 소스

최종 제출 기준은 `2. 최종` 폴더의 v9 PPTX·PDF·시연 스크립트다. 최종 MVP에는 Core E2E,
SQLite Task Context RAG·최대 1회 ReAct 재판단, Agent Action Proposal·Python Safety Guard,
실행 결과 재조회, Reply Agent의 회신 방식 판단·사용자 입력 기반 LLM Draft·사용자 승인 Gmail
발송과 `WAITING_REPLY` 전환이 포함된다. 2026-09-15 최종 기준은 pytest `227 passed`, 회사
LLM 15/15 실행 단위·28/28 Action 단계, Task Context Agent 3/3, Reply Planning 3/3,
Draft 1/1이다. 각 수치는 서로 다른 검증 분모이며 실제 회사 Mailbox 전체 정확도가 아니다.

## 화면 구분

- 실제 업무 모드: 테스트 Gmail 자동 동기화, Task·검토 요청·메일 흐름·회신 준비·운영 상태를 확인하는 기본 화면
- MVP 시연 모드: 실제 업무 DB와 분리된 합성 시나리오·품질 검증 화면

과거 멘토 보고자료와 Prototype은 개발 이력으로 보존하며 현재 최종 제출본으로 사용하지 않는다.

최종 제출 영상은 공식 가이드의 필수 구간을 `1. 시나리오 소개`, `2. Agent 추론 로그 (핵심)`,
`3. 최종 결과 확인` 전면 타이틀로 구분한다. Agent 구간에는 실제 Gmail `processing_events`의
RAG 검색·Context 관찰·Action Proposal·Python Guard·사용자 결정·승인 발송 로그와, 합성·비식별
회사 LLM Live Case의 Query Rewrite 1회 결과를 출처가 섞이지 않도록 구분해 표시한다.
