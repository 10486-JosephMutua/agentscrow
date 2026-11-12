"""PayPal Escrow MCP server.

Exposes the escrow primitives of the PayPal sandbox as MCP tools:

    create_escrow_order      needs a signed MANDATE   (caps and binds the amount)
    authorize_escrow         needs a signed MANDATE
    get_order_status         read-only
    get_authorization_status read-only
    capture_escrow           needs a signed SETTLEMENT TICKET
    void_escrow              needs a signed SETTLEMENT TICKET
    reauthorize_escrow       needs a signed SETTLEMENT TICKET
    verify_webhook           read-only (checks a PayPal webhook signature)
    pay_worker               needs a signed SETTLEMENT TICKET

The guardrails live *in the server*, not in prompts: an agent that is confused, buggy or
manipulated cannot lock more than its mandate or move money without a ticket.

Run:  python -m agentescrow.mcp_servers.paypal_escrow_server
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from agentescrow.config import Settings
from agentescrow.domain.mandate import MandateError, verify_mandate, verify_settlement_ticket
from agentescrow.logging_setup import configure_logging, job_logging_context
from agentescrow.money import to_decimal
from agentescrow.paypal.errors import PayPalError
from agentescrow.paypal.factory import AnyPayPalClient, build_paypal_client

logger = logging.getLogger(__name__)


def _amount(value: str) -> Decimal:
    try:
        amount = to_decimal(value)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if amount <= 0:
        raise ToolError("amount_usd must be greater than zero")
    return amount


def build_paypal_server(settings: Settings, client: AnyPayPalClient | None = None) -> FastMCP:
    """Create the MCP server. Pass ``client`` to inject a fake in tests."""
    settings.require_mandate_secret()
    paypal = client or build_paypal_client(settings)
    secret = settings.mandate_secret
    mcp = FastMCP("agentescrow-paypal")

    def guarded(job_id: str, tool: str, action: Any) -> dict[str, Any]:
        """Run ``action`` with job-tagged logging, translating domain errors into ToolErrors."""
        with job_logging_context(job_id):
            logger.info("MCP tool %s invoked", tool)
            try:
                result = action()
            except MandateError as exc:
                logger.warning("MCP tool %s REFUSED: %s", tool, exc)
                raise ToolError(f"Refused: {exc}") from exc
            except PayPalError as exc:
                logger.error("MCP tool %s PayPal error: %s", tool, exc)
                raise ToolError(str(exc)) from exc
            logger.info("MCP tool %s succeeded", tool)
            return result

    @mcp.tool
    def create_escrow_order(job_id: str, amount_usd: str, mandate_token: str) -> dict[str, Any]:
        """Create the PayPal order that will hold the job's bounty in escrow (intent AUTHORIZE).

        The buyer must still approve the returned approve_url. amount_usd is a decimal string
        such as "5.00". The mandate_token is signed and caps the amount.
        """

        def action() -> dict[str, Any]:
            amount = _amount(amount_usd)
            verify_mandate(secret, mandate_token, job_id=job_id, amount=amount)
            return paypal.create_authorize_order(
                amount=amount,
                reference_id=job_id,
                description=f"AgentEscrow bounty for {job_id}",
                return_url=f"{settings.public_base_url}/escrow/success?job_id={job_id}",
                cancel_url=f"{settings.public_base_url}/escrow/cancel?job_id={job_id}",
                request_id=f"order-{job_id}",
            )

        return guarded(job_id, "create_escrow_order", action)

    @mcp.tool
    def get_order_status(job_id: str, order_id: str) -> dict[str, Any]:
        """Read-only: show an order's status (APPROVED means the buyer approved it) and its authorization id."""
        return guarded(job_id, "get_order_status", lambda: paypal.get_order(order_id))

    @mcp.tool
    def authorize_escrow(job_id: str, order_id: str, amount_usd: str, mandate_token: str) -> dict[str, Any]:
        """Lock the funds: authorize an APPROVED order. Returns the authorization_id that holds the bounty."""

        def action() -> dict[str, Any]:
            verify_mandate(secret, mandate_token, job_id=job_id, amount=_amount(amount_usd))
            return paypal.authorize_order(order_id, request_id=f"authorize-{job_id}")

        return guarded(job_id, "authorize_escrow", action)

    @mcp.tool
    def get_authorization_status(authorization_id: str) -> dict[str, Any]:
        """Read-only: show an authorization. Status CREATED means the funds are locked and it is safe to start work."""
        return guarded("-", "get_authorization_status", lambda: paypal.get_authorization(authorization_id))

    @mcp.tool
    def capture_escrow(job_id: str, authorization_id: str, amount_usd: str, settlement_ticket: str) -> dict[str, Any]:
        """Collect payment from the hold (full or partial). Requires a settlement ticket for exactly this amount."""

        def action() -> dict[str, Any]:
            amount = _amount(amount_usd)
            verify_settlement_ticket(secret, settlement_ticket, job_id=job_id, action="capture", amount=amount)
            return paypal.capture_authorization(
                authorization_id,
                amount=amount,
                invoice_id=f"AE-{job_id}",
                request_id=f"capture-{job_id}",
                final_capture=True,  # closes the authorization and releases any unused remainder
            )

        return guarded(job_id, "capture_escrow", action)

    @mcp.tool
    def void_escrow(job_id: str, authorization_id: str, settlement_ticket: str) -> dict[str, Any]:
        """Release the hold so the buyer is charged nothing. Requires a settlement ticket for this job."""

        def action() -> dict[str, Any]:
            verify_settlement_ticket(secret, settlement_ticket, job_id=job_id, action="void")
            return paypal.void_authorization(authorization_id, request_id=f"void-{job_id}")

        return guarded(job_id, "void_escrow", action)

    @mcp.tool
    def reauthorize_escrow(job_id: str, authorization_id: str, amount_usd: str, settlement_ticket: str) -> dict[str, Any]:
        """Refresh a hold that is past PayPal's 3-day honor period. Returns the NEW authorization_id to use from now on."""

        def action() -> dict[str, Any]:
            amount = _amount(amount_usd)
            verify_settlement_ticket(secret, settlement_ticket, job_id=job_id, action="reauthorize", amount=amount)
            return paypal.reauthorize_authorization(authorization_id, amount=amount, request_id=f"reauthorize-{job_id}")

        return guarded(job_id, "reauthorize_escrow", action)

    @mcp.tool
    def verify_webhook(headers: dict[str, str], raw_body: str) -> dict[str, Any]:
        """Read-only: ask PayPal whether a webhook (its headers and exact raw body) is genuine."""
        webhook_id = settings.paypal_webhook_id or ("SIMULATED" if settings.paypal_mode == "simulated" else "")
        if not webhook_id:
            raise ToolError("PAYPAL_WEBHOOK_ID is not configured, so webhooks cannot be verified")
        upper = {key.upper(): value for key, value in headers.items()}
        return guarded(
            "-", "verify_webhook",
            lambda: {"verified": paypal.verify_webhook_signature(upper, raw_body.encode("utf-8"), webhook_id)},
        )  # fmt: skip

    @mcp.tool
    def pay_worker(job_id: str, receiver_email: str, amount_usd: str, settlement_ticket: str) -> dict[str, Any]:
        """Pay the worker's PayPal email via PayPal Payouts. Requires a settlement ticket for exactly this amount."""

        def action() -> dict[str, Any]:
            amount = _amount(amount_usd)
            verify_settlement_ticket(secret, settlement_ticket, job_id=job_id, action="payout", amount=amount)
            return paypal.create_payout(
                receiver_email=receiver_email,
                amount=amount,
                sender_batch_id=f"batch_{job_id}",
                sender_item_id=f"item_{job_id}",
                note=f"Verified deliverable for {job_id}",
                email_subject="You have a payout from AgentEscrow",
            )

        return guarded(job_id, "pay_worker", action)

    return mcp


def main() -> None:
    settings = Settings.from_env()
    settings.validate_modes()
    configure_logging(settings.log_level, settings.log_dir, service="paypal-mcp")
    server = build_paypal_server(settings)
    logger.info("PayPal Escrow MCP server listening on %s (mode=%s)", settings.paypal_mcp_url, settings.paypal_mode)
    server.run(transport="http", host=settings.mcp_host, port=settings.paypal_mcp_port)


if __name__ == "__main__":
    main()
