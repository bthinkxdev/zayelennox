"""Celery tasks for the shipping app."""

from __future__ import annotations

import logging

from celery import shared_task

from shipping.exceptions import ShiprocketAPIError

logger = logging.getLogger(__name__)


@shared_task(
    name="shipping.tasks.create_shipment_for_order_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def create_shipment_for_order_task(self, *, order_id: int) -> None:
    """Create a Shiprocket shipment for an order, run out-of-band via Celery."""
    from orders.models import Order
    from shipping.services import create_shipment_for_order

    try:
        order = Order.objects.select_related().get(pk=order_id)
    except Order.DoesNotExist:
        logger.error("create_shipment_for_order_task: order %s not found", order_id)
        return

    if hasattr(order, "shipment") and order.shipment.current_status != "error":
        logger.info("create_shipment_for_order_task: shipment already exists for order %s", order.order_number)
        return

    try:
        create_shipment_for_order(order, getattr(order, "shipment", None))
    except ShiprocketAPIError as exc:
        logger.error("create_shipment_for_order_task failed for order %s: %s", order.order_number, exc)
        raise self.retry(exc=exc)


@shared_task(
    name="shipping.tasks.cancel_shipment_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def cancel_shipment_task(self, *, order_id: int) -> None:
    """Cancel an order's Shiprocket shipment, run out-of-band via Celery.

    Triggered when an order is cancelled in the dashboard, keeps
    Shiprocket in sync so a cancelled order doesn't stay live  on the courier side.
    """
    from orders.models import Order
    from shipping.services import cancel_shipment

    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        logger.error("cancel_shipment_task: order %s not found", order_id)
        return

    shipment = getattr(order, "shipment", None)
    if shipment is None:
        logger.info("cancel_shipment_task: no shipment to cancel for order %s", order.order_number)
        return
    if shipment.is_cancelled:
        logger.info("cancel_shipment_task: shipment for order %s already cancelled", order.order_number)
        return

    try:
        cancel_shipment(shipment)
        logger.info("Cancelled Shiprocket shipment for order %s", order.order_number)
    except ShiprocketAPIError as exc:
        logger.error("cancel_shipment_task failed for order %s: %s", order.order_number, exc)
        raise self.retry(exc=exc)
