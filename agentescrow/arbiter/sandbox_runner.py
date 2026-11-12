"""Tier 2: run the hidden pytest suite against the worker's code in isolation.

Backends
--------
``docker``      The only backend considered safe for untrusted code. The worker's code and the
                tests go in over stdin to a throw-away container started with no network, a
                read-only root file system, dropped capabilities, no privilege escalation, and
                memory / CPU / process / file-size limits. Nothing is bind-mounted, so this
                also works when the API itself runs in a container. Needs the image from
                ``docker/sandbox.Dockerfile``.
``subprocess``  Development fallback with a timeout and POSIX resource limits only. It has NO
                network or file-system isolation, so it is refused unless the operator sets
                ``ALLOW_UNSAFE_SANDBOX=true``.

Fail closed: with ``backend="auto"`` and no reachable Docker daemon, running worker code raises
:class:`SandboxUnavailable` instead of silently falling back. The job then waits in
``NEEDS_REVIEW`` (nobody is paid or voided because of our infrastructure).

Result integrity: the test report is written by the process that runs the worker's code, so it
is cross-checked against pytest's own summary line; a mismatch is treated as an infrastructure
error, never as a pass.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from agentescrow.domain.models import SandboxResult

logger = logging.getLogger(__name__)

_OUTPUT_TAIL_CHARS = 3000
_MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
_MAX_FILE_BYTES = 10 * 1024 * 1024
# Time allowed on top of the test timeout for container start/stop. A cold Docker Desktop (WSL2) can need far
# longer than a warm daemon, so operators can raise it with SANDBOX_START_GRACE_S.
_DOCKER_START_GRACE_S = int(os.environ.get("SANDBOX_START_GRACE_S", "25"))
_SUMMARY = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|deselected|xfailed|xpassed|warnings?)")


class SandboxUnavailable(RuntimeError):
    """No safe way to run untrusted code is available (and the operator has not allowed an unsafe one)."""


@dataclass(frozen=True)
class SandboxRun:
    """Structured result plus raw pytest output.

    The raw output can contain hidden-test assertions, so it is only logged server-side (or
    returned to a worker for the worker's *own* tests); it is never stored on a job.
    """

    result: SandboxResult
    output: str


@lru_cache(maxsize=1)
def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=8).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def resolve_backend(requested: str, *, allow_unsafe: bool = False) -> str:
    """Pick the backend, or raise :class:`SandboxUnavailable` if none is acceptable."""
    if requested not in {"auto", "docker", "subprocess"}:
        raise ValueError(f"Unknown sandbox backend {requested!r}")
    if requested == "docker":
        return "docker"
    if requested == "auto" and docker_available():
        return "docker"
    if allow_unsafe:
        logger.warning("Using the UNISOLATED subprocess sandbox (ALLOW_UNSAFE_SANDBOX=true). Development only.")
        return "subprocess"
    raise SandboxUnavailable(
        "Docker is required to run worker code safely and is not reachable. Start Docker and build the image "
        "(docker build -t agentescrow-sandbox -f docker/sandbox.Dockerfile .), or set ALLOW_UNSAFE_SANDBOX=true "
        "for local development only."
    )


# ------------------------------------------------------------------ result parsing --
def _parse_junit_text(xml_text: str) -> tuple[int, int, int]:
    """Return (passed, failed, total) from pytest JUnit XML text."""
    root = ET.fromstring(xml_text)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) for s in suites)
    errors = sum(int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    passed = max(tests - failures - errors - skipped, 0)
    return passed, tests - passed, tests


def _summary_counts(output: str) -> dict[str, int]:
    """Counts from pytest's final summary line, e.g. '3 failed, 5 passed in 0.04s'."""
    counts: dict[str, int] = {}
    for line in reversed(output.strip().splitlines()):
        if " in " in line and _SUMMARY.search(line):
            for number, word in _SUMMARY.findall(line):
                counts[word.rstrip("s") if word.startswith("error") else word] = int(number)
            break
    return counts


def reports_agree(junit: tuple[int, int, int], output: str) -> bool:
    """True if the XML report's counts match pytest's own console summary."""
    passed, failed, total = junit
    summary = _summary_counts(output)
    if not summary:
        return False
    return summary.get("passed", 0) == passed and summary.get("failed", 0) + summary.get("error", 0) == failed


def _killed_by_resource_limit(exit_code: int | None) -> bool:
    """True if a POSIX child died from the CPU-limit signal (or SIGKILL), i.e. it ran out of budget."""
    if exit_code is None or exit_code >= 0 or os.name != "posix":
        return False
    return -exit_code in (signal.SIGXCPU, signal.SIGKILL)


def _limit_resources(timeout_s: int) -> None:  # pragma: no cover - runs in the child process
    import resource

    # The wall-clock timeout normally fires first; the CPU limit is a backstop.
    resource.setrlimit(resource.RLIMIT_CPU, (timeout_s + 2, timeout_s + 3))
    resource.setrlimit(resource.RLIMIT_AS, (_MEMORY_LIMIT_BYTES, _MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_MAX_FILE_BYTES, _MAX_FILE_BYTES))


# ---------------------------------------------------------------------- backends --
def _docker_command(image: str, container: str) -> list[str]:
    return [
        "docker", "run", "--rm", "-i", "--name", container,
        "--pull", "never",  # a missing image must fail in milliseconds, never hang on (or pull from) a registry
        "--network", "none",
        "--memory", "256m", "--memory-swap", "256m", "--cpus", "1", "--pids-limit", "128",
        "--read-only", "--tmpfs", "/tmp:rw,size=32m",
        "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
        "--ulimit", "nofile=256", "--ulimit", f"fsize={_MAX_FILE_BYTES}",
        image, "python", "/opt/sandbox/sandbox_entrypoint.py",
    ]  # fmt: skip


@dataclass
class _RawRun:
    junit_xml: str = ""
    output: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    error: str | None = None


def _force_kill(process: subprocess.Popen) -> None:
    """Kill a child (and its process group) and reap it, without ever waiting unboundedly."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        process.communicate(timeout=5)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        logger.error("Could not reap sandbox process %s", process.pid)


def _run_in_docker(solution_code: str, test_code: str, module_name: str, image: str, timeout_s: int) -> _RawRun:
    container = f"agentescrow-{uuid.uuid4().hex[:12]}"
    request = json.dumps(
        {"module_name": module_name, "solution_code": solution_code, "test_code": test_code, "timeout_s": timeout_s}
    )
    process = subprocess.Popen(
        _docker_command(image, container), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )  # fmt: skip
    limit = timeout_s + _DOCKER_START_GRACE_S
    try:
        stdout, stderr = process.communicate(request, timeout=limit)
    except subprocess.TimeoutExpired:
        try:
            subprocess.run(["docker", "kill", container], capture_output=True, timeout=15)
        except (subprocess.SubprocessError, OSError) as exc:
            logger.error("`docker kill` failed: %s", exc)
        _force_kill(process)  # never trust `docker kill` alone: the client process must not outlive the timeout
        logger.warning("Sandbox container exceeded %ss and was killed", limit)
        # The *test run* has its own timeout inside the container (reported as timed_out=True below, which is the
        # worker's fault). Getting here means Docker itself never answered within the limit: the daemon is hung,
        # still starting, or the container never started. That is OUR infrastructure failing, so it must not be
        # reported as a worker timeout (which voids the job); it becomes an error and the job waits in NEEDS_REVIEW.
        return _RawRun(
            error=f"Docker did not finish within {limit}s (daemon hung or still starting?). Check `docker info`, "
            "that the image exists (`docker images agentescrow-sandbox`), or raise SANDBOX_START_GRACE_S."
        )
    if process.returncode != 0:
        return _RawRun(error=f"Docker failed (exit {process.returncode}): {stderr.strip()[-300:]}")
    try:
        data = json.loads(stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return _RawRun(error="Sandbox returned unreadable output")
    if "error" in data:
        return _RawRun(error=f"Sandbox rejected the request: {data['error']}")
    return _RawRun(
        junit_xml=data.get("junit_xml", ""), output=data.get("output", ""),
        exit_code=data.get("exit_code"), timed_out=bool(data.get("timed_out")),
    )  # fmt: skip


def _run_in_subprocess(solution_code: str, test_code: str, module_name: str, timeout_s: int) -> _RawRun:
    with tempfile.TemporaryDirectory(prefix="agentescrow-sandbox-") as tmp:
        work = Path(tmp)
        (work / f"{module_name}.py").write_text(solution_code, encoding="utf-8")
        (work / "test_hidden.py").write_text(test_code, encoding="utf-8")
        report = work / "report.xml"
        command = [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}", "test_hidden.py",
        ]  # fmt: skip
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work), "LANG": "C.UTF-8",
               "PYTHONDONTWRITEBYTECODE": "1"}  # fmt: skip
        if os.name == "nt":  # pragma: no cover
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
        preexec = (lambda: _limit_resources(timeout_s)) if os.name == "posix" else None
        raw = _RawRun()
        try:
            process = subprocess.Popen(
                command, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, start_new_session=True, preexec_fn=preexec,
            )  # fmt: skip
            try:
                raw.output, _ = process.communicate(timeout=timeout_s)
                raw.exit_code = process.returncode
                if _killed_by_resource_limit(raw.exit_code):
                    raw.timed_out = True  # CPU limit hit: same verdict as running out of wall-clock time
                    logger.warning("Sandbox process was killed by a resource limit (signal %s)", -raw.exit_code)
            except subprocess.TimeoutExpired:
                raw.timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                raw.output, _ = process.communicate(timeout=5)
                logger.warning("Sandbox run timed out after %ss", timeout_s)
        except (OSError, subprocess.SubprocessError) as exc:
            raw.error = f"Could not start sandbox: {exc}"
        if report.exists():
            raw.junit_xml = report.read_text(encoding="utf-8", errors="replace")
        return raw


def run_pytest(
    solution_code: str,
    test_code: str,
    *,
    module_name: str = "solution",
    backend: str = "auto",
    image: str = "agentescrow-sandbox",
    timeout_s: int = 20,
    allow_unsafe: bool = False,
) -> SandboxRun:
    """Run ``test_code`` against ``solution_code`` in the chosen sandbox and return counts."""
    chosen = resolve_backend(backend, allow_unsafe=allow_unsafe)
    started = time.monotonic()
    logger.info("Tier 2 sandbox starting (backend=%s, timeout=%ss)", chosen, timeout_s)

    try:
        if chosen == "docker":
            raw = _run_in_docker(solution_code, test_code, module_name, image, timeout_s)
        else:
            raw = _run_in_subprocess(solution_code, test_code, module_name, timeout_s)
    except (OSError, subprocess.SubprocessError) as exc:
        raw = _RawRun(error=f"Could not start sandbox: {exc}")
        logger.error(raw.error)

    passed = failed = total = 0
    error = raw.error
    if raw.junit_xml and not raw.timed_out and error is None:
        try:
            passed, failed, total = _parse_junit_text(raw.junit_xml)
            if not reports_agree((passed, failed, total), raw.output):
                error = "Test report does not match pytest's own summary (possible tampering); needs human review"
                passed = failed = total = 0
                logger.error(error)
        except ET.ParseError:
            error = "Sandbox produced an unreadable test report"
            logger.error(error)

    duration = round(time.monotonic() - started, 2)
    output_tail = (raw.output or "")[-_OUTPUT_TAIL_CHARS:]
    result = SandboxResult(
        backend=chosen, passed=passed, failed=failed, total=total, exit_code=raw.exit_code,
        timed_out=raw.timed_out, duration_s=duration, error=error,
        score=round(passed / total, 4) if total else 0.0,
    )  # fmt: skip
    logger.info(
        "Tier 2 sandbox finished: %d/%d passed, exit=%s, timed_out=%s, %ss",
        passed, total, raw.exit_code, raw.timed_out, duration,
    )  # fmt: skip
    logger.debug("Sandbox output tail:\n%s", output_tail)
    return SandboxRun(result=result, output=output_tail)
