"""A strict fake of the PayPal REST endpoints AgentEscrow uses, served over real HTTP.

It enforces the request shapes from PayPal's documentation (for example Payouts `amount.currency`, not `currency_code`;
Orders `payment_source.paypal.experience_context`, not the deprecated `application_context`), idempotency via
`PayPal-Request-Id`, authorization/capture arithmetic, token expiry, and webhook signatures computed over the RAW event bytes.
It records every request so tests can assert on exactly what the client sent. It is a test double, not PayPal.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import itertools
import json
import re
import threading
from decimal import Decimal

from flask import Flask, jsonify, request
from werkzeug.serving import make_server

AMOUNT = re.compile(r"^\d+\.\d{2}$")


def _error(status, name, message, issue=None):
    body = {"name": name, "message": message, "debug_id": f"debug-{status}"}
    if issue:
        body["details"] = [{"issue": issue}]
    response = jsonify(body)
    response.status_code = status
    response.headers["PayPal-Debug-Id"] = body["debug_id"]
    return response


class FakePayPal:
    def __init__(self, client_id="client-id", client_secret="client-secret", webhook_secret="whsec"):
        self.client_id, self.client_secret, self.webhook_secret = client_id, client_secret, webhook_secret
        self.requests: list[dict] = []
        self.orders: dict[str, dict] = {}
        self.authorizations: dict[str, dict] = {}
        self.captures: dict[str, dict] = {}
        self.payouts: dict[str, dict] = {}
        self.tokens: set[str] = set()
        self._ids = itertools.count(1)
        self._replays: dict[str, tuple] = {}
        self._lock = threading.RLock()
        self.app = Flask("fake-paypal")
        self._routes()
        self._server = None

    # ----------------------------------------------------------------------- lifecycle --
    def start(self) -> "FakePayPal":
        self._server = make_server("127.0.0.1", 0, self.app, threaded=True)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    # --------------------------------------------------------------------- test hooks --
    def approve(self, order_id: str) -> None:
        self.orders[order_id]["status"] = "APPROVED"

    def expire_tokens(self) -> None:
        self.tokens.clear()

    def sign_webhook(self, raw_event: str, webhook_id: str) -> str:
        """The signature the fake accepts: HMAC over webhook id + the raw event text."""
        return hmac.new(self.webhook_secret.encode(), f"{webhook_id}|{raw_event}".encode(), hashlib.sha256).hexdigest()

    def calls(self, method: str, path_prefix: str) -> list[dict]:
        return [r for r in self.requests if r["method"] == method and r["path"].startswith(path_prefix)]

    # ----------------------------------------------------------------------------- impl --
    def _new_id(self, prefix):
        return f"{prefix}-{next(self._ids):06d}"

    def _auth_ok(self):
        header = request.headers.get("Authorization", "")
        return header.startswith("Bearer ") and header[7:] in self.tokens

    def _idempotent(self, key_prefix, build):
        """Replay the first response for a repeated PayPal-Request-Id (as PayPal does)."""
        request_id = request.headers.get("PayPal-Request-Id")
        if request_id and (key_prefix, request_id) in self._replays:
            body, status = self._replays[(key_prefix, request_id)]
            return jsonify(body), status
        result = build()
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], dict):
            if request_id:
                self._replays[(key_prefix, request_id)] = result
            return jsonify(result[0]), result[1]
        return result

    def _routes(self):
        app = self.app

        @app.before_request
        def _log_and_auth():
            raw = request.get_data()
            try:
                body = json.loads(raw) if raw and "json" in (request.content_type or "") else None
            except ValueError:
                body = None
            with self._lock:
                self.requests.append({"method": request.method, "path": request.path, "headers": dict(request.headers), "body": body, "raw": raw.decode("utf-8", "replace")})
            if request.path == "/v1/oauth2/token":
                return None
            if not self._auth_ok():
                return _error(401, "AUTHENTICATION_FAILURE", "Authentication failed due to invalid authentication credentials.")
            return None

        @app.post("/v1/oauth2/token")
        def token():
            expected = "Basic " + base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            if request.headers.get("Authorization") != expected:
                return _error(401, "invalid_client", "Client Authentication failed")
            if request.form.get("grant_type") != "client_credentials":
                return _error(400, "invalid_request", "grant_type must be client_credentials")
            value = self._new_id("token")
            self.tokens.add(value)
            return jsonify(access_token=value, token_type="Bearer", expires_in=3600)

        @app.post("/v2/checkout/orders")
        def create_order():
            def build():
                body = request.get_json()
                if "application_context" in body:
                    return _error(422, "INVALID_REQUEST", "application_context is deprecated; use payment_source.paypal.experience_context", "DEPRECATED_FIELD")
                if body.get("intent") != "AUTHORIZE":
                    return _error(422, "INVALID_REQUEST", "This escrow needs intent AUTHORIZE", "INVALID_INTENT")
                unit = body["purchase_units"][0]
                if unit["amount"].get("currency_code") != "USD" or not AMOUNT.match(unit["amount"]["value"]):
                    return _error(422, "INVALID_REQUEST", "Bad amount", "INVALID_AMOUNT")
                context = body["payment_source"]["paypal"]["experience_context"]
                order_id = self._new_id("ORDER")
                self.orders[order_id] = {"status": "PAYER_ACTION_REQUIRED", "amount": unit["amount"], "authorization": None, "return_url": context["return_url"]}
                return {"id": order_id, "status": "PAYER_ACTION_REQUIRED", "links": [{"rel": "payer-action", "href": f"{self.url}/checkoutnow?token={order_id}"}]}, 201

            return self._idempotent("order", build)

        @app.get("/v2/checkout/orders/<order_id>")
        def show_order(order_id):
            order = self.orders.get(order_id)
            if not order:
                return _error(404, "RESOURCE_NOT_FOUND", "Order not found", "INVALID_RESOURCE_ID")
            return jsonify(self._order_view(order_id))

        def _authorize(order_id):
            order = self.orders.get(order_id)
            if not order:
                return _error(404, "RESOURCE_NOT_FOUND", "Order not found", "INVALID_RESOURCE_ID")
            if order["authorization"]:
                return _error(422, "UNPROCESSABLE_ENTITY", "Order already authorized", "ORDER_ALREADY_AUTHORIZED")
            if order["status"] != "APPROVED":
                return _error(422, "UNPROCESSABLE_ENTITY", "Order not approved by the payer", "ORDER_NOT_APPROVED")
            authorization_id = self._new_id("AUTH")
            self.authorizations[authorization_id] = {"status": "CREATED", "amount": order["amount"], "captured": Decimal("0.00"), "order": order_id}
            order["authorization"], order["status"] = authorization_id, "COMPLETED"
            return self._order_view(order_id), 201

        @app.post("/v2/checkout/orders/<order_id>/authorize")
        def authorize(order_id):
            return self._idempotent(f"authorize-{order_id}", lambda: _authorize(order_id))

        @app.get("/v2/payments/authorizations/<authorization_id>")
        def show_authorization(authorization_id):
            auth = self.authorizations.get(authorization_id)
            if not auth:
                return _error(404, "RESOURCE_NOT_FOUND", "Authorization not found", "INVALID_RESOURCE_ID")
            return jsonify({"id": authorization_id, "status": auth["status"], "amount": auth["amount"], "expiration_time": "2099-01-01T00:00:00Z"})

        @app.post("/v2/payments/authorizations/<authorization_id>/capture")
        def capture(authorization_id):
            def build():
                auth = self.authorizations.get(authorization_id)
                if not auth:
                    return _error(404, "RESOURCE_NOT_FOUND", "Authorization not found", "INVALID_RESOURCE_ID")
                if auth["status"] not in {"CREATED", "PARTIALLY_CAPTURED"}:
                    return _error(422, "UNPROCESSABLE_ENTITY", f"Authorization is {auth['status']}", "AUTHORIZATION_CLOSED")
                body = request.get_json()
                amount = body.get("amount", {})
                if not AMOUNT.match(amount.get("value", "")) or amount.get("currency_code") != "USD":
                    return _error(422, "INVALID_REQUEST", "Bad capture amount", "INVALID_AMOUNT")
                if not isinstance(body.get("final_capture"), bool) or len(body.get("invoice_id", "")) > 127:
                    return _error(422, "INVALID_REQUEST", "Bad capture fields", "INVALID_PARAMETER_VALUE")
                value = Decimal(amount["value"])
                if auth["captured"] + value > Decimal(auth["amount"]["value"]):
                    return _error(422, "UNPROCESSABLE_ENTITY", "Capture exceeds the authorized amount", "MAX_CAPTURE_AMOUNT_EXCEEDED")
                auth["captured"] += value
                auth["status"] = "CAPTURED" if body["final_capture"] else "PARTIALLY_CAPTURED"
                capture_id = self._new_id("CAP")
                self.captures[capture_id] = {"authorization": authorization_id, "amount": value, "invoice_id": body["invoice_id"]}
                return {"id": capture_id, "status": "COMPLETED", "amount": amount, "final_capture": body["final_capture"], "invoice_id": body["invoice_id"]}, 201

            return self._idempotent(f"capture-{authorization_id}", build)

        @app.post("/v2/payments/authorizations/<authorization_id>/void")
        def void(authorization_id):
            auth = self.authorizations.get(authorization_id)
            if not auth:
                return _error(404, "RESOURCE_NOT_FOUND", "Authorization not found", "INVALID_RESOURCE_ID")
            if auth["status"] == "VOIDED":
                return "", 204  # idempotent
            if auth["status"] != "CREATED":
                return _error(422, "UNPROCESSABLE_ENTITY", f"Cannot void a {auth['status']} authorization", "PREVIOUSLY_CAPTURED")
            auth["status"] = "VOIDED"
            return "", 204

        @app.post("/v2/payments/authorizations/<authorization_id>/reauthorize")
        def reauthorize(authorization_id):
            def build():
                auth = self.authorizations.get(authorization_id)
                if not auth or auth["status"] != "CREATED":
                    return _error(422, "UNPROCESSABLE_ENTITY", "Authorization cannot be reauthorized", "REAUTHORIZATION_NOT_ALLOWED")
                amount = request.get_json().get("amount", {})
                if not AMOUNT.match(amount.get("value", "")) or amount.get("currency_code") != "USD":
                    return _error(422, "INVALID_REQUEST", "Bad amount", "INVALID_AMOUNT")
                new_id = self._new_id("AUTH")
                self.authorizations[new_id] = {**auth, "amount": amount, "captured": Decimal("0.00"), "status": "CREATED"}
                auth["status"] = "REAUTHORIZED"
                return {"id": new_id, "status": "CREATED", "amount": amount}, 201

            return self._idempotent(f"reauthorize-{authorization_id}", build)

        @app.post("/v1/payments/payouts")
        def payouts():
            body = request.get_json()
            header, items = body.get("sender_batch_header", {}), body.get("items", [])
            batch_id = header.get("sender_batch_id")
            if not batch_id or not items:
                return _error(400, "MALFORMED_REQUEST", "sender_batch_header and items are required", "MALFORMED_REQUEST")
            for item in items:
                amount = item.get("amount", {})
                if "currency_code" in amount or "currency" not in amount:
                    return _error(400, "MALFORMED_REQUEST", "Payouts amounts use `currency`, not `currency_code`", "MALFORMED_REQUEST_JSON")
                if item.get("recipient_type") != "EMAIL" or "@" not in item.get("receiver", "") or not AMOUNT.match(amount.get("value", "")):
                    return _error(400, "MALFORMED_REQUEST", "Bad payout item", "MALFORMED_REQUEST_JSON")
            if batch_id in self.payouts:
                return _error(400, "USER_BUSINESS_ERROR", "Duplicate sender_batch_id", "BATCH_ALREADY_EXISTS")
            payout_id = self._new_id("PAYOUT")
            self.payouts[batch_id] = {"id": payout_id, "items": items}
            response = jsonify({"batch_header": {"payout_batch_id": payout_id, "batch_status": "PENDING", "sender_batch_header": header}})
            response.status_code = 201
            return response

        @app.post("/v1/notifications/verify-webhook-signature")
        def verify_webhook():
            raw = request.get_data(as_text=True)
            body = json.loads(raw)
            needed = ("auth_algo", "cert_url", "transmission_id", "transmission_sig", "transmission_time", "webhook_id", "webhook_event")
            if any(key not in body for key in needed):
                return _error(400, "INVALID_REQUEST", "Missing verification fields", "MISSING_FIELD")
            marker = '"webhook_event":'
            raw_event = raw[raw.index(marker) + len(marker) : raw.rindex("}")]  # exactly what the client embedded
            expected = self.sign_webhook(raw_event, body["webhook_id"])
            return jsonify(verification_status="SUCCESS" if hmac.compare_digest(body["transmission_sig"], expected) else "FAILURE")

    def _order_view(self, order_id):
        order = self.orders[order_id]
        view = {"id": order_id, "status": order["status"], "purchase_units": [{"amount": order["amount"]}]}
        if order["authorization"]:
            auth = self.authorizations[order["authorization"]]
            view["purchase_units"][0]["payments"] = {"authorizations": [{"id": order["authorization"], "status": auth["status"], "amount": auth["amount"]}]}
        return view
