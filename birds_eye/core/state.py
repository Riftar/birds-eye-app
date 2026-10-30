import itertools
from enum import StrEnum

from pydantic import BaseModel

from birds_eye.core.contracts import SafeError


class PostStatus(StrEnum):
    IDEA = "idea"
    DRAFT = "draft"
    APPROVED = "approved"
    IN_REVIEW = "in_review"
    REVIEW_PASSED = "review_passed"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"


class Actor(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class PostState(BaseModel):
    status: PostStatus
    claim_token: str | None = None
    claim_active: bool = False


ORDER = list(PostStatus)
GATES = {
    (PostStatus.DRAFT, PostStatus.APPROVED),
    (PostStatus.REVIEW_PASSED, PostStatus.SCHEDULED),
}


def transition(
    post: PostState, target: PostStatus, *, actor: Actor, claim_token: str | None
) -> PostState:
    if (post.status, target) not in set(itertools.pairwise(ORDER)):
        raise SafeError("INVALID_TRANSITION", "The requested transition is invalid.")
    if (post.status, target) in GATES and actor != Actor.HUMAN:
        raise SafeError("HUMAN_ONLY", "This transition requires a human.")
    if actor == Actor.AGENT and (
        not post.claim_active or not post.claim_token or claim_token != post.claim_token
    ):
        raise SafeError("CLAIM_LOST", "The agent claim is no longer active.")
    return post.model_copy(update={"status": target})
