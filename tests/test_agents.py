"""Agent wiring is tested with a scripted fake chat model (no network, no Groq key)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agentescrow.agents.factory import (
    AgentError, BUYER_TOOLS, WORKER_TOOLS, build_buyer_agent, build_worker_agent, run_buyer_agent, run_worker_agent,
)  # fmt: skip
from agentescrow.domain.mandate import issue_mandate
from agentescrow.mcp_client import McpToolbox
from agentescrow.mcp_servers.paypal_escrow_server import build_paypal_server
from agentescrow.mcp_servers.workbench_server import build_workbench_server
from agentescrow.paypal.simulator import SimulatedPayPalClient
from agentescrow.samples import SCRIPTED_DELIVERABLES, build_sample_contract
from tests.conftest import TEST_SECRET

pytestmark = pytest.mark.asyncio


class ScriptedModel(BaseChatModel):
    """Returns pre-written AI messages in order, ignoring the prompt."""

    script: list = []
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        message = self.script[self.cursor]
        self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def _call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


async def test_buyer_agent_cannot_change_the_amount(settings):
    paypal = await McpToolbox.connect(build_paypal_server(settings, SimulatedPayPalClient()))
    mandate = issue_mandate(TEST_SECRET, job_id="job_a1", max_amount=Decimal("5.00"))
    # The "model" tries to lock $999 with a made-up mandate; middleware must overwrite both.
    model = ScriptedModel(
        script=[
            _call("create_escrow_order", {"job_id": "job_a1", "amount_usd": "999.00", "mandate_token": "fake"}, "c1"),
            AIMessage(content="Order created; the buyer must approve it."),
        ]
    )
    agent = build_buyer_agent(
        model, paypal.select(BUYER_TOOLS), job_id="job_a1", amount=Decimal("5.00"), mandate_token=mandate
    )
    order = await run_buyer_agent(agent, "job_a1", Decimal("5.00"))
    assert order["order_id"].startswith("SIM-ORDER-")


async def test_buyer_agent_without_an_order_is_an_error(settings):
    paypal = await McpToolbox.connect(build_paypal_server(settings, SimulatedPayPalClient()))
    mandate = issue_mandate(TEST_SECRET, job_id="job_a1", max_amount=Decimal("5.00"))
    model = ScriptedModel(script=[AIMessage(content="I could not do it.")])
    agent = build_buyer_agent(
        model, paypal.select(BUYER_TOOLS), job_id="job_a1", amount=Decimal("5.00"), mandate_token=mandate
    )
    with pytest.raises(AgentError):
        await run_buyer_agent(agent, "job_a1", Decimal("5.00"))


async def test_worker_agent_returns_a_structured_deliverable(settings):
    paypal = await McpToolbox.connect(build_paypal_server(settings, SimulatedPayPalClient()))
    workbench = await McpToolbox.connect(build_workbench_server(settings))
    contract, _ = build_sample_contract()
    honest = SCRIPTED_DELIVERABLES["honest"]
    tools = paypal.select({"get_authorization_status"}) + workbench.select({"run_python_tests"})
    model = ScriptedModel(
        script=[
            _call(
                "run_python_tests",
                {"solution_code": honest["solution_code"], "test_code": contract.specification.public_tests},
                "c1",
            ),
            _call("submit_deliverable", honest, "c2"),
        ]
    )
    agent = build_worker_agent(model, tools, persona="honest")
    deliverable = await run_worker_agent(agent, contract, "AUTH-1")
    assert "def rle_encode" in deliverable["solution_code"]


async def test_workers_cannot_reach_settlement_tools(settings):
    paypal = await McpToolbox.connect(build_paypal_server(settings, SimulatedPayPalClient()))
    assert {t.name for t in paypal.select(WORKER_TOOLS & set(paypal.names))} == {"get_authorization_status"}
    assert not ({"capture_escrow", "void_escrow", "pay_worker"} & (BUYER_TOOLS | WORKER_TOOLS))


async def test_unknown_persona_is_rejected():
    with pytest.raises(ValueError):
        build_worker_agent(ScriptedModel(script=[]), [], persona="wizard")