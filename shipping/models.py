"""Data layer for the shipping app — models only, no business logic."""

from __future__ import annotations

from django.db import models

from core.models import TimeStampedModel


class Shipment(TimeStampedModel):
    """
    Outbound courier shipment for an order (Shiprocket integration).

    Kept separate from Order for clearer lifecycle and error handling —
    an order can exist without ever successfully getting a shipment.
    """

    class Status(models.TextChoices):
        PENDING_CREATION = "pending_creation", "Pending creation"
        CREATED = "created", "Created"
        AWB_ASSIGNED = "awb_assigned", "AWB assigned"
        PICKUP_SCHEDULED = "pickup_scheduled", "Pickup scheduled"
        LABEL_GENERATED = "label_generated", "Label generated"
        IN_TRANSIT = "in_transit", "In transit"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"
        ERROR = "error", "Error"

    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="shipment",
        verbose_name="Order",
    )
    shiprocket_order_id = models.CharField(max_length=100, blank=True, verbose_name="Shiprocket order ID")
    shiprocket_shipment_id = models.CharField(max_length=100, blank=True, verbose_name="Shiprocket shipment ID")
    awb_code = models.CharField(max_length=100, blank=True, db_index=True, verbose_name="AWB code")
    courier_name = models.CharField(max_length=100, blank=True, verbose_name="Courier name")
    label_url = models.URLField(blank=True, verbose_name="Label URL")
    current_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_CREATION,
        db_index=True,
        verbose_name="Current status",
    )
    tracking_data = models.JSONField(default=dict, blank=True, verbose_name="Tracking data")
    is_cancelled = models.BooleanField(default=False, db_index=True, verbose_name="Is cancelled")
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="Cancelled at")
    error_log = models.TextField(blank=True, verbose_name="Error log")

    class Meta:
        verbose_name = "Shipment"
        verbose_name_plural = "Shipments"
        indexes = [
            models.Index(fields=["awb_code"], name="shp_shipment_awb_idx"),
            models.Index(fields=["shiprocket_order_id"], name="shp_shipment_sr_order_idx"),
            models.Index(fields=["shiprocket_shipment_id"], name="shp_shipment_sr_ship_idx"),
            models.Index(fields=["is_cancelled"], name="shp_shipment_cancelled_idx"),
        ]

    def __str__(self) -> str:
        return f"Shipment for {self.order.order_number}"
