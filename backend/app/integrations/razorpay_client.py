import hashlib
import hmac
import secrets
from decimal import Decimal
from typing import Any, Optional

import razorpay

from app.core.config import settings


class RazorpayGateway:
    """Razorpay integration supporting real live/sandbox keys and deterministic local HMAC test mode."""

    def __init__(self) -> None:
        self.key_id = settings.RAZORPAY_KEY_ID or "rzp_test_collegebites_local"
        self.key_secret = settings.RAZORPAY_KEY_SECRET or "rzp_test_secret_collegebites_local"
        self.webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET or "rzp_webhook_secret_collegebites_local"
        self.use_live_api = bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET and not settings.RAZORPAY_TEST_MODE)
        self._client = razorpay.Client(auth=(self.key_id, self.key_secret)) if self.use_live_api else None

    def create_order(self, *, amount_inr: Decimal, receipt_ref: str, notes: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        amount_paise = int((amount_inr * 100).quantize(Decimal("1")))
        if self._client is not None:
            return self._client.order.create(
                {
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": receipt_ref[:40],
                    "payment_capture": 1,
                    "notes": notes or {},
                }
            )
        return {
            "id": f"order_test_{secrets.token_hex(8)}",
            "entity": "order",
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt_ref[:40],
            "status": "created",
        }

    def verify_payment_signature(self, *, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> bool:
        body = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        expected = hmac.new(self.key_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, razorpay_signature.strip())

    def compute_test_payment_signature(self, *, razorpay_order_id: str, razorpay_payment_id: str) -> str:
        body = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        return hmac.new(self.key_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def verify_webhook_signature(self, *, raw_body: bytes, x_razorpay_signature: str) -> bool:
        expected = hmac.new(self.webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, x_razorpay_signature.strip())

    def compute_test_webhook_signature(self, *, raw_body: bytes) -> str:
        return hmac.new(self.webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


razorpay_gateway = RazorpayGateway()
