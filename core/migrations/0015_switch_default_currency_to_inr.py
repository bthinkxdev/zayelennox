"""
Switch the storefront's default currency from AED to INR.

Renames the existing default Currency row in place (same PK) rather than
creating a new one, so every FK that already points at it — SiteSettings,
Orders, Carts, PaymentTransactions — automatically becomes INR without any
data touched on those rows. Existing product prices are plain decimals with
no currency conversion applied (exchange_rate_to_base stays 1.00), so this
is a pure relabeling: numbers on existing products don't change.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import migrations


def switch_to_inr(apps, schema_editor) -> None:
    Currency = apps.get_model("core", "Currency")
    SiteSettings = apps.get_model("core", "SiteSettings")

    default_currency = Currency.objects.filter(is_default=True).first()

    if default_currency is not None:
        Currency.objects.filter(pk=default_currency.pk).update(
            code="INR",
            symbol="₹",
            is_active=True,
            is_default=True,
        )
        inr = Currency.objects.get(pk=default_currency.pk)
    else:
        inr, _ = Currency.objects.update_or_create(
            code="INR",
            defaults={
                "symbol": "₹",
                "exchange_rate_to_base": Decimal("1.00000000"),
                "is_default": True,
                "is_active": True,
            },
        )

    # Make sure INR is the only active/default currency on the storefront.
    Currency.objects.exclude(pk=inr.pk).update(is_default=False, is_active=False)

    SiteSettings.objects.update_or_create(
        pk=1,
        defaults={"default_currency": inr},
    )

    # Bust the 5-minute default-currency cache so the change is visible immediately.
    try:
        from django.core.cache import cache

        cache.delete("core:default_currency:v1")
    except Exception:
        pass


def noop_reverse(apps, schema_editor) -> None:
    """Not reversible — we don't know the original AED symbol/state to restore."""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_remove_contactinquiry_product_and_more"),
    ]

    operations = [
        migrations.RunPython(switch_to_inr, noop_reverse),
    ]
