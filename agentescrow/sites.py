"""The "website" task type: build a job from buyer preferences, and check that the job is fair.

A website job is posted from a *preference form* instead of a function signature and tests:

    SitePreferences --compile_checks--> checks --SHA-256--> committed in the contract
                    --acceptance_criteria--> the public brief the worker reads

The checks are compiled by plain Python rules (see :mod:`agentescrow.sitecheck`), never by an LLM, so the same
preferences always produce the same checks. Only the optional *tone* preference is left to the judge.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator

from agentescrow.arbiter.integrity import scan_text_for_injection
from agentescrow.domain.models import JobContract, TaskSpecification
from agentescrow.sitecheck import (
    SITE_SCHEMA, SITE_TASK_TYPE, SITE_TEMPLATE_ID, acceptance_criteria, blank_page, checks_to_json, compile_checks,
    normalize_prefs, render_site, run_checks, scan_site_integrity, tally,
)  # fmt: skip
from agentescrow.tasks import BuiltTask, LintCheck, LintReport, commitment


class SitePreferences(BaseModel):
    """What the buyer wants the website to be. Validated and normalised by :func:`normalize_prefs`."""

    business_name: str
    purpose: str
    sections: list[str]
    primary_color: str
    theme: str = "any"
    contact_fields: list[str] = Field(default_factory=list)
    include_text: list[str] = Field(default_factory=list)
    tone: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        return normalize_prefs(data)  # raises ValueError, which pydantic reports as a validation error


def build_site_task(prefs: SitePreferences, bounty: Decimal, ttl_seconds: int) -> BuiltTask:
    """The contract, the committed checks and a reference site for a website job."""
    data = prefs.model_dump()
    checks_json = checks_to_json(compile_checks(data))
    contract = JobContract(
        task_id=f"job_{uuid.uuid4().hex[:8]}",
        task_type=SITE_TASK_TYPE,
        bounty_usd=bounty,
        deadline_epoch=int(time.time()) + ttl_seconds,
        hidden_tests_sha256=commitment(checks_json),
        specification=TaskSpecification(
            title=f"Website for {data['business_name']}"[:80],
            description=(
                f"Build a website for {data['business_name']}. Purpose: {data['purpose']}. Deliver ONE self-contained index.html "
                "(inline CSS, no JavaScript, nothing loaded from other sites) that meets every preference listed below."
            ),
            function_name="index.html",
            function_signature="index.html: one self-contained page (HTML + inline CSS)",
            module_name="index",
            required_schema=SITE_SCHEMA,
            acceptance_criteria=acceptance_criteria(data),
            public_tests="",
            preferences=data,
        ),
    )
    return BuiltTask(contract, checks_json, SITE_TEMPLATE_ID, reference_solution=render_site(data, "honest"))


def lint_site_task(prefs: SitePreferences) -> LintReport:
    """Make sure a website job is fair before any money is locked. Pure Python: nothing to sandbox, nothing to wait for."""
    data = prefs.model_dump()
    checks = compile_checks(data)
    report: list[LintCheck] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        report.append(LintCheck(name=name, passed=passed, detail=detail))

    texts = {"business_name": data["business_name"], "purpose": data["purpose"], "tone": data["tone"] or ""}
    texts.update({f"include_text[{i}]": phrase for i, phrase in enumerate(data["include_text"])})
    injection = [finding for label, text in texts.items() for finding in scan_text_for_injection(label, text)]
    add("Preferences contain no instructions aimed at AI agents", not injection, "; ".join(injection[:2]))

    reference = render_site(data, "honest")
    results = run_checks(reference, checks)
    failing = [r["label"] for r in results if not r["passed"]]
    add("A reference website satisfies every check", not failing, "; ".join(failing[:3]))
    add("The reference website passes the integrity gate", not scan_site_integrity(reference), "; ".join(scan_site_integrity(reference)[:2]))

    passed, total = tally(run_checks(blank_page(), checks))
    add("A blank page is rejected", passed < total, f"a blank page passes {passed} of {total} checks")
    return LintReport(ok=all(c.passed for c in report), checks=report, hidden_test_count=len(checks))
