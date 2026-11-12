"""Access control without accounts: capabilities, browser sessions and the operator.

* A **capability** is a signed token bound to one job and one role (buyer or worker). The worker token
  also carries the job's *worker epoch*: when a worker is released (rejected or withdrawn) the epoch moves
  on, so the old worker's token stops working at once.
* A **session** is a signed bundle of capabilities kept in an ``HttpOnly`` cookie, so page scripts
  (and therefore XSS) can never read it. API clients that are not browsers use the bearer tokens instead.
* The **operator** is ``ADMIN_TOKEN`` (bearer) or an ``HttpOnly`` admin-session cookie obtained by logging in.
"""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass, field

from agentescrow.domain.tokens import TokenError, decode_token, encode_token

PUBLIC = "public"
SESSION_MAX_GRANTS = 25  # keeps the cookie small; the oldest grants fall off first
_ROLE_RANK = {"buyer": 0, "worker": 1}


@dataclass(frozen=True)
class Grant:
    job_id: str
    role: str  # "buyer" | "worker"
    epoch: int | None = None  # worker grants only


@dataclass(frozen=True)
class Principal:
    """Who is calling. ``via_cookie`` marks cookie-derived access (subject to the CSRF origin check)."""

    admin: bool = False
    grants: tuple[Grant, ...] = field(default_factory=tuple)
    via_cookie: bool = False

    @property
    def role(self) -> str:
        if self.admin:
            return "admin"
        return self.grants[0].role if self.grants else PUBLIC

    @property
    def job_id(self) -> str | None:
        return None if self.admin or not self.grants else self.grants[0].job_id

    def grant_for(self, job_id: str, *roles: str) -> Grant | None:
        for role in roles:
            for grant in self.grants:
                if grant.job_id == job_id and grant.role == role:
                    return grant
        return None


def issue_capability(secret: str, *, job_id: str, role: str, ttl_seconds: int, epoch: int | None = None, now: float | None = None) -> str:
    if role not in _ROLE_RANK:
        raise TokenError(f"Cannot issue a capability for role {role!r}")
    issued_at = int(now if now is not None else time.time())
    payload = {"typ": "capability", "role": role, "job_id": job_id, "iat": issued_at, "exp": issued_at + ttl_seconds}
    if epoch is not None:
        payload["epoch"] = epoch
    return encode_token(secret, payload)


def issue_session(secret: str, grants: list[Grant], *, ttl_seconds: int, now: float | None = None) -> str:
    issued_at = int(now if now is not None else time.time())
    caps = [[g.job_id, g.role, g.epoch] for g in grants[-SESSION_MAX_GRANTS:]]
    return encode_token(secret, {"typ": "session", "caps": caps, "iat": issued_at, "exp": issued_at + ttl_seconds})


def read_session(secret: str, token: str | None, now: float | None = None) -> list[Grant]:
    """Grants held by a session cookie. A missing, forged or expired cookie is simply 'no grants'."""
    if not token:
        return []
    try:
        payload = decode_token(secret, token, "session", now)
        return [Grant(str(job), str(role), epoch) for job, role, epoch in payload["caps"] if role in _ROLE_RANK]
    except (TokenError, KeyError, TypeError, ValueError):
        return []


def merge_grant(existing: list[Grant], new: Grant) -> list[Grant]:
    """Add ``new``, replacing any earlier grant for the same job and role."""
    kept = [g for g in existing if not (g.job_id == new.job_id and g.role == new.role)]
    return [*kept, new]


def issue_admin_session(secret: str, *, ttl_seconds: int, now: float | None = None) -> str:
    issued_at = int(now if now is not None else time.time())
    return encode_token(secret, {"typ": "admin_session", "iat": issued_at, "exp": issued_at + ttl_seconds})


def has_admin_session(secret: str, token: str | None, now: float | None = None) -> bool:
    if not token:
        return False
    try:
        decode_token(secret, token, "admin_session", now)
        return True
    except TokenError:
        return False


def resolve_principal(
    secret: str,
    admin_token: str,
    bearer: str | None,
    *,
    session_cookie: str | None = None,
    admin_cookie: str | None = None,
    now: float | None = None,
) -> Principal:
    """Turn credentials into a Principal. A bad *bearer* raises TokenError; bad cookies are ignored."""
    if bearer:
        if admin_token and hmac.compare_digest(bearer, admin_token):
            return Principal(admin=True)
        payload = decode_token(secret, bearer, "capability", now)
        return Principal(grants=(Grant(payload["job_id"], payload["role"], payload.get("epoch")),))
    admin = has_admin_session(secret, admin_cookie, now) and bool(admin_token)
    grants = tuple(read_session(secret, session_cookie, now))
    return Principal(admin=admin, grants=grants, via_cookie=bool(admin or grants))
