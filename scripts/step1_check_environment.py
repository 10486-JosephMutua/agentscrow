"""STEP 1a: verify your machine, packages and credentials before writing any logic.

    python -m scripts.step1_check_environment

Checks: Python version, required packages (with versions), settings, PayPal sandbox
OAuth, the configured Groq model, and Docker. Exits non-zero if something required fails.
"""

from __future__ import annotations

import importlib.metadata as metadata
import shutil
import sys

from agentescrow.arbiter.sandbox_runner import docker_available
from agentescrow.paypal.client import PayPalClient
from scripts._common import bootstrap, mask

REQUIRED_PACKAGES = [
    "langchain", "langchain-core", "langchain-groq", "langgraph", "fastmcp", "mcp", "flask", "flask-cors",
    "jsonschema", "pydantic", "requests", "python-dotenv", "pytest", "groq",
]  # fmt: skip


def main() -> int:
    settings, log = bootstrap("step1-check")
    failures: list[str] = []

    log.info("STEP 1: environment check")
    if sys.version_info < (3, 10):
        failures.append(f"Python 3.10+ required, found {sys.version.split()[0]}")
    log.info("Python %s", sys.version.split()[0])

    for name in REQUIRED_PACKAGES:
        try:
            log.info("package %-16s %s", name, metadata.version(name))
        except metadata.PackageNotFoundError:
            failures.append(f"missing package: {name} (run: pip install -r requirements.txt)")

    log.info("PAYPAL_MODE=%s  PAYPAL_CLIENT_ID=%s  GROQ_API_KEY=%s", settings.paypal_mode, mask(settings.paypal_client_id), mask(settings.groq_api_key))  # fmt: skip
    try:
        settings.require_mandate_secret()
        log.info("MANDATE_SECRET is set")
    except Exception as exc:  # noqa: BLE001
        failures.append(str(exc))

    if not settings.admin_token:
        log.warning("ADMIN_TOKEN is not set: the operator console (/ops) will be disabled")
    if settings.allow_unsafe_sandbox:
        log.warning("ALLOW_UNSAFE_SANDBOX=true: worker code may run WITHOUT isolation (development only)")
    if settings.paypal_mode == "sandbox" and not settings.paypal_webhook_id:
        log.warning("PAYPAL_WEBHOOK_ID is not set: webhooks are off (the return URL and polling still work)")

    # --- PayPal ------------------------------------------------------------------
    if settings.paypal_mode == "simulated":
        log.warning("PAYPAL_MODE=simulated: skipping the PayPal sandbox check (switch to 'sandbox' for the real demo)")
    else:
        try:
            settings.require_paypal()
            client = PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url, allow_live=settings.allow_live_paypal)  # fmt: skip
            client._access_token()  # noqa: SLF001 - intentional: this *is* the credential check
            log.info("PayPal sandbox OAuth OK")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"PayPal sandbox check failed: {exc}")

    # --- Groq --------------------------------------------------------------------
    needs_groq = settings.semantic_judge == "groq" or settings.worker_mode == "agent" or settings.buyer_mode == "agent"
    if not needs_groq:
        log.info("Groq is not required by the current modes (SEMANTIC_JUDGE/WORKER_MODE/BUYER_MODE)")
    elif not settings.groq_api_key:
        failures.append("GROQ_API_KEY is not set")
    else:
        try:
            from groq import Groq

            available = {model.id for model in Groq(api_key=settings.groq_api_key).models.list().data}
            if settings.groq_model in available:
                log.info("Groq OK: model %s is available (%d models total)", settings.groq_model, len(available))
            else:
                failures.append(f"GROQ_MODEL {settings.groq_model!r} not in your account's models: {sorted(available)}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"Groq check failed: {exc}")

    # --- Docker ------------------------------------------------------------------
    if docker_available():
        log.info("Docker daemon reachable: the isolated sandbox is available (build the image: docker build -t %s -f docker/sandbox.Dockerfile .)", settings.sandbox_image)  # fmt: skip
    elif shutil.which("docker"):
        log.warning("Docker is installed but the daemon is not reachable; the dev-only subprocess sandbox will be used")
    else:
        log.warning("Docker not found; the dev-only subprocess sandbox will be used (no network/file isolation)")

    if failures:
        for failure in failures:
            log.error("FAILED: %s", failure)
        return 1
    log.info("All required checks passed. Next: python -m scripts.step1_paypal_spike")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
