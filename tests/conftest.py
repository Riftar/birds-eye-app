import hashlib
import shutil
import socket
from collections import deque
from pathlib import Path

import pytest
from pydantic import SecretStr

from birds_eye.config import Settings
from birds_eye.providers.contracts import ModelRequest, ProviderError, Reservation


@pytest.fixture(autouse=True)
def test_suite_never_touches_repo_ledger():
    path = Path(__file__).resolve().parent.parent / "var" / "ledger.jsonl"

    def snapshot():
        if not path.exists():
            return None
        stat = path.stat()
        return (
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).digest(),
        )

    before = snapshot()
    yield
    assert snapshot() == before, "Tests created or modified the repository ledger"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must not use network connections")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture(autouse=True)
def fake_rate_limiter(monkeypatch):
    from birds_eye.providers.router import AsyncRateLimiter

    now = [0.0]

    async def sleep(delay):
        now[0] += delay

    limiter = AsyncRateLimiter(clock=lambda: now[0], sleep=sleep)
    monkeypatch.setattr("birds_eye.providers.router.process_limiter", lambda: limiter)


@pytest.fixture
def settings(monkeypatch, tmp_path):
    for name in (
        "BASETEN_API_KEY",
        "MODAL_TOKEN_ID",
        "MODAL_TOKEN_SECRET",
        "MODEL_API_KEY",
        "MODAL_MUSE_MODEL_ID",
        "DEFAULT_SCENARIO_DIR",
        "PROVIDER_MODE",
        "FORCE_FAIL_PROVIDERS",
        "MAX_CALLS_PER_RUN",
        "MAX_TOKENS_PER_RUN",
        "MUSE_MAX_TOKENS_DEFAULT",
        "BASETEN_BASE_URL",
        "META_MODEL_API_BASE_URL",
        "MODAL_MUSE_ENDPOINT",
        "META_REASONING_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)
    return Settings(provider_max_retries=0, ledger_path=tmp_path / "ledger.jsonl")


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
