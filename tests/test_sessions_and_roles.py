"""Cookie sessions (HttpOnly), CSRF origin checks, operator login, and worker release with epochs."""

from __future__ import annotations

import time

import pytest

from agentescrow.api.app import create_app
from tests.conftest import ADMIN_TOKEN


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app(api_parts):
    settings, service, runner = api_parts
    flask_app = create_app(settings, service, runner)
    flask_app.testing = True
    return flask_app


def post_job(client, **body):
    response = client.post("/api/jobs", json={"bounty_usd": "5.00", **body})
    assert response.status_code == 201, response.get_json()
    return response


def wait_for(client, job_id, states, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").get_json()
        if job["state"] in states:
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} stuck in {job['state']}")


# ----------------------------------------------------------------------- sessions --
def test_the_session_cookie_is_httponly_and_samesite_strict(app):
    response = post_job(app.test_client())
    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith("ae_session=") and "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie


def test_a_browser_acts_without_ever_holding_a_token(app):
    browser = app.test_client()
    jid = post_job(browser).get_json()["job"]["job_id"]
    view = browser.get(f"/api/jobs/{jid}").get_json()
    assert view["viewer"]["roles"] == ["buyer"]
    assert browser.post(f"/api/jobs/{jid}/accept", json={"worker_id": "w", "worker_email": "w@example.com"}).status_code == 200
    assert browser.get(f"/api/jobs/{jid}").get_json()["viewer"]["roles"] == ["buyer", "worker"]  # one browser, both seats
    escrow = browser.post(f"/api/jobs/{jid}/escrow")  # authenticated by the cookie alone
    assert escrow.status_code == 200 and escrow.get_json()["approve_url"]


def test_another_browser_has_no_access(app):
    owner, stranger = app.test_client(), app.test_client()
    jid = post_job(owner).get_json()["job"]["job_id"]
    assert stranger.get(f"/api/jobs/{jid}").get_json()["viewer"]["roles"] == []
    assert stranger.post(f"/api/jobs/{jid}/escrow").status_code == 401


def test_forged_and_garbage_cookies_are_just_anonymous(app):
    client = app.test_client()
    jid = post_job(app.test_client()).get_json()["job"]["job_id"]
    client.set_cookie("ae_session", "garbage")
    assert client.get(f"/api/jobs/{jid}").status_code == 200
    assert client.post(f"/api/jobs/{jid}/escrow").status_code == 401


def test_my_jobs_lists_what_this_browser_can_act_on(app):
    browser = app.test_client()
    first = post_job(browser).get_json()["job"]["job_id"]
    second = post_job(browser).get_json()["job"]["job_id"]
    mine = browser.get("/api/me/jobs").get_json()
    assert [item["job_id"] for item in mine] == [second, first] and mine[0]["roles"] == ["buyer"]
    assert app.test_client().get("/api/me/jobs").get_json() == []


def test_bearer_tokens_still_work_for_scripts_and_agents(app):
    created = post_job(app.test_client(use_cookies=False)).get_json()
    jid, token = created["job"]["job_id"], created["token"]
    assert app.test_client(use_cookies=False).post(f"/api/jobs/{jid}/cancel", headers=auth(token)).status_code == 200


# ------------------------------------------------------------------------- CSRF --
def test_cross_site_state_changes_are_refused(app):
    browser = app.test_client()
    jid = post_job(browser).get_json()["job"]["job_id"]
    browser.post(f"/api/jobs/{jid}/accept", json={"worker_id": "w", "worker_email": "w@example.com"})
    assert browser.post(f"/api/jobs/{jid}/escrow", headers={"Origin": "https://evil.example"}).status_code == 403
    assert browser.post(f"/api/jobs/{jid}/escrow", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert browser.post(f"/api/jobs/{jid}/escrow", headers={"Origin": "http://localhost:5173"}).status_code == 200  # the UI's own origin


def test_a_bearer_request_is_exempt_from_the_origin_check(app):
    created = post_job(app.test_client(use_cookies=False)).get_json()
    client = app.test_client(use_cookies=False)
    assert client.post(f"/api/jobs/{created['job']['job_id']}/cancel", headers={**auth(created["token"]), "Origin": "https://evil.example"}).status_code == 200


def test_reads_are_not_subject_to_the_origin_check(app):
    jid = post_job(app.test_client()).get_json()["job"]["job_id"]
    assert app.test_client().get(f"/api/jobs/{jid}", headers={"Origin": "https://evil.example"}).status_code == 200


# --------------------------------------------------------------------- operator --
def test_operator_login_uses_an_httponly_cookie(app):
    client = app.test_client()
    assert client.get("/api/admin/overview").status_code == 401
    assert client.post("/api/admin/login", json={"token": "wrong"}).status_code == 401
    ok = client.post("/api/admin/login", json={"token": ADMIN_TOKEN})
    assert ok.status_code == 200 and "ae_admin=" in ok.headers["Set-Cookie"] and "HttpOnly" in ok.headers["Set-Cookie"]
    assert ADMIN_TOKEN not in ok.get_data(as_text=True)
    assert client.get("/api/admin/overview").status_code == 200
    client.post("/api/admin/logout")
    assert client.get("/api/admin/overview").status_code == 401


def test_operator_login_is_throttled(app):
    client = app.test_client()
    codes = [client.post("/api/admin/login", json={"token": f"guess-{i}"}).status_code for i in range(8)]
    assert codes[:5] == [401] * 5 and set(codes[5:]) == {429}


def test_operator_login_cannot_be_forged_cross_site(app):
    assert app.test_client().post("/api/admin/login", json={"token": ADMIN_TOKEN}, headers={"Origin": "https://evil.example"}).status_code == 403


# ------------------------------------------------------------------ worker release --
def accept(client, jid, worker="w1"):
    return client.post(f"/api/jobs/{jid}/accept", json={"worker_id": worker, "worker_email": f"{worker}@example.com"}).get_json()


def test_the_buyer_can_reject_a_worker_and_the_old_token_dies(app):
    plain = app.test_client(use_cookies=False)
    created = post_job(plain).get_json()
    jid, buyer = created["job"]["job_id"], created["token"]
    first = accept(plain, jid, "griefer")["token"]
    assert plain.post(f"/api/jobs/{jid}/reject-worker", headers=auth(first)).status_code == 403  # a worker cannot reject itself via the buyer route
    assert plain.post(f"/api/jobs/{jid}/reject-worker", headers=auth(buyer)).status_code == 200
    assert plain.get(f"/api/jobs/{jid}").get_json()["state"] == "POSTED"
    second = accept(plain, jid, "honest")["token"]
    plain.post(f"/api/jobs/{jid}/escrow", headers=auth(buyer))
    plain.get(f"/escrow/success?job_id={jid}")
    assert plain.post(f"/api/jobs/{jid}/run", json={"persona": "honest"}, headers=auth(first)).status_code == 403  # released seat
    assert plain.post(f"/api/jobs/{jid}/run", json={"persona": "honest"}, headers=auth(second)).status_code == 202


def test_a_worker_can_withdraw_before_funding(app):
    plain = app.test_client(use_cookies=False)
    created = post_job(plain).get_json()
    jid = created["job"]["job_id"]
    token = accept(plain, jid)["token"]
    assert plain.post(f"/api/jobs/{jid}/withdraw", headers=auth(token)).status_code == 200
    assert plain.get(f"/api/jobs/{jid}").get_json()["state"] == "POSTED"
    assert plain.post(f"/api/jobs/{jid}/withdraw", headers=auth(token)).status_code in (403, 409)


def test_release_is_impossible_once_funds_are_pending(app):
    plain = app.test_client(use_cookies=False)
    created = post_job(plain).get_json()
    jid, buyer = created["job"]["job_id"], created["token"]
    accept(plain, jid)
    plain.post(f"/api/jobs/{jid}/escrow", headers=auth(buyer))
    assert plain.post(f"/api/jobs/{jid}/reject-worker", headers=auth(buyer)).status_code == 409


def test_a_released_workers_cookie_stops_working_too(app):
    buyer_browser, worker_browser = app.test_client(), app.test_client()
    jid = post_job(buyer_browser).get_json()["job"]["job_id"]
    accept(worker_browser, jid)
    assert worker_browser.get(f"/api/jobs/{jid}").get_json()["viewer"]["roles"] == ["worker"]
    buyer_browser.post(f"/api/jobs/{jid}/reject-worker")
    assert worker_browser.get(f"/api/jobs/{jid}").get_json()["viewer"]["roles"] == []
