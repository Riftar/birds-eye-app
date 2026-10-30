import pytest

from birds_eye.core.contracts import SafeError
from birds_eye.core.state import Actor, PostState, PostStatus, transition


@pytest.mark.parametrize(
    ("status", "target"),
    [
        (PostStatus.DRAFT, PostStatus.APPROVED),
        (PostStatus.REVIEW_PASSED, PostStatus.SCHEDULED),
    ],
)
def test_human_gates(status, target):
    post = PostState(status=status, claim_token="valid", claim_active=True)
    with pytest.raises(SafeError) as error:
        transition(post, target, actor=Actor.AGENT, claim_token="valid")
    assert error.value.code == "HUMAN_ONLY"
    assert (
        transition(post, target, actor=Actor.HUMAN, claim_token=None).status == target
    )


def test_invalid_transition():
    with pytest.raises(SafeError) as error:
        transition(
            PostState(status=PostStatus.IDEA),
            PostStatus.PUBLISHED,
            actor=Actor.HUMAN,
            claim_token=None,
        )
    assert error.value.code == "INVALID_TRANSITION"


@pytest.mark.parametrize(
    ("active", "stored", "provided"),
    [
        (True, "valid", None),
        (False, "valid", "valid"),
        (True, "valid", "wrong"),
        (True, None, "valid"),
    ],
    ids=["missing", "stale", "mismatched", "no-claim"],
)
def test_claim_loss(active, stored, provided):
    with pytest.raises(SafeError) as error:
        transition(
            PostState(status=PostStatus.IDEA, claim_token=stored, claim_active=active),
            PostStatus.DRAFT,
            actor=Actor.AGENT,
            claim_token=provided,
        )
    assert error.value.code == "CLAIM_LOST"


def test_valid_agent_claim():
    post = PostState(status=PostStatus.IDEA, claim_token="valid", claim_active=True)
    assert (
        transition(
            post, PostStatus.DRAFT, actor=Actor.AGENT, claim_token="valid"
        ).status
        == PostStatus.DRAFT
    )
