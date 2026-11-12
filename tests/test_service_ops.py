"""Operational behavior: reauthorization, deadline sweeping, webhooks, and already-released holds."""

from __future__ import annotations

import time
from datetime import timedelta
from decimal import Decimal

import pytest

from agentescrow.arbiter.semantic_judge import StaticSemanticJudge
from agentescrow.domain.models import JobState, utc_now
from agentescrow.orchestrator.endpoints import inprocess_endpoints
from agentescrow.orchestrator.service import EscrowService, JobError, SettlementError
from agentescrow.orchestrator.store import JobStore
from agentescrow.paypal.simulator import SimulatedPayPalClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def env(settings):
    paypal = SimulatedPayPalClient(auto_approve=False)
    store = JobStore(settings.database_path)
    service = EscrowService(settings, store, inprocess_endpoints(settings, paypal), StaticSemanticJudge(0.9))
    return service, store, paypal


async def _to_pending(service, paypal):
    job = await service.post_job(Decimal("5.00"))
    await service.accept_job(job.job_id, "w1", "w@example.com")
    job = await service.open_escrow(job.job_id)
    return job


async def _locked(service, paypal):
    job = await _to_pending(service, paypal)
    paypal.approve(job.order_id)
    return await service.confirm_funding(job.job_id)


# ------------------------------------------------------------------ reauthorization --
async def test_a_hold_older_than_the_honor_period_is_reauthorized_before_capture(env):
    service, store, paypal = env
    job = await _locked(service, paypal)
    old_authorization = job.authorization_id
    await service.run_worker(job.job_id, "honest")
    await service.arbitrate(job.job_id)

    aged = store.get(job.job_id)
    aged.locked_at = utc_now() - timedelta(days=4)
    store.save(aged, expected_state=aged.state)

    settled = await service.settle(job.job_id)
    assert settled.state == JobState.SETTLED and settled.capture_id
    assert settled.authorization_id != old_authorization and settled.reauthorized_at is not None
    assert any("reauthorized" in e["message"] for e in store.events(job.job_id))


async def test_a_fresh_hold_is_not_reauthorized(env):
    service, store, paypal = env
    job = await _locked(service, paypal)
    original = job.authorization_id
    settled = await service.run_pipeline(job.job_id, "honest")
    assert settled.authorization_id == original and settled.reauthorized_at is None


async def test_a_hold_past_29_days_cannot_be_captured(env):
    service, store, paypal = env
    job = await _locked(service, paypal)
    await service.run_worker(job.job_id, "honest")
    await service.arbitrate(job.job_id)
    stale = store.get(job.job_id)
    stale.locked_at = utc_now() - timedelta(days=30)
    store.save(stale, expected_state=stale.state)
    with pytest.raises(SettlementError, match="29 days"):
        await service.settle(job.job_id)
    assert store.get(job.job_id).state == JobState.SETTLING


# ------------------------------------------------------------------ deadline sweeper --
async def test_sweeper_voids_overdue_funded_jobs_and_cancels_unfunded_ones(env):
    service, store, paypal = env
    funded = await _locked(service, paypal)
    unfunded = await service.post_job()
    for job in (funded, unfunded):
        past = store.get(job.job_id)
        past.contract.deadline_epoch = int(time.time()) - 5
        store.save(past, expected_state=past.state)
    on_time = await service.post_job()

    closed = await service.sweep_overdue()
    assert set(closed) == {funded.job_id, unfunded.job_id}
    assert store.get(funded.job_id).state == JobState.VOIDED
    assert store.get(unfunded.job_id).state == JobState.CANCELLED
    assert store.get(on_time.job_id).state == JobState.POSTED
    assert await service.sweep_overdue() == []  # idempotent


async def test_sweeper_never_touches_submitted_work(env):
    service, store, paypal = env
    job = await _locked(service, paypal)
    await service.run_worker(job.job_id, "honest")
    past = store.get(job.job_id)
    past.contract.deadline_epoch = int(time.time()) - 5
    store.save(past, expected_state=past.state)
    assert await service.sweep_overdue() == []
    assert store.get(job.job_id).state == JobState.SUBMITTED


async def test_deadline_hours_are_validated_and_applied(env):
    service, _, _ = env
    job = await service.post_job(deadline_hours=2)
    assert 2 * 3600 - 60 <= job.contract.deadline_epoch - time.time() <= 2 * 3600 + 5
    for bad in (0, -1, 25 * 24 + 1):
        with pytest.raises(ValueError, match="deadline_hours"):
            await service.post_job(deadline_hours=bad)


async def test_submitting_after_the_deadline_is_rejected(env):
    service, store, paypal = env
    job = await _locked(service, paypal)
    late = store.get(job.job_id)
    late.contract.deadline_epoch = int(time.time()) - 5
    store.save(late, expected_state=late.state)
    with pytest.raises(JobError, match="deadline"):
        await service.run_worker(job.job_id, "honest")


# ------------------------------------------------------------------------ webhooks --
def _event(event_id, event_type, resource):
    return {"id": event_id, "event_type": event_type, "resource": resource}


async def test_order_approved_webhook_locks_the_funds(env):
    service, store, paypal = env
    job = await _to_pending(service, paypal)
    paypal.approve(job.order_id)  # the buyer approved in PayPal; the webhook arrives before they return to us
    outcome = await service.handle_webhook(_event("WH-1", "CHECKOUT.ORDER.APPROVED", {"id": job.order_id, "status": "APPROVED"}))
    assert outcome == "funding confirmed"
    assert store.get(job.job_id).state == JobState.ESCROW_LOCKED


async def test_webhook_for_an_unapproved_order_does_not_lock_funds(env):
    service, store, paypal = env
    job = await _to_pending(service, paypal)
    outcome = await service.handle_webhook(_event("WH-2", "CHECKOUT.ORDER.APPROVED", {"id": job.order_id}))
    assert outcome.startswith("funding not confirmed")
    assert store.get(job.job_id).state == JobState.FUNDS_PENDING


async def test_webhook_retries_are_ignored(env):
    service, store, paypal = env
    job = await _to_pending(service, paypal)
    paypal.approve(job.order_id)
    event = _event("WH-3", "CHECKOUT.ORDER.APPROVED", {"id": job.order_id})
    assert await service.handle_webhook(event) == "funding confirmed"
    assert await service.handle_webhook(event) == "duplicate"


async def test_authorization_created_webhook_matches_by_related_order(env):
    service, store, paypal = env
    job = await _to_pending(service, paypal)
    paypal.approve(job.order_id)
    resource = {"id": "AUTH-NOT-YET-KNOWN", "supplementary_data": {"related_ids": {"order_id": job.order_id}}}
    assert await service.handle_webhook(_event("WH-4", "PAYMENT.AUTHORIZATION.CREATED", resource)) == "funding confirmed"


async def test_external_void_closes_a_waiting_job(env):
    service, store, paypal = env
    job = await _locked(service, paypal)
    outcome = await service.handle_webhook(_event("WH-5", "PAYMENT.AUTHORIZATION.VOIDED", {"id": job.authorization_id}))
    assert "voided externally" in outcome
    assert store.get(job.job_id).state == JobState.VOIDED


async def test_external_void_mid_work_raises_an_alert_but_changes_nothing(env):
    service, store, paypal = env
    job = await _locked(service, paypal)
    await service.run_worker(job.job_id, "honest")
    outcome = await service.handle_webhook(_event("WH-6", "PAYMENT.AUTHORIZATION.VOIDED", {"id": job.authorization_id}))
    assert outcome.startswith("alert")
    after = store.get(job.job_id)
    assert after.state == JobState.SUBMITTED and "voided externally" in (after.error or "")


async def test_our_own_void_is_just_confirmed(env):
    service, store, paypal = env
    job = await _locked(service, paypal)
    await service.cancel_job(job.job_id)
    outcome = await service.handle_webhook(_event("WH-7", "PAYMENT.AUTHORIZATION.VOIDED", {"id": job.authorization_id}))
    assert outcome == "void confirmed"


async def test_capture_webhooks_are_logged(env):
    service, store, paypal = env
    job = await _locked(service, paypal)
    settled = await service.run_pipeline(job.job_id, "honest")
    done = _event("WH-8", "PAYMENT.CAPTURE.COMPLETED", {"id": settled.capture_id})
    assert await service.handle_webhook(done) == "capture confirmed"
    denied = _event("WH-9", "PAYMENT.CAPTURE.DENIED", {"id": settled.capture_id})
    assert (await service.handle_webhook(denied)).startswith("alert")


async def test_unknown_jobs_and_events_are_ignored(env):
    service, _, _ = env
    assert (await service.handle_webhook(_event("WH-10", "CHECKOUT.ORDER.APPROVED", {"id": "NOPE"}))).startswith("ignored")
    assert (await service.handle_webhook({"event_type": "X"})).startswith("ignored")


# ----------------------------------------------------------- already-released holds --
async def test_cancelling_an_already_voided_hold_still_succeeds(env, monkeypatch):
    service, store, paypal = env
    job = await _locked(service, paypal)
    paypal.void_authorization(job.authorization_id, request_id="someone-else-voided-it")  # released outside our flow
    cancelled = await service.cancel_job(job.job_id)
    assert cancelled.state == JobState.VOIDED
    assert any("already released" in e["message"] for e in store.events(job.job_id))


async def test_overview_summarises_money(env):
    service, store, paypal = env
    job = await _locked(service, paypal)
    await service.run_pipeline(job.job_id, "honest")
    overview = service.overview()
    assert overview["counts"]["SETTLED"] == 1
    assert (overview["captured_usd"], overview["paid_to_workers_usd"], overview["platform_fees_usd"]) == ("5.00", "4.67", "0.33")
