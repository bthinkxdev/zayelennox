"""
Cross-app signal handlers for the shipping app.

Listens to ``orders.signals.order_status_changed`` and automatically kicks
off Shiprocket shipment creation once an order is packed and ready to hand
to a courier.

Trigger point: ``OrderStatus.READY``. Change ``SHIPMENT_TRIGGER_STATUS``
below if your fulfillment flow should hand off to Shiprocket at a
different stage.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.dispatch import receiver

from orders.models import OrderStatus
from orders.signals import order_status_changed

logger = logging.getLogger(__name__)

SHIPMENT_TRIGGER_STATUS = OrderStatus.READY


@receiver(order_status_changed)
def auto_create_shipment_on_ready(sender, order, old_status, new_status, send_notifications=True, **kwargs):
    """When an order becomes READY, enqueue Shiprocket shipment creation if one doesn't exist."""
    if new_status != SHIPMENT_TRIGGER_STATUS:
        return

    if hasattr(order, "shipment"):
        # Shipment already exists (or a previous attempt errored) — leave it
        # to the admin "recreate shipment" action rather than silently retrying.
        return

    from shipping.tasks import create_shipment_for_order_task

    def _dispatch_shipment_task() -> None:
        try:
            create_shipment_for_order_task.delay(order_id=order.pk)
            logger.info("Queued Shiprocket shipment creation for order %s", order.order_number)
        except Exception:
            logger.exception(
                "Shiprocket shipment dispatch failed for order %s", order.order_number
            )

    transaction.on_commit(_dispatch_shipment_task)


@receiver(order_status_changed)
def auto_cancel_shipment_on_cancelled(sender, order, old_status, new_status, send_notifications=True, **kwargs):
    """When an order is cancelled, cancel its Shiprocket shipment too, if any.

    Keeps Shiprocket in sync with the dashboard: without this, cancelling
    an order here left the shipment live on Shiprocket's side with no
    automatic follow-up.
    """
    if new_status != OrderStatus.CANCELLED:
        return

    shipment = getattr(order, "shipment", None)
    if shipment is None or shipment.is_cancelled:
        # Nothing was ever booked, or it's already cancelled -- nothing to do.
        return

    from shipping.tasks import cancel_shipment_task

    def _dispatch_cancel_task() -> None:
        try:
            cancel_shipment_task.delay(order_id=order.pk)
            logger.info("Queued Shiprocket shipment cancellation for order %s", order.order_number)
        except Exception:
            logger.exception(
                "Shiprocket shipment cancel dispatch failed for order %s", order.order_number
            )

    transaction.on_commit(_dispatch_cancel_task)
