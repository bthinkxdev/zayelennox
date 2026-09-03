"""Storefront template helpers for currency display."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django import template

register = template.Library()


def _format_money_amount(value: Decimal) -> str:
    """Format money without trailing .00; keep decimals only when needed."""
    quantized = value.quantize(Decimal("0.01"), ROUND_HALF_UP)
    if quantized == quantized.to_integral_value():
        return f"{int(quantized)}"
    text = f"{quantized:.2f}".rstrip("0").rstrip(".")
    return text


@register.filter
def in_display_currency(amount, currency) -> str:
    """Convert a base-currency amount into the active display currency."""
    if amount is None or amount == "":
        return ""
    if currency is None:
        try:
            return _format_money_amount(Decimal(str(amount)))
        except Exception:
            return str(amount)
    base = Decimal(str(amount))
    rate = Decimal(str(currency.exchange_rate_to_base))
    if rate <= 0:
        return _format_money_amount(base)
    converted = (base / rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return _format_money_amount(converted)


@register.simple_tag
def money_label(amount, currency) -> str:
    """Format amount with currency symbol for templates."""
    symbol = getattr(currency, "symbol", "")
    value = in_display_currency(amount, currency)
    return f"{symbol} {value}".strip()


@register.filter
def decimal_add(value, arg) -> Decimal:
    """
    Safely add two money amounts as Decimal.

    """
    try:
        base = Decimal(str(value)) if value not in (None, "") else Decimal("0")
    except Exception:
        base = Decimal("0")
    try:
        delta = Decimal(str(arg)) if arg not in (None, "") else Decimal("0")
    except Exception:
        delta = Decimal("0")
    return base + delta


def _cheapest_variant(variants):
    """Cheapest in-stock variant, falling back to the cheapest overall if none are in stock."""
    in_stock = [v for v in variants if v.stock_quantity > 0]
    pool = in_stock or variants
    return min(pool, key=lambda v: v.price_delta)


@register.filter
def card_display_price(product) -> Decimal:
    """
    Price to show on a product card (jm-product-card__pricing).

    Products without variants keep showing `product.display_price` as
    before. Once a product has variants (`product.variant_list`, prefetched
    by catalog.selectors._variant_list_prefetch), the card instead shows the
    price of the cheapest in-stock variant - same starting-price logic PDP
    now defaults to - with any active flash-sale discount percentage applied
    the same way it's applied to the base price.
    """
    variants = getattr(product, "variant_list", None)
    if not variants:
        return getattr(product, "display_price", None) or product.base_price

    base = product.base_price + _cheapest_variant(variants).price_delta
    pct = getattr(product, "flash_discount_percentage", None)
    if pct:
        discount = (base * pct / Decimal("100")).quantize(Decimal("0.01"))
        return base - discount
    return base


@register.filter
def card_original_price(product) -> Decimal:
    """Struck-through 'was' price paired with card_display_price when a flash sale is active."""
    variants = getattr(product, "variant_list", None)
    if not variants:
        return getattr(product, "original_price", None) or product.base_price
    return product.base_price + _cheapest_variant(variants).price_delta


@register.filter
def card_mrp(product):
    """MRP to pair with card_display_price on a product card, or None if unset."""
    variants = getattr(product, "variant_list", None)
    if not variants:
        return getattr(product, "mrp", None)
    return _cheapest_variant(variants).effective_mrp


@register.filter
def discount_percent(mrp, price) -> int:
    """Return the whole-number discount percent off mrp, or 0 if not discounted."""
    try:
        mrp_d = Decimal(str(mrp))
        price_d = Decimal(str(price))
    except Exception:
        return 0
    if mrp_d <= 0 or price_d >= mrp_d:
        return 0
    pct = ((mrp_d - price_d) / mrp_d * Decimal("100")).quantize(Decimal("1"), ROUND_HALF_UP)
    return int(pct)
