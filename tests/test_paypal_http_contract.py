"""The REAL PayPalClient, MCP server and orchestrator against a strict fake PayPal over real HTTP sockets."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from agentescrow.api.app import create_app
from agentescrow.api.runner import AsyncRunner
from agentescrow.arbiter.semantic_judge import StaticSemanticJudge
from agentescrow.domain.models import JobState, Outcome, utc_now
from agentescrow.orchestrator.endpoints import inprocess_endpoints
from agentescrow.orchestrator.service import EscrowService
from agentescrow.orchestrator.store import JobStore
from agentescrow.paypal.client import PayPalClient
from agentescrow.paypal.errors import PayPalError
from tests.fakes.paypal_server import FakePayPal


@pytest.fixture
def fake():
    server = FakePayPal().start()
    yield server
    server.stop()


@pytest.fixture
def client(fake):
    return PayPalClient("client-id", "client-secret", fake.url, allow_live=True)  # allow_live only because the fake is not *.sandbox.paypal.com


def order(client, request_id="order-1", amount="5.00"):
    return client.create_authorize_order(amount=Decimal(amount), reference_id="job_1", description="d", return_url="http://app/return", cancel_url="http://app/cancel", request_id=request_id)


# ------------------------------------------------------------------- the client --
def test_the_full_lifecycle_over_real_http(fake, client):
    created = order(client)
    assert created["approve_url"].startswith(fake.url) and created["status"] == "PAYER_ACTION_REQUIRED"
    with pytest.raises(PayPalError) as early:
        client.authorize_order(created["order_id"], request_id="authorize-1")
    assert "ORDER_NOT_APPROVED" in early.value.issues and early.value.status_code == 422 and early.value.debug_id
    fake.approve(created["order_id"])
    auth = client.authorize_order(created["order_id"], request_id="authorize-1")
    assert auth["authorization_status"] == "CREATED"
    assert client.get_authorization(auth["authorization_id"])["status"] == "CREATED"
    capture = client.capture_authorization(auth["authorization_id"], amount=Decimal("3.96"), invoice_id="AE-job_1", request_id="capture-1")
    assert capture["status"] == "COMPLETED" and fake.captures[capture["capture_id"]]["amount"] == Decimal("3.96")
    assert client.get_authorization(auth["authorization_id"])["status"] == "CAPTURED"  # final_capture closes it, releasing the rest
    payout = client.create_payout(receiver_email="w@example.com", amount=Decimal("3.70"), sender_batch_id="batch_job_1", sender_item_id="item_job_1", note="n", email_subject="s")
    assert payout["batch_status"] == "PENDING"


def test_requests_have_exactly_the_documented_shapes(fake, client):
    created = order(client)
    fake.approve(created["order_id"])
    auth = client.authorize_order(created["order_id"], request_id="authorize-1")
    client.capture_authorization(auth["authorization_id"], amount=Decimal("5"), invoice_id="AE-job_1", request_id="capture-1")
    client.create_payout(receiver_email="w@example.com", amount=Decimal("4.67"), sender_batch_id="b1", sender_item_id="i1", note="n", email_subject="s")
    create = fake.calls("POST", "/v2/checkout/orders")[0]
    assert create["body"]["intent"] == "AUTHORIZE" and "application_context" not in create["body"]
    assert create["headers"]["Paypal-Request-Id"] == "order-1" and create["headers"]["Authorization"].startswith("Bearer ")
    cap = fake.calls("POST", "/v2/payments/authorizations/")[0]
    assert cap["body"] == {"amount": {"value": "5.00", "currency_code": "USD"}, "invoice_id": "AE-job_1", "final_capture": True}
    payout = fake.calls("POST", "/v1/payments/payouts")[0]["body"]
    assert payout["items"][0]["amount"] == {"value": "4.67", "currency": "USD"}  # `currency`, not `currency_code`


def test_the_fake_itself_rejects_the_payouts_mistake_the_original_spec_made(fake, client):
    import requests

    token = client._access_token()  # noqa: SLF001
    bad = {"sender_batch_header": {"sender_batch_id": "x"}, "items": [{"recipient_type": "EMAIL", "receiver": "a@b.co", "amount": {"value": "1.00", "currency_code": "USD"}}]}
    response = requests.post(f"{fake.url}/v1/payments/payouts", json=bad, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert response.status_code == 400 and "currency" in response.json()["message"]


def test_idempotency_keys_make_retries_safe(fake, client):
    first, again = order(client, "order-A"), order(client, "order-A")
    assert first["order_id"] == again["order_id"] and len(fake.orders) == 1
    fake.approve(first["order_id"])
    auth = client.authorize_order(first["order_id"], request_id="authorize-A")
    assert client.authorize_order(first["order_id"], request_id="authorize-A")["authorization_id"] == auth["authorization_id"]
    one = client.capture_authorization(auth["authorization_id"], amount=Decimal("2"), invoice_id="i", request_id="capture-A", final_capture=False)
    two = client.capture_authorization(auth["authorization_id"], amount=Decimal("2"), invoice_id="i", request_id="capture-A", final_capture=False)
    assert one["capture_id"] == two["capture_id"] and len(fake.captures) == 1  # a retry never double-charges


def test_a_payout_batch_id_cannot_be_reused(fake, client):
    kwargs = dict(receiver_email="w@example.com", amount=Decimal("1"), sender_batch_id="batch_dup", sender_item_id="i", note="n", email_subject="s")
    client.create_payout(**kwargs)
    with pytest.raises(PayPalError, match="Duplicate"):
        client.create_payout(**kwargs)


def test_money_arithmetic_is_enforced_by_the_server_and_surfaced(fake, client):
    created = order(client)
    fake.approve(created["order_id"])
    auth = client.authorize_order(created["order_id"], request_id="a")
    with pytest.raises(PayPalError) as over:
        client.capture_authorization(auth["authorization_id"], amount=Decimal("5.01"), invoice_id="i", request_id="c1")
    assert "MAX_CAPTURE_AMOUNT_EXCEEDED" in over.value.issues


def test_an_expired_token_is_refreshed_transparently(fake, client):
    order(client, "o1")
    fake.expire_tokens()  # the server forgets every token
    assert order(client, "o2")["order_id"]
    assert len(fake.calls("POST", "/v1/oauth2/token")) == 2


def test_wrong_credentials_fail_clearly(fake):
    bad = PayPalClient("client-id", "WRONG", fake.url, allow_live=True)
    with pytest.raises(PayPalError, match="Authentication failed"):
        order(bad)


def test_void_is_idempotent_and_blocked_after_capture(fake, client):
    created = order(client)
    fake.approve(created["order_id"])
    auth = client.authorize_order(created["order_id"], request_id="a")
    assert client.void_authorization(auth["authorization_id"], request_id="v1")["voided"]
    assert client.void_authorization(auth["authorization_id"], request_id="v2")["voided"]
    other = order(client, "order-2")
    fake.approve(other["order_id"])
    captured = client.authorize_order(other["order_id"], request_id="a2")
    client.capture_authorization(captured["authorization_id"], amount=Decimal("5"), invoice_id="i", request_id="c")
    with pytest.raises(PayPalError):
        client.void_authorization(captured["authorization_id"], request_id="v3")


def test_reauthorize_returns_a_new_authorization(fake, client):
    created = order(client)
    fake.approve(created["order_id"])
    auth = client.authorize_order(created["order_id"], request_id="a")
    fresh = client.reauthorize_authorization(auth["authorization_id"], amount=Decimal("5.00"), request_id="r1")
    assert fresh["authorization_id"] != auth["authorization_id"] and client.get_authorization(fresh["authorization_id"])["status"] == "CREATED"
    assert fake.authorizations[auth["authorization_id"]]["status"] == "REAUTHORIZED"


def test_webhook_signatures_cover_the_raw_bytes(fake, client):
    raw = '{"id":"WH-1",   "event_type":"CHECKOUT.ORDER.APPROVED",  "resource":{"id":"X"}}'  # irregular spacing must survive
    headers = {"PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://x", "PAYPAL-TRANSMISSION-ID": "t", "PAYPAL-TRANSMISSION-TIME": "2026-10-09T00:00:00Z", "PAYPAL-TRANSMISSION-SIG": fake.sign_webhook(raw, "WHID")}
    assert client.verify_webhook_signature(headers, raw.encode(), "WHID") is True
    assert client.verify_webhook_signature({**headers, "PAYPAL-TRANSMISSION-SIG": "forged"}, raw.encode(), "WHID") is False
    assert client.verify_webhook_signature(headers, raw.replace("X", "Y").encode(), "WHID") is False  # any change to the event is detected


# -------------------------------------------------- the whole system on top of it --
@pytest.fixture
def stack(settings, fake, client):
    real = replace(settings, paypal_mode="sandbox", paypal_webhook_id="WHID", paypal_base_url=fake.url)
    runner = AsyncRunner()
    service = EscrowService(real, JobStore(real.database_path), inprocess_endpoints(real, client), StaticSemanticJudge(0.9))
    yield real, service, runner
    runner.stop()


async def funded(service, fake):
    job = await service.post_job(Decimal("5.00"))
    await service.accept_job(job.job_id, "w1", "w@example.com")
    job = await service.open_escrow(job.job_id)
    fake.approve(job.order_id)
    return await service.confirm_funding(job.job_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(("persona", "state", "outcome"), [("honest", JobState.SETTLED, Outcome.FULL), ("sloppy", JobState.SETTLED, Outcome.PARTIAL), ("cheater", JobState.VOIDED, Outcome.VOID)])
async def test_the_orchestrator_moves_exactly_the_right_money(stack, fake, persona, state, outcome):
    _, service, _ = stack
    job = await service.run_pipeline((await funded(service, fake)).job_id, persona)
    assert job.state == state and job.decision.outcome == outcome
    captured = sum(c["amount"] for c in fake.captures.values())
    payouts = [Decimal(p["items"][0]["amount"]["value"]) for p in fake.payouts.values()]
    if outcome == Outcome.VOID:
        assert captured == 0 and payouts == [] and fake.authorizations[job.authorization_id]["status"] == "VOIDED"
    else:
        assert captured == job.decision.capture_amount and payouts == [job.decision.worker_payout]
        assert job.decision.capture_amount == job.decision.platform_fee + job.decision.worker_payout


@pytest.mark.asyncio
async def test_a_stale_hold_is_reauthorized_before_capture_over_real_http(stack, fake):
    _, service, _ = stack
    job = await funded(service, fake)
    await service.run_worker(job.job_id, "honest")
    await service.arbitrate(job.job_id)
    aged = service.get_job(job.job_id)
    aged.locked_at = utc_now() - timedelta(days=4)
    service._store.save(aged, expected_state=aged.state)  # noqa: SLF001
    settled = await service.settle(job.job_id)
    assert settled.state == JobState.SETTLED and settled.authorization_id != job.authorization_id
    assert fake.authorizations[job.authorization_id]["status"] == "REAUTHORIZED"
    assert list(fake.captures.values())[0]["authorization"] == settled.authorization_id


@pytest.mark.asyncio
async def test_webhooks_with_real_verification_lock_the_funds(stack, fake):
    settings, service, runner = stack
    client = create_app(settings, service, runner).test_client(use_cookies=False)
    job = await service.post_job(Decimal("5.00"))
    await service.accept_job(job.job_id, "w", "w@example.com")
    job = await service.open_escrow(job.job_id)
    fake.approve(job.order_id)
    raw = json.dumps({"id": "WH-EVT-1", "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": job.order_id}})
    headers = {"Content-Type": "application/json", "PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://x", "PAYPAL-TRANSMISSION-ID": "t1", "PAYPAL-TRANSMISSION-TIME": "2026-10-09T00:00:00Z"}
    forged = client.post("/api/webhooks/paypal", data=raw, headers={**headers, "PAYPAL-TRANSMISSION-SIG": "forged"})
    assert forged.status_code == 401 and service.get_job(job.job_id).state == JobState.FUNDS_PENDING
    genuine = client.post("/api/webhooks/paypal", data=raw, headers={**headers, "PAYPAL-TRANSMISSION-SIG": fake.sign_webhook(raw, "WHID")})
    assert genuine.status_code == 200
    deadline = time.time() + 15
    while service.get_job(job.job_id).state != JobState.ESCROW_LOCKED and time.time() < deadline:
        time.sleep(0.1)
    assert service.get_job(job.job_id).state == JobState.ESCROW_LOCKED
