"""The job lifecycle as an explicit state machine.

Every status change in the system goes through :func:`assert_transition`, so an
illegal move (for example capturing money for a job that was never submitted) is
rejected in one place.
"""

from __future__ import annotations

from agentescrow.domain.models import JobState as S


class InvalidTransition(RuntimeError):
    """Raised when a job is asked to move to a state it cannot reach from where it is."""


ALLOWED_TRANSITIONS: dict[S, frozenset[S]] = {
    S.POSTED: frozenset({S.ACCEPTED, S.CANCELLED}),
    S.ACCEPTED: frozenset({S.FUNDS_PENDING, S.POSTED, S.CANCELLED}),
    S.FUNDS_PENDING: frozenset({S.ESCROW_LOCKED, S.CANCELLED}),
    S.ESCROW_LOCKED: frozenset({S.SUBMITTED, S.VOIDED}),
    S.SUBMITTED: frozenset({S.ARBITRATING}),
    S.ARBITRATING: frozenset({S.SETTLING, S.NEEDS_REVIEW}),
    S.NEEDS_REVIEW: frozenset({S.ARBITRATING}),
    S.SETTLING: frozenset({S.SETTLED, S.VOIDED}),
    S.SETTLED: frozenset(),
    S.VOIDED: frozenset(),
    S.CANCELLED: frozenset(),
}

TERMINAL_STATES = frozenset(state for state, targets in ALLOWED_TRANSITIONS.items() if not targets)


def can_transition(current: S, target: S) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def assert_transition(current: S, target: S) -> None:
    if not can_transition(current, target):
        allowed = ", ".join(sorted(s.value for s in ALLOWED_TRANSITIONS[current])) or "none (terminal)"
        raise InvalidTransition(f"Cannot move job from {current.value} to {target.value}. Allowed: {allowed}")
