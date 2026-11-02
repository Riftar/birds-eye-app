import httpx
import pytest

from birds_eye.app import create_app
from birds_eye.core.contracts import RunResult


@pytest.mark.asyncio
@pytest.mark.parametrize("passed", [True, False])
async def test_gates_follow_review_and_audit(settings, monkeypatch, passed):
    settings.provider_mode = "mock"

    async def fake_run(context, router):
        return RunResult(
            stages=[
                {"stage": "Reviewer", "decision": "approve" if passed else "revise"}
            ]
        )

    monkeypatch.setattr("birds_eye.meta.routes.run_meta", fake_run)
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        post = (await client.post("/meta/runs", json={"brief": "test"})).json()["post"]
        path = f"/meta/posts/{post['id']}"
        assert post["status"] == "draft"
        invalid = await client.post(
            path + "/transition", json={"target": "scheduled", "actor": "human"}
        )
        assert (
            invalid.status_code == 409
            and invalid.json()["code"] == "INVALID_TRANSITION"
        )
        denied = await client.post(
            path + "/transition", json={"target": "approved", "actor": "agent"}
        )
        assert denied.status_code == 409 and denied.json()["code"] == "HUMAN_ONLY"
        assert (
            await client.post(path + "/reject", json={"actor": "human", "reason": "  "})
        ).status_code == 422
        rejection = await client.post(
            path + "/reject", json={"actor": "human", "reason": "Needs work"}
        )
        assert rejection.json()["post"]["audit"][-1]["reason"] == "Needs work"
        approved = await client.post(
            path + "/transition", json={"target": "approved", "actor": "human"}
        )
        post = approved.json()["post"]
        assert post["status"] == ("review_passed" if passed else "in_review")
        assert [(a["actor"], a["from"], a["to"]) for a in post["audit"][:3]] == [
            ("agent", "idea", "draft"),
            ("human", "draft", "draft"),
            ("human", "draft", "approved"),
        ]
        scheduled = await client.post(
            path + "/transition", json={"target": "scheduled", "actor": "human"}
        )
        assert scheduled.status_code == (200 if passed else 409)
        if passed:
            post = scheduled.json()["post"]
            assert post["status"] == "scheduled"
            assert post["audit"][-1]["from"] == "review_passed"
            assert post["audit"][-1]["to"] == "scheduled"
            assert post["audit"][-1]["at"]
            assert (
                await client.post(
                    path + "/reject", json={"actor": "human", "reason": "late"}
                )
            ).status_code == 409
        assert (
            await client.post(
                "/meta/posts/missing/transition",
                json={"target": "approved", "actor": "human"},
            )
        ).status_code == 404
