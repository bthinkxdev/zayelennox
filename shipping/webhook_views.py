"""Inbound webhook handling for Shiprocket status updates."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from shipping.models import Shipment

logger = logging.getLogger(__name__)

# Maps Shiprocket's free-text "current_status" webhook field to our enum.
_STATUS_MAP = {
    "delivered": Shipment.Status.DELIVERED,
    "cancelled": Shipment.Status.CANCELLED,
    "canceled": Shipment.Status.CANCELLED,
    "in transit": Shipment.Status.IN_TRANSIT,
    "out for delivery": Shipment.Status.IN_TRANSIT,
    "shipped": Shipment.Status.IN_TRANSIT,
    "pickup generated": Shipment.Status.PICKUP_SCHEDULED,
}


@method_decorator(csrf_exempt, name="dispatch")
class ShiprocketWebhookView(View):
    """
    Handle Shiprocket status webhooks.

    Configure this URL in the Shiprocket dashboard and set
    ``SHIPROCKET_WEBHOOK_TOKEN`` to the same secret Shiprocket sends back,
    either as an ``X-Api-Key`` header or a ``token`` query param.
    """

    def post(self, request, *args, **kwargs):
        expected_token = getattr(settings, "SHIPROCKET_WEBHOOK_TOKEN", "")
        if expected_token:
            token = request.headers.get("X-Api-Key") or request.GET.get("token")
            if token != expected_token:
                logger.warning("Shiprocket webhook: invalid token.")
                return HttpResponse(status=401)

        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            logger.warning("Shiprocket webhook: invalid JSON payload.")
            return HttpResponse(status=400)

        awb_code = str(payload.get("awb") or payload.get("awb_code") or "")
        if not awb_code:
            logger.warning("Shiprocket webhook: payload missing AWB. %s", payload)
            return JsonResponse({"detail": "missing awb"}, status=200)

        shipment = Shipment.objects.filter(awb_code=awb_code).first()
        if shipment is None:
            logger.warning("Shiprocket webhook: shipment not found for AWB %s", awb_code)
            return JsonResponse({"detail": "shipment not found"}, status=200)

        raw_status = str(payload.get("current_status") or payload.get("status") or "").strip().lower()
        mapped_status = _STATUS_MAP.get(raw_status)

        shipment.tracking_data = {**(shipment.tracking_data or {}), "last_webhook": payload}
        update_fields = ["tracking_data", "updated_at"]
        if mapped_status:
            shipment.current_status = mapped_status
            update_fields.append("current_status")
        shipment.save(update_fields=update_fields)

        logger.info("Shiprocket webhook processed for AWB %s -> %s", awb_code, raw_status)
        return JsonResponse({"detail": "ok"}, status=200)
