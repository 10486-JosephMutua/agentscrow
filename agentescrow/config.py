"""Application settings.

Every setting comes from an environment variable (optionally loaded from a ``.env``
file). Nothing in the codebase reads ``os.environ`` directly except this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER_SECRET = "change-me-to-a-long-random-string"


class ConfigError(RuntimeError):
    """Raised when a required setting is missing or invalid."""


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # --- PayPal -----------------------------------------------------------------
    paypal_client_id: str
    paypal_client_secret: str
    paypal_base_url: str
    paypal_worker_email: str
    paypal_mode: str  # "sandbox" (real PayPal sandbox API) or "simulated" (in-memory, dev/CI only)
    paypal_webhook_id: str
    allow_live_paypal: bool
    # --- Groq / LLM -------------------------------------------------------------
    groq_api_key: str
    groq_model: str
    semantic_judge: str  # "groq" or "static"
    buyer_mode: str  # "agent" or "direct"
    worker_mode: str  # "agent" (Groq LLM worker) or "scripted" (deterministic personas)
    # --- MCP servers ------------------------------------------------------------
    mcp_host: str
    paypal_mcp_port: int
    workbench_mcp_port: int
    marketplace_mcp_port: int
    api_url: str
    # --- Security ---------------------------------------------------------------
    mandate_secret: str
    admin_token: str
    capability_ttl_s: int
    rate_limit_per_min: int
    trust_proxy: bool
    admin_session_ttl_s: int
    validate_per_min: int
    max_streams: int
    max_streams_per_ip: int
    server_threads: int
    demo_personas: bool
    judge_samples: int
    receipt_signing_key: str
    groq_base_url: str
    groq_fallback_models: tuple
    single_instance: bool
    # --- Business rules ---------------------------------------------------------
    platform_fee_rate: Decimal
    default_deadline_hours: int
    max_escrow_days: int
    sweep_interval_s: int
    # --- Sandbox ----------------------------------------------------------------
    sandbox_backend: str  # "auto", "docker" or "subprocess"
    sandbox_image: str
    sandbox_timeout_s: int
    allow_unsafe_sandbox: bool
    # --- Web / storage / logging ------------------------------------------------
    public_base_url: str
    frontend_url: str
    frontend_dist: Path
    api_host: str
    api_port: int
    database_path: Path
    log_level: str
    log_dir: Path

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset({self.public_base_url, self.frontend_url})

    @property
    def paypal_mcp_url(self) -> str:
        return f"http://{self.mcp_host}:{self.paypal_mcp_port}/mcp"

    @property
    def workbench_mcp_url(self) -> str:
        return f"http://{self.mcp_host}:{self.workbench_mcp_port}/mcp"

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        """Load settings. ``env_file`` defaults to ``<project>/.env`` when present."""
        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
        return cls(
            paypal_client_id=_env("PAYPAL_CLIENT_ID"),
            paypal_client_secret=_env("PAYPAL_CLIENT_SECRET"),
            paypal_base_url=_env("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"),
            paypal_worker_email=_env("PAYPAL_WORKER_EMAIL", "payouts-simulator-receiver@paypal.com"),
            paypal_mode=_env("PAYPAL_MODE", "sandbox").lower(),
            paypal_webhook_id=_env("PAYPAL_WEBHOOK_ID"),
            allow_live_paypal=_env("ALLOW_LIVE_PAYPAL", "false").lower() == "true",
            groq_api_key=_env("GROQ_API_KEY"),
            groq_model=_env("GROQ_MODEL", "openai/gpt-oss-120b"),
            semantic_judge=_env("SEMANTIC_JUDGE", "groq").lower(),
            buyer_mode=_env("BUYER_MODE", "agent").lower(),
            worker_mode=_env("WORKER_MODE", "agent").lower(),
            mcp_host=_env("MCP_HOST", "127.0.0.1"),
            paypal_mcp_port=int(_env("PAYPAL_MCP_PORT", "8765")),
            workbench_mcp_port=int(_env("WORKBENCH_MCP_PORT", "8766")),
            marketplace_mcp_port=int(_env("MARKETPLACE_MCP_PORT", "8767")),
            api_url=_env("AGENTESCROW_API", f"http://{_env('API_HOST', '127.0.0.1')}:{_env('API_PORT', '5000')}").rstrip("/"),
            mandate_secret=_env("MANDATE_SECRET"),
            admin_token=_env("ADMIN_TOKEN"),
            capability_ttl_s=int(_env("CAPABILITY_TTL_S", str(7 * 24 * 3600))),
            rate_limit_per_min=int(_env("RATE_LIMIT_PER_MIN", "30")),
            trust_proxy=_env("TRUST_PROXY", "false").lower() == "true",
            admin_session_ttl_s=int(_env("ADMIN_SESSION_TTL_S", str(8 * 3600))),
            validate_per_min=int(_env("VALIDATE_PER_MIN", "6")),
            max_streams=int(_env("MAX_STREAMS", "100")),
            max_streams_per_ip=int(_env("MAX_STREAMS_PER_IP", "8")),
            server_threads=int(_env("SERVER_THREADS", "128")),
            demo_personas=_env("DEMO_PERSONAS", "true").lower() == "true",
            judge_samples=int(_env("JUDGE_SAMPLES", "3")),
            receipt_signing_key=_env("RECEIPT_SIGNING_KEY"),
            groq_base_url=_env("GROQ_BASE_URL"),
            groq_fallback_models=tuple(m.strip() for m in _env("GROQ_FALLBACK_MODELS", "openai/gpt-oss-120b,llama-3.3-70b-versatile,openai/gpt-oss-20b").split(",") if m.strip()),
            single_instance=_env("SINGLE_INSTANCE", "true").lower() == "true",
            platform_fee_rate=Decimal(_env("PLATFORM_FEE_RATE", "0.0667")),
            default_deadline_hours=int(_env("DEFAULT_DEADLINE_HOURS", "24")),
            max_escrow_days=int(_env("MAX_ESCROW_DAYS", "25")),
            sweep_interval_s=int(_env("SWEEP_INTERVAL_S", "60")),
            sandbox_backend=_env("SANDBOX_BACKEND", "auto").lower(),
            sandbox_image=_env("SANDBOX_IMAGE", "agentescrow-sandbox"),
            sandbox_timeout_s=int(_env("SANDBOX_TIMEOUT_S", "20")),
            allow_unsafe_sandbox=_env("ALLOW_UNSAFE_SANDBOX", "false").lower() == "true",
            public_base_url=_env("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/"),
            frontend_url=_env("FRONTEND_URL", "http://localhost:5173").rstrip("/"),
            frontend_dist=Path(_env("FRONTEND_DIST", str(PROJECT_ROOT / "frontend" / "dist"))),
            api_host=_env("API_HOST", "127.0.0.1"),
            api_port=int(_env("API_PORT", "5000")),
            database_path=Path(_env("DATABASE_PATH", str(PROJECT_ROOT / "data" / "agentescrow.db"))),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            log_dir=Path(_env("LOG_DIR", str(PROJECT_ROOT / "logs"))),
        )

    # --- Validation helpers: each caller checks only what it needs ---------------
    def validate_modes(self) -> None:
        """Reject typos in enum-like settings early, with a clear message."""
        allowed = {
            "PAYPAL_MODE": (self.paypal_mode, {"sandbox", "simulated"}),
            "SEMANTIC_JUDGE": (self.semantic_judge, {"groq", "static"}),
            "BUYER_MODE": (self.buyer_mode, {"agent", "direct"}),
            "WORKER_MODE": (self.worker_mode, {"agent", "scripted"}),
            "SANDBOX_BACKEND": (self.sandbox_backend, {"auto", "docker", "subprocess"}),
        }
        for name, (value, options) in allowed.items():
            if value not in options:
                raise ConfigError(f"{name} must be one of {sorted(options)}, got {value!r}")
        if not 1 <= self.max_escrow_days <= 28:
            raise ConfigError("MAX_ESCROW_DAYS must be between 1 and 28 (PayPal authorizations last 29 days)")
        if not 1 <= self.judge_samples <= 9:
            raise ConfigError("JUDGE_SAMPLES must be between 1 and 9")
        if self.default_deadline_hours < 1 or self.default_deadline_hours > self.max_escrow_days * 24:
            raise ConfigError("DEFAULT_DEADLINE_HOURS must be between 1 and MAX_ESCROW_DAYS * 24")

    def require_paypal(self) -> None:
        if self.paypal_mode == "simulated":
            return
        missing = [
            name
            for name, value in (
                ("PAYPAL_CLIENT_ID", self.paypal_client_id),
                ("PAYPAL_CLIENT_SECRET", self.paypal_client_secret),
            )
            if not value
        ]
        if missing:
            raise ConfigError(f"Missing PayPal settings: {', '.join(missing)}")

    def require_groq(self) -> None:
        if not self.groq_api_key:
            raise ConfigError("Missing GROQ_API_KEY")

    def require_admin_token(self) -> None:
        if self.admin_token and len(self.admin_token) < 16:
            raise ConfigError("ADMIN_TOKEN must be at least 16 characters (or leave it empty to disable admin access)")

    def require_mandate_secret(self) -> None:
        if not self.mandate_secret or self.mandate_secret == PLACEHOLDER_SECRET:
            raise ConfigError("Set MANDATE_SECRET to a long random string (see .env.example)")
        if len(self.mandate_secret) < 16:
            raise ConfigError("MANDATE_SECRET must be at least 16 characters")
        self.require_admin_token()
