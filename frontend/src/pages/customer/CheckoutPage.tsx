import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CreditCard, ShieldAlert, Smartphone, Trash2 } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, CartSummary, CollegeSettings, Order } from "../../types";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../components/ui/Primitives";

export const CheckoutPage: React.FC = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const {
    user,
    selectedCanteenId,
    selectedCounterId,
    selectedTableId,
    scannedLocationQrCode,
    saveGuestOrderToken,
  } = useAppStore();

  const { data: college } = useQuery<CollegeSettings>({
    queryKey: ["college-settings"],
    queryFn: async () => (await api.get("/canteens/college")).data,
  });

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const activeCanteen = useMemo(
    () => canteens.find((c) => c.id === selectedCanteenId) || canteens[0],
    [canteens, selectedCanteenId]
  );

  const { data: cart, refetch: refetchCart } = useQuery<CartSummary>({
    queryKey: ["cart", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: async () => (await api.get(`/carts?canteen_id=${activeCanteen!.id}`)).data,
  });

  const { data: slots = [] } = useQuery<any[]>({
    queryKey: ["pickup-slots", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: async () => (await api.get(`/orders/slots/${activeCanteen!.id}`)).data,
  });

  const [couponInput, setCouponInput] = useState("");
  const [slotId, setSlotId] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<"razorpay" | "stripe" | "cash" | "pay_at_pickup">("razorpay");
  const [orderType, setOrderType] = useState<"pickup" | "dine_in" | "qr_table">(
    selectedTableId ? "qr_table" : "pickup"
  );
  const [acceptedPolicy, setAcceptedPolicy] = useState(false);

  // Guest info & OTP state
  const [guestName, setGuestName] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [devOtpHint, setDevOtpHint] = useState<string | null>(null);
  const [otpVerifiedToken, setOtpVerifiedToken] = useState<string | null>(null);
  const [otpSent, setOtpSent] = useState(false);

  // Razorpay payment modal state
  const [pendingOrder, setPendingOrder] = useState<Order | null>(null);
  const [rzpMethod, setRzpMethod] = useState("upi");
  const [busy, setBusy] = useState(false);
  const [idemKey] = useState(() => "cb-idem-" + Date.now() + "-" + Math.random().toString(36).slice(2));

  const updateItemQty = async (cartItemId: string, newQty: number) => {
    try {
      await api.patch(`/carts/items/${cartItemId}`, { quantity: newQty });
      refetchCart();
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const updateItemNote = async (cartItemId: string, currentNote: string) => {
    const next = window.prompt("Update special preparation note (kitchen instructions):", currentNote);
    if (next === null) return;
    try {
      await api.patch(`/carts/items/${cartItemId}`, { special_instructions: next.trim() || "" });
      refetchCart();
      pushToast("Item customization updated", "success");
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const applyCoupon = async () => {
    if (!activeCanteen) return;
    try {
      const res = await api.post("/carts/coupon", {
        canteen_id: activeCanteen.id,
        coupon_code: couponInput.trim() || null,
      });
      qc.setQueryData(["cart", activeCanteen.id], res.data);
      if (res.data.coupon_message) {
        pushToast(res.data.coupon_message, res.data.coupon_valid ? "success" : "error");
      }
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const sendGuestOtp = async () => {
    if (!guestPhone.trim()) return pushToast("Enter your mobile number first", "error");
    try {
      const res = await api.post("/auth/otp/request", { target: guestPhone.trim(), purpose: "guest_checkout" });
      setOtpSent(true);
      setDevOtpHint(res.data.dev_otp || null);
      pushToast("OTP sent to your mobile number", "success");
    } catch (err) {
      pushToast(getApiError(err, "Failed to send OTP"), "error");
    }
  };

  const verifyGuestOtp = async () => {
    try {
      const res = await api.post("/auth/otp/verify", {
        target: guestPhone.trim(),
        purpose: "guest_checkout",
        code: otpCode.trim(),
      });
      setOtpVerifiedToken(res.data.verification_token);
      pushToast("Mobile verified!", "success");
    } catch (err) {
      pushToast(getApiError(err, "Invalid OTP"), "error");
    }
  };

  const placeOrder = async () => {
    if (!activeCanteen || !cart || cart.items.length === 0) return;
    if (!acceptedPolicy) {
      return pushToast("Please acknowledge the college cancellation & payment policy", "error");
    }
    setBusy(true);
    try {
      const res = await api.post<Order>("/orders/checkout", {
        canteen_id: activeCanteen.id,
        counter_id: selectedCounterId || null,
        table_id: selectedTableId || null,
        location_qr_code: scannedLocationQrCode || null,
        pickup_slot_id: slotId || null,
        order_type: orderType,
        order_channel: scannedLocationQrCode ? "qr" : "web",
        payment_method: paymentMethod,
        coupon_code: cart.coupon_code || null,
        idempotency_key: idemKey,
        guest_name: !user ? guestName : null,
        guest_phone: !user ? guestPhone : null,
        guest_otp_verification_token: !user ? otpVerifiedToken : null,
        accepted_policy: acceptedPolicy,
      });

      const ord = res.data;
      if (ord.guest_access_token) {
        saveGuestOrderToken(ord.order_number, ord.guest_access_token);
      }
      qc.invalidateQueries({ queryKey: ["cart", activeCanteen.id] });

      if (paymentMethod === "razorpay") {
        if (ord.razorpay_key_id && ord.razorpay_key_id !== "rzp_test_collegebites_local") {
          const loaded = await new Promise<boolean>((resolve) => {
            if ((window as any).Razorpay) return resolve(true);
            const script = document.createElement("script");
            script.src = "https://checkout.razorpay.com/v1/checkout.js";
            script.onload = () => resolve(true);
            script.onerror = () => resolve(false);
            document.body.appendChild(script);
          });
          if (loaded && (window as any).Razorpay) {
            const rzp = new (window as any).Razorpay({
              key: ord.razorpay_key_id,
              order_id: ord.razorpay_order_id,
              name: college?.college_name || "CollegeBites",
              description: `Order ${ord.order_number}`,
              handler: async (response: any) => {
                try {
                  const verified = await api.post<Order>("/payments/razorpay/verify", {
                    order_id: ord.id,
                    razorpay_order_id: response.razorpay_order_id,
                    razorpay_payment_id: response.razorpay_payment_id,
                    razorpay_signature: response.razorpay_signature,
                    payment_method: "upi",
                  });
                  pushToast(`Payment Verified! Token: ${verified.data.pickup_token_code}`, "success");
                  navigate(`/orders/${verified.data.order_number}`);
                } catch (err) {
                  pushToast(getApiError(err, "Razorpay signature verification failed"), "error");
                }
              },
              modal: {
                ondismiss: () => navigate(`/orders/${ord.order_number}`),
              },
            });
            rzp.open();
            return;
          }
        }
        setRzpMethod("upi");
        setPendingOrder(ord);
      } else if (paymentMethod === "stripe") {
        if (ord.stripe_checkout_url) {
          window.location.href = ord.stripe_checkout_url;
          return;
        }
        setRzpMethod("card");
        setPendingOrder(ord);
      } else {
        pushToast("Order placed! Complete payment at counter to generate pickup token.", "info");
        navigate(`/orders/${ord.order_number}`);
      }
    } catch (err) {
      pushToast(getApiError(err, "Checkout failed"), "error");
    } finally {
      setBusy(false);
    }
  };

  const signHmacHex = async (secret: string, message: string): Promise<string> => {
    const enc = new TextEncoder();
    const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const sigBuf = await crypto.subtle.sign("HMAC", key, enc.encode(message));
    return Array.from(new Uint8Array(sigBuf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  };

  const completeGatewayTestVerification = async () => {
    if (!pendingOrder) return;
    setBusy(true);
    try {
      let verified: { data: Order };
      if (pendingOrder.payment_method === "stripe" && pendingOrder.stripe_session_id) {
        const piId = "pi_web_" + Date.now();
        const sigHex = await signHmacHex(
          import.meta.env.VITE_STRIPE_TEST_SECRET || "sk_test_collegebites_local",
          `${pendingOrder.stripe_session_id}|${piId}`
        );
        verified = await api.post<Order>("/payments/stripe/verify", {
          order_id: pendingOrder.id,
          stripe_session_id: pendingOrder.stripe_session_id,
          stripe_payment_intent_id: piId,
          stripe_signature: sigHex,
          payment_method: rzpMethod,
        });
      } else if (pendingOrder.razorpay_order_id) {
        const paymentId = "pay_web_" + Date.now();
        const sigHex = await signHmacHex(
          import.meta.env.VITE_RAZORPAY_TEST_SECRET || "rzp_test_secret_collegebites_local",
          `${pendingOrder.razorpay_order_id}|${paymentId}`
        );
        verified = await api.post<Order>("/payments/razorpay/verify", {
          order_id: pendingOrder.id,
          razorpay_order_id: pendingOrder.razorpay_order_id,
          razorpay_payment_id: paymentId,
          razorpay_signature: sigHex,
          payment_method: rzpMethod,
        });
      } else {
        throw new Error("Missing gateway payment reference");
      }
      pushToast(`Payment Verified! Pickup Token: ${verified.data.pickup_token_code}`, "success");
      setPendingOrder(null);
      navigate(`/orders/${verified.data.order_number}`);
    } catch (err) {
      pushToast(getApiError(err, "Payment verification failed"), "error");
    } finally {
      setBusy(false);
    }
  };

  const simulatePaymentFailure = async () => {
    if (!pendingOrder) return;
    setBusy(true);
    try {
      const endpoint = pendingOrder.payment_method === "stripe" ? "/payments/stripe/fail" : "/payments/razorpay/fail";
      await api.post(endpoint, {
        order_id: pendingOrder.id,
        reason: "Customer cancelled payment on gateway",
      });
      pushToast("Payment marked failed. Slot released.", "error");
      setPendingOrder(null);
      navigate(`/orders/${pendingOrder.order_number}`);
    } catch (err) {
      pushToast(getApiError(err), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {!cart || cart.items.length === 0 ? (
        <div className="mx-auto max-w-xl px-4 py-14 text-center">
          <Card className="p-8 space-y-4">
            <h1 className="text-2xl font-extrabold text-slate-900">
              {pendingOrder ? "Complete Your Payment" : "Your Cart is Empty"}
            </h1>
            <p className="text-sm text-slate-600">
              {pendingOrder
                ? `Order ${pendingOrder.order_number} is created and awaiting payment verification.`
                : "Browse our campus canteens and add delicious items first."}
            </p>
            {!pendingOrder && <Button onClick={() => navigate("/")}>Explore Menu</Button>}
          </Card>
        </div>
      ) : (
        <div className="mx-auto max-w-6xl px-4 py-6">
      <h1 className="mb-6 text-2xl font-extrabold text-slate-900">Checkout • {activeCanteen?.name}</h1>

      {cart.validation_errors.length > 0 && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {cart.validation_errors.map((e, i) => (
            <div key={i}>• {e}</div>
          ))}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-5">
          {/* Items */}
          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900">Order Items ({cart.items.length})</h2>
            {cart.items.map((it) => (
              <div key={it.id} className="flex items-start justify-between gap-3 border-b border-slate-100 pb-3 last:border-none">
                <div>
                  <div className="font-bold text-sm text-slate-900">
                    {it.item_name} {it.variant_name ? `(${it.variant_name})` : ""}
                  </div>
                  <div className="text-xs text-slate-500">₹{it.unit_price} base</div>
                  {it.customizations.map((c, idx) => (
                    <div key={idx} className="text-[11px] text-slate-500">
                      + {c.option_name}: {c.option_value} {Number(c.total_price) > 0 ? `(₹${c.total_price})` : ""}
                    </div>
                  ))}
                  {it.special_instructions && (
                    <div className="text-[11px] italic text-slate-500">Note: {it.special_instructions}</div>
                  )}
                  <button
                    type="button"
                    onClick={() => updateItemNote(it.id, it.special_instructions || "")}
                    className="mt-0.5 text-[11px] font-semibold text-orange-600 hover:underline"
                  >
                    {it.special_instructions ? "Edit note" : "+ Add kitchen note"}
                  </button>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2 rounded-lg border border-slate-200 px-2 py-1 text-xs font-bold">
                    <button type="button" onClick={() => updateItemQty(it.id, it.quantity - 1)}>
                      -
                    </button>
                    <span>{it.quantity}</span>
                    <button type="button" onClick={() => updateItemQty(it.id, it.quantity + 1)}>
                      +
                    </button>
                  </div>
                  <span className="font-bold text-sm text-slate-900 w-16 text-right">₹{it.line_subtotal}</span>
                  <button
                    type="button"
                    onClick={() => updateItemQty(it.id, 0)}
                    className="text-slate-400 hover:text-red-600"
                    aria-label="Remove item"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </Card>

          {/* Guest Details + OTP */}
          {!user && (
            <Card className="p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="font-bold text-slate-900">Guest Ordering Details</h2>
                <Badge tone="blue">No Registration Needed</Badge>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-bold text-slate-700">Your Name *</label>
                  <Input value={guestName} onChange={(e) => setGuestName(e.target.value)} placeholder="Visitor / Student Name" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-bold text-slate-700">Mobile Number *</label>
                  <div className="flex gap-2">
                    <Input value={guestPhone} onChange={(e) => setGuestPhone(e.target.value)} placeholder="+919876543210" />
                    <Button type="button" size="sm" variant="outline" onClick={sendGuestOtp}>
                      Send OTP
                    </Button>
                  </div>
                </div>
              </div>

              {college?.guest_otp_required && otpSent && !otpVerifiedToken && (
                <div className="rounded-xl bg-amber-50 border border-amber-200 p-3 space-y-2">
                  <div className="text-xs font-semibold text-amber-900">
                    Enter 6-digit OTP to verify mobile {devOtpHint ? `(Dev OTP: ${devOtpHint})` : ""}
                  </div>
                  <div className="flex gap-2 max-w-xs">
                    <Input value={otpCode} onChange={(e) => setOtpCode(e.target.value)} placeholder="123456" maxLength={6} />
                    <Button type="button" size="sm" onClick={verifyGuestOtp}>
                      Verify
                    </Button>
                  </div>
                </div>
              )}

              {otpVerifiedToken && (
                <div className="inline-flex items-center gap-1.5 text-xs font-bold text-emerald-700">
                  <CheckCircle2 className="h-4 w-4" /> Mobile verified for guest checkout
                </div>
              )}
            </Card>
          )}

          {/* Pickup Slot & Payment Method */}
          <Card className="p-5 space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-bold text-slate-700">Order Type</label>
                <Select value={orderType} onChange={(e) => setOrderType(e.target.value as any)}>
                  <option value="pickup">Self Pickup at Counter</option>
                  <option value="dine_in">Dine-in</option>
                  {selectedTableId && <option value="qr_table">Table QR Order</option>}
                </Select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold text-slate-700">Pickup Slot (Optional)</label>
                <Select value={slotId} onChange={(e) => setSlotId(e.target.value)}>
                  <option value="">Immediate (~{cart.estimated_prep_minutes} mins)</option>
                  {slots.map((s) => (
                    <option key={s.id} value={s.id} disabled={s.available_count <= 0}>
                      {s.slot_date} {s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)} ({s.available_count} left)
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            <div>
              <label className="mb-2 block text-xs font-bold text-slate-700">Payment Method</label>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {activeCanteen?.allow_online_payment && (
                  <>
                    <button
                      type="button"
                      onClick={() => setPaymentMethod("razorpay")}
                      className={`rounded-xl border p-3 text-left text-xs font-bold ${
                        paymentMethod === "razorpay" ? "border-orange-600 bg-orange-50 text-orange-900" : "border-slate-200"
                      }`}
                    >
                      <CreditCard className="h-4 w-4 mb-1 text-orange-600" />
                      Razorpay Online
                      <div className="font-normal text-slate-500">UPI, Cards, Netbanking, Wallets</div>
                    </button>
                    <button
                      type="button"
                      onClick={() => setPaymentMethod("stripe")}
                      className={`rounded-xl border p-3 text-left text-xs font-bold ${
                        paymentMethod === "stripe" ? "border-indigo-600 bg-indigo-50 text-indigo-900" : "border-slate-200"
                      }`}
                    >
                      <CreditCard className="h-4 w-4 mb-1 text-indigo-600" />
                      Stripe Checkout
                      <div className="font-normal text-slate-500">Global Cards, Apple/Google Pay</div>
                    </button>
                  </>
                )}
                {activeCanteen?.allow_cash_at_counter && (
                  <button
                    type="button"
                    onClick={() => setPaymentMethod("cash")}
                    className={`rounded-xl border p-3 text-left text-xs font-bold ${
                      paymentMethod === "cash" ? "border-orange-600 bg-orange-50 text-orange-900" : "border-slate-200"
                    }`}
                  >
                    <Smartphone className="h-4 w-4 mb-1 text-slate-700" />
                    Cash at Counter
                    <div className="font-normal text-slate-500">Token issued after cashier confirms</div>
                  </button>
                )}
                {activeCanteen?.allow_pay_at_pickup && (
                  <button
                    type="button"
                    onClick={() => setPaymentMethod("pay_at_pickup")}
                    className={`rounded-xl border p-3 text-left text-xs font-bold ${
                      paymentMethod === "pay_at_pickup" ? "border-orange-600 bg-orange-50 text-orange-900" : "border-slate-200"
                    }`}
                  >
                    Pay at Pickup
                    <div className="font-normal text-slate-500">Token issued on payment</div>
                  </button>
                )}
              </div>
            </div>
          </Card>
        </div>

        {/* Summary & Policy */}
        <div className="space-y-4">
          <Card className="p-5 space-y-4">
            <h2 className="font-bold text-slate-900">Bill Summary (Server Verified)</h2>

            <div className="flex gap-2">
              <Input
                value={couponInput}
                onChange={(e) => setCouponInput(e.target.value)}
                placeholder="Coupon code (e.g. CAMPUS10)"
              />
              <Button type="button" variant="outline" size="sm" onClick={applyCoupon}>
                Apply
              </Button>
            </div>

            <div className="space-y-2 border-t border-slate-100 pt-3 text-sm">
              <div className="flex justify-between text-slate-600">
                <span>Subtotal</span>
                <span>₹{cart.subtotal_amount}</span>
              </div>
              <div className="flex justify-between text-emerald-700">
                <span>Discount {cart.coupon_code ? `(${cart.coupon_code})` : ""}</span>
                <span>-₹{cart.discount_amount}</span>
              </div>
              <div className="flex justify-between text-slate-600">
                <span>Tax</span>
                <span>₹{cart.tax_amount}</span>
              </div>
              <div className="flex justify-between border-t border-slate-200 pt-2 text-lg font-extrabold text-slate-900">
                <span>Total Payable</span>
                <span>₹{cart.total_amount}</span>
              </div>
            </div>

            {/* College Cancellation & Payment Policy */}
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950 space-y-2">
              <div className="flex items-center gap-1.5 font-bold">
                <ShieldAlert className="h-4 w-4 text-amber-700 shrink-0" /> College Payment & Cancellation Policy
              </div>
              <p className="leading-relaxed text-[11px]">{college?.cancellation_policy_text}</p>
              <label className="flex items-start gap-2 font-semibold cursor-pointer">
                <input
                  type="checkbox"
                  checked={acceptedPolicy}
                  onChange={(e) => setAcceptedPolicy(e.target.checked)}
                  className="mt-0.5 rounded border-amber-400"
                />
                <span>I acknowledge the college payment policy (no in-app refunds).</span>
              </label>
            </div>

            <Button
              variant="primary"
              size="lg"
              className="w-full"
              disabled={busy || cart.validation_errors.length > 0}
              onClick={placeOrder}
            >
              {busy
                ? "Processing..."
                : paymentMethod === "razorpay" || paymentMethod === "stripe"
                ? `Pay ₹${cart.total_amount}`
                : `Place Order • ₹${cart.total_amount}`}
            </Button>
          </Card>
        </div>
      </div>
    </div>
      )}

      {/* Razorpay / Stripe Payment Verification Sheet */}
      <Modal
        open={Boolean(pendingOrder)}
        onClose={() => {}}
        title={pendingOrder?.payment_method === "stripe" ? "Stripe Checkout" : "Razorpay Checkout"}
      >
        {pendingOrder && (
          <div className="space-y-4">
            <div className="rounded-xl bg-slate-900 p-4 text-white flex items-center justify-between">
              <div>
                <div className="text-xs text-slate-400">CollegeBites • {pendingOrder.order_number}</div>
                <div className="text-2xl font-extrabold">₹{pendingOrder.total_amount}</div>
              </div>
              <Badge tone="amber">
                {pendingOrder.payment_method === "stripe"
                  ? `Stripe: ${pendingOrder.stripe_session_id}`
                  : `RZP: ${pendingOrder.razorpay_order_id}`}
              </Badge>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-bold text-slate-700">
                {pendingOrder.payment_method === "stripe" ? "Select Stripe Method" : "Select Razorpay Method"}
              </label>
              <div className="grid grid-cols-2 gap-2">
                {(pendingOrder.payment_method === "stripe"
                  ? [
                      { id: "card", label: "Credit / Debit Card" },
                      { id: "apple_pay", label: "Apple Pay / Express" },
                      { id: "google_pay", label: "Google Pay" },
                      { id: "link", label: "Stripe Link" },
                    ]
                  : [
                      { id: "upi", label: "UPI (GPay / PhonePe)" },
                      { id: "card", label: "Debit / Credit Card" },
                      { id: "netbanking", label: "Net Banking" },
                      { id: "wallet", label: "Supported Wallets" },
                    ]
                ).map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setRzpMethod(m.id)}
                    className={`rounded-xl border px-3 py-2 text-xs font-bold ${
                      rzpMethod === m.id ? "border-orange-600 bg-orange-50 text-orange-900" : "border-slate-200"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 text-xs text-slate-600 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
              <span>
                Backend verifies cryptographic HMAC signature before generating your Pickup Token, QR code & printable receipt.
              </span>
            </div>

            <div className="flex gap-2">
              <Button variant="success" className="flex-1" disabled={busy} onClick={completeGatewayTestVerification}>
                Complete & Verify Payment
              </Button>
              <Button variant="outline" disabled={busy} onClick={simulatePaymentFailure}>
                Cancel / Fail
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
};
