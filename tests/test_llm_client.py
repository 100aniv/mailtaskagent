import json
from types import SimpleNamespace

from mailtaskagent.config import PROJECT_ROOT, Settings
from mailtaskagent.llm_client import AzureMailAnalyzer
from mailtaskagent.models import MailIntent
from mailtaskagent.workflow import load_mails


def test_live_analyzer_retries_once_after_invalid_structured_output(tmp_path) -> None:
    settings = Settings(
        api_url="https://example.test",
        api_key="test-key",
        model="test-model",
        api_version="test-version",
        timeout_seconds=1,
        use_mock=False,
        database_path=tmp_path / "unused.db",
        confidence_threshold=0.75,
        schema_retries=1,
    )
    valid_content = json.dumps(
        {
            "is_task_request": False,
            "intent": "NON_TASK",
            "task_title": None,
            "request_summary": None,
            "requester": None,
            "due_date": None,
            "reply_required": False,
            "reason": "일반 공지",
            "confidence": 0.99,
        }
    )
    contents = iter(["not-json", valid_content])
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(contents)))]
        )

    analyzer = AzureMailAnalyzer(settings)
    analyzer.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    mail = load_mails(PROJECT_ROOT / "data" / "dummy_mails.json")[4]

    result = analyzer.analyze(mail)

    assert result.intent == MailIntent.NON_TASK
    assert len(calls) == 2
