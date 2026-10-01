from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str | None = None
    openai_api_type: Literal["openai", "azure"] = "openai"
    openai_api_version: str = "2025-04-01-preview"
    llm_model: str = "gpt-4.1-mini"
    openai_base_url: str | None = None
    llm_supports_temperature: bool = True
    log_level: str = "INFO"
    app_env: str = "development"
    score_met_points: float = 1.0
    score_partial_points: float = 0.5
    score_unclear_points: float = 0.25
    score_not_met_points: float = 0.0
    score_must_have_weight: float = 3.0
    score_nice_to_have_weight: float = 1.0
    score_knockout_cap: int = 65
    confidence_consistency_weight: float = 0.30
    confidence_evidence_weight: float = 0.30
    confidence_input_weight: float = 0.25
    confidence_verification_weight: float = 0.15
    confidence_requirement_quality_weight: float = 0.40
    confidence_resume_quality_weight: float = 0.40
    confidence_source_quality_weight: float = 0.20
    llm_input_price_per_million_tokens: float = 0.40
    llm_output_price_per_million_tokens: float = 1.60


@lru_cache
def get_settings() -> Settings:
    return Settings()
