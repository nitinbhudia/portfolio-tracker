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


settings = Settings()
