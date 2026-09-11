"""Concrete payment gateway adapters."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import uuid
from decimal import Decimal
from typing import Any

from payments.adapters.base import PaymentCaptureResult, PaymentGatewayAdapter, PaymentIntentResult

logger = logging.getLogger(__name__)


class CardGatewayAdapter(PaymentGatewayAdapter):
    """
    Generic card processor sandbox adapter.

    Uses a vendor-neutral interface (Stripe-like intent/capture shape) without
    coupling to a specific SDK — swap the internals when a processor is chosen.
    """

    key = "card"
    display_name = "Credit / Debit Card"
    is_async = False

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        intent_id = f"card_pi_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(
            intent_id=intent_id,
            client_secret=f"{intent_id}_secret",
            metadata={"amount": str(amount), "currency": currency, **metadata},
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        expected = hmac.new(b"sandbox-card", payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid card webhook signature.")
        return json.loads(payload.decode())

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        if intent_id.startswith("card_fail"):
            return PaymentCaptureResult(success=False, transaction_id=intent_id)
        return PaymentCaptureResult(
            success=True,
            transaction_id=f"card_tx_{intent_id}",
            metadata={"gateway": self.key},
        )

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"refund_{transaction_id}")


class QatarLocalGatewayAdapter(PaymentGatewayAdapter):
    """Qatar local payment rails sandbox adapter (e.g. NAPS-style deferred confirm)."""

    key = "qatar_local"
    display_name = "Qatar Local Payment"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        intent_id = f"qa_pi_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(
            intent_id=intent_id,
            metadata={"amount": str(amount), "currency": currency, **metadata},
            requires_webhook=True,
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        expected = hmac.new(b"sandbox-qatar", payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid Qatar local webhook signature.")
        return json.loads(payload.decode())

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"qa_tx_{intent_id}")

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"qa_refund_{transaction_id}")


class ApplePayAdapter(PaymentGatewayAdapter):
    """Apple Pay wallet adapter — async webhook confirmation."""

    key = "apple_pay"
    display_name = "Apple Pay"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        intent_id = f"ap_pi_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(intent_id=intent_id, requires_webhook=True, metadata=metadata)

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        expected = hmac.new(b"sandbox-apple", payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid Apple Pay webhook signature.")
        return json.loads(payload.decode())

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"ap_tx_{intent_id}")

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"ap_refund_{transaction_id}")


class GooglePayAdapter(PaymentGatewayAdapter):
    """Google Pay wallet adapter — async webhook confirmation."""

    key = "google_pay"
    display_name = "Google Pay"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        intent_id = f"gp_pi_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(intent_id=intent_id, requires_webhook=True, metadata=metadata)

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        expected = hmac.new(b"sandbox-google", payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid Google Pay webhook signature.")
        return json.loads(payload.decode())

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"gp_tx_{intent_id}")

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"gp_refund_{transaction_id}")



def _get_razorpay_credentials() -> tuple[str, str]:
    """
    Resolve Razorpay credentials.

    """
    try:
        from core.models import SiteSettings
        settings_inst = SiteSettings.objects.first()
        if settings_inst:
            key_id = settings_inst.razorpay_key_id.strip()
            key_secret = settings_inst.razorpay_key_secret.strip()
            if key_id and key_secret:
                return key_id, key_secret
    except Exception:
        pass
    import os
    key_id = os.getenv("RZP_CLIENT_ID") or os.getenv("RAZORPAY_KEY_ID", "")
    key_secret = os.getenv("RZP_CLIENT_SECRET") or os.getenv("RAZORPAY_KEY_SECRET", "")
    return key_id, key_secret


class RazorpayAdapter(PaymentGatewayAdapter):
    """
    Razorpay payment gateway base adapter.
    """
    key = "razorpay"
    display_name = "Razorpay (UPI, Credit/Debit Card, Net Banking, Wallets)"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        key_id, key_secret = _get_razorpay_credentials()
        amount_in_paise = int(amount * 100)

        if key_id and key_secret:
            try:
                import requests
                response = requests.post(
                    "https://api.razorpay.com/v1/orders",
                    auth=(key_id, key_secret),
                    json={
                        "amount": amount_in_paise,
                        "currency": currency,
                        "receipt": f"ord_{metadata.get('order_id', '')}",
                        "payment_capture": 1,
                        "notes": {
                            "order_id": str(metadata.get("order_id", "")),
                            "order_number": str(metadata.get("order_number", "")),
                        },
                    },
                    timeout=10,
                )
                if response.status_code in (200, 201):
                    data = response.json()
                    intent_id = data.get("id")
                    return PaymentIntentResult(
                        intent_id=intent_id,
                        requires_webhook=True,
                        metadata={"key_id": key_id, "razorpay_order_id": intent_id, **metadata},
                    )
                logger.error(
                    "Razorpay order creation failed (status=%s): %s",
                    response.status_code,
                    response.text,
                )
            except Exception:
                logger.exception("Razorpay order creation request failed; falling back to mock intent.")

        intent_id = f"rzp_order_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(
            intent_id=intent_id,
            requires_webhook=True,
            metadata={"key_id": key_id or "rzp_test_mock", "razorpay_order_id": intent_id, **metadata},
        )

    def verify_payment_signature(
        self,
        *,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> bool:
        key_id, key_secret = _get_razorpay_credentials()
        if not key_secret:
            return True
        msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        expected = hmac.new(key_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, razorpay_signature)

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        key_id, key_secret = _get_razorpay_credentials()
        if key_secret:
            expected = hmac.new(key_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError("Invalid Razorpay webhook signature.")
        return json.loads(payload.decode())

    def capture_payment(
        self,
        *,
        razorpay_payment_id: str,
        amount: Decimal,
        currency: str = None,
    ) -> bool:
        if not currency:
            from core.selectors import get_default_currency
            default_curr = get_default_currency()
            currency = default_curr.code if default_curr else "INR"
        key_id, key_secret = _get_razorpay_credentials()
        if key_id and key_secret and razorpay_payment_id and not razorpay_payment_id.startswith("pay_test_"):
            try:
                import requests
                amount_in_paise = int(amount * 100)
                resp = requests.post(
                    f"https://api.razorpay.com/v1/payments/{razorpay_payment_id}/capture",
                    auth=(key_id, key_secret),
                    json={"amount": amount_in_paise, "currency": currency},
                    timeout=10,
                )
                if resp.status_code in (200, 201):
                    return True
                logger.warning(
                    "Razorpay capture for %s returned status=%s: %s",
                    razorpay_payment_id,
                    resp.status_code,
                    resp.text,
                )
                return "already" in resp.text.lower() or "captured" in resp.text.lower()
            except Exception:
                logger.exception("Razorpay capture request failed for payment %s.", razorpay_payment_id)
                return False
        return True

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(
            success=True,
            transaction_id=f"rzp_tx_{intent_id}",
            metadata={"gateway": self.key},
        )

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"razorpay_refund_{transaction_id}")

class RazorpayUPIAdapter(RazorpayAdapter):
    key = "razorpay_upi"
    display_name = "UPI"

class RazorpayCardAdapter(RazorpayAdapter):
    key = "razorpay_card"
    display_name = "Credit/Debit Card"

class RazorpayNetbankingAdapter(RazorpayAdapter):
    key = "razorpay_netbanking"
    display_name = "Net Banking"

class RazorpayWalletAdapter(RazorpayAdapter):
    key = "razorpay_wallet"
    display_name = "Wallet"


def _get_payu_credentials() -> tuple[str, str]:

    try:
        from core.models import SiteSettings
        settings_inst = SiteSettings.objects.first()
        if settings_inst:
            merchant_key = settings_inst.payu_merchant_key.strip()
            merchant_salt = settings_inst.payu_merchant_salt.strip()
            if merchant_key and merchant_salt:
                return merchant_key, merchant_salt
    except Exception:
        pass
    import os
    merchant_key = os.getenv("PAYU_MERCHANT_KEY", "")
    merchant_salt = os.getenv("PAYU_MERCHANT_SALT", "")
    return merchant_key, merchant_salt


def _get_payu_test_mode() -> bool:
    """Resolve whether PayU should use its test/sandbox endpoint."""
    try:
        from core.models import SiteSettings
        settings_inst = SiteSettings.objects.first()
        if settings_inst is not None:
            return bool(settings_inst.payu_test_mode)
    except Exception:
        pass
    import os
    return os.getenv("PAYU_TEST_MODE", "true").strip().lower() not in ("0", "false", "no")


PAYU_TEST_BASE_URL = "https://test.payu.in/_payment"
PAYU_LIVE_BASE_URL = "https://secure.payu.in/_payment"


class PayUAdapter(PaymentGatewayAdapter):
    """
    PayU payment gateway adapter.

    """

    key = "payu"
    display_name = "PayU (UPI, Credit/Debit Card, Net Banking, Wallets)"
    is_async = True

    @staticmethod
    def base_url() -> str:
        return PAYU_TEST_BASE_URL if _get_payu_test_mode() else PAYU_LIVE_BASE_URL

    @staticmethod
    def build_request_hash(
        *,
        merchant_key: str,
        merchant_salt: str,
        txnid: str,
        amount: str,
        productinfo: str,
        firstname: str,
        email: str,
        udf1: str = "",
        udf2: str = "",
        udf3: str = "",
        udf4: str = "",
        udf5: str = "",
    ) -> str:
        """PayU's documented request-hash sequence (11 fields, then 5 blanks, then salt)."""
        sequence = "|".join(
            [
                merchant_key, txnid, amount, productinfo, firstname, email,
                udf1, udf2, udf3, udf4, udf5, "", "", "", "", "",
                merchant_salt,
            ]
        )
        return hashlib.sha512(sequence.encode("utf-8")).hexdigest()

    @staticmethod
    def verify_response_hash(
        *,
        merchant_salt: str,
        merchant_key: str,
        status: str,
        txnid: str,
        amount: str,
        productinfo: str,
        firstname: str,
        email: str,
        received_hash: str,
        udf1: str = "",
        udf2: str = "",
        udf3: str = "",
        udf4: str = "",
        udf5: str = "",
    ) -> bool:

        if not merchant_salt or not received_hash:
            return False
        sequence = "|".join(
            [
                merchant_salt, status, "", "", "", "", "",
                udf5, udf4, udf3, udf2, udf1, email, firstname, productinfo, amount, txnid,
                merchant_key,
            ]
        )
        expected = hashlib.sha512(sequence.encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected, received_hash.lower())

    @staticmethod
    def _safe_txnid(raw: str) -> str:
        """PayU txnid: alphanumeric only, kept well under its 25-char limit."""
        cleaned = re.sub(r"[^A-Za-z0-9]", "", str(raw or ""))
        return cleaned[:20] or uuid.uuid4().hex[:16]

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        merchant_key, merchant_salt = _get_payu_credentials()
        txnid = self._safe_txnid(metadata.get("order_number") or metadata.get("order_id"))
        amount_str = f"{amount:.2f}"
        productinfo = f"Order {metadata.get('order_number', '')}".strip() or "Order Payment"
        firstname = str(metadata.get("customer_name") or "Customer").strip()[:60] or "Customer"
        email = str(metadata.get("customer_email") or "guest@example.com").strip()

        request_hash = ""
        if merchant_key and merchant_salt:
            request_hash = self.build_request_hash(
                merchant_key=merchant_key,
                merchant_salt=merchant_salt,
                txnid=txnid,
                amount=amount_str,
                productinfo=productinfo,
                firstname=firstname,
                email=email,
            )
        else:
            logger.warning("PayU credentials not configured; created a mock intent for txnid=%s", txnid)
            merchant_key = merchant_key or "payu_test_mock"

        return PaymentIntentResult(
            intent_id=txnid,
            requires_webhook=True,
            metadata={
                "key": merchant_key,
                "payu_txnid": txnid,
                "hash": request_hash,
                "amount": amount_str,
                "productinfo": productinfo,
                "firstname": firstname,
                "email": email,
                "base_url": self.base_url(),
                **metadata,
            },
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        """
        Parse and verify a server-to-server PayU webhook delivery.

        """
        data = json.loads(payload.decode())
        merchant_key, merchant_salt = _get_payu_credentials()
        is_valid = self.verify_response_hash(
            merchant_salt=merchant_salt,
            merchant_key=merchant_key,
            status=str(data.get("status", "")),
            txnid=str(data.get("txnid", "")),
            amount=str(data.get("amount", "")),
            productinfo=str(data.get("productinfo", "")),
            firstname=str(data.get("firstname", "")),
            email=str(data.get("email", "")),
            received_hash=str(data.get("hash", "")),
        )
        if not is_valid:
            raise ValueError("Invalid PayU webhook hash.")
        return data

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(
            success=True,
            transaction_id=f"payu_tx_{intent_id}",
            metadata={"gateway": self.key},
        )

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"payu_refund_{transaction_id}")
