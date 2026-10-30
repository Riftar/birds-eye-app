"""SAM 3.1 segmentation over the Meta Model API (Responses API SSE).

Image only, text prompt. The wire format is the documented
segmentation-output grammar: each ``response.output_text.delta`` payload
carries frame lines of the form ``<Nf>`` followed by comma-separated
records ``OBJECT_ID`` + box token + mask token. An empty lane means zero
matches, which is a valid result, not an error.

Mask rasters are decoded with :func:`meta_sam_parser.decode_mask_to_raster`
when the optional ``sam`` extra is installed; otherwise the payload is kept
undecoded and only boxes are computed.
# TODO(meta-08): vendor a lossless/one-bit mask decoder so ``raster`` is
# populated without the optional ``meta_sam_parser`` extra.
"""

from __future__ import annotations

import math
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

from birds_eye.providers.contracts import ProviderError
from birds_eye.providers.logging import log_attempt

MODEL_ID = "sam-3.1"
PROVIDER_ID = "meta_model_api"

try:  # Optional extra: pip install birds-eye[sam].
    from meta_sam_parser import SegmentationMask as _WireMask
    from meta_sam_parser import decode_mask_to_raster as _decode_raster
except ImportError:  # pragma: no cover - decoder absent.
    _WireMask = None
    _decode_raster = None


class MediaInput(BaseModel):
    """Image input for segmentation. ``data_url`` is a data: or https: URL."""

    kind: Literal["image"] = "image"
    data_url: str | None = None
    file_id: str | None = None
    mime: str | None = None
    bytes_len: int | None = None

    @property
    def image_url(self) -> str:
        if self.data_url:
            return self.data_url
        if self.file_id:
            return self.file_id
        raise ValueError("MediaInput needs data_url or file_id.")


class Box(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class MaskInfo(BaseModel):
    h: int
    w: int
    encoding: Literal["lossless", "one_bit"]
    payload_len: int
    raster: bytes | None = None


class SegmentedObject(BaseModel):
    object_id: str
    frame: int
    box: Box
    confidence: float | None = None
    mask: MaskInfo


class SegmentationResult(BaseModel):
    source_w: int = 0
    source_h: int = 0
    objects: list[SegmentedObject] = Field(default_factory=list)


_FRAME_RE = re.compile(r"<([0-9]+)f(?:;[^>]*)?>(.*)$", re.DOTALL)
_RECORD_RE = re.compile(r",?([0-9]+)(?=<\|)")
_TOKEN_RE = re.compile(r"<\|([A-Za-z][A-Za-z0-9_.-]*)(?:;([^|]*))?\|>")
_SIGNED_INT_RE = re.compile(r"-?[0-9]+$")
_UNSIGNED_INT_RE = re.compile(r"[0-9]+$")
_MASK_DATA_RE = re.compile(r"([0-9]+),([0-9]+),([!~][^|]+)$")
_BOX_KEYS = frozenset({"x1", "y1", "x2", "y2", "w", "h", "c"})
_MASK_KEYS = frozenset({"x", "y", "data", "c"})
_ENCODING_BY_MARKER = {"~": "lossless", "!": "one_bit"}


def _malformed(message: str) -> ProviderError:
    return ProviderError("MALFORMED_RESPONSE", message)


def _read_fields(body: str | None, allowed: frozenset[str]) -> dict[str, str] | None:
    values: dict[str, str] = {}
    for part in [] if body is None else body.split(";"):
        part = part.strip()
        if not part:
            continue
        key, sep, value = part.partition("=")
        key = key.strip()
        if not sep or key not in allowed or key in values:
            return None
        values[key] = value.strip()
    return values


def _read_confidence(values: dict[str, str]) -> float | None:
    raw = values.get("c")
    if raw is None:
        return None
    try:
        confidence = float(raw)
    except ValueError:
        return None
    if math.isnan(confidence) or math.isinf(confidence):
        return None
    return confidence


def _decode_payload(encoding: str, payload: str, w: int, h: int) -> bytes | None:
    if _decode_raster is None or _WireMask is None:
        return None
    try:
        return bytes(
            _decode_raster(
                _WireMask(encoding=encoding, payload=payload, width=w, height=h)
            )
        )
    except Exception:  # noqa: BLE001 - decode is best-effort over varied errors.
        return None


def _parse_record(object_id: str, region: str) -> tuple[Box, MaskInfo, float | None]:
    tokens: list[tuple[str, str | None]] = []
    pos = 0
    for match in _TOKEN_RE.finditer(region):
        if match.start() != pos:
            raise _malformed("Segmentation record has unexpected text.")
        tokens.append((match.group(1), match.group(2)))
        pos = match.end()
    if pos != len(region):
        raise _malformed("Segmentation record has unexpected text.")
    boxes = [body for name, body in tokens if name == "box"]
    masks = [body for name, body in tokens if name == "mask"]
    if len(boxes) != 1 or len(masks) != 1:
        raise _malformed("Segmentation record needs one box and one mask.")
    box_fields = _read_fields(boxes[0], _BOX_KEYS)
    mask_fields = _read_fields(masks[0], _MASK_KEYS)
    if box_fields is None or mask_fields is None:
        raise _malformed("Segmentation record has invalid fields.")
    coords = [box_fields.get(key) for key in ("x1", "y1", "x2", "y2")]
    if any(
        value is None or _SIGNED_INT_RE.fullmatch(value) is None for value in coords
    ):
        raise _malformed("Segmentation box needs integer x1/y1/x2/y2.")
    dims = [box_fields.get(key) for key in ("w", "h")]
    if any(
        value is None or _UNSIGNED_INT_RE.fullmatch(value) is None for value in dims
    ):
        raise _malformed("Segmentation box needs unsigned w/h.")
    if mask_fields.get("x") != "0" or mask_fields.get("y") != "0":
        raise _malformed("Segmentation mask needs x=0;y=0.")
    data = _MASK_DATA_RE.fullmatch(mask_fields.get("data") or "")
    if data is None:
        raise _malformed("Segmentation mask needs data=H,W,<enc><payload>.")
    mask_h, mask_w = int(data.group(1)), int(data.group(2))
    if mask_h <= 0 or mask_w <= 0:
        raise _malformed("Segmentation mask dimensions must be positive.")
    payload = data.group(3)
    encoding = _ENCODING_BY_MARKER[payload[0]]
    box_confidence = _read_confidence(box_fields)
    mask_confidence = _read_confidence(mask_fields)
    if "c" in box_fields and box_confidence is None:
        raise _malformed("Segmentation box confidence is not a number.")
    if "c" in mask_fields and mask_confidence is None:
        raise _malformed("Segmentation mask confidence is not a number.")
    confidence = box_confidence if box_confidence is not None else mask_confidence
    box = Box(
        x1=int(coords[0]),
        y1=int(coords[1]),
        x2=int(coords[2]),
        y2=int(coords[3]),
    )
    mask = MaskInfo(
        h=mask_h,
        w=mask_w,
        encoding=encoding,
        payload_len=len(payload),
        raster=_decode_payload(encoding, payload, mask_w, mask_h),
    )
    return box, mask, confidence


def parse_segmentation_text(text: str) -> SegmentationResult:
    """Parse accumulated output-text deltas into a SegmentationResult.

    Object ids are sparse and stable: every record keeps its own id and the
    result never assumes positional numbering.
    """

    result = SegmentationResult()
    if not text.strip():
        return result
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        header = _FRAME_RE.fullmatch(line)
        if header is None:
            raise _malformed("Segmentation line needs a <Nf> frame header.")
        frame = int(header.group(1))
        rest = header.group(2).strip()
        if not rest:
            continue
        matches = list(_RECORD_RE.finditer(rest))
        if not matches or matches[0].start() != 0:
            raise _malformed("Segmentation line needs id-led records.")
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(rest)
            region = rest[match.end() : end]
            box, mask, confidence = _parse_record(match.group(1), region)
            if not result.objects:
                result.source_w, result.source_h = mask.w, mask.h
            result.objects.append(
                SegmentedObject(
                    object_id=match.group(1),
                    frame=frame,
                    box=box,
                    confidence=confidence,
                    mask=mask,
                )
            )
    return result


def build_request_body(
    prompt: str,
    image_url: str,
    *,
    mask_encoding: str | None = None,
    include_confidence: bool = False,
) -> dict:
    body: dict = {
        "model": MODEL_ID,
        "stream": True,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
    }
    metadata: dict = {}
    if mask_encoding is not None:
        metadata["mask_encoding"] = mask_encoding
    if include_confidence:
        metadata["include_confidence"] = "true"
    if metadata:
        body["metadata"] = metadata
    return body


def _error_for_status(status: int) -> ProviderError:
    if status in (401, 403):
        return ProviderError("AUTHENTICATION_ERROR")
    if status == 429:
        return ProviderError("RATE_LIMITED")
    if status >= 500:
        return ProviderError("PROVIDER_5XX")
    return ProviderError("INVALID_REQUEST")


async def _read_output_text(response) -> str:
    """Accumulate output_text deltas until response.completed."""

    import json as _json

    event: str | None = None
    data_lines: list[str] = []
    deltas: list[str] = []
    completed = False

    def dispatch() -> None:
        nonlocal completed
        if event is None:
            return
        payload = "\n".join(data_lines)
        if event == "response.output_text.delta":
            try:
                data = _json.loads(payload) if payload else None
            except ValueError:
                raise _malformed("Segmentation delta is not JSON.") from None
            if not isinstance(data, dict) or not isinstance(data.get("delta"), str):
                raise _malformed("Segmentation delta has no text.") from None
            deltas.append(data["delta"])
        elif event == "response.completed":
            completed = True
        elif event in ("response.failed", "response.incomplete"):
            raise ProviderError("PROVIDER_5XX")
        elif event in (
            "response.refusal.delta",
            "response.refusal.done",
        ):
            raise ProviderError("SAFETY_REFUSAL")
        elif payload == "[DONE]":
            return

    async for line in response.aiter_lines():
        if line == "":
            dispatch()
            event, data_lines = None, []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
        elif line.strip() == "[DONE]":
            continue
    dispatch()
    if not completed:
        raise _malformed("Segmentation stream ended without response.completed.")
    return "".join(deltas)


async def segment(
    client,
    base_url: str,
    key,
    image: MediaInput,
    prompt: str,
    timeout: float,
    *,
    mask_encoding: str | None = None,
    include_confidence: bool = False,
) -> SegmentationResult:
    """Segment an image with SAM 3.1 over the Responses API (SSE)."""

    import httpx

    record = {
        "event": "provider_attempt",
        "run_id": None,
        "stage": "segment",
        "call_id": None,
        "attempt": 1,
        "logical_model": MODEL_ID,
        "provider": PROVIDER_ID,
        "model": MODEL_ID,
        "concrete_model": MODEL_ID,
        "status": "failed",
        "error_code": None,
        "latency_ms": 0,
        "requested_max_tokens": None,
        "effective_max_tokens": None,
        "max_completion_tokens": None,
        "reasoning_effort": None,
        "usage": None,
        "cost_usd": None,
        "finish_reason": None,
        "truncated": False,
    }
    start = time.monotonic()
    try:
        try:
            image_url = image.image_url
        except ValueError:
            raise ProviderError("INVALID_REQUEST") from None
        body = build_request_body(
            prompt,
            image_url,
            mask_encoding=mask_encoding,
            include_confidence=include_confidence,
        )
        headers = {
            # The key value is used here only; it never enters logs or records.
            "Authorization": "Bearer " + key.get_secret_value(),
            "Accept": "text/event-stream",
        }
        try:
            async with client.stream(
                "POST",
                base_url.rstrip("/") + "/responses",
                headers=headers,
                json=body,
                timeout=timeout,
            ) as response:
                if response.status_code >= 400:
                    raise _error_for_status(response.status_code)
                text = await _read_output_text(response)
        except httpx.TimeoutException:
            raise ProviderError("TIMEOUT") from None
        except httpx.RequestError:
            raise ProviderError("CONNECTION_ERROR") from None
        result = parse_segmentation_text(text)
        record["status"] = "success"
        return result
    except ProviderError as exc:
        record["error_code"] = exc.code
        raise
    finally:
        record["latency_ms"] = round((time.monotonic() - start) * 1000, 3)
        log_attempt(record)


__all__ = [  # noqa: RUF022 - grouped constants, models, functions.
    "MODEL_ID",
    "PROVIDER_ID",
    "Box",
    "MaskInfo",
    "MediaInput",
    "SegmentedObject",
    "SegmentationResult",
    "build_request_body",
    "parse_segmentation_text",
    "segment",
]
