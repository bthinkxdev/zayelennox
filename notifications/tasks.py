"""Celery tasks for the notifications app."""

from __future__ import annotations

from celery import shared_task

from notifications.services import create_notification, send_email, send_sms, send_whatsapp


@shared_task(name="notifications.tasks.dispatch_sms")
def dispatch_sms(*, phone: str, message: str) -> None:
    """Async Celery wrapper around the send_sms service function."""
    send_sms(phone=phone, message=message)


@shared_task(name="notifications.tasks.dispatch_order_status_notification")
def dispatch_order_status_notification(
    *,
    order_id: int,
    old_status: str,
    new_status: str,
) -> None:
    """
    Send order status updates on the customer's preferred channels.

    Chooses email, SMS, and/or WhatsApp based on CustomerProfile preferences.
    """
    from orders.models import Order

    order = (
        Order.objects.select_related("customer_profile", "customer_profile__user")
        .prefetch_related("items__product")
        .filter(pk=order_id)
        .first()
    )
    if order is None or order.customer_profile is None:
        return

    profile = order.customer_profile
    user = profile.user
    title = f"Order {order.order_number} update"
    
    items = list(order.items.all())
    product_names = ", ".join([item.product.name for item in items[:3]])
    if len(items) > 3:
        product_names += " and more"
        
    status_messages = {
        "preparing": f"Great news! We have started packing your order ({order.order_number}) containing {product_names} and will ship it out soon.",
        "packaging": f"Great news! We have started packing your order ({order.order_number}) containing {product_names} and will ship it out soon.",
        "ready": f"Your order ({order.order_number}) is ready to be shipped out.",
        "out_for_delivery": f"Your order ({order.order_number}) containing {product_names} is out for delivery today! Please make sure someone is available to receive it.",
        "delivered": f"Your order ({order.order_number}) has been delivered! We hope you love your new equipment. (You can now leave a review in your dashboard!).",
        "cancelled": f"Your order ({order.order_number}) has been cancelled successfully. If you have already paid, your refund will be processed within 5-7 business days.",
        "refunded": f"Your order ({order.order_number}) has been refunded."
    }
    
    body = status_messages.get(new_status, f"Your order status changed from {old_status} to {new_status}.")
    body += "\n\nBest regards,\nThe ZAYE LENNOX Team"

    if profile.notify_via_email and user.email:
        send_email(email=user.email, subject=title, message=body)

    if profile.phone:
        if profile.notify_via_sms:
            send_sms(phone=profile.phone, message=body)
        if profile.notify_via_whatsapp:
            send_whatsapp(phone=profile.phone, message=body)


@shared_task(name="notifications.tasks.dispatch_order_confirmation_notification")
def dispatch_order_confirmation_notification(*, order_id: int) -> None:
    """
    Send an order confirmation email / notification right after the order is placed.
    """
    from orders.models import Order
    from django.urls import reverse
    from core.services import get_site_settings

    order = (
        Order.objects.select_related("customer_profile", "customer_profile__user")
        .prefetch_related("items__product")
        .filter(pk=order_id)
        .first()
    )
    if order is None or order.customer_profile is None:
        return

    profile = order.customer_profile
    user = profile.user
    title = f"Order Confirmation - {order.order_number}"
    
    items = list(order.items.all())
    product_names = ", ".join([item.product.name for item in items[:3]])
    if len(items) > 3:
        product_names += " and more"
    
    body = (
        f"Thank you for your order!\n\n"
        f"Your order {order.order_number} containing {product_names} has been successfully received.\n"
        f"We will notify you once the status changes.\n\n"
        f"Best regards,\n"
        f"The ZAYE LENNOX Team"
    )

    if profile.notify_via_email and user.email:
        send_email(email=user.email, subject=title, message=body)

    if profile.phone:
        if profile.notify_via_sms:
            send_sms(phone=profile.phone, message=f"ZAYE LENNOX: Order {order.order_number} confirmed. Thank you!")
        if profile.notify_via_whatsapp:
            send_whatsapp(phone=profile.phone, message=body)


@shared_task(name="notifications.tasks.dispatch_vendor_order_notification")
def dispatch_vendor_order_notification(*, order_id: int) -> None:

    from django.contrib.auth.models import User
    from django.db.models import Q

    from core.services import get_site_settings
    from dashboard.access import DASHBOARD_GROUPS
    from orders.models import Order

    order = (
        Order.objects.select_related("customer_profile__user", "currency")
        .prefetch_related("items__product")
        .filter(pk=order_id)
        .first()
    )
    if order is None:
        return

    items = list(order.items.all())
    product_names = ", ".join(item.product.name for item in items[:3])
    if len(items) > 3:
        product_names += " and more"

    if order.customer_profile and order.customer_profile.user:
        customer_user = order.customer_profile.user
        customer_name = customer_user.get_full_name() or customer_user.username
    else:
        customer_name = (order.delivery_address_snapshot or {}).get("name") or "Guest"

    currency_symbol = order.currency.symbol if order.currency else ""

    title = f"New order {order.order_number}"
    body = (
        f"New order {order.order_number} was just placed by {customer_name}.\n\n"
        f"Items: {product_names}\n"
        f"Total: {currency_symbol}{order.total_amount}\n\n"
        f"View it in the dashboard under Orders."
    )

    #in-app notification for every dashboard staff user (same roles that can
    #access the dashboard - see dashboard.access.user_can_access_dashboard).
    staff_users = User.objects.filter(
        Q(is_superuser=True) | Q(groups__name__in=DASHBOARD_GROUPS)
    ).distinct()
    for staff_user in staff_users:
        create_notification(user=staff_user, title=title, body=body)

    #email the vendor's registered inbox, if configured.
    site_settings = get_site_settings()
    if site_settings.vendor_email:
        send_email(email=site_settings.vendor_email, subject=title, message=body)

