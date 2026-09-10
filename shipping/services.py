"""Write operations and orchestration for the shipping app."""

from __future__ import annotations

import logging
from typing import Optional

from django.utils import timezone

from shipping.exceptions import ShiprocketAPIError
from shipping.models import Shipment
from shipping.shiprocket_client import shiprocket_client

logger = logging.getLogger(__name__)


def _is_failed_status(value) -> bool:
    """True when a Shiprocket boolean-ish status flag (0/1) signals failure."""
    return value is not None and value in (0, "0", False)


def _extract_message(data: dict) -> str:

    not_created = data.get("not_created")
    if isinstance(not_created, dict) and not_created:
        return "; ".join(str(v) for v in not_created.values())

    response = data.get("response")
    if isinstance(response, dict):
        reason = response.get("data") or response.get("message")
        if isinstance(reason, dict):
            reason = reason.get("message") or str(reason)
        if reason:
            return str(reason)
    elif response:
        return str(response)

    return "Shiprocket did not return a specific reason."


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
        awb_inner = awb_response.get("data", {}) if isinstance(awb_response, dict) else {}
        if not isinstance(awb_inner, dict):
            awb_inner = {}
        awb_code = str(awb_inner.get("awb_code") or awb_inner.get("awb") or "")
        if _is_failed_status(awb_data.get("awb_assign_status")) or not awb_code:
            reason = awb_inner.get("awb_assign_error") or "Shiprocket could not assign an AWB for this shipment."
            raise ShiprocketAPIError(f"AWB assignment failed: {reason}")
        shipment.awb_code = awb_code
        shipment.courier_name = str(awb_inner.get("courier_name") or "")
        shipment.current_status = Shipment.Status.AWB_ASSIGNED
        shipment.save(update_fields=["awb_code", "courier_name", "current_status", "updated_at"])

        pickup_data = shiprocket_client.request_pickup(shipment)
        if _is_failed_status(pickup_data.get("pickup_status")):
            raise ShiprocketAPIError(f"Pickup request failed: {_extract_message(pickup_data)}")
        shipment.current_status = Shipment.Status.PICKUP_SCHEDULED
        shipment.save(update_fields=["current_status", "updated_at"])

        label_data = shiprocket_client.generate_label(shipment)
        if _is_failed_status(label_data.get("label_created")):
            raise ShiprocketAPIError(f"Label generation failed: {_extract_message(label_data)}")
        label_response = label_data.get("response")
        label_url = label_data.get("label_url") or (
            label_response.get("data", {}).get("label_url", "") if isinstance(label_response, dict) else ""
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
        
        shipment.error_log = (
            "Something went wrong while booking this shipment with Shiprocket. "
            "Please try 'Recreate shipment' from admin, or contact support if it keeps failing."
        )
        shipment.current_status = Shipment.Status.ERROR
        shipment.save(update_fields=["error_log", "current_status", "updated_at"])
        logger.error(
            "Unexpected error while creating shipment for order %s: %s", order.order_number, exc, exc_info=True
        )
        raise ShiprocketAPIError(str(exc)) from exc


def cancel_shipment(shipment: Shipment) -> Shipment:

    try:
        shiprocket_client.cancel_shipment(shipment)
    except ShiprocketAPIError as exc:
        shipment.error_log = (
            f"This order was cancelled, but cancelling the shipment in Shiprocket failed: {exc} "
            "Please cancel it manually in the Shiprocket panel."
        )
        shipment.save(update_fields=["error_log", "updated_at"])
        raise

    shipment.is_cancelled = True
    shipment.cancelled_at = timezone.now()
    shipment.current_status = Shipment.Status.CANCELLED
    shipment.error_log = ""
    shipment.save(update_fields=["is_cancelled", "cancelled_at", "current_status", "error_log", "updated_at"])
    return shipment


def refresh_tracking(shipment: Shipment) -> Shipment:
    """Fetch latest tracking info from Shiprocket by AWB and store it on the shipment."""
    if not shipment.awb_code:
        raise ShiprocketAPIError("Shipment has no AWB code to track.")
    data = shiprocket_client.track_shipment(shipment.awb_code)
    shipment.tracking_data = data
    shipment.save(update_fields=["tracking_data", "updated_at"])
    return shipment
