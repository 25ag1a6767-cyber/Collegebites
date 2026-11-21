import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";

export default function CheckoutScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const { user, selectedCanteenId, scannedQrCode, saveGuestOrderToken } = useMobileStore();

  const { data: canteens = [] } = useQuery<any[]>({
    queryKey: ["m-canteens"],
    queryFn: async () => (await mobileApi.get("/canteens")).data,
  });
  const activeCanteenId = selectedCanteenId || canteens[0]?.id;

  const { data: cart } = useQuery<any>({
    queryKey: ["m-cart", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await mobileApi.get(`/carts?canteen_id=${activeCanteenId}`)).data,
  });

  const [guestName, setGuestName] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpToken, setOtpToken] = useState<string | null>(null);
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [acceptedPolicy, setAcceptedPolicy] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const requestOtp = async () => {
    const res = await mobileApi.post("/auth/otp/request", { target: guestPhone, purpose: "guest_checkout" });
    setDevOtp(res.data.dev_otp || null);
  };

  const verifyOtp = async () => {
    const res = await mobileApi.post("/auth/otp/verify", {
      target: guestPhone,
      purpose: "guest_checkout",
      code: otpCode,
    });
    setOtpToken(res.data.verification_token);
  };

  const placeOrder = async () => {
    setErrorMsg("");
    if (!acceptedPolicy) {
      setErrorMsg("Please accept the college payment policy first.");
      return;
    }
    try {
      const orderRes = await mobileApi.post("/orders/checkout", {
        canteen_id: activeCanteenId,
        location_qr_code: scannedQrCode || null,
        order_channel: "mobile",
        payment_method: "razorpay",
        guest_name: !user ? guestName : null,
        guest_phone: !user ? guestPhone : null,
        guest_otp_verification_token: !user ? otpToken : null,
        accepted_policy: true,
      });
      const ord = orderRes.data;
      if (ord.guest_access_token) saveGuestOrderToken(ord.order_number, ord.guest_access_token);
      qc.invalidateQueries({ queryKey: ["m-cart", activeCanteenId] });
      router.push(`/order/${ord.order_number}`);
    } catch (e: any) {
      setErrorMsg(e?.response?.data?.detail || "Checkout failed");
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ gap: 12, paddingBottom: 40 }}>
      <Text style={styles.title}>Checkout</Text>
      {cart?.items?.map((it: any) => (
        <View key={it.id} style={styles.row}>
          <Text style={styles.itemTxt}>
            {it.quantity}x {it.item_name}
          </Text>
          <Text style={styles.itemTxt}>₹{it.line_subtotal}</Text>
        </View>
      ))}
      <View style={styles.totalBox}>
        <Text style={styles.totalLabel}>Total Payable (incl. tax)</Text>
        <Text style={styles.totalVal}>₹{cart?.total_amount || "0.00"}</Text>
      </View>

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

      <View style={styles.policyRow}>
        <Switch value={acceptedPolicy} onValueChange={setAcceptedPolicy} />
        <Text style={{ flex: 1, fontSize: 12, color: "#475569" }}>
          I acknowledge the college payment policy (no in-app refunds once confirmed).
        </Text>
      </View>

      {Boolean(errorMsg) && <Text style={{ color: "#dc2626", fontWeight: "700" }}>{errorMsg}</Text>}
      <Pressable onPress={placeOrder} style={styles.btnPrimary}>
        <Text style={styles.btnPrimaryTxt}>Proceed to Payment • ₹{cart?.total_amount || "0.00"}</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16 },
  title: { fontSize: 20, fontWeight: "800", color: "#0f172a" },
  sub: { fontSize: 14, fontWeight: "700", color: "#0f172a" },
  row: { flexDirection: "row", justifyContent: "space-between", backgroundColor: "#fff", padding: 12, borderRadius: 10 },
  itemTxt: { fontWeight: "700", color: "#0f172a" },
  totalBox: { flexDirection: "row", justifyContent: "space-between", backgroundColor: "#0f172a", padding: 14, borderRadius: 12 },
  totalLabel: { color: "#cbd5e1", fontWeight: "700" },
  totalVal: { color: "#fff", fontWeight: "900", fontSize: 18 },
  box: { backgroundColor: "#fff", padding: 14, borderRadius: 12, gap: 8 },
  input: { backgroundColor: "#f8fafc", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8 },
  btnSec: { backgroundColor: "#0f172a", borderRadius: 10, paddingHorizontal: 14, justifyContent: "center" },
  policyRow: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: "#fffbeb", padding: 10, borderRadius: 10 },
  btnPrimary: { backgroundColor: "#ea580c", borderRadius: 12, paddingVertical: 14, alignItems: "center" },
  btnPrimaryTxt: { color: "#fff", fontWeight: "800", fontSize: 15 },
});
