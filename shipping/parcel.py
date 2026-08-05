"""Parcel dimension/weight calculation for courier booking."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

MIN_DIM = Decimal("0.5")
MIN_WEIGHT = Decimal("0.1")


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _calculate_parcel_from_lines(lines: Iterable) -> dict:
    """
    Shared aggregation logic: each line must expose ``get_shipping_dims()``
    and ``quantity``. Works identically for ``OrderItem`` and ``CartItem``.

    All dimensions are in cm and weight in kg.
    """
    total_weight = Decimal("0")
    lengths: list[Decimal] = []
    breadths: list[Decimal] = []
    heights: list[Decimal] = []

    for line in lines:
        dims = line.get_shipping_dims()
        qty = Decimal(line.quantity or 0)

        weight = _to_decimal(dims.get("weight"))
        length = _to_decimal(dims.get("length"))
        breadth = _to_decimal(dims.get("breadth"))
        height = _to_decimal(dims.get("height"))

        total_weight += weight * qty
        if length > 0:
            lengths.append(length)
        if breadth > 0:
            breadths.append(breadth)
        if height > 0:
            heights.append(height * qty)

    length = max(lengths) if lengths else Decimal("0")
    breadth = max(breadths) if breadths else Decimal("0")
    height = sum(heights) if heights else Decimal("0")

    volumetric_weight = Decimal("0")
    if length > 0 and breadth > 0 and height > 0:
        volumetric_weight = (length * breadth * height) / Decimal("5000")

    final_weight = max(total_weight, volumetric_weight)

    return {
        "length": round(max(length, MIN_DIM), 2),
        "breadth": round(max(breadth, MIN_DIM), 2),
        "height": round(max(height, MIN_DIM), 2),
        "weight": round(max(final_weight, MIN_WEIGHT), 2),
    }


def calculate_parcel(order) -> dict:
    """
    Calculate balanced parcel dimensions and weight for a placed Order.

    Each order line resolves its own dims via ``OrderItem.get_shipping_dims()``
    (variant override if set, else the product's default) — this is what
    makes the calculation work whether a line has a variant or not.
    """
    items = order.items.select_related("product", "variant").all()
    return _calculate_parcel_from_lines(items)


def calculate_parcel_from_cart(cart) -> dict:
    """
    Same calculation as ``calculate_parcel``, but for an in-progress Cart —
    used to quote real Shiprocket shipping rates at checkout, before an
    order exists.
    """
    items = cart.items.select_related("product", "variant").all()
    return _calculate_parcel_from_lines(items)
