"""An external agent earning money through the marketplace MCP server, over real HTTP all the way down."""

from __future__ import annotations

import threading
import time

import pytest
import requests
from werkzeug.serving import make_server

from agentescrow.api.app import create_app
from agentescrow.mcp_client import McpToolbox, ToolCallFailed
from agentescrow.mcp_servers.marketplace_server import build_marketplace_server
from agentescrow.tasks import TEMPLATES
from tests.fakes.groq_server import FakeGroq, text, tool_call

HONEST = TEMPLATES["rle"].scripted["honest"]


@pytest.fixture
def live(api_parts):
    settings, service, runner = api_parts
    server = make_server("127.0.0.1", 0, create_app(settings, service, runner), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    yield base, settings
    server.shutdown()


def post_job(base):
    created = requests.post(f"{base}/api/jobs", json={"bounty_usd": "5.00"}, timeout=20).json()
    return created["job"]["job_id"], {"Authorization": f"Bearer {created['token']}"}


def fund(base, job_id, buyer):
    requests.post(f"{base}/api/jobs/{job_id}/escrow", headers=buyer, timeout=30).raise_for_status()
    requests.get(f"{base}/escrow/success", params={"job_id": job_id}, allow_redirects=False, timeout=30)


def wait_state(base, job_id, states, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = requests.get(f"{base}/api/jobs/{job_id}", timeout=10).json()["state"]
        if state in states:
            return state
        time.sleep(0.2)
    raise AssertionError(f"stuck in {state}")


@pytest.mark.asyncio
async def test_a_worker_agent_can_find_accept_deliver_and_get_paid(live):
    base, _ = live
    job_id, buyer = post_job(base)
    tools = await McpToolbox.connect(build_marketplace_server(base))
    assert tools.names == ["accept_job", "check_funding", "get_job_brief", "get_result", "list_open_jobs", "submit_solution", "withdraw"]

    open_jobs = await tools.call("list_open_jobs")
    assert job_id in str(open_jobs)
    brief = await tools.call("get_job_brief", job_id=job_id)
    assert brief["function_signature"] == "def rle_encode(s: str) -> str" and len(brief["hidden_tests_sha256"]) == 64
    assert "test_random_cases" not in str(brief) and "test_run_longer" not in str(brief)  # the hidden tests are not in the brief

    accepted = await tools.call("accept_job", job_id=job_id, worker_name="ext-agent", payout_email="agent@example.com")
    assert accepted["accepted"] and "token" not in str(accepted).lower()  # the model never sees its access token
    assert (await tools.call("check_funding", job_id=job_id))["funds_locked"] is False
    with pytest.raises(ToolCallFailed, match="only submit once the funds are locked"):
        await tools.call("submit_solution", job_id=job_id, solution_code=HONEST["solution_code"], explanation=HONEST["explanation"])

    fund(base, job_id, buyer)  # the BUYER approves; the worker agent cannot
    assert (await tools.call("check_funding", job_id=job_id))["funds_locked"] is True
    assert (await tools.call("submit_solution", job_id=job_id, solution_code=HONEST["solution_code"], explanation=HONEST["explanation"]))["submitted"]
    wait_state(base, job_id, {"SETTLED"})
    result = await tools.call("get_result", job_id=job_id)
    assert result["done"] and result["outcome"] == "FULL" and result["paid_to_you_usd"] == "4.67" and result["hidden_tests"] == "9/9"


@pytest.mark.asyncio
async def test_each_marketplace_server_only_holds_its_own_tokens(live):
    base, _ = live
    job_id, _ = post_job(base)
    one = await McpToolbox.connect(build_marketplace_server(base))
    two = await McpToolbox.connect(build_marketplace_server(base))
    await one.call("accept_job", job_id=job_id, worker_name="one", payout_email="one@example.com")
    with pytest.raises(ToolCallFailed):
        await two.call("withdraw", job_id=job_id)  # server two never accepted: it has no token for this job


@pytest.mark.asyncio
async def test_an_agent_cannot_approve_payments_or_cancel(live):
    base, _ = live
    tools = await McpToolbox.connect(build_marketplace_server(base))
    assert not {"open_escrow", "confirm_funding", "cancel", "capture_escrow", "pay_worker"} & set(tools.names)


@pytest.mark.asyncio
async def test_api_errors_become_clear_tool_errors(live):
    base, _ = live
    tools = await McpToolbox.connect(build_marketplace_server(base))
    with pytest.raises(ToolCallFailed, match="No job"):
        await tools.call("get_job_brief", job_id="job_missing")
    dead = await McpToolbox.connect(build_marketplace_server("http://127.0.0.1:9"))
    with pytest.raises(ToolCallFailed, match="Cannot reach AgentEscrow"):
        await dead.call("list_open_jobs")


@pytest.mark.asyncio
async def test_a_real_langchain_agent_earns_the_bounty_via_mcp(live):
    """Real ChatGroq -> fake Groq HTTP -> real MCP marketplace server -> real API -> arbiter -> simulated PayPal."""
    from langchain.agents import create_agent
    from langchain.mcp import MCPAdapter
    from langchain_groq import ChatGroq

    base, _ = live
    job_id, buyer = post_job(base)

    def brain(body):
        results = [m for m in body["messages"] if m["role"] == "tool"]
        step = len(results)
        if step == 0:
            return tool_call("list_open_jobs", {"limit": 5})
        if step == 1:
            return tool_call("get_job_brief", {"job_id": job_id})
        if step == 2:
            return tool_call("accept_job", {"job_id": job_id, "worker_name": "ext", "payout_email": "ext@example.com"})
        if step == 3:
            fund(base, job_id, buyer)  # meanwhile the human buyer approves the hold
            return tool_call("check_funding", {"job_id": job_id})
        if step == 4:
            return tool_call("submit_solution", {"job_id": job_id, "solution_code": HONEST["solution_code"], "explanation": HONEST["explanation"]})
        if step == 5:
            wait_state(base, job_id, {"SETTLED", "VOIDED"})
            return tool_call("get_result", {"job_id": job_id})
        return text("Done: paid in full.")

    fake = FakeGroq(brain).start()
    try:
        tools = await MCPAdapter(build_marketplace_server(base)).list_tools()
        agent = create_agent(ChatGroq(model="openai/gpt-oss-120b", api_key="k", base_url=fake.url, temperature=0), tools, system_prompt="You are a worker.")
        result = await agent.ainvoke({"messages": [{"role": "user", "content": "earn a bounty"}]}, config={"recursion_limit": 30})
    finally:
        fake.stop()
    assert "paid in full" in result["messages"][-1].content
    assert requests.get(f"{base}/api/jobs/{job_id}", timeout=10).json()["state"] == "SETTLED"
    offered = FakeGroq.tool_names(fake.requests[0])
    assert offered == {"list_open_jobs", "get_job_brief", "accept_job", "check_funding", "submit_solution", "get_result", "withdraw"}
