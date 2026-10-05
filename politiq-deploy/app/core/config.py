from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("database_url")
    @classmethod
    def _asyncpg(cls, v: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+asyncpg://" + v[len(prefix):]
        return v

    cors_origins: list[str] = []

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"

    # Prices in paise. PLACEHOLDERS - set real pricing via env. 0 => checkout disabled.
    price_report_unlock_paise: int = 0
    price_subscription_monthly_paise: int = 0
    report_entitlement_days: int = 30
    subscription_days: int = 30

    upload_dir: str = "./uploads"
    max_upload_mb: int = 50
    rate_limit_public_per_min: int = 60
    rate_limit_paid_per_min: int = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()

AI_DISCLAIMER = "AI-assisted analysis - not official data. Verify against ECI / primary sources."
