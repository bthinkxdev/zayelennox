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
from shipping.exceptions import ShiprocketAPIError
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


class FreeDeliveryTests(_Base):
    """
    The vendor's "Charge customers for delivery" switch: when off, no delivery charge reaches
    the cart, checkout, order total, payment amount or bill - while Shiprocket keeps working.
    """

    def setUp(self):
        super().setUp()
        self.set_charging(False)
        self.address()  # complete saved address (682001)

    def set_charging(self, on: bool):
        site = get_site_settings()
        site.charge_for_delivery = on
        site.save()

    def cart(self):
        from cart.models import Cart

        return Cart.objects.get(customer_profile=self.profile, is_buy_now=False)

    def request_with_session(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = self.user
        request.session = self.client.session
        return request

    def place(self, *, override=None, key="k-free"):
        from checkout.services import place_order

        session = CheckoutSession.objects.create(
            cart=self.cart(), customer_profile=self.profile, address=Address.objects.first()
        )
        return place_order(
            checkout_session_id=session.pk, idempotency_key=key, customer_profile=self.profile,
            shipping_charge_override=override,
        )

    # ---- cart -----------------------------------------------------------
    def test_cart_summary_never_includes_a_delivery_charge(self):
        from cart.models import Cart
        from cart.selectors import get_cart_summary

        Cart.objects.filter(pk=self.cart().pk).update(delivery_charge=Decimal("40.00"))
        summary = get_cart_summary(cart=self.cart())
        self.assertTrue(summary.free_delivery)
        self.assertEqual(summary.delivery_charge, Decimal("0.00"))
        self.assertEqual(summary.grand_total, summary.subtotal)

        self.set_charging(True)  # regression: the stored charge applies again
        summary = get_cart_summary(cart=self.cart())
        self.assertFalse(summary.free_delivery)
        self.assertEqual(summary.delivery_charge, Decimal("40.00"))
        self.assertEqual(summary.grand_total, summary.subtotal + Decimal("40.00"))

    def test_cart_page_and_sidebar_cart_say_free(self):
        for url in ("/cart/", "/cart/drawer/"):
            html = self.client.get(url).content.decode()
            self.assertIn(">Free<", html, url)
            self.assertNotIn("Calculated at checkout", html, url)
        self.set_charging(True)
        self.assertIn("Calculated at checkout", self.client.get("/cart/").content.decode())
        self.assertNotIn(">Free<", self.client.get("/cart/drawer/").content.decode())

    # ---- checkout page --------------------------------------------------
    def test_checkout_page_announces_free_delivery_and_shows_no_charge(self):
        html = self.client.get("/checkout/").content.decode()
        self.assertIn("Free delivery", html)
        self.assertIn('class="co-free"', html)
        self.assertIn("var freeDelivery = true;", html)
        self.assertRegex(html, r'id="summary-shipping" data-server-value="0\.0+" data-value="0\.0+" class="text-success fw-semibold">Free<')
        self.assertRegex(html, r'id="summary-total" data-server-value="100\.0+"')  # the product's price, nothing added

    def test_checkout_page_is_unchanged_when_delivery_is_charged(self):
        self.set_charging(True)
        html = self.client.get("/checkout/").content.decode()
        self.assertNotIn('class="co-free"', html)
        self.assertIn("var freeDelivery = false;", html)
        self.assertNotIn(">Free<", html.split('id="summary-shipping"')[1][:200])

    # ---- Shiprocket still works, but never prices ---------------------------
    def test_serviceability_check_still_uses_shiprocket_but_returns_no_price_or_choice(self):
        with mock.patch.object(shiprocket_client, "get_shipping_rates", return_value=COURIERS) as rates:
            data = self.client.get("/shipping/check-serviceability/?pincode=682001").json()
        self.assertEqual(rates.call_count, 1)  # the integration is still queried
        self.assertTrue(data["ok"] and data["is_serviceable"] and data["free_delivery"])
        self.assertEqual(data["shipping_charge"], 0)
        self.assertEqual(data["available_couriers"], [])
        self.assertEqual(data["etd"], "Sep 21, 2026")  # Shiprocket's recommended courier's estimate
        self.assertNotIn("shiprocket_shipping", self.client.session)

    def test_unserviceable_pincode_and_shiprocket_outage_still_behave(self):
        with mock.patch.object(
            shiprocket_client, "get_shipping_rates", return_value={"available_couriers": [], "recommended_courier_id": None}
        ):
            self.assertEqual(
                self.client.get("/shipping/check-serviceability/?pincode=999999").json(), {"ok": True, "is_serviceable": False}
            )
        cache.clear()
        with mock.patch.object(shiprocket_client, "get_shipping_rates", side_effect=ShiprocketAPIError("down")):
            data = self.client.get("/shipping/check-serviceability/?pincode=560001").json()
        self.assertFalse(data["ok"])
        self.assertTrue(data["retryable"])

    def test_courier_choice_is_refused_while_delivery_is_free(self):
        response = self.client.post("/shipping/select-courier/", {"courier_id": "1"}).json()
        self.assertFalse(response["ok"])

    def test_order_time_charge_is_zero_even_with_a_stale_quote_or_flat_rate(self):
        from shipping.rates import store_quote

        request = self.request_with_session()
        couriers = [dict(COURIERS["available_couriers"][0], tags=["cheapest"])]
        store_quote(request, pincode="682001", couriers=couriers, selected_id=6)
        self.assertEqual(resolve_order_shipping_charge(request, cart=self.cart(), pincode="682001"), Decimal("0.00"))

        site = get_site_settings()
        site.use_shiprocket_delivery_charge = False
        site.save()
        self.assertEqual(resolve_order_shipping_charge(request, cart=self.cart(), pincode="682001"), Decimal("0.00"))

    # ---- the order, the payment and the bill agree ------------------------------
    def test_order_total_excludes_delivery_even_if_a_charge_is_passed_in(self):
        order = self.place(override=Decimal("99.00"))
        self.assertEqual(order.delivery_charge, Decimal("0.00"))
        self.assertEqual(order.total_amount, order.subtotal - order.coupon_discount)
        self.assertEqual(order.total_amount, Decimal("100.00"))

    def test_order_total_includes_the_quoted_charge_when_delivery_is_charged(self):
        self.set_charging(True)
        order = self.place(override=Decimal("99.00"), key="k-charged")
        self.assertEqual(order.delivery_charge, Decimal("99.00"))
        self.assertEqual(order.total_amount, Decimal("199.00"))

    def test_payment_is_taken_for_exactly_the_order_total(self):
        from payments.services import process_payment

        order = self.place(override=Decimal("99.00"))
        asked = {}

        class Adapter:
            is_async = True

            def create_payment_intent(self, *, amount, currency, metadata):
                asked["amount"] = amount
                return mock.Mock(intent_id="intent-1")

        with mock.patch("payments.services.get_payment_adapter", return_value=Adapter()):
            payment = process_payment(order=order, gateway_key="fake", payment_data={})
        self.assertEqual(payment.amount, order.total_amount)
        self.assertEqual(asked["amount"], order.total_amount)
        self.assertEqual(asked["amount"], Decimal("100.00"))

    def test_order_page_and_bill_show_free_and_no_amount(self):
        order = self.place()
        page = self.client.get("/orders/%d/" % order.pk).content.decode()
        self.assertRegex(page, r"Delivery Fee</span>\s*<span><span class=\"text-success fw-semibold\">Free</span>")
        bill = self.client.get("/accounts/dashboard/orders/%d/invoice/" % order.pk).content.decode()
        self.assertRegex(bill, r"<td>Delivery Charge</td>\s*<td>Free</td>")

    def test_bill_shows_the_amount_when_a_charge_was_billed(self):
        self.set_charging(True)
        order = self.place(override=Decimal("99.00"), key="k-bill")
        bill = self.client.get("/accounts/dashboard/orders/%d/invoice/" % order.pk).content.decode()
        self.assertRegex(bill, r"<td>Delivery Charge</td>\s*<td>[^<]*99</td>")

    def test_shiprocket_booking_still_happens_with_zero_shipping_charges(self):
        order = self.place()
        with mock.patch.object(shiprocket_client, "_request", return_value={"order_id": 1}) as request:
            shiprocket_client.create_order(order, None)
        method, path = request.call_args.args[:2]
        self.assertEqual((method, path), ("POST", "/orders/create/adhoc"))
        self.assertEqual(request.call_args.kwargs["json"]["shipping_charges"], "0.00")


class DeliveryChargeSettingTests(TestCase):
    def test_vendor_can_switch_it_off_and_on_from_the_settings_page(self):
        admin = get_user_model().objects.create_superuser(username="adm", email="a@x.com", password="x")
        self.client.force_login(admin)
        page = self.client.get("/dashboard/settings/").content.decode()
        self.assertIn('name="charge_for_delivery"', page)
        self.assertIn("Charge customers for delivery", page)
        self.assertTrue(get_site_settings().charge_for_delivery)  # default: charged, nothing changes until switched

        from dashboard.forms import SiteSettingsForm

        site = get_site_settings()
        form = SiteSettingsForm({"site_name": "Z", "primary_color": "#000000", "secondary_color": "#111111",
                                 "font_family": "Inter", "default_shipping_charge": "50", "tax_rate_percent": "0",
                                 "active_payment_gateway": "razorpay", "shiprocket_pickup_location": "x"}, instance=site)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertFalse(get_site_settings().charge_for_delivery)  # unticked box = free delivery
