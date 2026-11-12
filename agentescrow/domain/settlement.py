"""Settlement policy: turns arbiter evidence into a money decision.

This module is deliberately a *pure function* with no I/O and no LLM. The language
model proposes a quality score; only this code decides how much money moves.

Policy
------
Hard gates (any failure voids the hold, the buyer pays nothing):
  1. Integrity: manipulation attempt or forbidden API use.
  2. Schema: deliverable must match the contract's JSON Schema.
  3. Sandbox: hidden tests must have run, without timing out.

Score: V = 0.30 * schema + 0.40 * sandbox + 0.30 * semantic
  * V >= 0.85 and every hidden test passed      -> FULL    (capture the whole bounty)
  * V >= 0.50 and >= 50% of hidden tests passed -> PARTIAL (capture floor(bounty * V))
  * otherwise                                   -> VOID

The platform fee is a percentage of the captured amount; the worker receives the rest.
"""

from __future__ import annotations

from decimal import Decimal

from agentescrow.domain.models import Outcome, SettlementDecision, Verdict
from agentescrow.money import floor_cents, round_cents

SCHEMA_WEIGHT = 0.30
SANDBOX_WEIGHT = 0.40
SEMANTIC_WEIGHT = 0.30

FULL_PASS_THRESHOLD = 0.85
PARTIAL_THRESHOLD = 0.50
MIN_PASS_RATIO_FOR_PARTIAL = 0.50

_ZERO = Decimal("0.00")


def compute_v_score(schema_score: float, sandbox_score: float, semantic_score: float) -> float:
    """Weighted verification score in [0, 1], rounded to 4 places."""
    value = SCHEMA_WEIGHT * schema_score + SANDBOX_WEIGHT * sandbox_score + SEMANTIC_WEIGHT * semantic_score
    return round(value, 4)


def _void(reason: str, v_score: float) -> SettlementDecision:
    return SettlementDecision(outcome=Outcome.VOID, reason=reason, v_score=v_score)


def _paid(outcome: Outcome, reason: str, v_score: float, capture: Decimal, fee_rate: Decimal) -> SettlementDecision:
    fee = round_cents(capture * fee_rate)
    fee = min(fee, capture)
    return SettlementDecision(
        outcome=outcome,
        reason=reason,
        v_score=v_score,
        capture_amount=capture,
        platform_fee=fee,
        worker_payout=capture - fee,
    )


def decide_settlement(verdict: Verdict, *, bounty: Decimal, fee_rate: Decimal) -> SettlementDecision:
    """Apply the policy above to an arbiter :class:`Verdict`."""
    v_score = verdict.v_score

    if not verdict.integrity.ok:
        return _void("Integrity violation: " + "; ".join(verdict.integrity.findings), v_score)
    if not verdict.schema_check.valid:
        return _void("Deliverable does not match the contract schema", v_score)

    sandbox = verdict.sandbox
    if sandbox is None or sandbox.total == 0 or sandbox.timed_out:
        return _void("Hidden tests did not produce a usable result", v_score)
    if verdict.semantic is None:
        raise ValueError("A verdict that passed every gate must include a semantic result")

    pass_ratio = sandbox.passed / sandbox.total
    noun = "preference checks" if sandbox.backend == "html-checks" else "hidden tests"

    if v_score >= FULL_PASS_THRESHOLD and sandbox.failed == 0 and sandbox.passed == sandbox.total:
        return _paid(Outcome.FULL, f"V={v_score:.2f}: all {noun} passed", v_score, round_cents(bounty), fee_rate)

    if v_score >= PARTIAL_THRESHOLD and pass_ratio >= MIN_PASS_RATIO_FOR_PARTIAL:
        capture = min(floor_cents(bounty * Decimal(str(v_score))), round_cents(bounty))
        reason = f"V={v_score:.2f}: {sandbox.passed}/{sandbox.total} {noun} passed; pro-rated payment"
        return _paid(Outcome.PARTIAL, reason, v_score, capture, fee_rate)

    return _void(f"V={v_score:.2f} is below the payment threshold", v_score)
