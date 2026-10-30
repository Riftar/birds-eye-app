import json
import logging
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from birds_eye.providers.contracts import ProviderError
from birds_eye.providers.sam import (
    MediaInput,
    parse_segmentation_text,
    segment,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sam"
BASE_URL = "https://api.meta.ai/v1"
PROMPT = "MOCK red mug"
IMAGE = MediaInput(
    data_url="data:image/png;base64,TU9DSw==", mime="image/png", bytes_len=8
)
KEY = SecretStr("FAKE_SAM_SECRET")


def sse_client(body: str, status: int = 200, captured: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(
            status,
            content=body.encode(),
            headers={"Content-Type": "text/event-stream"},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.mark.asyncio
async def test_request_shape():
    captured = []
    async with sse_client(read_fixture("lossless.sse"), captured=captured) as client:
        await segment(client, BASE_URL, KEY, IMAGE, PROMPT, 30.0)
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST"
    assert str(request.url) == BASE_URL + "/responses"
    assert request.headers["accept"] == "text/event-stream"
    assert request.headers["authorization"] == "Bearer FAKE_SAM_SECRET"
    body = json.loads(request.content.decode())
    assert body["model"] == "sam-3.1"
    assert body["stream"] is True
    message = body["input"][0]
    assert (message["type"], message["role"]) == ("message", "user")
    text_part, image_part = message["content"]
    assert text_part == {"type": "input_text", "text": PROMPT}
    assert image_part == {"type": "input_image", "image_url": IMAGE.data_url}
    assert "metadata" not in body


@pytest.mark.asyncio
async def test_request_shape_with_mask_options():
    captured = []
    async with sse_client(read_fixture("one_bit.sse"), captured=captured) as client:
        await segment(
            client,
            BASE_URL,
            KEY,
            IMAGE,
            PROMPT,
            30.0,
            mask_encoding="one_bit",
            include_confidence=True,
        )
    body = json.loads(captured[0].content.decode())
    assert body["metadata"] == {
        "mask_encoding": "one_bit",
        "include_confidence": "true",
    }


@pytest.mark.asyncio
async def test_parse_single_object_lossless():
    async with sse_client(read_fixture("lossless.sse")) as client:
        result = await segment(client, BASE_URL, KEY, IMAGE, PROMPT, 30.0)
    assert (result.source_w, result.source_h) == (4, 3)
    assert len(result.objects) == 1
    obj = result.objects[0]
    assert (obj.object_id, obj.frame) == ("1", 0)
    assert (obj.box.x1, obj.box.y1, obj.box.x2, obj.box.y2) == (10, 20, 110, 120)
    assert obj.confidence is None
    assert (obj.mask.h, obj.mask.w) == (3, 4)
    assert obj.mask.encoding == "lossless"
    assert obj.mask.payload_len == len("~FAKELOSSLESSPAYLOAD")
    assert obj.mask.raster is None


@pytest.mark.asyncio
async def test_parse_sparse_ids_and_confidence():
    async with sse_client(read_fixture("sparse_ids_confidence.sse")) as client:
        result = await segment(client, BASE_URL, KEY, IMAGE, PROMPT, 30.0)
    assert [obj.object_id for obj in result.objects] == ["3", "7"]
    assert [obj.confidence for obj in result.objects] == [0.93, 0.81]
    assert (result.objects[0].box.x1, result.objects[0].box.y2) == (5, 60)
    assert (result.objects[1].box.x1, result.objects[1].box.y2) == (60, 100)


@pytest.mark.asyncio
async def test_zero_matches_is_empty_result_not_error():
    async with sse_client(read_fixture("zero_matches.sse")) as client:
        result = await segment(client, BASE_URL, KEY, IMAGE, PROMPT, 30.0)
    assert result.objects == []
    assert (result.source_w, result.source_h) == (0, 0)
    assert parse_segmentation_text("  \n").objects == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "AUTHENTICATION_ERROR"),
        (403, "AUTHENTICATION_ERROR"),
        (429, "RATE_LIMITED"),
        (500, "PROVIDER_5XX"),
        (503, "PROVIDER_5XX"),
        (400, "INVALID_REQUEST"),
    ],
)
async def test_http_error_mapping(status, code):
    async with sse_client("", status=status) as client:
        with pytest.raises(ProviderError) as error:
            await segment(client, BASE_URL, KEY, IMAGE, PROMPT, 30.0)
    assert error.value.code == code


@pytest.mark.asyncio
async def test_key_value_never_logged(caplog):
    async with sse_client(read_fixture("lossless.sse")) as client:
        with caplog.at_level(logging.INFO, logger="birds_eye.model_calls"):
            await segment(client, BASE_URL, KEY, IMAGE, PROMPT, 30.0)
    assert caplog.records, "SAM segment must log one JSON line per attempt"
    assert KEY.get_secret_value() not in caplog.text
    record = json.loads(caplog.records[-1].message)
    assert (record["provider"], record["model"], record["status"]) == (
        "meta_model_api",
        "sam-3.1",
        "success",
    )
    assert KEY.get_secret_value() not in json.dumps(record)
    caplog.clear()
    async with sse_client("", status=429) as client:
        with (
            caplog.at_level(logging.INFO, logger="birds_eye.model_calls"),
            pytest.raises(ProviderError),
        ):
            await segment(client, BASE_URL, KEY, IMAGE, PROMPT, 30.0)
    assert KEY.get_secret_value() not in caplog.text
    failed = json.loads(caplog.records[-1].message)
    assert (failed["status"], failed["error_code"]) == ("failed", "RATE_LIMITED")


@pytest.mark.asyncio
async def test_decode_one_bit_raster_when_parser_available():
    pytest.importorskip("meta_sam_parser")
    async with sse_client(read_fixture("one_bit.sse")) as client:
        result = await segment(client, BASE_URL, KEY, IMAGE, PROMPT, 30.0)
    (obj,) = result.objects
    assert obj.mask.encoding == "one_bit"
    assert obj.mask.raster == bytes((1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0))


@pytest.mark.asyncio
async def test_malformed_delta_is_error():
    body = (
        "event: response.output_text.delta\n"
        'data: {"type": "response.output_text.delta", "delta": "hello"}\n'
        "\n"
        "event: response.completed\n"
        'data: {"type": "response.completed"}\n'
        "\n"
    )
    async with sse_client(body) as client:
        with pytest.raises(ProviderError) as error:
            await segment(client, BASE_URL, KEY, IMAGE, PROMPT, 30.0)
    assert error.value.code == "MALFORMED_RESPONSE"


@pytest.mark.asyncio
async def test_missing_completed_is_error():
    body = (
        "event: response.output_text.delta\n"
        'data: {"type": "response.output_text.delta", "delta": "<0f>"}\n'
        "\n"
    )
    async with sse_client(body) as client:
        with pytest.raises(ProviderError) as error:
            await segment(client, BASE_URL, KEY, IMAGE, PROMPT, 30.0)
    assert error.value.code == "MALFORMED_RESPONSE"


@pytest.mark.asyncio
async def test_missing_image_url_is_invalid_request():
    async with sse_client(read_fixture("lossless.sse")) as client:
        with pytest.raises(ProviderError) as error:
            await segment(client, BASE_URL, KEY, MediaInput(), PROMPT, 30.0)
    assert error.value.code == "INVALID_REQUEST"
