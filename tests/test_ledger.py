import json
from decimal import Decimal

import pytest
from conftest import FakeTransport
from fastapi.testclient import TestClient
from pydantic import SecretStr

from birds_eye.app import create_app
from birds_eye.config import Settings
from birds_eye.providers.budget import LedgerBudgetGuard
from birds_eye.providers.contracts import ProviderId, ProviderReply
from birds_eye.providers.router import ModelRouter, NoCostBudget


def test_stub_mode_uses_no_cost_budget(settings):
    settings.provider_mode = "stub"
    settings.ledger_path.write_text("invalid ledger")
    app = create_app(settings)
    assert isinstance(app.state.budget, NoCostBudget)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert (
            client.post("/meta/runs", json={"brief": "MOCK brief"}).status_code == 501
        )


def test_live_mode_uses_ledger_guard(settings):
    settings.provider_mode = "live"
    app = create_app(settings)
    assert isinstance(app.state.budget, LedgerBudgetGuard)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200


def test_corrupt_ledger_line_is_skipped_and_counted_valid_lines(
    ledger_settings, monkeypatch
):
    from birds_eye.providers.logging import logger

    ledger_settings.ledger_path.write_text(
        '{"provider":"baseten","cost_usd":"1.25"}\n'
        '\n{"private":"partial secret"\n'
        '{"provider":"modal","cost_usd":"2.5"}\n'
        '{"provider":"baseten","cost_usd":"bad"}\n'
    )
    warnings = []
    monkeypatch.setattr(logger, "warning", warnings.append)
    guard = LedgerBudgetGuard(ledger_settings)
    assert guard.totals[ProviderId.BASETEN] == Decimal("1.25")
    assert guard.totals[ProviderId.MODAL] == Decimal("2.5")
    assert [json.loads(warning) for warning in warnings] == [
        {"event": "ledger_corrupt_line", "line_no": 3},
        {"event": "ledger_corrupt_line", "line_no": 5},
    ]


@pytest.fixture
def ledger_settings(tmp_path):
    return Settings(
        ledger_path=tmp_path / "ledger.jsonl",
        provider_mode="live",
        provider_max_retries=0,
        baseten_api_key=SecretStr("FAKE_SECRET"),
        model_api_key=SecretStr("FAKE_META"),
        price_meta_model_api_input_per_mtok_usd=1,
        price_meta_model_api_output_per_mtok_usd=2,
    )


@pytest.mark.asyncio
async def test_reserve_and_settle_to_actual_cost(ledger_settings, muse_request):
    guard = LedgerBudgetGuard(ledger_settings)
    reservation = await guard.reserve(ProviderId.BASETEN, Decimal(1))
    cost = await guard.settle_attempt(
        reservation,
        muse_request,
        "model",
        {"prompt_tokens": 100, "completion_tokens": 200},
        "success",
        None,
    )
    assert cost == Decimal("0.000975")
    assert guard.summary()["baseten"]["spent_usd"] == float(cost)


@pytest.mark.asyncio
async def test_cap_reached_skips_provider_and_falls_back(ledger_settings, muse_request):
    ledger_settings.baseten_budget_cap_usd = Decimal(0)
    guard = LedgerBudgetGuard(ledger_settings)
    result = await ModelRouter(
        ledger_settings, FakeTransport([ProviderReply(output="ok")]), guard
    ).call(muse_request)
    assert result.metadata[0]["error_code"] == "BUDGET_EXHAUSTED"
    assert result.metadata[-1]["provider"] == "meta_model_api"


def test_all_capped_returns_402_structured_body(ledger_settings):
    ledger_settings.baseten_budget_cap_usd = Decimal(0)
    ledger_settings.meta_model_api_budget_cap_usd = Decimal(0)
    app = create_app(ledger_settings)
    with TestClient(app) as client:
        response = client.post("/meta/runs", json={"brief": "MOCK brief"})
    from birds_eye.providers.logging import logger

    for handler in logger.handlers[:]:
        if getattr(handler, "birds_eye_stdout", False):
            logger.removeHandler(handler)
    assert response.status_code == 402
    assert response.json()["code"] == "PROVIDER_BUDGET_EXHAUSTED"
    assert response.json()["attempts"]


@pytest.mark.asyncio
async def test_ledger_totals_survive_restart(ledger_settings, muse_request):
    guard = LedgerBudgetGuard(ledger_settings)
    r = await guard.reserve(ProviderId.BASETEN, Decimal(1))
    await guard.settle_attempt(r, muse_request, "model", None, "success", None)
    assert (
        LedgerBudgetGuard(Settings(ledger_path=ledger_settings.ledger_path)).totals[
            ProviderId.BASETEN
        ]
        == 1
    )


@pytest.mark.asyncio
async def test_timeout_keeps_worst_case_failure_releases(ledger_settings, muse_request):
    guard = LedgerBudgetGuard(ledger_settings)
    for error in ("TIMEOUT", "CONNECTION_ERROR"):
        r = await guard.reserve(ProviderId.BASETEN, Decimal(1))
        await guard.settle_attempt(r, muse_request, "model", None, "failed", error)
    assert guard.totals[ProviderId.BASETEN] == 1
    assert not guard.open


@pytest.mark.asyncio
async def test_price_not_configured_is_recorded_skip(ledger_settings, muse_request):
    ledger_settings.baseten_budget_cap_usd = Decimal(0)
    ledger_settings.meta_muse_model = "unknown-model"
    ledger_settings.price_meta_model_api_input_per_mtok_usd = None
    from birds_eye.providers.contracts import RoutingError

    with pytest.raises(RoutingError) as exc:
        await ModelRouter(
            ledger_settings, FakeTransport(), LedgerBudgetGuard(ledger_settings)
        ).call(muse_request)
    assert exc.value.attempts[-1]["error_code"] == "PRICE_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_cost_usd_in_attempt_metadata_and_stdout_line_without_keys(
    ledger_settings, muse_request, caplog
):
    from birds_eye.providers.logging import logger

    with caplog.at_level("INFO", logger=logger.name):
        result = await ModelRouter(
            ledger_settings,
            FakeTransport(
                [
                    ProviderReply(
                        output="ok",
                        usage={"prompt_tokens": 10, "completion_tokens": 20},
                    )
                ]
            ),
            LedgerBudgetGuard(ledger_settings),
        ).call(muse_request)
    record = json.loads(caplog.records[-1].message)
    assert record["cost_usd"] == result.metadata[-1]["cost_usd"]
    assert record["ledger_total_usd"] == record["cost_usd"]
    assert "FAKE_SECRET" not in caplog.text
