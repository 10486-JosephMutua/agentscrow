"""STEP 2: talk to the running PayPal Escrow MCP server over HTTP, as an agent would.

    Terminal 1:  python -m agentescrow.mcp_servers.paypal_escrow_server
    Terminal 2:  python -m scripts.step2_mcp_smoke_test

Shows the tools, then proves the guardrails: an over-cap order and a ticket-less capture
are REFUSED by the server itself.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from agentescrow.domain.mandate import issue_mandate
from agentescrow.mcp_client import McpToolbox, ToolCallFailed
from scripts._common import bootstrap


async def main() -> int:
    settings, log = bootstrap("step2-mcp")
    settings.require_mandate_secret()
    log.info("STEP 2: connecting to %s", settings.paypal_mcp_url)
    toolbox = await McpToolbox.connect(settings.paypal_mcp_url)
    log.info("Tools exposed: %s", toolbox.names)

    job_id = "smoke_job"
    mandate = issue_mandate(settings.mandate_secret, job_id=job_id, max_amount=Decimal("5.00"))

    log.info("Guardrail 1: ask for $999 with a $5 mandate (must be refused)")
    try:
        await toolbox.call("create_escrow_order", job_id=job_id, amount_usd="999.00", mandate_token=mandate)
        log.error("UNEXPECTED: the over-cap order was accepted")
        return 1
    except ToolCallFailed as exc:
        log.info("  refused as expected: %s", exc)

    log.info("Guardrail 2: capture without a settlement ticket (must be refused)")
    try:
        await toolbox.call("capture_escrow", job_id=job_id, authorization_id="X", amount_usd="1.00", settlement_ticket="forged.ticket")  # fmt: skip
        log.error("UNEXPECTED: the ticket-less capture was accepted")
        return 1
    except ToolCallFailed as exc:
        log.info("  refused as expected: %s", exc)

    log.info("Creating a legitimate $5.00 order through MCP")
    order = await toolbox.call("create_escrow_order", job_id=job_id, amount_usd="5.00", mandate_token=mandate)
    log.info("  order %s -> approve at %s", order["order_id"], order["approve_url"])
    log.info("STEP 2 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
