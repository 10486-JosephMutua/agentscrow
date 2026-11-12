from decimal import Decimal

import pytest

from agentescrow.domain.mandate import (
    MandateError, issue_mandate, issue_settlement_ticket, verify_mandate, verify_settlement_ticket,
)  # fmt: skip
from agentescrow.money import floor_cents, money_str, round_cents, to_decimal

SECRET = "unit-test-secret-that-is-long-enough"


def test_money_formatting_and_rounding():
    assert money_str(75) == "75.00"
    assert money_str("4.675") == "4.68"  # half-up
    assert floor_cents("3.959") == Decimal("3.95")  # never over-charge
    assert round_cents(Decimal("0.3335")) == Decimal("0.33")


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity", ""])
def test_to_decimal_rejects_garbage(bad):
    with pytest.raises(ValueError):
        to_decimal(bad)


def test_mandate_roundtrip_and_cap():
    token = issue_mandate(SECRET, job_id="j1", max_amount=Decimal("5.00"), now=1000)
    assert verify_mandate(SECRET, token, job_id="j1", amount="5.00", now=1001)["max_amount"] == "5.00"
    with pytest.raises(MandateError, match="exceeds"):
        verify_mandate(SECRET, token, job_id="j1", amount="5.01", now=1001)


def test_mandate_rejects_tampering_expiry_and_wrong_job():
    token = issue_mandate(SECRET, job_id="j1", max_amount=Decimal("5.00"), ttl_seconds=60, now=1000)
    with pytest.raises(MandateError, match="expired"):
        verify_mandate(SECRET, token, job_id="j1", amount="1.00", now=2000)
    with pytest.raises(MandateError, match="different job"):
        verify_mandate(SECRET, token, job_id="j2", amount="1.00", now=1001)
    with pytest.raises(MandateError, match="signature"):
        verify_mandate("another-secret-of-sufficient-length", token, job_id="j1", amount="1.00", now=1001)
    body, signature = token.split(".")
    with pytest.raises(MandateError):
        verify_mandate(SECRET, f"{body}x.{signature}", job_id="j1", amount="1.00", now=1001)
    with pytest.raises(MandateError, match="Malformed"):
        verify_mandate(SECRET, "no-dot", job_id="j1", amount="1.00")


def test_settlement_ticket_binds_job_action_and_amount():
    ticket = issue_settlement_ticket(SECRET, job_id="j1", action="capture", amount=Decimal("3.95"), now=1000)
    assert verify_settlement_ticket(SECRET, ticket, job_id="j1", action="capture", amount="3.95", now=1001)
    with pytest.raises(MandateError, match="does not permit"):
        verify_settlement_ticket(SECRET, ticket, job_id="j1", action="payout", amount="3.95", now=1001)
    with pytest.raises(MandateError, match="amount"):
        verify_settlement_ticket(SECRET, ticket, job_id="j1", action="capture", amount="3.96", now=1001)
    with pytest.raises(MandateError, match="expired"):
        verify_settlement_ticket(SECRET, ticket, job_id="j1", action="capture", amount="3.95", now=9999)
    with pytest.raises(MandateError, match="Unknown settlement action"):
        issue_settlement_ticket(SECRET, job_id="j1", action="refund")
