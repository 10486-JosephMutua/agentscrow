"""Docker sandbox: command hardening, the stdin/stdout protocol, and result-tampering defenses.

Docker itself is not required here: the container entrypoint is exercised as a plain
subprocess, which is exactly what runs inside the container.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentescrow.arbiter import sandbox_runner
from agentescrow.arbiter.sandbox_runner import (
    SandboxRun, _docker_command, _parse_junit_text, _summary_counts, reports_agree, run_pytest,
)  # fmt: skip
from agentescrow.samples import SCRIPTED_DELIVERABLES, build_sample_contract

ENTRYPOINT = Path(__file__).resolve().parent.parent / "docker" / "sandbox_entrypoint.py"


def test_docker_command_is_locked_down():
    command = _docker_command("agentescrow-sandbox", "c1")
    joined = " ".join(command)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--pids-limit 128", "--memory 256m", "-i"):
        assert flag in joined, flag
    assert "-v " not in joined and "--volume" not in joined, "nothing may be bind-mounted into the sandbox"
    assert "--privileged" not in joined and "docker.sock" not in joined
    assert command[-3:] == ["python", "/opt/sandbox/sandbox_entrypoint.py"][-3:] or command[-2:] == ["python", "/opt/sandbox/sandbox_entrypoint.py"]


def _entrypoint(request: dict) -> dict:
    done = subprocess.run([sys.executable, str(ENTRYPOINT)], input=json.dumps(request), capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_entrypoint_protocol_with_the_honest_solution():
    _, hidden = build_sample_contract()
    out = _entrypoint({"module_name": "solution", "solution_code": SCRIPTED_DELIVERABLES["honest"]["solution_code"], "test_code": hidden, "timeout_s": 20})
    assert out["timed_out"] is False and out["exit_code"] == 0
    assert _parse_junit_text(out["junit_xml"]) == (9, 0, 9)
    assert reports_agree((9, 0, 9), out["output"])


@pytest.mark.parametrize(
    "request_body",
    [
        {"module_name": "not valid!", "solution_code": "x", "test_code": "y"},
        {"module_name": "solution", "solution_code": 1, "test_code": "y"},
        {"module_name": "solution", "solution_code": "x" * 200_000, "test_code": "y"},
        {"solution_code": "x"},
    ],
)
def test_entrypoint_rejects_bad_requests(request_body):
    assert "error" in _entrypoint(request_body)


def test_entrypoint_enforces_its_own_timeout():
    out = _entrypoint({"module_name": "solution", "solution_code": "def f():\n    while True: pass\n", "test_code": "from solution import f\ndef test_x():\n    f()\n", "timeout_s": 2})
    assert out["timed_out"] is True


def test_docker_path_end_to_end_with_a_stubbed_docker(monkeypatch):
    """Route `docker run` to the real entrypoint to prove run_pytest wires stdin/stdout correctly."""
    _, hidden = build_sample_contract()
    real_popen = subprocess.Popen

    def fake_popen(command, **kwargs):
        assert command[0] == "docker"
        return real_popen([sys.executable, str(ENTRYPOINT)], **{k: v for k, v in kwargs.items() if k != "start_new_session"})

    monkeypatch.setattr(sandbox_runner.subprocess, "Popen", fake_popen)
    run = run_pytest(SCRIPTED_DELIVERABLES["sloppy"]["solution_code"], hidden, backend="docker")
    assert isinstance(run, SandboxRun)
    assert (run.result.backend, run.result.passed, run.result.failed, run.result.total) == ("docker", 5, 4, 9)
    assert run.result.error is None


def test_docker_failure_is_an_infrastructure_error_not_a_verdict(monkeypatch):
    class Dead:
        returncode = 125

        def communicate(self, *a, **k):
            return "", "Unable to find image 'agentescrow-sandbox:latest' locally"

    monkeypatch.setattr(sandbox_runner.subprocess, "Popen", lambda *a, **k: Dead())
    run = run_pytest("def f(): pass", "def test_x(): pass", backend="docker")
    assert run.result.error and "Unable to find image" in run.result.error
    assert run.result.total == 0 and not run.result.timed_out


def test_a_forged_report_is_detected():
    forged = '<testsuites><testsuite tests="8" failures="0" errors="0" skipped="0"></testsuite></testsuites>'
    assert _parse_junit_text(forged) == (8, 0, 8)
    # Worker code exited early after writing the forged XML: pytest never printed a summary.
    assert not reports_agree((8, 0, 8), "")
    # ...or printed a summary that disagrees with the XML.
    assert not reports_agree((8, 0, 8), "3 failed, 5 passed in 0.04s")
    assert reports_agree((5, 3, 8), "3 failed, 5 passed in 0.04s")
    assert reports_agree((8, 0, 8), "8 passed in 0.02s")
    assert reports_agree((0, 8, 8), "8 errors in 0.02s")


def test_summary_parsing():
    assert _summary_counts("....\n2 failed, 6 passed, 1 skipped in 0.5s\n") == {"failed": 2, "passed": 6, "skipped": 1}
    assert _summary_counts("no summary here") == {}


def test_run_pytest_flags_tampering_as_an_infrastructure_error(monkeypatch):
    forged_xml = '<testsuites><testsuite tests="8" failures="0" errors="0" skipped="0"></testsuite></testsuites>'
    monkeypatch.setattr(
        sandbox_runner, "_run_in_subprocess",
        lambda *a, **k: sandbox_runner._RawRun(junit_xml=forged_xml, output="", exit_code=0),
    )  # fmt: skip
    run = run_pytest("x", "y", backend="subprocess", allow_unsafe=True)
    assert run.result.error and "tampering" in run.result.error
    assert run.result.passed == 0 and run.result.total == 0
