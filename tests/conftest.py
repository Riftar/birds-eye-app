import shutil
import socket
from collections import deque
from pathlib import Path

import pytest
from pydantic import SecretStr

from birds_eye.config import Settings
from birds_eye.providers.contracts import ModelRequest, ProviderError, Reservation


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must not use network connections")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture
def settings(monkeypatch):
    for name in (
        "BASETEN_API_KEY",
        "MODAL_TOKEN_ID",
        "MODAL_TOKEN_SECRET",
        "MODEL_API_KEY",
        "MODAL_MUSE_MODEL_ID",
        "DEFAULT_SCENARIO_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    return Settings()


@pytest.fixture
def configured_settings(settings):
    settings.baseten_api_key = SecretStr("FAKE_BASETEN_SECRET")
    settings.modal_token_id = SecretStr("FAKE_MODAL_ID")
    settings.modal_token_secret = SecretStr("FAKE_MODAL_SECRET")
    settings.model_api_key = SecretStr("FAKE_META_SECRET")
    settings.modal_muse_model_id = "mock-modal-muse-deployment"
    return settings


class FakeTransport:
    def __init__(self, replies=()):
        self.replies = deque(replies)
        self.calls = []

    async def invoke(self, binding, request):
        self.calls.append((binding, request))
        result = self.replies.popleft()
        if isinstance(result, Exception):
            raise result
        return result


class FakeBudgetGuard:
    def __init__(self, rejected=()):
        self.rejected = set(rejected)
        self.reservations = []
        self.settlements = []

    async def reserve(self, provider, max_cost_usd):
        if provider in self.rejected:
            raise ProviderError("BUDGET_EXHAUSTED")
        reservation = Reservation(id=str(len(self.reservations)))
        self.reservations.append((provider, max_cost_usd, reservation))
        return reservation

    async def settle(self, reservation, actual_cost_usd):
        self.settlements.append((reservation, actual_cost_usd))


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def budget():
    return FakeBudgetGuard()


@pytest.fixture
def muse_request():
    return ModelRequest(
        run_id="run-1",
        stage="writer",
        call_id="call-1",
        logical_model="muse-spark",
        operation="text",
        max_tokens=40,
    )


@pytest.fixture
def scenario(tmp_path):
    target = tmp_path / "tencent-scenario"
    shutil.copytree(Path("mock-data/default"), target)
    return target
