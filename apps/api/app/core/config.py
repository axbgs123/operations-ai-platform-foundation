from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_mock_mode: bool = True
    database_url: str = (
        "postgresql+psycopg://operations_ai:local-development-only"
        "@localhost:55432/operations_ai"
    )
    web_origin: str = "http://localhost:3000"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
