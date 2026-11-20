"""Application settings from environment variables (.env). No secrets are needed in Phase 1."""
from datetime import date
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(BACKEND_DIR.parent / ".env"), extra="ignore")

    database_url: str = f"sqlite:///{BACKEND_DIR / 'fibonacci_ai.db'}"
    synthetic_end_date: date = date(2025, 12, 31)
    synthetic_days: int = 600
    base_currency: str = "USD"
    default_sensitivity: str = "medium"
    gap_threshold_business_days: int = 2
    stale_after_business_days: int = 3

    # IBKR Flex Web Service (read-only reports). Secrets: environment / .env only.
    ibkr_flex_token: SecretStr | None = None
    ibkr_flex_query_id: str | None = None
    broker_sync_cooldown_seconds: int = 60

    # Tiingo end-of-day prices (US). Secret: environment / .env only.
    tiingo_api_key: SecretStr | None = None

    # EODHD end-of-day prices (Europe). Secret: environment / .env only. The token travels in the
    # URL (EODHD's only method), so it is redacted from every error and never logged.
    eodhd_api_key: SecretStr | None = None
    eodhd_daily_budget: int = 1000


def _make() -> Settings:
    from app import demo
    if not demo.DEMO:
        return Settings()
    # Demo mode: never read .env (your keys) and never open your real database. The "demo" keys only switch the
    # price features on: every request is answered by app.demo.network with synthetic data, so nothing leaves.
    return Settings(_env_file=None, database_url=f"sqlite:///{demo.RESEARCH_DB}", tiingo_api_key="demo",
                    eodhd_api_key="demo", ibkr_flex_token=None, ibkr_flex_query_id=None)


settings = _make()
