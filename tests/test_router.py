import base64
import io

import pytest
from conftest import FakeBudgetGuard, FakeTransport
from PIL import Image

from birds_eye.providers.contracts import (
    MediaInput,
    ModelBinding,
    ModelRequest,
    ProviderError,
    ProviderId,
    ProviderReply,
    RoutingError,
)
from birds_eye.providers.router import ModelRouter
from birds_eye.providers.transport import DisabledTransport


@pytest.mark.asyncio
async def test_fallback_preserves_model_and_token_floor(
    configured_settings, budget, muse_request
):
    transport = FakeTransport(
        [
            ProviderError("TIMEOUT"),
            ProviderReply(output="ok"),
        ]
    )
    response = await ModelRouter(configured_settings, transport, budget).call(
        muse_request
    )
    assert response.logical_model == "muse-spark"
    assert [binding.provider for binding, _ in transport.calls] == [
        ProviderId.BASETEN,
        ProviderId.META,
    ]
    assert all(
        request.logical_model == "muse-spark" and request.max_tokens == 400
        for _, request in transport.calls
    )
    assert all(
        record["requested_max_tokens"] == 40 and record["effective_max_tokens"] == 400
        for record in response.metadata
    )
    assert [cost for _, cost in budget.settlements] == [None, None]


@pytest.mark.asyncio
async def test_sam_only_routes_to_meta(configured_settings, budget):
    transport = FakeTransport([ProviderReply(output="mask")])
    image_buffer = io.BytesIO()
    Image.new("RGB", (1, 1), "red").save(image_buffer, format="PNG")
    image_bytes = image_buffer.getvalue()
    request = ModelRequest(
        run_id="r",
        stage="segment",
        call_id="c",
        logical_model="sam-3.1",
        operation="segmentation",
        media=MediaInput(
            mime="image/png",
            data_url="data:image/png;base64,"
            + base64.b64encode(image_bytes).decode("ascii"),
            bytes_len=len(image_bytes),
        ),
    )
    result = await ModelRouter(configured_settings, transport, budget).call(request)
    assert [
        (binding.provider, binding.concrete_model) for binding, _ in transport.calls
    ] == [(ProviderId.META, "sam-3.1")]
    assert [record["error_code"] for record in result.metadata] == [
        "UNSUPPORTED_CAPABILITY",
        None,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        ProviderError("TIMEOUT"),
        ProviderError("RATE_LIMITED"),
        ProviderError("PROVIDER_5XX"),
        TimeoutError(),
        ConnectionError(),
        ProviderError("AUTHENTICATION_ERROR"),
        ProviderError("CONFIGURATION_ERROR"),
    ],
    ids=["timeout", "429", "5xx", "timeout-exception", "connection", "auth", "config"],
)
async def test_retryable_failure_falls_back(
    configured_settings, budget, muse_request, error
):
    transport = FakeTransport([error, ProviderReply(output="ok")])
    result = await ModelRouter(configured_settings, transport, budget).call(
        muse_request
    )
    assert len(transport.calls) == 2
    assert result.metadata[0]["status"] == "failed"
    assert result.metadata[1]["provider"] == "meta_model_api"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["INVALID_REQUEST", "SAFETY_REFUSAL", "MALFORMED_RESPONSE"]
)
async def test_terminal_failure_stops(configured_settings, budget, muse_request, code):
    transport = FakeTransport(
        [ProviderError(code), ProviderReply(output="must not run")]
    )
    with pytest.raises(RoutingError) as error:
        await ModelRouter(configured_settings, transport, budget).call(muse_request)
    assert error.value.code == code
    assert len(transport.calls) == len(error.value.attempts) == 1


@pytest.mark.asyncio
async def test_all_provider_failure_returns_typed_attempts(
    configured_settings, budget, muse_request
):
    transport = FakeTransport(
        [
            ProviderError("TIMEOUT"),
            ProviderError("RATE_LIMITED"),
            ProviderError("PROVIDER_5XX"),
        ]
    )
    with pytest.raises(RoutingError) as error:
        await ModelRouter(configured_settings, transport, budget).call(muse_request)
    assert error.value.code == "PROVIDERS_EXHAUSTED"
    assert [r["error_code"] for r in error.value.attempts] == [
        "TIMEOUT",
        "RATE_LIMITED",
    ]
    assert len(budget.settlements) == 2


@pytest.mark.asyncio
async def test_missing_credentials_budget_and_capability_record_skips(
    settings, muse_request
):
    settings.baseten_api_key = configured_secret()
    budget = FakeBudgetGuard(rejected=[ProviderId.BASETEN])
    with pytest.raises(RoutingError) as error:
        await ModelRouter(settings, FakeTransport(), budget).call(muse_request)
    assert [r["error_code"] for r in error.value.attempts] == [
        "BUDGET_EXHAUSTED",
        "MISSING_CREDENTIALS",
    ]
    assert all(r["status"] == "skipped" for r in error.value.attempts)


def configured_secret():
    from pydantic import SecretStr

    return SecretStr("FAKE_KEY")


@pytest.mark.asyncio
async def test_invalid_model_operation_is_rejected(
    configured_settings, budget, muse_request
):
    transport = FakeTransport()
    with pytest.raises(RoutingError) as error:
        await ModelRouter(configured_settings, transport, budget).call(
            muse_request.model_copy(update={"operation": "segmentation"})
        )
    assert error.value.code == "INVALID_REQUEST"
    assert error.value.attempts == [] and not transport.calls


@pytest.mark.asyncio
async def test_disabled_transport_never_networks(muse_request):
    binding = ModelBinding(
        logical_model="muse-spark",
        provider=ProviderId.BASETEN,
        concrete_model="mock",
        operation="text",
    )
    with pytest.raises(ProviderError) as error:
        await DisabledTransport().invoke(binding, muse_request)
    assert error.value.code == "INTEGRATION_NOT_READY"


@pytest.mark.asyncio
async def test_forced_baseten_failure_goes_straight_to_meta(
    settings, budget, muse_request
):
    settings.provider_mode = "live"
    settings.baseten_api_key = configured_secret()
    settings.model_api_key = configured_secret()
    settings.force_fail_providers = "baseten"
    result = await ModelRouter(
        settings, FakeTransport([ProviderReply(output="ok")]), budget
    ).call(muse_request)
    assert [record["provider"] for record in result.metadata] == [
        "baseten",
        "meta_model_api",
    ]
    assert result.metadata[0]["error_code"] == "FORCED_FAILURE"
    assert result.metadata[1]["status"] == "success"
