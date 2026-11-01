import httpx
import pytest

from birds_eye.app import create_app


@pytest.mark.asyncio
async def test_home_script_escapes_truncation_newline(settings):
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        html = (await client.get("/")).text

    assert "'\n(output truncated" not in html
