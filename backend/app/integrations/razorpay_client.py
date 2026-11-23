import hashlib
import hmac
import secrets
from decimal import Decimal
from typing import Any, Optional

import razorpay
import requests
from fastapi import HTTPException

from app.core.config import settings


class RazorpayGateway:
    """Razorpay Standard Checkout integration powered by the official `razorpay` Python SDK."""

    def __init__(self) -> None:
        self._configured = bool(settings.RAZORPAY_KEY_ID.strip() and settings.RAZORPAY_KEY_SECRET.strip())
        self.key_id = settings.RAZORPAY_KEY_ID.strip() or "rzp_test_collegebites_local"
        self.public_key_id: Optional[str] = settings.RAZORPAY_KEY_ID.strip() or None
        self.key_secret = settings.RAZORPAY_KEY_SECRET.strip() or "rzp_test_secret_collegebites_local"
        self.webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET.strip() or "rzp_webhook_secret_collegebites_local"
        # Call live/sandbox Razorpay REST Orders API whenever real credentials are configured
        self.use_live_api = self._configured

    def _client(self) -> razorpay.Client:
        return razorpay.Client(auth=(self.key_id, self.key_secret))

    def create_order(
        self,
        *,
        amount_inr: Decimal,
        receipt_ref: str,
        notes: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        amount_paise = int((amount_inr * 100).quantize(Decimal("1")))
        if amount_paise < 100:
            raise HTTPException(
                status_code=400,
                detail="Minimum payment amount for Razorpay is ₹1.00 (100 paise).",
            )
        if self.use_live_api:
            payload = {
                "amount": amount_paise,
                "currency": "INR",
                "receipt": receipt_ref[:40],
                "payment_capture": 1,
                "notes": notes or {},
            }
            try:
                return self._client().order.create(data=payload)
            except razorpay.errors.BadRequestError as exc:
                msg = str(exc) or "Razorpay request error"
                if "auth" in msg.lower():
                    raise HTTPException(
                        status_code=401,
                        detail="Razorpay authentication failed. Verify RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.",
                    ) from exc
                raise HTTPException(status_code=500, detail=f"Razorpay API error: {msg}") from exc
            except (
                razorpay.errors.GatewayError,
                razorpay.errors.ServerError,
                requests.exceptions.RequestException,
            ) as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Razorpay gateway error while creating order: {exc}",
                ) from exc

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

    def verify_payment_signature(
        self,
        *,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> bool:
        if not (razorpay_order_id and razorpay_payment_id and razorpay_signature):
            return False
        try:
            self._client().utility.verify_payment_signature(
                {
                    "razorpay_order_id": razorpay_order_id.strip(),
                    "razorpay_payment_id": razorpay_payment_id.strip(),
                    "razorpay_signature": razorpay_signature.strip(),
                }
            )
            return True
        except razorpay.errors.SignatureVerificationError:
            return False

    def compute_test_payment_signature(self, *, razorpay_order_id: str, razorpay_payment_id: str) -> str:
        body = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        return hmac.new(self.key_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def verify_webhook_signature(self, *, raw_body: bytes, x_razorpay_signature: str) -> bool:
        if not raw_body or not x_razorpay_signature:
            return False
        expected = hmac.new(self.webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, x_razorpay_signature.strip())

    def compute_test_webhook_signature(self, *, raw_body: bytes) -> str:
        return hmac.new(self.webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    def fetch_payment(self, razorpay_payment_id: str) -> Optional[dict[str, Any]]:
        if not self.use_live_api or not razorpay_payment_id:
            return None
        try:
            return self._client().payment.fetch(razorpay_payment_id)
        except (
            razorpay.errors.BadRequestError,
            razorpay.errors.GatewayError,
            razorpay.errors.ServerError,
            requests.exceptions.RequestException,
        ):
            return None


razorpay_gateway = RazorpayGateway()
