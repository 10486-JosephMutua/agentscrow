"""Shared fixtures. Tests never touch the network: PayPal is simulated and judges are static."""

from __future__ import annotations

import warnings
from decimal import Decimal
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", message=".*langchain.mcp.*beta.*")

from agentescrow.config import Settings  # noqa: E402

TEST_SECRET = "unit-test-secret-that-is-long-enough"
ADMIN_TOKEN = "admin-token-for-tests-123456"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    base = Settings.from_env(env_file=tmp_path / "does-not-exist.env")
    return Settings(
        **{
            **base.__dict__,
            "paypal_mode": "simulated",
            "semantic_judge": "static",
            "buyer_mode": "direct",
            "worker_mode": "scripted",
            "mandate_secret": TEST_SECRET,
            "sandbox_backend": "subprocess",
            "allow_unsafe_sandbox": True,
            "admin_token": ADMIN_TOKEN,
            "rate_limit_per_min": 1000,
            "paypal_webhook_id": "WH-TEST",
            "sandbox_timeout_s": 20,
            "public_base_url": "http://localhost:5000",
            "frontend_url": "http://localhost:5173",
            "platform_fee_rate": Decimal("0.0667"),
            "database_path": tmp_path / "test.db",
            "log_dir": tmp_path / "logs",
            "paypal_client_id": "",
            "paypal_client_secret": "",
            "groq_api_key": "",
        }
    )


@pytest.fixture
def api_parts(settings):
    """(settings, service, runner) wired to the PayPal simulator, scripted workers and a static judge."""
    from agentescrow.api.runner import AsyncRunner
    from agentescrow.arbiter.semantic_judge import StaticSemanticJudge
    from agentescrow.orchestrator.endpoints import inprocess_endpoints
    from agentescrow.orchestrator.service import EscrowService
    from agentescrow.orchestrator.store import JobStore
    from agentescrow.paypal.simulator import SimulatedPayPalClient

    runner = AsyncRunner()
    service = EscrowService(settings, JobStore(settings.database_path), inprocess_endpoints(settings, SimulatedPayPalClient()), StaticSemanticJudge(0.9))
    yield settings, service, runner
    runner.stop()


GOOD_TASK = dict(
    title="Double a number",
    description="Implement double(x) returning twice the integer x. Negative numbers and zero must work too.",
    function_name="double",
    function_signature="def double(x: int) -> int",
    public_tests="from solution import double\n\n\ndef test_two():\n    assert double(2) == 4\n",
    hidden_tests=(
        "from solution import double\n\n\ndef test_zero():\n    assert double(0) == 0\n\n\ndef test_negative():\n    assert double(-3) == -6\n\n\n"
        "def test_large():\n    assert double(10**6) == 2 * 10**6\n\n\ndef test_one():\n    assert double(1) == 2\n"
    ),
    reference_solution="def double(x: int) -> int:\n    return x * 2\n",
)
