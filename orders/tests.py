"""Bill numbers: sequential per financial year, and findable from the dashboard."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import Currency
from core.services import get_site_settings
from orders.models import Order, OrderNumberSequence
from orders.selectors import bill_number_filter
from orders.services import financial_year_series, generate_order_number


def make_order(number: str, **kwargs) -> Order:
    currency = Currency.objects.filter(is_default=True).first() or Currency.objects.first()
    return Order.objects.create(order_number=number, total_amount=Decimal("100"), currency=currency, **kwargs)


class BillNumberTests(TestCase):
    def test_financial_year_runs_april_to_march(self):
        self.assertEqual(financial_year_series(date(2026, 4, 1)), "2627")
        self.assertEqual(financial_year_series(date(2027, 3, 31)), "2627")
        self.assertEqual(financial_year_series(date(2027, 4, 1)), "2728")
        self.assertEqual(financial_year_series(date(2026, 3, 31)), "2526")
        self.assertEqual(financial_year_series(date(2099, 12, 31)), "9900")

    def test_numbers_are_sequential_readable_and_within_the_gst_length_limit(self):
        numbers = [generate_order_number(on=date(2026, 9, 19)) for _ in range(3)]
        self.assertEqual(numbers, ["ZYL-2627-00001", "ZYL-2627-00002", "ZYL-2627-00003"])
        self.assertLessEqual(len(numbers[0]), 16)

    def test_numbering_restarts_each_financial_year_and_years_do_not_interfere(self):
        self.assertEqual(generate_order_number(on=date(2027, 3, 31)), "ZYL-2627-00001")
        self.assertEqual(generate_order_number(on=date(2027, 4, 1)), "ZYL-2728-00001")
        self.assertEqual(generate_order_number(on=date(2027, 3, 31)), "ZYL-2627-00002")
        self.assertEqual(generate_order_number(on=date(2027, 4, 2)), "ZYL-2728-00002")

    def test_number_grows_past_five_digits_instead_of_wrapping(self):
        OrderNumberSequence.objects.create(series="2627", last_number=99999)
        self.assertEqual(generate_order_number(on=date(2026, 9, 19)), "ZYL-2627-100000")

    def test_a_rolled_back_order_does_not_use_up_a_number(self):
        try:
            with transaction.atomic():
                self.assertEqual(generate_order_number(on=date(2026, 9, 19)), "ZYL-2627-00001")
                raise RuntimeError("order creation failed")
        except RuntimeError:
            pass
        self.assertEqual(generate_order_number(on=date(2026, 9, 19)), "ZYL-2627-00001")

    def test_issued_numbers_are_unique_orders(self):
        make_order(generate_order_number())
        make_order(generate_order_number())
        self.assertEqual(Order.objects.values("order_number").distinct().count(), 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_order(Order.objects.first().order_number)


class BillNumberSearchTests(TestCase):
    def setUp(self):
        self.a = make_order("ZYL-2627-00012")
        self.b = make_order("ZYL-2627-00120")
        self.c = make_order("ZYL-2728-00012")
        self.old = make_order("ZYL-A12B34C56D78")  # an older random-style number
        self.big = make_order("ZYL-2728-02627")

    def find(self, query, field="order_number"):
        return set(Order.objects.filter(bill_number_filter(query, field=field)).values_list("order_number", flat=True))

    def test_sequence_digits_only_find_that_number_in_every_year(self):
        self.assertEqual(self.find("12"), {"ZYL-2627-00012", "ZYL-2728-00012"})
        self.assertEqual(self.find("00012"), {"ZYL-2627-00012", "ZYL-2728-00012"})
        self.assertEqual(self.find("120"), {"ZYL-2627-00120"})

    def test_full_number_matches_however_it_is_typed(self):
        for typed in ("ZYL-2627-00012", "zyl-2627-00012", "ZYL262700012", "zyl 2627 00012", "2627-00012", "262700012"):
            self.assertEqual(self.find(typed), {"ZYL-2627-00012"}, typed)

    def test_partial_numbers_and_old_random_numbers_still_match(self):
        # four digits: bill no. 2627 *or* the 2627 financial year
        self.assertEqual(self.find("2627"), {"ZYL-2627-00012", "ZYL-2627-00120", "ZYL-2728-02627"})
        self.assertEqual(self.find("2627-"), {"ZYL-2627-00012", "ZYL-2627-00120"})
        self.assertEqual(self.find("a12b"), {"ZYL-A12B34C56D78"})
        self.assertEqual(self.find("ZYL-2728"), {"ZYL-2728-00012", "ZYL-2728-02627"})

    def test_no_match_returns_nothing(self):
        self.assertEqual(self.find("99999"), set())
        self.assertEqual(self.find("ZYL-3000-00001"), set())


class DashboardBillPageTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="adm", email="a@x.com", password="x")
        self.client.force_login(self.admin)
        self.order = make_order("ZYL-2627-00007")
        make_order("ZYL-2627-00008")

    def test_dashboard_search_finds_the_bill_by_number_and_by_bare_digits(self):
        from payments.models import PaymentStatus, PaymentTransaction

        for order in Order.objects.all():
            PaymentTransaction.objects.create(
                order=order, gateway_key="cod", status=PaymentStatus.SUCCESS, amount=Decimal("100"),
                currency=order.currency,
            )
        for query in ("ZYL-2627-00007", "zyl262700007", "7"):
            html = self.client.get("/dashboard/orders/", {"q": query}).content.decode()
            self.assertIn("ZYL-2627-00007", html, query)
            self.assertNotIn("ZYL-2627-00008", html, query)
            html = self.client.get("/dashboard/payment/", {"q": query}).content.decode()
            self.assertIn("ZYL-2627-00007", html, f"payments: {query}")
            self.assertNotIn("ZYL-2627-00008", html, f"payments: {query}")

    def _invoice(self):
        return self.client.get(f"/dashboard/orders/{self.order.pk}/invoice/").content.decode()

    def test_invoice_shows_bill_number_and_shop_address_when_switched_on(self):
        site = get_site_settings()
        site.shop_address = "12 MG Road\nKochi 682001"
        site.show_shop_address_on_invoice = True
        site.save()
        html = self._invoice()
        self.assertIn("Bill No: ZYL-2627-00007", html)
        self.assertIn("12 MG Road<br>Kochi 682001", html)

    def test_shop_address_is_left_off_the_bill_when_switched_off(self):
        site = get_site_settings()
        site.shop_address = "12 MG Road\nKochi 682001"
        site.show_shop_address_on_invoice = False
        site.save()
        html = self._invoice()
        self.assertNotIn("12 MG Road", html)
        self.assertIn("Bill No: ZYL-2627-00007", html)

    def test_settings_page_offers_the_switch(self):
        html = self.client.get("/dashboard/settings/").content.decode()
        self.assertIn('name="show_shop_address_on_invoice"', html)
        self.assertIn("Show shop address on bills", html)
