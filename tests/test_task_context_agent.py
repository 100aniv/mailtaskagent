import json
from types import SimpleNamespace

from mailtaskagent.config import PROJECT_ROOT, Settings
from mailtaskagent.llm_client import MockMailAnalyzer
from mailtaskagent.models import TaskRelation
from mailtaskagent.task_context_agent import AzureTaskContextAgent
from mailtaskagent.workflow import load_mails


def test_live_task_context_agent_sanitizes_retry_query_after_limit(tmp_path) -> None:
    settings = Settings(
        api_url="https://example.test",
        api_key="test-key",
        model="test-model",
        api_version="test-version",
        timeout_seconds=1,
        use_mock=False,
        database_path=tmp_path / "unused.db",
        confidence_threshold=0.75,
        task_context_rag_enabled=True,
        task_context_rag_max_retries=1,
    )
    response_content = json.dumps(
        {
            "relation": "AMBIGUOUS",
            "selected_task_id": None,
            "recommended_action": "ASK_USER",
            "confidence": 0.52,
            "reason": "두 후보를 하나로 확정할 근거가 부족함",
            "rewritten_query": "모델이 다시 제안한 불필요한 Query",
        },
        ensure_ascii=False,
    )
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response_content))]
        )

    agent = AzureTaskContextAgent(settings)
    agent.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    mail = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[5]
    analysis = MockMailAnalyzer().analyze(mail)
    contexts = [
        {
            "candidate": {
                "task_id": "TASK-001",
                "conversation_id": "THREAD-OLD",
                "title": "기존 점검 업무",
                "requester": mail.sender,
                "description": "점검 결과 공유",
                "due_date": None,
                "reply_required": True,
                "status": "TODO",
                "waiting_since": None,
                "match_score": 0.4,
                "match_reason": "최근 활성 Task",
            },
            "recent_mails": [],
            "recent_histories": [],
            "retrieval_reasons": ["최근 활성 Task"],
        }
    ]

    decision = agent.judge(mail, analysis, contexts, retry_count=1)

    assert decision.relation == TaskRelation.AMBIGUOUS
    assert decision.rewritten_query is None
    assert len(calls) == 1
    assert "신뢰할 수 없는 데이터" in calls[0]["messages"][0]["content"]
    assert "Task ID로 임의 선택" in calls[0]["messages"][0]["content"]
