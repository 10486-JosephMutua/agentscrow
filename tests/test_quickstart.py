"""The judge's first-run path: the offline preset must produce a configuration the server accepts."""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values

from agentescrow.config import ConfigError, Settings
from scripts import quickstart

ROOT = Path(__file__).resolve().parent.parent
ENV_KEYS = ("PAYPAL_MODE", "WORKER_MODE", "BUYER_MODE", "SEMANTIC_JUDGE", "MANDATE_SECRET", "ADMIN_TOKEN", "ALLOW_UNSAFE_SANDBOX", "GROQ_API_KEY", "PAYPAL_CLIENT_ID")


@pytest.fixture
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_offline_preset_needs_no_keys_and_passes_the_servers_own_checks(tmp_path, clean_env):
    text, generated = quickstart.render_env((ROOT / ".env.offline.example").read_text(encoding="utf-8"))
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")

    assert not [k for k, v in dotenv_values(env_file).items() if (v or "").startswith("__")]  # no placeholder left behind
    settings = Settings.from_env(env_file)
    settings.validate_modes()
    settings.require_mandate_secret()  # also validates ADMIN_TOKEN length
    settings.require_paypal()  # simulated mode: no credentials needed
    assert (settings.paypal_mode, settings.worker_mode, settings.buyer_mode, settings.semantic_judge) == ("simulated", "scripted", "direct", "static")
    assert settings.mandate_secret == generated["MANDATE_SECRET"] and settings.admin_token == generated["ADMIN_TOKEN"]


def test_secrets_are_random_per_run():
    template = (ROOT / ".env.offline.example").read_text(encoding="utf-8")
    first, _ = quickstart.render_env(template)
    second, _ = quickstart.render_env(template)
    assert first != second


def test_real_template_gets_secrets_but_still_demands_the_keys(tmp_path, clean_env):
    text, _ = quickstart.render_env((ROOT / ".env.example").read_text(encoding="utf-8"))
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    settings = Settings.from_env(env_file)
    settings.require_mandate_secret()
    with pytest.raises(ConfigError):
        settings.require_paypal()  # sandbox mode without PayPal credentials must be refused


def test_an_existing_env_is_never_overwritten(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MINE=1\n", encoding="utf-8")
    monkeypatch.setattr(quickstart, "ENV_FILE", env_file)
    assert quickstart.write_env(real=False, force=False) is None
    assert env_file.read_text(encoding="utf-8") == "MINE=1\n"
    assert quickstart.write_env(real=False, force=True) is not None
    assert env_file.with_suffix(".bak").read_text(encoding="utf-8") == "MINE=1\n"
