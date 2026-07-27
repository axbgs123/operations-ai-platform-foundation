from functools import lru_cache
from typing import Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_MODEL_SECRET_ENCRYPTION_KEY = (
    "local-development-model-secret-change-me"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_mock_mode: bool = True
    database_url: str = (
        "postgresql+psycopg://operations_ai:local-development-only"
        "@localhost:55432/operations_ai"
    )
    web_origin: str = "http://localhost:3000"
    redis_url: str = "redis://localhost:6379/0"
    trusted_proxy_ips: str = ""
    rate_limit_auth_per_minute: int = 10
    rate_limit_ai_per_minute: int = 20
    rate_limit_upload_per_minute: int = 30
    rate_limit_export_per_five_minutes: int = 10
    rate_limit_destructive_per_ten_minutes: int = 5
    rate_limit_demo_factor: float = 0.25
    s3_endpoint: str = "http://localhost:9000"
    s3_public_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "operations-ai"
    s3_access_key: str = "operations-ai"
    s3_secret_key: str = "local-development-only"
    storage_signing_secret: str = "local-development-signing-secret-change-me"
    analysis_adapter_url: str | None = None
    analysis_adapter_token: str | None = None
    analysis_model_version: str = "configured-analysis-v1"
    analysis_request_timeout_seconds: float = 30.0
    readiness_timeout_seconds: float = 2.0
    model_secret_encryption_key: SecretStr = SecretStr(
        DEFAULT_MODEL_SECRET_ENCRYPTION_KEY
    )

    @model_validator(mode="after")
    def reject_development_model_key_outside_development(self) -> Self:
        if self.app_env != "development":
            key = self.model_secret_encryption_key.get_secret_value()
            if key == DEFAULT_MODEL_SECRET_ENCRYPTION_KEY:
                raise ValueError(
                    "model secret encryption key must be configured outside development"
                )
            if len(key) < 32:
                raise ValueError(
                    "model secret encryption key must be at least 32 characters"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
