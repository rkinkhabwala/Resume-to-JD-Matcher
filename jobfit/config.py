from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str | None = None
    llm_model: str = "gpt-4.1-mini"
    openai_base_url: str | None = None
    llm_supports_temperature: bool = True
    log_level: str = "INFO"
    app_env: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
