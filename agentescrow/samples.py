"""Compatibility helpers for the original single-template sample (run-length encoding).

New code should use :mod:`agentescrow.tasks` directly; this module keeps the short names that scripts and tests use.
"""

from __future__ import annotations

from decimal import Decimal

from agentescrow.domain.models import JobContract
from agentescrow.tasks import DEFAULT_BOUNTY, REQUIRED_SCHEMA, TEMPLATES, build_template_task

SAMPLE_BOUNTY = DEFAULT_BOUNTY
SCRIPTED_DELIVERABLES = TEMPLATES["rle"].scripted
PUBLIC_TESTS = TEMPLATES["rle"].public_tests

__all__ = ["PUBLIC_TESTS", "REQUIRED_SCHEMA", "SAMPLE_BOUNTY", "SCRIPTED_DELIVERABLES", "build_sample_contract"]


def build_sample_contract(bounty: Decimal = SAMPLE_BOUNTY, ttl_seconds: int = 3600) -> tuple[JobContract, str]:
    """Return ``(contract, hidden_tests)`` for the run-length-encoding task (fresh random cases every call)."""
    built = build_template_task("rle", bounty, ttl_seconds)
    return built.contract, built.hidden_tests
