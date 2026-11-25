import React, { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { z } from "zod";
import { authApi } from "../src/api/auth.api";
import { canteensApi } from "../src/api/canteens.api";
import { cartApi } from "../src/api/cart.api";
import { getMobileApiError } from "../src/api/client";
import { ordersApi } from "../src/api/orders.api";
import { useMobileStore } from "../src/store/useMobileStore";
import { BrandLogo } from "../src/components/BrandLogo";

const guestSchema = z
  .object({
    guestName: z.string().trim().min(2, "Guest name must be at least 2 characters."),
    guestPhone: z.string().trim().min(8, "Enter a valid mobile number (e.g. +919876543210)."),
    guestEmail: z.string().trim().optional().default(""),
  });

export default function CheckoutScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const { user, selectedCanteenId, scannedQrCode, saveGuestOrderToken } = useMobileStore();

  const { data: college } = useQuery<any>({
    queryKey: ["m-college"],
    queryFn: canteensApi.getCollegeSettings,
  });

  const { data: canteens = [] } = useQuery<any[]>({
    queryKey: ["m-canteens"],
    queryFn: canteensApi.listCanteens,
  });
  const activeCanteen = canteens.find((c) => c.id === selectedCanteenId) || canteens[0];
  const activeCanteenId = activeCanteen?.id;

  const { data: canteenDetail } = useQuery<any>({
    queryKey: ["m-canteen-detail", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: () => canteensApi.getCanteenDetail(activeCanteenId),
  });

  const { data: cart, refetch: refetchCart } = useQuery<any>({
    queryKey: ["m-cart", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: () => cartApi.getCart(activeCanteenId),
  });

  const { data: slots = [] } = useQuery<any[]>({
    queryKey: ["m-slots", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: () => ordersApi.getPickupSlots(activeCanteenId),
  });

  const [selectedCounterId, setSelectedCounterId] = useState<string>("");
  const [selectedSlotId, setSelectedSlotId] = useState<string>("");
  const payMethod = "razorpay" as const;
  const [guestName, setGuestName] = useState("");
  const [guestEmail, setGuestEmail] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [acceptedPolicy, setAcceptedPolicy] = useState(false);
  const [orderNotes, setOrderNotes] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [idemKey, setIdemKey] = useState(() => `cb-mob-idem-${Date.now()}-${Math.random().toString(36).slice(2)}`);

  const updateQty = async (cartItemId: string, nextQty: number) => {
    try {
      await cartApi.updateItem(cartItemId, { quantity: nextQty });
      refetchCart();
    } catch (e: unknown) {
      setErrorMsg(getMobileApiError(e, "Could not update item"));
    }
  };

  const placeOrder = async () => {
    setErrorMsg("");
    if (!activeCanteen?.is_open_now) {
      setErrorMsg("Selected canteen is currently closed or temporarily unavailable.");
      return;
    }
    if (!acceptedPolicy) {
      setErrorMsg("Please accept the college payment policy first.");
      return;
    }
    if (!user) {
      const parsed = guestSchema.safeParse({ guestName, guestPhone, guestEmail });
      if (!parsed.success) {
        setErrorMsg(parsed.error.issues[0]?.message || "Enter valid guest details.");
        return;
      }
    }
    setBusy(true);
    try {
      const ord = await ordersApi.checkout(
        {
          canteen_id: activeCanteenId,
          counter_id: selectedCounterId || null,
          location_qr_code: scannedQrCode || null,
          pickup_slot_id: selectedSlotId || null,
          order_channel: "mobile",
          payment_method: payMethod,
          idempotency_key: idemKey,
          guest_name: !user ? guestName.trim() : null,
          guest_phone: !user && guestPhone.trim() ? guestPhone.trim() : null,
          guest_email: !user && guestEmail.trim() ? guestEmail.trim() : null,
          notes: orderNotes.trim() || null,
          accepted_policy: true,
        },
        idemKey
      );
      if (ord.guest_access_token) saveGuestOrderToken(ord.order_number, ord.guest_access_token);
      setIdemKey(`cb-mob-idem-${Date.now()}-${Math.random().toString(36).slice(2)}`);
      qc.invalidateQueries({ queryKey: ["m-cart", activeCanteenId] });
      qc.invalidateQueries({ queryKey: ["m-orders"] });
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
        <BrandLogo size={56} />
        <Text style={styles.title}>Your Cart is Empty</Text>
        <Text style={{ color: "#64748b", fontSize: 13 }}>Add delicious items from any campus canteen first.</Text>
        <Pressable onPress={() => router.push("/")} style={styles.btnPrimary}>
          <Text style={styles.btnPrimaryTxt}>Browse Menu</Text>
        </Pressable>
      </View>
    );
  }

  const checkoutBlocked =
    busy ||
    (cart.validation_errors?.length || 0) > 0 ||
    !activeCanteen?.is_open_now;

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
              {it.item_name} {it.variant_name ? `(${it.variant_name})` : ""} • ₹{it.unit_price}
            </Text>
            {it.customizations?.map((c: any, idx: number) => (
              <Text key={idx} style={{ fontSize: 11, color: "#64748b" }}>
                + {c.option_name}: {c.option_value}
              </Text>
            ))}
            {Boolean(it.special_instructions) && (
              <Text style={{ fontSize: 11, fontStyle: "italic", color: "#64748b" }}>Note: {it.special_instructions}</Text>
            )}
            <Pressable onPress={() => updateQty(it.id, 0)}>
              <Text style={{ fontSize: 11, color: "#dc2626", fontWeight: "700", marginTop: 3 }}>Remove</Text>
            </Pressable>
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

      {/* Pickup Counter Selection */}
      {canteenDetail?.counters?.length > 0 && (
        <View style={styles.box}>
          <Text style={styles.sub}>Pickup Counter</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <Pressable
              onPress={() => setSelectedCounterId("")}
              style={[styles.slotPill, selectedCounterId === "" && styles.slotActive]}
            >
              <Text style={[styles.slotTxt, selectedCounterId === "" && { color: "#fff" }]}>Auto Assign</Text>
            </Pressable>
            {canteenDetail.counters
              .filter((ct: any) => ct.is_active !== false)
              .map((ct: any) => (
                <Pressable
                  key={ct.id}
                  onPress={() => setSelectedCounterId(ct.id)}
                  style={[styles.slotPill, selectedCounterId === ct.id && styles.slotActive]}
                >
                  <Text style={[styles.slotTxt, selectedCounterId === ct.id && { color: "#fff" }]}>{ct.name}</Text>
                </Pressable>
              ))}
          </ScrollView>
        </View>
      )}

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

      {/* Payment Method */}
      <View style={styles.box}>
        <Text style={styles.sub}>Online Payment Gateway (Razorpay Only • Cash Disabled)</Text>
        <View style={[styles.payOpt, styles.payOptActive]}>
          <Text style={{ fontWeight: "700", fontSize: 12, color: "#fff" }}>
            Razorpay Standard Checkout (UPI / Cards / Netbanking)
          </Text>
        </View>
      </View>

      <TextInput style={styles.input} value={orderNotes} onChangeText={setOrderNotes} placeholder="Order notes (optional)" />

      {!user && (
        <View style={styles.box}>
          <Text style={styles.sub}>Direct Guest Ordering Details</Text>
          <TextInput style={styles.input} value={guestName} onChangeText={setGuestName} placeholder="Full Name" />
          <TextInput
            style={styles.input}
            value={guestPhone}
            onChangeText={setGuestPhone}
            placeholder="Mobile Number (+919876543210)"
          />
          <TextInput
            style={styles.input}
            value={guestEmail}
            onChangeText={setGuestEmail}
            autoCapitalize="none"
            keyboardType="email-address"
            placeholder="Email Address (Optional for receipts)"
          />
        </View>
      )}

      <View style={styles.totalBox}>
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <Text style={{ color: "#fdedce", fontSize: 12 }}>Order Subtotal</Text>
          <Text style={{ color: "#fdedce", fontSize: 12, fontWeight: "700" }}>₹{cart.subtotal_amount}</Text>
        </View>
        <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 4 }}>
          <Text style={styles.totalLabel}>Final Payable Amount</Text>
          <Text style={styles.totalVal}>₹{cart.total_amount}</Text>
        </View>
        <Text style={{ color: "#cbd5e1", fontSize: 10, marginTop: 4 }}>
          Listed prices inclusive of applicable statutory taxes. No additional checkout tax or extra charges.
        </Text>
      </View>

      <View style={styles.policyRow}>
        <Switch value={acceptedPolicy} onValueChange={setAcceptedPolicy} />
        <Text style={{ flex: 1, fontSize: 12, color: "#475569" }}>
          {college?.cancellation_policy_text || "I acknowledge the college payment policy (no in-app refunds once confirmed)."}
        </Text>
      </View>

      {Boolean(errorMsg) && <Text style={{ color: "#dc2626", fontWeight: "700" }}>{errorMsg}</Text>}
      <Pressable
        disabled={checkoutBlocked}
        onPress={placeOrder}
        style={[styles.btnPrimary, checkoutBlocked && { backgroundColor: "#cbd5e1" }]}
      >
        <Text style={styles.btnPrimaryTxt}>
          {busy ? "Processing..." : `Proceed to Payment • ₹${cart.total_amount}`}
        </Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  emptyBox: { flex: 1, justifyContent: "center", alignItems: "center", padding: 24, gap: 12, backgroundColor: "#fdf8f0" },
  container: { flex: 1, backgroundColor: "#fdf8f0", padding: 16 },
  title: { fontSize: 20, fontWeight: "800", color: "#0f172a" },
  sub: { fontSize: 13, fontWeight: "800", color: "#0f172a" },
  warnBox: { backgroundColor: "#fee2e2", padding: 12, borderRadius: 10 },
  rowCard: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", backgroundColor: "#fff", padding: 12, borderRadius: 12, borderWidth: 1, borderColor: "#e7d7c9" },
  itemTxt: { fontWeight: "700", color: "#0f172a", fontSize: 13 },
  qtyBtn: { width: 28, height: 28, borderRadius: 8, backgroundColor: "#e2e8f0", alignItems: "center", justifyContent: "center" },
  totalBox: { backgroundColor: "#380106", padding: 14, borderRadius: 12 },
  totalLabel: { color: "#fdedce", fontWeight: "700", fontSize: 15 },
  totalVal: { color: "#fff", fontWeight: "900", fontSize: 18 },
  box: { backgroundColor: "#fff", padding: 12, borderRadius: 12, gap: 8, borderWidth: 1, borderColor: "#e7d7c9" },
  input: { backgroundColor: "#fff", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8 },
  btnSec: { backgroundColor: "#380106", borderRadius: 10, paddingHorizontal: 14, justifyContent: "center", paddingVertical: 8 },
  slotPill: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 16, backgroundColor: "#f1f5f9", marginRight: 6 },
  slotActive: { backgroundColor: "#76010d" },
  slotTxt: { fontSize: 12, fontWeight: "700", color: "#334155" },
  payOpt: { flex: 1, minWidth: 95, paddingVertical: 9, borderRadius: 10, borderWidth: 1, borderColor: "#cbd5e1", alignItems: "center" },
  payOptActive: { backgroundColor: "#380106", borderColor: "#380106" },
  policyRow: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: "#fffbeb", padding: 10, borderRadius: 10 },
  btnPrimary: { backgroundColor: "#76010d", borderRadius: 12, paddingVertical: 14, paddingHorizontal: 20, alignItems: "center" },
  btnPrimaryTxt: { color: "#fff", fontWeight: "800", fontSize: 15 },
});
