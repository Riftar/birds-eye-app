from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    baseten_api_key: SecretStr | None = None
    modal_token_id: SecretStr | None = None
    modal_token_secret: SecretStr | None = None
    model_api_key: SecretStr | None = None
    provider_mode: Literal["stub", "live"] = "stub"
    baseten_base_url: str = "https://inference.baseten.co/v1"
    meta_model_api_base_url: str = "https://api.meta.ai/v1"
    modal_muse_endpoint: str | None = None
    force_fail_providers: str = ""
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"] = "low"
    meta_reasoning_effort: (
        Literal["minimal", "low", "medium", "high", "xhigh"] | None
    ) = None
    provider_max_retries: int = Field(default=2, ge=0)
    provider_retry_base_seconds: float = Field(default=1, ge=0)
    planner_max_tokens: int = Field(default=4000, ge=400)
    writer_max_tokens: int = Field(default=4000, ge=400)
    reviewer_max_tokens: int = Field(default=3000, ge=400)
    max_calls_per_run: int = Field(default=12, ge=1)
    max_tokens_per_run: int = Field(default=16000, ge=1)
    default_scenario_dir: Path = Path("mock-data/default")
    modal_profile: str = "riftar-dev"
    modal_muse_model_id: str | None = None
    modal_budget_cap_usd: Decimal = Field(default=Decimal(50), ge=0)
    meta_model_api_budget_cap_usd: Decimal = Field(default=Decimal(100), ge=0)
    baseten_budget_cap_usd: Decimal | None = Field(default=None, ge=0)
    provider_timeout_seconds: float = Field(default=120, gt=0)
    muse_max_tokens_default: int = Field(default=2000, ge=400)
