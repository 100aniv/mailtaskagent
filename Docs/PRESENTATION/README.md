# MailTaskAgent 발표자료

## 파일 구성

- `AI_MASTER_최종_이해_및_시연가이드.md`: 최종 MVP 구현 범위, 자동 동작, 완료 처리와 5분 시연 순서를 정리한 설명 자료
- `2026-09-02_멘토시연_이해자료_및_스크립트.md`: 내일 시연용 구조 설명, 실행 순서, 발표 대사, 예상 질문과 답변
- `MailTaskAgent_멘토리뷰_2026-08-26.pptx`: 2026-08-26 멘토 리뷰용 설명 자료
- `build_mentor_deck.mjs`: 발표자료를 다시 생성하는 소스

이 자료는 최종 발표본이 아니라 현재 시연 가능한 Core E2E와 Task Context RAG·ReAct,
Agent Action Proposal·Python Safety Guard 구현 증적과 운영 UI 방향을 설명하기 위한 리뷰본이다. 전체 pytest `149 passed`와 Task Context
Agent 회사 LLM Live 합성 검증 `3/3` 결과를 반영했으며 이를 최종 발표자료로 발전시킨다.

## 화면 구분

- 현재 Streamlit UI: 합성 Mail로 기능을 검증하는 시연 화면
- 운영 UI 콘셉트: 자동 동기화된 Mail, 오늘의 업무, 확인 필요, 활동 기록을 중심으로 사용하는 목표 화면

운영 UI 콘셉트 원본은 `prototype/final_ui_mockup.html`에서 확인한다.
