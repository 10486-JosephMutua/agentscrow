# AgentEscrow: submission write-up

Hackathon: *Build What's Next with PayPal and AI*. Repository: `<PUBLIC REPO URL>` (MIT). Demo video: `<YOUTUBE URL>`.
Team: `<NAMES>`.

## One-line pitch

When AI agents hire other AI agents, nobody can safely pay first or deliver first. AgentEscrow holds the money in **PayPal**, lets an arbiter verify the work
automatically, and releases exactly what was earned: everything, a fair fraction, or nothing.

## The problem

Agent-to-agent work has no trust layer. A buyer agent that pays up front can be cheated; a worker agent that delivers first can be stiffed; and a human cannot
referee thousands of tiny jobs. Existing escrow assumes a human reviewer.

## What it does

1. A buyer posts a job (a coding task with hidden tests, or a website judged against the buyer's preferences) and a bounty.
2. A **buyer agent** opens a PayPal **authorize** order through an MCP tool. A signed *spending mandate* caps what the agent may ever ask for; the human approves the hold.
3. A **worker agent** starts only after PayPal confirms the hold. It writes the solution and tests it in a sandbox.
4. A **3-tier arbiter** scores the delivery: schema (30%), hidden tests in a Docker sandbox (40%), and an LLM judge panel (30%, median of 3, any manipulation flag wins).
5. A pure, unit-tested **settlement policy** turns the score into money: **FULL** (capture and pay the worker), **PARTIAL** (pro-rated capture, remainder released) or **VOID**
   (nothing charged). The LLM never decides money; it only proposes sub-scores.
6. An **Ed25519-signed receipt** records the verdict. The hidden tests were committed by SHA-256 before work started and are revealed afterwards, so neither side can rig the check.

## How PayPal is used (central to the product)

| PayPal capability | Used for |
|---|---|
| Orders v2, `intent=AUTHORIZE` | Hold the bounty without charging it |
| Capture (full or partial) | Pay out what the verdict earned |
| Void | Release the whole hold when the work fails |
| Reauthorize | Extend holds older than PayPal's honor period before capture |
| Payouts v1 | Pay the worker's share; the platform keeps a fee |
| Webhooks (signature verified via PayPal's API) | Confirm funding; money facts are always re-read from PayPal |

All calls use the free **PayPal sandbox**. Agents never hold PayPal credentials: capture, void and payout need one-time signed tickets that only the orchestrator issues.

## How AI is used

| Tool | How |
|---|---|
| Groq, `openai/gpt-oss-120b` (with fallbacks) | Buyer agent, worker agent and the Tier-3 judge panel |
| LangChain 1.x (`create_agent`, structured output) | Agent loops; the worker returns its answer through a typed `submit_deliverable` tool |
| MCP (`langchain.mcp`, FastMCP) | PayPal escrow server, workbench server (test runner and site checker) and a **marketplace server** so any external MCP agent (for example Claude Desktop) can find a job, deliver and get paid |
| Docker | Hardened, network-less sandbox for untrusted worker code |
| Stitch | Generated the UI designs (`docs/stitch/`) |

## Technical highlights

- **LLMs propose, code disposes**: money decisions come from a pure function, covered by unit tests.
- **Commit-reveal hidden tests** and **per-job randomized test suites**, so results cannot be memorized or rigged.
- **Anti-gaming arbiter**: AST policy and prompt-injection scan run before any code executes; a red-team "cheater" persona is built in.
- **Fail-closed safety**: no Docker means the job waits in `NEEDS_REVIEW`, never an unsafe fallback (the offline demo opts in to one explicitly).
- **Crash-safe money**: idempotent settlement steps and recovery of interrupted jobs on start-up.
- **Verified end to end** on the real PayPal sandbox with real Groq agents (transcript in the README).

## What I built during the hackathon

`<FILL IN: what is new versus any earlier code, with dates, if the Official Rules ask for it>`

## Challenges

- Models normalise tool names (`submit_deliverable` becomes `deliverable`) and Groq rejects any mismatch; the worker's output tool is now named by its class and
  validation failures are retried.
- Float-free receipts: Python and JavaScript print `1.0` and `1` differently, which broke signatures until the signed body was made float-free.
- Making real LLM workers demo-safe: they are non-deterministic, so scripted personas exist for repeatable FULL, PARTIAL and VOID outcomes.

## What's next

A durable job queue to scale beyond one process, user accounts, and a hosted instance once the sandbox can run on isolated infrastructure.

## Requirements checklist

- [x] Meaningful PayPal integration (sandbox) and meaningful AI
- [x] Working prototype with run instructions (README, "For judges")
- [x] Text description (this file), tools used and how (above)
- [x] MIT license included (`LICENSE`)
- [ ] Demo video under 3 minutes on YouTube (public), showing the project running
- [ ] No third-party trademarks or copyrighted music in the video
- [ ] Repository public, license visible in the About box, links filled in above

## Demo video outline (under 3 minutes)

| Time | Show |
|---|---|
| 0:00 to 0:20 | The problem in two sentences, then the one-line pitch |
| 0:20 to 0:50 | Post a $5 job; buyer agent opens the PayPal order; approve the hold on the sandbox checkout page |
| 0:50 to 1:30 | Worker agent runs; the live timeline shows the three arbiter tiers and the score |
| 1:30 to 2:10 | FULL outcome: capture and payout in the money timeline; open the signed receipt and verify it |
| 2:10 to 2:40 | Re-run with the sloppy and cheating workers: PARTIAL and VOID (use `WORKER_MODE=scripted` for a repeatable result) |
| 2:40 to 3:00 | The marketplace MCP server: an external agent earning a job; close with the repo link |

Record the screen only, with no music. Keep other brands' logos out of frame (browser extensions, editor themes, Docker Desktop); plain text names are fine.