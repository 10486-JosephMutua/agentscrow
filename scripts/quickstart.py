"""One-command setup for judges and first-time users (standard library only).

    python -m scripts.quickstart                # offline demo: no keys, no PayPal, no Docker; builds the UI if it can; starts the server
    python -m scripts.quickstart --no-start     # only prepare .env and the UI
    python -m scripts.quickstart --real         # prepare .env for the REAL PayPal sandbox + Groq (you add the keys), do not start
    python -m scripts.quickstart --force        # replace an existing .env (the old one is saved as .env.bak)

It never overwrites an existing .env unless you pass --force, and it never prints or stores secrets anywhere else.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
OFFLINE_TEMPLATE = ROOT / ".env.offline.example"
REAL_TEMPLATE = ROOT / ".env.example"
FRONTEND = ROOT / "frontend"
MIN_PYTHON = (3, 12)


def render_env(template: str) -> tuple[str, dict[str, str]]:
    """Fill the secret placeholders in ``template``. Returns the text and the generated values."""
    generated = {"MANDATE_SECRET": secrets.token_urlsafe(48), "ADMIN_TOKEN": secrets.token_urlsafe(32)}
    out = []
    for line in template.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in generated and (value.strip() in ("", "change-me-to-a-long-random-string") or value.strip().startswith("__")):
            line = f"{key.strip()}={generated[key.strip()]}"
        out.append(line)
    return "\n".join(out) + "\n", generated


def write_env(real: bool, force: bool) -> dict[str, str] | None:
    """Create .env. Returns the generated secrets, or None when an existing .env was kept."""
    if ENV_FILE.exists() and not force:
        print(f"* Keeping your existing {ENV_FILE.name} (use --force to replace it).")
        return None
    template = (REAL_TEMPLATE if real else OFFLINE_TEMPLATE).read_text(encoding="utf-8")
    text, generated = render_env(template)
    if ENV_FILE.exists():
        shutil.copyfile(ENV_FILE, ENV_FILE.with_suffix(".bak"))
        print("* Saved the old .env as .env.bak")
    ENV_FILE.write_text(text, encoding="utf-8")
    print(f"* Wrote {ENV_FILE.name} ({'real PayPal sandbox + Groq' if real else 'offline demo'}) with fresh random secrets.")
    return generated


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required (you have {sys.version.split()[0]}).")


def check_packages() -> None:
    missing = []
    for module in ("flask", "waitress", "pydantic", "dotenv", "langchain", "groq", "cryptography", "jsonschema"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        raise SystemExit(
            "Missing Python packages: " + ", ".join(missing) + "\nInstall them inside your virtualenv:  pip install -r requirements.txt"
        )


def build_ui() -> None:
    dist = FRONTEND / "dist" / "index.html"
    if dist.is_file():
        print("* UI already built (frontend/dist).")
        return
    npm = shutil.which("npm")
    if not npm:
        print("! frontend/dist is missing and Node.js/npm was not found.")
        print("  The API still runs, and `python -m scripts.site_demo` works, but the web UI needs:  cd frontend && npm ci && npm run build")
        print("  (Node 22 or newer).")
        return
    print("* Building the web UI (first time only, about a minute)...")
    try:
        subprocess.run([npm, "ci"], cwd=FRONTEND, check=True)
        subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"! The UI build failed ({exc}). The API still runs; see the README for the manual build.")


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=8).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--real", action="store_true", help="prepare .env for the real PayPal sandbox + Groq agents (keys are yours to add)")
    parser.add_argument("--no-start", action="store_true", help="prepare everything but do not start the server")
    parser.add_argument("--force", action="store_true", help="replace an existing .env (backed up to .env.bak)")
    args = parser.parse_args()

    check_python()
    generated = write_env(args.real, args.force)
    if generated:
        print(f"* Operator console token (Admin page): {generated['ADMIN_TOKEN']}")

    if args.real:
        print(
            "\nNext: edit .env and add PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_WORKER_EMAIL and GROQ_API_KEY,\n"
            "build the sandbox image (docker build -t agentescrow-sandbox -f docker/sandbox.Dockerfile .), then run:\n"
            "  python -m scripts.step1_check_environment\n  python -m agentescrow.api.app --inprocess"
        )
        build_ui()
        return

    check_packages()
    build_ui()
    if docker_ready():
        print("* Docker is running: worker code will run in the hardened sandbox container (build the image once with: "
              "docker build -t agentescrow-sandbox -f docker/sandbox.Dockerfile .).")
    else:
        print("* Docker not detected: worker code will run in the UNISOLATED subprocess sandbox. Fine for this local demo only.")
    if args.no_start:
        print("\nStart it with:  python -m agentescrow.api.app --inprocess   then open http://localhost:5000")
        return
    print("\n* Starting AgentEscrow on http://localhost:5000  (Ctrl+C to stop). Click \"Run the guided demo\".\n")
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable, "-m", "agentescrow.api.app", "--inprocess"])


if __name__ == "__main__":
    main()