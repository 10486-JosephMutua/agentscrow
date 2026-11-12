"""The settlement policy is a pure function, so it is tested as a table of cases."""

from decimal import Decimal

import pytest

from agentescrow.domain.models import (
    IntegrityResult, Outcome, SandboxResult, SchemaResult, SemanticResult, Verdict,
)  # fmt: skip
from agentescrow.domain.settlement import compute_v_score, decide_settlement

BOUNTY, FEE = Decimal("75.00"), Decimal("0.0667")


def verdict(*, schema=True, integrity=True, passed=8, total=8, semantic=0.9, timed_out=False, sandbox=True):
    schema_score = 1.0 if schema else 0.0
    sandbox_result = (
        SandboxResult(backend="x", passed=passed, failed=total - passed, total=total, timed_out=timed_out,
                      score=(passed / total if total else 0.0))
        if sandbox else None
    )  # fmt: skip
    sem = SemanticResult(clarity=semantic, relevance=semantic, thoroughness=semantic, score=semantic, rationale="r", judge="t")
    return Verdict(
        schema_check=SchemaResult(valid=schema, score=schema_score),
        integrity=IntegrityResult(ok=integrity, findings=[] if integrity else ["bad"]),
        sandbox=sandbox_result,
        semantic=sem if sandbox else None,
        v_score=compute_v_score(schema_score, sandbox_result.score if sandbox_result else 0.0, semantic if sandbox else 0.0),
    )  # fmt: skip


def test_weights():
    assert compute_v_score(1, 1, 1) == 1.0
    assert compute_v_score(1, 0, 0) == 0.3
    assert compute_v_score(0, 1, 0) == 0.4
    assert compute_v_score(0, 0, 1) == 0.3


def test_full_pass_pays_everything_minus_fee():
    d = decide_settlement(verdict(), bounty=BOUNTY, fee_rate=FEE)
    assert d.outcome == Outcome.FULL
    assert d.capture_amount == Decimal("75.00")
    assert d.platform_fee == Decimal("5.00") and d.worker_payout == Decimal("70.00")  # the documented $75 -> $70 + $5


def test_partial_is_pro_rated_and_sums_exactly():
    d = decide_settlement(verdict(passed=6, total=8, semantic=0.8), bounty=BOUNTY, fee_rate=FEE)
    assert d.outcome == Outcome.PARTIAL
    assert Decimal("0") < d.capture_amount < BOUNTY
    assert d.capture_amount == d.platform_fee + d.worker_payout


def test_high_score_but_one_failing_test_is_not_a_full_pass():
    d = decide_settlement(verdict(passed=19, total=20, semantic=1.0), bounty=BOUNTY, fee_rate=FEE)
    assert d.v_score >= 0.85 and d.outcome == Outcome.PARTIAL


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(schema=False, sandbox=False),  # schema gate
        dict(integrity=False),  # integrity gate
        dict(passed=0, total=8),  # nothing passes
        dict(passed=3, total=8, semantic=1.0),  # < 50% of tests, even with a glowing judge
        dict(timed_out=True),  # infinite loop
        dict(passed=0, total=0),  # no tests ran
    ],
)
def test_gates_void_the_hold(kwargs):
    d = decide_settlement(verdict(**kwargs), bounty=BOUNTY, fee_rate=FEE)
    assert d.outcome == Outcome.VOID
    assert d.capture_amount == d.worker_payout == d.platform_fee == Decimal("0.00")


def test_sandbox_failure_cannot_be_rescued_by_schema_and_semantic_scores():
    # 0.30 + 0.30 = 0.60 would be "marginal" under a naive weighted average.
    d = decide_settlement(verdict(passed=0, total=8, semantic=1.0), bounty=BOUNTY, fee_rate=FEE)
    assert d.outcome == Outcome.VOID


def test_partial_never_exceeds_the_bounty():
    d = decide_settlement(verdict(passed=7, total=8, semantic=1.0), bounty=Decimal("0.01"), fee_rate=FEE)
    assert d.capture_amount <= Decimal("0.01")
