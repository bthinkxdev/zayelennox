"""Checkout-time courier quotes: fetch, rank, remember the customer's pick, price the order."""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Optional

from django.core.cache import cache

from core.services import get_site_settings
from shipping.exceptions import ShiprocketAPIError
from shipping.parcel import calculate_parcel_from_cart
from shipping.shiprocket_client import get_shiprocket_config, shiprocket_client

logger = logging.getLogger(__name__)

# Session key holding the customer's verified courier options + choice. The
# order's shipping charge is always looked up from this server-held quote —
# a client-supplied courier_id can only pick among what Shiprocket quoted.
SESSION_KEY = "shiprocket_shipping"

QUOTE_CACHE_TTL = 15 * 60
# Interactive checkout must fail fast instead of hanging on Shiprocket retries.
_LIVE_MAX_RETRIES = 2
_LIVE_TIMEOUT = 8
_NO_ETA = 10**6


def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception:
        logger.warning("Rate cache read failed", exc_info=True)
        return None


def _cache_set(key: str, value) -> None:
    try:
        cache.set(key, value, timeout=QUOTE_CACHE_TTL)
    except Exception:
        logger.warning("Rate cache write failed", exc_info=True)


def _rank(couriers: list[dict], recommended_id) -> list[dict]:
    """Sort cheapest-first and tag the cheapest / fastest / Shiprocket-recommended options."""
    if not couriers:
        return []

    def eta(c):
        return c["eta_hours"] if c["eta_hours"] is not None else _NO_ETA

    cheapest = min(couriers, key=lambda c: (c["freight_charge"], eta(c)))
    fastest = min(couriers, key=lambda c: (eta(c), c["freight_charge"]))
    for c in couriers:
        c["tags"] = [
            tag
            for tag, hit in (
                ("cheapest", c is cheapest),
                ("fastest", c is fastest),
                ("recommended", recommended_id is not None and c["courier_id"] == recommended_id),
            )
            if hit
        ]
    return sorted(couriers, key=lambda c: (c["freight_charge"], eta(c)))


def fetch_courier_options(*, cart, pincode: str) -> list[dict]:
    """
    Ranked courier options (cheapest first) for the cart's parcel to ``pincode``;
    empty when the pincode isn't serviceable. Quotes are cached briefly per
    parcel+route so repeat checks are instant and ride out short Shiprocket blips.

    Raises:
        ShiprocketAPIError: Shiprocket is unconfigured or unreachable.
    """
    pickup_pincode = get_shiprocket_config()["pickup_pincode"]
    if not pickup_pincode:
        raise ShiprocketAPIError("SHIPROCKET_PICKUP_PINCODE is not configured.")

    parcel = calculate_parcel_from_cart(cart)
    raw_key = "|".join(
        str(x) for x in (pickup_pincode, pincode, parcel["weight"], parcel["length"], parcel["breadth"], parcel["height"])
    )
    cache_key = "sr_quote:" + hashlib.md5(raw_key.encode()).hexdigest()

    couriers = _cache_get(cache_key)
    if couriers is None:
        result = shiprocket_client.get_shipping_rates(
            pickup_pincode=pickup_pincode,
            delivery_pincode=pincode,
            weight=float(parcel["weight"]),
            length=float(parcel["length"]),
            breadth=float(parcel["breadth"]),
            height=float(parcel["height"]),
            is_cod=False,
            max_retries=_LIVE_MAX_RETRIES,
            timeout=_LIVE_TIMEOUT,
        )
        couriers = _rank(result["available_couriers"], result["recommended_courier_id"])
        _cache_set(cache_key, couriers)
    return couriers


def estimate_courier(couriers: list[dict]) -> dict:
    """
    The courier whose delivery estimate to quote when the customer isn't choosing one
    (free delivery): Shiprocket's own recommendation, else the fastest, else the first.
    """
    for tag in ("recommended", "fastest"):
        for courier in couriers:
            if tag in courier["tags"]:
                return courier
    return couriers[0]


def store_quote(request, *, pincode: str, couriers: list[dict], selected_id) -> None:
    request.session[SESSION_KEY] = {
        "pincode": pincode,
        "couriers": {str(c["courier_id"]): c for c in couriers},
        "selected_courier_id": str(selected_id),
    }


def clear_quote(request) -> None:
    request.session.pop(SESSION_KEY, None)


def get_selected_courier(request, pincode: str) -> Optional[dict]:
    """The courier the customer is currently charged for, if a quote for this pincode is held."""
    quote = request.session.get(SESSION_KEY)
    if not quote or quote.get("pincode") != pincode:
        return None
    return (quote.get("couriers") or {}).get(quote.get("selected_courier_id"))


def select_courier(request, courier_id: str) -> Optional[dict]:
    """Switch the held quote's choice; None if it isn't one of the quoted couriers."""
    quote = request.session.get(SESSION_KEY)
    courier = (quote or {}).get("couriers", {}).get(courier_id)
    if courier is None:
        return None
    quote["selected_courier_id"] = courier_id
    request.session[SESSION_KEY] = quote
    return courier


def resolve_order_shipping_charge(request, *, cart, pincode: Optional[str]) -> Decimal:
    """
    Shipping charge to bill on the order — decided server-side, never ₹0 by accident
    (₹0 only when the vendor has turned delivery charges off).

    Uses the courier the customer picked. If no quote for this pincode is held
    (the browser never ran the check, or it failed), quotes it now and takes the
    cheapest; if Shiprocket is still unavailable, falls back to the flat charge.
    """
    site_settings = get_site_settings()
    if not site_settings.charge_for_delivery:
        return Decimal("0.00")
    if not site_settings.use_shiprocket_delivery_charge:
        return site_settings.default_shipping_charge

    if pincode:
        courier = get_selected_courier(request, pincode)
        if courier is None:
            try:
                couriers = fetch_courier_options(cart=cart, pincode=pincode)
            except ShiprocketAPIError as exc:
                logger.error("Order-time courier quote failed for %s: %s", pincode, exc)
                couriers = []
            if couriers:
                courier = couriers[0]
                store_quote(request, pincode=pincode, couriers=couriers, selected_id=courier["courier_id"])
        if courier is not None:
            return Decimal(str(courier["freight_charge"]))

    logger.warning("No courier quote for pincode %r; billing the flat shipping charge.", pincode)
    return site_settings.default_shipping_charge
