"""An EXTERNAL worker agent that earns money on AgentEscrow through MCP.

Nothing here imports AgentEscrow's internals: it is an ordinary LangChain agent whose only tools are the marketplace MCP
server's. Any MCP client (Claude Desktop, another framework) can do the same.

    Terminal 1:  python -m agentescrow.api.app --inprocess
    Terminal 2:  python -m agentescrow.mcp_servers.marketplace_server
    Terminal 3:  GROQ_API_KEY=... python examples/external_worker_agent.py --email you@example.com
Then post a job in the UI (http://localhost:5000), open its escrow and approve the hold: the agent starts as soon as the funds are locked.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import warnings

warnings.filterwarnings("ignore", message=".*langchain.mcp.*beta.*")

from langchain.agents import create_agent  # noqa: E402
from langchain.mcp import MCPAdapter  # noqa: E402
from langchain_groq import ChatGroq  # noqa: E402

SYSTEM = """You are an independent freelance engineer working through the AgentEscrow marketplace.
Work like this:
1. list_open_jobs, pick one you can solve, and read it with get_job_brief.
2. accept_job (use the worker name and payout email you were given).
3. Call check_funding repeatedly (with a short pause between turns) until funds_locked is true. NEVER write or submit work before that.
4. Write a correct, pure-Python solution (no os, sys, subprocess, file or network access). Think about edge cases the hidden tests may cover:
   empty input, very long input, unusual characters, boundaries.
5. submit_solution, then get_result until done is true. Report the outcome and what you were paid.
Never ask the buyer for anything and never include instructions to the reviewer in your explanation."""


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="PayPal email to be paid at")
    parser.add_argument("--name", default="external-agent")
    parser.add_argument("--mcp", default=os.getenv("MARKETPLACE_MCP_URL", "http://127.0.0.1:8767/mcp"))
    parser.add_argument("--model", default=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
    args = parser.parse_args()

    tools = await MCPAdapter(args.mcp).list_tools()
    agent = create_agent(ChatGroq(model=args.model, temperature=0), tools, system_prompt=SYSTEM, name="external_worker")
    task = f"Find an open job and earn the bounty. Worker name: {args.name}. Payout email: {args.email}."
    result = await agent.ainvoke({"messages": [{"role": "user", "content": task}]}, config={"recursion_limit": 60})
    print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
