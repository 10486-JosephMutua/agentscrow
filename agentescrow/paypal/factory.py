"""Chooses the PayPal client implementation from settings."""

from __future__ import annotations

import logging
from typing import Union

from agentescrow.config import Settings
from agentescrow.paypal.client import PayPalClient
from agentescrow.paypal.simulator import SimulatedPayPalClient

logger = logging.getLogger(__name__)

AnyPayPalClient = Union[PayPalClient, SimulatedPayPalClient]


def build_paypal_client(settings: Settings) -> AnyPayPalClient:
    settings.require_paypal()
    if settings.paypal_mode == "simulated":
        # Persist next to the job database: the jobs outlive a restart, so the (fake) PayPal ids they hold must too.
        return SimulatedPayPalClient(state_path=settings.database_path.with_name("paypal_simulator.json"))
    logger.info("Using the PayPal sandbox REST API at %s", settings.paypal_base_url)
    return PayPalClient(
        settings.paypal_client_id,
        settings.paypal_client_secret,
        settings.paypal_base_url,
        allow_live=settings.allow_live_paypal,
    )
