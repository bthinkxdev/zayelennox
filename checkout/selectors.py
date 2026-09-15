"""Read-only query functions for the checkout app."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from cart.selectors import CartSummary
from catalog.tax import reverse_calculate_gst, split_by_supply_type
from checkout.models import CheckoutSession, CheckoutSessionStatus
from core.services import get_site_settings


def get_checkout_session_by_id(*, session_id: int) -> Optional[CheckoutSession]:
    """
    Return a checkout session with related cart and address.

    Query guarantee: 1 SELECT with select_related(cart, address, delivery_slot).
    """
    return (
        CheckoutSession.objects.filter(pk=session_id)
        .select_related(
            "cart",
            "cart__currency",
            "cart__destination_city",
            "address",
            "address__city",
            "delivery_slot",
            "customer_profile",
            "order",
        )
        .first()
    )


def get_draft_checkout_for_cart(*, cart_id: int) -> Optional[CheckoutSession]:
    """
    Return the active draft checkout session for a cart.

    Query guarantee: 1 SELECT filtered by cart_id + status=draft.
    """
    return (
        CheckoutSession.objects.filter(
            cart_id=cart_id,
            status=CheckoutSessionStatus.DRAFT,
        )
        .select_related("cart", "address", "delivery_slot")
        .first()
    )


def resolve_is_interstate(*, buyer_state: str) -> bool:
    """
    Whether a delivery to ``buyer_state`` counts as an interstate GST supply.

    Compares (case-insensitively, trimmed) against the seller's own
    registered_state. An unknown/blank buyer state defaults to intrastate
    (CGST+SGST) as the safer minimal fallback for the rare no-address case.
    """
    registered_state = get_site_settings().registered_state
    if not registered_state or not buyer_state:
        return False
    return registered_state.strip().lower() != buyer_state.strip().lower()


@dataclass
class CartGstLine:
    """Per-line GST breakdown, in the same order as CartSummary.lines."""

    hsn_code: str
    gst_rate_percent: Decimal
    taxable_value: Decimal
    tax_amount: Decimal


@dataclass
class CartGstBreakdown:
    """
    GST breakdown for a whole cart/order, reused by both the checkout-page
    display and place_order (single source of truth for the tax math, so
    what the customer sees pre-payment matches what gets stored).
    """

    is_interstate: bool
    lines: list[CartGstLine] = field(default_factory=list)
    total_taxable_value: Decimal = Decimal("0.00")
    total_tax_amount: Decimal = Decimal("0.00")

    @property
    def split(self) -> dict:
        return split_by_supply_type(tax_amount=self.total_tax_amount, is_interstate=self.is_interstate)


def get_cart_gst_breakdown(*, summary: CartSummary, buyer_state: str) -> CartGstBreakdown:
    """Reverse-calculate GST out of each cart line's (already tax-inclusive) subtotal."""
    is_interstate = resolve_is_interstate(buyer_state=buyer_state)

    lines: list[CartGstLine] = []
    total_taxable_value = Decimal("0.00")
    total_tax_amount = Decimal("0.00")

    for line in summary.lines:
        taxable_value, tax_amount = reverse_calculate_gst(
            inclusive_amount=line.line_subtotal,
            gst_rate_percent=line.effective_gst_rate_percent,
        )
        lines.append(
            CartGstLine(
                hsn_code=line.effective_hsn_code,
                gst_rate_percent=line.effective_gst_rate_percent,
                taxable_value=taxable_value,
                tax_amount=tax_amount,
            )
        )
        total_taxable_value += taxable_value
        total_tax_amount += tax_amount

    return CartGstBreakdown(
        is_interstate=is_interstate,
        lines=lines,
        total_taxable_value=total_taxable_value,
        total_tax_amount=total_tax_amount,
    )
