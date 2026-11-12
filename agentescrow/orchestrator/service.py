"""The escrow orchestrator: drives a job through its lifecycle.

    post_job -> accept_job -> open_escrow -> confirm_funding -> run_worker
             -> arbitrate -> settle

Every step is logged, appended to the job's event timeline (which the UI streams), and
moves the job through the explicit state machine. Money only moves in :meth:`settle`,
via tickets the *service* issues after the deterministic settlement policy has decided.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any

from agentescrow.agents.factory import (
    BUYER_TOOLS, SITE_WORKER_TOOLS, WORKER_TOOLS, AgentError, build_buyer_agent, build_chat_model, build_worker_agent,
    run_buyer_agent, run_worker_agent,
)  # fmt: skip
from agentescrow.arbiter.arbiter import Arbiter
from agentescrow.arbiter.sandbox_runner import SandboxUnavailable, resolve_backend
from agentescrow.arbiter.semantic_judge import SemanticJudge
from agentescrow.config import Settings
from agentescrow.domain.mandate import issue_mandate, issue_settlement_ticket
from agentescrow.domain.models import Job, JobState, Outcome, Verdict, utc_now
from agentescrow.domain.receipt import ReceiptSigner, build_receipt, verify_signature
from agentescrow.domain.settlement import decide_settlement
from agentescrow.domain.state_machine import InvalidTransition, assert_transition
from agentescrow.logging_setup import job_logging_context
from agentescrow.mcp_client import ToolCallFailed
from agentescrow.money import money_str
from agentescrow.orchestrator.endpoints import McpEndpoints
from agentescrow.orchestrator.store import JobStore, StaleJobError
from agentescrow.sitecheck import HTML_BACKEND, SITE_TASK_TYPE, scripted_site_deliverable
from agentescrow.sites import SitePreferences, build_site_task, lint_site_task
from agentescrow.tasks import (
    DEFAULT_BOUNTY, DEFAULT_TEMPLATE, CustomTask, LintReport, build_custom_task, build_template_task, commitment,
    issue_validation_ticket, lint_custom_task, personas_for, scripted_deliverable, ticket_covers,
)  # fmt: skip

logger = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HONOR_PERIOD = timedelta(days=3)  # PayPal guarantees funds for 3 days; after that a hold should be refreshed
AUTHORIZATION_VALIDITY = timedelta(days=29)  # PayPal authorizations cannot be captured after 29 days


class JobError(RuntimeError):
    """A request that is invalid for the job's current state (maps to HTTP 409)."""


class NotReady(JobError):
    """The buyer has not approved the PayPal order yet."""


class ArbitrationFailed(JobError):
    """The arbiter could not finish (infrastructure problem). The job can be re-arbitrated."""


class TaskRejected(JobError):
    """A custom task failed its lint. ``report`` says which checks failed."""

    def __init__(self, report: LintReport) -> None:
        self.report = report
        failed = "; ".join(f"{c.name}" for c in report.checks if not c.passed)
        super().__init__(f"The task was rejected: {failed}")


class SettlementError(JobError):
    """A PayPal step failed during settlement. The job stays SETTLING and can be resumed."""


class EscrowService:
    def __init__(
        self, settings: Settings, store: JobStore, endpoints: McpEndpoints, judge: SemanticJudge, signer: ReceiptSigner | None = None,
    ) -> None:
        self._signer = signer or ReceiptSigner.load(
            seed_b64=settings.receipt_signing_key, key_path=settings.database_path.parent / "receipt_signing.key"
        )
        self._settings = settings
        self._store = store
        self._endpoints = endpoints
        self._arbiter = Arbiter(settings, judge)
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ---------------------------------------------------------------- plumbing --
    def get_job(self, job_id: str) -> Job:
        return self._store.get(job_id)

    def list_jobs(self, states: list[JobState] | None = None, limit: int = 100) -> list[Job]:
        return self._store.list(limit=limit, states=states)

    def overview(self) -> dict[str, Any]:
        """Operator summary: job counts per state and money totals across settled jobs."""
        captured = paid = fees = Decimal("0.00")
        for job in self._store.list(limit=1000, states=[JobState.SETTLED]):
            if job.decision:
                captured += job.decision.capture_amount
                paid += job.decision.worker_payout
                fees += job.decision.platform_fee
        return {
            "counts": self._store.counts_by_state(),
            "captured_usd": str(captured), "paid_to_workers_usd": str(paid), "platform_fees_usd": str(fees),
        }  # fmt: skip

    def events(self, job_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        self._store.get(job_id)  # raises JobNotFound for unknown ids
        return self._store.events(job_id, after_id)

    def record_error(self, job_id: str, message: str) -> None:
        """Add an error to a job's timeline (used for failures that happen in background tasks)."""
        self._event(job_id, "error", message)

    def _event(self, job_id: str, kind: str, message: str, **data: Any) -> None:
        logger.info("[%s] %s", kind, message)
        self._store.add_event(job_id, kind, message, data)

    def _move(self, job: Job, target: JobState, message: str, **fields: Any) -> Job:
        expected = job.state
        try:
            assert_transition(expected, target)
        except InvalidTransition as exc:
            raise JobError(str(exc)) from exc
        job.state = target
        for name, value in fields.items():
            setattr(job, name, value)
        try:
            self._store.save(job, expected_state=expected)
        except StaleJobError as exc:
            raise JobError("The job was modified by another request; reload and retry") from exc
        self._event(job.job_id, "state", message, state=target.value)
        return job

    def _save_fields(self, job: Job, **fields: Any) -> Job:
        """Update non-state fields (for example a PayPal id) without changing the state."""
        for name, value in fields.items():
            setattr(job, name, value)
        self._store.save(job, expected_state=job.state)
        return job

    @staticmethod
    def _require(job: Job, *states: JobState) -> None:
        if job.state not in states:
            wanted = " or ".join(s.value for s in states)
            raise JobError(f"Job {job.job_id} is {job.state.value}; this step needs {wanted}")

    # --------------------------------------------------------------- 1. posting --
    @property
    def signer(self) -> ReceiptSigner:
        return self._signer

    async def validate_custom_task(self, task: CustomTask) -> tuple[LintReport, str | None]:
        """Lint a buyer-defined task in the sandbox. Returns the report and, if it passed, a short-lived ticket."""
        report = await asyncio.to_thread(lint_custom_task, task, self._settings)
        ticket = issue_validation_ticket(self._settings.mandate_secret, task) if report.ok else None
        return report, ticket

    async def post_job(
        self,
        bounty: Decimal | None = None,
        deadline_hours: int | None = None,
        template_id: str = DEFAULT_TEMPLATE,
        custom: CustomTask | None = None,
        validation_ticket: str | None = None,
        site: SitePreferences | None = None,
    ) -> Job:
        hours = deadline_hours if deadline_hours is not None else self._settings.default_deadline_hours
        if not 1 <= hours <= self._settings.max_escrow_days * 24:
            raise ValueError(f"deadline_hours must be between 1 and {self._settings.max_escrow_days * 24}")
        amount = bounty or DEFAULT_BOUNTY
        if site is not None:
            report = lint_site_task(site)  # pure Python and instant: the checks are compiled from the preferences
            if not report.ok:
                raise TaskRejected(report)
            built = build_site_task(site, amount, hours * 3600)
        elif custom is not None:
            if not ticket_covers(self._settings.mandate_secret, validation_ticket, custom):
                report, _ = await self.validate_custom_task(custom)  # never trust the client: lint again
                if not report.ok:
                    raise TaskRejected(report)
            built = build_custom_task(custom, amount, hours * 3600)
        else:
            built = build_template_task(template_id, amount, hours * 3600)
        contract, hidden_tests = built.contract, built.hidden_tests
        job_id = contract.task_id
        with job_logging_context(job_id):
            mandate = issue_mandate(self._settings.mandate_secret, job_id=job_id, max_amount=contract.bounty_usd)
            job = Job(
                job_id=job_id, contract=contract, hidden_tests=hidden_tests, mandate_token=mandate,
                template_id=built.template_id, reference_solution=built.reference_solution,
            )  # fmt: skip
            self._store.create(job)
            self._event(
                job_id, "state", f"Buyer posted job '{contract.specification.title}' with a ${money_str(contract.bounty_usd)} bounty",
                state=JobState.POSTED.value,
            )  # fmt: skip
            self._event(job_id, "mandate", f"Signed spending mandate issued: escrow capped at ${money_str(contract.bounty_usd)}")
            self._event(job_id, "commitment", f"Hidden tests committed: SHA-256 {contract.hidden_tests_sha256[:16]}…", sha256=contract.hidden_tests_sha256)
            return job

    async def accept_job(self, job_id: str, worker_id: str, worker_email: str) -> Job:
        with job_logging_context(job_id):
            if not worker_id.strip():
                raise ValueError("worker_id is required")
            if not _EMAIL.match(worker_email):
                raise ValueError("worker_email must be a valid email address")
            async with self._locks[job_id]:
                job = self._store.get(job_id)
                self._require(job, JobState.POSTED)
                return self._move(
                    job, JobState.ACCEPTED, f"Worker '{worker_id}' committed to the task",
                    worker_id=worker_id.strip(), worker_email=worker_email.strip(), worker_epoch=job.worker_epoch + 1,
                )  # fmt: skip

    async def release_worker(self, job_id: str, *, by: str) -> Job:
        """Free the worker seat (the buyer rejects the worker, or the worker withdraws) before any money is locked.

        The worker epoch moves on, so the released worker's access token stops working immediately.
        """
        with job_logging_context(job_id):
            async with self._locks[job_id]:
                job = self._store.get(job_id)
                self._require(job, JobState.ACCEPTED)
                released = job.worker_id
                return self._move(
                    job, JobState.POSTED, f"Worker '{released}' was released by the {by}; the job is open again",
                    worker_id=None, worker_email=None, worker_epoch=job.worker_epoch + 1,
                )  # fmt: skip

    # ---------------------------------------------------------- 2. escrow funding --
    async def open_escrow(self, job_id: str) -> Job:
        """Buyer side: create the PayPal AUTHORIZE order and hand back the approval link."""
        with job_logging_context(job_id):
            async with self._locks[job_id]:
                job = self._store.get(job_id)
                self._require(job, JobState.ACCEPTED)
                paypal = await self._endpoints.paypal()
                amount = job.contract.bounty_usd
                if self._settings.buyer_mode == "agent":
                    self._event(job_id, "agent", "Buyer agent is opening the escrow order")
                    agent = build_buyer_agent(
                        build_chat_model(self._settings), paypal.select(BUYER_TOOLS),
                        job_id=job_id, amount=amount, mandate_token=job.mandate_token or "",
                    )  # fmt: skip
                    order = await run_buyer_agent(agent, job_id, amount)
                else:
                    order = await paypal.call(
                        "create_escrow_order", job_id=job_id, amount_usd=money_str(amount),
                        mandate_token=job.mandate_token or "",
                    )  # fmt: skip
                self._event(job_id, "paypal", f"PayPal order {order['order_id']} created (intent AUTHORIZE); waiting for buyer approval", order_id=order["order_id"])  # fmt: skip
                return self._move(
                    job, JobState.FUNDS_PENDING, "Waiting for the buyer to approve the PayPal hold",
                    order_id=order["order_id"], approve_url=order.get("approve_url"),
                )  # fmt: skip

    async def confirm_funding(self, job_id: str) -> Job:
        """After the buyer approved: authorize the order. Idempotent; raises NotReady if not approved yet."""
        with job_logging_context(job_id):
            async with self._locks[job_id]:
                job = self._store.get(job_id)
                if job.state == JobState.ESCROW_LOCKED:
                    return job
                self._require(job, JobState.FUNDS_PENDING)
                paypal = await self._endpoints.paypal()
                order = await paypal.call("get_order_status", job_id=job_id, order_id=job.order_id or "")
                authorization_id = order.get("authorization_id")
                if not authorization_id:
                    if order.get("status") != "APPROVED":
                        raise NotReady(f"The buyer has not approved the PayPal order yet (status: {order.get('status')})")
                    auth = await paypal.call(
                        "authorize_escrow", job_id=job_id, order_id=job.order_id or "",
                        amount_usd=money_str(job.contract.bounty_usd), mandate_token=job.mandate_token or "",
                    )  # fmt: skip
                    authorization_id = auth["authorization_id"]
                self._event(job_id, "paypal", f"PayPal authorization {authorization_id} holds ${money_str(job.contract.bounty_usd)}", authorization_id=authorization_id)  # fmt: skip
                return self._move(
                    job, JobState.ESCROW_LOCKED, "Escrow locked: funds are held, the worker may start",
                    authorization_id=authorization_id, locked_at=utc_now(),
                )  # fmt: skip

    # ---------------------------------------------------------------- 3. working --
    async def run_worker(self, job_id: str, persona: str = "honest") -> Job:
        """Run a worker agent (or a scripted persona) and submit its deliverable."""
        with job_logging_context(job_id):
            async with self._locks[job_id]:
                job = self._store.get(job_id)
                allowed = personas_for(job.template_id) if self._settings.demo_personas else ("honest",)
                if persona not in allowed:
                    raise ValueError(f"persona must be one of {list(allowed)} for this job")
                self._require(job, JobState.ESCROW_LOCKED)
                paypal = await self._endpoints.paypal()
                # The orchestrator never starts compute unless PayPal confirms the funds are locked.
                hold = await paypal.call("get_authorization_status", authorization_id=job.authorization_id or "")
                if hold.get("status") != "CREATED":
                    raise JobError(f"Funds are not locked (authorization status: {hold.get('status')})")
                self._event(job_id, "agent", f"Funds confirmed locked; worker agent ({persona}) starting")

                is_site = job.contract.task_type == SITE_TASK_TYPE
                if self._settings.worker_mode == "scripted" and is_site:
                    deliverable = scripted_site_deliverable(job.contract.specification.preferences or {}, persona)
                elif self._settings.worker_mode == "scripted":
                    deliverable = scripted_deliverable(
                        job.template_id, persona, function_name=job.contract.specification.function_name,
                        reference_solution=job.reference_solution,
                    )  # fmt: skip
                else:
                    workbench = await self._endpoints.workbench()
                    wanted = SITE_WORKER_TOOLS if is_site else WORKER_TOOLS
                    tools = paypal.select(wanted & set(paypal.names)) + workbench.select(wanted & set(workbench.names))
                    agent = build_worker_agent(build_chat_model(self._settings), tools, persona=persona, task_type=job.contract.task_type)
                    try:
                        deliverable = await run_worker_agent(agent, job.contract, job.authorization_id or "")
                    except AgentError as exc:
                        self._event(job_id, "error", f"Worker agent failed: {exc}")
                        raise
                return self._submit(job, deliverable)

    async def submit_deliverable(self, job_id: str, deliverable: dict[str, Any]) -> Job:
        """Entry point for external workers that did the work themselves."""
        with job_logging_context(job_id):
            if not isinstance(deliverable, dict):
                raise ValueError("deliverable must be a JSON object")
            async with self._locks[job_id]:
                job = self._store.get(job_id)
                self._require(job, JobState.ESCROW_LOCKED)
                return self._submit(job, deliverable)

    def _submit(self, job: Job, deliverable: dict[str, Any]) -> Job:
        if time.time() > job.contract.deadline_epoch:
            raise JobError("The job deadline has passed")
        return self._move(job, JobState.SUBMITTED, "Worker submitted a deliverable", deliverable=deliverable)

    # -------------------------------------------------------------- 4. arbitrating --
    async def arbitrate(self, job_id: str) -> Job:
        """Run the 3-tier arbiter and record the settlement decision. Safe to retry after NEEDS_REVIEW."""
        with job_logging_context(job_id):
            async with self._locks[job_id]:
                job = self._store.get(job_id)
                self._require(job, JobState.SUBMITTED, JobState.NEEDS_REVIEW)
                job = self._move(job, JobState.ARBITRATING, "Autonomous arbitration started", error=None)
                try:
                    if commitment(job.hidden_tests) != job.contract.hidden_tests_sha256:
                        raise ArbitrationFailed("The stored hidden tests no longer match the commitment made when the job was posted")
                    verdict = await self._arbiter.evaluate(job.contract, job.hidden_tests, job.deliverable or {})
                    if verdict.sandbox is not None and verdict.sandbox.error:
                        # Our infrastructure failed, not the worker: never void or pay on that basis.
                        raise ArbitrationFailed(f"Sandbox infrastructure error: {verdict.sandbox.error}")
                except Exception as exc:
                    logger.exception("Arbitration failed for %s", job_id)
                    self._move(job, JobState.NEEDS_REVIEW, f"Arbitration could not finish: {exc}", error=str(exc))
                    if isinstance(exc, ArbitrationFailed):
                        raise
                    raise ArbitrationFailed(str(exc)) from exc

                self._record_tier_events(job_id, verdict)
                decision = decide_settlement(verdict, bounty=job.contract.bounty_usd, fee_rate=self._settings.platform_fee_rate)
                self._event(job_id, "decision", f"Decision: {decision.outcome.value} - {decision.reason}", outcome=decision.outcome.value)  # fmt: skip
                return self._move(job, JobState.SETTLING, "Settlement decided; moving money", verdict=verdict, decision=decision)

    def _record_tier_events(self, job_id: str, verdict: Verdict) -> None:
        schema = verdict.schema_check
        self._event(job_id, "tier", f"Tier 1 schema: {'PASS' if schema.valid else 'FAIL'}", tier=1, passed=schema.valid)
        if "integrity" not in verdict.tiers_skipped:
            ok = verdict.integrity.ok
            self._event(job_id, "tier", f"Integrity gate: {'PASS' if ok else 'FAIL - ' + '; '.join(verdict.integrity.findings)}", tier="integrity", passed=ok)  # fmt: skip
        if verdict.sandbox:
            sb = verdict.sandbox
            if sb.backend == HTML_BACKEND:
                self._event(job_id, "tier", f"Tier 2 preference checks: {sb.passed}/{sb.total} passed", tier=2, passed=sb.passed, total=sb.total)
                for item in verdict.checklist or []:
                    if not item.passed:
                        self._event(job_id, "check", f"Not met: {item.label} ({item.detail})")
            else:
                self._event(job_id, "tier", f"Tier 2 hidden tests: {sb.passed}/{sb.total} passed ({sb.backend} sandbox)", tier=2, passed=sb.passed, total=sb.total)  # fmt: skip
        if verdict.semantic:
            self._event(job_id, "tier", f"Tier 3 semantic judge: {verdict.semantic.score:.2f}", tier=3, score=verdict.semantic.score)  # fmt: skip
        self._event(job_id, "tier", f"Verification score V = {verdict.v_score:.2f}", v_score=verdict.v_score)

    # ---------------------------------------------------------------- 5. settling --
    async def settle(self, job_id: str) -> Job:
        """Move the money according to the decision. Resumable: re-run after a failure."""
        with job_logging_context(job_id):
            async with self._locks[job_id]:
                job = self._store.get(job_id)
                self._require(job, JobState.SETTLING)
                decision = job.decision
                assert decision is not None, "SETTLING job without a decision"
                secret = self._settings.mandate_secret
                paypal = await self._endpoints.paypal()
                try:
                    if decision.outcome == Outcome.VOID:
                        await self._void_hold(job, paypal)
                        self._event(job_id, "paypal", "Authorization voided: the buyer was charged $0.00")
                        return self._move(job, JobState.VOIDED, "Hold released; buyer charged nothing", error=None)

                    if not job.capture_id:
                        job = await self._ensure_fresh_authorization(job, paypal)
                        ticket = issue_settlement_ticket(secret, job_id=job_id, action="capture", amount=decision.capture_amount)
                        capture = await paypal.call(
                            "capture_escrow", job_id=job_id, authorization_id=job.authorization_id or "",
                            amount_usd=money_str(decision.capture_amount), settlement_ticket=ticket,
                        )  # fmt: skip
                        job = self._save_fields(job, capture_id=capture["capture_id"])
                        self._event(job_id, "paypal", f"Captured ${money_str(decision.capture_amount)} (capture {capture['capture_id']})", capture_id=capture["capture_id"])  # fmt: skip

                    if not job.payout_batch_id and decision.worker_payout > 0:
                        ticket = issue_settlement_ticket(secret, job_id=job_id, action="payout", amount=decision.worker_payout)
                        payout = await paypal.call(
                            "pay_worker", job_id=job_id, receiver_email=job.worker_email or self._settings.paypal_worker_email,
                            amount_usd=money_str(decision.worker_payout), settlement_ticket=ticket,
                        )  # fmt: skip
                        job = self._save_fields(job, payout_batch_id=payout["payout_batch_id"])
                        self._event(job_id, "paypal", f"Paid worker ${money_str(decision.worker_payout)} (batch {payout['payout_batch_id']}); platform fee ${money_str(decision.platform_fee)}", payout_batch_id=payout["payout_batch_id"])  # fmt: skip
                    return self._move(job, JobState.SETTLED, "Job settled", error=None)
                except ToolCallFailed as exc:
                    self._save_fields(job, error=str(exc))
                    self._event(job_id, "error", f"Settlement step failed (job stays SETTLING, safe to retry): {exc}")
                    raise SettlementError(str(exc)) from exc

    # ------------------------------------------------------------- PayPal holds --
    async def _void_hold(self, job: Job, paypal: Any) -> None:
        """Release the hold. If PayPal says it fails, but the hold is in fact already VOIDED (expired, or
        voided by a webhook race), that is the outcome we wanted, so it counts as success."""
        ticket = issue_settlement_ticket(self._settings.mandate_secret, job_id=job.job_id, action="void")
        try:
            await paypal.call("void_escrow", job_id=job.job_id, authorization_id=job.authorization_id or "", settlement_ticket=ticket)  # fmt: skip
        except ToolCallFailed:
            try:
                status = await paypal.call("get_authorization_status", authorization_id=job.authorization_id or "")
            except ToolCallFailed as lookup:
                if self._settings.paypal_mode == "simulated" and "RESOURCE_NOT_FOUND" in str(lookup):
                    # Jobs created before the simulator persisted its state: the simulator lost the hold when the
                    # server restarted. A simulated hold holds no money, so the void's goal (buyer charged $0.00)
                    # is already met; retrying would fail with 404 on every restart and strand the job in SETTLING.
                    self._event(job.job_id, "paypal", "The simulated hold no longer exists (simulator restarted); nothing to void")
                    return
                raise
            if status.get("status") != "VOIDED":
                raise
            self._event(job.job_id, "paypal", "The hold was already released; nothing more to void")

    async def _ensure_fresh_authorization(self, job: Job, paypal: Any) -> Job:
        """Before capturing, refresh a hold older than PayPal's honor period (once), so funds are still guaranteed."""
        locked_at = job.locked_at or job.created_at
        age = utc_now() - locked_at
        if age < HONOR_PERIOD or job.reauthorized_at is not None:
            return job
        if age >= AUTHORIZATION_VALIDITY:
            raise SettlementError("The PayPal authorization is older than 29 days and can no longer be captured")
        ticket = issue_settlement_ticket(
            self._settings.mandate_secret, job_id=job.job_id, action="reauthorize", amount=job.contract.bounty_usd
        )
        fresh = await paypal.call(
            "reauthorize_escrow", job_id=job.job_id, authorization_id=job.authorization_id or "",
            amount_usd=money_str(job.contract.bounty_usd), settlement_ticket=ticket,
        )  # fmt: skip
        self._event(
            job.job_id, "paypal",
            f"Hold was {age.days} days old (past PayPal's 3-day honor period): reauthorized as {fresh['authorization_id']}",
            authorization_id=fresh["authorization_id"],
        )  # fmt: skip
        return self._save_fields(job, authorization_id=fresh["authorization_id"], reauthorized_at=utc_now())

    # --------------------------------------------------------------- cancelling --
    async def cancel_job(self, job_id: str, reason: str | None = None) -> Job:
        """Abandon a job. If funds are locked, the hold is voided so the buyer pays nothing."""
        with job_logging_context(job_id):
            async with self._locks[job_id]:
                job = self._store.get(job_id)
                if job.state == JobState.ESCROW_LOCKED:
                    paypal = await self._endpoints.paypal()
                    try:
                        await self._void_hold(job, paypal)
                    except ToolCallFailed as exc:
                        raise SettlementError(str(exc)) from exc
                    return self._move(job, JobState.VOIDED, reason or "Job cancelled; hold released, buyer charged nothing")
                self._require(job, JobState.POSTED, JobState.ACCEPTED, JobState.FUNDS_PENDING)
                return self._move(job, JobState.CANCELLED, reason or "Job cancelled before any money was locked")

    async def sweep_overdue(self) -> list[str]:
        """Enforce deadlines: jobs still waiting for a delivery after their deadline are closed.

        A locked job is voided (the buyer pays nothing); an unfunded job is cancelled. Jobs already
        submitted are never swept: the deadline is for delivery, and the arbiter decides the rest.
        """
        now = time.time()
        closed: list[str] = []
        waiting = [JobState.POSTED, JobState.ACCEPTED, JobState.FUNDS_PENDING, JobState.ESCROW_LOCKED]
        for job in self._store.list(limit=500, states=waiting):
            if now <= job.contract.deadline_epoch:
                continue
            try:
                await self.cancel_job(job.job_id, reason="Deadline passed without a delivery; job closed and any hold released")
                closed.append(job.job_id)
            except (JobError, ToolCallFailed) as exc:
                logger.warning("Could not close overdue job %s: %s", job.job_id, exc)
        if closed:
            logger.info("Deadline sweep closed %d job(s): %s", len(closed), closed)
        return closed


    # ------------------------------------------------------------------ webhooks --
    async def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        """Ask PayPal (through the MCP server) whether a webhook is genuine."""
        paypal = await self._endpoints.paypal()
        result = await paypal.call("verify_webhook", headers=dict(headers), raw_body=raw_body.decode("utf-8", "replace"))
        return bool(result.get("verified"))

    def _job_for_webhook(self, event_type: str, resource: dict[str, Any]) -> Job | None:
        related = ((resource.get("supplementary_data") or {}).get("related_ids") or {})
        resource_id = str(resource.get("id", ""))
        if event_type.startswith("CHECKOUT.ORDER"):
            return self._store.find_by("order_id", resource_id)
        if event_type.startswith("PAYMENT.AUTHORIZATION"):
            return self._store.find_by("authorization_id", resource_id) or self._store.find_by("order_id", str(related.get("order_id", "")))
        if event_type.startswith("PAYMENT.CAPTURE"):
            return self._store.find_by("capture_id", resource_id) or self._store.find_by("order_id", str(related.get("order_id", "")))
        return None

    async def handle_webhook(self, event: dict[str, Any]) -> str:
        """Act on a *verified* PayPal webhook. Webhooks are hints: money-relevant facts are always re-read from
        PayPal's API (``confirm_funding`` does so), and duplicates (PayPal retries) are ignored."""
        event_id, event_type = str(event.get("id", "")), str(event.get("event_type", ""))
        resource = event.get("resource") if isinstance(event.get("resource"), dict) else {}
        job = self._job_for_webhook(event_type, resource)
        if not event_id or not self._store.record_webhook(event_id, event_type, job.job_id if job else None):
            return "duplicate" if event_id else "ignored: no event id"
        if job is None:
            outcome = "ignored: no matching job"
        else:
            with job_logging_context(job.job_id):
                outcome = await self._apply_webhook(event_type, resource, job)
        self._store.set_webhook_outcome(event_id, outcome)
        logger.info("Webhook %s (%s): %s", event_type, event_id, outcome)
        return outcome

    async def _apply_webhook(self, event_type: str, resource: dict[str, Any], job: Job) -> str:
        job_id = job.job_id
        if event_type in {"CHECKOUT.ORDER.APPROVED", "PAYMENT.AUTHORIZATION.CREATED"}:
            self._event(job_id, "webhook", f"PayPal webhook: {event_type}", event_type=event_type)
            if job.state != JobState.FUNDS_PENDING:
                return f"noted ({job.state.value})"
            try:
                await self.confirm_funding(job_id)
            except (NotReady, JobError, ToolCallFailed) as exc:
                return f"funding not confirmed: {exc}"
            return "funding confirmed"

        if event_type == "PAYMENT.AUTHORIZATION.VOIDED":
            ours = job.state in {JobState.VOIDED, JobState.CANCELLED} or (
                job.state == JobState.SETTLING and job.decision is not None and job.decision.outcome == Outcome.VOID
            )
            if ours:
                self._event(job_id, "webhook", "PayPal confirmed the authorization was voided", event_type=event_type)
                return "void confirmed"
            async with self._locks[job_id]:
                job = self._store.get(job_id)
                if job.state == JobState.ESCROW_LOCKED:
                    self._move(job, JobState.VOIDED, "PayPal voided the hold (expired or released outside AgentEscrow); job closed")
                    return "job closed: hold voided externally"
            self._event(job_id, "error", "PayPal voided the hold while the job was in progress; settlement will fail and needs an operator")
            self._save_fields(self._store.get(job_id), error="The PayPal hold was voided externally")
            return "alert: hold voided externally during work"

        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            self._event(job_id, "webhook", "PayPal confirmed the capture completed", event_type=event_type)
            return "capture confirmed"
        if event_type in {"PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.PENDING"}:
            self._event(job_id, "error", f"PayPal reports the capture is {event_type.rsplit('.', 1)[-1].lower()}", event_type=event_type)
            return f"alert: {event_type}"
        return "ignored: event type not used"

    # -------------------------------------------------------------- convenience --
    async def run_pipeline(self, job_id: str, persona: str = "honest") -> Job:
        """worker -> arbitrate -> settle, for a job whose escrow is already locked."""
        job = self._store.get(job_id)
        if job.state == JobState.ESCROW_LOCKED:
            await self.run_worker(job_id, persona)
        if self._store.get(job_id).state in {JobState.SUBMITTED, JobState.NEEDS_REVIEW}:
            await self.arbitrate(job_id)
        if self._store.get(job_id).state == JobState.SETTLING:
            await self.settle(job_id)
        return self._store.get(job_id)

    def receipt(self, job_id: str) -> dict[str, Any]:
        job = self._store.get(job_id)
        try:
            return build_receipt(job, self._signer, simulated=self._settings.paypal_mode == "simulated")
        except ValueError as exc:
            raise JobError(str(exc)) from exc

    def verify_receipt(self, document: dict[str, Any]) -> dict[str, Any]:
        """Check a receipt this platform issued (anyone can also do it offline with the public key)."""
        try:
            valid = verify_signature(self._signer.public_key_b64, document["receipt"], document["signature"])
        except (KeyError, TypeError):
            valid = False
        return {"valid": valid, "key_id": self._signer.key_id}

    def reveal_hidden_tests(self, job_id: str) -> dict[str, Any]:
        """After the verdict the hidden tests become public so anyone can audit it against the commitment."""
        job = self._store.get(job_id)
        if job.state not in {JobState.SETTLED, JobState.VOIDED}:
            raise JobError("Hidden tests are revealed only after the job is settled or voided")
        digest = commitment(job.hidden_tests)
        return {"tests": job.hidden_tests, "sha256": digest, "matches_commitment": digest == job.contract.hidden_tests_sha256}

    async def check_dependencies(self) -> dict[str, dict[str, Any]]:
        """Readiness probe: can this server actually do its job right now?"""
        checks: dict[str, dict[str, Any]] = {}
        try:
            self._store.list(limit=1)
            checks["database"] = {"ok": True}
        except Exception as exc:  # noqa: BLE001
            checks["database"] = {"ok": False, "detail": str(exc)}
        try:
            toolbox = await self._endpoints.paypal()
            checks["paypal_mcp"] = {"ok": True, "tools": len(toolbox.names)}
        except Exception as exc:  # noqa: BLE001
            checks["paypal_mcp"] = {"ok": False, "detail": str(exc)[:200]}
        try:
            backend = resolve_backend(self._settings.sandbox_backend, allow_unsafe=self._settings.allow_unsafe_sandbox)
            checks["sandbox"] = {"ok": True, "backend": backend}
        except SandboxUnavailable as exc:
            checks["sandbox"] = {"ok": False, "detail": str(exc)[:200]}
        checks["receipt_key"] = {"ok": True, "key_id": self._signer.key_id}
        return checks

    # ------------------------------------------------------------- crash recovery --
    async def recover_after_restart(self) -> list[str]:
        """Pick up jobs that a restart interrupted. Money steps are idempotent, so resuming is safe.

        * ARBITRATING: the arbiter was killed mid-run -> mark NEEDS_REVIEW, then arbitrate again.
        * SUBMITTED / NEEDS_REVIEW: arbitrate. * SETTLING: resume the settlement.
        """
        resumed: list[str] = []
        stuck = self._store.list(limit=500, states=[JobState.ARBITRATING, JobState.SUBMITTED, JobState.NEEDS_REVIEW, JobState.SETTLING])
        for job in stuck:
            with job_logging_context(job.job_id):
                if job.state == JobState.ARBITRATING:
                    async with self._locks[job.job_id]:
                        fresh = self._store.get(job.job_id)
                        if fresh.state == JobState.ARBITRATING:
                            self._move(fresh, JobState.NEEDS_REVIEW, "The server restarted during arbitration; it will run again", error="Interrupted by a restart")
                self._event(job.job_id, "state", "Recovered after a restart: resuming")
                try:
                    await self.run_pipeline(job.job_id)
                    resumed.append(job.job_id)
                except Exception as exc:  # noqa: BLE001 - one bad job must not stop the others
                    logger.error("Could not resume %s: %s", job.job_id, exc)
                    self._event(job.job_id, "error", f"Recovery could not finish: {exc}")
        if resumed:
            logger.info("Recovered %d job(s) after a restart: %s", len(resumed), resumed)
        return resumed
