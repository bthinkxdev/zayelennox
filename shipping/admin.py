"""Django admin registrations for the shipping app."""

from __future__ import annotations

from django.contrib import admin, messages

from shipping.exceptions import ShiprocketAPIError
from shipping.models import Shipment
from shipping.services import cancel_shipment, create_shipment_for_order, refresh_tracking


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    """Admin interface for Shiprocket shipments, with manual lifecycle actions."""

    list_display = (
        "order",
        "current_status",
        "awb_code",
        "courier_name",
        "is_cancelled",
        "updated_at",
    )
    list_filter = ("current_status", "is_cancelled")
    search_fields = ("order__order_number", "awb_code", "shiprocket_order_id", "shiprocket_shipment_id")
    list_select_related = ("order",)
    readonly_fields = (
        "shiprocket_order_id",
        "shiprocket_shipment_id",
        "awb_code",
        "courier_name",
        "label_url",
        "tracking_data",
        "error_log",
    )
    raw_id_fields = ("order",)
    actions = ["action_create_or_recreate_shipment", "action_cancel_shipment", "action_refresh_tracking"]

    @admin.action(description="Create / recreate shipment in Shiprocket")
    def action_create_or_recreate_shipment(self, request, queryset):
        for shipment in queryset:
            try:
                create_shipment_for_order(shipment.order, shipment)
                self.message_user(
                    request, f"Shipment created for {shipment.order.order_number}.", level=messages.SUCCESS
                )
            except ShiprocketAPIError as exc:
                self.message_user(
                    request,
                    f"Failed to create shipment for {shipment.order.order_number}: {exc}",
                    level=messages.ERROR,
                )

    @admin.action(description="Cancel shipment in Shiprocket")
    def action_cancel_shipment(self, request, queryset):
        for shipment in queryset:
            try:
                cancel_shipment(shipment)
                self.message_user(
                    request, f"Shipment cancelled for {shipment.order.order_number}.", level=messages.SUCCESS
                )
            except ShiprocketAPIError as exc:
                self.message_user(
                    request,
                    f"Failed to cancel shipment for {shipment.order.order_number}: {exc}",
                    level=messages.ERROR,
                )

    @admin.action(description="Refresh tracking from Shiprocket")
    def action_refresh_tracking(self, request, queryset):
        for shipment in queryset:
            try:
                refresh_tracking(shipment)
                self.message_user(
                    request, f"Tracking refreshed for {shipment.order.order_number}.", level=messages.SUCCESS
                )
            except ShiprocketAPIError as exc:
                self.message_user(
                    request,
                    f"Failed to refresh tracking for {shipment.order.order_number}: {exc}",
                    level=messages.ERROR,
                )
