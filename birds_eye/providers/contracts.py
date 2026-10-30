from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from birds_eye.core.contracts import SafeError


class ProviderId(StrEnum):
    BASETEN = "baseten"
    MODAL = "modal"
    META = "meta_model_api"


class ModelBinding(BaseModel):
    logical_model: str
    provider: ProviderId
    concrete_model: str
    operation: Literal["text", "segmentation"]


class ModelRequest(BaseModel):
    run_id: str
    stage: str
    call_id: str
    logical_model: str
    operation: Literal["text", "segmentation"]
    prompt: str = ""
    instructions: str = ""
    max_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: Decimal = Field(default=Decimal(0), ge=0)
    json_schema_name: str | None = None
    json_schema: dict | None = None


class ProviderReply(BaseModel):
    output: Any
    usage: dict | None = None
    cost_usd: Decimal | None = None
    finish_reason: str | None = None
    truncated: bool = False


class ModelResponse(BaseModel):
    logical_model: str
    output: Any
    metadata: list[dict]


class Reservation(BaseModel):
    id: str


class Transport(Protocol):
    async def invoke(
        self, binding: ModelBinding, request: ModelRequest
    ) -> ProviderReply: ...


class BudgetGuard(Protocol):
    async def reserve(
        self, provider: ProviderId, max_cost_usd: Decimal
    ) -> Reservation: ...
    async def settle(
        self, reservation: Reservation, actual_cost_usd: Decimal | None
    ) -> None: ...


class ProviderError(SafeError):
    def __init__(self, code: str, message: str = "Provider call failed."):
        super().__init__(code, message)


class RoutingError(SafeError):
    def __init__(self, code: str, message: str, attempts: list[dict]):
        super().__init__(code, message)
        self.attempts = attempts
        self.stages = []
        self.failed_stage = None
