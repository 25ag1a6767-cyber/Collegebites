import hashlib
import hmac
import secrets
from decimal import Decimal
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from app.core.config import settings

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


class RazorpayGateway:
    """Razorpay integration supporting real live/sandbox REST orders and dev/test HMAC verification."""

    def __init__(self) -> None:
        self._configured = bool(settings.RAZORPAY_KEY_ID.strip() and settings.RAZORPAY_KEY_SECRET.strip())
        self.key_id = settings.RAZORPAY_KEY_ID.strip() or "rzp_test_collegebites_local"
        self.public_key_id: Optional[str] = settings.RAZORPAY_KEY_ID.strip() or None
        self.key_secret = settings.RAZORPAY_KEY_SECRET.strip() or "rzp_test_secret_collegebites_local"
        self.webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET.strip() or "rzp_webhook_secret_collegebites_local"
        # Call live/sandbox Razorpay REST Orders API whenever real credentials are configured
        self.use_live_api = self._configured

    def create_order(self, *, amount_inr: Decimal, receipt_ref: str, notes: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        amount_paise = int((amount_inr * 100).quantize(Decimal("1")))
        if self.use_live_api:
            resp = httpx.post(
                f"{RAZORPAY_API_BASE}/orders",
                auth=(self.key_id, self.key_secret),
                json={
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": receipt_ref[:40],
                    "payment_capture": 1,
                    "notes": notes or {},
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            return resp.json()
        if settings.is_production:
            raise HTTPException(
                status_code=503,
                detail="Razorpay payment gateway credentials (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET) are not configured in production.",
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
