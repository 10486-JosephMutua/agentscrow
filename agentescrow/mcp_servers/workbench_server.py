"""Workbench MCP server: tools a *worker* agent uses while it works.

``run_python_tests`` lets the worker run its own pytest tests against its own code in the
same isolated sandbox the arbiter uses. It never receives the buyer's hidden tests.

Run:  python -m agentescrow.mcp_servers.workbench_server
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from agentescrow.arbiter.integrity import scan_code_policy
from agentescrow.arbiter.sandbox_runner import SandboxUnavailable, run_pytest
from agentescrow.config import Settings
from agentescrow.logging_setup import configure_logging
from agentescrow.sitecheck import compile_checks, normalize_prefs, run_checks, scan_site_integrity, tally

logger = logging.getLogger(__name__)
_MAX_INPUT_CHARS = 20_000


def build_workbench_server(settings: Settings) -> FastMCP:
    mcp = FastMCP("agentescrow-workbench")

    @mcp.tool
    def run_python_tests(solution_code: str, test_code: str) -> dict[str, Any]:
        """Run YOUR pytest tests against YOUR code in an isolated sandbox.

        solution_code is saved as solution.py; test_code is saved as test_hidden.py and should
        start with `from solution import <function>`. Returns pass/fail counts and the tail of pytest's output.
        """
        if len(solution_code) > _MAX_INPUT_CHARS or len(test_code) > _MAX_INPUT_CHARS:
            raise ToolError("Input too large")
        findings = scan_code_policy(solution_code)
        if findings:
            raise ToolError("solution_code violates the sandbox policy: " + "; ".join(findings[:5]))
        logger.info("Worker requested a sandbox test run")
        try:
            run = run_pytest(
                solution_code,
                test_code,
                backend=settings.sandbox_backend,
                image=settings.sandbox_image,
                timeout_s=settings.sandbox_timeout_s,
                allow_unsafe=settings.allow_unsafe_sandbox,
            )
        except SandboxUnavailable as exc:
            raise ToolError(str(exc)) from exc
        result = run.result
        return {
            "passed": result.passed,
            "failed": result.failed,
            "total": result.total,
            "timed_out": result.timed_out,
            "error": result.error,
            "output_tail": run.output[-1500:],
        }

    @mcp.tool
    def check_site(index_html: str, preferences: dict[str, Any]) -> dict[str, Any]:
        """Check YOUR website against the buyer's preferences before you submit it.

        Pass the complete index_html and the preferences JSON from the brief. Returns how many checks pass and,
        for each one that fails, what is wrong. Fix them and call again until nothing fails.
        """
        if len(index_html) > _MAX_INPUT_CHARS * 3:
            raise ToolError("index_html is too large")
        try:
            prefs = normalize_prefs(preferences)
        except ValueError as exc:
            raise ToolError(f"preferences are invalid: {exc}") from exc
        logger.info("Worker requested a website self-check")
        results = run_checks(index_html, compile_checks(prefs))
        passed, total = tally(results)
        return {
            "passed": passed,
            "total": total,
            "integrity_findings": scan_site_integrity(index_html)[:5],
            "failed_checks": [{"check": r["label"], "problem": r["detail"]} for r in results if not r["passed"]],
        }

    return mcp


def main() -> None:
    settings = Settings.from_env()
    settings.validate_modes()
    configure_logging(settings.log_level, settings.log_dir, service="workbench-mcp")
    server = build_workbench_server(settings)
    logger.info("Workbench MCP server listening on %s", settings.workbench_mcp_url)
    server.run(transport="http", host=settings.mcp_host, port=settings.workbench_mcp_port)


if __name__ == "__main__":
    main()
