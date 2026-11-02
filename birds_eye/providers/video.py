"""Bounded, temporary video preprocessing using the system ffmpeg."""

import base64
import binascii
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from birds_eye.providers.contracts import MediaInput, ProviderError


def preprocess_video(media: MediaInput, settings) -> MediaInput:
    executable = shutil.which(settings.ffmpeg_bin)
    if not executable:
        raise ProviderError(
            "FFMPEG_NOT_FOUND",
            "ffmpeg was not found; set FFMPEG_BIN or install ffmpeg.",
        )
    prefix = f"data:{media.mime};base64,"
    if media.mime not in {
        "video/mp4",
        "video/quicktime",
    } or not media.data_url.startswith(prefix):
        raise ProviderError("INVALID_VIDEO")
    encoded = media.data_url[len(prefix) :]
    if len(encoded) > 4 * ((settings.max_video_bytes + 2) // 3):
        raise ProviderError("INVALID_VIDEO")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if (
            len(raw) != media.bytes_len
            or not raw
            or len(raw) > settings.max_video_bytes
        ):
            raise ValueError
    except (ValueError, binascii.Error):
        raise ProviderError("INVALID_VIDEO") from None
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "input"
        output = Path(directory) / "output.mp4"
        source.write_bytes(raw)
        try:
            result = subprocess.run(
                [
                    executable,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-t",
                    "8",
                    "-vf",
                    "fps=8,scale=w='min(720,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-progress",
                    "pipe:1",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            counts = re.findall(r"^frame=\s*(\d+)$", result.stdout, re.MULTILINE)
            frames = int(counts[-1]) if counts else 0
            data = output.read_bytes()
            if not 1 <= frames <= 64 or not data:
                raise ValueError
        except (subprocess.SubprocessError, OSError, ValueError):
            raise ProviderError(
                "INVALID_VIDEO", "Video preprocessing failed."
            ) from None
    return media.model_copy(
        update={
            "mime": "video/mp4",
            "data_url": "data:video/mp4;base64," + base64.b64encode(data).decode(),
            "bytes_len": len(data),
            "frames": frames,
        }
    )
