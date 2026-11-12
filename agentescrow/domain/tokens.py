"""Minimal HMAC-SHA256 signed tokens shared by mandates, settlement tickets and capabilities.

Format: ``base64url(json payload) + "." + base64url(HMAC)``. Every payload carries a ``typ``
(what the token is for) and an ``exp`` (unix expiry), both checked on decode, so a token of
one kind can never be replayed as another.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class TokenError(ValueError):
    """The token is malformed, forged, expired or of the wrong type."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, body: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())


def encode_token(secret: str, payload: dict[str, Any]) -> str:
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(secret, body)}"


def decode_token(secret: str, token: str, expected_type: str, now: float | None = None) -> dict[str, Any]:
    try:
        body, signature = token.split(".")
    except ValueError as exc:
        raise TokenError("Malformed token") from exc
    if not hmac.compare_digest(signature, _sign(secret, body)):
        raise TokenError("Token signature is invalid")
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TokenError("Token payload is unreadable") from exc
    if payload.get("typ") != expected_type:
        raise TokenError(f"Expected a {expected_type} token")
    if payload.get("exp", 0) < (now if now is not None else time.time()):
        raise TokenError("Token has expired")
    return payload
