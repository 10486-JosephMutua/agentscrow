"""Signed tokens that bound what the agents may do with money.

Two kinds of token, both HMAC-SHA256 signed with ``MANDATE_SECRET``:

* **Mandate** (``typ=mandate``), issued when a job is posted. It says: *"for job X, the
  buyer authorizes escrow of at most N USD until time T"*. The PayPal MCP server refuses
  to create or authorize an order that exceeds or contradicts it, so even a confused or
  manipulated buyer agent cannot lock more money than the human delegated. This is the
  idea behind the intent mandates of Google's AP2 protocol (a demo of the idea, not an
  implementation of the AP2 specification).

* **Settlement ticket** (``typ=settlement``), issued by the orchestrator *after* the
  deterministic settlement policy has decided. Capture, void, reauthorize and payout tools require a
  ticket that names the exact job, action and amount, and expires in minutes. Agents are
  never given tickets, so they cannot move money even if they could reach those tools.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from agentescrow.domain.tokens import TokenError, decode_token, encode_token
from agentescrow.money import money_str, to_decimal

SETTLEMENT_ACTIONS = frozenset({"capture", "void", "payout", "reauthorize"})


class MandateError(TokenError):
    """The token is malformed, forged, expired or does not cover the requested action."""


def _encode(secret: str, payload: dict[str, Any]) -> str:
    return encode_token(secret, payload)


def _decode(secret: str, token: str, expected_type: str, now: float | None) -> dict[str, Any]:
    try:
        return decode_token(secret, token, expected_type, now)
    except TokenError as exc:
        raise MandateError(str(exc)) from exc


# ---------------------------------------------------------------------- mandates --
def issue_mandate(
    secret: str,
    *,
    job_id: str,
    max_amount: Decimal,
    currency: str = "USD",
    ttl_seconds: int = 3600,
    now: float | None = None,
) -> str:
    issued_at = int(now if now is not None else time.time())
    return _encode(
        secret,
        {
            "typ": "mandate",
            "job_id": job_id,
            "max_amount": money_str(max_amount),
            "currency": currency,
            "iat": issued_at,
            "exp": issued_at + ttl_seconds,
        },
    )


def verify_mandate(
    secret: str,
    token: str,
    *,
    job_id: str,
    amount: Decimal | str,
    currency: str = "USD",
    now: float | None = None,
) -> dict[str, Any]:
    """Return the mandate payload if it authorizes ``amount`` for ``job_id``; else raise."""
    payload = _decode(secret, token, "mandate", now)
    if payload.get("job_id") != job_id:
        raise MandateError("Mandate was issued for a different job")
    if payload.get("currency") != currency:
        raise MandateError("Mandate currency does not match")
    if to_decimal(amount) > to_decimal(payload["max_amount"]):
        raise MandateError(f"Requested {money_str(amount)} exceeds the mandate cap of {payload['max_amount']}")
    return payload


# ------------------------------------------------------------ settlement tickets --
def issue_settlement_ticket(
    secret: str,
    *,
    job_id: str,
    action: str,
    amount: Decimal | str = Decimal("0.00"),
    ttl_seconds: int = 300,
    now: float | None = None,
) -> str:
    if action not in SETTLEMENT_ACTIONS:
        raise MandateError(f"Unknown settlement action {action!r}")
    issued_at = int(now if now is not None else time.time())
    return _encode(
        secret,
        {
            "typ": "settlement",
            "job_id": job_id,
            "action": action,
            "amount": money_str(amount),
            "iat": issued_at,
            "exp": issued_at + ttl_seconds,
        },
    )


def verify_settlement_ticket(
    secret: str,
    token: str,
    *,
    job_id: str,
    action: str,
    amount: Decimal | str = Decimal("0.00"),
    now: float | None = None,
) -> dict[str, Any]:
    """Return the ticket payload only if it names exactly this job, action and amount."""
    payload = _decode(secret, token, "settlement", now)
    if payload.get("job_id") != job_id:
        raise MandateError("Settlement ticket was issued for a different job")
    if payload.get("action") != action:
        raise MandateError(f"Settlement ticket does not permit '{action}'")
    if to_decimal(payload["amount"]) != to_decimal(amount):
        raise MandateError("Settlement ticket amount does not match the requested amount")
    return payload
