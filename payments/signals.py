"""Cross-app signal handlers for the payments app (side effects only)."""

from __future__ import annotations

from django.dispatch import receiver

from orders.models import OrderStatus
from orders.signals import order_status_changed
from payments.services import mark_cod_payment_collected


@receiver(order_status_changed)
def mark_cod_paid_on_delivery(
    sender,
    *,
    order,
    old_status: str,
    new_status: str,
    **kwargs,
) -> None:
    """
    Cash-on-Delivery payments sit Pending until the order is actually
    delivered and the vendor has the cash in hand - flip them to Success
    once that happens.

    """
    if new_status != OrderStatus.DELIVERED:
        return
    mark_cod_payment_collected(order=order)
