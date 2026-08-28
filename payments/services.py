"""Write operations and business rules for the payments app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction

from orders.models import OrderStatus
from payments.exceptions import InvalidPaymentStatusTransitionError
from payments.models import PaymentStatus, PaymentTransaction
from payments.registry import get_payment_adapter

if TYPE_CHECKING:
    from orders.models import Order

ALLOWED_PAYMENT_STATUS_TRANSITIONS: dict[str, set[str]] = {
    PaymentStatus.PENDING: {PaymentStatus.SUCCESS, PaymentStatus.FAILED},
    PaymentStatus.SUCCESS: set(),
    PaymentStatus.FAILED: {PaymentStatus.SUCCESS},
}


@transaction.atomic
def confirm_payment_success(*, payment_transaction: PaymentTransaction) -> PaymentTransaction:
    """
    Single convergence point for successful payment — sync or async.

    Order confirmation logic lives here exclusively regardless of gateway.
    """
    payment_transaction.status = PaymentStatus.SUCCESS
    payment_transaction.save(update_fields=["status", "updated_at"])

    #empty and deactivate the cart now that payment is confirmed
    order = payment_transaction.order
    if order:
        from checkout.models import CheckoutSession, CheckoutSessionStatus
        session = CheckoutSession.objects.filter(order=order).first()
        if session:
            session.status = CheckoutSessionStatus.COMPLETED
            session.save(update_fields=["status", "updated_at"])

        if order.cart:
            cart = order.cart
            from cart.models import CartItem
            CartItem.objects.filter(cart=cart).delete()

        #send order placement confirmation email
        from notifications.tasks import dispatch_order_confirmation_notification
        transaction.on_commit(
            lambda: dispatch_order_confirmation_notification.delay(order_id=order.pk)
        )

    return payment_transaction


@transaction.atomic
def confirm_payment_failed(*, payment_transaction: PaymentTransaction) -> PaymentTransaction:
    """Mark a payment transaction as failed."""
    payment_transaction.status = PaymentStatus.FAILED
    payment_transaction.save(update_fields=["status", "updated_at"])
    return payment_transaction


@transaction.atomic
def mark_cod_payment_collected(*, order: "Order") -> None:
    """
    Flip a Cash-on-Delivery order's payment transaction(s) to Success.

    """
    pending_cod_txs = PaymentTransaction.objects.filter(
        order=order,
        gateway_key="cod",
        status=PaymentStatus.PENDING,
    )
    for payment_tx in pending_cod_txs:
        payment_tx.status = PaymentStatus.SUCCESS
        payment_tx.save(update_fields=["status", "updated_at"])


@transaction.atomic
def transition_payment_status(
    *, payment_transaction: PaymentTransaction, new_status: str
) -> PaymentTransaction:
    """
    Validate and apply a manual payment status change (the dashboard's
    "Update Payment" action on the order detail page).

    """
    old_status = payment_transaction.status
    if new_status == old_status:
        return payment_transaction

    order = payment_transaction.order
    if order is not None:
        if order.order_status == OrderStatus.DELIVERED and new_status == PaymentStatus.FAILED:
            raise InvalidPaymentStatusTransitionError(
                "Can't mark payment as Failed: this order has already been delivered."
            )
        if order.order_status == OrderStatus.CANCELLED and new_status == PaymentStatus.SUCCESS:
            raise InvalidPaymentStatusTransitionError(
                "Can't mark payment as Paid: this order is Cancelled. Use "
                "Refunded on the order status instead if money needs to go back."
            )

    allowed = ALLOWED_PAYMENT_STATUS_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise InvalidPaymentStatusTransitionError(
            f"Cannot change payment status from "
            f"{PaymentStatus(old_status).label} to {PaymentStatus(new_status).label}."
        )

    if new_status == PaymentStatus.SUCCESS:
        confirm_payment_success(payment_transaction=payment_transaction)
    elif new_status == PaymentStatus.FAILED:
        confirm_payment_failed(payment_transaction=payment_transaction)
    else:
        payment_transaction.status = new_status
        payment_transaction.save(update_fields=["status", "updated_at"])

    return payment_transaction


@transaction.atomic
def process_payment(
    *,
    order: Order,
    gateway_key: str,
    payment_data: dict[str, Any],
) -> PaymentTransaction:
    """
    Process payment via registry-selected adapter.

    Writes PaymentTransaction as PENDING immediately. Sync gateways capture
    inline; async gateways complete via webhook → confirm_payment_success.
    """
    adapter = get_payment_adapter(gateway_key=gateway_key)
    metadata = {"order_id": order.pk, "order_number": order.order_number, **payment_data}

    #clean up: mark any previous abandoned payment attempts as failed
    PaymentTransaction.objects.filter(
        order=order,
        status=PaymentStatus.PENDING
    ).update(status=PaymentStatus.FAILED)

    payment_tx = PaymentTransaction.objects.create(
        order=order,
        gateway_key=gateway_key,
        amount=order.total_amount,
        currency=order.currency,
        status=PaymentStatus.PENDING,
        metadata=metadata,
    )

    intent = adapter.create_payment_intent(
        amount=order.total_amount,
        currency=order.currency.code,
        metadata=metadata,
    )
    payment_tx.external_intent_id = intent.intent_id
    payment_tx.save(update_fields=["external_intent_id", "updated_at"])

    if adapter.is_async:
        return payment_tx

    capture = adapter.capture(intent_id=intent.intent_id)

    payment_tx.external_transaction_id = capture.transaction_id
    payment_tx.metadata.update(capture.metadata)
    payment_tx.save(update_fields=["external_transaction_id", "metadata", "updated_at"])

    if capture.success:
        confirm_payment_success(payment_transaction=payment_tx)
        #COD checkouts are successful, but the payment itself should remain Pending until the admin manually collects the cash and marks it as Success.
        if gateway_key == "cod":
            payment_tx.status = PaymentStatus.PENDING
            payment_tx.save(update_fields=["status", "updated_at"])
    else:
        confirm_payment_failed(payment_transaction=payment_tx)

    return payment_tx


@transaction.atomic
def handle_payment_webhook(
    *,
    gateway_key: str,
    payload: bytes,
    signature: str,
) -> PaymentTransaction | None:
    """
    Verify webhook via adapter and converge on confirm_payment_success/failed.
    """
    adapter = get_payment_adapter(gateway_key=gateway_key)
    event = adapter.verify_webhook(payload=payload, signature=signature)

    intent_id = event.get("intent_id", "")
    payment_tx = PaymentTransaction.objects.filter(
        external_intent_id=intent_id,
        gateway_key=gateway_key,
    ).first()
    if payment_tx is None:
        return None

    if event.get("status") == "success":
        payment_tx.external_transaction_id = event.get("transaction_id", "")
        payment_tx.save(update_fields=["external_transaction_id", "updated_at"])
        return confirm_payment_success(payment_transaction=payment_tx)

    return confirm_payment_failed(payment_transaction=payment_tx)
