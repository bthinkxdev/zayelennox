"""Cart: a combo is one unit (grouped display, whole-combo quantity/remove), separate from plain products."""

from __future__ import annotations

import re
from decimal import Decimal

from django.test import TestCase

from cart.models import Cart, CartItem
from cart.selectors import combo_units, get_cart_product_ids, get_cart_summary
from cart.services import add_combo_to_cart, add_to_cart, change_combo_quantity, merge_carts
from catalog.models import Category, Combo, ComboItem, Product
from core.models import Currency


class CartComboTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Cat", slug="cat")
        self.a = Product.objects.create(
            name="Alpha", slug="alpha", category=category, base_price=Decimal("100"), hsn_code="1001",
            gst_rate_percent=Decimal("5"), stock_quantity=20,
        )
        self.b = Product.objects.create(
            name="Beta", slug="beta", category=category, base_price=Decimal("300"), hsn_code="2002",
            gst_rate_percent=Decimal("18"), stock_quantity=20,
        )
        self.combo = Combo.objects.create(name="Duo Pack", slug="duo-pack", combo_price=Decimal("320"))
        ComboItem.objects.create(combo=self.combo, product=self.a, quantity=1)
        ComboItem.objects.create(combo=self.combo, product=self.b, quantity=2)
        currency = Currency.objects.filter(is_default=True).first() or Currency.objects.first()
        self.cart = Cart.objects.create(session_key="s-1", currency=currency)

    # ---- grouping -------------------------------------------------------
    def test_combo_lines_collapse_into_one_block_and_plain_lines_stay_separate(self):
        add_to_cart(cart=self.cart, product=self.a, quantity=2)  # plain Alpha
        add_combo_to_cart(cart=self.cart, combo=self.combo, quantity=2)

        summary = get_cart_summary(cart=self.cart)
        self.assertEqual(len(summary.lines), 3)  # plain Alpha + 2 combo components
        self.assertEqual([b.is_combo for b in summary.blocks], [False, True])

        block = summary.blocks[1]
        self.assertEqual(block.name, "Duo Pack")
        self.assertEqual(block.units, 2)
        self.assertEqual([line.quantity for line in block.lines], [2, 4])  # 1×2 and 2×2
        self.assertEqual(block.total, Decimal("640.00"))  # 2 × combo price
        # normal price per combo = 100 + 2×300 = 700 → 1400 for two, vs 640 charged
        self.assertEqual(block.savings, Decimal("760.00"))

    def test_plain_product_is_never_a_combo(self):
        add_to_cart(cart=self.cart, product=self.a, quantity=1)
        (block,) = get_cart_summary(cart=self.cart).blocks
        self.assertFalse(block.is_combo)
        self.assertEqual(block.combo_name_snapshot, "")

    def test_units_is_none_when_combo_was_edited_after_adding(self):
        add_combo_to_cart(cart=self.cart, combo=self.combo, quantity=1)
        ComboItem.objects.filter(combo=self.combo, product=self.b).update(quantity=3)
        (block,) = get_cart_summary(cart=self.cart).blocks
        self.assertTrue(block.is_combo)
        self.assertIsNone(block.units)
        self.assertIsNone(block.normal_total)

    def test_combo_units_needs_every_component_at_one_whole_multiple(self):
        add_combo_to_cart(cart=self.cart, combo=self.combo, quantity=3)
        items = list(CartItem.objects.filter(cart=self.cart))
        combo_items = list(self.combo.items.all())
        self.assertEqual(combo_units(items=items, combo_items=combo_items), 3)
        self.assertIsNone(combo_units(items=items[:1], combo_items=combo_items))

    def test_deleted_combo_leaves_ordinary_lines(self):
        add_combo_to_cart(cart=self.cart, combo=self.combo, quantity=1)
        self.combo.delete()
        summary = get_cart_summary(cart=self.cart)
        self.assertTrue(all(not b.is_combo for b in summary.blocks))
        self.assertEqual(len(summary.blocks), 2)

    def test_product_only_in_cart_via_a_combo_is_not_counted_as_in_cart(self):
        add_combo_to_cart(cart=self.cart, combo=self.combo, quantity=1)
        self.assertEqual(get_cart_product_ids_for(self.cart), set())
        add_to_cart(cart=self.cart, product=self.a, quantity=1)
        self.assertEqual(get_cart_product_ids_for(self.cart), {self.a.pk})

    def test_combo_is_charged_exactly_its_price_for_any_quantity(self):
        """No paisa drift: N combos cost exactly N × combo price whenever a component has quantity 1."""
        for price in ("99.99", "100.01", "320.00", "333.33", "0.07"):
            for units in (1, 2, 3, 5, 7):
                Combo.objects.filter(pk=self.combo.pk).update(combo_price=Decimal(price))
                CartItem.objects.filter(cart=self.cart).delete()
                add_combo_to_cart(cart=self.cart, combo=Combo.objects.get(pk=self.combo.pk), quantity=units)
                (block,) = get_cart_summary(cart=self.cart).blocks
                self.assertEqual(block.total, Decimal(price) * units, (price, units))

    def test_allocation_is_exact_or_within_the_smallest_quantity_when_no_component_is_single(self):
        from cart.services import _allocate_combo_price

        for quantities in ([2, 2], [3, 2], [2, 4], [3, 3]):
            for price in (10001, 9999, 33333, 12345):
                units = _allocate_combo_price(
                    normal_totals=[Decimal("100") * q for q in quantities], per_combo_quantities=quantities, price_paise=price
                )
                drift = price - sum(u * q for u, q in zip(units, quantities))
                self.assertLess(abs(drift), min(quantities), (quantities, price, units, drift))

    # ---- quantity -------------------------------------------------------
    def test_change_combo_quantity_scales_the_whole_combo(self):
        add_combo_to_cart(cart=self.cart, combo=self.combo, quantity=1)
        self.assertEqual(change_combo_quantity(cart=self.cart, combo_id=self.combo.pk, delta=1), 2)
        (block,) = get_cart_summary(cart=self.cart).blocks
        self.assertEqual((block.units, block.total), (2, Decimal("640.00")))
        self.assertEqual(change_combo_quantity(cart=self.cart, combo_id=self.combo.pk, delta=-1), 1)
        self.assertEqual(get_cart_summary(cart=self.cart).blocks[0].total, Decimal("320.00"))

    def test_change_combo_quantity_never_goes_below_one(self):
        add_combo_to_cart(cart=self.cart, combo=self.combo, quantity=1)
        self.assertEqual(change_combo_quantity(cart=self.cart, combo_id=self.combo.pk, delta=-1), 1)
        self.assertEqual(CartItem.objects.filter(cart=self.cart).count(), 2)

    def test_failed_resize_leaves_the_cart_exactly_as_it_was(self):
        from cart.exceptions import InsufficientStockError

        add_combo_to_cart(cart=self.cart, combo=self.combo, quantity=1)
        before = sorted(CartItem.objects.filter(cart=self.cart).values_list("product_id", "quantity", "unit_price_at_add"))
        Product.objects.filter(pk=self.b.pk).update(stock_quantity=3)  # room for 1 combo (2 of Beta), not 2 (4)
        with self.assertRaises(InsufficientStockError):
            change_combo_quantity(cart=self.cart, combo_id=self.combo.pk, delta=1)
        after = sorted(CartItem.objects.filter(cart=self.cart).values_list("product_id", "quantity", "unit_price_at_add"))
        self.assertEqual(before, after)

    def test_cannot_resize_an_inactive_or_edited_combo(self):
        from cart.exceptions import ComboLineNotAdjustableError

        add_combo_to_cart(cart=self.cart, combo=self.combo, quantity=1)
        ComboItem.objects.filter(combo=self.combo, product=self.b).update(quantity=3)
        with self.assertRaises(ComboLineNotAdjustableError):
            change_combo_quantity(cart=self.cart, combo_id=self.combo.pk, delta=1)
        ComboItem.objects.filter(combo=self.combo, product=self.b).update(quantity=2)
        Combo.objects.filter(pk=self.combo.pk).update(is_active=False)
        with self.assertRaises(ComboLineNotAdjustableError):
            change_combo_quantity(cart=self.cart, combo_id=self.combo.pk, delta=1)

    # ---- merge ----------------------------------------------------------
    def test_guest_plain_product_is_not_absorbed_into_a_combo_line_on_merge(self):
        from accounts.models import CustomerProfile
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(username="u", email="u@x.com", password="x")
        currency = self.cart.currency
        profile = CustomerProfile.objects.create(user=user, preferred_currency=currency)
        user_cart = Cart.objects.create(customer_profile=profile, currency=currency)
        add_combo_to_cart(cart=user_cart, combo=self.combo, quantity=1)  # includes Alpha ×1
        add_to_cart(cart=self.cart, product=self.a, quantity=2)  # guest's plain Alpha ×2

        merge_carts(guest_cart=self.cart, user_profile=profile)

        alpha_lines = CartItem.objects.filter(cart=user_cart, product=self.a)
        self.assertEqual(sorted((i.combo_id is not None, i.quantity) for i in alpha_lines), [(False, 2), (True, 1)])
        self.assertEqual(get_cart_summary(cart=user_cart).blocks[0].units, 1)  # combo unchanged


def get_cart_product_ids_for(cart):
    """get_cart_product_ids takes a request; exercise the same query through a stub request."""
    from django.test import RequestFactory
    from django.contrib.sessions.backends.db import SessionStore

    request = RequestFactory().get("/")
    request.session = SessionStore()
    request.session.create()
    request.session.save()
    Cart.objects.filter(pk=cart.pk).update(session_key=request.session.session_key)
    from django.contrib.auth.models import AnonymousUser

    request.user = AnonymousUser()
    return get_cart_product_ids(request=request)


class CartComboPageTests(TestCase):
    """The rendered cart page and sidebar cart."""

    def setUp(self):
        category = Category.objects.create(name="Cat", slug="cat")
        self.a = Product.objects.create(
            name="Alpha", slug="alpha", category=category, base_price=Decimal("100"), hsn_code="1001", stock_quantity=20
        )
        self.b = Product.objects.create(
            name="Beta", slug="beta", category=category, base_price=Decimal("300"), hsn_code="2002", stock_quantity=20
        )
        self.plain = Product.objects.create(
            name="Plain", slug="plain", category=category, base_price=Decimal("50"), hsn_code="3003", stock_quantity=20
        )
        self.combo = Combo.objects.create(name="Duo Pack", slug="duo-pack", combo_price=Decimal("320"))
        ComboItem.objects.create(combo=self.combo, product=self.a, quantity=1)
        ComboItem.objects.create(combo=self.combo, product=self.b, quantity=1)
        self.client.post("/cart/add/", {"product_id": self.plain.pk, "quantity": 1})
        self.client.post("/cart/combo/add/", {"combo_id": self.combo.pk, "quantity": 1})

    def surfaces(self):
        return {"page": self.client.get("/cart/").content.decode(), "drawer": self.client.get("/cart/drawer/").content.decode()}

    def test_one_combo_card_with_one_remove_and_one_stepper(self):
        for name, html in self.surfaces().items():
            self.assertEqual(html.count('<article class="cart-combo'), 1, name)
            self.assertEqual(len(re.findall(r'name="combo_id"[^>]*>\s*<input type="hidden" name="is_drawer"[^>]*>\s*<button class="cart-combo__remove"', html)), 1, name)
            self.assertEqual(html.count("Remove combo"), 2, name)  # visible label + aria-label, one button
            self.assertEqual(html.count("/cart/combo/quantity/"), 4, name)  # −/+ form action + hx-post
            self.assertIn("Duo Pack", html)
            self.assertIn("Alpha", html)
            self.assertIn("Beta", html)

    def test_plain_product_row_has_its_own_stepper_and_delete_and_no_combo_wording(self):
        html = self.surfaces()["page"]
        plain_row = html[html.index("Plain"):]
        plain_row = plain_row[: plain_row.index("</li>")]
        self.assertIn("/cart/quantity/", plain_row)
        self.assertNotIn("combo", plain_row.lower())

    def test_combo_stepper_and_remove_work_over_http(self):
        self.client.post("/cart/combo/quantity/", {"combo_id": self.combo.pk, "delta": 1})
        self.assertEqual(CartItem.objects.filter(combo=self.combo).count(), 2)
        self.assertEqual(CartItem.objects.get(combo=self.combo, product=self.a).quantity, 2)
        self.client.post("/cart/combo/remove/", {"combo_id": self.combo.pk})
        self.assertFalse(CartItem.objects.filter(combo=self.combo).exists())
        self.assertTrue(CartItem.objects.filter(product=self.plain).exists())

    def test_junk_combo_ids_never_crash(self):
        for path in ("/cart/combo/remove/", "/cart/combo/quantity/"):
            for value in ("", "abc", "0", "-1"):
                response = self.client.post(path, {"combo_id": value, "delta": 1})
                self.assertEqual(response.status_code, 200, (path, value))
        self.assertTrue(CartItem.objects.filter(combo=self.combo).exists())
        self.assertEqual(self.client.post("/cart/combo/add/", {"combo_id": "abc"}).status_code, 404)

    def test_resize_error_is_shown_on_the_combo_card(self):
        Product.objects.filter(pk=self.b.pk).update(stock_quantity=1)
        html = self.client.post(
            "/cart/combo/quantity/", {"combo_id": self.combo.pk, "delta": 1, "is_drawer": "0"}
        ).content.decode()
        self.assertIn('class="cart-combo__error"', html)
        self.assertIn("Only 1 items available in stock.", html)
        self.assertEqual(CartItem.objects.get(combo=self.combo, product=self.b).quantity, 1)

    def test_checkout_summary_shows_one_combo_header_with_each_products_tax(self):
        html = self.client.get("/checkout/").content.decode()
        self.assertEqual(html.count('class="sum-combo"'), 1)
        self.assertIn("HSN 1001", html)
        self.assertIn("HSN 2002", html)
        self.assertNotIn("Part of combo", html)
