"""Thin, well-logged client for the PayPal REST APIs used by AgentEscrow.

Endpoints (checked against the PayPal developer documentation):

* ``POST /v1/oauth2/token``                                   client-credentials token
* ``POST /v2/checkout/orders``                                create order (intent AUTHORIZE)
* ``GET  /v2/checkout/orders/{id}``                           show order
* ``POST /v2/checkout/orders/{id}/authorize``                 authorize an APPROVED order
* ``GET  /v2/payments/authorizations/{id}``                   show authorization
* ``POST /v2/payments/authorizations/{id}/capture``           capture (full or partial)
* ``POST /v2/payments/authorizations/{id}/void``              void (release the hold)
* ``POST /v2/payments/authorizations/{id}/reauthorize``       refresh a hold after the 3-day honor period
* ``POST /v1/payments/payouts``                               pay the worker
* ``POST /v1/notifications/verify-webhook-signature``         verify an incoming webhook

Design rules:
* Refuses to talk to anything but the sandbox unless ``allow_live`` is set.
* Every state-changing call carries a ``PayPal-Request-Id`` so retries are idempotent.
* Money is passed as ``Decimal`` and formatted to 2 decimals.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from decimal import Decimal
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import requests

from agentescrow.money import money_str
from agentescrow.paypal.errors import PayPalError

logger = logging.getLogger(__name__)

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
_TOKEN_EXPIRY_MARGIN_S = 60


class PayPalClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = SANDBOX_BASE_URL,
        *,
        allow_live: bool = False,
        timeout_s: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        host = urlparse(base_url).hostname or ""
        if not allow_live and "sandbox" not in host:
            raise PayPalError(
                f"Refusing to use non-sandbox PayPal host {host!r}. "
                "Set ALLOW_LIVE_PAYPAL=true only if you really intend to move real money."
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._session = session or requests.Session()
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    # ------------------------------------------------------------------ auth ----
    def _access_token(self, *, force_refresh: bool = False) -> str:
        with self._token_lock:
            if not force_refresh and self._token and time.monotonic() < self._token_expires_at:
                return self._token
            logger.info("Requesting PayPal access token")
            try:
                response = self._session.post(
                    f"{self._base_url}/v1/oauth2/token",
                    data={"grant_type": "client_credentials"},
                    auth=(self._client_id, self._client_secret),
                    headers={"Accept": "application/json"},
                    timeout=self._timeout_s,
                )
            except requests.RequestException as exc:
                raise PayPalError(f"Could not reach PayPal: {exc}", name="NETWORK_ERROR") from exc
            if response.status_code != 200:
                raise self._to_error(response)
            body = response.json()
            self._token = body["access_token"]
            self._token_expires_at = time.monotonic() + int(body.get("expires_in", 300)) - _TOKEN_EXPIRY_MARGIN_S
            return self._token

    # --------------------------------------------------------------- plumbing ---
    @staticmethod
    def _to_error(response: requests.Response) -> PayPalError:
        debug_id = response.headers.get("PayPal-Debug-Id", "")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        details = body.get("details") or []
        issues = [d.get("issue", "") for d in details if isinstance(d, dict)]
        return PayPalError(
            body.get("message") or body.get("error_description") or response.text[:200],
            status_code=response.status_code,
            name=body.get("name") or body.get("error", ""),
            debug_id=body.get("debug_id") or debug_id,
            issues=[issue for issue in issues if issue],
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        request_id: str | None = None,
        prefer_representation: bool = False,
        raw_json: str | None = None,
    ) -> dict[str, Any]:
        """Send one authenticated request and return the parsed JSON body ({} if empty).

        ``raw_json`` sends a pre-serialized body byte-for-byte (needed for webhook verification).
        """
        for attempt in (1, 2):
            headers = {
                "Authorization": f"Bearer {self._access_token(force_refresh=attempt == 2)}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            if request_id:
                headers["PayPal-Request-Id"] = request_id
            if prefer_representation:
                headers["Prefer"] = "return=representation"
            started = time.monotonic()
            try:
                body_args: dict[str, Any] = {"data": raw_json.encode("utf-8")} if raw_json is not None else {"json": json_body}
                response = self._session.request(
                    method, f"{self._base_url}{path}", headers=headers, timeout=self._timeout_s, **body_args
                )
            except requests.RequestException as exc:
                raise PayPalError(f"Could not reach PayPal: {exc}", name="NETWORK_ERROR") from exc

            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "PayPal %s %s -> %s in %sms (debug_id=%s)",
                method,
                path,
                response.status_code,
                elapsed_ms,
                response.headers.get("PayPal-Debug-Id", "-"),
            )
            if response.status_code == 401 and attempt == 1:
                logger.warning("PayPal returned 401; refreshing token and retrying once")
                continue
            if response.status_code >= 400:
                raise self._to_error(response)
            if response.status_code == 204 or not response.content:
                return {}
            return response.json()
        raise PayPalError("Authentication failed after token refresh", status_code=401)  # pragma: no cover

    # -------------------------------------------------------------- summaries ---
    @staticmethod
    def _first_authorization(order: dict[str, Any]) -> dict[str, Any]:
        for unit in order.get("purchase_units", []):
            authorizations = (unit.get("payments") or {}).get("authorizations") or []
            if authorizations:
                return authorizations[0]
        return {}

    @classmethod
    def _summarize_order(cls, order: dict[str, Any]) -> dict[str, Any]:
        authorization = cls._first_authorization(order)
        return {
            "order_id": order.get("id", ""),
            "status": order.get("status", ""),
            "authorization_id": authorization.get("id"),
            "authorization_status": authorization.get("status"),
            "amount": authorization.get("amount"),
        }

    # ------------------------------------------------------------------ orders --
    def create_authorize_order(
        self,
        *,
        amount: Decimal,
        reference_id: str,
        description: str,
        return_url: str,
        cancel_url: str,
        request_id: str,
        currency: str = "USD",
    ) -> dict[str, Any]:
        """Create an order with ``intent=AUTHORIZE``. The buyer must still approve it.

        ``application_context`` is deprecated by PayPal; the redirect URLs live in
        ``payment_source.paypal.experience_context`` instead.
        """
        payload = {
            "intent": "AUTHORIZE",
            "purchase_units": [
                {
                    "reference_id": reference_id[:256],
                    "description": description[:127],
                    "amount": {"currency_code": currency, "value": money_str(amount)},
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": "AgentEscrow",
                        "shipping_preference": "NO_SHIPPING",
                        "user_action": "PAY_NOW",
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                    }
                }
            },
        }
        order = self._request("POST", "/v2/checkout/orders", json_body=payload, request_id=request_id)
        links = {link.get("rel"): link.get("href") for link in order.get("links", [])}
        approve_url = links.get("payer-action") or links.get("approve") or ""
        if not approve_url:
            raise PayPalError("PayPal did not return an approval link for the order", name="MISSING_APPROVE_LINK")
        logger.info("Created PayPal order %s for %s %s", order.get("id"), money_str(amount), currency)
        return {"order_id": order["id"], "status": order.get("status", ""), "approve_url": approve_url}

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._summarize_order(self._request("GET", f"/v2/checkout/orders/{order_id}"))

    def authorize_order(self, order_id: str, *, request_id: str) -> dict[str, Any]:
        """Place the hold on the buyer's funds. The order must be in status APPROVED."""
        order = self._request(
            "POST",
            f"/v2/checkout/orders/{order_id}/authorize",
            json_body={},
            request_id=request_id,
            prefer_representation=True,
        )
        summary = self._summarize_order(order)
        if not summary["authorization_id"]:
            raise PayPalError("Order was authorized but no authorization id was returned", name="MISSING_AUTHORIZATION")
        logger.info("Authorized order %s -> authorization %s", order_id, summary["authorization_id"])
        return summary

    # --------------------------------------------------------- authorizations ---
    def get_authorization(self, authorization_id: str) -> dict[str, Any]:
        auth = self._request("GET", f"/v2/payments/authorizations/{authorization_id}")
        return {
            "authorization_id": auth.get("id", authorization_id),
            "status": auth.get("status", ""),
            "amount": auth.get("amount"),
            "expiration_time": auth.get("expiration_time"),
        }

    def capture_authorization(
        self,
        authorization_id: str,
        *,
        amount: Decimal,
        invoice_id: str,
        request_id: str,
        final_capture: bool = True,
        currency: str = "USD",
    ) -> dict[str, Any]:
        """Capture ``amount`` (<= the authorized amount). ``final_capture`` closes the authorization."""
        payload = {
            "amount": {"value": money_str(amount), "currency_code": currency},
            "invoice_id": invoice_id[:127],
            "final_capture": final_capture,
        }
        capture = self._request(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/capture",
            json_body=payload,
            request_id=request_id,
            prefer_representation=True,
        )
        logger.info(
            "Captured %s %s on authorization %s (capture=%s status=%s final=%s)",
            money_str(amount),
            currency,
            authorization_id,
            capture.get("id"),
            capture.get("status"),
            final_capture,
        )
        return {
            "capture_id": capture.get("id", ""),
            "status": capture.get("status", ""),
            "amount": capture.get("amount"),
            "final_capture": capture.get("final_capture", final_capture),
        }

    def void_authorization(self, authorization_id: str, *, request_id: str) -> dict[str, Any]:
        """Release the hold. The buyer is not charged."""
        self._request("POST", f"/v2/payments/authorizations/{authorization_id}/void", request_id=request_id)
        logger.info("Voided authorization %s", authorization_id)
        return {"authorization_id": authorization_id, "voided": True}

    def reauthorize_authorization(
        self, authorization_id: str, *, amount: Decimal, request_id: str, currency: str = "USD"
    ) -> dict[str, Any]:
        """Refresh a hold once its 3-day honor period is over (allowed within the 29-day window).

        PayPal returns a NEW authorization id with a fresh honor period; callers must switch to it.
        """
        body = self._request(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/reauthorize",
            json_body={"amount": {"value": money_str(amount), "currency_code": currency}},
            request_id=request_id,
            prefer_representation=True,
        )
        new_id = body.get("id") or authorization_id
        logger.info("Reauthorized %s -> %s (status %s)", authorization_id, new_id, body.get("status"))
        return {"authorization_id": new_id, "previous_authorization_id": authorization_id, "status": body.get("status", "")}

    # ---------------------------------------------------------------- webhooks --
    def verify_webhook_signature(self, headers: Mapping[str, str], raw_body: bytes, webhook_id: str) -> bool:
        """Ask PayPal whether this webhook is genuine. Returns True only for ``verification_status == SUCCESS``.

        The event is embedded **exactly as received** (not re-serialized): the signature covers the raw bytes.
        """
        names = {
            "auth_algo": "PAYPAL-AUTH-ALGO",
            "cert_url": "PAYPAL-CERT-URL",
            "transmission_id": "PAYPAL-TRANSMISSION-ID",
            "transmission_sig": "PAYPAL-TRANSMISSION-SIG",
            "transmission_time": "PAYPAL-TRANSMISSION-TIME",
        }
        values = {key: headers.get(header) for key, header in names.items()}
        missing = [names[key] for key, value in values.items() if not value]
        if missing:
            logger.warning("Webhook is missing signature headers: %s", missing)
            return False
        try:
            event_text = raw_body.decode("utf-8")
            json.loads(event_text)
        except (UnicodeDecodeError, ValueError):
            logger.warning("Webhook body is not valid JSON")
            return False
        head = ",".join(f"{json.dumps(key)}:{json.dumps(value)}" for key, value in {**values, "webhook_id": webhook_id}.items())
        body = self._request(
            "POST", "/v1/notifications/verify-webhook-signature", raw_json=f'{{{head},"webhook_event":{event_text}}}'
        )
        verified = body.get("verification_status") == "SUCCESS"
        logger.info("Webhook signature verification: %s", body.get("verification_status"))
        return verified

    # ----------------------------------------------------------------- payouts --
    def create_payout(
        self,
        *,
        receiver_email: str,
        amount: Decimal,
        sender_batch_id: str,
        sender_item_id: str,
        note: str,
        email_subject: str,
        currency: str = "USD",
    ) -> dict[str, Any]:
        """Pay the worker.

        NOTE: Payouts v1 uses ``currency`` (not ``currency_code``) inside ``amount``.
        PayPal rejects a ``sender_batch_id`` used in the last 30 days, which makes this
        call safe to retry.
        """
        payload = {
            "sender_batch_header": {
                "sender_batch_id": sender_batch_id,
                "email_subject": email_subject[:255],
                "email_message": note[:1000],
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "receiver": receiver_email,
                    "amount": {"value": money_str(amount), "currency": currency},
                    "note": note[:4000],
                    "sender_item_id": sender_item_id,
                }
            ],
        }
        body = self._request("POST", "/v1/payments/payouts", json_body=payload)
        header = body.get("batch_header", {})
        logger.info(
            "Created payout batch %s (status=%s) of %s %s",
            header.get("payout_batch_id"),
            header.get("batch_status"),
            money_str(amount),
            currency,
        )
        return {"payout_batch_id": header.get("payout_batch_id", ""), "batch_status": header.get("batch_status", "")}
