"""A server restart must not strand jobs that were mid-settlement.

The job store (SQLite) survives a restart, so the PayPal ids it holds must stay valid. Before the simulator
persisted its state, every restart made `void_escrow` / `get_authorization_status` fail with
404 RESOURCE_NOT_FOUND and the job sat in SETTLING forever (recovery retried and failed on every start).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentescrow.arbiter.semantic_judge import StaticSemanticJudge
from agentescrow.domain.models import JobState
from agentescrow.orchestrator.endpoints import inprocess_endpoints
from agentescrow.orchestrator.service import EscrowService
from agentescrow.orchestrator.store import JobStore
from agentescrow.paypal.errors import PayPalError
from agentescrow.paypal.simulator import SimulatedPayPalClient


def _service(settings, paypal) -> EscrowService:
    return EscrowService(settings, JobStore(settings.database_path), inprocess_endpoints(settings, paypal), StaticSemanticJudge(0.9))


async def _locked_job(service):
    job = await service.post_job(Decimal("5.00"))
    await service.accept_job(job.job_id, "w1", "w@example.com")
    await service.open_escrow(job.job_id)  # auto-approving simulator
    return await service.confirm_funding(job.job_id)


def test_the_simulator_keeps_its_holds_across_a_restart(tmp_path):
    path = tmp_path / "paypal_simulator.json"
    before = SimulatedPayPalClient(state_path=path)
    order = before.create_authorize_order(
        amount=Decimal("5.00"), reference_id="j", description="d", return_url="http://x", cancel_url="http://x", request_id="order-j"
    )
    authorization = before.authorize_order(order["order_id"], request_id="authorize-j")["authorization_id"]
    before.capture_authorization(authorization, amount=Decimal("2.00"), invoice_id="j", request_id="capture-j", final_capture=False)

    after = SimulatedPayPalClient(state_path=path)  # "restart"
    assert after.get_authorization(authorization)["status"] == "PARTIALLY_CAPTURED"
    with pytest.raises(PayPalError) as over:  # the Decimal balance came back intact
        after.capture_authorization(authorization, amount=Decimal("4.00"), invoice_id="j", request_id="capture-2")
    assert "MAX_CAPTURE_AMOUNT_EXCEEDED" in over.value.issues


def test_a_corrupt_simulator_file_does_not_crash_the_server(tmp_path):
    path = tmp_path / "paypal_simulator.json"
    path.write_text("{not json", encoding="utf-8")
    SimulatedPayPalClient(state_path=path)  # must not raise
    assert path.with_suffix(".corrupt").exists()


@pytest.mark.asyncio
async def test_voiding_a_hold_the_simulator_forgot_still_finishes_the_job(settings):
    """Legacy jobs (created before persistence) reference holds the restarted simulator has never heard of."""
    job = await _locked_job(_service(settings, SimulatedPayPalClient()))
    restarted = _service(settings, SimulatedPayPalClient())  # fresh, empty simulator: the hold is unknown to it
    voided = await restarted.cancel_job(job.job_id)
    assert voided.state == JobState.VOIDED
    assert any("no longer exists" in e["message"] for e in restarted.events(job.job_id))
