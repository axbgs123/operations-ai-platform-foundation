import re
from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_MODEL_SECRET_ENCRYPTION_KEY = "local-development-model-secret-change-me"
DEFAULT_SESSION_SIGNING_SECRET = "local-development-session-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_mock_mode: bool = True
    app_lite_mode: bool = False
    demo_seed_enabled: bool = False
    session_signing_secret: SecretStr = SecretStr(DEFAULT_SESSION_SIGNING_SECRET)
    database_url: str = (
        "postgresql+psycopg://operations_ai:local-development-only"
        "@localhost:55432/operations_ai"
    )
    web_origin: str = "http://localhost:3000"
    extension_origin: str = "chrome-extension://mdbmlilohlhmjmcmkpbpjhldganompcl"
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
    storage_backend: Literal["s3", "local"] = "s3"
    local_storage_path: str = "/data/objects"
    api_public_url: str = "http://localhost:8000"
    storage_signing_secret: str = "local-development-signing-secret-change-me"
    analysis_adapter_url: str | None = None
    analysis_adapter_token: str | None = None
    analysis_model_version: str = "configured-analysis-v1"
    analysis_request_timeout_seconds: float = 30.0
    public_data_scheduler_enabled: bool = False
    public_data_scheduler_interval_seconds: int = 60
    readiness_timeout_seconds: float = 2.0
    model_secret_encryption_key: SecretStr = SecretStr(
        DEFAULT_MODEL_SECRET_ENCRYPTION_KEY
    )

    @model_validator(mode="after")
    def reject_development_model_key_outside_development(self) -> Self:
        if not re.fullmatch(r"chrome-extension://[a-p]{32}", self.extension_origin):
            raise ValueError("extension origin must be one exact Chrome extension ID")
        if self.app_env == "development":
            return self
        key = self.model_secret_encryption_key.get_secret_value()
        insecure_values = {
            "local-development-only",
            "local-development-signing-secret-change-me",
            DEFAULT_MODEL_SECRET_ENCRYPTION_KEY,
        }
        if key in insecure_values:
            raise ValueError(
                "model secret encryption key must be configured outside development"
            )
        if len(key) < 32:
            raise ValueError(
                "model secret encryption key must be at least 32 characters"
            )
        if self.storage_backend == "s3" and self.s3_secret_key in insecure_values:
            raise ValueError("S3 secret key must be configured outside development")
        if (
            self.storage_signing_secret in insecure_values
            or len(self.storage_signing_secret) < 32
        ):
            raise ValueError(
                "storage signing secret must be configured outside development"
            )
        session_secret = self.session_signing_secret.get_secret_value()
        if session_secret == DEFAULT_SESSION_SIGNING_SECRET:
            raise ValueError(
                "session signing secret must be configured outside development"
            )
        if len(session_secret) < 32:
            raise ValueError("session signing secret must be at least 32 characters")
        if "local-development-only" in self.database_url:
            raise ValueError("database password must be configured outside development")
        return self

    @property
    def run_tasks_inline(self) -> bool:
        return self.app_mock_mode or self.app_lite_mode


@lru_cache
def get_settings() -> Settings:
    return Settings()
