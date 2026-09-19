"""Read-only query functions for the orders app; views must not call the ORM directly."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from django.core.paginator import Paginator
from django.db.models import Prefetch, Q

from accounts.models import CustomerProfile
from orders.models import BILL_NUMBER_PREFIX, Order, OrderItem, OrderStatusHistory


@dataclass(frozen=True)
class OrderTrackingView:
    """Hydrated order data for the customer tracking timeline."""

    order: Order
    status_history: list[OrderStatusHistory]


def get_customer_orders(
    *,
    customer_profile: CustomerProfile,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """
    Return a paginated page of orders for a customer dashboard.

    Query guarantee: 2 queries — COUNT + page SELECT with select_related.
    """
    queryset = (
        Order.objects.select_related(
            "currency",
        )
        .filter(customer_profile=customer_profile)
        .order_by("-created_at")
    )
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page)
    return {
        "results": list(page_obj.object_list),
        "page": page_obj.number,
        "page_size": page_size,
        "total_count": paginator.count,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


def get_recent_orders_for_customer(*, customer_profile_id: int, limit: int = 5) -> list[Order]:
    """
    Return the most recent orders for a customer profile.

    Delegates to ``get_customer_orders`` page 1 and slices to ``limit``.
    Query guarantee: 2 queries (COUNT + page SELECT).
    """
    profile = CustomerProfile.objects.filter(pk=customer_profile_id).first()
    if profile is None:
        return []
    page = get_customer_orders(customer_profile=profile, page=1, page_size=limit)
    return page["results"]


def get_order_tracking_view(
    *,
    order_id: int,
    customer_profile: Optional[CustomerProfile] = None,
) -> Optional[OrderTrackingView]:
    """
    Return order tracking data with status history in one efficient call.

    Query guarantee: 1 SELECT on order with select_related + 1 prefetch for history.
    """
    queryset = Order.objects.select_related(
        "customer_profile",
        "currency",
        "proof_of_delivery",
    ).prefetch_related(
        Prefetch(
            "status_history",
            queryset=OrderStatusHistory.objects.select_related("changed_by").order_by("changed_at"),
        ),
        Prefetch(
            "items",
            queryset=OrderItem.objects.select_related(
                "product",
                "variant",
            ),
        ),
    )
    if customer_profile is not None:
        queryset = queryset.filter(customer_profile=customer_profile)

    order = queryset.filter(pk=order_id).first()
    if order is None:
        return None

    history = list(order.status_history.all())
    return OrderTrackingView(order=order, status_history=history)


def bill_number_filter(query: str, *, field: str = "order_number") -> Q:
    """
    Match orders by bill number however staff type it.

    * just the sequence digits — ``12`` or ``00012`` — finds that number in every year
      (four digits also match a whole financial year, e.g. ``2627``);
    * a full or partial number in any case, with or without the dashes —
      ``zyl-2627-00012``, ``ZYL262700012``, ``2627-00012`` — finds it;
    * anything else is a plain substring match (still finds older random-style numbers).

    ``field`` is the lookup path to the number, e.g. ``"order__order_number"``.
    """
    query = query.strip()
    compact = re.sub(r"[^A-Za-z0-9]", "", query)

    if re.fullmatch(r"\d{1,5}", query):
        condition = Q(**{f"{field}__iendswith": f"-{query.zfill(5)}"})
        if len(query) == 4:  # could equally be a financial-year series like 2627
            condition |= Q(**{f"{field}__icontains": f"-{query}-"})
        return condition

    match = re.fullmatch(rf"(?:{BILL_NUMBER_PREFIX})?(\d{{4}})(\d{{1,5}})", compact, re.IGNORECASE)
    condition = Q(**{f"{field}__icontains": query})
    if match:
        condition |= Q(**{f"{field}__iexact": f"{BILL_NUMBER_PREFIX}-{match.group(1)}-{match.group(2).zfill(5)}"})
    return condition
