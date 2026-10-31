from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from birds_eye.config import Settings
from birds_eye.providers.budget import IMAGE_PRICES, LedgerBudgetGuard, cost_for_frames
from birds_eye.providers.contracts import ProviderId
from birds_eye.providers.registry import bindings
from birds_eye.providers.router import AsyncRateLimiter, ModelRouter
from birds_eye.providers.transport import LiveTransport


def test_meta_binding_uses_setting_default_contributor(settings):
    meta = lambda: next(
        b
        for b in bindings(settings)
        if b.provider == ProviderId.META and b.operation == "text"
    )
    assert meta().concrete_model == "muse-spark-1.3-contributor"
    settings.meta_muse_model = "muse-spark-1.3"
    assert meta().concrete_model == "muse-spark-1.3"


def test_price_table_defaults(settings):
    guard = LedgerBudgetGuard(settings)
    assert guard.prices(ProviderId.META, "muse-spark-1.3-contributor") == (
        Decimal("0.10"),
        Decimal("0.002"),
        Decimal("0.20"),
    )
    assert guard.prices(ProviderId.META, "muse-spark-1.3") == (
        Decimal("1.25"),
        Decimal("0.15"),
        Decimal("4.25"),
    )
    assert (
        IMAGE_PRICES["sam-3.1"] == settings.sam_price_per_image_usd == Decimal("0.0025")
    )
    assert IMAGE_PRICES["muse-image-1.0"] == Decimal("0.01")


@pytest.mark.asyncio
async def test_cached_input_tokens_priced_at_cached_rate(settings, muse_request):
    guard = LedgerBudgetGuard(settings)
    reservation = await guard.reserve(ProviderId.META, Decimal(1))
    cost = await guard.settle_attempt(
        reservation,
        muse_request,
        settings.meta_muse_model,
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 80},
        },
        "success",
        None,
    )
    assert cost == Decimal("0.00000616")


def test_sam_video_cost_min_50_frames():
    assert cost_for_frames(10) == cost_for_frames(50) == Decimal("0.01")
    assert cost_for_frames(1000) == Decimal("0.20")


def test_max_tokens_per_run_default_24000(settings):
    assert settings.max_tokens_per_run == 24000


@pytest.mark.asyncio
async def test_rate_limiter_spaces_calls_over_rpm():
    now = [0.0]

    async def sleep(delay):
        now[0] += delay

    limiter = AsyncRateLimiter(clock=lambda: now[0], sleep=sleep)
    for _ in range(141):
        await limiter.acquire("model", 140)
    assert now[0] == pytest.approx(60)


@pytest.mark.asyncio
async def test_429_maps_rate_limited_and_retries(settings, muse_request, budget):
    from pydantic import SecretStr

    settings.model_api_key = SecretStr("FAKE")
    settings.provider_max_retries = 1
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async def sleep(delay):
        pass

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await ModelRouter(
            settings, LiveTransport(settings, client), budget, sleep=sleep
        ).call(muse_request)
    assert [x["error_code"] for x in response.metadata[-2:]] == ["RATE_LIMITED", None]
    assert len(calls) == 2


def test_reasoning_effort_max_rejected():
    with pytest.raises(ValidationError):
        Settings(reasoning_effort="max")
    with pytest.raises(ValidationError):
        Settings(meta_reasoning_effort="max")
