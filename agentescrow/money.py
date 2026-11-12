"""Money helpers.

All monetary values are handled as ``Decimal`` and sent to PayPal as 2-decimal
strings. Floats are never used for money because they cannot represent cents exactly.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def to_decimal(value: object) -> Decimal:
    """Convert ``value`` to a finite Decimal, or raise ``ValueError``."""
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError(f"Not a valid amount: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Amount must be finite: {value!r}")
    return result


def round_cents(value: object) -> Decimal:
    """Round to cents, half-up (the convention used on invoices)."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def floor_cents(value: object) -> Decimal:
    """Round down to cents. Used for pro-rated captures so we never over-charge."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_DOWN)


def money_str(value: object) -> str:
    """Format an amount the way PayPal expects it, e.g. ``'75.00'``."""
    return f"{round_cents(value):.2f}"
