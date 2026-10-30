import json
from pathlib import Path

import httpx
import pytest
from conftest import FakeBudgetGuard, FakeTransport
from pydantic import SecretStr

from birds_eye.app import create_app
from birds_eye.providers.contracts import (
    ModelBinding,
    ProviderError,
    ProviderId,
    ProviderReply,
)
from birds_eye.providers.router import ModelRouter
from birds_eye.providers.transport import LiveTransport


@pytest.mark.asyncio
async def test_retries_then_meta_and_budget(settings, muse_request):
    settings.baseten_api_key = SecretStr("fake")
    settings.model_api_key = SecretStr("fake")
    settings.provider_max_retries = 2
    settings.max_tokens_per_run = 16000
    settings.provider_retry_base_seconds = 1
    delays = []

    async def sleep(delay):
        delays.append(delay)

    fake = FakeTransport(
        [ProviderError("RATE_LIMITED")] * 3
        + [ProviderReply(output="done", usage={"total_tokens": 100})]
    )
    router = ModelRouter(
        settings, fake, FakeBudgetGuard(), sleep=sleep, jitter=lambda: 0.5
    )
    response = await router.call(muse_request.model_copy(update={"max_tokens": 4000}))
    assert delays == [1.5, 3.0]
    assert [a["provider"] for a in response.metadata] == ["baseten"] * 3 + [
        "modal",
        "meta_model_api",
    ]
    assert [a["attempt"] for a in response.metadata[:3]] == [1, 2, 3]
    assert router.run_budget.tokens == 100


@pytest.mark.asyncio
async def test_forced_failure_no_retry(settings, muse_request):
    settings.baseten_api_key = settings.model_api_key = SecretStr("fake")
    settings.provider_max_retries = 2
    settings.force_fail_providers = "baseten"

    async def sleep(_):
        pytest.fail("forced failure must not sleep")

    fake = FakeTransport([ProviderReply(output="done")])
    result = await ModelRouter(settings, fake, FakeBudgetGuard(), sleep=sleep).call(
        muse_request
    )
    assert result.metadata[0]["error_code"] == "FORCED_FAILURE"
    assert len(fake.calls) == 1 and fake.calls[0][0].provider == ProviderId.META


@pytest.mark.asyncio
@pytest.mark.parametrize("content,failed", [("short stub", True), ("x" * 40, False)])
async def test_length_and_usage(settings, muse_request, content, failed):
    settings.model_api_key = SecretStr("fake")
    body = {
        "choices": [{"message": {"content": content}, "finish_reason": "length"}],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 20,
            "completion_tokens_details": {"reasoning_tokens": 15},
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    ) as client:
        transport = LiveTransport(settings, client)
        binding = ModelBinding(
            logical_model="muse-spark",
            provider=ProviderId.META,
            concrete_model="test",
            operation="text",
        )
        if failed:
            with pytest.raises(ProviderError, match="Provider call failed") as exc:
                await transport.invoke(binding, muse_request)
            assert exc.value.code == "EMPTY_CONTENT_LENGTH"
        else:
            reply = await transport.invoke(binding, muse_request)
            assert (
                reply.truncated
                and reply.usage["completion_tokens_details"]["reasoning_tokens"] == 15
            )


@pytest.mark.asyncio
async def test_brief_and_partial_error(settings):
    settings.provider_mode = "live"
    settings.baseten_api_key = SecretStr("fake")
    brief = "A Jakarta coffee shop serving iced kopi susu."
    fake = FakeTransport(
        [
            ProviderReply(output="plan"),
            ProviderReply(output="draft"),
            ProviderReply(output='{"decision":"approve","findings":[]}'),
        ]
    )
    app = create_app(settings)
    app.state.transport = fake
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/meta/runs", json={"brief": brief})
        ).status_code == 200
        mock = json.loads(Path("mock-data/default/creator-brief.MOCK.json").read_text())
        for _, request in fake.calls:
            assert brief in request.prompt
            assert mock["creator"] not in request.prompt
        app.state.transport = FakeTransport(
            [ProviderReply(output="plan"), ProviderError("AUTHENTICATION_ERROR")]
        )
        result = await client.post("/meta/runs", json={"brief": brief})
        assert result.status_code == 502
        data = result.json()
        assert (
            data["code"] == "PROVIDERS_EXHAUSTED" and data["failed_stage"] == "Writer"
        )
        assert data["stages"][0]["output"] == "plan"
        assert data["attempts"][0]["error_code"] == "AUTHENTICATION_ERROR"


@pytest.mark.asyncio
async def test_timeout_reservation_and_stdout(settings, muse_request, capsys):
    from birds_eye.providers.logging import configure_logging, logger

    settings.baseten_api_key = SecretStr("SECRET_DO_NOT_PRINT")
    settings.provider_max_retries = 1
    settings.max_tokens_per_run = 4500

    async def sleep(_):
        pass

    fake = FakeTransport(
        [
            ProviderError("TIMEOUT"),
            ProviderReply(
                output="ok",
                usage={
                    "prompt_tokens": 50,
                    "completion_tokens": 100,
                    "completion_tokens_details": {"reasoning_tokens": 30},
                },
                finish_reason="length",
                truncated=True,
            ),
        ]
    )
    router = ModelRouter(
        settings, fake, FakeBudgetGuard(), sleep=sleep, jitter=lambda: 0
    )
    configure_logging()
    try:
        result = await router.call(muse_request.model_copy(update={"max_tokens": 4000}))
        assert fake.calls[1][1].max_tokens == 500
        assert router.run_budget.tokens == 4150
        assert result.metadata[-1]["truncated"]
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert len(lines) == 2 and all(
            line["event"] == "provider_attempt" for line in lines
        )
        assert lines[-1]["usage"]["reasoning_tokens"] == 30
        assert "SECRET_DO_NOT_PRINT" not in json.dumps(lines)
        assert {
            "run_id",
            "stage",
            "provider",
            "model",
            "logical_model",
            "attempt",
            "status",
            "error_code",
            "latency_ms",
            "max_completion_tokens",
            "reasoning_effort",
            "usage",
            "finish_reason",
            "truncated",
        } <= lines[-1].keys()
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "birds_eye_stdout", False):
                logger.removeHandler(handler)
        logger.propagate = True
