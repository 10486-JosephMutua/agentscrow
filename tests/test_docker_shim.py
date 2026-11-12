"""The real `docker` code path (real subprocesses, real stdin/stdout protocol) against a stand-in `docker` executable.

The stand-in refuses any `docker run` that lacks the hardening flags, so these tests prove what AgentEscrow actually puts
on the command line. They do NOT prove container isolation itself: that needs a real Docker daemon.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from agentescrow.arbiter import sandbox_runner
from agentescrow.arbiter.arbiter import Arbiter
from agentescrow.arbiter.sandbox_runner import docker_available, run_pytest
from agentescrow.arbiter.semantic_judge import StaticSemanticJudge
from agentescrow.samples import SCRIPTED_DELIVERABLES, build_sample_contract

FAKES = Path(__file__).resolve().parent / "fakes"


@pytest.fixture
def docker(monkeypatch, tmp_path):
    log = tmp_path / "docker.log"
    monkeypatch.setenv("PATH", f"{FAKES}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_DOCKER_PYTHON", sys.executable)
    docker_available.cache_clear()
    yield log
    docker_available.cache_clear()


def test_docker_is_detected_through_the_real_cli_path(docker):
    assert docker_available() is True
    assert sandbox_runner.resolve_backend("auto") == "docker"  # no ALLOW_UNSAFE_SANDBOX needed


def test_a_real_docker_run_executes_the_hidden_tests(docker):
    _, hidden = build_sample_contract()
    run = run_pytest(SCRIPTED_DELIVERABLES["honest"]["solution_code"], hidden, backend="docker")
    assert (run.result.backend, run.result.passed, run.result.total, run.result.error) == ("docker", 9, 9, None)
    command = docker.read_text().splitlines()[-1]
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--pids-limit 128", "--memory 256m"):
        assert flag in command
    assert " -v " not in command and "--privileged" not in command  # nothing from the host is mounted into the sandbox


def test_the_arbiter_runs_end_to_end_through_docker(docker, settings):
    import asyncio

    contract, hidden = build_sample_contract()
    docker_settings = replace(settings, sandbox_backend="docker", allow_unsafe_sandbox=False)
    verdict = asyncio.run(Arbiter(docker_settings, StaticSemanticJudge(0.9)).evaluate(contract, hidden, SCRIPTED_DELIVERABLES["sloppy"]))
    assert verdict.sandbox.backend == "docker" and (verdict.sandbox.passed, verdict.sandbox.total) == (5, 9)


def test_an_infinite_loop_is_stopped_inside_the_container(docker):
    code = "def rle_encode(s):\n    while True:\n        pass\n"
    run = run_pytest(code, "from solution import rle_encode\n\n\ndef test_a():\n    rle_encode('a')\n", backend="docker", timeout_s=2)
    assert run.result.timed_out and run.result.passed == 0


def test_a_hung_container_is_killed(docker, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_HANG", "1")
    monkeypatch.setattr(sandbox_runner, "_DOCKER_START_GRACE_S", 1)
    run = run_pytest("def f(): pass", "from solution import f\n\n\ndef test_a():\n    f()\n", backend="docker", timeout_s=1)
    assert any(line.startswith("kill agentescrow-") for line in docker.read_text().splitlines())
    # A Docker daemon that never answers is OUR failure, not the worker's: it must surface as an infrastructure error
    # (job -> NEEDS_REVIEW), never as `timed_out`, which the settlement policy treats as a worker fault and voids on.
    assert run.result.error and "Docker did not finish" in run.result.error
    assert not run.result.timed_out and run.result.total == 0


def test_docker_never_pulls_the_sandbox_image(docker):
    run_pytest("def f(): pass", "from solution import f\n\n\ndef test_a():\n    f()\n", backend="docker")
    assert "--pull never" in docker.read_text().splitlines()[-1]


def test_an_unsafe_command_line_is_refused_and_becomes_an_infrastructure_error(docker, monkeypatch):
    real = sandbox_runner._docker_command  # noqa: SLF001

    def careless(image, container):
        command = real(image, container)
        index = command.index("--network")
        return command[:index] + command[index + 2 :]  # a regression that forgets `--network none`

    monkeypatch.setattr(sandbox_runner, "_docker_command", careless)
    run = run_pytest("def f(): pass", "def test_a():\n    pass\n", backend="docker")
    assert run.result.error and "exit 125" in run.result.error and "refusing an unsafe" in run.result.error
    assert run.result.total == 0  # never treated as a verdict about the worker
