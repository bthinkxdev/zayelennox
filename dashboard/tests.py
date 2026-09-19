"""Tests for the dashboard app.

Access control, CRUD flows, and report views are exercised here. Add cases
under a tests/ package as coverage grows (see scripts/scaffold_apps.py).
"""

from __future__ import annotations

import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from catalog.models import Category, Combo, ComboItem, Product, ProductVariant
from dashboard.forms import CategoryForm


def _png() -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    return SimpleUploadedFile("t.png", buffer.getvalue(), content_type="image/png")


class ComboFormFeedbackTests(TestCase):
    """A combo that can't be saved must say why on the page; one that shouldn't be saved must not be."""

    URL = "/dashboard/combo/create/"

    def setUp(self):
        admin = get_user_model().objects.create_superuser(username="adm", email="a@x.com", password="x")
        self.client.force_login(admin)
        category = Category.objects.create(name="Cat", slug="cat")

        def product(name, slug):
            return Product.objects.create(
                name=name, slug=slug, category=category, base_price=Decimal("100"), hsn_code="1001", stock_quantity=9
            )

        self.p1, self.p2, self.with_variants = product("P1", "p1"), product("P2", "p2"), product("PV", "pv")
        ProductVariant.objects.create(product=self.with_variants, variant_type="size", name="L", sku_suffix="L", stock_quantity=5)
        self.p2_variant = ProductVariant.objects.create(
            product=self.p2, variant_type="size", name="XL", sku_suffix="XL", stock_quantity=5
        )
        self.good_rows = [
            {"product": self.p1.pk, "variant": "", "quantity": "1"},
            {"product": Product.objects.create(
                name="P3", slug="p3", category=category, base_price=Decimal("50"), hsn_code="1001", stock_quantity=9
            ).pk, "variant": "", "quantity": "1"},
        ]

    def submit(self, *, name="Duo", slug="", price="320", items=None, images=()):
        data = {"name": name, "slug": slug, "description": "", "combo_price": price, "is_active": "on", "display_order": "0"}
        for prefix, rows in (("comboitems", self.good_rows if items is None else items), ("images", images), ("documents", ())):
            data.update({f"{prefix}-TOTAL_FORMS": str(len(rows)), f"{prefix}-INITIAL_FORMS": "0",
                         f"{prefix}-MIN_NUM_FORMS": "0", f"{prefix}-MAX_NUM_FORMS": "1000"})
            for i, row in enumerate(rows):
                data.update({f"{prefix}-{i}-{key}": value for key, value in row.items()})
        return self.client.post(self.URL, data)

    def assertRejectedWith(self, response, message):
        self.assertEqual(response.status_code, 200, "expected the form to be shown again, not saved")
        self.assertContains(response, message)
        self.assertFalse(Combo.objects.exists())

    def test_valid_combo_saves(self):
        self.assertEqual(self.submit().status_code, 302)
        self.assertEqual(Combo.objects.get().items.count(), 2)

    def test_variant_of_another_product_is_explained(self):
        rows = [{"product": self.p1.pk, "variant": self.p2_variant.pk, "quantity": "1"}, self.good_rows[1]]
        self.assertRejectedWith(self.submit(items=rows), "This variant does not belong to the selected product.")

    def test_product_with_variants_needs_one_chosen_and_says_so(self):
        rows = [{"product": self.with_variants.pk, "variant": "", "quantity": "1"}, self.good_rows[1]]
        self.assertRejectedWith(self.submit(items=rows), "pick one")

    def test_the_same_product_twice_is_rejected_not_saved_twice(self):
        response = self.submit(items=[self.good_rows[0], self.good_rows[0]])
        self.assertRejectedWith(response, "This product is already in the combo")

    def test_same_product_in_two_different_variants_is_allowed(self):
        other_variant = ProductVariant.objects.create(
            product=self.p2, variant_type="size", name="XXL", sku_suffix="XXL", stock_quantity=5
        )
        rows = [
            {"product": self.p2.pk, "variant": self.p2_variant.pk, "quantity": "1"},
            {"product": self.p2.pk, "variant": other_variant.pk, "quantity": "1"},
        ]
        self.assertEqual(self.submit(items=rows).status_code, 302)

    def test_a_name_with_no_letters_or_numbers_cannot_produce_an_empty_slug(self):
        self.assertRejectedWith(self.submit(name="!!!"), "no letters or numbers")

    def test_two_primary_images_are_rejected(self):
        images = [
            {"image": _png(), "alt_text": "", "display_order": "0", "is_primary": "on"},
            {"image": _png(), "alt_text": "", "display_order": "1", "is_primary": "on"},
        ]
        self.assertRejectedWith(self.submit(images=images), "Mark only one image as the primary image.")

    def test_combo_list_shows_when_a_combo_can_not_be_bought(self):
        combo = Combo.objects.create(name="Pack", slug="pack", combo_price=Decimal("90"))
        ComboItem.objects.create(combo=combo, product=self.p1, quantity=1)
        page = self.client.get("/dashboard/combo/").content.decode()
        self.assertIn("Sellable now", page)
        Product.objects.filter(pk=self.p1.pk).update(is_active=False)
        self.assertFalse(Combo.objects.get(pk=combo.pk).is_available)
        self.assertIn("bg-secondary-subtle", self.client.get("/dashboard/combo/").content.decode())


class SlugAutoMixinTests(TestCase):
    def test_other_dashboard_forms_also_refuse_an_empty_generated_slug(self):
        form = CategoryForm({"name": "???", "slug": "", "display_order": 0, "is_active": "on"})
        self.assertFalse(form.is_valid())
        self.assertIn("slug", form.errors)
