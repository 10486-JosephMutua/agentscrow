"""Builds the LLM agents with ``langchain.agents.create_agent``.

Agents get the *least* tools they need (an allow-list per role), and the buyer agent's
money-critical arguments are pinned by middleware so the model cannot change them.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

import groq
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_groq import ChatGroq

from agentescrow.agents.model_resolver import resolve_groq_model
from agentescrow.agents.prompts import (
    BUYER_SYSTEM, CHEATER_ADDENDUM, SITE_CHEATER_ADDENDUM, SITE_SLOPPY_ADDENDUM, SITE_WORKER_SYSTEM, SLOPPY_ADDENDUM, WORKER_SYSTEM,
)  # fmt: skip
from agentescrow.config import Settings
from agentescrow.domain.models import DELIVERABLE_TOOL_NAME, Deliverable, JobContract, SiteDeliverable
from agentescrow.mcp_client import tool_result_dict
from agentescrow.money import money_str
from agentescrow.sitecheck import SITE_TASK_TYPE

logger = logging.getLogger(__name__)

BUYER_TOOLS = {"create_escrow_order"}
WORKER_TOOLS = {"get_authorization_status", "run_python_tests"}
SITE_WORKER_TOOLS = {"get_authorization_status", "check_site"}
AGENT_RECURSION_LIMIT = 30
TOOL_CALL_RETRIES = 2  # extra attempts after a malformed tool call from the model
_PERSONA_ADDENDA = {"honest": "", "sloppy": SLOPPY_ADDENDUM, "cheater": CHEATER_ADDENDUM}
_SITE_PERSONA_ADDENDA = {"honest": "", "sloppy": SITE_SLOPPY_ADDENDUM, "cheater": SITE_CHEATER_ADDENDUM}


class AgentError(RuntimeError):
    """An agent failed to produce the result the orchestrator needs."""


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Groq chat model. Temperature 0 keeps tool calling and judging as repeatable as possible."""
    settings.require_groq()
    model = resolve_groq_model(settings)
    logger.info("Using Groq model %s", model)
    options = {"base_url": settings.groq_base_url} if settings.groq_base_url else {}
    return ChatGroq(model=model, api_key=settings.groq_api_key, temperature=0, max_retries=2, **options)


# ------------------------------------------------------------------------- buyer --
def _pin_arguments(pinned: dict[str, Any]):
    """Middleware: overwrite named tool arguments with trusted values before the tool runs."""

    @wrap_tool_call
    async def pin(request, handler):  # type: ignore[no-untyped-def]
        tool_call = request.tool_call
        args = dict(tool_call.get("args") or {})
        changed = {k: v for k, v in pinned.items() if args.get(k) != v}
        if changed:
            logger.warning(
                "Pinned %s arguments for %s: model proposed %s",
                sorted(changed),
                tool_call.get("name"),
                {k: ("<token>" if "token" in k else args.get(k)) for k in changed},
            )
        request = request.override(tool_call={**tool_call, "args": {**args, **pinned}})
        return await handler(request)

    return pin


def build_buyer_agent(
    model: BaseChatModel, tools: list[BaseTool], *, job_id: str, amount: Decimal, mandate_token: str
):
    """Buyer agent: opens the escrow order. job_id, amount and mandate are pinned, not model-chosen."""
    pinned = {"job_id": job_id, "amount_usd": money_str(amount), "mandate_token": mandate_token}
    return create_agent(
        model,
        tools,
        system_prompt=BUYER_SYSTEM,
        middleware=[_pin_arguments(pinned)],
        name="buyer_agent",
    )


def find_tool_result(messages: list[BaseMessage], tool_name: str) -> dict[str, Any] | None:
    """Return the payload of the last successful call to ``tool_name`` in an agent transcript."""
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and message.name == tool_name and message.status != "error":
            return tool_result_dict(message)
    return None


async def _invoke(agent, prompt: str, *, retries: int = TOOL_CALL_RETRIES) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Run an agent, turning any failure (model unreachable, rate limited, tool loop that never ends) into AgentError.

    Malformed tool calls (``tool_use_failed``: wrong tool name, invalid JSON) are an expected, usually transient, LLM
    failure, so they are retried a limited number of times before giving up.
    """
    for attempt in range(retries + 1):
        try:
            return await agent.ainvoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config={"recursion_limit": AGENT_RECURSION_LIMIT},
            )
        except AgentError:
            raise
        except groq.BadRequestError as exc:
            if ("tool_use_failed" in str(exc) or "Tool call validation failed" in str(exc)) and attempt < retries:
                logger.warning("Model produced a malformed tool call; retrying (%d/%d): %s", attempt + 1, retries, str(exc)[:300])
                continue
            logger.error("Agent run failed: %s: %s", type(exc).__name__, exc)
            raise AgentError(f"The agent could not finish ({type(exc).__name__}): {str(exc)[:200]}") from exc
        except Exception as exc:  # noqa: BLE001 - the orchestrator only needs to know the agent could not finish
            logger.error("Agent run failed: %s: %s", type(exc).__name__, exc)
            raise AgentError(f"The agent could not finish ({type(exc).__name__}): {str(exc)[:200]}") from exc
    raise AgentError("The agent could not finish: retries exhausted")  # pragma: no cover - loop always returns or raises


async def run_buyer_agent(agent, job_id: str, amount: Decimal) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    prompt = f"Open the escrow for job_id={job_id} with amount_usd={money_str(amount)}."
    logger.info("Buyer agent starting")
    result = await _invoke(agent, prompt)
    order = find_tool_result(result["messages"], "create_escrow_order")
    if not order or "order_id" not in order:
        raise AgentError("Buyer agent finished without creating an escrow order")
    logger.info("Buyer agent created order %s", order["order_id"])
    return order


# ------------------------------------------------------------------------ worker --
def worker_brief(contract: JobContract, authorization_id: str) -> str:
    spec = contract.specification
    criteria = "\n".join(f"- {item}" for item in spec.acceptance_criteria)
    if contract.task_type == SITE_TASK_TYPE:
        return (
            f"Job {contract.task_id}: {spec.title}\n\n"
            f"{spec.description}\n\n"
            f"Buyer preferences (pass this exact JSON to check_site as `preferences`):\n{json.dumps(spec.preferences or {}, indent=2)}\n\n"
            f"What the buyer will check:\n{criteria}\n\n"
            f"Escrow authorization id: {authorization_id}"
        )
    return (
        f"Job {contract.task_id}: {spec.title}\n\n"
        f"{spec.description}\n\n"
        f"Signature: {spec.function_signature}\n"
        f"Module name: {spec.module_name}.py\n\n"
        f"Acceptance criteria:\n{criteria}\n\n"
        f"Public example tests (the buyer also has hidden tests):\n```python\n{spec.public_tests}\n```\n\n"
        f"Escrow authorization id: {authorization_id}"
    )


def _named_schema(schema: type) -> type:
    """Return a subclass whose *class name* is the tool name.

    ``model_config(title=...)`` is not honoured by every langchain version: ToolStrategy may name the tool after
    ``schema.__name__`` ("Deliverable"). gpt-oss then lower-cases it to "deliverable" and Groq rejects the call with
    "attempted to call tool 'deliverable' which was not in request.tools". Naming the class itself removes the ambiguity.
    """
    return type(DELIVERABLE_TOOL_NAME, (schema,), {"__doc__": schema.__doc__, "__module__": schema.__module__})


def build_worker_agent(model: BaseChatModel, tools: list[BaseTool], *, persona: str = "honest", task_type: str = "python_function"):
    if persona not in _PERSONA_ADDENDA:
        raise ValueError(f"Unknown persona {persona!r}; choose one of {sorted(_PERSONA_ADDENDA)}")
    site = task_type == SITE_TASK_TYPE
    system = (SITE_WORKER_SYSTEM + _SITE_PERSONA_ADDENDA[persona]) if site else (WORKER_SYSTEM + _PERSONA_ADDENDA[persona])
    logger.info("Worker agent tools: %s + %s (structured output)", sorted(t.name for t in tools), DELIVERABLE_TOOL_NAME)
    return create_agent(
        model,
        tools,
        system_prompt=system,
        response_format=ToolStrategy(_named_schema(SiteDeliverable if site else Deliverable)),
        name=f"worker_agent_{persona}",
    )


async def run_worker_agent(agent, contract: JobContract, authorization_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    logger.info("Worker agent starting")
    result = await _invoke(agent, worker_brief(contract, authorization_id))
    deliverable = result.get("structured_response")
    if not isinstance(deliverable, (Deliverable, SiteDeliverable)):
        raise AgentError("Worker agent finished without a structured deliverable")
    body = deliverable.index_html if isinstance(deliverable, SiteDeliverable) else deliverable.solution_code
    logger.info("Worker agent delivered %d characters of %s", len(body), "HTML" if isinstance(deliverable, SiteDeliverable) else "code")
    return deliverable.model_dump()
