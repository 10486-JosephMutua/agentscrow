"""Request authentication and authorization for the HTTP API.

Credentials, in order of precedence:
  1. ``Authorization: Bearer <token>``: a per-job buyer/worker capability, or the operator's ``ADMIN_TOKEN`` (scripts, agents).
  2. ``ae_session`` cookie: an HttpOnly bundle of capabilities (the browser UI). Page scripts cannot read it.
  3. ``ae_admin`` cookie: an HttpOnly operator session created by ``POST /api/admin/login``.
Callers with none of these are *public* and see redacted data.

Cookie-authenticated browsers are protected from cross-site request forgery by ``SameSite=Strict`` plus an ``Origin`` check
(:func:`check_origin`) on every state-changing request.
"""

from __future__ import annotations

from flask import request

from agentescrow.config import Settings
from agentescrow.domain.capability import Principal, resolve_principal
from agentescrow.domain.models import Job
from agentescrow.domain.tokens import TokenError

SESSION_COOKIE = "ae_session"
ADMIN_COOKIE = "ae_admin"
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuthError(Exception):
    """Authentication (401), authorization (403) or throttling (429) failure."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


def current_principal(settings: Settings) -> Principal:
    header = request.headers.get("Authorization", "")
    bearer = header[7:].strip() if header.lower().startswith("bearer ") else None
    try:
        return resolve_principal(
            settings.mandate_secret, settings.admin_token, bearer,
            session_cookie=request.cookies.get(SESSION_COOKIE), admin_cookie=request.cookies.get(ADMIN_COOKIE),
        )  # fmt: skip
    except TokenError as exc:
        raise AuthError(401, f"Invalid or expired token: {exc}") from exc


def check_origin(settings: Settings) -> None:
    """Refuse browser requests that were started by another site (CSRF defence).

    Requests carrying an ``Authorization`` header are exempt (a page on another origin cannot attach one without our
    CORS approval). Requests with neither ``Origin`` nor ``Sec-Fetch-Site`` come from non-browser clients and are allowed.
    """
    if request.method not in _UNSAFE_METHODS or request.headers.get("Authorization"):
        return
    origin = request.headers.get("Origin")
    if origin:
        if origin in settings.allowed_origins or origin == request.host_url.rstrip("/"):
            return
        raise AuthError(403, "Cross-origin request refused")
    site = request.headers.get("Sec-Fetch-Site")
    if site and site not in {"same-origin", "none"}:
        raise AuthError(403, "Cross-site request refused")


def require_role(settings: Settings, job_id: str, *roles: str, job: Job | None = None) -> tuple[Principal, str]:
    """Return ``(principal, acting_role)`` if the caller holds one of ``roles`` for this job (admins pass).

    A worker grant is honored only while its epoch matches the job's current ``worker_epoch``; a released worker is refused.
    """
    principal = current_principal(settings)
    if principal.admin:
        return principal, "admin"
    stale = False
    for role in roles:
        grant = principal.grant_for(job_id, role)
        if grant is None:
            continue
        if role == "worker" and job is not None and grant.epoch != job.worker_epoch:
            stale = True
            continue
        return principal, role
    if stale:
        raise AuthError(403, "Your worker seat on this job was released")
    if not principal.grants:
        raise AuthError(401, "This action needs access: open the job from the browser that created or accepted it, or send 'Authorization: Bearer <token>'")
    raise AuthError(403, "You do not have permission for this action on this job")


def require_admin(settings: Settings) -> Principal:
    principal = current_principal(settings)
    if not principal.admin:
        raise AuthError(403 if principal.grants else 401, "Operator access required")
    return principal


def viewer_roles(principal: Principal, job: Job) -> list[str]:
    """Every role the caller may act in on this job, most powerful first."""
    roles = []
    if principal.admin:
        roles.append("admin")
    if principal.grant_for(job.job_id, "buyer"):
        roles.append("buyer")
    worker = principal.grant_for(job.job_id, "worker")
    if worker and worker.epoch == job.worker_epoch:
        roles.append("worker")
    return roles


def view_role(principal: Principal, job: Job) -> str:
    """Which redacted view of this job the caller may see."""
    roles = viewer_roles(principal, job)
    return roles[0] if roles else "public"
