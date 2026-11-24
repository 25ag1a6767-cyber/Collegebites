import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CreditCard, ShieldAlert, Trash2 } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { useOfflineStore } from "../../store/useOfflineStore";
import type { Canteen, CartSummary, CollegeSettings, Order } from "../../types";
import { BrandEmptyState, BrandLogo } from "../../components/branding/BrandLogo";
import { OtpVerificationBox } from "../../components/auth/OtpVerificationBox";
import { Badge, Button, Card, Input, InputPromptModal, Modal, Select, useToast } from "../../components/ui/Primitives";
import { openRazorpayModal, getPublicRazorpayKeyId } from "../../utils/razorpay";

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
    refetchInterval: () => (typeof navigator !== "undefined" && navigator.onLine === false ? false : 25_000),
  });

  const { data: slots = [] } = useQuery<any[]>({
    queryKey: ["pickup-slots", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: async () => (await api.get(`/orders/slots/${activeCanteen!.id}`)).data,
  });

  const [slotId, setSlotId] = useState("");
  const paymentMethod = "razorpay" as const;
  const [orderType, setOrderType] = useState<"pickup" | "dine_in" | "qr_table">(
    selectedTableId ? "qr_table" : "pickup"
  );
  const [acceptedPolicy, setAcceptedPolicy] = useState(false);

  // Guest info & live OTP state
  const [guestName, setGuestName] = useState("");
  const [guestEmail, setGuestEmail] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [otpVerifiedToken, setOtpVerifiedToken] = useState<string | null>(null);

  const { data: otpCaps } = useQuery<{
    email_otp_enabled: boolean;
    sms_otp_enabled: boolean;
    otp_expiry_seconds?: number;
    resend_cooldown_seconds?: number;
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

      const ordWithToken =
        ord.guest_access_token ? ord : { ...ord };
      if (ordWithToken.razorpay_order_id && getPublicRazorpayKeyId(ordWithToken)) {
        const opened = await openRazorpayModal({
          order: ordWithToken,
          prefill: !user
            ? {
                name: guestName.trim() || undefined,
                email: guestEmail.trim() || undefined,
                contact: guestPhone.trim() || undefined,
              }
            : { name: user.full_name, email: user.email || undefined, contact: user.phone || undefined },
          description: `${college?.college_name || "CollegeBites"} • ${ordWithToken.order_number}`,
          onVerified: (verified) => {
            pushToast(`Payment Verified! Token: ${verified.pickup_token_code}`, "success");
            setPendingOrder(null);
            navigate(`/orders/${verified.order_number}`);
          },
          onError: (err) => {
            pushToast(getApiError(err, "Razorpay payment failed"), "error");
            navigate(`/orders/${ordWithToken.order_number}`);
          },
          onDismiss: () => {
            pushToast("Razorpay checkout closed. You can complete or retry payment on your order page.", "info");
            navigate(`/orders/${ordWithToken.order_number}`);
          },
        });
        if (opened) return;
      }
      setPendingOrder(ordWithToken);
    } catch (err) {
      pushToast(getApiError(err, "Checkout failed"), "error");
    } finally {
      setBusy(false);
    }
  };

  const launchGatewayCheckout = async () => {
    if (!pendingOrder) return;
    if (pendingOrder.razorpay_order_id && getPublicRazorpayKeyId(pendingOrder)) {
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
    pushToast("Razorpay public key is not configured in this environment.", "error");
  };

  const simulatePaymentFailure = async () => {
    if (!pendingOrder) return;
    setBusy(true);
    try {
      const gTok = pendingOrder.guest_access_token
        ? `?guest_token=${encodeURIComponent(pendingOrder.guest_access_token)}`
        : "";
      await api.post(`/payments/razorpay/fail${gTok}`, {
        order_id: pendingOrder.id,
        razorpay_order_id: pendingOrder.razorpay_order_id,
        reason: "Customer cancelled payment on Razorpay gateway",
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

          {/* Guest Details + Live OTP */}
          {!user && (
            <Card className="p-5 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-bold text-slate-900">Guest Ordering Details</h2>
                <Badge tone="blue">
                  {otpCaps && !otpCaps.sms_otp_enabled
                    ? "Live Email OTP Verification"
                    : "Live OTP Verification"}
                </Badge>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-bold text-slate-700">Your Name *</label>
                  <Input value={guestName} onChange={(e) => setGuestName(e.target.value)} placeholder="Visitor / Student Name" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-bold text-slate-700">Mobile Number (Order Contact) *</label>
                  <Input
                    value={guestPhone}
                    onChange={(e) => {
                      setGuestPhone(e.target.value);
                      if (!guestEmail.trim()) setOtpVerifiedToken(null);
                    }}
                    placeholder="+919876543210"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold text-slate-700">
                  Email Address for Verification OTP {otpCaps && !otpCaps.sms_otp_enabled ? "*" : "(Recommended)"}
                </label>
                <Input
                  type="email"
                  value={guestEmail}
                  onChange={(e) => {
                    setGuestEmail(e.target.value);
                    setOtpVerifiedToken(null);
                  }}
                  placeholder="you@college.edu"
                />
              </div>

              {college?.guest_otp_required && (
                <OtpVerificationBox
                  target={guestOtpTarget}
                  purpose="guest_checkout"
                  verifiedToken={otpVerifiedToken}
                  onVerified={(tok) => {
                    setOtpVerifiedToken(tok);
                    pushToast("Guest OTP verified!", "success");
                  }}
                  verifyButtonLabel="Verify for Checkout"
                />
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
                <Badge tone="green">Razorpay Verified • Online Only</Badge>
              </div>
              {activeCanteen?.allow_online_payment && (college?.razorpay_enabled ?? true) ? (
                <div className="rounded-xl border border-[#76010d] bg-[#fdf8f0] p-3.5 text-left text-xs font-bold text-[#380106]">
                  <div className="flex items-center gap-2">
                    <CreditCard className="h-4 w-4 text-[#76010d]" />
                    <span>Razorpay Standard Checkout</span>
                  </div>
                  <div className="mt-1 font-normal text-slate-600">
                    UPI Apps (GPay, PhonePe, Paytm), UPI QR, Cards &amp; Netbanking • Server-verified HMAC signature
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">
                  Razorpay online checkout is currently disabled for this canteen.
                </div>
              )}
            </div>
          </Card>
        </div>

        {/* Summary & Policy */}
        <div className="space-y-4">
          <Card className="p-5 space-y-4">
            <h2 className="font-bold text-slate-900">Bill Summary (Server Verified)</h2>

            <div className="space-y-2 border-t border-slate-100 pt-3 text-sm">
              <div className="flex justify-between text-slate-600">
                <span>Order Subtotal</span>
                <span>₹{cart.subtotal_amount}</span>
              </div>
              <div className="flex justify-between border-t border-slate-200 pt-2 text-lg font-extrabold text-slate-900">
                <span>Final Payable Amount</span>
                <span>₹{cart.total_amount}</span>
              </div>
              <p className="text-[11px] text-slate-500">
                Listed prices are inclusive of applicable statutory taxes. No additional checkout tax or extra charges.
              </p>
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
                : `Pay ₹${cart.total_amount} with Razorpay`}
            </Button>
          </Card>
        </div>
      </div>
    </div>
      )}

      {/* Razorpay Checkout Modal */}
      <Modal
        open={Boolean(pendingOrder)}
        onClose={() => {}}
        title="Razorpay Online Checkout"
      >
        {pendingOrder && (
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
                {getPublicRazorpayKeyId(pendingOrder)
                  ? "Backend independently verifies Razorpay HMAC signature and amount/currency before issuing your Pickup Token, QR code & digital receipt."
                  : "Razorpay public key is not configured in this environment. Track your pending order or cancel to release your slot."}
              </span>
            </div>

            <div className="flex flex-wrap gap-2">
              {getPublicRazorpayKeyId(pendingOrder) && (
                <Button variant="success" className="flex-1" disabled={busy} onClick={launchGatewayCheckout}>
                  Pay ₹{pendingOrder.total_amount} via Razorpay
                </Button>
              )}
              <Button
                variant={getPublicRazorpayKeyId(pendingOrder) ? "outline" : "primary"}
                className={getPublicRazorpayKeyId(pendingOrder) ? undefined : "flex-1"}
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
