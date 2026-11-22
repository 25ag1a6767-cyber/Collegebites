import React, { useEffect, useState } from "react";
import { Linking, Platform, Pressable, ScrollView, Share, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "react-native-qrcode-svg";
import { API_BASE_URL, buildMobileWsUrl, getMobileApiError } from "../../src/api/client";
import { ordersApi } from "../../src/api/orders.api";
import { paymentsApi } from "../../src/api/payments.api";
import { tokensApi } from "../../src/api/tokens.api";
import { StripePayButton } from "../../src/components/StripePayButton";
import { useMobileStore } from "../../src/store/useMobileStore";

const STEPS = [
  { key: "CREATED", label: "Created" },
  { key: "PAYMENT_PENDING", label: "Paying" },
  { key: "PAYMENT_CONFIRMED", label: "Paid" },
  { key: "PLACED", label: "Placed" },
  { key: "ACCEPTED", label: "Accepted" },
  { key: "PREPARING", label: "Preparing" },
  { key: "READY", label: "Ready" },
  { key: "COMPLETED", label: "Collected" },
];

export default function OrderDetailScreen() {
  const { orderNumber } = useLocalSearchParams<{ orderNumber: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { accessToken, guestOrderTokens, cachedOrders, saveCachedOrder } = useMobileStore();
  const gToken = orderNumber ? guestOrderTokens[orderNumber] : undefined;
  const suffix = gToken ? `?guest_token=${encodeURIComponent(gToken)}` : "";
  const [paying, setPaying] = useState(false);
  const [errMsg, setErrMsg] = useState("");

  const {
    data: liveOrder,
    isError: orderIsError,
    error: orderError,
    refetch,
  } = useQuery<any>({
    queryKey: ["m-order", orderNumber],
    enabled: Boolean(orderNumber),
    queryFn: async () => {
      const data = await ordersApi.getOrder(String(orderNumber), gToken);
      if (orderNumber) saveCachedOrder(orderNumber, data);
      return data;
    },
    refetchInterval: 4000,
  });

  const order = liveOrder || (orderNumber ? cachedOrders[orderNumber] : null);
  const isOfflineCache = !liveOrder && Boolean(order);

  const { data: receipt } = useQuery<any>({
    queryKey: ["m-receipt", orderNumber],
    enabled: Boolean(order?.payment_status === "CONFIRMED" && orderNumber),
    queryFn: () => tokensApi.getReceipt(String(orderNumber), gToken),
  });

  // Real-time WebSocket updates
  useEffect(() => {
    if (!order?.id) return;
    if (!accessToken && !gToken) return;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(buildMobileWsUrl(`/ws/orders/${order.id}`, { token: accessToken, guestToken: gToken }));
      ws.onmessage = () => {
        qc.invalidateQueries({ queryKey: ["m-order", orderNumber] });
        qc.invalidateQueries({ queryKey: ["m-receipt", orderNumber] });
      };
    } catch {
      // polling fallback handles it
    }
    return () => ws?.close();
  }, [order?.id, orderNumber, accessToken, gToken, qc]);

  if (!order && orderIsError) {
    return (
      <View style={styles.center}>
        <Text style={{ fontWeight: "900", fontSize: 16, color: "#dc2626", marginBottom: 6 }}>Order Unavailable</Text>
        <Text style={{ color: "#475569", textAlign: "center", fontSize: 13, marginBottom: 14 }}>
          {getMobileApiError(orderError, "Could not load this order. Verify order number and guest token.")}
        </Text>
        <View style={{ flexDirection: "row", gap: 10 }}>
          <Pressable onPress={() => void refetch()} style={styles.payBtn}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>Retry</Text>
          </Pressable>
          <Pressable onPress={() => router.replace("/orders")} style={styles.cancelBtn}>
            <Text style={{ color: "#0f172a", fontWeight: "800" }}>Back to Orders</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  if (!order) {
    return (
      <View style={styles.center}>
        <Text>Loading order details...</Text>
      </View>
    );
  }

  const cancelStripePayment = async () => {
    setPaying(true);
    setErrMsg("");
    try {
      await paymentsApi.failStripe(
        { order_id: order.id, reason: "Customer cancelled Stripe payment in mobile app" },
        gToken
      );
      await refetch();
    } catch (e: unknown) {
      setErrMsg(getMobileApiError(e, "Could not update payment status"));
    } finally {
      setPaying(false);
    }
  };

  const cancelRazorpayPayment = async () => {
    setPaying(true);
    setErrMsg("");
    try {
      await paymentsApi.failRazorpay(
        { order_id: order.id, reason: "Customer cancelled payment in mobile app" },
        gToken
      );
      await refetch();
    } catch (e: unknown) {
      setErrMsg(getMobileApiError(e, "Could not update payment status"));
    } finally {
      setPaying(false);
    }
  };

  const retryPayment = async (method: "razorpay" | "stripe") => {
    setPaying(true);
    setErrMsg("");
    try {
      await paymentsApi.retryPayment(order.id, method, gToken);
      await refetch();
    } catch (e: unknown) {
      setErrMsg(getMobileApiError(e, "Could not restart payment"));
    } finally {
      setPaying(false);
    }
  };

  const cancelOrder = async () => {
    setErrMsg("");
    try {
      await ordersApi.cancelOrder(order.id, "Cancelled by customer from mobile app", gToken);
      await refetch();
    } catch (e: unknown) {
      setErrMsg(getMobileApiError(e, "Cannot cancel order at this stage"));
    }
  };

  const downloadOrShareReceipt = async () => {
    setErrMsg("");
    if (Platform.OS === "web") {
      try {
        const blob = await tokensApi.downloadReceiptPdfBlob(order.order_number, gToken);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `CollegeBites-${order.order_number}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
      } catch (e: unknown) {
        setErrMsg(getMobileApiError(e, "Could not download PDF receipt"));
      }
      return;
    }
    if (gToken) {
      await Linking.openURL(tokensApi.getGuestReceiptPdfUrl(order.order_number, gToken));
      return;
    }
    try {
      const lines = (order.items || [])
        .map((i: any) => `${i.quantity}x ${i.item_name} (₹${i.line_subtotal})`)
        .join("\n");
      await Share.share({
        message: `COLLEGEBITES RECEIPT\nOrder: ${order.order_number}\nPickup Token: ${order.pickup_token_code || "Pending"}\nCanteen: ${order.canteen_name} / ${order.counter_name}\nTotal Paid: ₹${order.total_amount}\n\nItems:\n${lines}`,
      });
    } catch {
      // user dismissed share sheet
    }
  };

  const stepIdx = STEPS.findIndex((s) => s.key === order.status);
  const isTerminalFail = ["CANCELLED", "REJECTED", "PAYMENT_FAILED"].includes(order.status);

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ gap: 12, paddingBottom: 40 }}>
      {isOfflineCache && (
        <View style={styles.offlineBanner}>
          <Text style={{ color: "#92400e", fontSize: 12, fontWeight: "700" }}>
            Showing cached offline token slip (network unavailable).
          </Text>
        </View>
      )}

      <View style={styles.tokenBox}>
        <Text style={styles.smallLabel}>COLLEGEBITES • {receipt?.college_name || order.canteen_name}</Text>
        <Text style={styles.ordNo}>{order.order_number}</Text>
        {order.pickup_token_code ? (
          <>
            <Text style={styles.tokenBig}>{order.pickup_token_code}</Text>
            {order.qr_token_raw && (
              <View style={styles.qrWrap}>
                <QRCode value={order.qr_token_raw} size={170} />
              </View>
            )}
            <Text style={styles.counterSub}>
              Counter: {order.counter_name} • {order.status}
              {order.estimated_prep_minutes ? ` • Est ${order.estimated_prep_minutes}m` : ""}
            </Text>
          </>
        ) : (
          <Text style={{ color: "#fbbf24", fontWeight: "700", marginTop: 8 }}>
            Status: {order.status} (Payment: {order.payment_status})
          </Text>
        )}
      </View>

      {isTerminalFail ? (
        <View style={styles.termBanner}>
          <Text style={{ color: "#991b1b", fontWeight: "800", fontSize: 13 }}>
            Order Status: {order.status} (Payment: {order.payment_status})
          </Text>
          <Text style={{ color: "#7f1d1d", fontSize: 12, marginTop: 3 }}>
            No in-app refunds are processed. Any payment records remain preserved in transaction history.
          </Text>
        </View>
      ) : (
        <View style={styles.timelineRow}>
          {STEPS.map((st, idx) => {
            const reached = stepIdx >= idx;
            return (
              <View key={st.key} style={[styles.stepPill, reached && styles.stepReached]}>
                <Text style={[styles.stepTxt, reached && { color: "#065f46" }]}>{st.label}</Text>
              </View>
            );
          })}
        </View>
      )}

      {order.status === "PAYMENT_PENDING" &&
        (order.stripe_payment_intent_id || order.stripe_session_id || order.payment_method === "stripe") && (
          <View style={styles.payBox}>
            <Text style={styles.secTitle}>Complete Stripe Payment (₹{order.total_amount})</Text>
            {Boolean(errMsg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{errMsg}</Text>}
            <StripePayButton
              order={order}
              guestToken={gToken}
              disabled={paying}
              onVerified={() => refetch()}
              onError={(msg) => setErrMsg(msg)}
            />
            <Pressable disabled={paying} onPress={cancelStripePayment} style={styles.cancelBtn}>
              <Text style={{ color: "#0f172a", fontWeight: "700" }}>Cancel Payment</Text>
            </Pressable>
          </View>
        )}

      {order.status === "PAYMENT_PENDING" && order.razorpay_order_id && (
        <View style={styles.payBox}>
          <Text style={styles.secTitle}>Complete Razorpay Payment (₹{order.total_amount})</Text>
          {Boolean(errMsg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{errMsg}</Text>}
          {order.razorpay_key_id ? (
            <Pressable
              onPress={() => {
                const webUrl = API_BASE_URL.replace(/\/api\/v1$/, "").replace(":8000", ":5173");
                Linking.openURL(`${webUrl}/orders/${order.order_number}${suffix}`);
              }}
              style={styles.payBtn}
            >
              <Text style={{ color: "#fff", fontWeight: "800" }}>Open Razorpay UPI Checkout</Text>
            </Pressable>
          ) : (
            <Text style={{ color: "#64748b", fontSize: 12 }}>
              Live Razorpay checkout credentials are not configured on the server for this environment.
            </Text>
          )}
          <Pressable disabled={paying} onPress={cancelRazorpayPayment} style={styles.cancelBtn}>
            <Text style={{ color: "#0f172a", fontWeight: "700" }}>Cancel Payment</Text>
          </Pressable>
        </View>
      )}

      {order.status === "PAYMENT_FAILED" && (
        <View style={styles.payBox}>
          <Text style={styles.secTitle}>Retry Online Payment (₹{order.total_amount})</Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable disabled={paying} onPress={() => retryPayment("razorpay")} style={[styles.payBtn, { flex: 1 }]}>
              <Text style={{ color: "#fff", fontWeight: "800" }}>Retry Razorpay</Text>
            </Pressable>
            <Pressable
              disabled={paying}
              onPress={() => retryPayment("stripe")}
              style={[styles.payBtn, { flex: 1, backgroundColor: "#4f46e5" }]}
            >
              <Text style={{ color: "#fff", fontWeight: "800" }}>Retry Stripe</Text>
            </Pressable>
          </View>
        </View>
      )}

      <View style={styles.card}>
        <Text style={styles.secTitle}>Complete Receipt Summary</Text>
        <Text style={{ fontSize: 11, color: "#64748b" }}>
          Customer: {receipt?.customer_name || order.guest_name || "Guest"} • Method: {order.payment_method} • Ref:{" "}
          {receipt?.payment_reference || "Pending"}
        </Text>
        {order.items?.map((it: any) => (
          <View key={it.id} style={{ gap: 2 }}>
            <View style={styles.itemRow}>
              <Text style={{ fontWeight: "700", flex: 1 }}>
                {it.quantity}× {it.item_name} {it.variant_name ? `(${it.variant_name})` : ""}
              </Text>
              <Text style={{ fontWeight: "700" }}>₹{it.line_subtotal}</Text>
            </View>
            {it.customizations?.map((c: any, idx: number) => (
              <Text key={idx} style={{ fontSize: 11, color: "#64748b", paddingLeft: 10 }}>
                • {c.option_name}: {c.option_value}
              </Text>
            ))}
          </View>
        ))}
        <View style={styles.divider} />
        <View style={styles.itemRow}>
          <Text style={{ fontSize: 12, color: "#64748b" }}>Subtotal / Discount / Tax</Text>
          <Text style={{ fontSize: 12, color: "#64748b" }}>
            ₹{order.subtotal_amount} / -₹{order.discount_amount} / ₹{order.tax_amount}
          </Text>
        </View>
        <View style={styles.itemRow}>
          <Text style={{ fontWeight: "900", fontSize: 16 }}>Total Paid</Text>
          <Text style={{ fontWeight: "900", fontSize: 16 }}>₹{order.total_amount}</Text>
        </View>
        <Text style={{ fontSize: 10, color: "#64748b", marginTop: 4 }}>
          Show your pickup token and QR code only after READY status. Each order can be collected once. No in-app refunds per college policy.
        </Text>
      </View>

      {Boolean(errMsg) && <Text style={{ color: "#dc2626", fontWeight: "700", fontSize: 12 }}>{errMsg}</Text>}

      {order.payment_status === "CONFIRMED" && (
        <Pressable onPress={downloadOrShareReceipt} style={styles.pdfBtn}>
          <Text style={{ color: "#fff", fontWeight: "800" }}>
            {Platform.OS === "web" || gToken ? "Download Printable PDF Receipt" : "Share / Save Digital Receipt"}
          </Text>
        </Pressable>
      )}

      <View style={{ flexDirection: "row", gap: 8 }}>
        {["PAYMENT_PENDING", "PLACED", "ACCEPTED"].includes(order.status) && (
          <Pressable onPress={cancelOrder} style={[styles.cancelBtn, { flex: 1 }]}>
            <Text style={{ fontWeight: "700", color: "#991b1b" }}>Cancel Order</Text>
          </Pressable>
        )}
        <Pressable onPress={() => router.push(`/support?order_id=${order.id}`)} style={[styles.cancelBtn, { flex: 1 }]}>
          <Text style={{ fontWeight: "700", color: "#0f172a" }}>Report Issue</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, backgroundColor: "#f8fafc" },
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16 },
  offlineBanner: { backgroundColor: "#fef3c7", borderRadius: 10, padding: 10 },
  termBanner: { backgroundColor: "#fee2e2", borderRadius: 12, padding: 12 },
  tokenBox: { backgroundColor: "#0f172a", borderRadius: 18, padding: 20, alignItems: "center" },
  smallLabel: { color: "#fdba74", fontSize: 11, fontWeight: "800" },
  ordNo: { color: "#fff", fontSize: 14, fontWeight: "700", marginTop: 4 },
  tokenBig: { color: "#fff", fontSize: 44, fontWeight: "900", marginVertical: 10, letterSpacing: 2 },
  counterSub: { color: "#86efac", fontSize: 12, fontWeight: "700", marginTop: 10, textAlign: "center" },
  qrWrap: { backgroundColor: "#fff", padding: 12, borderRadius: 12 },
  timelineRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  stepPill: { minWidth: 68, paddingVertical: 6, paddingHorizontal: 8, borderRadius: 8, backgroundColor: "#e2e8f0", alignItems: "center" },
  stepReached: { backgroundColor: "#d1fae5" },
  stepTxt: { fontSize: 11, fontWeight: "700", color: "#475569" },
  payBox: { backgroundColor: "#fff", borderRadius: 14, padding: 16, gap: 10, borderWidth: 1, borderColor: "#fed7aa" },
  payBtn: { backgroundColor: "#059669", borderRadius: 10, padding: 12, alignItems: "center" },
  cancelBtn: { backgroundColor: "#e2e8f0", borderRadius: 10, padding: 11, alignItems: "center" },
  pdfBtn: { backgroundColor: "#ea580c", borderRadius: 12, padding: 14, alignItems: "center" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 16, gap: 8, borderWidth: 1, borderColor: "#e2e8f0" },
  secTitle: { fontWeight: "800", fontSize: 15, marginBottom: 4 },
  itemRow: { flexDirection: "row", justifyContent: "space-between" },
  divider: { height: 1, backgroundColor: "#e2e8f0", marginVertical: 6 },
});
