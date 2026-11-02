import asyncio
import re
import shutil
from pathlib import Path

import httpx
import pytest

from birds_eye.app import create_app


@pytest.mark.asyncio
async def test_home_script_escapes_truncation_newline(settings):
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        html = (await client.get("/")).text

    assert "'\n(output truncated" not in html
    assert "Output cut off" in html

    title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert title and ":" in title.group(1) and "—" not in title.group(1)
    heading = re.search(r"<h1>(.*?)</h1>", html, re.DOTALL)
    assert heading and ":" in heading.group(1) and "—" not in heading.group(1)

    script = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    assert script
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to parse the inline JavaScript")
    process = await asyncio.create_subprocess_exec(
        node, "--check", stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate(script.group(1).encode())
    assert process.returncode == 0, stderr.decode()


@pytest.mark.asyncio
async def test_demo_rendering_and_pending_run(settings):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to exercise the demo renderer")
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        html = (await client.get("/")).text
        css = (await client.get("/design/components.css")).text
    script = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    assert script
    harness = Path("tests/ui_demo_check.js").read_text()
    process = await asyncio.create_subprocess_exec(
        node, stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate(
        (harness + "\n" + script.group(1) + "\nverifyDemo().catch(e => { console.error(e); process.exitCode = 1; });").encode()
    )
    assert process.returncode == 0, stderr.decode()
    assert re.search(r"\.output\s*\{[^}]*font-family:\s*var\(--font-body\)", css)
