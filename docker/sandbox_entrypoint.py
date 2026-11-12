"""Runs INSIDE the sandbox container. Reads one JSON request on stdin, writes one JSON result on stdout.

Request : {"module_name": "solution", "solution_code": "...", "test_code": "...", "timeout_s": 20}
Response: {"junit_xml": "...", "output": "<tail of pytest output>", "exit_code": 0, "timed_out": false}

No files are bind-mounted into the container: code arrives on stdin and results leave on
stdout, so the same image works whether the API runs on the host or in another container.
Only the standard library is used here; pytest itself runs in a child process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_FIELD_CHARS = 100_000
MAX_OUTPUT_CHARS = 6_000
MAX_JUNIT_CHARS = 200_000


def _fail(message: str) -> None:
    print(json.dumps({"error": message}))
    raise SystemExit(0)


def main() -> None:
    try:
        request = json.load(sys.stdin)
        module_name = request["module_name"]
        solution_code = request["solution_code"]
        test_code = request["test_code"]
        timeout_s = int(request.get("timeout_s", 20))
    except (ValueError, KeyError, TypeError) as exc:
        _fail(f"Bad sandbox request: {exc}")

    if not (isinstance(module_name, str) and module_name.isidentifier()):
        _fail("module_name must be a Python identifier")
    if not (isinstance(solution_code, str) and isinstance(test_code, str)):
        _fail("solution_code and test_code must be strings")
    if len(solution_code) > MAX_FIELD_CHARS or len(test_code) > MAX_FIELD_CHARS:
        _fail("Input too large")

    work = Path(tempfile.mkdtemp(prefix="work-", dir="/tmp"))
    (work / f"{module_name}.py").write_text(solution_code, encoding="utf-8")
    (work / "test_hidden.py").write_text(test_code, encoding="utf-8")
    report = work / "report.xml"
    command = [
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}", "test_hidden.py",
    ]  # fmt: skip
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin"), "HOME": str(work), "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1"}  # fmt: skip

    timed_out, exit_code, output = False, None, ""
    try:
        done = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=timeout_s)
        exit_code, output = done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")

    junit = report.read_text(encoding="utf-8", errors="replace")[:MAX_JUNIT_CHARS] if report.exists() else ""
    print(json.dumps({"junit_xml": junit, "output": output[-MAX_OUTPUT_CHARS:], "exit_code": exit_code, "timed_out": timed_out}))


if __name__ == "__main__":
    main()
