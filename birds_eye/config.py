from decimal import Decimal
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    baseten_api_key: SecretStr | None = None
    modal_token_id: SecretStr | None = None
    modal_token_secret: SecretStr | None = None
    model_api_key: SecretStr | None = None
    provider_mode: str = "stub"
    default_scenario_dir: Path = Path("mock-data/default")
    modal_profile: str = "riftar-dev"
    modal_muse_model_id: str | None = None
    modal_budget_cap_usd: Decimal = Field(default=Decimal(50), ge=0)
    meta_model_api_budget_cap_usd: Decimal = Field(default=Decimal(100), ge=0)
    baseten_budget_cap_usd: Decimal | None = Field(default=None, ge=0)
    provider_timeout_seconds: float = Field(default=30, gt=0)
    muse_max_tokens_default: int = Field(default=800, ge=400)
