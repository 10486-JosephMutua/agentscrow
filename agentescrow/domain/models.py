"""Domain models: the job contract, evidence produced by the arbiter, and the job itself."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


DELIVERABLE_TOOL_NAME = "submit_deliverable"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobState(str, Enum):
    POSTED = "POSTED"  # contract published, waiting for a worker
    ACCEPTED = "ACCEPTED"  # a worker committed to the task
    FUNDS_PENDING = "FUNDS_PENDING"  # PayPal order created, waiting for the buyer to approve
    ESCROW_LOCKED = "ESCROW_LOCKED"  # PayPal authorization holds the bounty
    SUBMITTED = "SUBMITTED"  # worker delivered an artifact
    ARBITRATING = "ARBITRATING"  # arbiter pipeline running
    NEEDS_REVIEW = "NEEDS_REVIEW"  # arbiter infrastructure failed; safe to retry
    SETTLING = "SETTLING"  # decision made, PayPal calls in progress (resumable)
    SETTLED = "SETTLED"  # captured (fully or partially) and worker paid
    VOIDED = "VOIDED"  # hold released; buyer charged nothing
    CANCELLED = "CANCELLED"  # abandoned before any money was locked


class Outcome(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    VOID = "VOID"


# --------------------------------------------------------------------- contract --
class TaskSpecification(BaseModel):
    title: str
    description: str
    function_name: str
    function_signature: str
    module_name: str = "solution"
    required_schema: dict[str, Any]
    acceptance_criteria: list[str]
    public_tests: str = Field(description="Example pytest tests the worker may see.")
    preferences: dict[str, Any] | None = Field(
        default=None, description="Buyer preferences for a website job (public: the worker needs them). None for code jobs."
    )


class JobContract(BaseModel):
    """Machine-readable task specification posted by the buyer agent."""

    task_id: str
    task_type: str = "python_function"
    bounty_usd: Decimal = Field(gt=Decimal("0"))
    deadline_epoch: int
    hidden_tests_sha256: str = ""
    specification: TaskSpecification


class Deliverable(BaseModel):
    """What a worker agent must hand back (also used as its structured-output schema).

    ``ToolStrategy`` exposes this schema to the LLM as a tool named after the schema title. Models (gpt-oss in
    particular) sometimes normalise names to lowercase, and Groq rejects any tool name that is not an exact match.
    A lowercase snake_case title gives the model nothing to normalise.
    """

    model_config = ConfigDict(title=DELIVERABLE_TOOL_NAME)

    solution_code: str = Field(description="Complete contents of solution.py")
    explanation: str = Field(description="Short explanation of the approach and the edge cases handled")

    @field_validator("solution_code")
    @classmethod
    def _must_be_valid_python(cls, value: str) -> str:
        """Reject unparseable code so the agent gets a chance to fix it instead of submitting it."""
        try:
            ast.parse(value)
        except SyntaxError as exc:
            raise ValueError(f"solution_code is not valid Python ({exc.msg} at line {exc.lineno}); fix it and call the tool again")
        return value


class SiteDeliverable(BaseModel):
    """What a worker agent hands back for a *website* job (also its structured-output schema).

    Same tool name as :class:`Deliverable`, for the same reason: a lowercase snake_case name is one the model reproduces exactly.
    """

    model_config = ConfigDict(title=DELIVERABLE_TOOL_NAME)

    index_html: str = Field(description="The complete index.html: one self-contained page with inline CSS, no JavaScript")
    explanation: str = Field(description="Short, plain explanation of the design choices and how each preference was met")

    @field_validator("index_html")
    @classmethod
    def _must_look_like_a_page(cls, value: str) -> str:
        lowered = value.lower()
        if "<html" not in lowered or "</html>" not in lowered:
            raise ValueError("index_html must be a complete HTML document (with <html> ... </html>); fix it and call the tool again")
        return value


# --------------------------------------------------------------------- evidence --
class SchemaResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    score: float


class IntegrityResult(BaseModel):
    ok: bool
    findings: list[str] = Field(default_factory=list)


class SandboxResult(BaseModel):
    backend: str
    passed: int
    failed: int
    total: int
    exit_code: int | None = None
    timed_out: bool = False
    duration_s: float = 0.0
    error: str | None = None  # infrastructure problem, never test output
    score: float = 0.0  # passed / total


class SemanticResult(BaseModel):
    clarity: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    thoroughness: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=1.0)
    rationale: str
    judge: str
    manipulation_suspected: bool = False


class ChecklistItem(BaseModel):
    """One preference check for a website job: what was asked, whether the page met it, and why."""

    id: str
    label: str
    source: str = "preference"  # "preference" (asked by the buyer) or "baseline" (quality bar for every site)
    passed: bool
    detail: str = ""


class Verdict(BaseModel):
    schema_check: SchemaResult
    integrity: IntegrityResult
    sandbox: SandboxResult | None = None
    semantic: SemanticResult | None = None
    checklist: list[ChecklistItem] | None = None  # website jobs only: one line per preference
    v_score: float
    tiers_skipped: list[str] = Field(default_factory=list)


class SettlementDecision(BaseModel):
    outcome: Outcome
    reason: str
    v_score: float
    capture_amount: Decimal = Decimal("0.00")
    platform_fee: Decimal = Decimal("0.00")
    worker_payout: Decimal = Decimal("0.00")


# Fields each audience must never see. The hidden tests and the mandate token are never
# exposed over HTTP, not even to admins.
_NEVER_EXPOSED = frozenset({"hidden_tests", "mandate_token", "reference_solution"})
_HIDDEN_FROM_PUBLIC = frozenset(
    {"deliverable", "approve_url", "worker_email", "order_id", "authorization_id", "capture_id", "payout_batch_id", "error"}
)
_HIDDEN_FROM_WORKER = frozenset({"approve_url", "worker_email"})
_HIDDEN_FROM_BUYER = frozenset({"worker_email"})

# -------------------------------------------------------------------------- job --
class Job(BaseModel):
    job_id: str
    state: JobState = JobState.POSTED
    contract: JobContract
    hidden_tests: str = Field(repr=False)
    mandate_token: str | None = Field(default=None, repr=False)
    worker_id: str | None = None
    worker_email: str | None = None
    worker_epoch: int = 0
    template_id: str = "rle"
    reference_solution: str | None = Field(default=None, repr=False)
    order_id: str | None = None
    approve_url: str | None = None
    authorization_id: str | None = None
    deliverable: dict[str, Any] | None = None
    verdict: Verdict | None = None
    decision: SettlementDecision | None = None
    capture_id: str | None = None
    payout_batch_id: str | None = None
    locked_at: datetime | None = None
    reauthorized_at: datetime | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    # ------------------------------------------------------------------ views ----
    def view(self, role: str = "public") -> dict[str, Any]:
        """JSON-safe dict for API clients, redacted for ``role`` (public, buyer, worker or admin)."""
        hidden = set(_NEVER_EXPOSED)
        if role == "public":
            hidden |= _HIDDEN_FROM_PUBLIC
        elif role == "worker":
            hidden |= _HIDDEN_FROM_WORKER
        elif role == "buyer":
            hidden |= _HIDDEN_FROM_BUYER
        elif role != "admin":
            raise ValueError(f"Unknown role {role!r}")
        data = self.model_dump(mode="json", exclude=hidden)
        if "deliverable" in hidden:
            data["deliverable_submitted"] = self.deliverable is not None
        return data

    def public_view(self) -> dict[str, Any]:
        """Anonymous view. Kept as a convenience alias for ``view("public")``."""
        return self.view("public")
