"""Customer-facing views for the shipping app (checkout-time serviceability + courier choice)."""

from __future__ import annotations

import logging
import re

from django.conf import settings as django_settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from cart.selectors import get_buy_now_cart_for_request, get_cart_for_request
from core.services import get_site_settings
from shipping.exceptions import ShiprocketAPIError
from shipping.rates import (
    SESSION_KEY,
    clear_quote,
    estimate_courier,
    fetch_courier_options,
    get_selected_courier,
    select_courier,
    store_quote,
)

logger = logging.getLogger(__name__)

_PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")


def _courier_payload(courier: dict) -> dict:
    return {
        "shipping_charge": courier["freight_charge"],
        "courier_name": courier["courier_name"],
        "estimated_delivery_days": courier["estimated_delivery_days"],
        "etd": courier["etd"],
        "selected_courier_id": str(courier["courier_id"]),
    }


@require_GET
def check_serviceability_view(request):
    """
    GET ?pincode=XXXXXX[&buy_now=1]

    Quotes real Shiprocket courier options for the customer's actual cart and
    destination pincode, cheapest first (or, with free delivery, just confirms the
    pincode and the delivery estimate), and holds the quote in the session so
    the customer can choose by price/delivery time and place_order bills the
    exact charge they saw. Keeps the customer's earlier choice when they
    re-check the same pincode.
    """
    pincode = (request.GET.get("pincode") or "").strip()
    if not _PINCODE_RE.match(pincode):
        return JsonResponse({"ok": False, "error": "Enter a valid 6-digit pincode."}, status=200)

    cart = (
        get_buy_now_cart_for_request(request=request)
        if request.GET.get("buy_now") == "1"
        else get_cart_for_request(request=request)
    )
    if cart is None or not cart.items.exists():
        return JsonResponse({"ok": False, "error": "Your cart is empty."}, status=200)

    try:
        couriers = fetch_courier_options(cart=cart, pincode=pincode)
    except ShiprocketAPIError as exc:
        logger.error("Serviceability check failed for pincode %s: %s", pincode, exc)
        clear_quote(request)
        payload = {
            "ok": False,
            "retryable": True,
            "error": "Could not fetch delivery options right now. Please try again.",
        }
        if django_settings.DEBUG:
            payload["debug_error"] = str(exc)
        return JsonResponse(payload, status=200)

    if not couriers:
        clear_quote(request)
        return JsonResponse({"ok": True, "is_serviceable": False})

    site_settings = get_site_settings()
    if not site_settings.charge_for_delivery:
        # Free delivery: Shiprocket still confirmed the pincode and gave a delivery estimate,
        # but no price or courier choice is offered — nothing here can reach the customer's total.
        clear_quote(request)
        estimate = estimate_courier(couriers)
        return JsonResponse(
            {
                "ok": True,
                "is_serviceable": True,
                "free_delivery": True,
                "shipping_charge": 0,
                "estimated_delivery_days": estimate["estimated_delivery_days"],
                "etd": estimate["etd"],
                "available_couriers": [],
            }
        )

    if not site_settings.use_shiprocket_delivery_charge:
        # The flat charge is applied in place_order; no courier choice to offer.
        clear_quote(request)
        return JsonResponse(
            {
                "ok": True,
                "is_serviceable": True,
                "shipping_charge": float(site_settings.default_shipping_charge),
                "estimated_delivery_days": couriers[0]["estimated_delivery_days"],
                "etd": couriers[0]["etd"],
                "available_couriers": [],
            }
        )

    previous = get_selected_courier(request, pincode)
    selected = next(
        (c for c in couriers if previous and c["courier_id"] == previous["courier_id"]), couriers[0]
    )
    store_quote(request, pincode=pincode, couriers=couriers, selected_id=selected["courier_id"])

    return JsonResponse(
        {"ok": True, "is_serviceable": True, "available_couriers": couriers, **_courier_payload(selected)}
    )


@require_POST
def select_courier_view(request):
    """
    POST courier_id=<id>

    Lets the customer switch courier among the options quoted for their
    pincode. The charge is always taken from that server-held quote.
    """
    site_settings = get_site_settings()
    if not site_settings.charge_for_delivery or not site_settings.use_shiprocket_delivery_charge:
        return JsonResponse(
            {"ok": False, "error": "Delivery options are not selectable right now."}, status=200
        )

    courier_id = (request.POST.get("courier_id") or "").strip()
    if not courier_id or not request.session.get(SESSION_KEY):
        return JsonResponse(
            {"ok": False, "error": "Please check your pincode again before choosing a courier."}, status=200
        )

    courier = select_courier(request, courier_id)
    if courier is None:
        return JsonResponse(
            {"ok": False, "error": "That delivery option is no longer available. Please re-check your pincode."},
            status=200,
        )

    return JsonResponse({"ok": True, **_courier_payload(courier)}, status=200)
