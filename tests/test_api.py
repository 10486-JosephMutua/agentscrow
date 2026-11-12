"""HTTP API tests: auth roles, redaction, rate limits, webhooks, admin, SSE, static UI."""

from __future__ import annotations

import json
import time

import pytest

from agentescrow.api.app import create_app
from agentescrow.api.ratelimit import RateLimiter
from agentescrow.api.runner import AsyncRunner
from agentescrow.arbiter.semantic_judge import StaticSemanticJudge
from agentescrow.orchestrator.endpoints import inprocess_endpoints
from agentescrow.orchestrator.service import EscrowService
from agentescrow.orchestrator.store import JobStore
from agentescrow.paypal.simulator import SimulatedPayPalClient
from agentescrow.samples import SCRIPTED_DELIVERABLES
from tests.conftest import ADMIN_TOKEN


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def parts(settings):
    runner = AsyncRunner()
    service = EscrowService(
        settings, JobStore(settings.database_path), inprocess_endpoints(settings, SimulatedPayPalClient()),
        StaticSemanticJudge(0.9),
    )  # fmt: skip
    yield settings, service, runner
    runner.stop()


@pytest.fixture
def client(parts):
    settings, service, runner = parts
    app = create_app(settings, service, runner)
    app.testing = True
    return app.test_client(use_cookies=False)  # these tests authenticate with bearer tokens, like a script or agent


def wait_for(client, job_id, states, token=None, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=auth(token) if token else {}).get_json()
        if job["state"] in states:
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} stuck in {job['state']}")


def new_job(client, **body):
    created = client.post("/api/jobs", json={"bounty_usd": "5.00", **body})
    assert created.status_code == 201
    data = created.get_json()
    return data["job"]["job_id"], data["token"]


def accepted_job(client):
    jid, buyer = new_job(client)
    worker = client.post(f"/api/jobs/{jid}/accept", json={"worker_id": "w1", "worker_email": "w@example.com"}).get_json()["token"]
    return jid, buyer, worker


def funded_job(client):
    jid, buyer, worker = accepted_job(client)
    escrow = client.post(f"/api/jobs/{jid}/escrow", headers=auth(buyer))
    assert escrow.status_code == 200 and escrow.get_json()["approve_url"]
    assert client.get(f"/escrow/success?job_id={jid}").status_code == 302
    return jid, buyer, worker


# ---------------------------------------------------------------------- basics --
def test_health_reports_modes_but_no_secrets(client):
    body = client.get("/api/health").get_json()
    assert body["status"] == "ok" and body["paypal_mode"] == "simulated" and body["webhooks_configured"] is True
    assert "secret" not in json.dumps(body).lower() and ADMIN_TOKEN not in json.dumps(body)


def test_security_headers_are_set(client):
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff" and response.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" not in response.headers  # API JSON needs none
    assert "frame-ancestors 'none'" in client.get("/anything").headers["Content-Security-Policy"]


# ------------------------------------------------------------------- redaction --
def test_public_view_hides_everything_sensitive(client):
    jid, buyer, worker = funded_job(client)
    client.post(f"/api/jobs/{jid}/run", json={"persona": "honest"}, headers=auth(buyer))
    wait_for(client, jid, {"SETTLED"})
    text = json.dumps(client.get(f"/api/jobs/{jid}").get_json())
    assert "hidden_tests_sha256" in text, "the commitment is public by design"
    for secret in ('"hidden_tests":', "reference_solution", "mandate_token", "test_run_longer_than_nine", "w@example.com", "parts.append", "SIM-AUTH", "SIM-ORDER"):
        assert secret not in text, secret
    assert '"deliverable_submitted": true' in text


def test_each_role_sees_what_it_should(client):
    jid, buyer, worker = funded_job(client)
    client.post(f"/api/jobs/{jid}/run", json={"persona": "honest"}, headers=auth(buyer))
    wait_for(client, jid, {"SETTLED"})
    as_buyer = client.get(f"/api/jobs/{jid}", headers=auth(buyer)).get_json()
    as_worker = client.get(f"/api/jobs/{jid}", headers=auth(worker)).get_json()
    as_admin = client.get(f"/api/jobs/{jid}", headers=auth(ADMIN_TOKEN)).get_json()
    assert "def rle_encode" in json.dumps(as_buyer["deliverable"]) and "worker_email" not in as_buyer
    assert "worker_email" not in as_worker and "approve_url" not in as_worker
    assert as_admin["worker_email"] == "w@example.com"
    for view in (as_buyer, as_worker, as_admin):
        assert "hidden_tests" not in view and "mandate_token" not in view


def test_another_jobs_token_gets_only_the_public_view(client):
    jid, _, _ = funded_job(client)
    _, other_buyer = new_job(client)
    view = client.get(f"/api/jobs/{jid}", headers=auth(other_buyer)).get_json()
    assert "deliverable" not in view and "order_id" not in view


# ------------------------------------------------------------------------ auth --
def test_protected_actions_need_the_right_token(client):
    jid, buyer, worker = accepted_job(client)
    other_jid, other_buyer = new_job(client)
    assert client.post(f"/api/jobs/{jid}/escrow").status_code == 401
    assert client.post(f"/api/jobs/{jid}/escrow", headers=auth("garbage")).status_code == 401
    assert client.post(f"/api/jobs/{jid}/escrow", headers=auth(worker)).status_code == 403
    assert client.post(f"/api/jobs/{jid}/escrow", headers=auth(other_buyer)).status_code == 403
    assert client.post(f"/api/jobs/{jid}/escrow", headers=auth(buyer)).status_code == 200
    assert client.post(f"/api/jobs/{jid}/submit", json={}, headers=auth(buyer)).status_code == 403  # only workers submit


def test_an_expired_token_is_a_401(parts):
    settings, service, runner = parts
    from agentescrow.domain.capability import issue_capability

    expired = issue_capability(settings.mandate_secret, job_id="job_x", role="buyer", ttl_seconds=60, now=time.time() - 3600)
    app = create_app(settings, service, runner)
    assert app.test_client().get("/api/whoami", headers=auth(expired)).status_code == 401


def test_whoami(client):
    jid, buyer = new_job(client)
    assert client.get("/api/whoami").get_json() == {"role": "public", "admin": False, "jobs": []}
    assert client.get("/api/whoami", headers=auth(buyer)).get_json() == {"role": "buyer", "admin": False, "jobs": [jid]}
    assert client.get("/api/whoami", headers=auth(ADMIN_TOKEN)).get_json()["role"] == "admin"


def test_admin_endpoints(client):
    jid, buyer, _ = funded_job(client)
    client.post(f"/api/jobs/{jid}/run", json={"persona": "honest"}, headers=auth(buyer))
    wait_for(client, jid, {"SETTLED"})
    assert client.get("/api/admin/overview").status_code == 401
    assert client.get("/api/admin/overview", headers=auth(buyer)).status_code == 403
    overview = client.get("/api/admin/overview", headers=auth(ADMIN_TOKEN)).get_json()
    assert overview["counts"]["SETTLED"] == 1 and overview["captured_usd"] == "5.00"
    jobs = client.get("/api/admin/jobs?state=SETTLED", headers=auth(ADMIN_TOKEN)).get_json()
    assert [j["job_id"] for j in jobs] == [jid] and jobs[0]["worker_email"] == "w@example.com"
    assert client.post("/api/admin/sweep", headers=auth(ADMIN_TOKEN)).get_json() == {"closed": []}
    assert client.get("/api/admin/jobs?state=NOPE", headers=auth(ADMIN_TOKEN)).status_code == 400


def test_admin_is_disabled_without_a_configured_token(parts):
    settings, service, runner = parts
    from dataclasses import replace

    app = create_app(replace(settings, admin_token=""), service, runner)
    assert app.test_client().get("/api/admin/overview", headers=auth("")).status_code == 401


# ------------------------------------------------------------------ rate limiting --
def test_rate_limits_job_creation(parts):
    settings, service, runner = parts
    app = create_app(settings, service, runner, limiter=RateLimiter(3))
    client = app.test_client()
    codes = [client.post("/api/jobs", json={}).status_code for _ in range(5)]
    assert codes == [201, 201, 201, 429, 429]


def test_rate_limiter_refills_over_time():
    now = [0.0]
    limiter = RateLimiter(60, clock=lambda: now[0])  # one token per second
    assert [limiter.allow("a") for _ in range(61)].count(False) == 1
    assert limiter.allow("b")  # other keys are independent
    now[0] += 2.0
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")


# ------------------------------------------------------------------------ flows --
def test_full_flow_through_http_honest_worker(client):
    jid, buyer, worker = funded_job(client)
    assert client.get(f"/api/jobs/{jid}").get_json()["state"] == "ESCROW_LOCKED"
    assert client.post(f"/api/jobs/{jid}/run", json={"persona": "honest"}, headers=auth(worker)).status_code == 202
    job = wait_for(client, jid, {"SETTLED", "VOIDED"})
    assert job["state"] == "SETTLED" and job["decision"]["outcome"] == "FULL"
    receipt = client.get(f"/api/jobs/{jid}/receipt").get_json()
    assert receipt["receipt"]["worker_payout_usd"] == "4.67" and receipt["signature"]


def test_cheater_is_voided_over_http(client):
    jid, buyer, _ = funded_job(client)
    client.post(f"/api/jobs/{jid}/run", json={"persona": "cheater"}, headers=auth(buyer))
    job = wait_for(client, jid, {"SETTLED", "VOIDED"})
    assert job["state"] == "VOIDED" and job["decision"]["outcome"] == "VOID"


def test_external_worker_can_submit_and_get_arbitrated(client):
    jid, buyer, worker = funded_job(client)
    assert client.post(f"/api/jobs/{jid}/submit", json=SCRIPTED_DELIVERABLES["honest"], headers=auth(worker)).status_code == 200
    assert client.post(f"/api/jobs/{jid}/arbitrate", headers=auth(buyer)).status_code == 202
    assert wait_for(client, jid, {"SETTLED", "VOIDED"})["state"] == "SETTLED"


def test_job_board_filters_by_state(client):
    open_id, _ = new_job(client)
    taken_id, _, _ = accepted_job(client)
    posted = [j["job_id"] for j in client.get("/api/jobs?state=POSTED").get_json()]
    assert open_id in posted and taken_id not in posted
    assert client.get("/api/jobs?state=BOGUS").status_code == 400


def test_deadline_hours(client):
    created = client.post("/api/jobs", json={"deadline_hours": 3}).get_json()["job"]
    assert 3 * 3600 - 60 < created["contract"]["deadline_epoch"] - time.time() < 3 * 3600 + 5
    assert client.post("/api/jobs", json={"deadline_hours": 0}).status_code == 400
    assert client.post("/api/jobs", json={"deadline_hours": "soon"}).status_code == 400
    assert client.post("/api/jobs", json={"deadline_hours": True}).status_code == 400


def test_sse_stream_replays_the_timeline_and_ends(client):
    jid, buyer, _ = funded_job(client)
    client.post(f"/api/jobs/{jid}/run", json={"persona": "honest"}, headers=auth(buyer))
    wait_for(client, jid, {"SETTLED"})
    raw = client.get(f"/api/jobs/{jid}/stream").get_data(as_text=True)
    assert raw.count("event: timeline") >= 8 and "Job settled" in raw and "event: end" in raw


def test_events_endpoint_supports_after(client):
    jid, _, _ = funded_job(client)
    everything = client.get(f"/api/jobs/{jid}/events").get_json()
    later = client.get(f"/api/jobs/{jid}/events?after={everything[0]['id']}").get_json()
    assert len(later) == len(everything) - 1


@pytest.mark.parametrize(
    ("method", "path", "payload", "status"),
    [
        ("get", "/api/jobs/job_missing", None, 404),
        ("get", "/api/jobs/job_missing/stream", None, 404),
        ("post", "/api/jobs", {"bounty_usd": "abc"}, 400),
        ("post", "/api/jobs", {"bounty_usd": "5000"}, 400),
        ("get", "/api/nope", None, 404),
    ],
)
def test_error_responses(client, method, path, payload, status):
    assert getattr(client, method)(path, json=payload).status_code == status


def test_conflicts_and_validation(client):
    jid, buyer = new_job(client)
    assert client.post(f"/api/jobs/{jid}/run", json={"persona": "honest"}, headers=auth(buyer)).status_code == 409
    assert client.post(f"/api/jobs/{jid}/escrow", headers=auth(buyer)).status_code == 409  # not accepted yet
    assert client.get(f"/api/jobs/{jid}/receipt").status_code == 409  # not settled yet
    assert client.post(f"/api/jobs/{jid}/accept", json={"worker_id": "w", "worker_email": "bad"}).status_code == 400


def test_unknown_persona_is_400(client):
    jid, buyer, _ = funded_job(client)
    assert client.post(f"/api/jobs/{jid}/run", json={"persona": "wizard"}, headers=auth(buyer)).status_code == 400


# --------------------------------------------------------------------- webhooks --
def webhook(client, event, signature=SimulatedPayPalClient.webhook_signature("WH-TEST")):
    return client.post(
        "/api/webhooks/paypal", data=json.dumps(event), content_type="application/json",
        headers={"PAYPAL-TRANSMISSION-SIG": signature},
    )  # fmt: skip


def test_webhook_signature_is_enforced(client):
    event = {"id": "WH-A", "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "X"}}
    assert webhook(client, event, signature="forged").status_code == 401
    assert webhook(client, event).status_code == 200


def test_webhook_approves_funding_end_to_end(parts):
    settings, service, runner = parts
    from dataclasses import replace

    settings = replace(settings, paypal_webhook_id="WH-TEST")
    paypal = SimulatedPayPalClient(auto_approve=False)
    service = EscrowService(settings, JobStore(settings.database_path), inprocess_endpoints(settings, paypal), StaticSemanticJudge(0.9))
    client = create_app(settings, service, runner).test_client()
    jid, buyer, _ = accepted_job(client)
    order_id = client.post(f"/api/jobs/{jid}/escrow", headers=auth(buyer)).get_json()["order_id"]
    paypal.approve(order_id)
    event = {"id": "WH-B", "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": order_id}}
    assert webhook(client, event, signature=SimulatedPayPalClient.webhook_signature("WH-TEST")).status_code == 200
    assert wait_for(client, jid, {"ESCROW_LOCKED"})["state"] == "ESCROW_LOCKED"


def test_webhooks_are_unavailable_without_a_configured_id(parts):
    settings, service, runner = parts
    from dataclasses import replace

    app = create_app(replace(settings, paypal_mode="sandbox", paypal_webhook_id=""), service, runner)
    assert webhook(app.test_client(), {"id": "x"}).status_code == 503


# ---------------------------------------------------------------------- static UI --
def test_built_ui_is_served_with_spa_fallback(parts, tmp_path):
    from dataclasses import replace

    settings, service, runner = parts
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "a.js").write_text("console.log(1)")
    client = create_app(replace(settings, frontend_dist=tmp_path), service, runner).test_client()
    assert client.get("/").get_data(as_text=True) == "<html>app</html>"
    assert client.get("/jobs/job_123").get_data(as_text=True) == "<html>app</html>"  # client-side route
    assert client.get("/assets/a.js").get_data(as_text=True) == "console.log(1)"
    assert client.get("/../../etc/passwd").status_code in (200, 404) and "root:" not in client.get("/..%2f..%2fetc%2fpasswd").get_data(as_text=True)
    assert client.get("/api/does-not-exist").status_code == 404  # never swallowed by the SPA


def test_without_a_build_the_root_explains_itself(parts, tmp_path):
    from dataclasses import replace

    settings, service, runner = parts
    empty = tmp_path / "no-build"
    client = create_app(replace(settings, frontend_dist=empty), service, runner).test_client()
    assert "Build the UI" in client.get("/").get_json()["message"]
