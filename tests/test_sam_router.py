import base64
import io
import json
import logging
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from PIL import Image

from birds_eye.providers.budget import LedgerBudgetGuard
from birds_eye.providers.contracts import (
    MediaInput,
    ModelRequest,
    ProviderId,
    RoutingError,
)
from birds_eye.providers.registry import bindings
from birds_eye.providers.router import ModelRouter
from birds_eye.providers.transport import LiveTransport


def image_input(size=(10, 10)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format="PNG")
    raw = buf.getvalue()
    return MediaInput(
        mime="image/png",
        data_url="data:image/png;base64," + base64.b64encode(raw).decode(),
        bytes_len=len(raw),
    )


def request(media):
    return ModelRequest(
        run_id="mock-run",
        stage="segment",
        call_id="mock-call",
        logical_model="sam-3.1",
        operation="segmentation",
        prompt="MOCK mug",
        media=media,
    )


def client_for(captured):
    body = (Path(__file__).parent / "fixtures/sam/lossless.sse").read_text()

    def handler(req):
        captured.append(req)
        return httpx.Response(
            200, text=body, headers={"Content-Type": "text/event-stream"}
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_sam_routes_only_to_meta(configured_settings):
    assert [
        b.provider
        for b in bindings(configured_settings)
        if b.logical_model == "sam-3.1"
    ] == [ProviderId.META]
    captured = []
    async with client_for(captured) as client:
        router = ModelRouter(
            configured_settings,
            LiveTransport(configured_settings, client),
            LedgerBudgetGuard(configured_settings),
        )
        result = await router.call(request(image_input()))
    assert [r["error_code"] for r in result.metadata] == [
        "UNSUPPORTED_CAPABILITY",
        None,
    ]
    assert result.output["source_w"] == 100
    assert result.metadata[-1]["usage"] == {"images": 1}
    assert Decimal(result.metadata[-1]["cost_usd"]) == Decimal("0.0025")
    assert len(captured) == 1
    ledger = json.loads(configured_settings.ledger_path.read_text())
    assert ledger["run_id"] == "mock-run" and Decimal(ledger["cost_usd"]) == Decimal(
        "0.0025"
    )


@pytest.mark.asyncio
async def test_media_too_large_or_bad_mime_rejected(
    configured_settings, budget, transport
):
    image = image_input()
    router = ModelRouter(configured_settings, transport, budget)
    for media in (
        image.model_copy(update={"mime": "image/gif"}),
        image.model_copy(update={"bytes_len": 4_000_001}),
        image.model_copy(update={"bytes_len": 0}),
    ):
        with pytest.raises(RoutingError) as exc:
            await router.call(request(media))
        assert exc.value.code == "INVALID_IMAGE"
    assert not transport.calls


@pytest.mark.asyncio
async def test_downscale_long_side_to_1536(configured_settings):
    captured = []
    async with client_for(captured) as client:
        router = ModelRouter(
            configured_settings,
            LiveTransport(configured_settings, client),
            LedgerBudgetGuard(configured_settings),
        )
        await router.call(request(image_input((2000, 1000))))
    body = json.loads(captured[0].content)
    url = body["input"][0]["content"][1]["image_url"]
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        assert image.size == (1536, 768)


@pytest.mark.asyncio
async def test_second_sam_call_in_run_hits_cap(configured_settings):
    captured = []
    async with client_for(captured) as client:
        router = ModelRouter(
            configured_settings,
            LiveTransport(configured_settings, client),
            LedgerBudgetGuard(configured_settings),
        )
        await router.call(request(image_input()))
        with pytest.raises(RoutingError) as exc:
            await router.call(request(image_input()))
    assert exc.value.code == "RUN_BUDGET_EXCEEDED"
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_segmentation_attempt_logged_with_model_sam_3_1(
    configured_settings, caplog
):
    captured = []
    async with client_for(captured) as client:
        router = ModelRouter(
            configured_settings,
            LiveTransport(configured_settings, client),
            LedgerBudgetGuard(configured_settings),
        )
        with caplog.at_level(logging.INFO, logger="birds_eye.model_calls"):
            result = await router.call(request(image_input()))
    records = [json.loads(r.message) for r in caplog.records]
    attempts = [r for r in records if r["provider"] == "meta_model_api"]
    assert len(attempts) == 1
    assert attempts[0]["model"] == "sam-3.1"
    assert attempts[0]["operation"] == "segmentation"
    assert attempts[0]["objects"] == 1
    assert attempts[0]["run_id"] == "mock-run"
    assert attempts[0]["cost_usd"] == result.metadata[-1]["cost_usd"]
