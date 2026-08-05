"""Write operations and orchestration for the shipping app."""

from __future__ import annotations

import logging
from typing import Optional

from django.utils import timezone

from shipping.exceptions import ShiprocketAPIError
from shipping.models import Shipment
from shipping.shiprocket_client import shiprocket_client

logger = logging.getLogger(__name__)


def create_shipment_for_order(order, shipment: Optional[Shipment] = None) -> Shipment:
    """
    Orchestrate full shipment creation for an order:
      - create Shiprocket order
      - assign AWB
      - request pickup
      - generate label
      - update Shipment status throughout

    Raises ShiprocketAPIError on failure; the Shipment row is left in
    "error" status with error_log populated so it's visible in admin.
    """
    if shipment is None:
        shipment, _ = Shipment.objects.get_or_create(
            order=order, defaults={"current_status": Shipment.Status.PENDING_CREATION}
        )

    try:
        create_data = shiprocket_client.create_order(order, shipment)
        shipment.shiprocket_order_id = str(create_data.get("order_id") or "")
        shipment.shiprocket_shipment_id = str(create_data.get("shipment_id") or "")
        shipment.current_status = Shipment.Status.CREATED
        shipment.error_log = ""
        shipment.save(
            update_fields=[
                "shiprocket_order_id",
                "shiprocket_shipment_id",
                "current_status",
                "error_log",
                "updated_at",
            ]
        )

        awb_data = shiprocket_client.assign_awb(shipment)
        awb_response = awb_data.get("response", {}) or awb_data
        awb_inner = awb_response.get("data", {}) or awb_response
        shipment.awb_code = str(awb_inner.get("awb_code") or awb_inner.get("awb") or "")
        shipment.courier_name = str(awb_inner.get("courier_name") or "")
        shipment.current_status = Shipment.Status.AWB_ASSIGNED
        shipment.save(update_fields=["awb_code", "courier_name", "current_status", "updated_at"])

        shiprocket_client.request_pickup(shipment)
        shipment.current_status = Shipment.Status.PICKUP_SCHEDULED
        shipment.save(update_fields=["current_status", "updated_at"])

        label_data = shiprocket_client.generate_label(shipment)
        label_url = label_data.get("label_url") or (
            label_data.get("response", {}).get("data", {}).get("label_url", "")
        )
        shipment.label_url = label_url
        shipment.current_status = Shipment.Status.LABEL_GENERATED
        shipment.save(update_fields=["label_url", "current_status", "updated_at"])

        return shipment
    except ShiprocketAPIError as exc:
        shipment.error_log = str(exc)
        shipment.current_status = Shipment.Status.ERROR
        shipment.save(update_fields=["error_log", "current_status", "updated_at"])
        logger.error("Shiprocket shipment creation failed for order %s: %s", order.order_number, exc, exc_info=True)
        raise
    except Exception as exc:
        shipment.error_log = str(exc)
        shipment.current_status = Shipment.Status.ERROR
        shipment.save(update_fields=["error_log", "current_status", "updated_at"])
        logger.error(
            "Unexpected error while creating shipment for order %s: %s", order.order_number, exc, exc_info=True
        )
        raise ShiprocketAPIError(str(exc)) from exc


def cancel_shipment(shipment: Shipment) -> Shipment:
    """Cancel a shipment in Shiprocket and mark it cancelled locally."""
    shiprocket_client.cancel_shipment(shipment)
    shipment.is_cancelled = True
    shipment.cancelled_at = timezone.now()
    shipment.current_status = Shipment.Status.CANCELLED
    shipment.save(update_fields=["is_cancelled", "cancelled_at", "current_status", "updated_at"])
    return shipment


def refresh_tracking(shipment: Shipment) -> Shipment:
    """Fetch latest tracking info from Shiprocket by AWB and store it on the shipment."""
    if not shipment.awb_code:
        raise ShiprocketAPIError("Shipment has no AWB code to track.")
    data = shiprocket_client.track_shipment(shipment.awb_code)
    shipment.tracking_data = data
    shipment.save(update_fields=["tracking_data", "updated_at"])
    return shipment
