"""Shipping application configuration."""

from __future__ import annotations

from django.apps import AppConfig


class ShippingConfig(AppConfig):
    """Django app config for courier integration (Shiprocket) and shipment tracking."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "shipping"
    verbose_name = "Shipping"

    def ready(self) -> None:
        """Import signal modules when Django starts."""
        import shipping.signals  # noqa: F401
