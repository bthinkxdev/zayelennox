"""GST reverse-calculation for tax-inclusive product prices."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


def reverse_calculate_gst(*, inclusive_amount: Decimal, gst_rate_percent: Decimal) -> tuple[Decimal, Decimal]:
    """
    Split a GST-inclusive amount into (taxable_value, tax_amount).

    ``inclusive_amount`` already has GST baked in (e.g. a line total of
    unit_price * quantity) — this pulls it back out rather than adding tax
    on top. Call once per line total, not per-unit-then-multiplied, so
    rounding doesn't compound across quantity.
    """
    if gst_rate_percent == 0:
        return inclusive_amount, Decimal("0.00")

    divisor = 1 + (gst_rate_percent / Decimal("100"))
    taxable_value = (inclusive_amount / divisor).quantize(_CENT, rounding=ROUND_HALF_UP)
    tax_amount = (inclusive_amount - taxable_value).quantize(_CENT, rounding=ROUND_HALF_UP)
    return taxable_value, tax_amount


def split_by_supply_type(*, tax_amount: Decimal, is_interstate: bool) -> dict:
    """
    Split a total GST amount into CGST/SGST (intrastate) or IGST (interstate).

    Intrastate splits the amount exactly in half, keeping the remainder
    paisa (if the amount is odd) on SGST so cgst + sgst always equals
    tax_amount exactly.
    """
    if is_interstate:
        return {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": tax_amount}

    half = (tax_amount / 2).quantize(_CENT, rounding=ROUND_HALF_UP)
    remainder = tax_amount - half
    return {"cgst": half, "sgst": remainder, "igst": Decimal("0.00")}
