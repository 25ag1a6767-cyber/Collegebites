import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { MonitorOff, RotateCcw, ShoppingBag } from "lucide-react";
import { api, getApiError } from "../../api/client";
import type { Canteen, FoodItem, Order, ReceiptSnapshot } from "../../types";
import { ReceiptSlip } from "../../components/receipt/ReceiptSlip";
import { Button, Card, useToast } from "../../components/ui/Primitives";
import { openRazorpayModal } from "../../utils/razorpay";

const LABELS: Record<string, { title: string; pay: string; empty: string }> = {
  en: { title: "Self-Service Ordering Kiosk", pay: "Pay & Print Token", empty: "Tap dishes to begin" },
  hi: { title: "सेल्फ-सर्विस ऑर्डरिंग किओस्क", pay: "भुगतान करें और टोकन प्रिंट करें", empty: "शुरू करने के लिए व्यंजन चुनें" },
  te: { title: "సెల్ఫ్-సర్వీస్ ఆర్డరింగ్ కియోస్క్", pay: "చెల్లించి టోకెన్ ప్రింట్ చేయండి", empty: "ప్రారంభించడానికి వంటకాలను ఎంచుకోండి" },
};

export const KioskPage: React.FC = () => {
  const { pushToast } = useToast();
  const [lang, setLang] = useState<"en" | "hi" | "te">("en");
  const [payMethod, setPayMethod] = useState<"razorpay" | "stripe">("razorpay");
  const [cartLines, setCartLines] = useState<{ item: FoodItem; quantity: number }[]>([]);
  const [pendingOrder, setPendingOrder] = useState<Order | null>(null);
  const [receipt, setReceipt] = useState<ReceiptSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [idleSeconds, setIdleSeconds] = useState(90);

  const { data: kioskStatus } = useQuery<any>({
    queryKey: ["kiosk-status"],
    queryFn: async () => (await api.get("/kiosk/status")).data,
  });

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const enabledDevice = kioskStatus?.devices?.find((d: any) => d.is_enabled) || kioskStatus?.devices?.[0];
  const canteenId = enabledDevice?.canteen_id || canteens[0]?.id || "";

  const { data: items = [] } = useQuery<FoodItem[]>({
    queryKey: ["kiosk-items", canteenId],
    enabled: Boolean(canteenId && kioskStatus?.kiosk_enabled),
    queryFn: async () => (await api.get(`/menus/canteens/${canteenId}/items?available_only=true`)).data,
  });

  // Periodic device heartbeat when kiosk active
  useEffect(() => {
    if (!kioskStatus?.kiosk_enabled || !enabledDevice?.id) return;
    const hb = setInterval(() => {
      api.post(`/kiosk/devices/${enabledDevice.id}/heartbeat`).catch(() => {});
    }, 30000);
    return () => clearInterval(hb);
  }, [kioskStatus?.kiosk_enabled, enabledDevice?.id]);

  // Idle timeout auto-reset
  useEffect(() => {
    const timer = setInterval(() => {
      setIdleSeconds((s) => {
        if (s <= 1) {
          setCartLines([]);
          setPendingOrder(null);
          setReceipt(null);
          return enabledDevice?.idle_timeout_seconds || 90;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [enabledDevice?.idle_timeout_seconds]);

  const resetActivity = () => setIdleSeconds(enabledDevice?.idle_timeout_seconds || 90);

  if (!kioskStatus?.kiosk_enabled) {
    return (
      <div className="min-h-screen bg-slate-900 text-white flex items-center justify-center p-6">
        <Card className="max-w-md p-8 text-center bg-slate-800 border-slate-700 text-white space-y-4">
          <MonitorOff className="mx-auto h-12 w-12 text-amber-400" />
          <h1 className="text-xl font-extrabold">Self-Service Kiosk Disabled</h1>
          <p className="text-xs text-slate-300">
            Touchscreen kiosk ordering remains disabled by default until campus kiosk hardware is installed and enabled by the College Administrator.
          </p>
          <Link to="/">
            <Button variant="primary">Return to Customer Web App</Button>
          </Link>
        </Card>
      </div>
    );
  }

  const fetchReceiptForOrder = async (ord: Order) => {
    const tokenParam = ord.guest_access_token ? `?guest_token=${encodeURIComponent(ord.guest_access_token)}` : "";
    const recRes = await api.get<ReceiptSnapshot>(`/tokens/receipts/${ord.order_number}${tokenParam}`);
    setReceipt(recRes.data);
  };

  const placeKioskOrder = async () => {
    if (!enabledDevice || cartLines.length === 0) return;
    resetActivity();
    setBusy(true);
    try {
      const res = await api.post<Order>("/kiosk/orders", {
        device_code: enabledDevice.device_code,
        canteen_id: canteenId,
        payment_method: payMethod,
        language: lang,
        items: cartLines.map((l) => ({ food_item_id: l.item.id, quantity: l.quantity })),
      });
      const ord = res.data;
      setCartLines([]);
      setPendingOrder(ord);
    } catch (err) {
      pushToast(getApiError(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const completeKioskPayment = async () => {
    if (!pendingOrder) return;
    setBusy(true);
    try {
      if (pendingOrder.payment_method === "stripe") {
        if (pendingOrder.stripe_checkout_url) {
          window.location.href = pendingOrder.stripe_checkout_url;
          return;
        }
        throw new Error("Stripe gateway session URL is unavailable in this environment.");
      }
      if (pendingOrder.razorpay_order_id && pendingOrder.razorpay_key_id) {
        const opened = await openRazorpayModal({
          order: pendingOrder,
          description: `Kiosk Order ${pendingOrder.order_number}`,
          onVerified: async (confirmed) => {
            await fetchReceiptForOrder(confirmed);
            setPendingOrder(null);
            pushToast(`Token ${confirmed.pickup_token_code || ""} ready! Printing slip.`, "success");
          },
          onError: (err) => pushToast(getApiError(err, "Payment verification failed"), "error"),
        });
        if (opened) return;
      }
      throw new Error("Live payment gateway keys are not configured for kiosk checkout.");
    } catch (err) {
      pushToast(getApiError(err, "Payment gateway unavailable"), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-100 p-6 space-y-5" onClick={resetActivity}>
      <div className="flex items-center justify-between rounded-2xl bg-slate-900 p-4 text-white">
        <div>
          <h1 className="text-2xl font-black">{LABELS[lang].title}</h1>
          <div className="text-xs text-slate-400">Session auto-resets in {idleSeconds}s</div>
        </div>
        <div className="flex items-center gap-2">
          {(["en", "hi", "te"] as const).map((l) => (
            <Button key={l} size="sm" variant={lang === l ? "primary" : "outline"} onClick={() => setLang(l)}>
              {l.toUpperCase()}
            </Button>
          ))}
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setCartLines([]);
              setReceipt(null);
            }}
          >
            <RotateCcw className="h-4 w-4" /> Reset
          </Button>
        </div>
      </div>

      {receipt ? (
        <div className="space-y-4">
          <ReceiptSlip receipt={receipt} />
          <div className="text-center">
            <Button
              size="lg"
              onClick={() => {
                setReceipt(null);
                setPendingOrder(null);
                setCartLines([]);
              }}
            >
              Start Next Kiosk Order
            </Button>
          </div>
        </div>
      ) : pendingOrder ? (
        <Card className="mx-auto max-w-lg p-6 space-y-4 text-center">
          <div className="text-xs font-bold uppercase text-slate-500">Kiosk Order Created</div>
          <div className="text-2xl font-black text-slate-900">{pendingOrder.order_number}</div>
          <div className="text-3xl font-black text-orange-600">₹{pendingOrder.total_amount}</div>
          <div className="space-y-3">
            <div className="rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
              Complete {pendingOrder.payment_method.toUpperCase()} online payment to generate your printable pickup slip.
            </div>
            <Button size="lg" className="w-full" disabled={busy} onClick={completeKioskPayment}>
              {busy ? "Launching Gateway..." : "Launch Online Checkout & Print Slip"}
            </Button>
          </div>
          <Button
            variant="outline"
            onClick={() => {
              setPendingOrder(null);
              setCartLines([]);
            }}
          >
            New Order
          </Button>
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2 grid gap-4 sm:grid-cols-2">
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() =>
                  setCartLines((prev) => {
                    const idx = prev.findIndex((p) => p.item.id === item.id);
                    if (idx >= 0) {
                      const copy = [...prev];
                      copy[idx] = { ...copy[idx], quantity: copy[idx].quantity + 1 };
                      return copy;
                    }
                    return [...prev, { item, quantity: 1 }];
                  })
                }
                className="rounded-2xl bg-white p-5 text-left shadow-md border-2 border-transparent hover:border-orange-500 active:scale-[0.98]"
              >
                <div className="text-lg font-extrabold text-slate-900">{item.name}</div>
                <div className="text-xl font-black text-orange-600 mt-1">₹{item.base_price}</div>
              </button>
            ))}
          </div>

          <Card className="p-6 space-y-4">
            <h2 className="text-xl font-extrabold flex items-center gap-2">
              <ShoppingBag className="h-5 w-5 text-orange-600" /> Cart
            </h2>
            {cartLines.length === 0 ? (
              <div className="py-10 text-center text-slate-400">{LABELS[lang].empty}</div>
            ) : (
              <div className="space-y-3">
                {cartLines.map((l) => (
                  <div key={l.item.id} className="flex justify-between font-bold text-sm">
                    <span>
                      {l.quantity}× {l.item.name}
                    </span>
                    <span>₹{(Number(l.item.base_price) * l.quantity).toFixed(2)}</span>
                  </div>
                ))}
                <div className="flex flex-wrap gap-1.5 pt-2">
                  {(["razorpay", "stripe"] as const).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setPayMethod(m)}
                      className={`rounded-lg px-2.5 py-1 text-xs font-bold uppercase border ${
                        payMethod === m ? "border-orange-600 bg-orange-50 text-orange-800" : "border-slate-200 text-slate-600"
                      }`}
                    >
                      {m}
                    </button>
                  ))}
                </div>
                <Button size="lg" className="w-full" disabled={busy} onClick={placeKioskOrder}>
                  {busy ? "Creating Order..." : LABELS[lang].pay}
                </Button>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
};
