import time

import httpx

from birds_eye.config import Settings
from birds_eye.providers.contracts import (
    BudgetGuard,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderId,
    ProviderReply,
    RoutingError,
    Transport,
)
from birds_eye.providers.logging import log_attempt
from birds_eye.providers.registry import bindings


class RunBudget:
    def __init__(self, settings: Settings):
        self.max_calls = settings.max_calls_per_run
        self.max_tokens = settings.max_tokens_per_run
        self.calls = 0
        self.tokens = 0

    def reserve(self, tokens: int):
        if self.calls + 1 > self.max_calls or self.tokens + tokens > self.max_tokens:
            raise ProviderError("RUN_BUDGET_EXCEEDED")
        self.calls += 1
        self.tokens += tokens


class NoCostBudget:
    async def reserve(self, provider, max_cost_usd):
        from birds_eye.providers.contracts import Reservation

        return Reservation(id="unpriced")

    async def settle(self, reservation, actual_cost_usd):
        pass


class ModelRouter:
    def __init__(
        self,
        settings: Settings,
        transport: Transport,
        budget: BudgetGuard,
        run_budget: RunBudget | None = None,
    ):
        self.settings, self.transport, self.budget = settings, transport, budget
        self.run_budget = run_budget or RunBudget(settings)

    async def call(self, request: ModelRequest) -> ModelResponse:
        supported = {"muse-spark": "text", "sam-3.1": "segmentation"}
        if supported.get(request.logical_model) != request.operation:
            raise RoutingError("INVALID_REQUEST", "Unsupported model or operation.", [])
        effective = (
            max(request.max_tokens or self.settings.muse_max_tokens_default, 400)
            if request.logical_model == "muse-spark"
            else request.max_tokens
        )
        normalized = request.model_copy(update={"max_tokens": effective})
        records = []
        available = {
            b.provider: b
            for b in bindings(self.settings)
            if b.logical_model == request.logical_model
            and b.operation == request.operation
        }
        credentials = {
            ProviderId.BASETEN: bool(
                self.settings.baseten_api_key
                and self.settings.baseten_api_key.get_secret_value()
            ),
            ProviderId.MODAL: bool(
                self.settings.modal_token_id
                and self.settings.modal_token_id.get_secret_value()
                and self.settings.modal_token_secret
                and self.settings.modal_token_secret.get_secret_value()
            ),
            ProviderId.META: bool(
                self.settings.model_api_key
                and self.settings.model_api_key.get_secret_value()
            ),
        }
        for provider in ProviderId:
            binding = available.get(provider)
            record = {
                "run_id": request.run_id,
                "stage": request.stage,
                "call_id": request.call_id,
                "attempt": len(records) + 1,
                "logical_model": request.logical_model,
                "provider": provider.value,
                "concrete_model": binding.concrete_model if binding else None,
                "status": "skipped",
                "error_code": None,
                "latency_ms": 0,
                "requested_max_tokens": request.max_tokens,
                "effective_max_tokens": effective,
                "usage": None,
                "cost_usd": None,
            }
            start = time.monotonic()
            reservation = None
            reply = None
            terminal = False
            try:
                if not binding:
                    record["error_code"] = (
                        "NOT_CONFIGURED"
                        if provider == ProviderId.MODAL
                        and request.logical_model == "muse-spark"
                        else "UNSUPPORTED_CAPABILITY"
                    )
                elif not credentials[provider]:
                    record["error_code"] = "MISSING_CREDENTIALS"
                else:
                    try:
                        reservation = await self.budget.reserve(
                            provider, request.max_cost_usd
                        )
                    except ProviderError:
                        record["error_code"] = "BUDGET_EXHAUSTED"
                    else:
                        try:
                            self.run_budget.reserve(effective or 0)
                            if provider.value in {
                                p.strip()
                                for p in self.settings.force_fail_providers.split(",")
                            }:
                                raise ProviderError("FORCED_FAILURE")
                            reply = await self.transport.invoke(binding, normalized)
                            if (
                                not isinstance(reply, ProviderReply)
                                or reply.output is None
                            ):
                                raise ProviderError("MALFORMED_RESPONSE")
                            record.update(
                                status="success",
                                usage={
                                    k: v
                                    for k, v in (reply.usage or {}).items()
                                    if k
                                    in {
                                        "input_tokens",
                                        "output_tokens",
                                        "prompt_tokens",
                                        "completion_tokens",
                                        "total_tokens",
                                    }
                                    and isinstance(v, int)
                                    and not isinstance(v, bool)
                                    and v >= 0
                                }
                                if reply.usage is not None
                                else None,
                                cost_usd=str(reply.cost_usd)
                                if reply.cost_usd is not None
                                else None,
                            )
                        except ProviderError as exc:
                            safe_codes = {
                                "TIMEOUT",
                                "FORCED_FAILURE",
                                "EMPTY_CONTENT_LENGTH",
                                "RUN_BUDGET_EXCEEDED",
                                "CONNECTION_ERROR",
                                "RATE_LIMITED",
                                "PROVIDER_5XX",
                                "AUTHENTICATION_ERROR",
                                "CONFIGURATION_ERROR",
                                "INTEGRATION_NOT_READY",
                                "INVALID_REQUEST",
                                "SAFETY_REFUSAL",
                                "MALFORMED_RESPONSE",
                            }
                            code = (
                                exc.code if exc.code in safe_codes else "PROVIDER_ERROR"
                            )
                            record.update(status="failed", error_code=code)
                            terminal = code not in {
                                "TIMEOUT",
                                "FORCED_FAILURE",
                                "EMPTY_CONTENT_LENGTH",
                                "CONNECTION_ERROR",
                                "RATE_LIMITED",
                                "PROVIDER_5XX",
                                "AUTHENTICATION_ERROR",
                                "CONFIGURATION_ERROR",
                                "INTEGRATION_NOT_READY",
                            }
                        except (
                            TimeoutError,
                            ConnectionError,
                            httpx.TimeoutException,
                            httpx.NetworkError,
                        ):
                            record.update(
                                status="failed", error_code="CONNECTION_ERROR"
                            )
            finally:
                if reservation is not None:
                    await self.budget.settle(
                        reservation,
                        reply.cost_usd if isinstance(reply, ProviderReply) else None,
                    )
                record["latency_ms"] = round((time.monotonic() - start) * 1000, 3)
                records.append(record)
                log_attempt(record)
            if reply is not None and record["status"] == "success":
                return ModelResponse(
                    logical_model=request.logical_model,
                    output=reply.output,
                    metadata=records,
                )
            if terminal:
                raise RoutingError(
                    record["error_code"], "Provider request failed.", records
                )
        raise RoutingError(
            "PROVIDERS_EXHAUSTED", "No provider could complete the request.", records
        )
