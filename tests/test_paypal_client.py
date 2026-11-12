"""PayPalClient is tested against a fake HTTP session that asserts the documented payload shapes."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
import requests

from agentescrow.paypal.client import PayPalClient
from agentescrow.paypal.errors import PayPalError


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {"PayPal-Debug-Id": "dbg-1"}
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kw):  # token endpoint
        self.calls.append(("POST", url, kw))
        return self.responses.pop(0)

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.responses.pop(0)


TOKEN = FakeResponse(200, {"access_token": "tok", "expires_in": 3600})
BASE = "https://api-m.sandbox.paypal.com"


def client(*responses):
    session = FakeSession([TOKEN, *responses])
    return PayPalClient("id", "secret", session=session), session


def test_refuses_the_live_host_by_default():
    with pytest.raises(PayPalError, match="non-sandbox"):
        PayPalClient("i", "s", "https://api-m.paypal.com")
    PayPalClient("i", "s", "https://api-m.paypal.com", allow_live=True)  # explicit opt-in works


def test_create_order_uses_authorize_intent_and_experience_context():
    links = [{"rel": "payer-action", "href": "https://paypal.test/approve"}]
    c, s = client(FakeResponse(201, {"id": "ORD1", "status": "PAYER_ACTION_REQUIRED", "links": links}))
    out = c.create_authorize_order(
        amount=Decimal("75"), reference_id="job_1", description="d", return_url="http://r", cancel_url="http://c",
        request_id="order-job_1",
    )  # fmt: skip
    method, url, kw = s.calls[1]
    assert (method, url) == ("POST", f"{BASE}/v2/checkout/orders")
    body = kw["json"]
    assert body["intent"] == "AUTHORIZE"
    assert body["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "75.00"}
    assert body["payment_source"]["paypal"]["experience_context"]["return_url"] == "http://r"
    assert "application_context" not in body, "application_context is deprecated"
    assert kw["headers"]["PayPal-Request-Id"] == "order-job_1"
    assert out == {"order_id": "ORD1", "status": "PAYER_ACTION_REQUIRED", "approve_url": "https://paypal.test/approve"}


def test_create_order_falls_back_to_the_approve_link_and_errors_without_one():
    c, _ = client(FakeResponse(201, {"id": "O", "links": [{"rel": "approve", "href": "https://x/approve"}]}))
    assert c.create_authorize_order(
        amount=Decimal("1"), reference_id="j", description="d", return_url="r", cancel_url="c", request_id="r1"
    )["approve_url"] == "https://x/approve"  # fmt: skip
    c, _ = client(FakeResponse(201, {"id": "O", "links": []}))
    with pytest.raises(PayPalError, match="approval link"):
        c.create_authorize_order(amount=Decimal("1"), reference_id="j", description="d", return_url="r", cancel_url="c", request_id="r1")  # fmt: skip


def test_authorize_extracts_the_authorization_id():
    order = {"id": "ORD1", "status": "COMPLETED",
             "purchase_units": [{"payments": {"authorizations": [{"id": "AUTH1", "status": "CREATED", "amount": {"value": "75.00"}}]}}]}  # fmt: skip
    c, s = client(FakeResponse(201, order))
    out = c.authorize_order("ORD1", request_id="authorize-job_1")
    assert s.calls[1][1] == f"{BASE}/v2/checkout/orders/ORD1/authorize"
    assert out["authorization_id"] == "AUTH1" and out["authorization_status"] == "CREATED"


def test_capture_sends_amount_invoice_and_final_capture():
    c, s = client(FakeResponse(201, {"id": "CAP1", "status": "COMPLETED", "final_capture": True}))
    out = c.capture_authorization("AUTH1", amount=Decimal("45"), invoice_id="AE-job_1", request_id="capture-job_1")
    method, url, kw = s.calls[1]
    assert url == f"{BASE}/v2/payments/authorizations/AUTH1/capture"
    assert kw["json"] == {"amount": {"value": "45.00", "currency_code": "USD"}, "invoice_id": "AE-job_1", "final_capture": True}
    assert kw["headers"]["Prefer"] == "return=representation"
    assert out["capture_id"] == "CAP1"


def test_void_accepts_an_empty_204_response():
    c, s = client(FakeResponse(204, None))
    assert c.void_authorization("AUTH1", request_id="void-job_1") == {"authorization_id": "AUTH1", "voided": True}
    assert s.calls[1][1] == f"{BASE}/v2/payments/authorizations/AUTH1/void"


def test_payout_uses_currency_not_currency_code():
    c, s = client(FakeResponse(201, {"batch_header": {"payout_batch_id": "PB1", "batch_status": "PENDING"}}))
    out = c.create_payout(
        receiver_email="w@example.com", amount=Decimal("70"), sender_batch_id="batch_job_1",
        sender_item_id="item_job_1", note="n", email_subject="s",
    )  # fmt: skip
    body = s.calls[1][2]["json"]
    assert body["items"][0]["amount"] == {"value": "70.00", "currency": "USD"}
    assert body["sender_batch_header"]["sender_batch_id"] == "batch_job_1"
    assert out["payout_batch_id"] == "PB1"


def test_errors_carry_paypal_details():
    err = {"name": "UNPROCESSABLE_ENTITY", "message": "nope", "debug_id": "abc", "details": [{"issue": "AUTHORIZATION_EXPIRED"}]}
    c, _ = client(FakeResponse(422, err))
    with pytest.raises(PayPalError) as info:
        c.capture_authorization("A", amount=Decimal("1"), invoice_id="i", request_id="r")
    assert info.value.status_code == 422 and info.value.issues == ["AUTHORIZATION_EXPIRED"] and info.value.debug_id == "abc"


def test_a_401_refreshes_the_token_once_and_retries():
    c, s = client(FakeResponse(401, {"name": "AUTHENTICATION_FAILURE", "message": "x"}), TOKEN, FakeResponse(200, {"id": "A", "status": "CREATED"}))  # fmt: skip
    assert c.get_authorization("A")["status"] == "CREATED"
    assert len(s.calls) == 4  # token, call (401), token again, call


def test_network_failures_become_paypal_errors():
    class Boom(FakeSession):
        def request(self, *a, **k):
            raise requests.ConnectionError("down")

    c = PayPalClient("i", "s", session=Boom([TOKEN]))
    with pytest.raises(PayPalError, match="Could not reach PayPal"):
        c.get_order("O")


def test_reauthorize_posts_the_amount_and_returns_the_new_id():
    c, s = client(FakeResponse(201, {"id": "AUTH2", "status": "CREATED"}))
    out = c.reauthorize_authorization("AUTH1", amount=Decimal("5"), request_id="reauthorize-job_1")
    method, url, kw = s.calls[1]
    assert url == f"{BASE}/v2/payments/authorizations/AUTH1/reauthorize"
    assert kw["json"] == {"amount": {"value": "5.00", "currency_code": "USD"}}
    assert out == {"authorization_id": "AUTH2", "previous_authorization_id": "AUTH1", "status": "CREATED"}


WEBHOOK_HEADERS = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert",
    "PAYPAL-TRANSMISSION-ID": "tid-1", "PAYPAL-TRANSMISSION-SIG": "sig==", "PAYPAL-TRANSMISSION-TIME": "2026-10-04T10:00:00Z",
}  # fmt: skip


def test_webhook_verification_embeds_the_raw_event_untouched():
    c, s = client(FakeResponse(200, {"verification_status": "SUCCESS"}))
    raw = b'{"id":"WH-1",  "event_type":"CHECKOUT.ORDER.APPROVED","resource":{"id":"ORD1"}}'  # odd spacing must survive
    assert c.verify_webhook_signature(WEBHOOK_HEADERS, raw, "WHID") is True
    method, url, kw = s.calls[1]
    assert url == f"{BASE}/v1/notifications/verify-webhook-signature"
    sent = kw["data"].decode()
    assert raw.decode() in sent, "the event must be forwarded byte-for-byte"
    body = json.loads(sent)
    assert body["webhook_id"] == "WHID" and body["transmission_id"] == "tid-1" and body["auth_algo"] == "SHA256withRSA"


def test_webhook_verification_fails_closed():
    c, _ = client(FakeResponse(200, {"verification_status": "FAILURE"}))
    assert c.verify_webhook_signature(WEBHOOK_HEADERS, b"{}", "WHID") is False
    c, s = client()
    assert c.verify_webhook_signature({}, b"{}", "WHID") is False  # missing headers: PayPal is never even called
    assert len(s.calls) == 0
    c, s = client()
    assert c.verify_webhook_signature(WEBHOOK_HEADERS, b"not json", "WHID") is False
