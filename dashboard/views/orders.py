"""Order management: filterable list, detail, and guarded status transitions."""

from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from dashboard.access import dashboard_required
from orders.exceptions import InvalidOrderStatusTransitionError
from orders.models import Order, OrderStatus
from orders.services import ALLOWED_STATUS_TRANSITIONS, transition_order_status


@dashboard_required
@require_http_methods(["GET"])
def order_list(request: HttpRequest) -> HttpResponse:
    """Paginated, status-filterable, searchable order list."""
    qs = Order.objects.select_related("customer_profile__user", "currency").order_by("-created_at")

    status = request.GET.get("status", "").strip()
    if status:
        qs = qs.filter(order_status=status)
    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(
            Q(order_number__icontains=query)
            | Q(customer_profile__phone__icontains=query)
            | Q(delivery_address_snapshot__phone__icontains=query)
        )

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    context = {
        "nav_section": "orders",
        "page_title": "Orders",
        "page_obj": page_obj,
        "objects": page_obj.object_list,
        "statuses": OrderStatus.choices,
        "current_status": status,
        "search_query": query,
        "querystring": params.urlencode(),
    }
    return render(request, "dashboard/orders/list.html", context)


@dashboard_required
@require_http_methods(["GET"])
def order_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Order detail with line items, status history, POD and payments."""
    order = get_object_or_404(
        Order.objects.select_related("customer_profile__user", "currency"), pk=pk
    )
    items = order.items.select_related("product", "variant").all()
    history = order.status_history.select_related("changed_by").all()
    payments = order.payment_transactions.select_related("currency").all()
    pod = getattr(order, "proof_of_delivery", None)

    allowed_choices = OrderStatus.choices

    context = {
        "nav_section": "orders",
        "page_title": f"Order {order.order_number}",
        "order": order,
        "items": items,
        "history": history,
        "payments": payments,
        "pod": pod,
        "allowed_choices": allowed_choices,
    }
    return render(request, "dashboard/orders/detail.html", context)


@dashboard_required
@require_POST
def order_transition(request: HttpRequest, pk: int) -> HttpResponse:
    """Apply a status transition through the orders service state machine."""
    order = get_object_or_404(Order, pk=pk)
    new_status = request.POST.get("new_status", "")
    note = request.POST.get("note", "")

    if new_status == OrderStatus.CANCELLED and not note.strip():
        messages.error(
            request,
            "Please add a note explaining why this order is being cancelled.",
        )
        return redirect("dashboard:order-detail", pk=pk)

    try:
        transition_order_status(
            order=order, new_status=new_status, actor=request.user, note=note, force=True
        )
        messages.success(
            request, f"Order moved to {dict(OrderStatus.choices).get(new_status, new_status)}."
        )
    except InvalidOrderStatusTransitionError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:order-detail", pk=pk)


@dashboard_required
@require_POST
def order_payment_transition(request: HttpRequest, pk: int) -> HttpResponse:
    """Manually update the payment status of the latest payment transaction."""
    from payments.exceptions import InvalidPaymentStatusTransitionError
    from payments.models import PaymentStatus
    from payments.services import transition_payment_status

    order = get_object_or_404(Order, pk=pk)
    new_status = request.POST.get("new_status", "")

    # get the latest payment transaction to update
    tx = order.payment_transactions.last()

    if not tx:
        messages.error(request, "Could not update payment status: No payment records found.")
    elif new_status not in dict(PaymentStatus.choices):
        messages.error(request, "Unknown payment status.")
    else:
        try:
            transition_payment_status(payment_transaction=tx, new_status=new_status)
            messages.success(
                request, f"Payment marked as {dict(PaymentStatus.choices).get(new_status)}."
            )
        except InvalidPaymentStatusTransitionError as exc:
            messages.error(request, str(exc))

    return redirect("dashboard:order-detail", pk=pk)


@dashboard_required
@require_http_methods(["GET"])
def order_invoice_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Render the HTML invoice for an order."""
    from core.models import SiteSettings
    order = get_object_or_404(
        Order.objects.select_related("customer_profile__user", "currency"), pk=pk
    )
    
    context = {
        "order": order,
        "site_settings": SiteSettings.objects.first(),
    }
    return render(request, "shared/order_invoice.html", context)

