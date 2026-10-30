import httpx
import pytest

from birds_eye.app import create_app
from birds_eye.core.inputs import load_inputs


@pytest.fixture
async def client(settings):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_health_and_entry_points_without_credentials(client):
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    assert (await client.get("/meta")).json()["status"] == "PLACEHOLDER"
    assert (await client.get("/tencent")).json()["owner"] == "WorkBuddy"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/meta/runs", "PIPELINE_NOT_IMPLEMENTED"),
        ("/tencent/runs", "WORKBUDDY_PIPELINE_NOT_CONNECTED"),
    ],
)
async def test_run_endpoints_validate_and_return_stub(client, path, code, scenario):
    for kwargs in ({}, {"json": load_inputs(scenario).model_dump(mode="json")}):
        response = await client.post(path, **kwargs)
        assert response.status_code == 501
        assert response.json()["code"] == code
    assert (await client.post(path, json={})).status_code == 422
