"""Django admin registrations for the orders app."""

from __future__ import annotations

from django.contrib import admin, messages

from orders.models import Order, OrderItem, OrderStatusHistory, ProofOfDelivery
from orders.services import transition_order_status


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "changed_at", "note")
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "customer_profile",
        "order_status",
        "total_amount",
        "shipment_status",
        "created_at",
    )
    list_filter = ("order_status",)
    inlines = [OrderItemInline, OrderStatusHistoryInline]
    actions = ["action_create_shiprocket_shipment"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("shipment")

    def save_model(self, request, obj, form, change) -> None:
        if change:
            existing = Order.objects.filter(pk=obj.pk).first()
            if existing and existing.order_status != obj.order_status:
                transition_order_status(
                    order=existing,
                    new_status=obj.order_status,
                    actor=request.user,
                    note="Updated via Django admin.",
                )
                return
        super().save_model(request, obj, form, change)

    @admin.display(description="Shipment")
    def shipment_status(self, obj) -> str:
        shipment = getattr(obj, "shipment", None)
        if shipment is None:
            return "—"
        return f"{shipment.get_current_status_display()}" + (f" ({shipment.awb_code})" if shipment.awb_code else "")

    @admin.action(description="Create / recreate shipment in Shiprocket")
    def action_create_shiprocket_shipment(self, request, queryset):
        from shipping.exceptions import ShiprocketAPIError
        from shipping.models import Shipment
        from shipping.services import create_shipment_for_order

        for order in queryset:
            shipment, _ = Shipment.objects.get_or_create(order=order)
            try:
                create_shipment_for_order(order, shipment)
                self.message_user(request, f"Shipment created for {order.order_number}.", level=messages.SUCCESS)
            except ShiprocketAPIError as exc:
                self.message_user(
                    request, f"Failed to create shipment for {order.order_number}: {exc}", level=messages.ERROR
                )


@admin.register(ProofOfDelivery)
class ProofOfDeliveryAdmin(admin.ModelAdmin):
    list_display = ("order", "recipient_name", "delivered_at")
