"""Flask HTTP API for AgentEscrow.

Who can call what (see ``agentescrow/api/auth.py``): *public* callers send no credentials and see redacted data; *buyer* and
*worker* access is per job (an HttpOnly session cookie in browsers, bearer tokens for scripts and agents); *admin* is the operator.

    GET  /api/health, /api/ready, /api/whoami, /api/templates          public
    GET  /api/jobs                                                     public   job board (redacted)  ?state=POSTED&limit=50
    POST /api/tasks/validate                                           public   lint a custom task in the sandbox -> {ok, checks, ticket} (rate-limited)
    POST /api/jobs                                                     public   post a job {template | task, bounty_usd?, deadline_hours?}
    GET  /api/me/jobs                                                  session  the jobs this browser can act on
    GET  /api/jobs/<id>                                                public   redacted; richer for buyer/worker/admin; includes `viewer.roles`
    POST /api/jobs/<id>/accept                                         public   worker commits {worker_id, worker_email}
    POST /api/jobs/<id>/escrow | /confirm-funding | /cancel | /reject-worker       buyer
    POST /api/jobs/<id>/withdraw | /submit                             worker
    POST /api/jobs/<id>/run | /arbitrate                               buyer|worker
    GET  /api/jobs/<id>/events | /stream | /receipt | /hidden-tests    public   (hidden tests only after the verdict)
    POST /api/receipts/verify                                          public   check a receipt's signature
    POST /api/admin/login | /logout;  GET /api/admin/overview | /jobs;  POST /api/admin/sweep    operator
    POST /api/webhooks/paypal                                          PayPal   signature-verified webhook
    GET  /escrow/success | /escrow/cancel                              PayPal return URLs (redirect to the UI)
    GET  /.well-known/agentescrow-receipt-key.json | /.well-known/agent-card.json           discovery

Run:  python -m agentescrow.api.app             (production server; MCP servers as separate processes)
      python -m agentescrow.api.app --inprocess (one process; convenient for demos)
      python -m agentescrow.api.app --dev       (Flask's development server)
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

from flask import Flask, Response, abort, jsonify, redirect, request, send_from_directory, stream_with_context
from flask_cors import CORS
from pydantic import ValidationError
from werkzeug.middleware.proxy_fix import ProxyFix

from agentescrow import __version__
from agentescrow.agents.factory import AgentError
from agentescrow.api.auth import (
    ADMIN_COOKIE, SESSION_COOKIE, AuthError, check_origin, current_principal, require_admin, require_role, view_role,
    viewer_roles,
)  # fmt: skip
from agentescrow.api.ratelimit import RateLimiter, StreamLimiter
from agentescrow.api.runner import AsyncRunner
from agentescrow.arbiter.judge_factory import build_judge
from agentescrow.arbiter.sandbox_runner import SandboxUnavailable, resolve_backend
from agentescrow.config import ConfigError, Settings
from agentescrow.domain.capability import Grant, issue_admin_session, issue_capability, issue_session, merge_grant, read_session
from agentescrow.domain.models import Job, JobState
from agentescrow.domain.state_machine import TERMINAL_STATES
from agentescrow.logging_setup import configure_logging
from agentescrow.mcp_client import ToolCallFailed
from agentescrow.orchestrator.endpoints import http_endpoints, inprocess_endpoints
from agentescrow.orchestrator.lock import InstanceLock, InstanceLockError
from agentescrow.orchestrator.service import EscrowService, JobError, NotReady, TaskRejected
from agentescrow.orchestrator.store import JobNotFound, JobStore
from agentescrow.sitecheck import site_options
from agentescrow.sites import SitePreferences
from agentescrow.tasks import DEFAULT_TEMPLATE, CustomTask, personas_for, template_catalog

logger = logging.getLogger(__name__)

_RUNNABLE_STATES = {JobState.ESCROW_LOCKED, JobState.SUBMITTED, JobState.NEEDS_REVIEW, JobState.SETTLING}
_ARBITRATABLE_STATES = {JobState.SUBMITTED, JobState.NEEDS_REVIEW, JobState.SETTLING}
_SSE_POLL_S = 0.5
_SSE_KEEPALIVE_S = 15
_UI_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
    "connect-src 'self'; frame-src 'self' about:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def _body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _sse(event: str, data: Any, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data)}\n\n"


def _parse_states(values: list[str]) -> list[JobState] | None:
    try:
        return [JobState(value.upper()) for value in values] or None
    except ValueError as exc:
        raise ValueError(f"Unknown state; choose from {[s.value for s in JobState]}") from exc


def _describe(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in exc.errors()[:6])


def create_app(
    settings: Settings,
    service: EscrowService,
    runner: AsyncRunner,
    *,
    limiter: RateLimiter | None = None,
    streams: StreamLimiter | None = None,
) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
    if settings.trust_proxy:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # type: ignore[method-assign]
    CORS(app, origins=[settings.frontend_url], allow_headers=["Authorization", "Content-Type"], supports_credentials=True)
    limiter = limiter or RateLimiter(settings.rate_limit_per_min)
    validate_limiter = RateLimiter(max(1, settings.validate_per_min))
    login_limiter = RateLimiter(5)
    streams = streams or StreamLimiter(settings.max_streams, settings.max_streams_per_ip)
    dist_dir = settings.frontend_dist
    secure_cookies = settings.public_base_url.startswith("https://")

    def client_key() -> str:
        return request.remote_addr or "unknown"

    def throttle(bucket: str, which: RateLimiter | None = None) -> None:
        if not (which or limiter).allow(f"{bucket}:{client_key()}"):
            raise AuthError(429, "Too many requests; slow down and try again in a minute")

    def set_cookie(response: Response, name: str, value: str, max_age: int) -> Response:
        response.set_cookie(name, value, max_age=max_age, httponly=True, samesite="Strict", secure=secure_cookies or request.is_secure, path="/")
        return response

    # ------------------------------------------------------------------ errors --
    @app.errorhandler(AuthError)
    def _auth(exc: AuthError):
        kind = {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}.get(exc.status, "error")
        return jsonify(error=kind, message=exc.message), exc.status

    @app.errorhandler(JobNotFound)
    def _not_found(exc: JobNotFound):
        return jsonify(error="job_not_found", message=f"No job {exc}"), 404

    @app.errorhandler(NotReady)
    def _not_ready(exc: NotReady):
        return jsonify(error="not_ready", message=str(exc)), 409

    @app.errorhandler(TaskRejected)
    def _task_rejected(exc: TaskRejected):
        return jsonify(error="task_rejected", message=str(exc), **exc.report.model_dump(mode="json")), 422

    @app.errorhandler(JobError)
    def _conflict(exc: JobError):
        return jsonify(error="conflict", message=str(exc)), 409

    @app.errorhandler(ValidationError)
    def _invalid(exc: ValidationError):
        return jsonify(error="bad_request", message=_describe(exc)), 400

    @app.errorhandler(ValueError)
    def _bad_request(exc: ValueError):
        return jsonify(error="bad_request", message=str(exc)), 400

    @app.errorhandler(SandboxUnavailable)
    def _no_sandbox(exc: SandboxUnavailable):
        return jsonify(error="sandbox_unavailable", message=str(exc)), 503

    @app.errorhandler(ToolCallFailed)
    def _upstream(exc: ToolCallFailed):
        logger.error("Upstream tool failure: %s", exc)
        return jsonify(error="upstream_failure", message=str(exc)), 502

    @app.errorhandler(AgentError)
    def _agent(exc: AgentError):
        logger.error("Agent failure: %s", exc)
        return jsonify(error="agent_failure", message=str(exc)), 502

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        if hasattr(exc, "code") and isinstance(exc.code, int):  # werkzeug HTTPException
            return jsonify(error="http_error", message=getattr(exc, "description", str(exc))), exc.code
        logger.exception("Unhandled error")
        return jsonify(error="internal_error", message="Unexpected server error; see the server log"), 500

    @app.before_request
    def _csrf():
        check_origin(settings)

    @app.after_request
    def _security_headers(response: Response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if not request.path.startswith(("/api/", "/.well-known/")):
            response.headers.setdefault("Content-Security-Policy", _UI_CSP)
        return response

    # ------------------------------------------------------------------- helpers --
    def present(job: Job, role: str, principal) -> dict[str, Any]:  # noqa: ANN001
        data = job.view(role)
        data["viewer"] = {"roles": viewer_roles(principal, job)}
        return data

    def load(job_id: str, *roles: str):  # noqa: ANN202
        """Load a job and authorize the caller for one of ``roles``: returns (job, principal, acting_role)."""
        job = service.get_job(job_id)
        principal, acting = require_role(settings, job_id, *roles, job=job)
        return job, principal, acting

    def spawn_pipeline(job_id: str, persona: str = "honest") -> None:
        runner.spawn(
            service.run_pipeline(job_id, persona),
            on_error=lambda exc: service.record_error(job_id, f"{type(exc).__name__}: {exc}"),
        )

    def issue(response: Response, job: Job, role: str) -> tuple[Response, str]:
        """Give this browser a session grant (cookie) and return the bearer token for non-browser clients too."""
        epoch = job.worker_epoch if role == "worker" else None
        token = issue_capability(settings.mandate_secret, job_id=job.job_id, role=role, ttl_seconds=settings.capability_ttl_s, epoch=epoch)
        grants = merge_grant(read_session(settings.mandate_secret, request.cookies.get(SESSION_COOKIE)), Grant(job.job_id, role, epoch))
        set_cookie(response, SESSION_COOKIE, issue_session(settings.mandate_secret, grants, ttl_seconds=settings.capability_ttl_s), settings.capability_ttl_s)
        return response, token

    # ------------------------------------------------------------------ public --
    @app.get("/api/health")
    def health():
        try:
            sandbox = resolve_backend(settings.sandbox_backend, allow_unsafe=settings.allow_unsafe_sandbox)
        except SandboxUnavailable:
            sandbox = "unavailable"
        return jsonify(
            status="ok", version=__version__, paypal_mode=settings.paypal_mode, buyer_mode=settings.buyer_mode,
            worker_mode=settings.worker_mode, semantic_judge=settings.semantic_judge, llm_model=settings.groq_model,
            sandbox_backend=sandbox, judge_samples=settings.judge_samples, challenge_personas=settings.demo_personas,
            webhooks_configured=bool(settings.paypal_webhook_id) or settings.paypal_mode == "simulated",
            admin_enabled=bool(settings.admin_token),
        )  # fmt: skip

    @app.get("/api/ready")
    def ready():
        checks = runner.run(service.check_dependencies(), timeout=20)
        ok = all(check["ok"] for check in checks.values())
        return jsonify(ready=ok, checks=checks), 200 if ok else 503

    @app.get("/api/whoami")
    def whoami():
        principal = current_principal(settings)
        return jsonify(role=principal.role, admin=principal.admin, jobs=sorted({g.job_id for g in principal.grants}))

    @app.get("/api/templates")
    def templates():
        return jsonify(template_catalog())

    @app.get("/api/site/options")
    def site_form_options():
        """What the website preference form offers (sections, colours, tones), so the UI never hard-codes them."""
        return jsonify(site_options())

    @app.get("/api/jobs")
    def list_jobs():
        states = _parse_states(request.args.getlist("state"))
        limit = max(1, min(request.args.get("limit", default=50, type=int), 100))
        return jsonify([job.view("public") for job in service.list_jobs(states, limit)])

    @app.get("/api/me/jobs")
    def my_jobs():
        principal = current_principal(settings)
        out = []
        for job_id in dict.fromkeys(g.job_id for g in reversed(principal.grants)):
            try:
                job = service.get_job(job_id)
            except JobNotFound:
                continue
            roles = viewer_roles(principal, job)
            if roles:
                out.append({"job_id": job_id, "roles": roles, "state": job.state.value, "title": job.contract.specification.title, "bounty_usd": str(job.contract.bounty_usd)})
        return jsonify(out)

    @app.post("/api/tasks/validate")
    def validate_task():
        throttle("validate", validate_limiter)
        task = CustomTask.model_validate(_body())
        report, ticket = runner.run(service.validate_custom_task(task), timeout=240)
        return jsonify(**report.model_dump(mode="json"), ticket=ticket)  # a failed lint is a normal answer, not an error

    @app.post("/api/jobs")
    def create_job():
        throttle("create")
        body = _body()
        raw = body.get("bounty_usd")
        try:
            bounty = Decimal(str(raw)) if raw is not None else None
        except InvalidOperation as exc:
            raise ValueError("bounty_usd must be a number such as '5.00'") from exc
        if bounty is not None and not (Decimal("1.00") <= bounty <= Decimal("100.00")):
            raise ValueError("bounty_usd must be between 1.00 and 100.00 in this demo")
        hours = body.get("deadline_hours")
        if hours is not None and (not isinstance(hours, int) or isinstance(hours, bool)):
            raise ValueError("deadline_hours must be a whole number")
        custom = CustomTask.model_validate(body["task"]) if isinstance(body.get("task"), dict) else None
        site = SitePreferences.model_validate(body["site"]) if isinstance(body.get("site"), dict) else None
        template = str(body.get("template") or DEFAULT_TEMPLATE)
        job = runner.run(service.post_job(bounty, hours, template, custom, body.get("validation_ticket"), site), timeout=240)
        principal = current_principal(settings)
        response, token = issue(jsonify(), job, "buyer")
        response.set_data(json.dumps({"job": present(job, "buyer", _with_grant(principal, job, "buyer")), "token": token, "role": "buyer"}))
        response.mimetype, response.status_code = "application/json", 201
        return response

    def _with_grant(principal, job: Job, role: str):  # noqa: ANN001, ANN202
        """The principal as it will be once the new cookie is set (so the response can already list the new role)."""
        from dataclasses import replace

        epoch = job.worker_epoch if role == "worker" else None
        return replace(principal, grants=(*principal.grants, Grant(job.job_id, role, epoch)))

    @app.get("/api/jobs/<job_id>")
    def get_job(job_id: str):
        job = service.get_job(job_id)
        principal = current_principal(settings)
        return jsonify(present(job, view_role(principal, job), principal))

    @app.post("/api/jobs/<job_id>/accept")
    def accept(job_id: str):
        throttle("accept")
        body = _body()
        job = runner.run(service.accept_job(job_id, str(body.get("worker_id", "")), str(body.get("worker_email", ""))))
        principal = current_principal(settings)
        response, token = issue(jsonify(), job, "worker")
        response.set_data(json.dumps({"job": present(job, "worker", _with_grant(principal, job, "worker")), "token": token, "role": "worker"}))
        response.mimetype = "application/json"
        return response

    @app.get("/api/jobs/<job_id>/events")
    def events(job_id: str):
        return jsonify(service.events(job_id, request.args.get("after", default=0, type=int)))

    @app.get("/api/jobs/<job_id>/receipt")
    def receipt(job_id: str):
        return jsonify(service.receipt(job_id))

    @app.get("/api/jobs/<job_id>/hidden-tests")
    def hidden_tests(job_id: str):
        return jsonify(service.reveal_hidden_tests(job_id))

    @app.post("/api/receipts/verify")
    def verify_receipt():
        return jsonify(service.verify_receipt(_body()))

    @app.get("/api/jobs/<job_id>/stream")
    def stream(job_id: str):
        service.get_job(job_id)  # 404 before the stream opens
        key = client_key()
        if not streams.acquire(key):
            raise AuthError(429, "Too many live streams open; close some tabs or retry shortly")
        last_id = request.args.get("after", type=int)
        if last_id is None:
            last_id = request.headers.get("Last-Event-ID", default=0, type=int)

        def generate():
            nonlocal last_id
            idle = 0.0
            try:
                while True:
                    fresh = service.events(job_id, last_id)
                    for event in fresh:
                        last_id = event["id"]
                        yield _sse("timeline", event, event["id"])
                        idle = 0.0
                    if not fresh and service.get_job(job_id).state in TERMINAL_STATES:
                        time.sleep(0.3)  # let a final event land
                        if not service.events(job_id, last_id):
                            yield _sse("end", {"job_id": job_id})
                            return
                        continue
                    if not fresh:
                        idle += _SSE_POLL_S
                        if idle >= _SSE_KEEPALIVE_S:
                            yield ": keep-alive\n\n"
                            idle = 0.0
                    time.sleep(_SSE_POLL_S)
            finally:
                streams.release(key)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------ buyer actions --
    @app.post("/api/jobs/<job_id>/escrow")
    def open_escrow(job_id: str):
        _, principal, acting = load(job_id, "buyer")
        job = runner.run(service.open_escrow(job_id), timeout=180)
        return jsonify(present(job, acting, principal))

    @app.post("/api/jobs/<job_id>/confirm-funding")
    def confirm_funding(job_id: str):
        _, principal, acting = load(job_id, "buyer")
        job = runner.run(service.confirm_funding(job_id), timeout=60)
        return jsonify(present(job, acting, principal))

    @app.post("/api/jobs/<job_id>/cancel")
    def cancel(job_id: str):
        _, principal, acting = load(job_id, "buyer")
        job = runner.run(service.cancel_job(job_id), timeout=60)
        return jsonify(present(job, acting, principal))

    @app.post("/api/jobs/<job_id>/reject-worker")
    def reject_worker(job_id: str):
        _, principal, acting = load(job_id, "buyer")
        job = runner.run(service.release_worker(job_id, by="buyer"))
        return jsonify(present(job, acting, principal))

    # ----------------------------------------------------- buyer or worker actions --
    @app.post("/api/jobs/<job_id>/run")
    def run_pipeline(job_id: str):
        job, principal, acting = load(job_id, "buyer", "worker")
        persona = str(_body().get("persona", "honest"))
        allowed = personas_for(job.template_id) if settings.demo_personas else ("honest",)
        if persona not in allowed:
            raise ValueError(f"persona must be one of {list(allowed)} for this job")
        if job.state not in _RUNNABLE_STATES:
            raise JobError(f"Job is {job.state.value}; it must be funded (ESCROW_LOCKED) before it can run")
        spawn_pipeline(job_id, persona)
        return jsonify(present(job, acting, principal)), 202

    @app.post("/api/jobs/<job_id>/arbitrate")
    def arbitrate(job_id: str):
        job, principal, acting = load(job_id, "buyer", "worker")
        if job.state not in _ARBITRATABLE_STATES:
            raise JobError(f"Job is {job.state.value}; nothing to arbitrate")
        spawn_pipeline(job_id)
        return jsonify(present(job, acting, principal)), 202

    # ------------------------------------------------------------ worker actions --
    @app.post("/api/jobs/<job_id>/submit")
    def submit(job_id: str):
        _, principal, acting = load(job_id, "worker")
        job = runner.run(service.submit_deliverable(job_id, _body()))
        return jsonify(present(job, acting, principal))

    @app.post("/api/jobs/<job_id>/withdraw")
    def withdraw(job_id: str):
        _, principal, _ = load(job_id, "worker")
        job = runner.run(service.release_worker(job_id, by="worker"))
        return jsonify(present(job, "public", principal))

    # ----------------------------------------------------------------- operator --
    @app.post("/api/admin/login")
    def admin_login():
        throttle("login", login_limiter)
        supplied = str(_body().get("token", ""))
        if not settings.admin_token or not hmac.compare_digest(supplied, settings.admin_token):
            raise AuthError(401, "That operator token is not valid")
        response = jsonify(role="admin")
        return set_cookie(response, ADMIN_COOKIE, issue_admin_session(settings.mandate_secret, ttl_seconds=settings.admin_session_ttl_s), settings.admin_session_ttl_s)

    @app.post("/api/admin/logout")
    def admin_logout():
        response = jsonify(role="public")
        response.delete_cookie(ADMIN_COOKIE, path="/")
        return response

    @app.get("/api/admin/overview")
    def admin_overview():
        require_admin(settings)
        return jsonify(service.overview())

    @app.get("/api/admin/jobs")
    def admin_jobs():
        require_admin(settings)
        states = _parse_states(request.args.getlist("state"))
        limit = max(1, min(request.args.get("limit", default=100, type=int), 500))
        return jsonify([job.view("admin") for job in service.list_jobs(states, limit)])

    @app.post("/api/admin/sweep")
    def admin_sweep():
        require_admin(settings)
        return jsonify(closed=runner.run(service.sweep_overdue(), timeout=120))

    # ------------------------------------------------------------------ webhooks --
    @app.post("/api/webhooks/paypal")
    def paypal_webhook():
        raw = request.get_data()  # the exact bytes PayPal signed
        if not settings.paypal_webhook_id and settings.paypal_mode != "simulated":
            return jsonify(error="webhooks_not_configured", message="Set PAYPAL_WEBHOOK_ID to receive PayPal webhooks"), 503
        try:
            verified = runner.run(service.verify_webhook(request.headers, raw), timeout=30)
        except ToolCallFailed as exc:
            logger.error("Webhook verification could not be completed: %s", exc)
            return jsonify(error="verification_unavailable", message="Could not verify; PayPal will retry"), 503
        if not verified:
            logger.warning("Rejected a webhook with an invalid signature")
            return jsonify(error="invalid_signature", message="Webhook signature is not valid"), 401
        event = json.loads(raw)
        runner.spawn(
            service.handle_webhook(event if isinstance(event, dict) else {}),
            on_error=lambda exc: logger.error("Webhook handler failed: %s", exc),
        )
        return jsonify(received=True), 200  # answer fast; PayPal retries anything that is not 2xx

    # -------------------------------------------------------- PayPal redirects --
    def _ui(job_id: str, **params: str) -> Response:
        query = f"?{urlencode(params)}" if params else ""
        return redirect(f"{settings.frontend_url}/jobs/{job_id}{query}")

    @app.get("/escrow/success")
    def escrow_success():
        throttle("confirm")
        job_id = request.args.get("job_id", "")
        service.get_job(job_id)
        try:  # safe without credentials: it only moves forward if PayPal itself says the order is approved
            runner.run(service.confirm_funding(job_id), timeout=60)
        except (JobError, ToolCallFailed) as exc:
            logger.warning("Funding confirmation after PayPal return failed: %s", exc)
            return _ui(job_id, error=str(exc)[:200])
        return _ui(job_id, funded="1")

    @app.get("/escrow/cancel")
    def escrow_cancel():
        job_id = request.args.get("job_id", "")
        service.get_job(job_id)
        service.record_error(job_id, "The buyer left the PayPal approval page without approving")
        return _ui(job_id, cancelled="1")

    # ------------------------------------------------------------------ discovery --
    @app.get("/.well-known/agentescrow-receipt-key.json")
    def receipt_key():
        return jsonify(service.signer.public_info())

    @app.get("/.well-known/agent-card.json")
    def agent_card():
        base = settings.public_base_url
        skills = [
            {"id": "post-escrowed-job", "name": "Post an escrowed job", "description": "Post a verifiable Python-function task with a bounty held in PayPal escrow.", "tags": ["escrow", "payments", "jobs"]},
            {"id": "accept-and-deliver", "name": "Accept a job and deliver", "description": "Accept an open job, write the solution, and get paid when the hidden tests pass.", "tags": ["work", "agents", "payouts"]},
            {"id": "verify-verdict", "name": "Verify a verdict receipt", "description": "Check an Ed25519-signed verdict receipt and the hidden-test commitment.", "tags": ["verification", "audit"]},
        ]
        card = {
            "name": "AgentEscrow",
            "description": (
                "Escrow and autonomous arbitration for agent-to-agent payments on the PayPal sandbox. Discovery card only: jobs are exchanged "
                "through the REST API and MCP server listed under x-agentescrow, not through A2A message endpoints."
            ),
            "version": __version__,
            "url": base,
            "provider": {"organization": "AgentEscrow", "url": base},
            "capabilities": {"streaming": False, "pushNotifications": False},
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": skills,
            "x-agentescrow": {
                "rest_api": f"{base}/api",
                "job_board": f"{base}/api/jobs?state=POSTED",
                "receipt_public_key": f"{base}/.well-known/agentescrow-receipt-key.json",
                "mcp_server": "python -m agentescrow.mcp_servers.marketplace_server (Streamable HTTP, /mcp)",
                "human_docs": f"{base}/agents",
            },
        }
        return jsonify(card)

    # ------------------------------------------------------------- built React UI --
    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path: str):
        if path.startswith(("api/", "escrow/", ".well-known/")):
            abort(404)
        if not (dist_dir / "index.html").is_file():
            return jsonify(message="API is running. Build the UI with `cd frontend && npm run build`, or run it with `npm run dev`.")
        target = (dist_dir / path).resolve()
        if path and target.is_file() and dist_dir.resolve() in target.parents:
            return send_from_directory(dist_dir, path)
        return send_from_directory(dist_dir, "index.html")  # single-page-app fallback

    return app


async def _sweep_forever(service: EscrowService, interval_s: int) -> None:
    """Close overdue jobs now and then every ``interval_s`` seconds, for as long as the process lives."""
    while True:
        try:
            await service.sweep_overdue()
        except Exception:  # noqa: BLE001 - the sweeper must never die
            logger.exception("Deadline sweep failed")
        await asyncio.sleep(interval_s)


def build_service(settings: Settings, *, inprocess: bool) -> EscrowService:
    endpoints = inprocess_endpoints(settings) if inprocess else http_endpoints(settings)
    return EscrowService(settings, JobStore(settings.database_path), endpoints, build_judge(settings))


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentEscrow API server")
    parser.add_argument("--inprocess", action="store_true", help="run the MCP servers inside this process")
    parser.add_argument("--dev", action="store_true", help="use Flask's development server instead of the production server")
    args = parser.parse_args()

    settings = Settings.from_env()
    configure_logging(settings.log_level, settings.log_dir, service="api")
    try:
        settings.validate_modes()
        settings.require_mandate_secret()
        if settings.semantic_judge == "groq" or settings.worker_mode == "agent" or settings.buyer_mode == "agent":
            settings.require_groq()
        if not settings.admin_token:
            logger.warning("ADMIN_TOKEN is not set: the operator endpoints are disabled")
        if settings.paypal_mode == "sandbox" and not settings.paypal_webhook_id:
            logger.warning("PAYPAL_WEBHOOK_ID is not set: webhooks are off and funding relies on the return URL and polling")
        if settings.allow_unsafe_sandbox:
            logger.warning("ALLOW_UNSAFE_SANDBOX=true: worker code may run WITHOUT isolation. Development only.")
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    lock = InstanceLock(settings.database_path.with_suffix(".lock"))
    if settings.single_instance:
        try:
            lock.acquire()
        except InstanceLockError as exc:
            raise SystemExit(str(exc)) from exc

    service = build_service(settings, inprocess=args.inprocess)
    runner = AsyncRunner()
    runner.spawn(service.recover_after_restart())
    runner.spawn(_sweep_forever(service, settings.sweep_interval_s))
    app = create_app(settings, service, runner)
    logger.info(
        "API listening on http://%s:%s (paypal=%s, worker=%s, buyer=%s, judge=%s x%d, mcp=%s, server=%s)",
        settings.api_host, settings.api_port, settings.paypal_mode, settings.worker_mode, settings.buyer_mode,
        settings.semantic_judge, settings.judge_samples, "in-process" if args.inprocess else "http", "flask-dev" if args.dev else "waitress",
    )  # fmt: skip
    try:
        if args.dev:
            app.run(host=settings.api_host, port=settings.api_port, threaded=True)
        else:
            from waitress import serve

            # send_bytes=1 makes streamed responses (the live timeline) reach the browser immediately.
            serve(app, host=settings.api_host, port=settings.api_port, threads=settings.server_threads, send_bytes=1, ident="agentescrow", channel_timeout=120)
    finally:
        lock.release()


if __name__ == "__main__":
    main()
