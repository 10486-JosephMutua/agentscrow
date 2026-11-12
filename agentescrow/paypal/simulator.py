"""In-memory stand-in for :class:`PayPalClient`, for development, tests and offline demos.

By default state lives in memory only. Pass ``state_path`` to persist it to a JSON file: the job store
(SQLite) survives a restart, so the PayPal ids it holds must stay valid too, otherwise every job that was
mid-settlement when the server stopped fails with ``404 RESOURCE_NOT_FOUND`` forever.

It mimics the *behavior* AgentEscrow depends on (authorize -> capture/void -> payout, with
the same validation rules: capture <= authorized, no second capture, no capture after
void) but moves no money and talks to nothing. Everything it returns is flagged
``"simulated": True`` so a simulated receipt can never be mistaken for a real one.

Select it with ``PAYPAL_MODE=simulated``. The real demo and the submission video should
use ``PAYPAL_MODE=sandbox``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from agentescrow.money import money_str
from agentescrow.paypal.errors import PayPalError

logger = logging.getLogger(__name__)


def _new_id(prefix: str) -> str:
    return f"SIM-{prefix}-{uuid.uuid4().hex[:12].upper()}"


class SimulatedPayPalClient:
    """Drop-in replacement exposing the same public methods as ``PayPalClient``."""

    def __init__(self, *, auto_approve: bool = True, state_path: Path | str | None = None) -> None:
        """``auto_approve=False`` makes orders wait for :meth:`approve`, like a real buyer approval.

        ``state_path`` persists orders, authorizations, captures and idempotency records across restarts.
        """
        self._auto_approve = auto_approve
        self._state_path = Path(state_path) if state_path else None
        self._orders: dict[str, dict[str, Any]] = {}
        self._authorizations: dict[str, dict[str, Any]] = {}
        self._captures: dict[str, dict[str, Any]] = {}
        self._payout_batches: dict[str, str] = {}
        self._idempotent: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()
        logger.warning("PayPal SIMULATOR active: no real PayPal calls are made and no money moves")

    # -------------------------------------------------------------- persistence --
    def _load(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            authorizations = {
                key: {**value, "captured": Decimal(value["captured"])} for key, value in data["authorizations"].items()
            }
            self._orders, self._captures = dict(data["orders"]), dict(data["captures"])
            self._payout_batches, self._idempotent = dict(data["payout_batches"]), dict(data["idempotent"])
            self._authorizations = authorizations
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            # Never crash the server over a dev-only file, but never silently discard it either.
            broken = self._state_path.with_suffix(".corrupt")
            logger.error("Simulator state %s is unreadable (%s); starting empty, old file kept as %s", self._state_path, exc, broken)
            try:
                os.replace(self._state_path, broken)
            except OSError:
                pass
            self._orders, self._authorizations, self._captures = {}, {}, {}
            self._payout_batches, self._idempotent = {}, {}
            return
        logger.info(
            "Simulator state restored from %s (%d orders, %d authorizations)",
            self._state_path, len(self._orders), len(self._authorizations),
        )  # fmt: skip

    def _save(self) -> None:
        """Write the state atomically (temp file + rename) so a crash never leaves a half-written file. Callers hold the lock."""
        if self._state_path is None:
            return
        data = {
            "orders": self._orders,
            "authorizations": {k: {**v, "captured": str(v["captured"])} for k, v in self._authorizations.items()},
            "captures": self._captures,
            "payout_batches": self._payout_batches,
            "idempotent": self._idempotent,
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self._state_path)

    # ------------------------------------------------------------------ helpers --
    def _replay(self, key: str) -> dict[str, Any] | None:
        return self._idempotent.get(key)

    def _remember(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        self._idempotent[key] = value
        self._save()  # every state-changing call ends here, so one save covers the whole operation
        return value

    @staticmethod
    def _fail(status: int, name: str, message: str, issue: str) -> PayPalError:
        return PayPalError(message, status_code=status, name=name, debug_id="simulated", issues=[issue])

    # ------------------------------------------------------------------- orders --
    def create_authorize_order(
        self, *, amount: Decimal, reference_id: str, description: str, return_url: str, cancel_url: str,
        request_id: str, currency: str = "USD",
    ) -> dict[str, Any]:  # fmt: skip
        with self._lock:
            if (cached := self._replay(f"order:{request_id}")) is not None:
                return cached
            order_id = _new_id("ORDER")
            status = "APPROVED" if self._auto_approve else "CREATED"
            self._orders[order_id] = {"amount": money_str(amount), "currency": currency, "status": status}
            separator = "&" if "?" in return_url else "?"
            result = {
                "order_id": order_id,
                "status": "CREATED",
                "approve_url": f"{return_url}{separator}token={order_id}&simulated=1",
                "simulated": True,
            }
            logger.info("[sim] created order %s for %s %s (status %s)", order_id, money_str(amount), currency, status)
            return self._remember(f"order:{request_id}", result)

    def approve(self, order_id: str) -> None:
        """Simulate the buyer approving the order in PayPal."""
        with self._lock:
            if order_id not in self._orders:
                raise self._fail(404, "RESOURCE_NOT_FOUND", "Order not found", "INVALID_RESOURCE_ID")
            self._orders[order_id]["status"] = "APPROVED"
            self._save()

    def get_order(self, order_id: str) -> dict[str, Any]:
        with self._lock:
            order = self._orders.get(order_id)
            if order is None:
                raise self._fail(404, "RESOURCE_NOT_FOUND", "Order not found", "INVALID_RESOURCE_ID")
            authorization = next((a for a in self._authorizations.values() if a["order_id"] == order_id), None)
            return {
                "order_id": order_id,
                "status": "COMPLETED" if authorization else order["status"],
                "authorization_id": authorization["id"] if authorization else None,
                "authorization_status": authorization["status"] if authorization else None,
                "amount": {"currency_code": order["currency"], "value": order["amount"]},
                "simulated": True,
            }

    def authorize_order(self, order_id: str, *, request_id: str) -> dict[str, Any]:
        with self._lock:
            if (cached := self._replay(f"authorize:{request_id}")) is not None:
                return cached
            order = self._orders.get(order_id)
            if order is None:
                raise self._fail(404, "RESOURCE_NOT_FOUND", "Order not found", "INVALID_RESOURCE_ID")
            if order["status"] != "APPROVED":
                raise self._fail(422, "UNPROCESSABLE_ENTITY", "Order is not approved", "ORDER_NOT_APPROVED")
            authorization_id = _new_id("AUTH")
            self._authorizations[authorization_id] = {
                "id": authorization_id,
                "order_id": order_id,
                "status": "CREATED",
                "amount": order["amount"],
                "currency": order["currency"],
                "captured": Decimal("0.00"),
            }
            result = {
                "order_id": order_id,
                "status": "COMPLETED",
                "authorization_id": authorization_id,
                "authorization_status": "CREATED",
                "amount": {"currency_code": order["currency"], "value": order["amount"]},
                "simulated": True,
            }
            logger.info("[sim] authorized order %s -> %s", order_id, authorization_id)
            return self._remember(f"authorize:{request_id}", result)

    # ----------------------------------------------------------- authorizations --
    def _authorization(self, authorization_id: str) -> dict[str, Any]:
        authorization = self._authorizations.get(authorization_id)
        if authorization is None:
            raise self._fail(404, "RESOURCE_NOT_FOUND", "Authorization not found", "INVALID_RESOURCE_ID")
        return authorization

    def get_authorization(self, authorization_id: str) -> dict[str, Any]:
        with self._lock:
            authorization = self._authorization(authorization_id)
            return {
                "authorization_id": authorization_id,
                "status": authorization["status"],
                "amount": {"currency_code": authorization["currency"], "value": authorization["amount"]},
                "expiration_time": None,
                "simulated": True,
            }

    def capture_authorization(
        self, authorization_id: str, *, amount: Decimal, invoice_id: str, request_id: str,
        final_capture: bool = True, currency: str = "USD",
    ) -> dict[str, Any]:  # fmt: skip
        with self._lock:
            if (cached := self._replay(f"capture:{request_id}")) is not None:
                return cached
            authorization = self._authorization(authorization_id)
            if authorization["status"] in {"VOIDED", "CAPTURED"}:
                raise self._fail(
                    422, "UNPROCESSABLE_ENTITY", f"Authorization is {authorization['status']}", "AUTHORIZATION_CLOSED"
                )
            if amount + authorization["captured"] > Decimal(authorization["amount"]):
                raise self._fail(
                    422, "UNPROCESSABLE_ENTITY", "Capture exceeds the authorized amount", "MAX_CAPTURE_AMOUNT_EXCEEDED"
                )
            authorization["captured"] += amount
            authorization["status"] = "CAPTURED" if final_capture else "PARTIALLY_CAPTURED"
            capture_id = _new_id("CAP")
            self._captures[capture_id] = {"authorization_id": authorization_id, "amount": money_str(amount)}
            result = {
                "capture_id": capture_id,
                "status": "COMPLETED",
                "amount": {"value": money_str(amount), "currency_code": currency},
                "final_capture": final_capture,
                "simulated": True,
            }
            logger.info("[sim] captured %s on %s (final=%s)", money_str(amount), authorization_id, final_capture)
            return self._remember(f"capture:{request_id}", result)

    def void_authorization(self, authorization_id: str, *, request_id: str) -> dict[str, Any]:
        with self._lock:
            if (cached := self._replay(f"void:{request_id}")) is not None:
                return cached
            authorization = self._authorization(authorization_id)
            if authorization["status"] != "CREATED":
                raise self._fail(
                    422, "UNPROCESSABLE_ENTITY", f"Cannot void an authorization that is {authorization['status']}",
                    "PREVIOUSLY_VOIDED_OR_CAPTURED",
                )  # fmt: skip
            authorization["status"] = "VOIDED"
            logger.info("[sim] voided %s", authorization_id)
            return self._remember(
                f"void:{request_id}", {"authorization_id": authorization_id, "voided": True, "simulated": True}
            )

    def reauthorize_authorization(
        self, authorization_id: str, *, amount: Decimal, request_id: str, currency: str = "USD"
    ) -> dict[str, Any]:
        with self._lock:
            if (cached := self._replay(f"reauthorize:{request_id}")) is not None:
                return cached
            old = self._authorization(authorization_id)
            if old["status"] != "CREATED":
                raise self._fail(
                    422, "UNPROCESSABLE_ENTITY", f"Cannot reauthorize an authorization that is {old['status']}",
                    "REAUTHORIZATION_NOT_ALLOWED",
                )  # fmt: skip
            new_id = _new_id("AUTH")
            self._authorizations[new_id] = {**old, "id": new_id, "captured": Decimal("0.00"), "amount": money_str(amount)}
            old["status"] = "REAUTHORIZED"
            logger.info("[sim] reauthorized %s -> %s", authorization_id, new_id)
            return self._remember(
                f"reauthorize:{request_id}",
                {"authorization_id": new_id, "previous_authorization_id": authorization_id, "status": "CREATED", "simulated": True},
            )

    # ----------------------------------------------------------------- webhooks --
    @staticmethod
    def webhook_signature(webhook_id: str) -> str:
        """The signature value this simulator accepts for ``webhook_id`` (tests and local demos)."""
        return f"simulated:{webhook_id}"

    def verify_webhook_signature(self, headers: Any, raw_body: bytes, webhook_id: str) -> bool:
        return headers.get("PAYPAL-TRANSMISSION-SIG") == self.webhook_signature(webhook_id)

    # ------------------------------------------------------------------ payouts --
    def create_payout(
        self, *, receiver_email: str, amount: Decimal, sender_batch_id: str, sender_item_id: str, note: str,
        email_subject: str, currency: str = "USD",
    ) -> dict[str, Any]:  # fmt: skip
        with self._lock:
            if sender_batch_id in self._payout_batches:
                raise self._fail(
                    400, "USER_BUSINESS_ERROR", "Duplicate sender_batch_id", "BATCH_ALREADY_EXISTS"
                )
            batch_id = _new_id("PAYOUT")
            self._payout_batches[sender_batch_id] = batch_id
            self._save()
            logger.info("[sim] payout %s of %s %s to %s", batch_id, money_str(amount), currency, receiver_email)
            return {"payout_batch_id": batch_id, "batch_status": "SUCCESS", "simulated": True}
