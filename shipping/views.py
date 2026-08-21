"""Customer-facing views for the shipping app (checkout-time serviceability + rate check)."""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from cart.selectors import get_buy_now_cart_for_request, get_cart_for_request
from shipping.exceptions import ShiprocketAPIError
from shipping.parcel import calculate_parcel_from_cart
from shipping.shiprocket_client import shiprocket_client

logger = logging.getLogger(__name__)

_PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")

# Session key holding the last verified Shiprocket quote, consumed by
# checkout.services.place_order so the charge the customer saw is the
# charge they're actually billed (never trust the client for this).
SESSION_KEY = "shiprocket_shipping"


@require_GET
def check_serviceability_view(request):
    """
    GET ?pincode=XXXXXX[&buy_now=1]

    Quotes real Shiprocket courier rates for the customer's actual cart
    contents and destination pincode. On a serviceable result, stashes the
    recommended courier's charge in the session (keyed to this pincode) so
    place_order can apply the same real charge to the order.
    """
    pincode = (request.GET.get("pincode") or "").strip()
    if not _PINCODE_RE.match(pincode):
        return JsonResponse({"ok": False, "error": "Enter a valid 6-digit pincode."}, status=200)

    pickup_pincode = getattr(settings, "SHIPROCKET_PICKUP_PINCODE", "")
    if not pickup_pincode:
        logger.warning("SHIPROCKET_PICKUP_PINCODE is not configured; skipping serviceability check.")
        return JsonResponse(
            {"ok": False, "error": "Delivery check is not configured yet."}, status=200
        )

    buy_now_mode = request.GET.get("buy_now") == "1"
    cart = (
        get_buy_now_cart_for_request(request=request)
        if buy_now_mode
        else get_cart_for_request(request=request)
    )
    if cart is None or not cart.items.exists():
        return JsonResponse({"ok": False, "error": "Your cart is empty."}, status=200)

    parcel = calculate_parcel_from_cart(cart)

    try:
        result = shiprocket_client.get_shipping_rates(
            pickup_pincode=pickup_pincode,
            delivery_pincode=pincode,
            weight=float(parcel["weight"]),
            length=float(parcel["length"]),
            breadth=float(parcel["breadth"]),
            height=float(parcel["height"]),
            is_cod=False,
        )
    except ShiprocketAPIError as exc:
        logger.error("Serviceability check failed for pincode %s: %s", pincode, exc)
        request.session.pop(SESSION_KEY, None)
        return JsonResponse(
            {"ok": False, "error": "Could not verify delivery right now — you can still place your order."},
            status=200,
        )

    is_serviceable = result.get("is_serviceable", False)
    recommended = result.get("recommended_courier") or {}
    available_couriers = result.get("available_couriers") or []

    if is_serviceable:
        request.session[SESSION_KEY] = {
            "pincode": pincode,
            "shipping_charge": recommended.get("freight_charge", 0),
            "cod_charge": recommended.get("cod_charges", 0),
            "courier_name": recommended.get("courier_name", ""),
            "estimated_delivery_days": recommended.get("estimated_delivery_days"),
        }
    else:
        request.session.pop(SESSION_KEY, None)

    return JsonResponse(
        {
            "ok": True,
            "is_serviceable": is_serviceable,
            "shipping_charge": recommended.get("freight_charge", 0),
            "cod_charge": recommended.get("cod_charges", 0),
            "courier_name": recommended.get("courier_name"),
            "estimated_delivery_days": recommended.get("estimated_delivery_days"),
            "available_couriers": available_couriers[:3],
        },
        status=200,
    )
