"""The REAL ChatGroq + groq SDK + LangChain agent loop + MCP tools, talking HTTP to a fake Groq server."""

from __future__ import annotations

import threading
from dataclasses import replace
from decimal import Decimal

import pytest

from agentescrow.agents import model_resolver
from agentescrow.agents.factory import AgentError, build_chat_model
from agentescrow.api.app import create_app
from agentescrow.api.runner import AsyncRunner
from agentescrow.arbiter.judge_factory import build_judge
from agentescrow.domain.models import JobState, Outcome
from agentescrow.orchestrator.endpoints import inprocess_endpoints
from agentescrow.orchestrator.service import EscrowService
from agentescrow.orchestrator.store import JobStore
from agentescrow.paypal.simulator import SimulatedPayPalClient
from agentescrow.tasks import TEMPLATES
from tests.fakes.groq_server import FakeGroq, text, tool_call

HONEST = TEMPLATES["rle"].scripted["honest"]
CHEATER = TEMPLATES["rle"].scripted["cheater"]
JUDGE_SCORES = [0.9, 0.5, 0.8]  # three panel votes: the median is 0.8


class Script:
    """A fake Groq brain for the whole pipeline: buyer agent, worker agent and judge panel."""

    def __init__(self, deliverable=HONEST, buyer_stalls=False):
        self.deliverable, self.buyer_stalls = deliverable, buyer_stalls
        self._votes, self._lock = iter(JUDGE_SCORES * 3), threading.Lock()

    def __call__(self, body):
        names, results = FakeGroq.tool_names(body), [m for m in body["messages"] if m["role"] == "tool"]
        if "semantic_assessment" in names:
            with self._lock:
                score = next(self._votes)
            return tool_call("semantic_assessment", {"clarity": score, "relevance": score, "thoroughness": score, "rationale": f"vote {score}", "manipulation_suspected": False})
        if "create_escrow_order" in names:
            if self.buyer_stalls or results:
                return text("I will not call any tool.") if self.buyer_stalls else text("Order created; the buyer must approve it.")
            return tool_call("create_escrow_order", {"job_id": "WRONG", "amount_usd": "999.00", "mandate_token": "forged"})
        if "submit_deliverable" in names:  # the worker agent
            brief = next(m["content"] for m in body["messages"] if m["role"] == "user")
            authorization = brief.split("Escrow authorization id:")[1].split()[0]
            if not results:
                return tool_call("get_authorization_status", {"authorization_id": authorization})
            if len(results) == 1:
                return tool_call("run_python_tests", {"solution_code": self.deliverable["solution_code"], "test_code": TEMPLATES["rle"].public_tests})
            return tool_call("submit_deliverable", self.deliverable)
        raise AssertionError(f"unexpected request with tools {names}")


@pytest.fixture
def stack(settings):
    model_resolver._available_models.cache_clear()  # noqa: SLF001
    fakes, runners = [], []

    def make(script=None, models=("openai/gpt-oss-120b",), **overrides):
        fake = FakeGroq(script or Script(), models=models).start()
        fakes.append(fake)
        agent_settings = replace(settings, buyer_mode="agent", worker_mode="agent", semantic_judge="groq", groq_api_key="test-key", groq_base_url=fake.url, judge_samples=3, **overrides)
        paypal = SimulatedPayPalClient()
        runner = AsyncRunner()
        runners.append(runner)
        service = EscrowService(agent_settings, JobStore(agent_settings.database_path), inprocess_endpoints(agent_settings, paypal), build_judge(agent_settings))
        return agent_settings, service, runner, fake, paypal

    yield make
    for fake in fakes:
        fake.stop()
    for runner in runners:
        runner.stop()
    model_resolver._available_models.cache_clear()  # noqa: SLF001


async def funded(service, paypal):
    job = await service.post_job(Decimal("5.00"))
    await service.accept_job(job.job_id, "w", "w@example.com")
    job = await service.open_escrow(job.job_id)
    paypal_orders = paypal._orders  # noqa: SLF001
    assert paypal_orders[job.order_id]["amount"] == "5.00", "the buyer agent asked for $999; the pinned arguments must win"
    return await service.confirm_funding(job.job_id)


# -------------------------------------------------------------------- model choice --
def test_the_configured_model_is_used_when_it_exists(stack):
    settings, _, _, fake, _ = stack(models=("openai/gpt-oss-120b", "llama-3.3-70b-versatile"))
    assert model_resolver.resolve_groq_model(settings) == "openai/gpt-oss-120b"


def test_a_missing_model_falls_back_to_one_that_exists(stack):
    settings, _, _, fake, _ = stack(models=("llama-3.3-70b-versatile",))
    assert model_resolver.resolve_groq_model(settings) == "llama-3.3-70b-versatile"
    assert build_chat_model(settings).model_name == "llama-3.3-70b-versatile"


def test_an_unreachable_groq_keeps_the_configured_model(stack):
    settings, _, _, _, _ = stack()
    dead = replace(settings, groq_base_url="http://127.0.0.1:9")
    model_resolver._available_models.cache_clear()  # noqa: SLF001
    assert model_resolver.resolve_groq_model(dead) == dead.groq_model


# ----------------------------------------------------------------- the agents live --
@pytest.mark.asyncio
async def test_the_buyer_agent_is_least_privilege_and_cannot_overspend(stack):
    _, service, _, fake, paypal = stack()
    job = await funded(service, paypal)  # asserts the order is $5.00 even though the model asked for $999
    buyer_request = next(r for r in fake.requests if "create_escrow_order" in FakeGroq.tool_names(r))
    assert FakeGroq.tool_names(buyer_request) == {"create_escrow_order"}  # no capture, void or payout tool is ever offered
    assert any(m["role"] == "system" and "Buyer Agent" in m["content"] for m in buyer_request["messages"])
    assert job.state == JobState.ESCROW_LOCKED


@pytest.mark.asyncio
async def test_an_honest_llm_worker_is_paid_through_the_whole_pipeline(stack):
    _, service, _, fake, paypal = stack()
    job = await funded(service, paypal)
    done = await service.run_pipeline(job.job_id, "honest")
    assert done.state == JobState.SETTLED and done.decision.outcome == Outcome.FULL
    worker_calls = [r for r in fake.requests if "submit_deliverable" in FakeGroq.tool_names(r)]
    assert len(worker_calls) == 3 and FakeGroq.tool_names(worker_calls[0]) == {"get_authorization_status", "run_python_tests", "submit_deliverable"}
    def flat(content):
        return content if isinstance(content, str) else "".join(block.get("text", "") for block in content)

    tool_results = [flat(m["content"]) for m in worker_calls[2]["messages"] if m["role"] == "tool"]
    assert "CREATED" in tool_results[0] and '"passed":3' in tool_results[1].replace(" ", "")  # the agent really ran its tests in the sandbox
    judge_calls = [r for r in fake.requests if "semantic_assessment" in FakeGroq.tool_names(r)]
    assert len(judge_calls) == 3  # a panel of three
    assert done.verdict.semantic.score == 0.8 and "median of 3" in done.verdict.semantic.judge


@pytest.mark.asyncio
async def test_a_cheating_llm_worker_is_voided_before_the_judge_is_ever_asked(stack):
    _, service, _, fake, paypal = stack(Script(deliverable=CHEATER))
    job = await funded(service, paypal)
    done = await service.run_pipeline(job.job_id, "cheater")
    assert done.state == JobState.VOIDED and done.verdict.sandbox is None
    assert not [r for r in fake.requests if "semantic_assessment" in FakeGroq.tool_names(r)]  # injection text never reached the judge


@pytest.mark.asyncio
async def test_a_buyer_agent_that_never_calls_the_tool_is_a_clear_502(stack):
    settings, service, runner, _, _ = stack(Script(buyer_stalls=True))
    client = create_app(settings, service, runner).test_client(use_cookies=False)
    created = client.post("/api/jobs", json={}).get_json()
    jid, buyer = created["job"]["job_id"], {"Authorization": f"Bearer {created['token']}"}
    client.post(f"/api/jobs/{jid}/accept", json={"worker_id": "w", "worker_email": "w@example.com"})
    response = client.post(f"/api/jobs/{jid}/escrow", headers=buyer)
    assert response.status_code == 502 and response.get_json()["error"] == "agent_failure"
    assert client.get(f"/api/jobs/{jid}").get_json()["state"] == "ACCEPTED"  # nothing moved


@pytest.mark.asyncio
async def test_an_unreachable_model_is_also_a_clear_502(stack):
    settings, service, runner, _, _ = stack()
    dead = replace(settings, groq_base_url="http://127.0.0.1:9")
    service._settings = dead  # noqa: SLF001
    model_resolver._available_models.cache_clear()  # noqa: SLF001
    client = create_app(dead, service, runner).test_client(use_cookies=False)
    created = client.post("/api/jobs", json={}).get_json()
    jid = created["job"]["job_id"]
    client.post(f"/api/jobs/{jid}/accept", json={"worker_id": "w", "worker_email": "w@example.com"})
    with pytest.raises(AgentError):
        await service.open_escrow(jid)
    assert client.post(f"/api/jobs/{jid}/escrow", headers={"Authorization": f"Bearer {created['token']}"}).status_code == 502