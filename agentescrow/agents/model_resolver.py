"""Pick a Groq model that actually exists on the account, falling back to known alternatives.

Model ids change over time. Rather than failing the first job with a 404, the first call checks the account's model list
once per process, keeps the configured model when it is available, and otherwise uses the first available fallback.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from groq import Groq

from agentescrow.config import Settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _available_models(api_key: str, base_url: str) -> frozenset[str]:
    client = Groq(api_key=api_key, base_url=base_url or None, max_retries=1, timeout=10.0)
    return frozenset(model.id for model in client.models.list().data)


def resolve_groq_model(settings: Settings) -> str:
    """The configured model if available, else the first available fallback, else the configured one (and a warning)."""
    configured = settings.groq_model
    try:
        available = _available_models(settings.groq_api_key, settings.groq_base_url)
    except Exception as exc:  # noqa: BLE001 - offline or rate limited: keep going with the configured model
        logger.warning("Could not list Groq models (%s); using the configured model %s", exc, configured)
        return configured
    if configured in available:
        return configured
    for candidate in settings.groq_fallback_models:
        if candidate in available:
            logger.warning("Groq model %s is not available on this account; falling back to %s", configured, candidate)
            return candidate
    logger.error("None of the configured Groq models is available (%s); requests will likely fail", sorted(available)[:8])
    return configured
