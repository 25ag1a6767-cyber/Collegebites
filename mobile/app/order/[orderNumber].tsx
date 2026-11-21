import React, { useState } from "react";
import { Linking, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import QRCode from "react-native-qrcode-svg";
import { API_BASE_URL, mobileApi } from "../../src/api/client";
import { useMobileStore } from "../../src/store/useMobileStore";
import { hmacSha256Hex } from "../../src/utils/hmacSha256";

export default function OrderDetailScreen() {
  const { orderNumber } = useLocalSearchParams<{ orderNumber: string }>();
  const guestTokens = useMobileStore((s) => s.guestOrderTokens);
  const gToken = orderNumber ? guestTokens[orderNumber] : undefined;
  const suffix = gToken ? `?guest_token=${encodeURIComponent(gToken)}` : "";
  const [paying, setPaying] = useState(false);
  const [errMsg, setErrMsg] = useState("");

  const { data: order, refetch } = useQuery<any>({
    queryKey: ["m-order", orderNumber],
    enabled: Boolean(orderNumber),
    queryFn: async () => (await mobileApi.get(`/orders/${orderNumber}${suffix}`)).data,
    refetchInterval: 4000,
  });

  if (!order) {
    return (
      <View style={styles.center}>
        <Text>Loading order...</Text>
      </View>
    );
  }

  const verifyTestRazorpay = async () => {
    if (!order.razorpay_order_id) return;
    setPaying(true);
    setErrMsg("");
    try {
      const paymentId = `pay_mob_${Date.now()}`;
      const secret = process.env.EXPO_PUBLIC_RAZORPAY_TEST_SECRET || "rzp_test_secret_collegebites_local";
      const sig = hmacSha256Hex(secret, `${order.razorpay_order_id}|${paymentId}`);
      await mobileApi.post("/payments/razorpay/verify", {
        order_id: order.id,
        razorpay_order_id: order.razorpay_order_id,
        razorpay_payment_id: paymentId,
        razorpay_signature: sig,
        payment_method: "upi",
      });
      await refetch();
    } catch (e: any) {
      setErrMsg(e?.response?.data?.detail || "Payment verification failed");
    } finally {
      setPaying(false);
    }
  };

  const failTestRazorpay = async () => {
    setPaying(true);
    try {
      await mobileApi.post("/payments/razorpay/fail", {
        order_id: order.id,
        reason: "Customer cancelled payment in mobile app",
      });
      await refetch();
    } finally {
      setPaying(false);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ gap: 12, paddingBottom: 40 }}>
      <View style={styles.tokenBox}>
        <Text style={styles.smallLabel}>COLLEGEBITES • {order.canteen_name}</Text>
        <Text style={styles.ordNo}>{order.order_number}</Text>
        {order.pickup_token_code ? (
          <>
            <Text style={styles.tokenBig}>{order.pickup_token_code}</Text>
            {order.qr_token_raw && (
              <View style={styles.qrWrap}>
                <QRCode value={order.qr_token_raw} size={170} />
              </View>
            )}
            <Text style={styles.counterSub}>Counter: {order.counter_name} • {order.status}</Text>
          </>
        ) : (
          <Text style={{ color: "#fbbf24", fontWeight: "700", marginTop: 8 }}>
            Status: {order.status} (Payment: {order.payment_status})
          </Text>
        )}
      </View>

      {order.status === "PAYMENT_PENDING" && order.razorpay_order_id && (
        <View style={styles.payBox}>
          <Text style={styles.secTitle}>Complete Razorpay Payment (₹{order.total_amount})</Text>
          {Boolean(errMsg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{errMsg}</Text>}
          <Pressable disabled={paying} onPress={verifyTestRazorpay} style={styles.payBtn}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>{paying ? "Verifying..." : "Pay & Verify UPI Payment"}</Text>
          </Pressable>
          <Pressable disabled={paying} onPress={failTestRazorpay} style={styles.cancelBtn}>
            <Text style={{ color: "#0f172a", fontWeight: "700" }}>Simulate Payment Failure</Text>
          </Pressable>
        </View>
      )}

      <View style={styles.card}>
        <Text style={styles.secTitle}>Ordered Items</Text>
        {order.items?.map((it: any) => (
          <View key={it.id} style={styles.itemRow}>
            <Text style={{ fontWeight: "700" }}>
              {it.quantity}× {it.item_name} {it.variant_name ? `(${it.variant_name})` : ""}
            </Text>
            <Text style={{ fontWeight: "700" }}>₹{it.line_subtotal}</Text>
          </View>
        ))}
        <View style={styles.divider} />
        <View style={styles.itemRow}>
          <Text style={{ fontWeight: "900", fontSize: 16 }}>Total Paid</Text>
          <Text style={{ fontWeight: "900", fontSize: 16 }}>₹{order.total_amount}</Text>
        </View>
      </View>

      {order.payment_status === "CONFIRMED" && (
        <Pressable
          onPress={() =>
            Linking.openURL(`${API_BASE_URL}/tokens/receipts/${order.order_number}/pdf${suffix}`)
          }
          style={styles.pdfBtn}
        >
          <Text style={{ color: "#fff", fontWeight: "800" }}>Download Printable PDF Receipt</Text>
        </Pressable>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16 },
  tokenBox: { backgroundColor: "#0f172a", borderRadius: 18, padding: 20, alignItems: "center" },
  smallLabel: { color: "#fdba74", fontSize: 11, fontWeight: "800" },
  ordNo: { color: "#fff", fontSize: 14, fontWeight: "700", marginTop: 4 },
  tokenBig: { color: "#fff", fontSize: 44, fontWeight: "900", marginVertical: 10, letterSpacing: 2 },
  counterSub: { color: "#86efac", fontSize: 12, fontWeight: "700", marginTop: 10 },
  qrWrap: { backgroundColor: "#fff", padding: 12, borderRadius: 12 },
  payBox: { backgroundColor: "#fff", borderRadius: 14, padding: 16, gap: 10, borderWidth: 1, borderColor: "#fed7aa" },
  payBtn: { backgroundColor: "#059669", borderRadius: 10, padding: 12, alignItems: "center" },
  cancelBtn: { backgroundColor: "#e2e8f0", borderRadius: 10, padding: 10, alignItems: "center" },
  pdfBtn: { backgroundColor: "#ea580c", borderRadius: 12, padding: 14, alignItems: "center" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 16, gap: 8 },
  secTitle: { fontWeight: "800", fontSize: 15, marginBottom: 4 },
  itemRow: { flexDirection: "row", justifyContent: "space-between" },
  divider: { height: 1, backgroundColor: "#e2e8f0", marginVertical: 6 },
});
