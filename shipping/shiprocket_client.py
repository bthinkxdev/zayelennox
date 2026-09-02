"""Shiprocket API client with basic retry logic and structured logging."""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests
from django.conf import settings
from django.core.cache import cache

from shipping.exceptions import ShiprocketAPIError
from shipping.parcel import calculate_parcel

logger = logging.getLogger(__name__)


class ShiprocketClient:
    """Thin wrapper around the Shiprocket v1 external API."""

    def __init__(self, base_url: Optional[str] = None, max_retries: int = 3, timeout: int = 15):
        self.base_url = base_url or getattr(
            settings,
            "SHIPROCKET_BASE_URL",
            "https://apiv2.shiprocket.in/v1/external",
        )
        self.max_retries = max_retries
        self.timeout = timeout

    # ---------- Core HTTP helpers ----------

    def authenticate(self) -> str:
        """Return JWT token (cached). Expires in ~10 days; cached for 9."""
        cache_key = "shiprocket_token"
        token = cache.get(cache_key)
        if token:
            return token

        try:
            response = requests.post(
                f"{self.base_url}/auth/login",
                json={
                    "email": settings.SHIPROCKET_EMAIL,
                    "password": settings.SHIPROCKET_PASSWORD,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            token = data.get("token")
            if not token:
                raise ShiprocketAPIError("Shiprocket auth response missing token.")
            cache.set(cache_key, token, timeout=60 * 60 * 24 * 9)
            return token
        except requests.RequestException as exc:
            logger.error("Shiprocket auth failed: %s", exc, exc_info=True)
            raise ShiprocketAPIError(f"Shiprocket auth failed: {exc}") from exc

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.authenticate()}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, *, json=None, params=None, timeout=None):
        url = f"{self.base_url}{path}"
        timeout = timeout or self.timeout
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info("Shiprocket %s %s attempt %s", method, path, attempt)
                response = requests.request(
                    method=method,
                    url=url,
                    json=json,
                    params=params,
                    headers=self._headers(),
                    timeout=timeout,
                )
                if 500 <= response.status_code < 600:
                    logger.warning(
                        "Shiprocket %s %s server error %s: %s",
                        method,
                        path,
                        response.status_code,
                        response.text[:500],
                    )
                    last_exc = ShiprocketAPIError(f"Shiprocket server error {response.status_code}")
                else:
                    response.raise_for_status()
                    return response.json()
            except requests.RequestException as exc:
                logger.warning(
                    "Shiprocket %s %s request error on attempt %s: %s",
                    method,
                    path,
                    attempt,
                    exc,
                    exc_info=True,
                )
                if getattr(exc, "response", None) is not None:
                    logger.warning("Shiprocket response body: %s", exc.response.text)
                last_exc = exc

            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 5))

        raise ShiprocketAPIError(f"Shiprocket request failed for {path}: {last_exc}")

    # ---------- Public API methods ----------

    def create_order(self, order, shipment) -> dict:
        """Create a Shiprocket order for the given Order using calculated parcel dimensions."""
        address = order.delivery_address_snapshot or {}
        if not address.get("pincode"):
            raise ShiprocketAPIError("Order has no delivery pincode — cannot book with Shiprocket.")

        parcel = calculate_parcel(order)
        items = order.items.select_related("product", "variant").all()

        order_items = []
        for item in items:
            variant = item.variant
            sku = item.product.sku
            if variant is not None and variant.sku_suffix:
                sku = f"{sku}-{variant.sku_suffix}"
            order_items.append(
                {
                    "name": item.product.name,
                    "sku": sku,
                    "units": int(item.quantity),
                    "selling_price": str(item.unit_price),
                }
            )

        payment_method = "Prepaid"

        payload = {
            "order_id": str(order.order_number),
            "order_date": order.created_at.strftime("%Y-%m-%d %H:%M"),
            "pickup_location": getattr(settings, "SHIPROCKET_PICKUP_LOCATION", "Primary"),
            "billing_customer_name": address.get("name", ""),
            "billing_last_name": "",
            "billing_address": address.get("line1", ""),
            "billing_address_2": address.get("line2", ""),
            "billing_city": address.get("city", ""),
            "billing_pincode": address.get("pincode", ""),
            "billing_state": address.get("state", ""),
            "billing_country": address.get("country", "India"),
            "billing_email": address.get("email", ""),
            "billing_phone": address.get("phone", ""),
            "shipping_is_billing": True,
            "order_items": order_items,
            "payment_method": payment_method,
            "sub_total": str(order.subtotal),
            "length": float(parcel["length"]),
            "breadth": float(parcel["breadth"]),
            "height": float(parcel["height"]),
            "weight": float(parcel["weight"]),
        }

        data = self._request("POST", "/orders/create/adhoc", json=payload)
        logger.info("Shiprocket create_order success for %s: %s", order.order_number, data)
        return data

    def assign_awb(self, shipment) -> dict:
        if not shipment.shiprocket_shipment_id:
            raise ShiprocketAPIError("Shipment has no Shiprocket shipment_id.")
        payload = {"shipment_id": shipment.shiprocket_shipment_id}
        data = self._request("POST", "/courier/assign/awb", json=payload)
        logger.info("Shiprocket assign_awb success for order %s: %s", shipment.order.order_number, data)
        return data

    def request_pickup(self, shipment) -> dict:
        if not shipment.shiprocket_shipment_id:
            raise ShiprocketAPIError("Shipment has no Shiprocket shipment_id.")
        payload = {"shipment_id": [shipment.shiprocket_shipment_id]}
        data = self._request("POST", "/courier/generate/pickup", json=payload)
        logger.info("Shiprocket request_pickup success for order %s: %s", shipment.order.order_number, data)
        return data

    def generate_label(self, shipment) -> dict:
        if not shipment.shiprocket_shipment_id:
            raise ShiprocketAPIError("Shipment has no Shiprocket shipment_id.")
        payload = {"shipment_id": [shipment.shiprocket_shipment_id]}
        data = self._request("POST", "/courier/generate/label", json=payload)
        logger.info("Shiprocket generate_label success for order %s: %s", shipment.order.order_number, data)
        return data

    def cancel_shipment(self, shipment) -> dict:
        """Attempt to cancel a shipment in Shiprocket."""
        if not shipment.shiprocket_shipment_id and not shipment.shiprocket_order_id:
            raise ShiprocketAPIError("Shipment has no Shiprocket identifiers to cancel.")

        payload = {}
        if shipment.shiprocket_shipment_id:
            payload["shipment_id"] = [shipment.shiprocket_shipment_id]
        if shipment.shiprocket_order_id:
            payload["ids"] = [shipment.shiprocket_order_id]

        data = self._request("POST", "/orders/cancel", json=payload)
        logger.info("Shiprocket cancel_shipment success for order %s: %s", shipment.order.order_number, data)
        return data

    def check_serviceability(
        self,
        pickup_pincode: str,
        delivery_pincode: str,
        weight: float,
        length: float,
        breadth: float,
        height: float,
        is_cod: bool = False,
    ) -> dict:
        """Check if delivery is possible to the destination pincode."""
        params = {
            "pickup_postcode": pickup_pincode,
            "delivery_postcode": delivery_pincode,
            "weight": weight,
            "length": length,
            "breadth": breadth,
            "height": height,
            "cod": 1 if is_cod else 0,
        }
        data = self._request("GET", "/courier/serviceability/", params=params)
        logger.info("Serviceability check: %s -> %s", pickup_pincode, delivery_pincode)
        return data

    def get_shipping_rates(self, pickup_pincode, delivery_pincode, weight, length, breadth, height, is_cod=False):
        data = self.check_serviceability(pickup_pincode, delivery_pincode, weight, length, breadth, height, is_cod)
        available_couriers = []
        for courier in (data.get("data", {}).get("available_courier_companies") or []):
            available_couriers.append(
                {
                    "courier_id": courier.get("courier_company_id"),
                    "courier_name": courier.get("courier_name"),
                    "rate": float(courier.get("rate", 0)),
                    "freight_charge": float(courier.get("freight_charge", 0)),
                    "cod_charges": float(courier.get("cod_charges", 0)),
                    "estimated_delivery_days": courier.get("estimated_delivery_days"),
                    "cod_supported": bool(courier.get("cod", False)),
                }
            )
        return {
            "is_serviceable": len(available_couriers) > 0,
            "pickup_pincode": pickup_pincode,
            "delivery_pincode": delivery_pincode,
            "available_couriers": available_couriers,
            "recommended_courier": available_couriers[0] if available_couriers else None,
        }

    def track_shipment(self, awb_code: str) -> dict:
        path = f"/courier/track/awb/{awb_code}"
        data = self._request("GET", path)
        logger.info("Shiprocket track_shipment success for AWB %s", awb_code)
        return data


shiprocket_client = ShiprocketClient()
