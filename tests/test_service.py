"""End-to-end orchestration with the PayPal simulator, scripted workers and a static judge."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentescrow.arbiter.semantic_judge import JudgeError, StaticSemanticJudge
from agentescrow.domain.models import JobState, Outcome
from agentescrow.orchestrator.endpoints import inprocess_endpoints
from agentescrow.orchestrator.service import ArbitrationFailed, EscrowService, JobError, NotReady, SettlementError
from agentescrow.orchestrator.store import JobStore
from agentescrow.paypal.simulator import SimulatedPayPalClient

pytestmark = pytest.mark.asyncio


class FlakyJudge:
    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    def judge(self, contract, deliverable):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            raise JudgeError("rate limited")
        return StaticSemanticJudge(0.9).judge(contract, deliverable)


@pytest.fixture
def make_service(settings):
    def _make(judge=None):
        store = JobStore(settings.database_path)
        endpoints = inprocess_endpoints(settings, SimulatedPayPalClient())
        return EscrowService(settings, store, endpoints, judge or StaticSemanticJudge(0.9)), store

    return _make


async def _locked_job(service, email="worker@example.com"):
    job = await service.post_job(Decimal("5.00"))
    await service.accept_job(job.job_id, "worker-1", email)
    await service.open_escrow(job.job_id)
    return await service.confirm_funding(job.job_id)


async def test_honest_worker_is_paid_in_full(make_service):
    service, store = make_service()
    job = await _locked_job(service)
    assert job.state == JobState.ESCROW_LOCKED and job.authorization_id
    job = await service.run_pipeline(job.job_id, "honest")
    assert job.state == JobState.SETTLED
    assert job.decision.outcome == Outcome.FULL
    assert (job.decision.capture_amount, job.decision.platform_fee, job.decision.worker_payout) == (
        Decimal("5.00"), Decimal("0.33"), Decimal("4.67"),
    )  # fmt: skip
    assert job.capture_id and job.payout_batch_id
    kinds = [event["kind"] for event in store.events(job.job_id)]
    assert {"state", "mandate", "paypal", "tier", "decision"} <= set(kinds)


async def test_sloppy_worker_gets_a_partial_payment(make_service):
    service, _ = make_service()
    job = await _locked_job(service)
    job = await service.run_pipeline(job.job_id, "sloppy")
    assert job.state == JobState.SETTLED
    assert job.decision.outcome == Outcome.PARTIAL
    assert Decimal("0") < job.decision.capture_amount < Decimal("5.00")
    assert job.decision.capture_amount == job.decision.platform_fee + job.decision.worker_payout


async def test_cheater_is_voided_and_the_buyer_pays_nothing(make_service):
    service, store = make_service()
    job = await _locked_job(service)
    job = await service.run_pipeline(job.job_id, "cheater")
    assert job.state == JobState.VOIDED
    assert job.decision.outcome == Outcome.VOID and job.capture_id is None and job.payout_batch_id is None
    assert job.verdict.sandbox is None, "a submission that fails the integrity gate must never be executed"
    receipt = service.receipt(job.job_id)["receipt"]
    assert receipt["buyer_charged_usd"] == "0.00" and receipt["simulated"] is True


async def test_funding_must_be_confirmed_before_work(make_service):
    service, _ = make_service()
    job = await service.post_job()
    await service.accept_job(job.job_id, "w", "w@example.com")
    with pytest.raises(JobError, match="needs ESCROW_LOCKED"):
        await service.run_worker(job.job_id)


async def test_illegal_transitions_are_rejected(make_service):
    service, _ = make_service()
    job = await service.post_job()
    with pytest.raises(JobError):
        await service.settle(job.job_id)
    with pytest.raises(JobError):
        await service.arbitrate(job.job_id)


async def test_accept_validates_the_worker_email(make_service):
    service, _ = make_service()
    job = await service.post_job()
    with pytest.raises(ValueError, match="email"):
        await service.accept_job(job.job_id, "w", "not-an-email")


async def test_judge_outage_parks_the_job_for_review_then_recovers(make_service):
    service, _ = make_service(FlakyJudge())
    job = await _locked_job(service)
    await service.run_worker(job.job_id, "honest")
    with pytest.raises(ArbitrationFailed):
        await service.arbitrate(job.job_id)
    assert service.get_job(job.job_id).state == JobState.NEEDS_REVIEW
    await service.arbitrate(job.job_id)  # retry succeeds
    job = await service.settle(job.job_id)
    assert job.state == JobState.SETTLED


async def test_settlement_resumes_after_a_failed_payout(make_service, monkeypatch):
    service, store = make_service()
    job = await _locked_job(service)
    await service.run_worker(job.job_id, "honest")
    await service.arbitrate(job.job_id)

    from agentescrow import mcp_client

    real_call = mcp_client.McpToolbox.call
    state = {"fail": True}

    async def flaky_call(self, name, **kwargs):  # noqa: ANN001
        if name == "pay_worker" and state["fail"]:
            state["fail"] = False
            raise mcp_client.ToolCallFailed(name, "PayPal is down")
        return await real_call(self, name, **kwargs)

    monkeypatch.setattr(mcp_client.McpToolbox, "call", flaky_call)
    with pytest.raises(SettlementError):
        await service.settle(job.job_id)
    parked = service.get_job(job.job_id)
    assert parked.state == JobState.SETTLING and parked.capture_id and not parked.payout_batch_id

    settled = await service.settle(job.job_id)  # resume: capture is not repeated, payout now succeeds
    assert settled.state == JobState.SETTLED and settled.payout_batch_id


async def test_cancelling_a_funded_job_voids_the_hold(make_service):
    service, _ = make_service()
    job = await _locked_job(service)
    job = await service.cancel_job(job.job_id)
    assert job.state == JobState.VOIDED


async def test_cancelling_before_funding_needs_no_paypal(make_service):
    service, _ = make_service()
    job = await service.post_job()
    assert (await service.cancel_job(job.job_id)).state == JobState.CANCELLED


async def test_external_worker_submission_with_wrong_shape_is_voided(make_service):
    service, _ = make_service()
    job = await _locked_job(service)
    await service.submit_deliverable(job.job_id, {"answer": "forty-two"})
    await service.arbitrate(job.job_id)
    job = await service.settle(job.job_id)
    assert job.state == JobState.VOIDED
    assert job.verdict.schema_check.valid is False


async def test_funding_waits_for_the_buyer_to_approve(settings):
    paypal = SimulatedPayPalClient(auto_approve=False)
    store = JobStore(settings.database_path)
    service = EscrowService(settings, store, inprocess_endpoints(settings, paypal), StaticSemanticJudge(0.9))
    job = await service.post_job()
    await service.accept_job(job.job_id, "w", "w@example.com")
    job = await service.open_escrow(job.job_id)
    with pytest.raises(NotReady, match="has not approved"):
        await service.confirm_funding(job.job_id)
    assert service.get_job(job.job_id).state == JobState.FUNDS_PENDING
    paypal.approve(job.order_id)
    assert (await service.confirm_funding(job.job_id)).state == JobState.ESCROW_LOCKED
    assert (await service.confirm_funding(job.job_id)).state == JobState.ESCROW_LOCKED  # idempotent
