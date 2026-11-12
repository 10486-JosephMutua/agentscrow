"""Crash recovery, readiness, live-stream caps, the single-instance guard, demo personas and the judge panel."""

from __future__ import annotations

import threading
from dataclasses import replace
from decimal import Decimal

import pytest

from agentescrow.api.app import create_app
from agentescrow.api.ratelimit import StreamLimiter
from agentescrow.arbiter.semantic_judge import JudgeError, LLMSemanticJudge, SemanticAssessment
from agentescrow.domain.models import JobState
from agentescrow.orchestrator.lock import InstanceLock, InstanceLockError
from agentescrow.samples import build_sample_contract

pytestmark = pytest.mark.asyncio


async def locked(service):
    job = await service.post_job(Decimal("5.00"))
    await service.accept_job(job.job_id, "w", "w@example.com")
    await service.open_escrow(job.job_id)
    return await service.confirm_funding(job.job_id)


# --------------------------------------------------------------------- recovery --
async def test_a_job_interrupted_mid_arbitration_is_finished_after_a_restart(api_parts):
    _, service, _ = api_parts
    job = await locked(service)
    await service.run_worker(job.job_id, "honest")
    stuck = service._store.get(job.job_id)  # noqa: SLF001
    stuck.state = JobState.ARBITRATING  # the process died here
    service._store.save(stuck)  # noqa: SLF001
    assert await service.recover_after_restart() == [job.job_id]
    settled = service.get_job(job.job_id)
    assert settled.state == JobState.SETTLED and settled.capture_id and settled.payout_batch_id
    assert any("restarted" in e["message"] for e in service.events(job.job_id))


async def test_a_settlement_interrupted_before_the_payout_resumes_without_double_charging(api_parts):
    _, service, _ = api_parts
    job = await locked(service)
    await service.run_worker(job.job_id, "honest")
    await service.arbitrate(job.job_id)  # now SETTLING
    await service.recover_after_restart()
    first = service.get_job(job.job_id)
    assert first.state == JobState.SETTLED
    again = await service.recover_after_restart()
    assert again == [] and service.get_job(job.job_id).capture_id == first.capture_id  # nothing is repeated


async def test_recovery_ignores_jobs_that_are_fine(api_parts):
    _, service, _ = api_parts
    await locked(service)  # ESCROW_LOCKED: waiting for a worker, not stuck
    await service.post_job()
    assert await service.recover_after_restart() == []


# --------------------------------------------------------------------- readiness --
async def test_ready_reports_each_dependency(api_parts):
    settings, service, runner = api_parts
    body = create_app(settings, service, runner).test_client().get("/api/ready").get_json()
    assert body["ready"] is True and body["checks"]["paypal_mcp"]["tools"] >= 8 and body["checks"]["sandbox"]["backend"] == "subprocess"
    assert body["checks"]["receipt_key"]["key_id"] and body["checks"]["database"]["ok"]


async def test_not_ready_without_a_safe_sandbox(api_parts, monkeypatch):
    settings, service, runner = api_parts
    from agentescrow.arbiter import sandbox_runner

    monkeypatch.setattr(sandbox_runner, "docker_available", lambda: False)
    unsafe_off = replace(settings, allow_unsafe_sandbox=False, sandbox_backend="auto")
    service._settings = unsafe_off  # noqa: SLF001
    response = create_app(unsafe_off, service, runner).test_client().get("/api/ready")
    assert response.status_code == 503 and response.get_json()["checks"]["sandbox"]["ok"] is False


# ------------------------------------------------------------------ stream limits --
def test_stream_limiter_enforces_total_and_per_client_caps():
    limiter = StreamLimiter(total=3, per_key=2)
    assert limiter.acquire("a") and limiter.acquire("a") and not limiter.acquire("a")  # per-client cap
    assert limiter.acquire("b") and not limiter.acquire("c")  # total cap
    limiter.release("a")
    assert limiter.acquire("c")


async def test_the_stream_endpoint_returns_429_when_full_and_frees_slots(api_parts):
    settings, service, runner = api_parts
    streams = StreamLimiter(total=1, per_key=1)
    client = create_app(settings, service, runner, streams=streams).test_client()
    job = await service.post_job()
    await service.cancel_job(job.job_id)  # terminal, so a stream ends by itself
    assert streams.acquire("127.0.0.1")  # someone else holds the only slot
    assert client.get(f"/api/jobs/{job.job_id}/stream").status_code == 429
    streams.release("127.0.0.1")
    assert "event: end" in client.get(f"/api/jobs/{job.job_id}/stream").get_data(as_text=True)
    assert streams.acquire("127.0.0.1")  # the finished stream released its slot


# ---------------------------------------------------------------------- the lock --
def test_a_second_server_cannot_share_the_database(tmp_path):
    first, second = InstanceLock(tmp_path / "db.lock"), InstanceLock(tmp_path / "db.lock")
    first.acquire()
    with pytest.raises(InstanceLockError, match="already using"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


# ------------------------------------------------------------------ demo personas --
async def test_personas_other_than_honest_can_be_disabled_for_production(api_parts):
    settings, service, runner = api_parts
    strict = replace(settings, demo_personas=False)
    service._settings = strict  # noqa: SLF001
    client = create_app(strict, service, runner).test_client(use_cookies=False)
    created = client.post("/api/jobs", json={}).get_json()
    jid, buyer = created["job"]["job_id"], {"Authorization": f"Bearer {created['token']}"}
    client.post(f"/api/jobs/{jid}/accept", json={"worker_id": "w", "worker_email": "w@example.com"})
    client.post(f"/api/jobs/{jid}/escrow", headers=buyer)
    client.get(f"/escrow/success?job_id={jid}")
    assert client.post(f"/api/jobs/{jid}/run", json={"persona": "cheater"}, headers=buyer).status_code == 400
    assert client.post(f"/api/jobs/{jid}/run", json={"persona": "honest"}, headers=buyer).status_code == 202


# ----------------------------------------------------------------- the judge panel --
class FakeLLM:
    """Stands in for a chat model: with_structured_output(...).invoke(...) returns the next scripted assessment."""

    def __init__(self, outcomes):
        self._outcomes, self._lock = list(outcomes), threading.Lock()

    def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ANN003
        outer = self

        class Runner:
            def invoke(self, messages):  # noqa: ANN001
                with outer._lock:  # noqa: SLF001
                    item = outer._outcomes.pop(0)  # noqa: SLF001
                if isinstance(item, Exception):
                    raise item
                return item

        return Runner()


def vote(score, manipulation=False, note="ok"):
    return SemanticAssessment(clarity=score, relevance=score, thoroughness=score, rationale=note, manipulation_suspected=manipulation)


def judge(outcomes, samples=3):
    contract, _ = build_sample_contract()
    panel = LLMSemanticJudge(FakeLLM(outcomes), name="fake", samples=samples)
    return panel.judge(contract, {"solution_code": "x", "explanation": "y"})


async def test_the_panel_takes_the_median_not_the_mean():
    result = judge([vote(0.9), vote(0.95), vote(0.1)])  # one wild outlier
    assert result.score == 0.9 and result.judge == "fake (median of 3)"


async def test_any_single_manipulation_flag_zeroes_the_score():
    result = judge([vote(0.9), vote(0.9), vote(0.9, manipulation=True)])
    assert result.manipulation_suspected and result.score == 0.0


async def test_the_panel_survives_partial_failures_but_not_total_failure():
    assert judge([vote(0.8), RuntimeError("429"), RuntimeError("timeout")]).score == 0.8
    with pytest.raises(JudgeError, match="Semantic judge failed"):
        judge([RuntimeError("down")] * 3)


async def test_a_single_sample_behaves_like_the_original_judge():
    result = judge([vote(0.7)], samples=1)
    assert result.score == 0.7 and result.judge == "fake"
