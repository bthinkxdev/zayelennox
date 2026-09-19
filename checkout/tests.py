"""Checkout ↔ saved-address ↔ shipping-quote behaviour."""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from accounts.models import Address, CustomerProfile
from catalog.models import Category, Product
from checkout.models import CheckoutSession
from core.models import Currency
from core.services import get_site_settings
from orders.models import Order
from shipping.rates import fetch_courier_options, resolve_order_shipping_charge
from shipping.shiprocket_client import shiprocket_client

COURIERS = {
    "available_couriers": [
        {"courier_id": 6, "courier_name": "DTDC Surface", "freight_charge": 77.32, "estimated_delivery_days": 2,
         "etd": "Sep 20, 2026", "eta_hours": 48, "rating": 4.0, "is_surface": True},
        {"courier_id": 1, "courier_name": "Blue Dart Air", "freight_charge": 98.28, "estimated_delivery_days": 3,
         "etd": "Sep 21, 2026", "eta_hours": 72, "rating": 4.8, "is_surface": False},
    ],
    "recommended_courier_id": 1,
}


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(username="cust", email="cust@example.com", password="x", first_name="Asha")
        currency = Currency.objects.filter(is_default=True).first() or Currency.objects.first()
        self.profile = CustomerProfile.objects.create(user=self.user, preferred_currency=currency, phone="9876543210")
        category = Category.objects.create(name="Cat", slug="cat")
        self.product = Product.objects.create(
            name="P", slug="p", category=category, base_price=Decimal("100"), hsn_code="1001", stock_quantity=10
        )
        self.client.force_login(self.user)
        self.client.post("/cart/add/", {"product_id": self.product.pk, "quantity": 1})

        site = get_site_settings()
        site.use_shiprocket_delivery_charge = True
        site.default_shipping_charge = Decimal("50.00")
        site.shiprocket_pickup_pincode = "683106"
        site.save()

    def address(self, **overrides):
        data = dict(customer_profile=self.profile, label="Home", line1="12 Marine Drive", city_name="Kochi",
                    state_name="Kerala", pincode="682001")
        data.update(overrides)
        return Address.objects.create(**data)


class AddressDeliverabilityTests(_Base):
    def test_complete_address_is_deliverable(self):
        self.assertTrue(self.address().is_deliverable)

    def test_legacy_address_without_pincode_or_state_is_flagged(self):
        legacy = self.address(pincode="", state_name="")
        self.assertFalse(legacy.is_deliverable)
        self.assertEqual(set(legacy.delivery_problems), {"pincode", "state_name"})

    def test_malformed_pincode_is_flagged(self):
        for bad in ("12345", "0123456", "68200A", " "):
            self.assertIn("pincode", self.address(pincode=bad).delivery_problems, bad)


class CheckoutAddressSelectionTests(_Base):
    def test_preselects_first_deliverable_address_not_an_incomplete_default(self):
        incomplete = self.address(label="Old", pincode="", state_name="", is_default=True)
        complete = self.address(label="New")
        html = self.client.get("/checkout/").content.decode()

        self.assertRegex(html, rf'id="addr-{complete.pk}"[^>]*data-complete="1"[^>]*checked')
        self.assertRegex(html, rf'id="addr-{incomplete.pk}"[^>]*data-complete="0"')
        self.assertNotRegex(html, rf'id="addr-{incomplete.pk}"[^>]*data-complete="0"\s*checked')
        self.assertIn("Incomplete", html)

    def test_saved_address_pincode_is_exposed_for_the_delivery_check(self):
        addr = self.address(pincode="682030")
        html = self.client.get("/checkout/").content.decode()
        self.assertIn(f'id="addr-{addr.pk}" data-pincode="682030"', html)

    def test_place_order_rejects_incomplete_saved_address(self):
        legacy = self.address(pincode="", state_name="")
        response = self.client.post(
            "/checkout/place-order/",
            {"address_id": legacy.pk, "gateway_key": "razorpay", "idempotency_key": "k-incomplete"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('id="error-address_id"', body)
        self.assertIn("missing its", body)
        self.assertIn("pincode", body)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(CheckoutSession.objects.filter(address=legacy).exists())

    def test_edit_endpoint_reports_whether_address_is_now_deliverable(self):
        legacy = self.address(pincode="", state_name="")
        response = self.client.post(
            f"/checkout/address/{legacy.pk}/update/",
            {"name": "Asha", "phone": "9876543210", "address_line1": "12 Marine Drive", "city_name": "Kochi",
             "state_name": "Kerala", "pincode": "682001"},
        )
        payload = response.json()
        self.assertTrue(payload["success"], payload)
        self.assertTrue(payload["address"]["is_deliverable"])
        legacy.refresh_from_db()
        self.assertTrue(legacy.is_deliverable)


class SavedAddressShippingTests(_Base):
    def test_check_serviceability_works_for_a_saved_address_pincode(self):
        addr = self.address(pincode="682001")
        with mock.patch.object(shiprocket_client, "get_shipping_rates", return_value=COURIERS) as rates:
            data = self.client.get(f"/shipping/check-serviceability/?pincode={addr.pincode}").json()
        self.assertTrue(data["ok"] and data["is_serviceable"])
        self.assertEqual([c["courier_id"] for c in data["available_couriers"]], [6, 1])
        self.assertEqual(data["selected_courier_id"], "6")  # cheapest by default
        self.assertEqual(rates.call_args.kwargs["delivery_pincode"], "682001")

    def test_order_charge_uses_the_saved_addresss_pincode_even_if_browser_never_checked(self):
        from cart.selectors import get_cart_for_request
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = self.user
        request.session = self.client.session
        cart = get_cart_for_request(request=request)
        with mock.patch.object(shiprocket_client, "get_shipping_rates", return_value=COURIERS):
            charge = resolve_order_shipping_charge(request, cart=cart, pincode="682001")
        self.assertEqual(charge, Decimal("77.32"))

    def test_order_charge_falls_back_to_flat_rate_when_pincode_missing(self):
        from cart.selectors import get_cart_for_request
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = self.user
        request.session = self.client.session
        cart = get_cart_for_request(request=request)
        self.assertEqual(resolve_order_shipping_charge(request, cart=cart, pincode=""), Decimal("50.00"))

    def test_quotes_are_cached_so_repeat_checks_do_not_hit_shiprocket(self):
        from cart.selectors import get_cart_for_request
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = self.user
        request.session = self.client.session
        cart = get_cart_for_request(request=request)
        with mock.patch.object(shiprocket_client, "get_shipping_rates", return_value=COURIERS) as rates:
            fetch_courier_options(cart=cart, pincode="682001")
            fetch_courier_options(cart=cart, pincode="682001")
        self.assertEqual(rates.call_count, 1)
