"""URL routes for the shipping app."""

from __future__ import annotations

from django.urls import path

from shipping.views import check_serviceability_view
from shipping.webhook_views import ShiprocketWebhookView

app_name = "shipping"

urlpatterns = [
    path("webhooks/shiprocket/", ShiprocketWebhookView.as_view(), name="shiprocket-webhook"),
    path("check-serviceability/", check_serviceability_view, name="check-serviceability"),
]
