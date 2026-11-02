import base64
import json
import shutil
import subprocess
from decimal import Decimal

import httpx
import pytest

from birds_eye.providers.budget import LedgerBudgetGuard
from birds_eye.providers.contracts import MediaInput, ModelRequest, RoutingError
from birds_eye.providers.router import ModelRouter
from birds_eye.providers.sam import parse_segmentation_text
from birds_eye.providers.transport import LiveTransport
from birds_eye.providers.video import preprocess_video


def video(data):
    return MediaInput(
        kind="video",
        mime="video/mp4",
        data_url="data:video/mp4;base64," + base64.b64encode(data).decode(),
        bytes_len=len(data),
    )


def request(media):
    return ModelRequest(
        run_id="mock",
        stage="segmenter",
        call_id="video",
        logical_model="sam-3.1",
        operation="segmentation",
        prompt="MOCK square",
        media=media,
    )


def test_preprocess_caps_duration_fps_and_size(tmp_path, settings):
    if not shutil.which("ffmpeg"):
        pytest.skip("system ffmpeg unavailable")
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=800x400:r=12:d=2",
            "-c:v",
            "mpeg4",
            str(clip),
        ],
        check=True,
    )
    result = preprocess_video(video(clip.read_bytes()), settings)
    assert result.frames == 16
    output = tmp_path / "processed.mp4"
    output.write_bytes(base64.b64decode(result.data_url.split(",")[1]))
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert (stream["width"], stream["height"], stream["r_frame_rate"]) == (
        720,
        360,
        "8/1",
    )


def test_parse_multiframe_tracks_sparse_and_unordered_frames():
    record = "3<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|><|mask;x=0;y=0;data=1,1,!x|>"
    parsed = parse_segmentation_text(f"<7f>{record}<2f>{record}<9f>")
    assert [(o.frame, o.object_id) for o in parsed.objects] == [(7, "3"), (2, "3")]


@pytest.mark.asyncio
async def test_video_request_billing_and_frame_cap(configured_settings, monkeypatch):
    media = video(b"MOCK")
    monkeypatch.setattr(
        "birds_eye.providers.video.preprocess_video",
        lambda m, s: m.model_copy(update={"frames": 16}),
    )
    calls = []

    def handler(req):
        calls.append(req)
        if req.method == "DELETE":
            return httpx.Response(204)
        if req.url.path.endswith("/files"):
            return httpx.Response(200, json={"id": "file_mock"})
        return httpx.Response(
            200,
            text='event: response.completed\ndata: {"response":{"usage":{"video_frames_processed":60}}}\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = LedgerBudgetGuard(configured_settings)
        router = ModelRouter(
            configured_settings, LiveTransport(configured_settings, client), ledger
        )
        result = await router.call(request(media))
        assert result.metadata[-1]["billed_frames"] == 60
        assert Decimal(result.metadata[-1]["cost_usd"]) == Decimal("0.012")
        body = json.loads(calls[1].content)
        assert body["input"][0]["content"][1] == {
            "type": "input_video",
            "file_id": "file_mock",
        }
        assert body["metadata"] == {"mask_encoding": "one_bit"}
        assert calls[-1].method == "DELETE"
        configured_settings.max_video_frames_per_run = 15
        router = ModelRouter(
            configured_settings, LiveTransport(configured_settings, client), ledger
        )
        with pytest.raises(RoutingError, match="Provider call failed") as error:
            await router.call(request(media))
        assert error.value.code == "VIDEO_FRAME_CAP"
        assert len(calls) == 3
