import hashlib
import hmac
import secrets
import time
from decimal import Decimal
from typing import Any, Optional

import httpx

from app.core.config import settings

STRIPE_API_BASE = "https://api.stripe.com/v1"


class StripeGateway:
    """
    Stripe payment integration supporting live/sandbox REST Checkout Sessions and
    deterministic HMAC-SHA256 test verification when running without live keys.
    Strictly enforces CollegeBites' NO REFUNDS policy (never invokes refund endpoints).
    """

    def __init__(self) -> None:
        self.publishable_key = settings.STRIPE_PUBLISHABLE_KEY or "pk_test_collegebites_local"
        self.secret_key = settings.STRIPE_SECRET_KEY or "sk_test_collegebites_local"
        self.webhook_secret = settings.STRIPE_WEBHOOK_SECRET or "whsec_collegebites_local"
        self.use_live_api = bool(settings.STRIPE_SECRET_KEY and not settings.STRIPE_TEST_MODE)

    def create_checkout_session(
        self,
        *,
        amount_inr: Decimal,
        order_number: str,
        success_url: str,
        cancel_url: str,
        customer_email: Optional[str] = None,
    ) -> dict[str, Any]:
        amount_paise = int((amount_inr * 100).quantize(Decimal("1")))
        if self.use_live_api:
            form: dict[str, Any] = {
                "mode": "payment",
                "success_url": success_url,
                "cancel_url": cancel_url,
                "client_reference_id": order_number,
                "line_items[0][price_data][currency]": "inr",
                "line_items[0][price_data][product_data][name]": f"CollegeBites Order {order_number}",
                "line_items[0][price_data][unit_amount]": str(amount_paise),
                "line_items[0][quantity]": "1",
                "metadata[order_number]": order_number,
            }
            if customer_email:
                form["customer_email"] = customer_email
            resp = httpx.post(
                f"{STRIPE_API_BASE}/checkout/sessions",
                auth=(self.secret_key, ""),
                data=form,
                timeout=15.0,
            )
            resp.raise_for_status()
            return resp.json()

        sid = f"cs_test_cb_{secrets.token_hex(10)}"
        return {
            "id": sid,
            "object": "checkout.session",
            "amount_total": amount_paise,
            "currency": "inr",
            "payment_status": "unpaid",
            "status": "open",
            "url": None,
        }

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        if self.use_live_api:
            resp = httpx.get(
                f"{STRIPE_API_BASE}/checkout/sessions/{session_id}",
                auth=(self.secret_key, ""),
                timeout=15.0,
            )
            resp.raise_for_status()
            return resp.json()
        return {"id": session_id, "payment_status": "paid", "status": "complete"}

    def verify_test_payment_signature(
        self, *, stripe_session_id: str, stripe_payment_intent_id: str, stripe_signature: str
    ) -> bool:
        body = f"{stripe_session_id}|{stripe_payment_intent_id}".encode("utf-8")
        expected = hmac.new(self.secret_key.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, stripe_signature.strip())

    def compute_test_payment_signature(self, *, stripe_session_id: str, stripe_payment_intent_id: str) -> str:
        body = f"{stripe_session_id}|{stripe_payment_intent_id}".encode("utf-8")
        return hmac.new(self.secret_key.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def verify_webhook_signature(self, *, raw_body: bytes, stripe_signature_header: str) -> bool:
        """Verify Stripe-Signature header (`t=<timestamp>,v1=<hmac>`)."""
        parts: dict[str, str] = {}
        for item in stripe_signature_header.split(","):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                parts[k] = v
        ts = parts.get("t")
        v1 = parts.get("v1")
        if not ts or not v1:
            return False
        signed_payload = f"{ts}.".encode("utf-8") + raw_body
        expected = hmac.new(self.webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)

    def compute_test_webhook_signature(self, *, raw_body: bytes, timestamp: Optional[int] = None) -> str:
        ts = str(timestamp or int(time.time()))
        signed_payload = f"{ts}.".encode("utf-8") + raw_body
        sig = hmac.new(self.webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"


stripe_gateway = StripeGateway()
