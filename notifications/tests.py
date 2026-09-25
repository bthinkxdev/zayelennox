"""The delivered-order notification links each purchased product to its review-invite PDP link."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from accounts.models import CustomerProfile
from catalog.models import Category, Product
from catalog.services import verify_review_invite_token
from core.models import Currency
from notifications.tasks import dispatch_order_status_notification
from orders.models import Order, OrderItem, OrderStatus


class DeliveredNotificationReviewLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        user = User.objects.create_user(username="buyer", email="buyer@example.com", password="x")
        currency = Currency.objects.filter(is_default=True).first() or Currency.objects.first()
        self.customer = CustomerProfile.objects.create(user=user, preferred_currency=currency, phone="")
        category = Category.objects.create(name="Cat", slug="cat")
        self.product = Product.objects.create(
            name="Serum", slug="serum", category=category, base_price=Decimal("100"),
            hsn_code="1001", stock_quantity=10,
        )
        self.order = Order.objects.create(
            order_number="ZYL-TEST-1", total_amount=Decimal("100"), currency=currency,
            customer_profile=self.customer, order_status=OrderStatus.DELIVERED,
        )
        OrderItem.objects.create(order=self.order, product=self.product, quantity=1, unit_price=Decimal("100"))

    def test_delivered_email_contains_a_working_review_link_for_the_purchased_product(self):
        dispatch_order_status_notification(
            order_id=self.order.pk, old_status=OrderStatus.OUT_FOR_DELIVERY, new_status=OrderStatus.DELIVERED,
        )
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn(f"/products/{self.product.slug}/", body)
        self.assertIn("review_token=", body)

        token = body.split("review_token=")[1].split("#")[0]
        payload = verify_review_invite_token(token=token)
        self.assertEqual(payload, {"order_id": self.order.pk, "product_id": self.product.pk})
