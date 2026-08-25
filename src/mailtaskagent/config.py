from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_url: str
    api_key: str
    model: str
    api_version: str
    timeout_seconds: float
    use_mock: bool
    database_path: Path
    confidence_threshold: float
    schema_retries: int = 1

    @property
    def llm_mode(self) -> str:
        return "MOCK" if self.use_mock else "LIVE"


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
    api_key = os.getenv("COMPANY_LLM_API_KEY", "").strip()
    raw_db_path = Path(os.getenv("DATABASE_PATH", "data/mailtaskagent.db"))
    database_path = raw_db_path if raw_db_path.is_absolute() else PROJECT_ROOT / raw_db_path
    return Settings(
        api_url=os.getenv("COMPANY_LLM_API_URL", "https://skax.ai-talentlab.com").rstrip("/"),
        api_key=api_key,
        model=os.getenv("COMPANY_LLM_MODEL", "gpt-4.1-mini"),
        api_version=os.getenv("COMPANY_LLM_API_VERSION", "2024-12-01-preview"),
        timeout_seconds=float(os.getenv("COMPANY_LLM_TIMEOUT_SECONDS", "30")),
        use_mock=_as_bool(os.getenv("COMPANY_LLM_USE_MOCK"), default=not bool(api_key)),
        database_path=database_path,
        confidence_threshold=float(os.getenv("AGENT_CONFIDENCE_THRESHOLD", "0.75")),
        schema_retries=max(0, int(os.getenv("COMPANY_LLM_SCHEMA_RETRIES", "1"))),
    )
