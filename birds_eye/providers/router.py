import asyncio
import random
import time
from decimal import Decimal

import httpx

from birds_eye.config import Settings
from birds_eye.providers.budget import LedgerBudgetGuard
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

    def reserve(self, tokens: int) -> int:
        available = self.max_tokens - self.tokens
        if self.calls >= self.max_calls or (tokens and available < 400):
            raise ProviderError("RUN_BUDGET_EXCEEDED")
        amount = min(tokens, available)
        self.calls += 1
        self.tokens += amount
        return amount

    def settle(self, reserved: int, usage: dict | None, timeout: bool = False):
        if timeout:
            return
        usage = usage or {}
        actual = usage.get("total_tokens")
        if not isinstance(actual, int) or isinstance(actual, bool) or actual < 0:
            actual = sum(
                usage.get(k, 0)
                for k in ("prompt_tokens", "completion_tokens")
                if isinstance(usage.get(k), int)
                and not isinstance(usage.get(k), bool)
                and usage[k] >= 0
            )
        self.tokens += actual - reserved


class NoCostBudget:
    async def reserve(self, provider, max_cost_usd):
        from birds_eye.providers.contracts import Reservation

        return Reservation(id="unpriced")

    async def settle(self, reservation, actual_cost_usd):
        pass


def safe_usage(usage):
    if not isinstance(usage, dict):
        return None
    result = {
        k: v
        for k, v in usage.items()
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
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        n = details.get("reasoning_tokens")
        if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
            result["reasoning_tokens"] = n
    return result


class ModelRouter:
    def __init__(
        self,
        settings: Settings,
        transport: Transport,
        budget: BudgetGuard,
        run_budget: RunBudget | None = None,
        sleep=asyncio.sleep,
        jitter=random.random,
    ):
        self.settings, self.transport, self.budget = settings, transport, budget
        self.run_budget = run_budget or RunBudget(settings)
        self.sleep, self.jitter = sleep, jitter

    async def call(self, request: ModelRequest) -> ModelResponse:
        if {"muse-spark": "text", "sam-3.1": "segmentation"}.get(
            request.logical_model
        ) != request.operation:
            raise RoutingError("INVALID_REQUEST", "Unsupported model or operation.", [])
        effective = (
            max(request.max_tokens or self.settings.muse_max_tokens_default, 400)
            if request.logical_model == "muse-spark"
            else request.max_tokens or 0
        )
        available = {
            b.provider: b
            for b in bindings(self.settings)
            if b.logical_model == request.logical_model
            and b.operation == request.operation
        }
        credentials = {
            ProviderId.BASETEN: self.settings.baseten_api_key,
            ProviderId.MODAL: self.settings.modal_token_id
            and self.settings.modal_token_secret,
            ProviderId.META: self.settings.model_api_key,
        }
        records = []
        retryable = {"TIMEOUT", "RATE_LIMITED", "PROVIDER_5XX", "CONNECTION_ERROR"}
        fallback = retryable | {
            "FORCED_FAILURE",
            "EMPTY_CONTENT_LENGTH",
            "AUTHENTICATION_ERROR",
            "CONFIGURATION_ERROR",
            "INTEGRATION_NOT_READY",
        }
        safe = fallback | {
            "RUN_BUDGET_EXCEEDED",
            "INVALID_REQUEST",
            "SAFETY_REFUSAL",
            "MALFORMED_RESPONSE",
        }
        for provider in ProviderId:
            binding = available.get(provider)
            for retry in range(self.settings.provider_max_retries + 1):
                effort = (
                    (
                        self.settings.meta_reasoning_effort
                        or self.settings.reasoning_effort
                    )
                    if provider == ProviderId.META
                    else self.settings.reasoning_effort
                )
                record = {
                    "event": "provider_attempt",
                    "run_id": request.run_id,
                    "stage": request.stage,
                    "call_id": request.call_id,
                    "attempt": retry + 1,
                    "logical_model": request.logical_model,
                    "provider": provider.value,
                    "model": binding.concrete_model if binding else None,
                    "concrete_model": binding.concrete_model if binding else None,
                    "status": "skipped",
                    "error_code": None,
                    "latency_ms": 0,
                    "requested_max_tokens": request.max_tokens,
                    "effective_max_tokens": effective,
                    "max_completion_tokens": effective,
                    "reasoning_effort": effort,
                    "usage": None,
                    "cost_usd": None,
                    "ledger_total_usd": None,
                    "finish_reason": None,
                    "truncated": False,
                }
                start = time.monotonic()
                reservation = None
                reserved = None
                reply = None
                usage = None
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
                            max_cost = request.max_cost_usd
                            if isinstance(self.budget, LedgerBudgetGuard):
                                input_price, output_price = self.budget.prices(provider)
                                prompt_tokens = (
                                    len(request.prompt + request.instructions) + 2
                                ) // 3
                                max_cost = (
                                    prompt_tokens * input_price
                                    + effective * output_price
                                ) / Decimal(1_000_000)
                            reservation = await self.budget.reserve(provider, max_cost)
                        except ProviderError as exc:
                            record["error_code"] = exc.code
                        else:
                            reserved = self.run_budget.reserve(effective)
                            record["effective_max_tokens"] = record[
                                "max_completion_tokens"
                            ] = reserved
                            if provider.value in {
                                p.strip()
                                for p in self.settings.force_fail_providers.split(",")
                            }:
                                raise ProviderError("FORCED_FAILURE")
                            reply = await self.transport.invoke(
                                binding,
                                request.model_copy(update={"max_tokens": reserved}),
                            )
                            if (
                                not isinstance(reply, ProviderReply)
                                or reply.output is None
                            ):
                                raise ProviderError("MALFORMED_RESPONSE")
                            usage = reply.usage
                            record.update(
                                status="success",
                                usage=safe_usage(usage),
                                cost_usd=str(reply.cost_usd)
                                if reply.cost_usd is not None
                                else None,
                                finish_reason=reply.finish_reason,
                                truncated=reply.truncated,
                            )
                except ProviderError as exc:
                    code = exc.code if exc.code in safe else "PROVIDER_ERROR"
                    usage = getattr(exc, "usage", None)
                    finish = getattr(exc, "finish_reason", None)
                    record.update(
                        status="failed",
                        error_code=code,
                        usage=safe_usage(usage),
                        finish_reason=finish,
                        truncated=finish == "length",
                    )
                except (TimeoutError, httpx.TimeoutException):
                    record.update(status="failed", error_code="TIMEOUT")
                except (ConnectionError, httpx.NetworkError):
                    record.update(status="failed", error_code="CONNECTION_ERROR")
                finally:
                    if reserved is not None:
                        self.run_budget.settle(
                            reserved, usage, record["error_code"] == "TIMEOUT"
                        )
                    if reservation is not None:
                        if isinstance(self.budget, LedgerBudgetGuard):
                            cost = await self.budget.settle_attempt(
                                reservation,
                                request,
                                binding.concrete_model,
                                usage,
                                record["status"],
                                record["error_code"],
                            )
                            record["cost_usd"] = str(cost)
                        else:
                            await self.budget.settle(
                                reservation,
                                reply.cost_usd
                                if isinstance(reply, ProviderReply)
                                else None,
                            )
                    if isinstance(self.budget, LedgerBudgetGuard):
                        record["ledger_total_usd"] = str(self.budget.totals[provider])
                    record["latency_ms"] = round((time.monotonic() - start) * 1000, 3)
                    records.append(record)
                    log_attempt(record)
                if record["status"] == "success":
                    return ModelResponse(
                        logical_model=request.logical_model,
                        output=reply.output,
                        metadata=records,
                    )
                code = record["error_code"]
                if record["status"] == "skipped":
                    break
                if code not in fallback:
                    raise RoutingError(code, "Provider request failed.", records)
                if code not in retryable or retry == self.settings.provider_max_retries:
                    break
                await self.sleep(
                    self.settings.provider_retry_base_seconds
                    * (2**retry)
                    * (1 + self.jitter())
                )
        eligible = [
            r
            for r in records
            if r["error_code"]
            not in {"MISSING_CREDENTIALS", "NOT_CONFIGURED", "UNSUPPORTED_CAPABILITY"}
        ]
        if eligible and all(r["error_code"] == "BUDGET_EXHAUSTED" for r in eligible):
            raise RoutingError(
                "PROVIDER_BUDGET_EXHAUSTED", "Provider budget exhausted.", records
            )
        raise RoutingError(
            "PROVIDERS_EXHAUSTED", "No provider could complete the request.", records
        )
