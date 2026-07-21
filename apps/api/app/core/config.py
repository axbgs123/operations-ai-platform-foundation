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


@lru_cache
def get_settings() -> Settings:
    return Settings()
