import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import {
  BellRing,
  CheckCircle2,
  Clock,
  HelpCircle,
  PackageCheck,
  RefreshCw,
  RotateCcw,
  Utensils,
  XCircle,
} from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useRealtimeSync } from "../../hooks/useRealtimeSync";
import { useAppStore } from "../../store/useAppStore";
import type { Order, ReceiptSnapshot } from "../../types";
import { enableBrowserPushNotifications, playOrderAlertChime, showBrowserNotification } from "../../utils/notifications";
import { BrandLoadingState, BrandLogo } from "../../components/branding/BrandLogo";
import { ReceiptSlip } from "../../components/receipt/ReceiptSlip";
import { Badge, Button, Card, ConfirmModal, Input, useToast } from "../../components/ui/Primitives";
import { RealtimeStatusBadge } from "../../components/ui/RealtimeStatusBadge";
import { StripePaymentModal } from "../../components/payments/StripePaymentModal";
import { openRazorpayModal } from "../../utils/razorpay";

const STEPS = [
  { key: "PAYMENT_PENDING", label: "Payment Pending" },
  { key: "PAYMENT_CONFIRMED", label: "Payment Verified" },
  { key: "PLACED", label: "Order Placed" },
  { key: "ACCEPTED", label: "Accepted" },
  { key: "PREPARING", label: "Preparing" },
  { key: "READY", label: "Ready for Pickup" },
  { key: "COMPLETED", label: "Handed Over" },
];

function formatCountdown(secs: number): string {
  const s = Math.max(0, Math.floor(secs));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${String(m).padStart(2, "0")}:${String(rem).padStart(2, "0")}`;
}

export const OrderTrackingPage: React.FC = () => {
  const { orderNumber } = useParams<{ orderNumber: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { accessToken, guestOrderTokens, setSelectedCanteen } = useAppStore();

  const guestToken = searchParams.get("guest_token") || (orderNumber ? guestOrderTokens[orderNumber] : undefined);
  const [manualGuestToken, setManualGuestToken] = useState(guestToken || "");
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stripeModalOrder, setStripeModalOrder] = useState<Order | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [notifPerm, setNotifPerm] = useState<string>(() =>
    typeof window !== "undefined" && "Notification" in window ? Notification.permission : "unsupported"
  );
  const handledStripeRef = useRef<string | null>(null);
  const realtimeLiveRef = useRef(false);
  const prevTrackStateRef = useRef<{ status: string; delayed: number } | null>(null);

  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const effectiveToken = guestToken || manualGuestToken || undefined;
  const querySuffix = effectiveToken ? `?guest_token=${encodeURIComponent(effectiveToken)}` : "";

  const { data: order, error, refetch } = useQuery<Order>({
    queryKey: ["order", orderNumber, effectiveToken],
    enabled: Boolean(orderNumber),
    queryFn: async () => (await api.get(`/orders/${orderNumber}${querySuffix}`)).data,
    refetchInterval: () => (realtimeLiveRef.current ? 30000 : 5000),
    refetchIntervalInBackground: true,
  });

  const { status: orderSyncStatus, lastSyncedAt: orderLastSyncedAt } = useRealtimeSync<{ order?: Order }>({
    enabled: Boolean(order?.id && (accessToken || effectiveToken)),
    ssePath: order?.id ? `/realtime/orders/${order.id}/stream${querySuffix}` : null,
    wsPath: order?.id ? `/ws/orders/${order.id}` : null,
    wsGuestToken: effectiveToken,
    queryKeys: [["order", orderNumber, effectiveToken], ["receipt", orderNumber, effectiveToken]],
    onSnapshot: (snap) => {
      if (snap?.order) {
        qc.setQueryData(["order", orderNumber, effectiveToken], snap.order);
        if (snap.order.payment_status === "CONFIRMED") {
          qc.invalidateQueries({ queryKey: ["receipt", orderNumber, effectiveToken] });
        }
      }
    },
  });
  realtimeLiveRef.current = orderSyncStatus === "live";

  const { data: receipt, refetch: refetchReceipt } = useQuery<ReceiptSnapshot>({
    queryKey: ["receipt", orderNumber, effectiveToken],
    enabled: Boolean(order && order.payment_status === "CONFIRMED"),
    queryFn: async () => (await api.get(`/tokens/receipts/${orderNumber}${querySuffix}`)).data,
  });

  // Complete or record cancelled Stripe PaymentIntent / Checkout redirect
  useEffect(() => {
    const stripePi = searchParams.get("payment_intent");
    const stripeRedirectStatus = searchParams.get("redirect_status");
    const stripeSid = searchParams.get("stripe_session_id");
    const stripeCancelled = searchParams.get("stripe_cancelled");
    if (!order || order.payment_status === "CONFIRMED") return;
    if (stripeCancelled === "1" && handledStripeRef.current !== "cancelled" && order.status === "PAYMENT_PENDING") {
      handledStripeRef.current = "cancelled";
      api
        .post(`/payments/stripe/fail${querySuffix}`, {
          order_id: order.id,
          stripe_payment_intent_id: order.stripe_payment_intent_id || undefined,
          stripe_session_id: order.stripe_session_id || undefined,
          reason: "Stripe checkout cancelled by customer",
        })
        .then(() => {
          pushToast("Stripe checkout cancelled. You can retry payment anytime below.", "info");
          refetch();
        })
        .catch(() => {});
      return;
    }
    if (stripePi && handledStripeRef.current !== stripePi) {
      handledStripeRef.current = stripePi;
      if (stripeRedirectStatus === "failed") {
        api
          .post(`/payments/stripe/fail${querySuffix}`, {
            order_id: order.id,
            stripe_payment_intent_id: stripePi,
            reason: "Stripe 3DS or payment authorization failed",
          })
          .then(() => {
            pushToast("Stripe payment failed. Retry below.", "error");
            refetch();
          })
          .catch(() => {});
        return;
      }
      api
        .post(`/payments/stripe/verify${querySuffix}`, {
          order_id: order.id,
          stripe_payment_intent_id: stripePi,
          payment_method: "stripe",
        })
        .then((res) => {
          if (res.data.payment_status === "CONFIRMED") {
            pushToast("Stripe payment verified! Token issued.", "success");
          } else {
            pushToast("Stripe payment is processing. Updating automatically...", "info");
          }
          refetch();
          refetchReceipt();
        })
        .catch((err) => pushToast(getApiError(err, "Stripe PaymentIntent verification pending"), "info"));
      return;
    }
    if (stripeSid && handledStripeRef.current !== stripeSid) {
      handledStripeRef.current = stripeSid;
      api
        .post(`/payments/stripe/verify${querySuffix}`, {
          order_id: order.id,
          stripe_session_id: stripeSid,
          payment_method: "card",
        })
        .then(() => {
          pushToast("Stripe payment verified! Token issued.", "success");
          refetch();
          refetchReceipt();
        })
        .catch((err) => pushToast(getApiError(err, "Stripe session verification pending webhook"), "info"));
    }
  }, [searchParams, order, querySuffix, refetch, refetchReceipt, pushToast]);

  // Real-time stream + WS handled by useRealtimeSync above

  const handleConfirmCancelOrder = async () => {
    if (!order) return;
    setBusy(true);
    try {
      await api.post(`/orders/${order.id}/cancel${querySuffix}`, {
        reason: "Cancelled by customer before preparation",
      });
      pushToast("Order cancelled (payment record retained per policy)", "info");
      setConfirmCancelOpen(false);
      refetch();
    } catch (err) {
      pushToast(getApiError(err, "Cannot cancel order at this stage"), "error");
    } finally {
      setBusy(false);
    }
  };

  const handleRetryOnlinePayment = async (method: "razorpay" | "stripe") => {
    if (!order) return;
    setBusy(true);
    try {
      const res = await api.post<Order>(`/payments/retry/${order.id}${querySuffix}`, { payment_method: method });
      if (method === "stripe") {
        setStripeModalOrder(
          effectiveToken && !res.data.guest_access_token
            ? { ...res.data, guest_access_token: effectiveToken }
            : res.data
        );
        return;
      }
      if (res.data.razorpay_order_id && res.data.razorpay_key_id) {
        const opened = await openRazorpayModal({
          order: res.data,
          onVerified: () => {
            pushToast("Payment verified! Pickup token issued.", "success");
            refetch();
            refetchReceipt();
          },
          onError: (err) => {
            pushToast(getApiError(err, "Razorpay payment failed"), "error");
            refetch();
          },
          onDismiss: () => pushToast("Payment cancelled before completion.", "info"),
        });
        if (opened) return;
      }
      throw new Error("Live Razorpay checkout credentials are not configured in this environment.");
    } catch (err) {
      pushToast(getApiError(err, "Retry failed"), "error");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!order) return;
    const prev = prevTrackStateRef.current;
    if (!prev) {
      prevTrackStateRef.current = { status: order.status, delayed: order.delayed_minutes };
      return;
    }
    if (prev.status !== order.status) {
      playOrderAlertChime(order.status === "READY");
      const msg =
        order.status === "READY"
          ? `Token ${order.pickup_token_code || order.order_number} is READY at ${order.counter_name}!`
          : `Order ${order.order_number} is now ${order.status}`;
      pushToast(msg, order.status === "READY" ? "success" : "info");
      void showBrowserNotification(`Order ${order.status}`, msg, `/orders/${order.order_number}`);
    } else if (order.delayed_minutes > prev.delayed) {
      playOrderAlertChime(true);
      const msg = `Order ${order.order_number} delayed (+${order.delayed_minutes}m): ${order.delay_reason || ""}`;
      pushToast(msg, "info");
      void showBrowserNotification("Order Delayed", msg, `/orders/${order.order_number}`);
    }
    prevTrackStateRef.current = { status: order.status, delayed: order.delayed_minutes };
  }, [order, pushToast]);

  if (error) {
    return (
      <div className="mx-auto max-w-md px-4 py-12">
        <Card className="p-6 space-y-4">
          <h1 className="text-lg font-bold text-slate-900">Guest Order Access Verification</h1>
          <p className="text-xs text-slate-600">
            Enter your secure Guest Access Token (issued at checkout) or sign in to view order <strong>{orderNumber}</strong>.
          </p>
          <Input
            value={manualGuestToken}
            onChange={(e) => setManualGuestToken(e.target.value)}
            placeholder="CBG...."
          />
          <div className="flex gap-2">
            <Button onClick={() => refetch()}>Load Order</Button>
            <Button variant="outline" onClick={() => navigate("/login")}>
              Sign In
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  if (!order) {
    return <BrandLoadingState message="Loading order details..." />;
  }

  const currentStepIdx = STEPS.findIndex((s) => s.key === order.status);
  const isTerminalFail = ["CANCELLED", "REJECTED", "PAYMENT_FAILED"].includes(order.status);

  const handleReorderOrder = async () => {
    setBusy(true);
    try {
      let added = 0;
      for (const it of order.items) {
        if (!it.food_item_id) continue;
        const addons: { addon_id: string; quantity: number }[] = [];
        let spiceLevel: string | null = null;
        let sugarLevel: string | null = null;
        const removedIngredients: string[] = [];
        for (const c of it.customizations || []) {
          if (c.customization_type === "addon" && c.addon_id) addons.push({ addon_id: c.addon_id, quantity: c.quantity || 1 });
          else if (c.customization_type === "spice") spiceLevel = c.option_value;
          else if (c.customization_type === "sugar") sugarLevel = c.option_value;
          else if (c.customization_type === "remove_ingredient") removedIngredients.push(c.option_value);
        }
        try {
          await api.post("/carts/items", {
            canteen_id: order.canteen_id,
            food_item_id: it.food_item_id,
            variant_id: it.variant_id || null,
            quantity: it.quantity,
            spice_level: spiceLevel,
            sugar_level: sugarLevel,
            removed_ingredients: removedIngredients,
            addons,
            special_instructions: it.special_instructions || null,
          });
          added += 1;
        } catch {
          // continue adding remaining items
        }
      }
      if (added === 0) {
        pushToast("These dishes are currently unavailable to reorder", "error");
        return;
      }
      setSelectedCanteen(order.canteen_id);
      qc.invalidateQueries({ queryKey: ["cart", order.canteen_id] });
      pushToast(`Added ${added} item(s) to cart!`, "success");
      navigate("/checkout");
    } finally {
      setBusy(false);
    }
  };

  const startMs = new Date(order.confirmed_at || order.created_at).getTime();
  const targetMs = order.estimated_pickup_at
    ? new Date(order.estimated_pickup_at).getTime()
    : startMs + (order.estimated_prep_minutes + order.delayed_minutes) * 60000;
  const remainingSecs = Math.max(0, Math.floor((targetMs - nowMs) / 1000));
  const totalEtaSecs = Math.max(60, Math.floor((targetMs - startMs) / 1000));
  const progressPct =
    order.status === "READY" || order.status === "COMPLETED"
      ? 100
      : Math.min(95, Math.max(8, Math.round(((totalEtaSecs - remainingSecs) / totalEtaSecs) * 100)));

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
      {/* Status Banner */}
      <Card className="p-6 no-print">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <BrandLogo size="md" className="hidden sm:inline-flex mt-0.5" />
            <div>
              <div className="text-xs font-bold uppercase text-slate-400">
                {order.canteen_name} • {order.counter_name}
              </div>
              <h1 className="text-2xl font-extrabold text-slate-900">Order {order.order_number}</h1>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                <Badge tone={order.payment_status === "CONFIRMED" ? "green" : "amber"}>
                  Payment: {order.payment_status}
                </Badge>
                <Badge tone={isTerminalFail ? "red" : order.status === "READY" ? "green" : "blue"}>
                  Status: {order.status}
                </Badge>
                <RealtimeStatusBadge status={orderSyncStatus} lastSyncedAt={orderLastSyncedAt} />
                {order.delayed_minutes > 0 && (
                  <Badge tone="amber">
                    Delayed +{order.delayed_minutes}m ({order.delay_reason})
                  </Badge>
                )}
              </div>
            </div>
          </div>

          {order.pickup_token_code && (
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-[#380106] px-6 py-3 text-center text-white">
                <div className="text-[10px] font-bold uppercase tracking-widest text-[#fdedce]">Pickup Token</div>
                <div className="text-4xl font-black tracking-wider">{order.pickup_token_code}</div>
              </div>
              {order.qr_token_raw && (
                <div className="rounded-2xl border border-slate-200 bg-white p-2 text-center shadow-sm">
                  <QRCodeSVG value={order.qr_token_raw} size={74} />
                  <div className="text-[9px] font-bold text-slate-500 mt-0.5">Pickup QR</div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Live Progress Timeline */}
        {!isTerminalFail ? (
          <div className="mt-6 space-y-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-7">
              {STEPS.map((step, idx) => {
                const reached = currentStepIdx >= idx || (order.status === "PLACED" && idx <= 2);
                return (
                  <div
                    key={step.key}
                    className={`rounded-xl border p-2 text-center text-[11px] font-bold transition ${
                      reached
                        ? "border-emerald-500 bg-emerald-50 text-emerald-800"
                        : "border-slate-200 bg-slate-50 text-slate-400"
                    }`}
                  >
                    <div className="mx-auto mb-1 flex h-5 w-5 items-center justify-center rounded-full bg-white shadow-sm">
                      {reached ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <Clock className="h-3 w-3" />}
                    </div>
                    {step.label}
                  </div>
                );
              })}
            </div>
            {order.payment_status === "CONFIRMED" && order.status !== "COMPLETED" && (
              <div className="space-y-3">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 rounded-2xl border border-[#76010d]/15 bg-[#fdf8f0] p-3">
                  <div>
                    <div className="text-[10px] font-bold uppercase text-slate-500">Live Queue Position</div>
                    <div className="text-lg font-black text-[#5d010a]">
                      {order.status === "READY" ? "READY NOW" : order.queue_position ? `#${order.queue_position}` : "In Queue"}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-bold uppercase text-slate-500">Orders Ahead</div>
                    <div className="text-lg font-black text-slate-900">
                      {order.orders_ahead_count ?? 0} {order.orders_ahead_count === 1 ? "order" : "orders"}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-bold uppercase text-slate-500">Assigned Counter</div>
                    <div className="text-sm font-bold text-slate-900 truncate">
                      {order.counter_name || "Main Counter"}
                      {order.counter_queue_position && order.counter_queue_position > 0 ? ` (#${order.counter_queue_position})` : ""}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-bold uppercase text-slate-500">Dynamic Wait ETA</div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-lg font-black text-emerald-700">
                        {order.status === "READY"
                          ? "0 min"
                          : `~${order.dynamic_wait_minutes ?? order.estimated_prep_minutes + order.delayed_minutes} min`}
                      </span>
                      {order.is_priority && <Badge tone="red">PRIORITY</Badge>}
                    </div>
                  </div>
                </div>
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs font-semibold text-slate-600">
                    <span>
                      {order.status === "READY"
                        ? `Order ready at ${order.counter_name}! Present your QR token.`
                        : remainingSecs > 0
                        ? `Estimated ready in ${formatCountdown(remainingSecs)} (Target ${new Date(targetMs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })})`
                        : "Finishing preparation shortly — kitchen is finalizing your order."}
                    </span>
                    <span className="font-mono">{progressPct}%</span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
                    <div
                      className={`h-full transition-all duration-500 ${order.status === "READY" ? "bg-emerald-500" : "bg-[#76010d]"}`}
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="mt-5 flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            <XCircle className="h-6 w-6 shrink-0 text-red-600" />
            <div>
              <strong>Order {order.status}:</strong>{" "}
              {order.payment_status === "CONFIRMED"
                ? "Payment record retained. Contact the college finance office for any exceptional adjustment."
                : "No confirmed payment was recorded."}
            </div>
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
          <div className="text-xs text-slate-500 flex flex-wrap items-center gap-3">
            <span className="inline-flex items-center gap-1">
              <Utensils className="h-4 w-4" /> Est. Prep: ~{order.estimated_prep_minutes + order.delayed_minutes} mins
            </span>
            {notifPerm !== "granted" && notifPerm !== "unsupported" && (
              <button
                type="button"
                onClick={async () => {
                  const res = await enableBrowserPushNotifications();
                  setNotifPerm(Notification.permission);
                  if (res.granted) pushToast("Live Ready alerts enabled for your browser!", "success");
                }}
                className="inline-flex items-center gap-1 rounded-full bg-[#fdf8f0] border border-[#76010d]/25 px-2.5 py-0.5 text-[11px] font-bold text-[#76010d]"
              >
                <BellRing className="h-3 w-3" /> Enable Ready Alerts
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {order.payment_status !== "CONFIRMED" && ["PAYMENT_PENDING", "PAYMENT_FAILED"].includes(order.status) && (
              <>
                {order.status === "PAYMENT_PENDING" &&
                  order.payment_method === "stripe" &&
                  order.stripe_client_secret && (
                    <Button
                      size="sm"
                      variant="success"
                      disabled={busy}
                      onClick={() =>
                        setStripeModalOrder(
                          effectiveToken && !order.guest_access_token
                            ? { ...order, guest_access_token: effectiveToken }
                            : order
                        )
                      }
                    >
                      Complete Stripe Payment
                    </Button>
                  )}
                <Button size="sm" variant="primary" disabled={busy} onClick={() => void handleRetryOnlinePayment("razorpay")}>
                  <RefreshCw className="h-3.5 w-3.5" /> Pay via Razorpay UPI
                </Button>
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => void handleRetryOnlinePayment("stripe")}>
                  <RefreshCw className="h-3.5 w-3.5" /> Pay via Stripe
                </Button>
              </>
            )}
            {order.items.length > 0 && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void handleReorderOrder()}>
                <RotateCcw className="h-3.5 w-3.5" /> Reorder
              </Button>
            )}
            {["PAYMENT_PENDING", "PLACED", "ACCEPTED"].includes(order.status) && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirmCancelOpen(true)}>
                Cancel Order
              </Button>
            )}
            <Link to={`/support?order_id=${order.id}`}>
              <Button size="sm" variant="ghost">
                <HelpCircle className="h-4 w-4" /> Report Issue
              </Button>
            </Link>
          </div>
        </div>

        {order.status_history && order.status_history.length > 0 && (
          <div className="mt-4 border-t border-slate-100 pt-3">
            <div className="text-[11px] font-bold uppercase text-slate-400 mb-2">Order Activity Log</div>
            <div className="flex flex-wrap gap-2">
              {order.status_history.map((h) => (
                <div key={h.id} className="rounded-lg bg-slate-50 border border-slate-200/80 px-2.5 py-1 text-[11px] text-slate-700">
                  <strong>{h.to_status}</strong> •{" "}
                  {new Date(h.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                  {h.reason ? ` (${h.reason})` : ""}
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* Complete Printable Receipt & QR Code */}
      {receipt ? (
        <div className="space-y-2">
          <div className="flex items-center gap-2 px-1 no-print">
            <PackageCheck className="h-5 w-5 text-emerald-600" />
            <h2 className="text-lg font-extrabold text-slate-900">Official Digital Token Slip & Payment Receipt</h2>
          </div>
          <ReceiptSlip receipt={receipt} guestToken={effectiveToken} onPrinted={() => refetchReceipt()} />
        </div>
      ) : (
        <Card className="p-6 text-center text-sm text-slate-600 no-print">
          Pickup token, QR code, and complete receipt are generated automatically once backend payment confirmation succeeds.
        </Card>
      )}

      <ConfirmModal
        open={confirmCancelOpen}
        title={`Cancel Order ${order.order_number}?`}
        message="Are you sure you want to cancel this order? Note: Paid orders cannot be refunded through the CollegeBites app per college policy."
        confirmLabel="Confirm Cancellation"
        busy={busy}
        onCancel={() => setConfirmCancelOpen(false)}
        onConfirm={handleConfirmCancelOrder}
      />

      <StripePaymentModal
        order={stripeModalOrder}
        onClose={() => setStripeModalOrder(null)}
        onSuccess={() => {
          pushToast("Stripe payment verified! Pickup token issued.", "success");
          setStripeModalOrder(null);
          refetch();
          refetchReceipt();
        }}
        onProcessing={() => {
          pushToast("Payment is processing at Stripe. Tracking status...", "info");
          setStripeModalOrder(null);
          refetch();
        }}
        onFailed={() => {
          pushToast("Stripe payment cancelled or failed.", "info");
          setStripeModalOrder(null);
          refetch();
        }}
        onNavigateStatus={() => {
          setStripeModalOrder(null);
          refetch();
        }}
      />
    </div>
  );
};
