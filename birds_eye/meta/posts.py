from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from birds_eye.core.contracts import SafeError
from birds_eye.core.state import Actor, PostState, PostStatus, transition

router = APIRouter(prefix="/meta/posts")


class TransitionRequest(BaseModel):
    target: PostStatus
    actor: Actor


class RejectRequest(BaseModel):
    actor: Actor
    reason: str = Field(min_length=1, max_length=4000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Reason is required")
        return value


def create_post(app, review_passed):
    post = {
        "id": str(uuid4()),
        "status": PostStatus.DRAFT,
        "audit": [],
        "review_passed": review_passed,
    }
    app.state.posts[post["id"]] = post
    record(post, "agent", PostStatus.IDEA, PostStatus.DRAFT)
    return post


def record(post, actor, source, target, **extra):
    post["audit"].append(
        {
            "actor": actor,
            "from": source,
            "to": target,
            "at": datetime.now(UTC).isoformat(),
            **extra,
        }
    )


def get_post(request, post_id):
    post = request.app.state.posts.get(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


def move(post, target, actor):
    source = post["status"]
    token = "completed-review" if actor == Actor.AGENT else None
    state = PostState(status=source, claim_active=bool(token), claim_token=token)
    post["status"] = transition(state, target, actor=actor, claim_token=token).status
    record(post, actor, source, target)


@router.post("/{post_id}/transition")
async def post_transition(post_id: str, body: TransitionRequest, request: Request):
    post = get_post(request, post_id)
    try:
        # This endpoint only accepts human decisions; agent work is advanced internally.
        if body.actor != Actor.HUMAN:
            raise SafeError("HUMAN_ONLY", "This transition requires a human.")
        if body.target not in (PostStatus.APPROVED, PostStatus.SCHEDULED):
            raise SafeError(
                "INVALID_TRANSITION", "The requested transition is invalid."
            )
        move(post, body.target, body.actor)
        if body.target == PostStatus.APPROVED:
            move(post, PostStatus.IN_REVIEW, Actor.AGENT)
            if post["review_passed"]:
                move(post, PostStatus.REVIEW_PASSED, Actor.AGENT)
    except SafeError as exc:
        return JSONResponse(
            status_code=409,
            content={"code": exc.code, "message": exc.message, "post": post},
        )
    return {"post": post}


@router.post("/{post_id}/reject")
async def reject_post(post_id: str, body: RejectRequest, request: Request):
    post = get_post(request, post_id)
    if body.actor != Actor.HUMAN:
        return JSONResponse(
            status_code=409, content={"code": "HUMAN_ONLY", "post": post}
        )
    if post["status"] not in (PostStatus.DRAFT, PostStatus.REVIEW_PASSED):
        return JSONResponse(
            status_code=409, content={"code": "INVALID_TRANSITION", "post": post}
        )
    record(
        post,
        Actor.HUMAN,
        post["status"],
        post["status"],
        reason=body.reason,
        event="rejected",
    )
    return {"post": post}
