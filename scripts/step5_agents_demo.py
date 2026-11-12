"""STEP 5: run the real LangChain agents (create_agent + MCP tools + Groq) end to end.

    python -m scripts.step5_agents_demo --persona honest --inprocess
    python -m scripts.step5_agents_demo --persona cheater --inprocess

Needs GROQ_API_KEY. With ``--inprocess`` the MCP servers run inside this process (no extra
terminals). Without it, start both servers first:
    python -m agentescrow.mcp_servers.paypal_escrow_server
    python -m agentescrow.mcp_servers.workbench_server

PAYPAL_MODE=simulated makes the escrow instant (no browser approval); with PAYPAL_MODE=sandbox
the script pauses so you can approve the hold in PayPal.
"""

from __future__ import annotations

import argparse
import asyncio

from agentescrow.arbiter.judge_factory import build_judge
from agentescrow.config import ConfigError
from agentescrow.orchestrator.endpoints import http_endpoints, inprocess_endpoints
from agentescrow.orchestrator.service import EscrowService, PERSONAS
from agentescrow.orchestrator.store import JobStore
from scripts._common import bootstrap


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", choices=PERSONAS, default="honest")
    parser.add_argument("--inprocess", action="store_true")
    args = parser.parse_args()

    settings, log = bootstrap("step5-agents")
    try:
        settings.require_mandate_secret()
        settings.require_groq()
    except ConfigError as exc:
        log.error("%s", exc)
        return 1
    if settings.worker_mode != "agent":
        log.warning("WORKER_MODE=%s: the worker is NOT an LLM. Set WORKER_MODE=agent to use Groq.", settings.worker_mode)

    endpoints = inprocess_endpoints(settings) if args.inprocess else http_endpoints(settings)
    service = EscrowService(settings, JobStore(settings.database_path), endpoints, build_judge(settings))

    log.info("STEP 5: buyer_mode=%s worker_mode=%s judge=%s model=%s", settings.buyer_mode, settings.worker_mode, settings.semantic_judge, settings.groq_model)  # fmt: skip
    job = await service.post_job()
    await service.accept_job(job.job_id, f"{args.persona}-worker", settings.paypal_worker_email)
    job = await service.open_escrow(job.job_id)
    if settings.paypal_mode == "sandbox":
        print(f"\n  Approve the PayPal hold as the BUYER:\n  {job.approve_url}\n")
        input("  Press Enter after approving... ")
    await service.confirm_funding(job.job_id)
    job = await service.run_pipeline(job.job_id, args.persona)

    log.info("RESULT: state=%s outcome=%s", job.state.value, job.decision.outcome.value if job.decision else None)
    for event in service.events(job.job_id):
        print(f"  {event['ts'][11:19]}  {event['kind']:<9} {event['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
