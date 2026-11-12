"""The PayPal MCP server enforces mandates and settlement tickets server-side."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentescrow.domain.mandate import issue_mandate, issue_settlement_ticket
from agentescrow.mcp_client import McpToolbox, ToolCallFailed
from agentescrow.mcp_servers.paypal_escrow_server import build_paypal_server
from agentescrow.paypal.simulator import SimulatedPayPalClient
from tests.conftest import TEST_SECRET

pytestmark = pytest.mark.asyncio


async def _toolbox(settings):
    return await McpToolbox.connect(build_paypal_server(settings, SimulatedPayPalClient()))


def _mandate(job_id="job_t1", cap="5.00"):
    return issue_mandate(TEST_SECRET, job_id=job_id, max_amount=Decimal(cap))


def _ticket(job_id, action, amount="0.00"):
    return issue_settlement_ticket(TEST_SECRET, job_id=job_id, action=action, amount=Decimal(amount))


async def test_exposes_the_expected_tools(settings):
    toolbox = await _toolbox(settings)
    assert toolbox.names == [
        "authorize_escrow", "capture_escrow", "create_escrow_order", "get_authorization_status",
        "get_order_status", "pay_worker", "reauthorize_escrow", "verify_webhook", "void_escrow",
    ]  # fmt: skip


async def test_full_flow_authorize_capture_payout(settings):
    tb = await _toolbox(settings)
    order = await tb.call("create_escrow_order", job_id="job_t1", amount_usd="5.00", mandate_token=_mandate())
    assert order["approve_url"].startswith("http://localhost:5000/escrow/success?job_id=job_t1")
    auth = await tb.call(
        "authorize_escrow", job_id="job_t1", order_id=order["order_id"], amount_usd="5.00", mandate_token=_mandate()
    )
    status = await tb.call("get_authorization_status", authorization_id=auth["authorization_id"])
    assert status["status"] == "CREATED"
    capture = await tb.call(
        "capture_escrow", job_id="job_t1", authorization_id=auth["authorization_id"], amount_usd="3.95",
        settlement_ticket=_ticket("job_t1", "capture", "3.95"),
    )  # fmt: skip
    assert capture["status"] == "COMPLETED"
    payout = await tb.call(
        "pay_worker", job_id="job_t1", receiver_email="w@example.com", amount_usd="3.69",
        settlement_ticket=_ticket("job_t1", "payout", "3.69"),
    )  # fmt: skip
    assert payout["batch_status"] == "SUCCESS"


async def test_order_above_mandate_cap_is_refused(settings):
    tb = await _toolbox(settings)
    with pytest.raises(ToolCallFailed, match="exceeds the mandate cap"):
        await tb.call("create_escrow_order", job_id="job_t1", amount_usd="999.00", mandate_token=_mandate())


async def test_mandate_for_another_job_is_refused(settings):
    tb = await _toolbox(settings)
    with pytest.raises(ToolCallFailed, match="different job"):
        await tb.call("create_escrow_order", job_id="job_other", amount_usd="1.00", mandate_token=_mandate("job_t1"))


async def test_forged_mandate_is_refused(settings):
    tb = await _toolbox(settings)
    with pytest.raises(ToolCallFailed, match="signature"):
        await tb.call("create_escrow_order", job_id="job_t1", amount_usd="1.00", mandate_token="abc.def")


async def test_capture_without_valid_ticket_is_refused(settings):
    tb = await _toolbox(settings)
    with pytest.raises(ToolCallFailed, match="Refused"):
        await tb.call(
            "capture_escrow", job_id="job_t1", authorization_id="X", amount_usd="1.00", settlement_ticket="nope.nope"
        )


async def test_ticket_for_a_different_amount_is_refused(settings):
    tb = await _toolbox(settings)
    with pytest.raises(ToolCallFailed, match="amount does not match"):
        await tb.call(
            "capture_escrow", job_id="job_t1", authorization_id="X", amount_usd="4.00",
            settlement_ticket=_ticket("job_t1", "capture", "1.00"),
        )  # fmt: skip


async def test_a_mandate_cannot_be_used_as_a_settlement_ticket(settings):
    tb = await _toolbox(settings)
    with pytest.raises(ToolCallFailed, match="settlement"):
        await tb.call("void_escrow", job_id="job_t1", authorization_id="X", settlement_ticket=_mandate())


async def test_void_releases_the_hold(settings):
    tb = await _toolbox(settings)
    order = await tb.call("create_escrow_order", job_id="job_t1", amount_usd="5.00", mandate_token=_mandate())
    auth = await tb.call(
        "authorize_escrow", job_id="job_t1", order_id=order["order_id"], amount_usd="5.00", mandate_token=_mandate()
    )
    await tb.call(
        "void_escrow", job_id="job_t1", authorization_id=auth["authorization_id"],
        settlement_ticket=_ticket("job_t1", "void"),
    )  # fmt: skip
    status = await tb.call("get_authorization_status", authorization_id=auth["authorization_id"])
    assert status["status"] == "VOIDED"


async def test_reauthorize_needs_a_ticket_and_returns_a_new_authorization(settings):
    tb = await _toolbox(settings)
    order = await tb.call("create_escrow_order", job_id="job_t1", amount_usd="5.00", mandate_token=_mandate())
    auth = await tb.call(
        "authorize_escrow", job_id="job_t1", order_id=order["order_id"], amount_usd="5.00", mandate_token=_mandate()
    )
    with pytest.raises(ToolCallFailed, match="Refused"):
        await tb.call("reauthorize_escrow", job_id="job_t1", authorization_id=auth["authorization_id"], amount_usd="5.00", settlement_ticket="x.y")  # fmt: skip
    fresh = await tb.call(
        "reauthorize_escrow", job_id="job_t1", authorization_id=auth["authorization_id"], amount_usd="5.00",
        settlement_ticket=_ticket("job_t1", "reauthorize", "5.00"),
    )  # fmt: skip
    assert fresh["authorization_id"] != auth["authorization_id"]
    assert (await tb.call("get_authorization_status", authorization_id=fresh["authorization_id"]))["status"] == "CREATED"


async def test_verify_webhook_uses_the_configured_webhook_id(settings):
    tb = await _toolbox(settings)
    good = {"paypal-transmission-sig": SimulatedPayPalClient.webhook_signature("WH-TEST")}
    assert (await tb.call("verify_webhook", headers=good, raw_body="{}"))["verified"] is True
    bad = {"paypal-transmission-sig": "forged"}
    assert (await tb.call("verify_webhook", headers=bad, raw_body="{}"))["verified"] is False
