import React, { useMemo, useState } from "react";
import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe, type Stripe } from "@stripe/stripe-js";
import { AlertTriangle, CreditCard, Lock } from "lucide-react";
import { api, getApiError } from "../../api/client";
import type { Order } from "../../types";
import { BrandLogo } from "../branding/BrandLogo";
import { Badge, Button, Modal } from "../ui/Primitives";

const stripePromiseCache = new Map<string, Promise<Stripe | null>>();

function getStripePromise(publishableKey?: string | null): Promise<Stripe | null> | null {
  const key = (publishableKey || "").trim();
  if (!key) return null;
  let cached = stripePromiseCache.get(key);
  if (!cached) {
    cached = loadStripe(key);
    stripePromiseCache.set(key, cached);
  }
  return cached;
}

const StripeElementsInnerForm: React.FC<{
  order: Order;
  onSuccess: (verified: Order) => void;
  onFailed: (order: Order) => void;
  onProcessing: (order: Order) => void;
}> = ({ order, onSuccess, onFailed, onProcessing }) => {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const handlePay = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stripe || !elements || submitting) return;
    setSubmitting(true);
    setErrMsg(null);
    try {
      const guestQ = order.guest_access_token
        ? `?guest_token=${encodeURIComponent(order.guest_access_token)}`
        : "";
      const returnUrl = `${window.location.origin}/orders/${order.order_number}${guestQ}`;

      const result = await stripe.confirmPayment({
        elements,
        confirmParams: { return_url: returnUrl },
        redirect: "if_required",
      });

      if (result.error) {
        setErrMsg(result.error.message || "Payment was declined or interrupted.");
        setSubmitting(false);
        return;
      }

      const pi = result.paymentIntent;
      if (!pi) {
        setErrMsg("Payment confirmation did not return a PaymentIntent status.");
        setSubmitting(false);
        return;
      }

      if (pi.status === "succeeded" || pi.status === "processing") {
        const res = await api.post<Order>("/payments/stripe/verify", {
          order_id: order.id,
          stripe_payment_intent_id: pi.id,
          payment_method: "stripe",
        });
        if (res.data.payment_status === "CONFIRMED") {
          onSuccess(res.data);
        } else {
          onProcessing(res.data);
        }
        return;
      }

      setErrMsg(`Payment status is "${pi.status}". Complete authentication or cancel to retry.`);
    } catch (err) {
      setErrMsg(getApiError(err, "Unable to verify Stripe payment on server"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancelPayment = async () => {
    setSubmitting(true);
    try {
      const gTok = order.guest_access_token
        ? `?guest_token=${encodeURIComponent(order.guest_access_token)}`
        : "";
      const res = await api.post<Order>(`/payments/stripe/fail${gTok}`, {
        order_id: order.id,
        stripe_payment_intent_id: order.stripe_payment_intent_id || undefined,
        reason: "Customer cancelled Stripe PaymentElement sheet",
      });
      onFailed(res.data);
    } catch (err) {
      setErrMsg(getApiError(err, "Failed to cancel pending payment"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handlePay} className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-3">
        <PaymentElement options={{ layout: "tabs" }} />
      </div>
      {errMsg && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">{errMsg}</div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="success" className="flex-1" disabled={!stripe || !elements || submitting}>
          <Lock className="h-3.5 w-3.5" />
          {submitting ? "Confirming with Stripe..." : `Pay ₹${order.total_amount}`}
        </Button>
        <Button type="button" variant="outline" disabled={submitting} onClick={handleCancelPayment}>
          Cancel / Fail
        </Button>
      </div>
    </form>
  );
};

export const StripePaymentModal: React.FC<{
  order: Order | null;
  publishableKeyOverride?: string | null;
  onClose: () => void;
  onSuccess: (verified: Order) => void;
  onFailed: (order: Order) => void;
  onProcessing: (order: Order) => void;
  onNavigateStatus: (order: Order) => void;
}> = ({ order, publishableKeyOverride, onClose, onSuccess, onFailed, onProcessing, onNavigateStatus }) => {
  const [busy, setBusy] = useState(false);
  const [fallbackErr, setFallbackErr] = useState<string | null>(null);

  const publishableKey = order?.stripe_publishable_key || publishableKeyOverride || null;
  const isLocalSimulatedIntent = Boolean(order?.stripe_payment_intent_id?.startsWith("pi_test_cb_"));
  const canMountElements = Boolean(
    order && publishableKey && order.stripe_client_secret && !isLocalSimulatedIntent
  );

  const stripePromise = useMemo(
    () => (canMountElements ? getStripePromise(publishableKey) : null),
    [canMountElements, publishableKey]
  );

  const cancelPending = async () => {
    if (!order) return;
    setBusy(true);
    setFallbackErr(null);
    try {
      const gTok = order.guest_access_token
        ? `?guest_token=${encodeURIComponent(order.guest_access_token)}`
        : "";
      const res = await api.post<Order>(`/payments/stripe/fail${gTok}`, {
        order_id: order.id,
        stripe_payment_intent_id: order.stripe_payment_intent_id || undefined,
        stripe_session_id: order.stripe_session_id || undefined,
        reason: "Customer cancelled payment on gateway",
      });
      onFailed(res.data);
    } catch (err) {
      setFallbackErr(getApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={Boolean(order)} onClose={onClose} title="Stripe Payment">
      {order && (
        <div
          className="space-y-4"
          data-order-id={order.id}
          data-order-number={order.order_number}
          data-stripe-intent={order.stripe_payment_intent_id || ""}
        >
          <div className="rounded-xl bg-[#380106] p-4 text-white flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <BrandLogo size="sm" variant="dark" />
              <div>
                <div className="text-xs text-[#fdedce]/80">CollegeBites • {order.order_number}</div>
                <div className="text-2xl font-extrabold">₹{order.total_amount}</div>
              </div>
            </div>
            <Badge tone="amber">
              Stripe: {order.stripe_payment_intent_id || order.stripe_session_id || "Pending"}
            </Badge>
          </div>

          <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 text-xs text-slate-600 flex items-start gap-2">
            <CreditCard className="h-4 w-4 text-indigo-600 shrink-0 mt-0.5" />
            <span>
              Your pickup token and digital receipt are issued only after backend verification or Stripe webhook
              confirmation.
            </span>
          </div>

          {canMountElements && stripePromise && order.stripe_client_secret ? (
            <Elements
              stripe={stripePromise}
              options={{
                clientSecret: order.stripe_client_secret,
                appearance: { theme: "stripe" },
              }}
            >
              <StripeElementsInnerForm
                order={order}
                onSuccess={onSuccess}
                onFailed={onFailed}
                onProcessing={onProcessing}
              />
            </Elements>
          ) : (
            <div className="space-y-3">
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950 flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-700 shrink-0 mt-0.5" />
                <span>
                  {order.stripe_checkout_url
                    ? "Redirecting via legacy Stripe Checkout URL."
                    : "Stripe online processing is awaiting merchant activation in this environment. Track your order or await webhook confirmation."}
                </span>
              </div>
              {fallbackErr && <div className="text-xs text-red-600">{fallbackErr}</div>}
              <div className="flex flex-wrap gap-2">
                {order.stripe_checkout_url ? (
                  <Button
                    variant="success"
                    className="flex-1"
                    disabled={busy}
                    onClick={() => {
                      window.location.href = order.stripe_checkout_url!;
                    }}
                  >
                    Launch Stripe Checkout
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    className="flex-1"
                    disabled={busy}
                    onClick={() => onNavigateStatus(order)}
                  >
                    View Order Status
                  </Button>
                )}
                <Button variant="outline" disabled={busy} onClick={cancelPending}>
                  Cancel / Fail
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
};
