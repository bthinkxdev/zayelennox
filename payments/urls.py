"""URL routing for the payments app."""

from __future__ import annotations

from django.urls import path

from payments import views

app_name = "payments"

urlpatterns = [
    # Must precede the generic <str:gateway_key> catch-all below, which would
    # otherwise match "razorpay"/"payu" as a gateway_key and shadow these routes.
    path("webhooks/razorpay/", views.razorpay_webhook_view, name="razorpay-webhook"),
    path("webhooks/payu/", views.payu_webhook_view, name="payu-webhook"),
    path("webhooks/<str:gateway_key>/", views.payment_webhook_view, name="webhook"),
]
