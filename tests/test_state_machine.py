import pytest

from agentescrow.domain.models import JobState as S
from agentescrow.domain.state_machine import ALLOWED_TRANSITIONS, TERMINAL_STATES, InvalidTransition, assert_transition


def test_every_state_is_covered():
    assert set(ALLOWED_TRANSITIONS) == set(S)


def test_happy_path_is_legal():
    path = [S.POSTED, S.ACCEPTED, S.FUNDS_PENDING, S.ESCROW_LOCKED, S.SUBMITTED, S.ARBITRATING, S.SETTLING, S.SETTLED]
    for current, target in zip(path, path[1:], strict=False):
        assert_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.POSTED, S.SETTLED),  # cannot skip straight to paid
        (S.ESCROW_LOCKED, S.SETTLING),  # cannot settle without arbitration
        (S.SUBMITTED, S.SETTLED),
        (S.SETTLED, S.VOIDED),  # terminal states are final
        (S.VOIDED, S.SETTLED),
        (S.CANCELLED, S.POSTED),
    ],
)
def test_illegal_moves_are_rejected(current, target):
    with pytest.raises(InvalidTransition):
        assert_transition(current, target)


def test_review_loop_and_terminals():
    assert_transition(S.ARBITRATING, S.NEEDS_REVIEW)
    assert_transition(S.NEEDS_REVIEW, S.ARBITRATING)
    assert TERMINAL_STATES == {S.SETTLED, S.VOIDED, S.CANCELLED}
