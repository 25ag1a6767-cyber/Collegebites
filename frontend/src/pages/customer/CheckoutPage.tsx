import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CreditCard, ShieldAlert, Trash2 } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { useOfflineStore } from "../../store/useOfflineStore";
import type { Canteen, CartSummary, CollegeSettings, Order } from "../../types";
import { BrandEmptyState, BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, InputPromptModal, Modal, Select, useToast } from "../../components/ui/Primitives";
import { StripePaymentModal } from "../../components/payments/StripePaymentModal";
import { openRazorpayModal } from "../../utils/razorpay";

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
    refetchInterval: 8000,
  });

  const { data: slots = [] } = useQuery<any[]>({
    queryKey: ["pickup-slots", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: async () => (await api.get(`/orders/slots/${activeCanteen!.id}`)).data,
  });

  const { data: loyalty } = useQuery<any>({
    queryKey: ["loyalty-me"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/promotions/loyalty/me")).data,
  });

  const [couponInput, setCouponInput] = useState("");

  const [redeemPoints, setRedeemPoints] = useState(0);
  const [slotId, setSlotId] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<"razorpay" | "stripe">("razorpay");
  const [orderType, setOrderType] = useState<"pickup" | "dine_in" | "qr_table">(
    selectedTableId ? "qr_table" : "pickup"
  );
  const [acceptedPolicy, setAcceptedPolicy] = useState(false);

  // Guest info & OTP state
  const [guestName, setGuestName] = useState("");
  const [guestEmail, setGuestEmail] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [devOtpHint, setDevOtpHint] = useState<string | null>(null);
  const [otpVerifiedToken, setOtpVerifiedToken] = useState<string | null>(null);
  const [otpSent, setOtpSent] = useState(false);
  const [otpStatusMsg, setOtpStatusMsg] = useState<string | null>(null);
  const [otpErrorMsg, setOtpErrorMsg] = useState<string | null>(null);

  const { data: otpCaps } = useQuery<{
    email_otp_enabled: boolean;
    sms_otp_enabled: boolean;
    dev_echo_enabled: boolean;
  }>({
    queryKey: ["otp-capabilities"],
    enabled: !user,
    queryFn: async () => (await api.get("/auth/otp/capabilities")).data,
  });

  // Gateway Checkout Sheet / Note modal state
  const [pendingOrder, setPendingOrder] = useState<Order | null>(null);
  const [noteModalItem, setNoteModalItem] = useState<{ id: string; note: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const isOnline = useOfflineStore((s) => s.isOnline);
  const getOrCreateCheckoutIdemKey = useAppStore((s) => s.getOrCreateCheckoutIdemKey);
  const clearCheckoutIdemKey = useAppStore((s) => s.clearCheckoutIdemKey);

  const updateItemQty = async (cartItemId: string, newQty: number) => {
    try {
      await api.patch(`/carts/items/${cartItemId}`, { quantity: newQty });
      refetchCart();
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const submitItemNote = async (nextNote: string) => {
    if (!noteModalItem) return;
    setBusy(true);
    try {
      await api.patch(`/carts/items/${noteModalItem.id}`, { special_instructions: nextNote.trim() || "" });
      refetchCart();
      setNoteModalItem(null);
      pushToast("Item customization updated", "success");
    } catch (err) {
      pushToast(getApiError(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const guestOtpTarget = guestEmail.trim() || guestPhone.trim();

  const sendGuestOtp = async () => {
    setOtpErrorMsg(null);
    setOtpStatusMsg(null);
    if (!guestOtpTarget) return pushToast("Enter your email address or mobile number first", "error");
    try {
      const res = await api.post("/auth/otp/request", { target: guestOtpTarget, purpose: "guest_checkout" });
      setOtpSent(true);
      setDevOtpHint(res.data.dev_otp || null);
      setOtpStatusMsg(res.data.message || "OTP sent!");
      pushToast(res.data.message || "OTP sent!", "success");
    } catch (err) {
      const msg = getApiError(err, "Failed to send OTP");
      setOtpErrorMsg(msg);
      pushToast(msg, "error");
    }
  };

  const verifyGuestOtp = async () => {
    setOtpErrorMsg(null);
    if (!guestOtpTarget) return pushToast("Enter your email or mobile number first", "error");
    try {
      const res = await api.post("/auth/otp/verify", {
        target: guestOtpTarget,
        purpose: "guest_checkout",
        code: otpCode.trim(),
      });
      setOtpVerifiedToken(res.data.verification_token);
      setOtpStatusMsg(null);
      pushToast("Verified for guest checkout!", "success");
    } catch (err) {
      const msg = getApiError(err, "Invalid OTP");
      setOtpErrorMsg(msg);
      pushToast(msg, "error");
    }
  };

  const placeOrder = async () => {
    if (!activeCanteen || !cart || cart.items.length === 0) return;
    if (!isOnline || (typeof navigator !== "undefined" && navigator.onLine === false)) {
      return pushToast("You are offline. Online payment & checkout require a live server connection.", "error");
    }
    if (!acceptedPolicy) {
      return pushToast("Please acknowledge the college cancellation & payment policy", "error");
    }
    const cartSig = `${activeCanteen.id}:${cart.total_amount}:${cart.items
      .map((i) => `${i.id}:${i.quantity}`)
      .join(",")}:${paymentMethod}`;
    const checkoutIdemKey = getOrCreateCheckoutIdemKey(cartSig);
    setBusy(true);
    try {
      const res = await api.post<Order>(
        "/orders/checkout",
        {
          canteen_id: activeCanteen.id,
          counter_id: selectedCounterId || null,
          table_id: selectedTableId || null,
          location_qr_code: scannedLocationQrCode || null,
          pickup_slot_id: slotId || null,
          order_type: orderType,
          order_channel: scannedLocationQrCode ? "qr" : "web",
          payment_method: paymentMethod,
          redeem_loyalty_points: user && redeemPoints > 0 ? redeemPoints : 0,
          idempotency_key: checkoutIdemKey,
          guest_name: !user ? guestName : null,
          guest_phone: !user && guestPhone.trim() ? guestPhone.trim() : null,
          guest_email: !user && guestEmail.trim() ? guestEmail.trim() : null,
          guest_otp_verification_token: !user ? otpVerifiedToken : null,
          accepted_policy: acceptedPolicy,
        },
        { headers: { "X-Idempotency-Key": checkoutIdemKey } }
      );

      clearCheckoutIdemKey();
      const ord = res.data;
      if (ord.guest_access_token) {
        saveGuestOrderToken(ord.order_number, ord.guest_access_token);
      }
      qc.invalidateQueries({ queryKey: ["cart", activeCanteen.id] });

      if (paymentMethod === "razorpay") {
        if (ord.razorpay_order_id && ord.razorpay_key_id) {
          const opened = await openRazorpayModal({
            order: ord,
            prefill: !user
              ? { name: guestName.trim() || undefined, email: guestEmail.trim() || undefined, contact: guestPhone.trim() || undefined }
              : { name: user.full_name, email: user.email || undefined, contact: user.phone || undefined },
            description: `${college?.college_name || "CollegeBites"} • ${ord.order_number}`,
            onVerified: (verified) => {
              pushToast(`Payment Verified! Token: ${verified.pickup_token_code}`, "success");
              setPendingOrder(null);
              navigate(`/orders/${verified.order_number}`);
            },
            onError: (err) => {
              pushToast(getApiError(err, "Razorpay payment failed"), "error");
              navigate(`/orders/${ord.order_number}`);
            },
            onDismiss: () => {
              pushToast("Payment cancelled. You can retry payment on your order page.", "info");
              navigate(`/orders/${ord.order_number}`);
            },
          });
          if (opened) return;
        }
        setPendingOrder(ord);
      } else {
        setPendingOrder(ord);
      }
    } catch (err) {
      pushToast(getApiError(err, "Checkout failed"), "error");
    } finally {
      setBusy(false);
    }
  };

  const launchGatewayCheckout = async () => {
    if (!pendingOrder) return;
    if (pendingOrder.payment_method === "stripe" && pendingOrder.stripe_checkout_url) {
      window.location.href = pendingOrder.stripe_checkout_url;
      return;
    }
    if (pendingOrder.razorpay_order_id && pendingOrder.razorpay_key_id) {
      const opened = await openRazorpayModal({
        order: pendingOrder,
        description: `${college?.college_name || "CollegeBites"} • ${pendingOrder.order_number}`,
        onVerified: (verified) => {
          pushToast(`Payment Verified! Pickup Token: ${verified.pickup_token_code}`, "success");
          setPendingOrder(null);
          navigate(`/orders/${verified.order_number}`);
        },
        onError: (err) => pushToast(getApiError(err, "Payment verification failed"), "error"),
        onDismiss: () => pushToast("Payment window closed before completion.", "info"),
      });
      if (opened) return;
    }
    pushToast("Gateway checkout URL/key is not configured in this environment.", "error");
  };

  const simulatePaymentFailure = async () => {
    if (!pendingOrder) return;
    setBusy(true);
    try {
      const endpoint = pendingOrder.payment_method === "stripe" ? "/payments/stripe/fail" : "/payments/razorpay/fail";
      const gTok = pendingOrder.guest_access_token
        ? `?guest_token=${encodeURIComponent(pendingOrder.guest_access_token)}`
        : "";
      await api.post(`${endpoint}${gTok}`, {
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
        <div className="mx-auto max-w-xl px-4 py-14">
          <BrandEmptyState
            title={pendingOrder ? "Complete Your Payment" : "Your Cart is Empty"}
            description={
              pendingOrder
                ? `Order ${pendingOrder.order_number} is created and awaiting payment verification.`
                : "Browse our campus canteens and add delicious items first."
            }
            action={!pendingOrder ? <Button onClick={() => navigate("/")}>Explore Menu</Button> : undefined}
          />
        </div>
      ) : (
        <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6 flex items-center gap-3">
        <BrandLogo size="sm" />
        <h1 className="text-2xl font-extrabold text-slate-900">Checkout • {activeCanteen?.name}</h1>
      </div>

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
                    onClick={() => setNoteModalItem({ id: it.id, note: it.special_instructions || "" })}
                    className="mt-0.5 text-[11px] font-semibold text-[#76010d] hover:underline"
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
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-bold text-slate-900">Guest Ordering Details</h2>
                <Badge tone="blue">
                  {otpCaps && !otpCaps.sms_otp_enabled && !otpCaps.dev_echo_enabled
                    ? "Email OTP Active (SMS Gateway Unconfigured)"
                    : "No Registration Needed"}
                </Badge>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-bold text-slate-700">Your Name *</label>
                  <Input value={guestName} onChange={(e) => setGuestName(e.target.value)} placeholder="Visitor / Student Name" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-bold text-slate-700">Mobile Number (Order Contact) *</label>
                  <Input value={guestPhone} onChange={(e) => setGuestPhone(e.target.value)} placeholder="+919876543210" />
                </div>
              </div>
              <div className="flex flex-wrap items-end gap-2">
                <div className="flex-1 min-w-[220px]">
                  <label className="mb-1 block text-xs font-bold text-slate-700">
                    Email Address for Verification OTP {otpCaps && !otpCaps.sms_otp_enabled ? "*" : "(Optional if using SMS)"}
                  </label>
                  <Input type="email" value={guestEmail} onChange={(e) => setGuestEmail(e.target.value)} placeholder="you@college.edu" />
                </div>
                <Button type="button" size="sm" variant="outline" onClick={sendGuestOtp}>
                  {otpSent ? "Resend OTP" : "Send OTP"}
                </Button>
              </div>
              {otpCaps && !otpCaps.sms_otp_enabled && !otpCaps.dev_echo_enabled && (
                <div className="text-[11px] text-slate-500">
                  Real Email OTP is active via college SMTP. Direct SMS OTP requires Twilio / SMS gateway credentials in server config.
                </div>
              )}
              {otpErrorMsg && (
                <div className="rounded-xl bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-800">{otpErrorMsg}</div>
              )}

              {college?.guest_otp_required && otpSent && !otpVerifiedToken && (
                <div className="rounded-xl bg-amber-50 border border-amber-200 p-3 space-y-2">
                  <div className="text-xs font-semibold text-amber-900">
                    {otpStatusMsg || "Enter 6-digit OTP to verify"} {devOtpHint ? `(Dev OTP: ${devOtpHint})` : ""}
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
              <div className="mb-2 flex items-center justify-between">
                <label className="text-xs font-bold text-slate-700">Online Payment Gateway</label>
                <Badge tone="green">Online Only • No Cash</Badge>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {activeCanteen?.allow_online_payment && (
                  <>
                    {(college?.razorpay_enabled ?? true) && (
                      <button
                        type="button"
                        onClick={() => setPaymentMethod("razorpay")}
                        className={`rounded-xl border p-3 text-left text-xs font-bold ${
                          paymentMethod === "razorpay" ? "border-[#76010d] bg-[#fdf8f0] text-[#380106]" : "border-slate-200"
                        }`}
                      >
                        <CreditCard className="h-4 w-4 mb-1 text-[#76010d]" />
                        Razorpay Online
                        <div className="font-normal text-slate-500">Direct UPI Apps (GPay, PhonePe, Paytm) & UPI QR</div>
                      </button>
                    )}
                    {(college?.stripe_enabled ?? true) && (
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
                    )}
                  </>
                )}
              </div>
            </div>
          </Card>
        </div>

        {/* Summary & Policy */}
        <div className="space-y-4">
          <Card className="p-5 space-y-4">
            <h2 className="font-bold text-slate-900">Bill Summary (Server Verified)</h2>

            {/* Promotional Coupon Code Application */}
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs space-y-2">
              <div className="font-bold text-slate-700">Apply Offer / Coupon Code</div>
              <div className="flex gap-2">
                <Input
                  value={couponInput}
                  onChange={(e) => setCouponInput(e.target.value.toUpperCase())}
                  placeholder={cart.coupon_code || "Enter code (e.g. FESTIVE20)"}
                  className="bg-white"
                />
                {cart.coupon_code ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      if (!activeCanteen) return;
                      try {
                        await api.delete(`/carts/coupon?canteen_id=${activeCanteen.id}`);
                        setCouponInput("");
                        refetchCart();
                        pushToast("Coupon removed", "info");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Remove
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={!couponInput.trim() || !activeCanteen}
                    onClick={async () => {
                      if (!activeCanteen) return;
                      try {
                        await api.post("/carts/coupon", {
                          canteen_id: activeCanteen.id,
                          coupon_code: couponInput.trim().toUpperCase(),
                        });
                        setCouponInput("");
                        refetchCart();
                        pushToast("Coupon applied to cart!", "success");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Apply
                  </Button>
                )}
              </div>
              {cart.coupon_message && (
                <div className={cart.coupon_valid ? "text-emerald-700 font-semibold" : "text-red-600 font-semibold"}>
                  {cart.coupon_message}
                </div>
              )}
            </div>

            {user && (loyalty?.points_balance || 0) > 0 && (
              <div className="rounded-xl border border-[#76010d]/25 bg-[#fdf8f0] p-3 text-xs space-y-1.5">
                <div className="flex items-center justify-between font-bold text-[#380106]">
                  <span>Redeem Loyalty Points</span>
                  <span>Avail: {loyalty.points_balance} pts (4 pts = ₹1)</span>
                </div>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={0}
                    max={loyalty.points_balance}
                    step={4}
                    value={redeemPoints}
                    onChange={(e) =>
                      setRedeemPoints(Math.min(loyalty.points_balance, Math.max(0, Number(e.target.value) || 0)))
                    }
                    className="w-28 bg-white"
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setRedeemPoints(redeemPoints > 0 ? 0 : loyalty.points_balance)}
                  >
                    {redeemPoints > 0 ? "Clear" : "Use Max"}
                  </Button>
                  {redeemPoints > 0 && (
                    <span className="font-bold text-emerald-700">-₹{(redeemPoints / 4).toFixed(2)} est.</span>
                  )}
                </div>
              </div>
            )}

            <div className="space-y-2 border-t border-slate-100 pt-3 text-sm">
              <div className="flex justify-between text-slate-600">
                <span>Subtotal</span>
                <span>₹{cart.subtotal_amount}</span>
              </div>
              {Number(cart.discount_amount) > 0 && (
                <div className="flex justify-between text-emerald-700 font-semibold">
                  <span>Offer Discount {cart.coupon_code ? `(${cart.coupon_code})` : ""}</span>
                  <span>-₹{cart.discount_amount}</span>
                </div>
              )}
              {redeemPoints > 0 && (
                <div className="flex justify-between text-emerald-700">
                  <span>Loyalty Points Discount ({redeemPoints} pts)</span>
                  <span>-₹{(redeemPoints / 4).toFixed(2)} est.</span>
                </div>
              )}
              <div className="flex justify-between text-slate-600">
                <span>Tax</span>
                <span>₹{cart.tax_amount}</span>
              </div>
              <div className="flex justify-between border-t border-slate-200 pt-2 text-lg font-extrabold text-slate-900">
                <span>Total Payable</span>
                <span>₹{Math.max(0, Number(cart.total_amount) - (redeemPoints > 0 ? redeemPoints / 4 : 0)).toFixed(2)}</span>
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

            {!isOnline && (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-semibold text-red-800">
                Offline Mode: Order submission and payment processing are locked until internet connectivity is restored to prevent unverified or duplicate charges.
              </div>
            )}

            <Button
              variant="primary"
              size="lg"
              className="w-full"
              disabled={busy || !isOnline || cart.validation_errors.length > 0}
              onClick={placeOrder}
            >
              {!isOnline
                ? "Reconnect to Pay & Place Order"
                : busy
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

      {/* Stripe Elements / Gateway Modal */}
      {pendingOrder?.payment_method === "stripe" && (
        <StripePaymentModal
          order={pendingOrder}
          onClose={() => {}}
          onSuccess={(verified) => {
            pushToast(`Payment Verified! Token: ${verified.pickup_token_code}`, "success");
            setPendingOrder(null);
            navigate(`/orders/${verified.order_number}`);
          }}
          onProcessing={(procOrder) => {
            pushToast("Payment is processing at Stripe. Tracking status...", "info");
            setPendingOrder(null);
            navigate(`/orders/${procOrder.order_number}`);
          }}
          onFailed={(failedOrder) => {
            pushToast("Payment marked failed. Slot released.", "error");
            setPendingOrder(null);
            navigate(`/orders/${failedOrder.order_number}`);
          }}
          onNavigateStatus={(ord) => {
            setPendingOrder(null);
            navigate(`/orders/${ord.order_number}`);
          }}
        />
      )}

      {/* Razorpay Checkout Modal */}
      <Modal
        open={Boolean(pendingOrder && pendingOrder.payment_method !== "stripe")}
        onClose={() => {}}
        title="Razorpay Direct UPI Checkout"
      >
        {pendingOrder && pendingOrder.payment_method !== "stripe" && (
          <div className="space-y-4" data-order-id={pendingOrder.id} data-order-number={pendingOrder.order_number}>
            <div className="rounded-xl bg-[#380106] p-4 text-white flex items-center justify-between">
              <div className="flex items-center gap-3">
                <BrandLogo size="sm" variant="dark" />
                <div>
                  <div className="text-xs text-[#fdedce]/80">CollegeBites • {pendingOrder.order_number}</div>
                  <div className="text-2xl font-extrabold">₹{pendingOrder.total_amount}</div>
                </div>
              </div>
              <Badge tone="amber">RZP: {pendingOrder.razorpay_order_id}</Badge>
            </div>

            <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 text-xs text-slate-600 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
              <span>
                {pendingOrder.razorpay_key_id
                  ? "Backend verifies cryptographic gateway HMAC/webhook signature before generating your Pickup Token, QR code & printable receipt."
                  : "Live gateway credentials are not configured in this environment. Track your pending order or cancel to retry."}
              </span>
            </div>

            <div className="flex flex-wrap gap-2">
              {pendingOrder.razorpay_key_id && (
                <Button variant="success" className="flex-1" disabled={busy} onClick={launchGatewayCheckout}>
                  Pay ₹{pendingOrder.total_amount} via UPI App / QR
                </Button>
              )}
              <Button
                variant={pendingOrder.razorpay_key_id ? "outline" : "primary"}
                className={pendingOrder.razorpay_key_id ? undefined : "flex-1"}
                disabled={busy}
                onClick={() => navigate(`/orders/${pendingOrder.order_number}`)}
              >
                View Order Status
              </Button>
              <Button variant="outline" disabled={busy} onClick={simulatePaymentFailure}>
                Cancel / Fail
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <InputPromptModal
        open={Boolean(noteModalItem)}
        title="Kitchen Preparation Instructions"
        label="Special Note for this Dish"
        defaultValue={noteModalItem?.note || ""}
        placeholder="e.g. Extra crispy, pack chutney separately"
        submitLabel="Save Note"
        busy={busy}
        onCancel={() => setNoteModalItem(null)}
        onSubmit={submitItemNote}
      />
    </>
  );
};
