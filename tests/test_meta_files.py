import json
import logging
import re
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from birds_eye.providers.meta_files import delete, temp_file, upload
from birds_eye.providers.sam import MediaInput, segment

BASE_URL = "https://api.meta.ai/v1"
KEY = SecretStr("FAKE_FILES_SECRET")
FILENAME = "MOCK_secret_filename_xyz.mp4"
DATA = b"MOCKvideobytes"
FILE_ID = "file_mock_1"


def files_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_upload_multipart_fields_order_and_ttl(monkeypatch):
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": FILE_ID})

    async def run():
        async with files_client(handler) as client:
            return await upload(client, BASE_URL, KEY, DATA, FILENAME, "video/mp4")

    monkeypatch.delenv("META_FILE_TTL_SECONDS", raising=False)
    assert await run() == FILE_ID
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST"
    assert str(request.url) == BASE_URL + "/files"
    body = request.content.decode()
    order = [
        body.index('name="purpose"'),
        body.index('name="expires_after[anchor]"'),
        body.index('name="expires_after[seconds]"'),
        body.index('name="file"'),
    ]
    assert order == sorted(order), "purpose/expires_after must precede the file part"
    match = re.search(r'name="expires_after\[seconds\]"\r\n\r\n([0-9]+)', body)
    assert match is not None
    assert match.group(1) == "3600"

    monkeypatch.setenv("META_FILE_TTL_SECONDS", "60")
    captured.clear()
    assert await run() == FILE_ID
    match = re.search(
        r'name="expires_after\[seconds\]"\r\n\r\n([0-9]+)',
        captured[0].content.decode(),
    )
    assert match is not None
    assert match.group(1) == "60"


@pytest.mark.asyncio
async def test_delete_404_is_success():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "DELETE"
        assert str(request.url) == BASE_URL + "/files/" + FILE_ID
        return httpx.Response(404, json={"error": "MOCK not found"})

    async with files_client(handler) as client:
        await delete(client, BASE_URL, KEY, FILE_ID)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_temp_file_always_deletes_on_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": FILE_ID})
        assert str(request.url) == BASE_URL + "/files/" + FILE_ID
        return httpx.Response(200, json={"deleted": True})

    async with files_client(handler) as client:
        with pytest.raises(RuntimeError, match="MOCK boom"):
            async with temp_file(
                client, BASE_URL, KEY, DATA, FILENAME, "video/mp4"
            ) as file_id:
                assert file_id == FILE_ID
                raise RuntimeError("MOCK boom")
    assert [call.method for call in calls] == ["POST", "DELETE"]


@pytest.mark.asyncio
async def test_sam_request_uses_file_id_for_video_part():
    sse = (Path(__file__).parent / "fixtures" / "sam" / "lossless.sse").read_text()
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, content=sse.encode(), headers={"Content-Type": "text/event-stream"}
        )

    async with files_client(handler) as client:
        await segment(
            client,
            BASE_URL,
            KEY,
            MediaInput(kind="video", file_id="file_mock_vid", mime="video/mp4"),
            "MOCK prompt",
            30.0,
        )
    assert len(captured) == 1
    body = json.loads(captured[0].content.decode())
    _, video_part = body["input"][0]["content"]
    assert video_part == {"type": "input_video", "file_id": "file_mock_vid"}
    assert "image_url" not in video_part
    assert "video_url" not in video_part


@pytest.mark.asyncio
async def test_logs_have_no_key_or_filename(caplog):
    secret = KEY.get_secret_value()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": FILE_ID})
        return httpx.Response(200, json={"deleted": True})

    async with files_client(handler) as client:
        with caplog.at_level(logging.INFO, logger="birds_eye.model_calls"):
            async with temp_file(
                client, BASE_URL, KEY, DATA, FILENAME, "video/mp4"
            ) as file_id:
                assert file_id == FILE_ID
    assert secret not in caplog.text
    assert FILENAME not in caplog.text
    records = [json.loads(record.message) for record in caplog.records[-2:]]
    assert [(r["event"], r["action"]) for r in records] == [
        ("meta_file", "upload"),
        ("meta_file", "delete"),
    ]
    for record in records:
        assert set(record) == {
            "event",
            "action",
            "bytes",
            "latency_ms",
            "status",
            "error_code",
        }
        assert secret not in json.dumps(record)
        assert FILENAME not in json.dumps(record)
    assert records[0]["bytes"] == len(DATA)
    assert all(r["status"] == "success" for r in records)
