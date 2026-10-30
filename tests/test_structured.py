import json
from pathlib import Path

import httpx
import pytest
from conftest import FakeBudgetGuard, FakeTransport
from pydantic import SecretStr

from birds_eye.core.inputs import load_inputs, make_context
from birds_eye.meta.agents import parse_structured
from birds_eye.meta.pipeline import run_meta
from birds_eye.meta.prompts import load_prompts
from birds_eye.meta.schemas import ContentPlanOut, DraftOut, VerdictOut
from birds_eye.providers.contracts import (
    ModelBinding,
    ModelRequest,
    ProviderId,
    ProviderReply,
)
from birds_eye.providers.router import ModelRouter
from birds_eye.providers.transport import LiveTransport

PLAN_JSON = json.dumps(
    {
        "hook": "MOCK hook line",
        "format": "short_video",
        "key_points": ["MOCK point one", "MOCK point two"],
        "cta": "MOCK call to action",
        "segment_subject": "iced latte glass",
    }
)
DRAFT_JSON = json.dumps(
    {
        "format": "short_video",
        "beats": [{"label": "Hook", "text": "MOCK beat text"}],
        "caption": "MOCK caption",
    }
)
VERDICT_JSON = json.dumps(
    {
        "decision": "approve",
        "findings": [{"rule_id": "MOCK-R1", "message": "MOCK finding"}],
    }
)


def _schema_request(**kwargs):
    return ModelRequest(
        run_id="run-1",
        stage="planner",
        call_id="call-1",
        logical_model="muse-spark",
        operation="text",
        prompt="MOCK prompt",
        instructions="MOCK instructions",
        max_tokens=4000,
        json_schema_name="content_plan",
        json_schema=ContentPlanOut.model_json_schema(),
        **kwargs,
    )


def _ok_response():
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 1},
        },
    )


@pytest.mark.asyncio
async def test_meta_request_has_response_format_json_schema(settings):
    settings.model_api_key = SecretStr("fake")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return _ok_response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await LiveTransport(settings, client).invoke(
            ModelBinding(
                logical_model="muse-spark",
                provider=ProviderId.META,
                concrete_model="muse-spark-1.3",
                operation="text",
            ),
            _schema_request(),
        )
    response_format = seen["body"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "content_plan"
    assert (
        response_format["json_schema"]["schema"] == ContentPlanOut.model_json_schema()
    )
    assert response_format["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_baseten_request_has_no_response_format_but_schema_in_developer_message(
    settings,
):
    settings.baseten_api_key = SecretStr("fake")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return _ok_response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await LiveTransport(settings, client).invoke(
            ModelBinding(
                logical_model="muse-spark",
                provider=ProviderId.BASETEN,
                concrete_model="meta-models/muse-spark-open-1026",
                operation="text",
            ),
            _schema_request(),
        )
    assert "response_format" not in seen["body"]
    developer = seen["body"]["messages"][0]
    assert developer["role"] == "developer"
    assert "Return only JSON matching this schema" in developer["content"]
    assert "MOCK instructions" in developer["content"]


@pytest.mark.asyncio
async def test_valid_json_parses_into_models(settings):
    structured, parse_error = parse_structured(ContentPlanOut, PLAN_JSON)
    assert parse_error is False
    assert structured["hook"] == "MOCK hook line"
    assert structured["segment_subject"] == "iced latte glass"
    structured, parse_error = parse_structured(DraftOut, DRAFT_JSON)
    assert parse_error is False
    assert structured["beats"] == [{"label": "Hook", "text": "MOCK beat text"}]
    structured, parse_error = parse_structured(VerdictOut, VERDICT_JSON)
    assert parse_error is False
    assert structured["decision"] == "approve"

    settings.baseten_api_key = SecretStr("fake")
    fake = FakeTransport(
        [
            ProviderReply(output=PLAN_JSON),
            ProviderReply(output=DRAFT_JSON),
            ProviderReply(output=VERDICT_JSON),
        ]
    )
    result = await run_meta(
        make_context(load_inputs(settings.default_scenario_dir)),
        ModelRouter(settings, fake, FakeBudgetGuard()),
    )
    assert [s["parse_error"] for s in result.stages] == [False, False, False]
    assert result.stages[0]["structured"]["hook"] == "MOCK hook line"
    assert result.stages[1]["structured"]["caption"] == "MOCK caption"
    assert result.stages[2]["structured"]["decision"] == "approve"
    assert result.stages[2]["decision"] == "approve"


@pytest.mark.asyncio
async def test_fenced_or_invalid_json_degrades_to_text_with_parse_error(settings):
    structured, parse_error = parse_structured(
        ContentPlanOut, f"```json\n{PLAN_JSON}\n```"
    )
    assert parse_error is False and structured["hook"] == "MOCK hook line"

    structured, parse_error = parse_structured(ContentPlanOut, "not json at all")
    assert structured is None and parse_error is True
    structured, parse_error = parse_structured(DraftOut, '{"format":"short_video"')
    assert structured is None and parse_error is True
    structured, parse_error = parse_structured(VerdictOut, "unparseable")
    assert structured is None and parse_error is True

    settings.baseten_api_key = SecretStr("fake")
    fake = FakeTransport(
        [
            ProviderReply(output="plain MOCK plan text"),
            ProviderReply(output="plain MOCK draft text"),
            ProviderReply(output="unparseable"),
        ]
    )
    result = await run_meta(
        make_context(load_inputs(settings.default_scenario_dir)),
        ModelRouter(settings, fake, FakeBudgetGuard()),
    )
    assert [s["structured"] for s in result.stages] == [None, None, None]
    assert [s["parse_error"] for s in result.stages] == [True, True, True]
    assert result.stages[0]["output"] == "plain MOCK plan text"
    assert result.stages[1]["output"] == "plain MOCK draft text"
    assert result.stages[2]["output"] == "unparseable"
    assert result.stages[2]["decision"] == "revise"


def test_prompt_files_loaded_with_version():
    prompts = load_prompts()
    assert set(prompts) == {"planner", "writer", "reviewer"}
    for name, prompt in prompts.items():
        assert isinstance(prompt["version"], int) and prompt["version"] >= 1
        assert len(prompt["text"]) > 50
        header = (
            (Path("birds_eye/meta/prompts") / f"{name}.md")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        assert header.strip().lower().startswith("version:")


@pytest.mark.asyncio
async def test_user_brief_still_in_all_prompts_and_no_mock_brand(settings):
    settings.baseten_api_key = SecretStr("fake")
    brief = "A Jakarta coffee shop serving iced kopi susu."
    fake = FakeTransport(
        [
            ProviderReply(output=PLAN_JSON),
            ProviderReply(output=DRAFT_JSON),
            ProviderReply(output=VERDICT_JSON),
        ]
    )
    context = make_context(load_inputs(settings.default_scenario_dir))
    context = context.model_copy(update={"user_brief": brief})
    result = await run_meta(context, ModelRouter(settings, fake, FakeBudgetGuard()))
    mock = json.loads(Path("mock-data/default/creator-brief.MOCK.json").read_text())
    assert len(fake.calls) == 3
    for _, request in fake.calls:
        assert brief in request.prompt
        assert mock["creator"] not in request.prompt
    assert all(s["prompt_version"] >= 1 for s in result.stages)
