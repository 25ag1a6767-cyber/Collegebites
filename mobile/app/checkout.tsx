import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { getMobileApiError, mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";

export default function CheckoutScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const { user, selectedCanteenId, scannedQrCode, saveGuestOrderToken } = useMobileStore();

  const { data: college } = useQuery<any>({
    queryKey: ["m-college"],
    queryFn: async () => (await mobileApi.get("/canteens/college")).data,
  });

  const { data: canteens = [] } = useQuery<any[]>({
    queryKey: ["m-canteens"],
    queryFn: async () => (await mobileApi.get("/canteens")).data,
  });
  const activeCanteen = canteens.find((c) => c.id === selectedCanteenId) || canteens[0];
  const activeCanteenId = activeCanteen?.id;

  const { data: cart, refetch: refetchCart } = useQuery<any>({
    queryKey: ["m-cart", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await mobileApi.get(`/carts?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: slots = [] } = useQuery<any[]>({
    queryKey: ["m-slots", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await mobileApi.get(`/orders/slots/${activeCanteenId}`)).data,
  });

  const { data: loyalty } = useQuery<any>({
    queryKey: ["m-loyalty"],
    enabled: Boolean(user),
    queryFn: async () => (await mobileApi.get("/promotions/loyalty/me")).data,
  });

  const [couponInput, setCouponInput] = useState("");
  const [redeemPoints, setRedeemPoints] = useState(0);
  const [selectedSlotId, setSelectedSlotId] = useState<string>("");
  const [payMethod, setPayMethod] = useState<"razorpay" | "stripe" | "cash" | "pay_at_pickup">("razorpay");
  const [guestName, setGuestName] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpToken, setOtpToken] = useState<string | null>(null);
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [acceptedPolicy, setAcceptedPolicy] = useState(false);
  const [orderNotes, setOrderNotes] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [idemKey] = useState(() => `cb-mob-idem-${Date.now()}-${Math.random().toString(36).slice(2)}`);

  const updateQty = async (cartItemId: string, nextQty: number) => {
    try {
      await mobileApi.patch(`/carts/items/${cartItemId}`, { quantity: nextQty });
      refetchCart();
    } catch (e: unknown) {
      setErrorMsg(getMobileApiError(e, "Could not update item"));
    }
  };

  const applyCoupon = async () => {
    if (!activeCanteenId) return;
    setErrorMsg("");
    try {
      const res = await mobileApi.post("/carts/coupon", {
        canteen_id: activeCanteenId,
        coupon_code: couponInput.trim() || null,
      });
      qc.setQueryData(["m-cart", activeCanteenId], res.data);
      if (!res.data.coupon_valid && res.data.coupon_message) {
        setErrorMsg(res.data.coupon_message);
      }
    } catch (e: unknown) {
      setErrorMsg(getMobileApiError(e, "Coupon error"));
    }
  };

  const requestOtp = async () => {
    setErrorMsg("");
    try {
      const res = await mobileApi.post("/auth/otp/request", { target: guestPhone.trim(), purpose: "guest_checkout" });
      setDevOtp(res.data.dev_otp || null);
    } catch (e: unknown) {
      setErrorMsg(getMobileApiError(e, "Failed to send OTP"));
    }
  };

  const verifyOtp = async () => {
    setErrorMsg("");
    try {
      const res = await mobileApi.post("/auth/otp/verify", {
        target: guestPhone.trim(),
        purpose: "guest_checkout",
        code: otpCode.trim(),
      });
      setOtpToken(res.data.verification_token);
    } catch (e: unknown) {
      setErrorMsg(getMobileApiError(e, "OTP verification failed"));
    }
  };

  const placeOrder = async () => {
    setErrorMsg("");
    if (!acceptedPolicy) {
      setErrorMsg("Please accept the college payment policy first.");
      return;
    }
    if (!user) {
      if (!guestName.trim() || !guestPhone.trim()) {
        setErrorMsg("Enter guest name and mobile number.");
        return;
      }
      if (college?.guest_otp_required && !otpToken) {
        setErrorMsg("Verify guest OTP before placing order.");
        return;
      }
    }
    setBusy(true);
    try {
      const orderRes = await mobileApi.post(
        "/orders/checkout",
        {
          canteen_id: activeCanteenId,
          location_qr_code: scannedQrCode || null,
          pickup_slot_id: selectedSlotId || null,
          order_channel: "mobile",
          payment_method: payMethod,
          coupon_code: cart?.coupon_code || null,
          redeem_loyalty_points: user && redeemPoints > 0 ? redeemPoints : 0,
          idempotency_key: idemKey,
          guest_name: !user ? guestName.trim() : null,
          guest_phone: !user ? guestPhone.trim() : null,
          guest_otp_verification_token: !user ? otpToken : null,
          notes: orderNotes.trim() || null,
          accepted_policy: true,
        },
        { headers: { "X-Idempotency-Key": idemKey } }
      );
      const ord = orderRes.data;
      if (ord.guest_access_token) saveGuestOrderToken(ord.order_number, ord.guest_access_token);
      qc.invalidateQueries({ queryKey: ["m-cart", activeCanteenId] });
      router.push(`/order/${ord.order_number}`);
    } catch (e: unknown) {
      setErrorMsg(getMobileApiError(e, "Checkout failed"));
    } finally {
      setBusy(false);
    }
  };

  if (!cart || cart.items?.length === 0) {
    return (
      <View style={styles.emptyBox}>
        <Text style={styles.title}>Your Cart is Empty</Text>
        <Text style={{ color: "#64748b", fontSize: 13 }}>Add delicious items from any campus canteen first.</Text>
        <Pressable onPress={() => router.push("/")} style={styles.btnPrimary}>
          <Text style={styles.btnPrimaryTxt}>Browse Menu</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ gap: 12, paddingBottom: 40 }}>
      <Text style={styles.title}>Checkout • {cart.canteen_name}</Text>

      {cart.validation_errors?.length > 0 && (
        <View style={styles.warnBox}>
          {cart.validation_errors.map((err: string, idx: number) => (
            <Text key={idx} style={{ color: "#991b1b", fontSize: 12 }}>
              • {err}
            </Text>
          ))}
        </View>
      )}

      {cart.items.map((it: any) => (
        <View key={it.id} style={styles.rowCard}>
          <View style={{ flex: 1 }}>
            <Text style={styles.itemTxt}>
              {it.item_name} {it.variant_name ? `(${it.variant_name})` : ""}
            </Text>
            {it.customizations?.map((c: any, idx: number) => (
              <Text key={idx} style={{ fontSize: 11, color: "#64748b" }}>
                + {c.option_name}: {c.option_value}
              </Text>
            ))}
            {Boolean(it.special_instructions) && (
              <Text style={{ fontSize: 11, fontStyle: "italic", color: "#64748b" }}>Note: {it.special_instructions}</Text>
            )}
          </View>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Pressable onPress={() => updateQty(it.id, it.quantity - 1)} style={styles.qtyBtn}>
              <Text style={{ fontWeight: "800" }}>-</Text>
            </Pressable>
            <Text style={{ fontWeight: "800" }}>{it.quantity}</Text>
            <Pressable onPress={() => updateQty(it.id, it.quantity + 1)} style={styles.qtyBtn}>
              <Text style={{ fontWeight: "800" }}>+</Text>
            </Pressable>
            <Text style={[styles.itemTxt, { minWidth: 56, textAlign: "right" }]}>₹{it.line_subtotal}</Text>
          </View>
        </View>
      ))}

      {/* Coupon */}
      <View style={styles.box}>
        <Text style={styles.sub}>Promo Coupon</Text>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <TextInput style={[styles.input, { flex: 1 }]} value={couponInput} onChangeText={setCouponInput} placeholder="WELCOME10" />
          <Pressable onPress={applyCoupon} style={styles.btnSec}>
            <Text style={{ color: "#fff", fontWeight: "700" }}>Apply</Text>
          </Pressable>
        </View>
        {Number(cart.discount_amount) > 0 && (
          <Text style={{ color: "#059669", fontWeight: "700", fontSize: 12 }}>
            Discount applied: -₹{cart.discount_amount}
          </Text>
        )}
      </View>

      {/* Pickup Slot */}
      {slots.length > 0 && (
        <View style={styles.box}>
          <Text style={styles.sub}>Pickup Slot</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <Pressable
              onPress={() => setSelectedSlotId("")}
              style={[styles.slotPill, selectedSlotId === "" && styles.slotActive]}
            >
              <Text style={[styles.slotTxt, selectedSlotId === "" && { color: "#fff" }]}>ASAP</Text>
            </Pressable>
            {slots.map((s) => (
              <Pressable
                key={s.id}
                onPress={() => setSelectedSlotId(s.id)}
                style={[styles.slotPill, selectedSlotId === s.id && styles.slotActive]}
              >
                <Text style={[styles.slotTxt, selectedSlotId === s.id && { color: "#fff" }]}>
                  {String(s.start_time).slice(0, 5)}-{String(s.end_time).slice(0, 5)}
                </Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      )}

      {user && (loyalty?.points_balance || 0) > 0 && (
        <View style={styles.box}>
          <Text style={styles.sub}>Loyalty Points ({loyalty.points_balance} avail • 4 pts = ₹1)</Text>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Pressable
              onPress={() => setRedeemPoints(redeemPoints > 0 ? 0 : loyalty.points_balance)}
              style={[styles.btnSec, redeemPoints > 0 && { backgroundColor: "#ea580c" }]}
            >
              <Text style={{ color: "#fff", fontWeight: "700", fontSize: 12 }}>
                {redeemPoints > 0 ? `Redeeming ${redeemPoints} pts (-₹${(redeemPoints / 4).toFixed(2)})` : "Redeem Max Points"}
              </Text>
            </Pressable>
          </View>
        </View>
      )}

      {/* Payment Method */}
      <View style={styles.box}>
        <Text style={styles.sub}>Payment Method</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
          {[
            ...(activeCanteen?.allow_online_payment !== false && college?.razorpay_enabled !== false
              ? [{ id: "razorpay", label: "Razorpay" }]
              : []),
            ...(activeCanteen?.allow_online_payment !== false && college?.stripe_enabled !== false
              ? [{ id: "stripe", label: "Stripe Card" }]
              : []),
            ...(activeCanteen?.allow_cash_at_counter !== false ? [{ id: "cash", label: "Counter Cash" }] : []),
            ...(activeCanteen?.allow_pay_at_pickup ? [{ id: "pay_at_pickup", label: "Pay at Pickup" }] : []),
          ].map((m) => (
            <Pressable
              key={m.id}
              onPress={() => setPayMethod(m.id as any)}
              style={[styles.payOpt, payMethod === m.id && styles.payOptActive]}
            >
              <Text style={{ fontWeight: "700", fontSize: 12, color: payMethod === m.id ? "#fff" : "#0f172a" }}>
                {m.label}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>

      <TextInput style={styles.input} value={orderNotes} onChangeText={setOrderNotes} placeholder="Order notes (optional)" />

      {!user && (
        <View style={styles.box}>
          <Text style={styles.sub}>Guest Ordering (OTP Required)</Text>
          <TextInput style={styles.input} value={guestName} onChangeText={setGuestName} placeholder="Full Name" />
          <View style={{ flexDirection: "row", gap: 8 }}>
            <TextInput style={[styles.input, { flex: 1 }]} value={guestPhone} onChangeText={setGuestPhone} placeholder="+919876543210" />
            <Pressable onPress={requestOtp} style={styles.btnSec}>
              <Text style={{ color: "#fff", fontWeight: "700" }}>Send OTP</Text>
            </Pressable>
          </View>
          {devOtp && <Text style={{ fontSize: 12, color: "#b45309" }}>Dev OTP: {devOtp}</Text>}
          <View style={{ flexDirection: "row", gap: 8 }}>
            <TextInput style={[styles.input, { flex: 1 }]} value={otpCode} onChangeText={setOtpCode} placeholder="6-digit OTP" />
            <Pressable onPress={verifyOtp} style={styles.btnSec}>
              <Text style={{ color: "#fff", fontWeight: "700" }}>{otpToken ? "Verified ✓" : "Verify"}</Text>
            </Pressable>
          </View>
        </View>
      )}

      <View style={styles.totalBox}>
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <Text style={{ color: "#94a3b8", fontSize: 12 }}>Subtotal ₹{cart.subtotal_amount} • Tax ₹{cart.tax_amount}</Text>
        </View>
        <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 4 }}>
          <Text style={styles.totalLabel}>Total Payable</Text>
          <Text style={styles.totalVal}>₹{cart.total_amount}</Text>
        </View>
      </View>

      <View style={styles.policyRow}>
        <Switch value={acceptedPolicy} onValueChange={setAcceptedPolicy} />
        <Text style={{ flex: 1, fontSize: 12, color: "#475569" }}>
          {college?.cancellation_policy_text || "I acknowledge the college payment policy (no in-app refunds once confirmed)."}
        </Text>
      </View>

      {Boolean(errorMsg) && <Text style={{ color: "#dc2626", fontWeight: "700" }}>{errorMsg}</Text>}
      <Pressable
        disabled={busy || cart.validation_errors?.length > 0}
        onPress={placeOrder}
        style={[styles.btnPrimary, (busy || cart.validation_errors?.length > 0) && { backgroundColor: "#cbd5e1" }]}
      >
        <Text style={styles.btnPrimaryTxt}>
          {busy ? "Processing..." : `Proceed to Payment • ₹${cart.total_amount}`}
        </Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  emptyBox: { flex: 1, justifyContent: "center", alignItems: "center", padding: 24, gap: 12, backgroundColor: "#f8fafc" },
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16 },
  title: { fontSize: 20, fontWeight: "800", color: "#0f172a" },
  sub: { fontSize: 13, fontWeight: "800", color: "#0f172a" },
  warnBox: { backgroundColor: "#fee2e2", padding: 12, borderRadius: 10 },
  rowCard: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", backgroundColor: "#fff", padding: 12, borderRadius: 12, borderWidth: 1, borderColor: "#e2e8f0" },
  itemTxt: { fontWeight: "700", color: "#0f172a", fontSize: 13 },
  qtyBtn: { width: 28, height: 28, borderRadius: 8, backgroundColor: "#e2e8f0", alignItems: "center", justifyContent: "center" },
  totalBox: { backgroundColor: "#0f172a", padding: 14, borderRadius: 12 },
  totalLabel: { color: "#cbd5e1", fontWeight: "700", fontSize: 15 },
  totalVal: { color: "#fff", fontWeight: "900", fontSize: 18 },
  box: { backgroundColor: "#fff", padding: 12, borderRadius: 12, gap: 8, borderWidth: 1, borderColor: "#e2e8f0" },
  input: { backgroundColor: "#fff", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8 },
  btnSec: { backgroundColor: "#0f172a", borderRadius: 10, paddingHorizontal: 14, justifyContent: "center", paddingVertical: 8 },
  slotPill: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 16, backgroundColor: "#f1f5f9", marginRight: 6 },
  slotActive: { backgroundColor: "#ea580c" },
  slotTxt: { fontSize: 12, fontWeight: "700", color: "#334155" },
  payOpt: { flex: 1, paddingVertical: 9, borderRadius: 10, borderWidth: 1, borderColor: "#cbd5e1", alignItems: "center" },
  payOptActive: { backgroundColor: "#0f172a", borderColor: "#0f172a" },
  policyRow: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: "#fffbeb", padding: 10, borderRadius: 10 },
  btnPrimary: { backgroundColor: "#ea580c", borderRadius: 12, paddingVertical: 14, paddingHorizontal: 20, alignItems: "center" },
  btnPrimaryTxt: { color: "#fff", fontWeight: "800", fontSize: 15 },
});
