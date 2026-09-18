"""Customer-facing views for the shipping app (checkout-time serviceability + rate check)."""

from __future__ import annotations

import logging
import re

from django.conf import settings as django_settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from cart.selectors import get_buy_now_cart_for_request, get_cart_for_request
from core.services import get_site_settings
from shipping.exceptions import ShiprocketAPIError
from shipping.parcel import calculate_parcel_from_cart
from shipping.shiprocket_client import get_shiprocket_config, shiprocket_client

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

    pickup_pincode = get_shiprocket_config()["pickup_pincode"]
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
        payload = {"ok": False, "error": "Could not verify delivery right now — you can still place your order."}
        if django_settings.DEBUG:

            payload["debug_error"] = str(exc)
        return JsonResponse(payload, status=200)

    is_serviceable = result.get("is_serviceable", False)
    recommended = result.get("recommended_courier") or {}
    available_couriers = result.get("available_couriers") or []

    site_settings = get_site_settings()
    use_shiprocket_charge = site_settings.use_shiprocket_delivery_charge
    flat_charge = float(site_settings.default_shipping_charge)

    selectable_couriers = available_couriers[:3] if use_shiprocket_charge else []
    selected_courier_id = None

    if is_serviceable:
        if use_shiprocket_charge:
            couriers_by_id = {
                str(c["courier_id"]): c for c in selectable_couriers if c.get("courier_id") is not None
            }
            recommended_id = recommended.get("courier_id")
            selected_courier_id = str(recommended_id) if recommended_id is not None else None
            request.session[SESSION_KEY] = {
                "pincode": pincode,
                "couriers": couriers_by_id,
                "selected_courier_id": selected_courier_id,
                "shipping_charge": recommended.get("freight_charge", 0),
                "cod_charge": recommended.get("cod_charges", 0),
                "courier_name": recommended.get("courier_name", ""),
                "estimated_delivery_days": recommended.get("estimated_delivery_days"),
            }
        else:
            # flat charge is applied unconditionally in place_order when
            # this setting is off, so no per-pincode override is stored.
            request.session.pop(SESSION_KEY, None)
    else:
        request.session.pop(SESSION_KEY, None)

    display_charge = recommended.get("freight_charge", 0) if use_shiprocket_charge else flat_charge

    return JsonResponse(
        {
            "ok": True,
            "is_serviceable": is_serviceable,
            "shipping_charge": display_charge,
            "cod_charge": recommended.get("cod_charges", 0) if use_shiprocket_charge else 0,
            "courier_name": recommended.get("courier_name") if use_shiprocket_charge else None,
            "estimated_delivery_days": recommended.get("estimated_delivery_days"),
            "selected_courier_id": selected_courier_id,
            "available_couriers": selectable_couriers,
        },
        status=200,
    )


@require_POST
def select_courier_view(request):
    """
    POST courier_id=<id>

    Lets the customer switch which courier they're charged for, among the
    options quoted for their pincode by check_serviceability_view. The
    charge applied is always looked up from that server-held quote in the
    session - a client-supplied courier_id can only pick from what
    Shiprocket already quoted us, never set its own price.
    """
    site_settings = get_site_settings()
    if not site_settings.use_shiprocket_delivery_charge:
        return JsonResponse(
            {"ok": False, "error": "Delivery options are not selectable right now."}, status=200
        )

    courier_id = (request.POST.get("courier_id") or "").strip()
    stored_quote = request.session.get(SESSION_KEY)
    if not stored_quote or not courier_id:
        return JsonResponse(
            {"ok": False, "error": "Please check your pincode again before choosing a courier."}, status=200
        )

    courier = (stored_quote.get("couriers") or {}).get(courier_id)
    if not courier:
        return JsonResponse(
            {"ok": False, "error": "That delivery option is no longer available. Please re-check your pincode."},
            status=200,
        )

    stored_quote["selected_courier_id"] = courier_id
    stored_quote["shipping_charge"] = courier.get("freight_charge", 0)
    stored_quote["cod_charge"] = courier.get("cod_charges", 0)
    stored_quote["courier_name"] = courier.get("courier_name", "")
    stored_quote["estimated_delivery_days"] = courier.get("estimated_delivery_days")
    request.session[SESSION_KEY] = stored_quote

    return JsonResponse(
        {
            "ok": True,
            "shipping_charge": stored_quote["shipping_charge"],
            "cod_charge": stored_quote["cod_charge"],
            "courier_name": stored_quote["courier_name"],
            "estimated_delivery_days": stored_quote["estimated_delivery_days"],
            "selected_courier_id": courier_id,
        },
        status=200,
    )
