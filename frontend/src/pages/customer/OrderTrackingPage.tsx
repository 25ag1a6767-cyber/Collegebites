import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, HelpCircle, PackageCheck, Utensils, XCircle } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Order, ReceiptSnapshot } from "../../types";
import { ReceiptSlip } from "../../components/receipt/ReceiptSlip";
import { Badge, Button, Card, Input, useToast } from "../../components/ui/Primitives";

const STEPS = [
  { key: "PAYMENT_CONFIRMED", label: "Payment Verified" },
  { key: "PLACED", label: "Order Placed" },
  { key: "ACCEPTED", label: "Accepted" },
  { key: "PREPARING", label: "Preparing" },
  { key: "READY", label: "Ready for Pickup" },
  { key: "COMPLETED", label: "Handed Over" },
];

export const OrderTrackingPage: React.FC = () => {
  const { orderNumber } = useParams<{ orderNumber: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { guestOrderTokens } = useAppStore();

  const guestToken = searchParams.get("guest_token") || (orderNumber ? guestOrderTokens[orderNumber] : undefined);
  const [manualGuestToken, setManualGuestToken] = useState(guestToken || "");
  const effectiveToken = guestToken || manualGuestToken || undefined;
  const querySuffix = effectiveToken ? `?guest_token=${encodeURIComponent(effectiveToken)}` : "";

  const { data: order, error, refetch } = useQuery<Order>({
    queryKey: ["order", orderNumber, effectiveToken],
    enabled: Boolean(orderNumber),
    queryFn: async () => (await api.get(`/orders/${orderNumber}${querySuffix}`)).data,
    refetchInterval: 5000,
  });

  const { data: receipt, refetch: refetchReceipt } = useQuery<ReceiptSnapshot>({
    queryKey: ["receipt", orderNumber, effectiveToken],
    enabled: Boolean(order && order.payment_status === "CONFIRMED"),
    queryFn: async () => (await api.get(`/tokens/receipts/${orderNumber}${querySuffix}`)).data,
  });

  // WebSocket real-time updates
  useEffect(() => {
    if (!order?.id) return;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${proto}://${window.location.host}/api/v1/ws/orders/${order.id}`;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(wsUrl);
      ws.onmessage = () => {
        qc.invalidateQueries({ queryKey: ["order", orderNumber] });
        qc.invalidateQueries({ queryKey: ["receipt", orderNumber] });
      };
    } catch {
      // polling fallback handles it cleanly
    }
    return () => {
      ws?.close();
    };
  }, [order?.id, orderNumber, qc]);

  const handleCancelOrder = async () => {
    if (!order) return;
    if (!window.confirm("Cancel this order? Note: Paid orders cannot be refunded through CollegeBites.")) return;
    try {
      await api.post(`/orders/${order.id}/cancel${querySuffix}`, {
        reason: "Cancelled by customer before preparation",
      });
      pushToast("Order cancelled (payment record retained per policy)", "info");
      refetch();
    } catch (err) {
      pushToast(getApiError(err, "Cannot cancel order at this stage"), "error");
    }
  };

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
    return <div className="py-16 text-center text-sm text-slate-500">Loading order details...</div>;
  }

  const currentStepIdx = STEPS.findIndex((s) => s.key === order.status);
  const isTerminalFail = ["CANCELLED", "REJECTED", "PAYMENT_FAILED"].includes(order.status);

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
      {/* Status Banner */}
      <Card className="p-6 no-print">
        <div className="flex flex-wrap items-center justify-between gap-4">
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
              {order.delayed_minutes > 0 && (
                <Badge tone="amber">
                  Delayed +{order.delayed_minutes}m ({order.delay_reason})
                </Badge>
              )}
            </div>
          </div>

          {order.pickup_token_code && (
            <div className="rounded-2xl bg-slate-900 px-6 py-3 text-center text-white">
              <div className="text-[10px] font-bold uppercase tracking-widest text-orange-300">Pickup Token</div>
              <div className="text-4xl font-black tracking-wider">{order.pickup_token_code}</div>
            </div>
          )}
        </div>

        {/* Live Progress Timeline */}
        {!isTerminalFail ? (
          <div className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-6">
            {STEPS.map((step, idx) => {
              const reached = currentStepIdx >= idx || (order.status === "PLACED" && idx === 0);
              return (
                <div
                  key={step.key}
                  className={`rounded-xl border p-2.5 text-center text-xs font-bold transition ${
                    reached
                      ? "border-emerald-500 bg-emerald-50 text-emerald-800"
                      : "border-slate-200 bg-slate-50 text-slate-400"
                  }`}
                >
                  <div className="mx-auto mb-1 flex h-6 w-6 items-center justify-center rounded-full bg-white shadow-sm">
                    {reached ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <Clock className="h-3.5 w-3.5" />}
                  </div>
                  {step.label}
                </div>
              );
            })}
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
          <div className="text-xs text-slate-500 flex items-center gap-2">
            <Utensils className="h-4 w-4" /> Est. Ready: ~{order.estimated_prep_minutes} mins
          </div>
          <div className="flex flex-wrap gap-2">
            {["PAYMENT_PENDING", "PLACED", "ACCEPTED"].includes(order.status) && (
              <Button size="sm" variant="outline" onClick={handleCancelOrder}>
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
    </div>
  );
};
