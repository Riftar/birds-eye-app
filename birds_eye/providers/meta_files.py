"""Async client for the Meta Model API Files API (``/v1/files``).

Short-TTL uploads for SAM media: files are uploaded with
``expires_after[anchor]=created_at`` and a small ``expires_after[seconds]``
TTL, then deleted after the run. Every call logs one JSON line with event
``"meta_file"``; file contents, user filenames and keys never enter logs.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from birds_eye.providers.contracts import ProviderError

logger = logging.getLogger("birds_eye.model_calls")

DEFAULT_TTL_SECONDS = 3600
DEFAULT_INLINE_MAX_BYTES = 8 * 1024 * 1024
INLINE_DATA_URL_MAX_BYTES = 50 * 1024 * 1024
FILES_API_MAX_BYTES = 1024**3
VIDEO_MIMES = frozenset({"video/mp4", "video/quicktime"})


def ttl_seconds_or_default(ttl_seconds: int | None = None) -> int:
    if ttl_seconds is not None:
        return ttl_seconds
    try:
        return int(os.environ.get("META_FILE_TTL_SECONDS") or DEFAULT_TTL_SECONDS)
    except ValueError:
        return DEFAULT_TTL_SECONDS


def inline_max_bytes_or_default(limit: int | None = None) -> int:
    if limit is not None:
        return limit
    try:
        return int(os.environ.get("INLINE_MEDIA_MAX_BYTES") or DEFAULT_INLINE_MAX_BYTES)
    except ValueError:
        return DEFAULT_INLINE_MAX_BYTES


def should_use_files_api(
    mime: str | None,
    bytes_len: int | None,
    *,
    inline_max_bytes: int | None = None,
) -> bool:
    """Policy: inline data URLs for images; Files API for video or big bytes."""

    if (mime or "").lower() in VIDEO_MIMES:
        return True
    return bytes_len is not None and bytes_len > inline_max_bytes_or_default(
        inline_max_bytes
    )


def _error_for_status(status: int) -> ProviderError:
    if status in (401, 403):
        return ProviderError("AUTHENTICATION_ERROR")
    if status == 429:
        return ProviderError("RATE_LIMITED")
    if status >= 500:
        return ProviderError("PROVIDER_5XX")
    return ProviderError("INVALID_REQUEST")


def _log(
    action: str, size: int, latency_ms: float, status: str, error_code: str | None
) -> None:
    logger.info(
        json.dumps(
            {
                "event": "meta_file",
                "action": action,
                "bytes": size,
                "latency_ms": latency_ms,
                "status": status,
                "error_code": error_code,
            }
        )
    )


async def upload(
    client: Any,
    base_url: str,
    key: Any,
    data: bytes,
    filename: str,
    mime: str,
    *,
    ttl_seconds: int | None = None,
    timeout: float | None = None,
) -> str:
    """Upload bytes; return the Files API file id.

    ``purpose`` and ``expires_after`` fields are sent before the file part,
    and the file is the final part.
    """

    import httpx

    ttl = ttl_seconds_or_default(ttl_seconds)
    start = time.monotonic()
    error_code: str | None = None
    try:
        try:
            response = await client.post(
                base_url.rstrip("/") + "/files",
                # The key value is used here only; it never enters logs.
                headers={"Authorization": "Bearer " + key.get_secret_value()},
                data={
                    "purpose": "user_data",
                    "expires_after[anchor]": "created_at",
                    "expires_after[seconds]": str(ttl),
                },
                files={"file": (filename, data, mime)},
                timeout=timeout,
            )
        except httpx.TimeoutException:
            raise ProviderError("TIMEOUT") from None
        except httpx.RequestError:
            raise ProviderError("CONNECTION_ERROR") from None
        if response.status_code >= 400:
            raise _error_for_status(response.status_code)
        try:
            file_id = response.json()["id"]
        except (ValueError, KeyError, TypeError):
            raise ProviderError("MALFORMED_RESPONSE") from None
        if not isinstance(file_id, str) or not file_id:
            raise ProviderError("MALFORMED_RESPONSE")
        return file_id
    except ProviderError as exc:
        error_code = exc.code
        raise
    finally:
        _log(
            "upload",
            len(data),
            round((time.monotonic() - start) * 1000, 3),
            "success" if error_code is None else "failed",
            error_code,
        )


async def delete(
    client: Any,
    base_url: str,
    key: Any,
    file_id: str,
    *,
    timeout: float | None = None,
) -> None:
    """Delete a file. A 404 counts as success (already gone)."""

    import httpx

    start = time.monotonic()
    error_code: str | None = None
    try:
        try:
            response = await client.delete(
                base_url.rstrip("/") + "/files/" + file_id,
                # The key value is used here only; it never enters logs.
                headers={"Authorization": "Bearer " + key.get_secret_value()},
                timeout=timeout,
            )
        except httpx.TimeoutException:
            raise ProviderError("TIMEOUT") from None
        except httpx.RequestError:
            raise ProviderError("CONNECTION_ERROR") from None
        if response.status_code == 404:
            return
        if response.status_code >= 400:
            raise _error_for_status(response.status_code)
    except ProviderError as exc:
        error_code = exc.code
        raise
    finally:
        _log(
            "delete",
            0,
            round((time.monotonic() - start) * 1000, 3),
            "success" if error_code is None else "failed",
            error_code,
        )


@asynccontextmanager
async def temp_file(
    client: Any,
    base_url: str,
    key: Any,
    data: bytes,
    filename: str,
    mime: str,
    *,
    ttl_seconds: int | None = None,
    timeout: float | None = None,
) -> AsyncIterator[str]:
    """Upload, yield the file id, and always delete (best effort)."""

    file_id = await upload(
        client,
        base_url,
        key,
        data,
        filename,
        mime,
        ttl_seconds=ttl_seconds,
        timeout=timeout,
    )
    try:
        yield file_id
    finally:
        try:
            await delete(client, base_url, key, file_id, timeout=timeout)
        except Exception:  # noqa: S110, BLE001 - best-effort cleanup, already logged.
            pass


__all__ = [
    "DEFAULT_INLINE_MAX_BYTES",
    "DEFAULT_TTL_SECONDS",
    "FILES_API_MAX_BYTES",
    "INLINE_DATA_URL_MAX_BYTES",
    "VIDEO_MIMES",
    "delete",
    "inline_max_bytes_or_default",
    "should_use_files_api",
    "temp_file",
    "ttl_seconds_or_default",
    "upload",
]
