# AgentEscrow

**Escrow and autonomous arbitration for AI-agent payments, built on the PayPal sandbox.**

> A buyer posts a job. PayPal **authorizes** (holds) the bounty. A worker agent does the work. A 3-tier arbiter verifies it.
> Only then does money move: **full capture + payout**, a **pro-rated partial capture**, or a **void** that charges the buyer nothing.
> Every verdict is a **signed receipt** anyone can verify, against hidden tests that were **committed by hash** before the work began.

Built for the *Build What's Next with PayPal and AI* hackathon. PayPal (Orders v2 authorize/capture/void/reauthorize, Payouts, webhooks) is the
core of the product, and AI is used three ways: a Groq-hosted **buyer agent**, a **worker agent**, and an **LLM judge panel**, all talking to
PayPal and to each other through **MCP**. [`SUBMISSION.md`](SUBMISSION.md) has the write-up, the tools list and a requirements checklist.

## For judges: run it in 5 minutes (no keys, no PayPal account, no Docker)

You need **Python 3.12+** and, for the web UI, **Node 22+**. Everything runs on your machine.

```bash
git clone <this repo> && cd agentescrow
python -m venv venv
source venv/bin/activate            # Windows PowerShell:  venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m scripts.quickstart        # writes .env with fresh secrets, builds the UI once, starts the server
```

Open **http://localhost:5000** and click **Run the guided demo**. It posts a $5 job and gives your browser both seats (buyer and worker). In this mode the PayPal hold is simulated (approve it if the page asks); on the job page pick a worker from **"Which worker agent should take this job?"** and click **Run worker agent**. You will see the arbiter's
three tiers, the settlement decision, the PayPal money timeline and a signed receipt you can verify in the page. Run three jobs, one per worker, to see every outcome.

This offline mode uses an in-memory **PayPal simulator** and deterministic scripted workers, so it needs nothing from you. Every simulated receipt is flagged as simulated.

| Worker | What it delivers | Outcome |
|---|---|---|
| Honest | a correct solution | **FULL**: capture $5.00, pay the worker, platform fee kept |
| Sloppy | works, but caps run lengths at 9 so it fails the edge-case tests | **PARTIAL**: pro-rated capture, the rest of the hold is released |
| Cheating | hard-coded answers plus a prompt-injection note aimed at the judge | **VOID**: the buyer is charged nothing |

Other no-key checks:

```bash
python -m scripts.step4_arbiter_demo        # the 3 personas straight through the arbiter, with scores
python -m scripts.site_demo                 # a second task type: build a website against the buyer's preferences (opens a report)
pytest                                      # the backend test suite, no network needed (pip install -r requirements-dev.txt first)
```

*Troubleshooting.* No Node? The API and `site_demo` still work; install Node 22 and re-run `python -m scripts.quickstart`, or build the UI by hand with
`cd frontend && npm ci && npm run build`. No Docker? The offline mode falls back to an unisolated subprocess for the built-in templates, which is fine on your own
machine. With Docker running, build the sandbox image once (`docker build -t agentescrow-sandbox -f docker/sandbox.Dockerfile .`) and worker code runs in a hardened container instead.
Port 5000 busy? Set `API_PORT` in `.env`. `python -m scripts.quickstart --force` regenerates `.env`.

## Full run: real PayPal sandbox, real AI agents

This is the mode used in the demo video. It needs three things that only you can supply:

1. **PayPal sandbox**: a REST app (Sandbox) from the PayPal Developer dashboard, its client id and secret, a sandbox **Business** account (the platform) and a sandbox **Personal** account (the buyer, who approves the hold). Enable **Payouts** on the app.
2. **Groq API key** (free tier works): the agents and the judge use `openai/gpt-oss-120b`.
3. **Docker** with the sandbox image, so worker code runs isolated.

```bash
python -m scripts.quickstart --real        # writes .env from .env.example with fresh secrets; then add the keys below
#   PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_WORKER_EMAIL (a sandbox account that receives payouts), GROQ_API_KEY
docker build -t agentescrow-sandbox -f docker/sandbox.Dockerfile .
python -m scripts.step1_check_environment  # packages, keys, PayPal OAuth, Groq model, Docker
python -m agentescrow.api.app --inprocess  # server on http://localhost:5000
python -m scripts.step6_demo_client        # in a second terminal: runs the honest, sloppy and cheater workers
```

When the client prints a `sandbox.paypal.com/checkoutnow?token=...` link, open it, log in as the sandbox **Personal** account, approve the hold, then press Enter.
Real LLM workers are not deterministic: the "sloppy" prompt sometimes still yields correct code (and a FULL payout). For a repeatable FULL, PARTIAL and VOID,
use the scripted workers (`WORKER_MODE=scripted`). Optional: give the server a public URL and set `PAYPAL_WEBHOOK_ID` to receive PayPal webhooks instead of polling.

**A real run, as recorded by the client** (PayPal sandbox, Groq agents, Docker sandbox):

```
18:48:25  state     Buyer posted job 'Run-length encoding' with a $5.00 bounty
18:48:25  mandate   Signed spending mandate issued: escrow capped at $5.00
18:48:25  commitment Hidden tests committed: SHA-256 98569aea884b5ef7…
18:48:37  paypal    PayPal order 37G731726P969963J created (intent AUTHORIZE); waiting for buyer approval
18:53:51  paypal    PayPal authorization 5GA66889ER9521600 holds $5.00
18:53:58  agent     Funds confirmed locked; worker agent (honest) starting
18:54:45  state     Worker submitted a deliverable
18:54:57  tier      Tier 1 schema: PASS   |   Integrity gate: PASS
18:54:57  tier      Tier 2 hidden tests: 9/9 passed (docker sandbox)
18:54:57  tier      Tier 3 semantic judge: 0.97   |   Verification score V = 0.99
18:54:57  decision  Decision: FULL - V=0.99: all hidden tests passed
18:55:01  paypal    Captured $5.00 (capture 3PX708616J964373A)
18:55:02  paypal    Paid worker $4.67 (batch R8HD64Q3TLLT6); platform fee $0.33
```

## Hackathon requirements, and where to see each

| Requirement | Where |
|---|---|
| Meaningful PayPal integration (sandbox) | `agentescrow/paypal/client.py` (Orders v2 authorize, capture, void, reauthorize; Payouts; webhook verification), exposed to agents by `agentescrow/mcp_servers/paypal_escrow_server.py` |
| Meaningful AI | `agentescrow/agents/` (LangChain buyer and worker agents on Groq), `agentescrow/arbiter/semantic_judge.py` (judge panel, median of 3, manipulation flag) |
| Working prototype / functional demo | The two run paths above; React UI in `frontend/`; HTTP API in `agentescrow/api/app.py` |
| Documentation | This README, [`SUBMISSION.md`](SUBMISSION.md), and the reference sections below |
| Open source, license visible | MIT, [`LICENSE`](LICENSE) |

## How it works

```
Buyer --create_escrow_order--> PayPal MCP server --AUTHORIZE order--> PayPal            (signed spending mandate caps the amount)
  buyer approves the hold  ->  funds locked (webhook or return URL; both re-checked with PayPal)
Worker agent: waits for PayPal to confirm the hold -> writes code -> tests it in the sandbox   (internal agent, OR any external MCP agent)
Arbiter: Tier 1 schema (30%) -> integrity gate -> Tier 2 hidden pytest in Docker (40%) -> Tier 3 LLM judge panel (30%, median of 3)
Settlement policy (pure function): FULL | PARTIAL | VOID  ->  capture / void / reauthorize / payout via signed one-time tickets
Receipt: Ed25519-signed; hidden tests revealed after the verdict and checked against the commitment
```

## What makes it stand out

| Idea | Where |
|---|---|
| **Any agent can earn here.** A marketplace MCP server lets Claude Desktop, LangChain or any MCP client find a job, accept, deliver and get paid. The agent never sees its access token and cannot approve payments. | `mcp_servers/marketplace_server.py`, `examples/external_worker_agent.py` |
| **Cryptographically verifiable verdicts.** Ed25519-signed receipts, public key published, offline verifier, browser-side audit. The signed body is float-free so it verifies identically from Python, JavaScript or anything else. | `domain/receipt.py`, `scripts/verify_receipt.py` |
| **Commit-reveal hidden tests.** A SHA-256 of the hidden suite is public when the job is posted; the arbiter refuses tests that no longer match; the tests are published after the verdict. A buyer cannot rig the tests after seeing the work. | `tasks.py`, `orchestrator/service.py` |
| **Per-job randomized tests.** Built-in templates (run-length encoding, roman numerals, balanced brackets) generate fresh edge-case + random-case suites for every job, so revealed tests cannot be memorized. | `tasks.py` |
| **Bring your own task, linted.** Buyers define a task with tests and a reference solution; the sandbox proves the reference passes deterministically and that a do-nothing stub fails, and rejects prompt-injection in the description. | `tasks.py` |
| **LLMs propose, code disposes.** The judge returns sub-scores; a pure unit-tested function decides money. Any failed gate voids the hold. | `domain/settlement.py` |
| **Judge panel.** Median of N samples; any manipulation flag wins; partial failures tolerated. | `arbiter/semantic_judge.py` |
| **Signed spending mandates and settlement tickets.** The payment server refuses orders above the cap; capture, void, reauthorize and payout need one-time signed tickets that agents never hold. | `domain/mandate.py`, `mcp_servers/paypal_escrow_server.py` |
| **Anti-gaming arbiter.** Hidden tests; AST policy and prompt-injection scan run *before* any code executes; report-tamper cross-check. | `arbiter/integrity.py`, `arbiter/sandbox_runner.py` |

## Security model

| Threat | Defence |
|---|---|
| Stolen access tokens (XSS) | Browsers hold access in **HttpOnly, SameSite=Strict** cookies; page scripts never see a token. Operator login also uses a cookie. |
| Cross-site request forgery | `SameSite=Strict` plus an `Origin`/`Sec-Fetch-Site` check on every state-changing request (verified in a real browser). |
| A griefer accepting every job | The buyer can **reject** a worker (and a worker can withdraw) before funding; the released worker's access dies instantly (worker epochs). |
| Untrusted worker code | Runs only in a hardened Docker container (no network, read-only, dropped capabilities, resource limits, nothing mounted). **Fails closed**: no Docker means the job waits in `NEEDS_REVIEW`, never an unsafe fallback. |
| Hung sandbox or Docker daemon | Timeouts at every layer; the client process is force-killed and reaped, never waited on unboundedly. |
| Server crash mid-job | On start-up the orchestrator **recovers** interrupted arbitrations and settlements; money steps are idempotent. |
| Two servers on one database | A single-instance lock refuses the second server. |
| Connection exhaustion | Live streams are capped in total and per client; job creation, task linting and operator login are rate-limited. |
| Authorization expiring | Holds older than PayPal's 3-day honor period are reauthorized once before capture; a sweeper closes overdue jobs (buyer pays nothing). |
| Spoofed webhooks | Verified through PayPal's API using the **raw bytes** of the event; duplicates ignored; money-relevant facts re-read from PayPal. |

## Verified against documentation (things worth knowing)

* **`langchain-mcp-adapters` was replaced in LangChain 1.4**: `MultiServerMCPClient` is now `MCPAdapter` in `langchain.mcp` (`langchain[mcp]`, **beta**). Confined to `agentescrow/mcp_client.py`.
* **PayPal Payouts v1 uses `currency`** (not `currency_code`) in `amount`; Orders v2 `application_context` is deprecated for `payment_source.paypal.experience_context`.
* Webhook verification needs the event **byte-for-byte**; reauthorization returns a **new** authorization id (the job switches to it).
* A2A: the discovery card is served at `/.well-known/agent-card.json`, but it is **a discovery card only** (jobs go through the REST API and MCP server, not A2A message endpoints) and says so itself.
* Signed receipts must not contain floats: Python writes `1.0` where JavaScript reads `1`. A real browser found this, and a regression test now simulates the JS round trip.

## How this was verified, and what still is not

| Layer | How it was tested | Real? |
|---|---|---|
| Business rules, state machine, settlement, mandates, sessions, CSRF, roles | 261 backend tests | yes |
| `PayPalClient` + MCP server + orchestrator | Run against a **strict fake PayPal over real HTTP** (rejects `currency_code` in payouts, deprecated fields, over-capture; replays idempotency keys; verifies raw-byte webhook signatures) | real HTTP, **fake PayPal** |
| `ChatGroq` + LangChain agents + MCP tools + judge panel | Run against a **fake Groq server over real HTTP**; asserts the tool schemas actually sent (least privilege), pinned arguments, 502 mapping | real HTTP, **fake Groq** |
| Docker sandbox command path | Run against a **stand-in `docker` executable** that refuses unsafe command lines | real processes, **no real daemon** |
| UI | 61 component/page tests, a Node smoke test through the UI's own client, and **9 real-Chrome scenarios** (guided demo, templates, custom task, reject worker, CSRF attack, operator login, receipt audit, mobile) | yes |
| Production server | The browser and smoke suites run against **waitress**, including live streaming | yes |

**Exercised on a real stack (12 Nov 2026):** the real PayPal sandbox (authorize, capture, payout), real Groq agents and judge panel, and a real Docker
sandbox, through `scripts.step6_demo_client` (transcript above). **Not covered by automated tests:** the Docker/compose image builds and the CI workflow.
`python -m scripts.step1_check_environment` verifies PayPal, Groq and Docker on any machine in minutes. The Stitch designs are in `docs/stitch/`.

Honest remaining limits (a hosted demo is deliberately not offered: untrusted worker code needs a Docker daemon, and the unisolated fallback must never face the public internet): single-process by design (a durable queue would be the next step to scale out); one human-less trust root (the
platform signs receipts); no user accounts (access is per-job capability); the A2A card is discovery only; `langchain.mcp` is beta.

## Setup

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                  # then edit it
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into MANDATE_SECRET (and make an ADMIN_TOKEN the same way)
docker build -t agentescrow-sandbox -f docker/sandbox.Dockerfile .   # required to run worker code safely
pytest                                                # 261 tests, no network needed (about 3 minutes)
cd frontend && npm ci && npm test && npm run build    # 61 tests, then builds frontend/dist
```

**PayPal sandbox:** create a REST app (Sandbox) in the developer dashboard, put its client id and secret in `.env`, note your sandbox
**Business** and **Personal** accounts, and enable **Payouts**. **Webhooks (recommended):** give the server a public URL, add a webhook for your
app pointing at `https://<host>/api/webhooks/paypal` with the events listed in `.env.example`, and put its **Webhook ID** in `PAYPAL_WEBHOOK_ID`.
**No Docker yet?** For local development only, set `ALLOW_UNSAFE_SANDBOX=true`.

## Run it

| Step | Command | What it proves |
|---|---|---|
| 1a | `python -m scripts.step1_check_environment` | packages, keys, PayPal OAuth, Groq model, Docker |
| 1b | `python -m scripts.step1_paypal_spike --outcome full` (or `partial` / `void`) | authorize -> capture -> payout on the real sandbox |
| 2 | `python -m agentescrow.mcp_servers.paypal_escrow_server` then `python -m scripts.step2_mcp_smoke_test` | the PayPal MCP server and its guardrails |
| 3 | `pytest tests/test_settlement.py tests/test_state_machine.py tests/test_money_and_mandate.py` | the money policy |
| 4 | `python -m scripts.step4_arbiter_demo` (`--groq` for the real judge) | the 3 personas through the arbiter |
| 5 | `python -m scripts.step5_agents_demo --persona honest --inprocess` | real Groq agents using MCP tools |
| 6 | `python -m agentescrow.api.app --inprocess` then `python -m scripts.step6_demo_client` | the HTTP API and all three outcomes |
| 7 | open http://localhost:5000 (built UI) or `cd frontend && npm run dev` | the React control room |
| 7b | `cd frontend && API_BASE=http://127.0.0.1:5000 ADMIN_TOKEN=... npm run smoke` | the UI's API client against the live server |
| 7c | `cd frontend && npm i --no-save puppeteer-core @sparticuz/chromium && BASE=http://127.0.0.1:5000 ADMIN_TOKEN=... npm run e2e` | real-Chrome end-to-end scenarios |
| 8 | `python -m agentescrow.mcp_servers.marketplace_server` then `python examples/external_worker_agent.py --email you@example.com` | an **external agent** earning money through MCP |

No keys? `PAYPAL_MODE=simulated WORKER_MODE=scripted BUYER_MODE=direct SEMANTIC_JUDGE=static ALLOW_UNSAFE_SANDBOX=true` runs everything offline (every
simulated receipt is flagged). **Use `PAYPAL_MODE=sandbox` for the demo video.** In the UI click **Run the guided demo**: it posts a $5 job and gives your
browser both seats. The server defaults to **waitress**; `--dev` uses Flask's development server. `GET /api/ready` reports every dependency.

Verify a receipt offline: `python -m scripts.verify_receipt receipt.json --server http://localhost:5000 --hidden-tests tests.py`.
Docker: `docker compose --profile build-only build && docker compose up --build` (read the socket warning in `docker-compose.yml`).

## UI layout

The UI follows the Stitch designs and behaves like an app, not a long web page: the document itself never scrolls.
The header (logo, navigation, live escrow totals, PayPal mode) and footer are fixed; only the content region scrolls.
Filter bars and action bars stay pinned, and on a job's control room the story column and the money/actions column
scroll independently on desktop. On phones the navigation becomes a drawer, columns stack (money and next step first),
and tap targets are at least 44px. Layout helpers: `AppShell.jsx`, and `Page` / `Panes` / `Pane` in `components/ui.jsx`.

## HTTP API

| Method & path | Who | Purpose |
|---|---|---|
| `GET /api/health`, `/api/ready`, `/api/whoami`, `/api/templates` | public | modes; dependency checks; the caller's role; task templates |
| `POST /api/tasks/validate` | public (rate-limited) | lint a custom task in the sandbox -> `{ok, checks, ticket}` |
| `POST /api/jobs` | public (rate-limited) | post a job `{template \| task, validation_ticket?, bounty_usd?, deadline_hours?}` -> `{job, token}` and a session cookie |
| `GET /api/jobs?state=POSTED`, `/api/me/jobs` | public / session | the job board; the jobs this browser can act on |
| `GET /api/jobs/<id>` | public / role | redacted view; `viewer.roles` says what you may do |
| `POST /api/jobs/<id>/accept` | public (rate-limited) | worker commits `{worker_id, worker_email}` -> `{job, token}` |
| `POST /api/jobs/<id>/escrow`, `/confirm-funding`, `/cancel`, `/reject-worker` | buyer | open the PayPal hold; authorize once approved; abandon; release the worker |
| `POST /api/jobs/<id>/run`, `/arbitrate` | buyer or worker | worker -> arbitrate -> settle in the background |
| `POST /api/jobs/<id>/submit`, `/withdraw` | worker | an external worker delivers; gives the job back |
| `GET /api/jobs/<id>/events`, `/stream`, `/receipt`, `/hidden-tests` | public | timeline; live SSE; signed receipt; hidden tests (after the verdict) |
| `POST /api/receipts/verify` | public | check a receipt's signature |
| `POST /api/admin/login`, `/logout`; `GET /api/admin/overview`, `/jobs`; `POST /api/admin/sweep` | operator | console |
| `POST /api/webhooks/paypal` | PayPal | signature-verified webhook receiver |
| `GET /.well-known/agentescrow-receipt-key.json`, `/.well-known/agent-card.json` | public | receipt public key; discovery card |

Send tokens as `Authorization: Bearer <token>` (scripts and agents); browsers use the HttpOnly cookie.

## Logging

Every process logs to stderr and `logs/<service>.log` (rotating). Each line carries the job id: `grep job=job_ab12cd34 logs/*.log` follows one job across
the API, orchestrator, MCP calls and PayPal calls. Secrets (client secret, API key, mandate/ticket/access tokens, signing key) are never logged.

## Layout

```
agentescrow/
  config.py  logging_setup.py  money.py  mcp_client.py  tasks.py  samples.py
  paypal/        client.py (REST)  simulator.py  factory.py  errors.py
  mcp_servers/   paypal_escrow_server.py  workbench_server.py  marketplace_server.py
  domain/        models.py  state_machine.py  settlement.py  tokens.py  mandate.py  capability.py  receipt.py
  arbiter/       schema_validator.py  integrity.py  sandbox_runner.py  semantic_judge.py  judge_factory.py  arbiter.py
  agents/        prompts.py  factory.py  model_resolver.py        # langchain.agents.create_agent
  orchestrator/  service.py  store.py  endpoints.py  lock.py
  api/           app.py  auth.py  ratelimit.py  runner.py
frontend/        React 19 + Vite 8 + Tailwind 4 + React Router 8  (src/, e2e/run.mjs, scripts/smoke.mjs)
docs/stitch/     DESIGN.md  PROMPTS.md  README.md                  # the Stitch workflow (12 screen prompts)
examples/        external_worker_agent.py
docker/          sandbox.Dockerfile  sandbox_entrypoint.py
scripts/  tests/ (fakes/: PayPal, Groq, docker)  Dockerfile  docker-compose.yml  .github/workflows/ci.yml
```

## License

MIT (see `LICENSE`).

## Website jobs: checked against the buyer's preferences

Besides "write this Python function", a job can be "build this website". The buyer fills in a preference form (business
name, sections, accent colour, light/dark page, contact-form fields, phrases that must appear, tone). Each answer becomes a
check that the delivered `index.html` is held to:

- **Compiled, not guessed.** `agentescrow/sitecheck.py` turns the preferences into deterministic checks with fixed rules (no
  LLM). The canonical checks are committed by SHA-256 when the job is posted, exactly like hidden tests.
- **Parsed, never executed.** The page is read with Python's `html.parser`, so a hostile page cannot run anything in the
  arbiter. Pages may not contain JavaScript, iframes or anything loaded from other sites (integrity gate).
- **One line per preference.** The verdict carries a checklist (`verdict.checklist`) that says which preferences were met
  and why not, and the same V score and settlement policy as code jobs decide the payout.
- **Only tone is subjective.** The LLM judge scores the optional tone preference and nothing else.

Try it without PayPal, Docker or API keys (opens a report in your browser; press **Run in browser** to see each
worker's site next to its checklist):

    python -m scripts.site_demo

In the web UI choose **A website from your preferences** when posting a job; on the job page the delivered site has a
**Run in browser** button (locked-down frame: no scripts, no network). `WORKER_MODE=scripted` gives repeatable honest,
sloppy and cheating workers; `WORKER_MODE=agent` lets the Groq worker build the site and self-check it with the
`check_site` workbench tool.