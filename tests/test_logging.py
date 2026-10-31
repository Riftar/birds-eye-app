import json
import logging

import pytest
from conftest import FakeTransport

from birds_eye.providers.contracts import ProviderError, ProviderReply, RoutingError
from birds_eye.providers.logging import FIELDS
from birds_eye.providers.router import ModelRouter


@pytest.mark.asyncio
async def test_logs_match_returned_metadata_and_attribute_every_provider(
    configured_settings, budget, muse_request, caplog
):
    transport = FakeTransport(
        [
            ProviderError("TIMEOUT"),
            ProviderError("PROVIDER_5XX"),
            ProviderReply(output="ok", usage={"input_tokens": 3, "output_tokens": 4}),
        ]
    )
    with caplog.at_level(logging.INFO, logger="birds_eye.model_calls"):
        response = await ModelRouter(configured_settings, transport, budget).call(
            muse_request
        )
    records = [json.loads(record.message) for record in caplog.records]
    assert records == response.metadata
    assert all(set(record) == set(FIELDS) for record in records)
    assert [(r["provider"], r["concrete_model"]) for r in records] == [
        ("baseten", "meta-models/muse-spark-open-1026"),
        ("modal", "mock-modal-muse-deployment"),
        ("meta_model_api", "muse-spark-1.3-contributor"),
    ]
    assert all(r["logical_model"] == "muse-spark" for r in records)


@pytest.mark.asyncio
async def test_fake_secrets_and_raw_errors_never_appear(
    configured_settings, budget, muse_request, caplog
):
    secrets = [
        "FAKE_BASETEN_SECRET",
        "FAKE_MODAL_ID",
        "FAKE_MODAL_SECRET",
        "FAKE_META_SECRET",
    ]
    transport = FakeTransport(
        [
            ProviderError("TIMEOUT", " ".join(secrets)),
            ProviderReply(
                output="ok", usage={"input_tokens": 2, "raw": " ".join(secrets)}
            ),
        ]
    )
    with caplog.at_level(logging.INFO, logger="birds_eye.model_calls"):
        response = await ModelRouter(configured_settings, transport, budget).call(
            muse_request
        )
    for secret in secrets:
        assert secret not in caplog.text
        assert secret not in json.dumps(response.metadata)


@pytest.mark.asyncio
async def test_untrusted_error_code_is_sanitized(
    configured_settings, budget, muse_request, caplog
):
    transport = FakeTransport([ProviderError("FAKE_BASETEN_SECRET")])
    with (
        caplog.at_level(logging.INFO, logger="birds_eye.model_calls"),
        pytest.raises(RoutingError) as error,
    ):
        await ModelRouter(configured_settings, transport, budget).call(muse_request)
    assert error.value.code == "PROVIDER_ERROR"
    assert "FAKE_BASETEN_SECRET" not in caplog.text
    assert "FAKE_BASETEN_SECRET" not in json.dumps(error.value.attempts)
