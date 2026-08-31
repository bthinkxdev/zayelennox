"""Cross-app signal handlers for the reports app (side effects only)."""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from orders.models import Order
from orders.signals import order_status_changed

logger = logging.getLogger(__name__)


def _queue_report_refresh(order: Order) -> None:
    """
    Recompute the pre-aggregated report rows for the order's day, once the
    current transaction commits.

    """
    from reports.tasks import aggregate_daily_reports_task

    report_date_iso = timezone.localtime(order.created_at).date().isoformat()

    def _dispatch() -> None:
        try:
            aggregate_daily_reports_task.delay(report_date_iso=report_date_iso)
        except Exception:
            logger.exception(
                "Failed to queue report refresh for %s (order %s).",
                report_date_iso,
                order.order_number,
            )

    transaction.on_commit(_dispatch)


@receiver(post_save, sender=Order)
def refresh_report_on_order_created(sender, instance, created, **kwargs):
    """A brand-new order changes today's order count/revenue — refresh immediately."""
    if not created:
        return
    _queue_report_refresh(instance)


@receiver(order_status_changed)
def refresh_report_on_status_change(sender, order, old_status, new_status, **kwargs):

    _queue_report_refresh(order)
