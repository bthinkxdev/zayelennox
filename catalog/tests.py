"""Delivered-order review invites: signed token round-trip and submission gating."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomerProfile
from catalog.models import Category, Product, Review
from catalog.services import (
    build_review_invite_path,
    create_review_invite_token,
    verify_review_invite_token,
)
from core.models import Currency
from orders.models import Order, OrderItem, OrderStatus


def make_customer(email: str) -> CustomerProfile:
    User = get_user_model()
    user = User.objects.create_user(username=email, email=email, password="x")
    currency = Currency.objects.filter(is_default=True).first() or Currency.objects.first()
    return CustomerProfile.objects.create(user=user, preferred_currency=currency, phone="")


def make_product(slug: str) -> Product:
    category = Category.objects.filter(slug="cat").first() or Category.objects.create(name="Cat", slug="cat")
    return Product.objects.create(
        name=slug, slug=slug, category=category, base_price=Decimal("100"), hsn_code="1001", stock_quantity=10
    )


def make_order(customer: CustomerProfile, status: str = OrderStatus.DELIVERED) -> Order:
    currency = Currency.objects.filter(is_default=True).first() or Currency.objects.first()
    return Order.objects.create(
        order_number=f"ZYL-TEST-{Order.objects.count() + 1}",
        total_amount=Decimal("100"),
        currency=currency,
        customer_profile=customer,
        order_status=status,
    )


def make_item(order: Order, product: Product) -> OrderItem:
    return OrderItem.objects.create(order=order, product=product, quantity=1, unit_price=Decimal("100"))


class ReviewInviteTokenTests(TestCase):
    def test_valid_token_round_trips(self):
        token = create_review_invite_token(order_id=7, product_id=3)
        self.assertEqual(verify_review_invite_token(token=token), {"order_id": 7, "product_id": 3})

    def test_tampered_token_is_rejected(self):
        token = create_review_invite_token(order_id=7, product_id=3)
        with self.assertRaises(signing.BadSignature):
            verify_review_invite_token(token=token + "x")

    @override_settings(REVIEW_INVITE_TOKEN_MAX_AGE=-1)
    def test_expired_token_is_rejected(self):
        token = create_review_invite_token(order_id=7, product_id=3)
        with self.assertRaises(signing.BadSignature):
            verify_review_invite_token(token=token)

    def test_build_review_invite_path_scrolls_to_reviews(self):
        product = make_product("invite-path-product")
        path = build_review_invite_path(order_id=9, product=product)
        self.assertIn(f"/products/{product.slug}/", path)
        self.assertIn("review_token=", path)
        self.assertTrue(path.endswith("#reviews"))


class SubmitReviewViewTests(TestCase):
    def setUp(self):
        self.customer = make_customer("buyer@example.com")
        self.product = make_product("reviewed-product")
        self.order = make_order(self.customer)
        self.item = make_item(self.order, self.product)
        self.submit_url = reverse("catalog:submit-review", args=[self.product.pk])

    def post_with_token(self, **extra):
        token = create_review_invite_token(order_id=self.order.pk, product_id=self.product.pk)
        data = {"rating": 5, "title": "Great", "body": "Loved it", "token": token, **extra}
        return self.client.post(self.submit_url, data)

    def test_guest_with_valid_token_can_submit_and_review_is_verified(self):
        self.post_with_token()
        review = Review.objects.get(product=self.product)
        self.assertEqual(review.order_id, self.order.pk)
        self.assertEqual(review.customer_id, self.customer.pk)
        self.assertTrue(review.is_verified_purchase)

    def test_no_login_required_for_guest_token_path(self):
        response = self.post_with_token()
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertTrue(Review.objects.filter(product=self.product).exists())

    def test_tampered_token_is_rejected(self):
        response = self.client.post(
            self.submit_url,
            {"rating": 5, "title": "Great", "body": "Loved it", "token": "not-a-real-token"},
        )
        self.assertFalse(Review.objects.filter(product=self.product).exists())
        self.assertEqual(response.status_code, 302)

    def test_token_for_a_different_product_is_rejected(self):
        other_product = make_product("other-product")
        other_item = make_item(self.order, other_product)
        token = create_review_invite_token(order_id=self.order.pk, product_id=other_product.pk)
        self.client.post(self.submit_url, {"rating": 5, "title": "t", "body": "b", "token": token})
        self.assertFalse(Review.objects.filter(product=self.product).exists())

    def test_non_delivered_order_is_rejected(self):
        pending_order = make_order(self.customer, status=OrderStatus.RECEIVED)
        make_item(pending_order, self.product)
        token = create_review_invite_token(order_id=pending_order.pk, product_id=self.product.pk)
        self.client.post(self.submit_url, {"rating": 5, "title": "t", "body": "b", "token": token})
        self.assertFalse(Review.objects.filter(product=self.product).exists())

    def test_duplicate_review_for_same_order_and_product_is_rejected(self):
        self.post_with_token()
        self.post_with_token(title="Second attempt")
        self.assertEqual(Review.objects.filter(order=self.order, product=self.product).count(), 1)

    def test_authenticated_customer_can_still_submit_via_order_id(self):
        self.client.force_login(self.customer.user)
        response = self.client.post(
            self.submit_url,
            {"rating": 4, "title": "Good", "body": "Solid", "order_id": self.order.pk},
        )
        review = Review.objects.get(product=self.product)
        self.assertEqual(review.order_id, self.order.pk)
        self.assertTrue(review.is_verified_purchase)
        self.assertEqual(response.status_code, 302)

    def test_authenticated_customer_without_a_matching_delivered_order_is_rejected(self):
        other_customer = make_customer("other@example.com")
        self.client.force_login(other_customer.user)
        self.client.post(
            self.submit_url,
            {"rating": 4, "title": "Good", "body": "Solid", "order_id": self.order.pk},
        )
        self.assertFalse(Review.objects.filter(product=self.product).exists())


class PDPReviewFormRenderTests(TestCase):
    def setUp(self):
        self.customer = make_customer("pdp-buyer@example.com")
        self.product = make_product("pdp-reviewable-product")
        self.order = make_order(self.customer)
        make_item(self.order, self.product)
        self.pdp_url = reverse("catalog:pdp", args=[self.product.slug])

    def test_guest_with_valid_review_token_sees_the_form(self):
        token = create_review_invite_token(order_id=self.order.pk, product_id=self.product.pk)
        page = self.client.get(f"{self.pdp_url}?review_token={token}").content.decode()
        self.assertIn("jm-pdp-review-form", page)
        self.assertIn(f'value="{token}"', page)

    def test_anonymous_visitor_without_a_token_does_not_see_the_form(self):
        page = self.client.get(self.pdp_url).content.decode()
        self.assertNotIn("jm-pdp-review-form", page)

    def test_invalid_token_does_not_show_the_form(self):
        page = self.client.get(f"{self.pdp_url}?review_token=garbage").content.decode()
        self.assertNotIn("jm-pdp-review-form", page)

    def test_already_reviewed_order_product_shows_thank_you_instead_of_the_form(self):
        Review.objects.create(product=self.product, customer=self.customer, order=self.order, rating=5, title="t", body="b")
        token = create_review_invite_token(order_id=self.order.pk, product_id=self.product.pk)
        page = self.client.get(f"{self.pdp_url}?review_token={token}").content.decode()
        self.assertNotIn("jm-pdp-review-form", page)
        self.assertIn("already reviewed", page)

    def test_logged_in_customer_with_delivered_order_sees_the_form_without_a_token(self):
        self.client.force_login(self.customer.user)
        page = self.client.get(self.pdp_url).content.decode()
        self.assertIn("jm-pdp-review-form", page)
