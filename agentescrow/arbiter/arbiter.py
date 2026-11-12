"""The 3-tier autonomous arbiter pipeline.

    Tier 1  schema     deterministic JSON-Schema check             (weight 30%)
    Gate    integrity  AST policy + prompt-injection scan          (before any execution)
    Tier 2  sandbox    hidden pytest suite in an isolated runner   (weight 40%)
    Tier 3  semantic   LLM judge for clarity/relevance/depth       (weight 30%)

Expensive or risky tiers are skipped as soon as the outcome is certain to be a void.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from agentescrow.arbiter.integrity import check_integrity, check_site_integrity
from agentescrow.arbiter.sandbox_runner import run_pytest
from agentescrow.arbiter.schema_validator import validate_deliverable
from agentescrow.arbiter.semantic_judge import SemanticJudge
from agentescrow.config import Settings
from agentescrow.domain.models import ChecklistItem, IntegrityResult, JobContract, SandboxResult, Verdict
from agentescrow.domain.settlement import compute_v_score
from agentescrow.sitecheck import HTML_BACKEND, SITE_TASK_TYPE, tally, timed_run

logger = logging.getLogger(__name__)


class Arbiter:
    def __init__(self, settings: Settings, judge: SemanticJudge) -> None:
        self._settings = settings
        self._judge = judge

    async def evaluate(self, contract: JobContract, hidden_tests: str, deliverable: dict[str, Any]) -> Verdict:
        spec = contract.specification
        skipped: list[str] = []
        logger.info("Arbitration started for task %s", contract.task_id)
        if contract.task_type == SITE_TASK_TYPE:
            return await self._evaluate_site(contract, hidden_tests, deliverable)

        # Tier 1 -------------------------------------------------------------------
        schema_check = validate_deliverable(deliverable, spec.required_schema)
        if not schema_check.valid:
            skipped += ["integrity", "sandbox", "semantic"]
            return self._finish(schema_check, IntegrityResult(ok=True), None, None, skipped)

        # Integrity gate -------------------------------------------------------------
        integrity = check_integrity(deliverable)
        if not integrity.ok:
            skipped += ["sandbox", "semantic"]
            logger.warning("Skipping sandbox: submission was never executed because of integrity findings")
            return self._finish(schema_check, integrity, None, None, skipped)

        # Tier 2 -------------------------------------------------------------------
        run = await asyncio.to_thread(
            run_pytest,
            deliverable["solution_code"],
            hidden_tests,
            module_name=spec.module_name,
            backend=self._settings.sandbox_backend,
            image=self._settings.sandbox_image,
            timeout_s=self._settings.sandbox_timeout_s,
            allow_unsafe=self._settings.allow_unsafe_sandbox,
        )
        sandbox = run.result
        if sandbox.total == 0 or sandbox.timed_out:
            skipped.append("semantic")
            logger.warning("Skipping semantic judge: sandbox produced no usable test results")
            return self._finish(schema_check, integrity, sandbox, None, skipped)

        # Tier 3 -------------------------------------------------------------------
        semantic = await asyncio.to_thread(self._judge.judge, contract, deliverable)
        if semantic.manipulation_suspected:
            integrity = IntegrityResult(
                ok=False, findings=[*integrity.findings, "semantic judge flagged a manipulation attempt"]
            )
        return self._finish(schema_check, integrity, sandbox, semantic, skipped)

    async def _evaluate_site(self, contract: JobContract, hidden_tests: str, deliverable: dict[str, Any]) -> Verdict:
        """Website jobs: the same tiers, with the buyer's preferences as the test suite.

        Tier 2 parses the page as text (it is never executed), so it needs no sandbox and cannot be escaped.
        """
        skipped: list[str] = []
        schema_check = validate_deliverable(deliverable, contract.specification.required_schema)
        if not schema_check.valid:
            skipped += ["integrity", "sandbox", "semantic"]
            return self._finish(schema_check, IntegrityResult(ok=True), None, None, skipped)

        integrity = check_site_integrity(deliverable)
        if not integrity.ok:
            skipped += ["sandbox", "semantic"]
            logger.warning("Skipping preference checks: the page failed the integrity gate")
            return self._finish(schema_check, integrity, None, None, skipped)

        checks = json.loads(hidden_tests)
        results, seconds = await asyncio.to_thread(timed_run, deliverable["index_html"], checks)
        passed, total = tally(results)
        sandbox = SandboxResult(
            backend=HTML_BACKEND, passed=passed, failed=total - passed, total=total, exit_code=0,
            duration_s=seconds, score=round(passed / total, 4) if total else 0.0,
        )  # fmt: skip
        logger.info("Preference checks: %d/%d passed", passed, total)

        judge_site = getattr(self._judge, "judge_site", None) or self._judge.judge
        semantic = await asyncio.to_thread(judge_site, contract, deliverable)
        if semantic.manipulation_suspected:
            integrity = IntegrityResult(ok=False, findings=[*integrity.findings, "semantic judge flagged a manipulation attempt"])
        verdict = self._finish(schema_check, integrity, sandbox, semantic, skipped)
        verdict.checklist = [ChecklistItem(**item) for item in results]
        return verdict

    @staticmethod
    def _finish(schema_check, integrity, sandbox, semantic, skipped) -> Verdict:  # type: ignore[no-untyped-def]
        v_score = compute_v_score(
            schema_check.score,
            sandbox.score if sandbox else 0.0,
            semantic.score if semantic else 0.0,
        )
        logger.info("Arbitration finished: V=%.4f (skipped tiers: %s)", v_score, skipped or "none")
        return Verdict(
            schema_check=schema_check,
            integrity=integrity,
            sandbox=sandbox,
            semantic=semantic,
            v_score=v_score,
            tiers_skipped=skipped,
        )
