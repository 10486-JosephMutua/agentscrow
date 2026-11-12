"""STEP 1b: prove the PayPal sandbox escrow mechanics with plain REST calls, no agents.

    python -m scripts.step1_paypal_spike --outcome full      # authorize -> capture -> payout
    python -m scripts.step1_paypal_spike --outcome partial   # authorize -> capture 60% -> payout
    python -m scripts.step1_paypal_spike --outcome void      # authorize -> void (buyer pays nothing)

You will be given an approval URL: open it, log in with your SANDBOX *personal* (buyer)
account, approve, then press Enter here. Add --simulate to dry-run without PayPal.
"""

from __future__ import annotations

import argparse
import time
import uuid
from decimal import Decimal

from agentescrow.money import floor_cents, round_cents
from agentescrow.paypal.client import PayPalClient
from agentescrow.paypal.errors import PayPalError
from agentescrow.paypal.simulator import SimulatedPayPalClient
from scripts._common import bootstrap


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outcome", choices=["full", "partial", "void"], default="full")
    parser.add_argument("--amount", default="5.00", help="bounty in USD (default 5.00)")
    parser.add_argument("--simulate", action="store_true", help="use the in-memory simulator instead of PayPal")
    args = parser.parse_args()

    settings, log = bootstrap("step1-spike")
    amount = Decimal(args.amount)
    job_id = f"spike_{uuid.uuid4().hex[:8]}"
    log.info("STEP 1 spike: job=%s outcome=%s amount=%s simulate=%s", job_id, args.outcome, amount, args.simulate)

    if args.simulate:
        client = SimulatedPayPalClient()
    else:
        settings.require_paypal()
        client = PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url, allow_live=settings.allow_live_paypal)  # fmt: skip

    try:
        log.info("[1/5] Creating an AUTHORIZE order (nothing is charged yet)")
        order = client.create_authorize_order(
            amount=amount, reference_id=job_id, description=f"AgentEscrow spike {job_id}",
            return_url=f"{settings.public_base_url}/escrow/success?job_id={job_id}",
            cancel_url=f"{settings.public_base_url}/escrow/cancel?job_id={job_id}",
            request_id=f"order-{job_id}",
        )  # fmt: skip
        log.info("      order id: %s", order["order_id"])

        if not args.simulate:
            print(f"\n  Approve the hold as the BUYER (sandbox personal account):\n  {order['approve_url']}\n")
            input("  Press Enter once you have approved... ")

        log.info("[2/5] Authorizing the approved order: this locks the funds")
        for attempt in range(1, 4):
            try:
                auth = client.authorize_order(order["order_id"], request_id=f"authorize-{job_id}")
                break
            except PayPalError as exc:
                if attempt == 3:
                    raise
                log.warning("      authorize not ready (%s); retrying in 3s", exc)
                time.sleep(3)
        authorization_id = auth["authorization_id"]
        log.info("      authorization id: %s (status %s)", authorization_id, auth["authorization_status"])
        log.info("      authorization check: %s", client.get_authorization(authorization_id)["status"])

        if args.outcome == "void":
            log.info("[3/5] Voiding the authorization: the buyer is charged nothing")
            client.void_authorization(authorization_id, request_id=f"void-{job_id}")
            log.info("[4/5] (no capture) [5/5] (no payout)")
            log.info("DONE: hold released. Check the sandbox buyer account: no charge.")
            return 0

        capture_amount = amount if args.outcome == "full" else floor_cents(amount * Decimal("0.60"))
        fee = round_cents(capture_amount * settings.platform_fee_rate)
        payout_amount = capture_amount - fee
        log.info("[3/5] Capturing %s of %s (final_capture releases any remainder)", capture_amount, amount)
        capture = client.capture_authorization(authorization_id, amount=capture_amount, invoice_id=f"AE-{job_id}", request_id=f"capture-{job_id}")  # fmt: skip
        log.info("      capture id: %s (status %s)", capture["capture_id"], capture["status"])

        log.info("[4/5] Paying the worker %s (platform keeps %s)", payout_amount, fee)
        payout = client.create_payout(
            receiver_email=settings.paypal_worker_email, amount=payout_amount, sender_batch_id=f"batch_{job_id}",
            sender_item_id=f"item_{job_id}", note=f"Spike payout {job_id}", email_subject="AgentEscrow spike payout",
        )  # fmt: skip
        log.info("      payout batch: %s (status %s)", payout["payout_batch_id"], payout["batch_status"])
        log.info("[5/5] DONE: authorize -> capture -> payout verified end to end")
        return 0
    except PayPalError as exc:
        log.error("PayPal call failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
