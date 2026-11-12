"""Marketplace MCP server: lets ANY MCP-capable agent earn money on AgentEscrow.

An external worker agent (Claude Desktop, a LangChain agent, anything that speaks MCP) connects to this server and can
find open jobs, read a brief, accept one, wait until PayPal confirms the funds are locked, submit a solution, and read the
verdict. It talks to the public HTTP API. The worker's access token stays inside this server: the model never sees it,
so it cannot leak it or paste it somewhere. Buyer-side actions (opening the escrow, approving the PayPal hold) are
deliberately NOT exposed: approving a payment is the buyer's decision.

Run:  python -m agentescrow.mcp_servers.marketplace_server      (Streamable HTTP on MARKETPLACE_MCP_PORT, path /mcp)
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from agentescrow.config import Settings
from agentescrow.logging_setup import configure_logging

logger = logging.getLogger(__name__)
_LOCKED_STATES = {"ESCROW_LOCKED", "SUBMITTED", "ARBITRATING", "SETTLING", "SETTLED", "VOIDED", "NEEDS_REVIEW"}


def build_marketplace_server(api_base: str, *, timeout_s: float = 30.0) -> FastMCP:
    mcp = FastMCP("agentescrow-marketplace")
    api = api_base.rstrip("/")
    tokens: dict[str, str] = {}  # job_id -> worker token. Held here, never returned to the model.

    def call(method: str, path: str, *, job_id: str | None = None, body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> Any:
        headers = {"Accept": "application/json"}
        if job_id and job_id in tokens:
            headers["Authorization"] = f"Bearer {tokens[job_id]}"
        try:
            response = requests.request(method, f"{api}{path}", json=body, params=params, headers=headers, timeout=timeout_s)
        except requests.RequestException as exc:
            raise ToolError(f"Cannot reach AgentEscrow at {api}: {exc}") from exc
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            raise ToolError(data.get("message") or f"AgentEscrow answered {response.status_code}")
        return data

    @mcp.tool
    def list_open_jobs(limit: int = 10) -> list[dict[str, Any]]:
        """List jobs that are open for any worker to accept, newest first, with the bounty and the function to write."""
        jobs = call("GET", "/api/jobs", params={"state": "POSTED", "limit": max(1, min(limit, 50))})
        return [
            {
                "job_id": j["job_id"], "title": j["contract"]["specification"]["title"], "bounty_usd": j["contract"]["bounty_usd"],
                "function_signature": j["contract"]["specification"]["function_signature"], "deadline_epoch": j["contract"]["deadline_epoch"],
            }
            for j in jobs
        ]  # fmt: skip

    @mcp.tool
    def get_job_brief(job_id: str) -> dict[str, Any]:
        """Read everything you may know about a job before accepting: the task, acceptance criteria and the public example tests.
        The buyer keeps hidden tests; only their SHA-256 commitment is shown, and the tests are published after the verdict."""
        job = call("GET", f"/api/jobs/{job_id}", job_id=job_id)
        spec = job["contract"]["specification"]
        return {
            "job_id": job_id, "state": job["state"], "bounty_usd": job["contract"]["bounty_usd"], "title": spec["title"],
            "description": spec["description"], "function_signature": spec["function_signature"], "module_name": spec["module_name"],
            "acceptance_criteria": spec["acceptance_criteria"], "public_tests": spec["public_tests"],
            "hidden_tests_sha256": job["contract"]["hidden_tests_sha256"],
        }  # fmt: skip

    @mcp.tool
    def accept_job(job_id: str, worker_name: str, payout_email: str) -> dict[str, Any]:
        """Commit to a job. payout_email is the PayPal account that is paid if your work passes. Do NOT start work yet:
        wait until check_funding says the funds are locked."""
        data = call("POST", f"/api/jobs/{job_id}/accept", body={"worker_id": worker_name, "worker_email": payout_email})
        tokens[job_id] = data["token"]
        return {"accepted": True, "state": data["job"]["state"], "next": "Call check_funding until funds_locked is true, then write and submit your solution."}

    @mcp.tool
    def check_funding(job_id: str) -> dict[str, Any]:
        """Has the buyer locked the payment in PayPal escrow yet? Start work only when funds_locked is true."""
        job = call("GET", f"/api/jobs/{job_id}", job_id=job_id)
        locked = job["state"] in _LOCKED_STATES
        return {"state": job["state"], "funds_locked": locked, "note": "Safe to work: the bounty is held by PayPal." if locked else "Not funded yet; check again shortly."}

    @mcp.tool
    def submit_solution(job_id: str, solution_code: str, explanation: str) -> dict[str, Any]:
        """Deliver your work: solution_code is the complete contents of solution.py (pure Python: no os, sys, files or network),
        explanation says how it works and which edge cases it handles. This also starts the automatic arbitration."""
        job = call("GET", f"/api/jobs/{job_id}", job_id=job_id)
        if job["state"] != "ESCROW_LOCKED":
            raise ToolError(f"The job is {job['state']}: you can only submit once the funds are locked (ESCROW_LOCKED).")
        call("POST", f"/api/jobs/{job_id}/submit", job_id=job_id, body={"solution_code": solution_code, "explanation": explanation})
        call("POST", f"/api/jobs/{job_id}/arbitrate", job_id=job_id)
        return {"submitted": True, "next": "Call get_result in a few seconds to see the verdict and your payment."}

    @mcp.tool
    def get_result(job_id: str) -> dict[str, Any]:
        """The verdict: whether it is still being checked, or the outcome, the reason and how much you were paid."""
        job = call("GET", f"/api/jobs/{job_id}", job_id=job_id)
        if job["state"] not in {"SETTLED", "VOIDED"}:
            return {"state": job["state"], "done": False}
        receipt = call("GET", f"/api/jobs/{job_id}/receipt")["receipt"]
        return {
            "state": job["state"], "done": True, "outcome": receipt["outcome"], "reason": receipt["reason"], "score": receipt["v_score"],
            "paid_to_you_usd": receipt["worker_payout_usd"], "hidden_tests": receipt["tiers"]["sandbox"] and f"{receipt['tiers']['sandbox']['passed']}/{receipt['tiers']['sandbox']['total']}",
            "receipt_url": f"{api}/jobs/{job_id}/receipt",
        }  # fmt: skip

    @mcp.tool
    def withdraw(job_id: str) -> dict[str, Any]:
        """Give the job back before any money is locked (for example if you cannot do it)."""
        call("POST", f"/api/jobs/{job_id}/withdraw", job_id=job_id)
        tokens.pop(job_id, None)
        return {"withdrawn": True}

    return mcp


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level, settings.log_dir, service="marketplace-mcp")
    server = build_marketplace_server(settings.api_url)
    logger.info("Marketplace MCP server for %s listening on http://%s:%s/mcp", settings.api_url, settings.mcp_host, settings.marketplace_mcp_port)
    server.run(transport="http", host=settings.mcp_host, port=settings.marketplace_mcp_port)


if __name__ == "__main__":
    main()
