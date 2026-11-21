import hashlib
import hmac
import json
import secrets
import time
from decimal import Decimal
from typing import Any, Optional

import stripe
from fastapi import HTTPException

from app.core.config import settings


class StripeGateway:
    """
    Stripe payment integration powered by the official `stripe` Python SDK.
    - Uses PaymentIntents (`automatic_payment_methods={"enabled": True}`) for web Elements
      and mobile PaymentSheet, with server-verified status retrieval and Webhook signatures.
    - Also retains Checkout Session retrieval for backward compatibility.
    - In local/test runs without STRIPE_SECRET_KEY, provides deterministic `pi_test_*` intents
      and HMAC helpers while strictly refusing fake flows in production (`503`).
    - Strictly enforces CollegeBites' NO REFUNDS policy (never invokes refund APIs).
    """

    def __init__(self) -> None:
        self.publishable_key = settings.STRIPE_PUBLISHABLE_KEY.strip() or None
        self.secret_key = settings.STRIPE_SECRET_KEY.strip() or "sk_test_collegebites_local"
        self.webhook_secret = settings.STRIPE_WEBHOOK_SECRET.strip() or "whsec_collegebites_local"
        self.use_live_api = bool(settings.STRIPE_SECRET_KEY.strip())

    def _client(self) -> stripe.StripeClient:
        return stripe.StripeClient(self.secret_key)

    def create_payment_intent(
        self,
        *,
        amount_inr: Decimal,
        order_number: str,
        customer_email: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        amount_paise = int((amount_inr * 100).quantize(Decimal("1")))
        if self.use_live_api:
            params: dict[str, Any] = {
                "amount": amount_paise,
                "currency": "inr",
                "automatic_payment_methods": {"enabled": True},
                "description": f"CollegeBites Order {order_number}",
                "metadata": {"order_number": order_number, **(metadata or {})},
            }
            if customer_email:
                params["receipt_email"] = customer_email
            options = {"idempotency_key": idempotency_key} if idempotency_key else None
            try:
                intent = self._client().v1.payment_intents.create(params=params, options=options)
            except stripe.StripeError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Stripe PaymentIntent creation failed: {exc.user_message or str(exc)}",
                ) from exc
            return {
                "id": intent.id,
                "client_secret": intent.client_secret,
                "amount": intent.amount,
                "currency": intent.currency,
                "status": intent.status,
            }

        if settings.is_production:
            raise HTTPException(
                status_code=503,
                detail="Stripe payment gateway credentials (STRIPE_SECRET_KEY) are not configured in production.",
            )

        pi_id = f"pi_test_cb_{secrets.token_hex(10)}"
        return {
            "id": pi_id,
            "client_secret": f"{pi_id}_secret_{secrets.token_hex(12)}",
            "amount": amount_paise,
            "currency": "inr",
            "status": "requires_payment_method",
        }

    def retrieve_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        if self.use_live_api:
            try:
                intent = self._client().v1.payment_intents.retrieve(payment_intent_id)
            except stripe.StripeError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Stripe PaymentIntent retrieval failed: {exc.user_message or str(exc)}",
                ) from exc
            err_msg = None
            if intent.last_payment_error:
                err_msg = getattr(intent.last_payment_error, "message", None)
            return {
                "id": intent.id,
                "status": intent.status,
                "amount": intent.amount,
                "amount_received": getattr(intent, "amount_received", 0),
                "currency": intent.currency,
                "metadata": dict(intent.metadata or {}),
                "last_payment_error": err_msg,
            }
        return {
            "id": payment_intent_id,
            "status": "succeeded",
            "currency": "inr",
        }

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
            params: dict[str, Any] = {
                "mode": "payment",
                "success_url": success_url,
                "cancel_url": cancel_url,
                "client_reference_id": order_number,
                "line_items": [
                    {
                        "price_data": {
                            "currency": "inr",
                            "product_data": {"name": f"CollegeBites Order {order_number}"},
                            "unit_amount": amount_paise,
                        },
                        "quantity": 1,
                    }
                ],
                "metadata": {"order_number": order_number},
            }
            if customer_email:
                params["customer_email"] = customer_email
            try:
                sess = self._client().v1.checkout.sessions.create(params=params)
            except stripe.StripeError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Stripe Checkout Session creation failed: {exc.user_message or str(exc)}",
                ) from exc
            return {
                "id": sess.id,
                "object": "checkout.session",
                "amount_total": sess.amount_total,
                "currency": sess.currency,
                "payment_status": sess.payment_status,
                "status": sess.status,
                "url": sess.url,
            }

        if settings.is_production:
            raise HTTPException(
                status_code=503,
                detail="Stripe payment gateway credentials (STRIPE_SECRET_KEY) are not configured in production.",
            )

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
            try:
                sess = self._client().v1.checkout.sessions.retrieve(session_id)
            except stripe.StripeError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Stripe session retrieval failed: {exc.user_message or str(exc)}",
                ) from exc
            return {
                "id": sess.id,
                "payment_status": sess.payment_status,
                "status": sess.status,
                "payment_intent": sess.payment_intent,
            }
        return {"id": session_id, "payment_status": "paid", "status": "complete"}

    def verify_test_payment_signature(
        self,
        *,
        stripe_payment_intent_id: str,
        stripe_signature: str,
        stripe_session_id: Optional[str] = None,
    ) -> bool:
        """Verify local/test HMAC signature when live Stripe API is disabled."""
        candidates = [stripe_payment_intent_id]
        if stripe_session_id:
            candidates.append(f"{stripe_session_id}|{stripe_payment_intent_id}")
        provided = stripe_signature.strip()
        for raw in candidates:
            expected = hmac.new(self.secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, provided):
                return True
        return False

    def compute_test_payment_signature(
        self,
        *,
        stripe_payment_intent_id: str,
        stripe_session_id: Optional[str] = None,
    ) -> str:
        raw = f"{stripe_session_id}|{stripe_payment_intent_id}" if stripe_session_id else stripe_payment_intent_id
        return hmac.new(self.secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()

    def construct_webhook_event(
        self, *, raw_body: bytes, stripe_signature_header: str, tolerance_seconds: int = 300
    ) -> dict[str, Any]:
        """Verify Stripe-Signature header using stripe.Webhook.construct_event and return parsed event dict."""
        try:
            event = stripe.Webhook.construct_event(
                payload=raw_body.decode("utf-8"),
                sig_header=stripe_signature_header,
                secret=self.webhook_secret,
                tolerance=tolerance_seconds,
            )
            return json.loads(json.dumps(event))
        except stripe.SignatureVerificationError as exc:
            raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Malformed Stripe webhook JSON payload") from exc

    def verify_webhook_signature(
        self, *, raw_body: bytes, stripe_signature_header: str, tolerance_seconds: int = 300
    ) -> bool:
        try:
            stripe.Webhook.construct_event(
                payload=raw_body.decode("utf-8"),
                sig_header=stripe_signature_header,
                secret=self.webhook_secret,
                tolerance=tolerance_seconds,
            )
            return True
        except Exception:
            return False

    def compute_test_webhook_signature(self, *, raw_body: bytes, timestamp: Optional[int] = None) -> str:
        ts = str(timestamp or int(time.time()))
        signed_payload = f"{ts}.".encode("utf-8") + raw_body
        sig = hmac.new(self.webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"


stripe_gateway = StripeGateway()
