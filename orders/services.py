"""Write operations and business rules for the orders app."""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from orders.exceptions import InvalidOrderStatusTransitionError
from orders.models import (
    BILL_NUMBER_PREFIX,
    Order,
    OrderNumberSequence,
    OrderStatus,
    OrderStatusHistory,
)
from orders.signals import order_status_changed

ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.RECEIVED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.PACKAGING, OrderStatus.CANCELLED},
    OrderStatus.PACKAGING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.OUT_FOR_DELIVERY, OrderStatus.CANCELLED},
    OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.DELIVERED, OrderStatus.CANCELLED},
    OrderStatus.DELIVERED: {OrderStatus.REFUNDED},
    OrderStatus.CANCELLED: {OrderStatus.REFUNDED},
    OrderStatus.REFUNDED: set(),
}

HARD_BLOCKED_TRANSITIONS: dict[str, dict[str, str]] = {
    OrderStatus.DELIVERED: {
        OrderStatus.CANCELLED: (
            "Delivered orders can't be cancelled. Use Refunded instead if "
            "money needs to be returned to the customer."
        ),
    },
    OrderStatus.CANCELLED: {
        OrderStatus.DELIVERED: (
            "Cancelled orders can't be marked Delivered. If the customer "
            "still wants this order, create a new one."
        ),
    },
}


def financial_year_series(day: date) -> str:
    """Indian financial-year series for a date: April 2026 – March 2027 is ``"2627"``."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


@transaction.atomic
def generate_order_number(*, on: Optional[date] = None) -> str:
    """
    Issue the next bill number, e.g. ``ZYL-2627-00012``.

    Numbers run 1, 2, 3… within each Indian financial year (restarting on 1 April),
    which is what a tax invoice series needs: unique, sequential and traceable.
    The sequence row is locked while the number is taken, so concurrent orders can't
    get the same number, and because this runs inside the order's own transaction a
    failed order doesn't use one up.
    """
    series = financial_year_series(on or timezone.localdate())
    sequence, _ = OrderNumberSequence.objects.get_or_create(series=series)
    sequence = OrderNumberSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number", "updated_at"])
    return f"{BILL_NUMBER_PREFIX}-{series}-{sequence.last_number:05d}"


@transaction.atomic
def transition_order_status(
    *,
    order: Order,
    new_status: str,
    actor: Optional[User] = None,
    note: str = "",
    send_notifications: bool = True,
    force: bool = False,
) -> Order:
    """
    Validate and apply an order status transition.

    Writes ``OrderStatusHistory`` atomically and emits ``order_status_changed``.
    Notifications listen to the signal — this service never calls them directly.
    """
    old_status = order.order_status
    if new_status == old_status:
        return order

    blocked_message = HARD_BLOCKED_TRANSITIONS.get(old_status, {}).get(new_status)
    if blocked_message:
       
        raise InvalidOrderStatusTransitionError(blocked_message)

    if not force:
        allowed = ALLOWED_STATUS_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise InvalidOrderStatusTransitionError(
                f"Cannot transition order from {old_status} to {new_status}."
            )

    order.order_status = new_status
    order.save(update_fields=["order_status", "updated_at"])

    OrderStatusHistory.objects.create(
        order=order,
        from_status=old_status,
        to_status=new_status,
        changed_by=actor,
        note=note,
    )

    order_status_changed.send(
        sender=Order,
        order=order,
        old_status=old_status,
        new_status=new_status,
        send_notifications=send_notifications,
    )
    return order
