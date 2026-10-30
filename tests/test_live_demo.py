import json

import httpx
import pytest
from conftest import FakeBudgetGuard, FakeTransport
from pydantic import SecretStr

from birds_eye.app import create_app
from birds_eye.core.inputs import load_inputs, make_context
from birds_eye.meta.pipeline import run_meta
from birds_eye.providers.contracts import (
    ModelBinding,
    ProviderError,
    ProviderId,
    ProviderReply,
    RoutingError,
)
from birds_eye.providers.router import ModelRouter
from birds_eye.providers.transport import LiveTransport


@pytest.mark.asyncio
async def test_live_request_and_parse(settings, muse_request):
    settings.baseten_api_key = SecretStr("fake-secret")

    def handler(request):
        assert request.url == "https://inference.baseten.co/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer fake-secret"
        body = json.loads(request.content)
        assert body == {
            "model": "model",
            "messages": [{"role": "user", "content": ""}],
            "max_tokens": 40,
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "answer", "reasoning_content": "hidden"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reply = await LiveTransport(settings, client).invoke(
            ModelBinding(
                logical_model="muse-spark",
                provider=ProviderId.BASETEN,
                concrete_model="model",
                operation="text",
            ),
            muse_request,
        )
    assert reply.output == "answer" and reply.usage["total_tokens"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "INVALID_REQUEST"),
        (401, "AUTHENTICATION_ERROR"),
        (403, "AUTHENTICATION_ERROR"),
        (429, "RATE_LIMITED"),
        (500, "PROVIDER_5XX"),
    ],
)
async def test_live_errors(settings, muse_request, status, code):
    settings.model_api_key = SecretStr("fake")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(status, text="sensitive body")
        )
    ) as client:
        with pytest.raises(ProviderError) as exc:
            await LiveTransport(settings, client).invoke(
                ModelBinding(
                    logical_model="muse-spark",
                    provider=ProviderId.META,
                    concrete_model="model",
                    operation="text",
                ),
                muse_request,
            )
    assert exc.value.code == code and "sensitive" not in str(exc.value)


@pytest.mark.asyncio
async def test_empty_length(settings, muse_request):
    settings.model_api_key = SecretStr("fake")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": ""}, "finish_reason": "length"}]
                },
            )
        )
    ) as client:
        with pytest.raises(ProviderError) as exc:
            await LiveTransport(settings, client).invoke(
                ModelBinding(
                    logical_model="muse-spark",
                    provider=ProviderId.META,
                    concrete_model="model",
                    operation="text",
                ),
                muse_request,
            )
    assert exc.value.code == "EMPTY_CONTENT_LENGTH"


@pytest.mark.asyncio
async def test_forced_fallback_and_caps(settings, muse_request):
    settings.baseten_api_key = SecretStr("fake")
    settings.model_api_key = SecretStr("fake")
    settings.force_fail_providers = "baseten"
    settings.max_calls_per_run = 2
    transport = FakeTransport([ProviderReply(output="ok")])
    router = ModelRouter(settings, transport, FakeBudgetGuard())
    result = await router.call(muse_request)
    assert [a["error_code"] for a in result.metadata] == [
        "FORCED_FAILURE",
        "NOT_CONFIGURED",
        None,
    ]
    assert transport.calls[0][0].provider == ProviderId.META
    with pytest.raises(RoutingError) as exc:
        await router.call(muse_request)
    assert exc.value.code == "RUN_BUDGET_EXCEEDED"
    settings.max_calls_per_run = 6
    settings.max_tokens_per_run = 399
    with pytest.raises(RoutingError) as exc:
        await ModelRouter(settings, FakeTransport(), FakeBudgetGuard()).call(
            muse_request
        )
    assert exc.value.code == "RUN_BUDGET_EXCEEDED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("review", "decision"),
    [
        ('```json\n{"decision":"approve","findings":[]}\n```', "approve"),
        ("unparseable", "revise"),
    ],
)
async def test_pipeline_and_routes(settings, review, decision):
    settings.provider_mode = "live"
    settings.baseten_api_key = SecretStr("fake")
    replies = [ProviderReply(output=x) for x in ("plan", "draft", review)]
    fake = FakeTransport(replies)
    result = await run_meta(
        make_context(load_inputs(settings.default_scenario_dir)),
        ModelRouter(settings, fake, FakeBudgetGuard()),
    )
    assert len(fake.calls) == 3 and result.stages[2]["decision"] == decision
    app = create_app(settings)
    app.state.transport = FakeTransport(
        [ProviderReply(output=x) for x in ("plan", "draft", review)]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        page = await client.get("/")
        assert "textarea" in page.text and "MOCK" in page.text
        response = await client.post("/meta/runs", json={"brief": "test"})
        assert response.status_code == 200
        assert all(
            s["attempts"][0]["concrete_model"] == "meta-models/muse-spark-open-1026"
            for s in response.json()["stages"]
        )
        assert (
            await client.post("/meta/runs", json={"brief": "a" * 4001})
        ).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (httpx.ConnectError("sensitive"), "CONNECTION_ERROR"),
        (httpx.ReadTimeout("sensitive"), "TIMEOUT"),
    ],
)
async def test_transport_network_errors(settings, muse_request, error, code):
    settings.baseten_api_key = SecretStr("fake")

    def handler(request):
        raise error

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as exc:
            await LiveTransport(settings, client).invoke(
                ModelBinding(
                    logical_model="muse-spark",
                    provider=ProviderId.BASETEN,
                    concrete_model="model",
                    operation="text",
                ),
                muse_request,
            )
    assert exc.value.code == code and "sensitive" not in str(exc.value)


@pytest.mark.asyncio
async def test_live_attempt_logging_excludes_key_and_error_body(
    settings, muse_request, caplog
):
    import logging

    settings.baseten_api_key = SecretStr("fake-secret-to-protect")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(401, text="private-error-body")
        )
    ) as client:
        with (
            caplog.at_level(logging.INFO, logger="birds_eye.model_calls"),
            pytest.raises(RoutingError),
        ):
            await ModelRouter(
                settings, LiveTransport(settings, client), FakeBudgetGuard()
            ).call(muse_request)
    assert "fake-secret-to-protect" not in caplog.text
    assert "private-error-body" not in caplog.text
    assert "AUTHENTICATION_ERROR" in caplog.text


@pytest.mark.parametrize(
    ("raw", "decision", "findings", "show_raw"),
    [
        (
            '```json\n{"decision":"approve","findings":["fine"]}\n```',
            "approve",
            ["fine"],
            False,
        ),
        (
            '{"decision":"approve","findings":["first", "escaped \\"quote\\"", "incomplete',
            "approve",
            ["first", 'escaped "quote"'],
            False,
        ),
        ('{"decision":"revise","findings":["one",', "revise", ["one"], False),
        ('{"decision":"approve","findings":[', "approve", [], False),
        ("not a verdict", "revise", ["not a verdict"], True),
    ],
)
def test_verdict_recovery(raw, decision, findings, show_raw):
    from birds_eye.meta.agents import parse_verdict

    verdict = parse_verdict(raw, [])
    assert verdict.decision == decision
    assert [item.message for item in verdict.findings] == findings
    assert (verdict.output == raw) == show_raw
