from decimal import Decimal

import pytest

from agentescrow.domain.models import JobState
from agentescrow.orchestrator.store import JobNotFound, JobStore, StaleJobError
from agentescrow.samples import build_sample_contract


def _job():
    from agentescrow.domain.models import Job

    contract, hidden = build_sample_contract(Decimal("5.00"))
    return Job(job_id=contract.task_id, contract=contract, hidden_tests=hidden)


def test_roundtrip_preserves_hidden_tests_internally(tmp_path):
    store = JobStore(tmp_path / "s.db")
    job = store.create(_job())
    loaded = store.get(job.job_id)
    assert loaded.hidden_tests == job.hidden_tests and loaded.contract.bounty_usd == Decimal("5.00")
    assert "hidden_tests" not in loaded.public_view()


def test_optimistic_save_blocks_concurrent_state_changes(tmp_path):
    store = JobStore(tmp_path / "s.db")
    job = store.create(_job())
    a, b = store.get(job.job_id), store.get(job.job_id)
    a.state = JobState.ACCEPTED
    store.save(a, expected_state=JobState.POSTED)
    b.state = JobState.CANCELLED
    with pytest.raises(StaleJobError):
        store.save(b, expected_state=JobState.POSTED)
    assert store.get(job.job_id).state == JobState.ACCEPTED


def test_missing_jobs_and_event_ordering(tmp_path):
    store = JobStore(tmp_path / "s.db")
    with pytest.raises(JobNotFound):
        store.get("nope")
    job = store.create(_job())
    first = store.add_event(job.job_id, "state", "one")
    second = store.add_event(job.job_id, "paypal", "two", {"x": 1})
    assert [e["message"] for e in store.events(job.job_id)] == ["one", "two"]
    assert [e["message"] for e in store.events(job.job_id, after_id=first)] == ["two"]
    assert second > first and store.events(job.job_id)[1]["data"] == {"x": 1}
