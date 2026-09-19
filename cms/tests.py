"""Homepage combos: the "Combos" tile beside the categories and the combos section."""

from __future__ import annotations

from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from catalog.models import Category, Combo, ComboItem, Product
from catalog.selectors import get_combos_teaser
from cms.models import HomepageSection


class HomepageCombosTests(TestCase):
    def setUp(self):
        cache.clear()
        HomepageSection.objects.create(section_type="shop_by_category", display_order=1)
        HomepageSection.objects.create(section_type="combos", title="Combos", display_order=2)
        category = Category.objects.create(name="Hair", slug="hair")
        self.product = Product.objects.create(
            name="Oil", slug="oil", category=category, base_price=Decimal("100"), hsn_code="1001", stock_quantity=5
        )

    def make_combo(self, **kw):
        combo = Combo.objects.create(name="Duo", slug="duo", combo_price=Decimal("150"), **kw)
        ComboItem.objects.create(combo=combo, product=self.product, quantity=1)
        return combo

    def test_no_teaser_and_no_section_without_active_combos(self):
        self.assertIsNone(get_combos_teaser())
        cache.clear()
        html = self.client.get("/").content.decode()
        self.assertNotIn("jm-cat-arch--combos", html)
        self.assertNotIn("Previous combos", html)

    def test_inactive_combo_is_not_shown(self):
        self.make_combo(is_active=False)
        self.assertIsNone(get_combos_teaser())

    def test_active_combo_adds_tile_and_section(self):
        self.make_combo(is_active=True)
        self.assertEqual(get_combos_teaser(), {"cover": ""})
        cache.clear()
        html = self.client.get("/").content.decode()
        self.assertIn('href="/shop/combos/" class="jm-cat-arch jm-cat-arch--combos', html)
        self.assertIn("Previous combos", html)
        self.assertIn("Duo", html)
