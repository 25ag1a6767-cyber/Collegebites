import React, { useState } from "react";
import { Alert, Linking, Platform, Pressable, ScrollView, Share, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import QRCode from "react-native-qrcode-svg";
import { API_BASE_URL, getMobileApiError } from "../../src/api/client";
import { ordersApi } from "../../src/api/orders.api";
import { paymentsApi } from "../../src/api/payments.api";
import { profileApi } from "../../src/api/profile.api";
import { tokensApi } from "../../src/api/tokens.api";
import { BrandLogo } from "../../src/components/BrandLogo";
import { useMobileRealtimeWs } from "../../src/hooks/useMobileRealtimeWs";
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
    refetchInterval: 12000,
  });

  const order = liveOrder || (orderNumber ? cachedOrders[orderNumber] : null);
  const isOfflineCache = !liveOrder && Boolean(order);

  const { data: receipt } = useQuery<any>({
    queryKey: ["m-receipt", orderNumber],
    enabled: Boolean(order?.payment_status === "CONFIRMED" && orderNumber),
    queryFn: () => tokensApi.getReceipt(String(orderNumber), gToken),
  });

  const { data: invoice } = useQuery<any>({
    queryKey: ["m-invoice", order?.id],
    enabled: Boolean(order?.payment_status === "CONFIRMED" && order?.id),
    queryFn: () => profileApi.getOrderInvoice(String(order.id), gToken),
  });

  useMobileRealtimeWs({
    enabled: Boolean(order?.id && (accessToken || gToken)),
    wsPath: order?.id ? `/ws/orders/${order.id}` : null,
    token: accessToken,
    guestToken: gToken,
    queryKeys: [["m-order", orderNumber], ["m-receipt", orderNumber]],
  });

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
        <BrandLogo size={54} />
        <Text style={{ marginTop: 10, fontWeight: "700", color: "#5d010a" }}>Loading order details...</Text>
      </View>
    );
  }

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

  const syncPaymentStatus = async () => {
    setPaying(true);
    setErrMsg("");
    try {
      await paymentsApi.syncRazorpay(order.id, gToken);
      await refetch();
    } catch (e: unknown) {
      setErrMsg(getMobileApiError(e, "Could not sync Razorpay payment status"));
    } finally {
      setPaying(false);
    }
  };

  const retryPayment = async () => {
    setPaying(true);
    setErrMsg("");
    try {
      await paymentsApi.retryPayment(order.id, "razorpay", gToken);
      await refetch();
    } catch (e: unknown) {
      setErrMsg(getMobileApiError(e, "Could not restart payment"));
    } finally {
      setPaying(false);
    }
  };

  const performCancelOrder = async () => {
    setErrMsg("");
    try {
      await ordersApi.cancelOrder(order.id, "Cancelled by customer from mobile app", gToken);
      await refetch();
    } catch (e: unknown) {
      setErrMsg(getMobileApiError(e, "Cannot cancel order at this stage"));
    }
  };

  const cancelOrder = () => {
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && !window.confirm("Cancel this order? No in-app refunds are processed per policy.")) {
        return;
      }
      void performCancelOrder();
      return;
    }
    Alert.alert(
      "Cancel Order?",
      "Are you sure you want to cancel this order? No in-app refunds are processed per college policy.",
      [
        { text: "Keep Order", style: "cancel" },
        { text: "Cancel Order", style: "destructive", onPress: () => void performCancelOrder() },
      ]
    );
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
              {order.queue_position && order.queue_position > 0
                ? ` • Queue #${order.queue_position} (${order.orders_ahead_count ?? 0} ahead)`
                : ""}
            </Text>
            <Text style={{ color: "#fdedce", fontSize: 11, fontWeight: "700", marginTop: 4, textAlign: "center" }}>
              {order.status === "READY"
                ? "Estimated Wait: 0 min — Ready for Pickup"
                : order.waiting_time_available === false
                ? order.waiting_time_message || "Waiting time currently unavailable."
                : order.dynamic_wait_minutes !== null && order.dynamic_wait_minutes !== undefined
                ? `Estimated Wait: ~${order.dynamic_wait_minutes} min${
                    order.estimated_pickup_at
                      ? ` • Est. Pickup ${new Date(order.estimated_pickup_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                      : ""
                  }`
                : order.estimated_prep_minutes
                ? `Estimated Wait: ~${order.estimated_prep_minutes + (order.delayed_minutes || 0)} min`
                : "Waiting time currently unavailable."}
            </Text>
            <Text style={{ color: "#cbd5e1", fontSize: 10, marginTop: 2 }}>
              Last updated:{" "}
              {order.last_updated_at
                ? new Date(order.last_updated_at).toLocaleTimeString()
                : new Date(order.confirmed_at || order.created_at).toLocaleTimeString()}
            </Text>
            {order.delayed_minutes > 0 && (
              <Text style={{ color: "#fbbf24", fontSize: 12, fontWeight: "800", marginTop: 4 }}>
                Delayed +{order.delayed_minutes} min{order.delay_reason ? `: ${order.delay_reason}` : ""}
              </Text>
            )}
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
              <Text style={{ color: "#fff", fontWeight: "800" }}>Open Razorpay Checkout</Text>
            </Pressable>
          ) : (
            <Text style={{ color: "#64748b", fontSize: 12 }}>
              Live Razorpay checkout credentials are not configured on the server for this environment.
            </Text>
          )}
          <Pressable disabled={paying} onPress={syncPaymentStatus} style={styles.cancelBtn}>
            <Text style={{ color: "#0f172a", fontWeight: "700" }}>Check Payment Status</Text>
          </Pressable>
          <Pressable disabled={paying} onPress={cancelRazorpayPayment} style={styles.cancelBtn}>
            <Text style={{ color: "#0f172a", fontWeight: "700" }}>Cancel Payment</Text>
          </Pressable>
        </View>
      )}

      {order.status === "PAYMENT_FAILED" && (
        <View style={styles.payBox}>
          <Text style={styles.secTitle}>Retry Razorpay Payment (₹{order.total_amount})</Text>
          <Pressable disabled={paying} onPress={retryPayment} style={styles.payBtn}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>Retry Razorpay Checkout</Text>
          </Pressable>
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
          <Text style={{ fontSize: 12, color: "#64748b" }}>Order Subtotal</Text>
          <Text style={{ fontSize: 12, color: "#64748b" }}>₹{order.subtotal_amount}</Text>
        </View>
        {Number(order.discount_amount) > 0 && (
          <View style={styles.itemRow}>
            <Text style={{ fontSize: 12, color: "#64748b" }}>Historical Discount</Text>
            <Text style={{ fontSize: 12, color: "#64748b" }}>-₹{order.discount_amount}</Text>
          </View>
        )}
        {Number(order.tax_amount) > 0 && (
          <View style={styles.itemRow}>
            <Text style={{ fontSize: 12, color: "#64748b" }}>Historical Tax</Text>
            <Text style={{ fontSize: 12, color: "#64748b" }}>₹{order.tax_amount}</Text>
          </View>
        )}
        <View style={styles.itemRow}>
          <Text style={{ fontWeight: "900", fontSize: 16 }}>Final Payable Amount</Text>
          <Text style={{ fontWeight: "900", fontSize: 16 }}>₹{order.total_amount}</Text>
        </View>
        {Number(order.tax_amount) === 0 && (
          <Text style={{ fontSize: 10, color: "#64748b" }}>
            Listed prices inclusive of applicable statutory taxes. No additional checkout tax or extra charges.
          </Text>
        )}
        <Text style={{ fontSize: 10, color: "#64748b", marginTop: 4 }}>
          Show your pickup token and QR code only after READY status. Each order can be collected once. No in-app refunds per college policy.
        </Text>
      </View>

      {Boolean(errMsg) && <Text style={{ color: "#dc2626", fontWeight: "700", fontSize: 12 }}>{errMsg}</Text>}

      {order.payment_status === "CONFIRMED" && (
        <View style={{ gap: 8 }}>
          {invoice && (
            <View style={styles.card}>
              <Text style={styles.secTitle}>Invoice • {invoice.invoice_number}</Text>
              <Text style={{ fontSize: 11, color: "#475569" }}>
                {Number(invoice.tax_amount) > 0
                  ? `Subtotal: ₹${invoice.subtotal_amount} • CGST: ₹${invoice.tax_breakdown?.cgst_amount || "0.00"} • SGST: ₹${invoice.tax_breakdown?.sgst_amount || "0.00"} • Total: ₹${invoice.total_amount}`
                  : `Subtotal: ₹${invoice.subtotal_amount} • Total Paid: ₹${invoice.total_amount} (Inclusive of applicable statutory taxes)`}
              </Text>
              <Pressable
                onPress={() => {
                  const invSuffix = gToken ? `?guest_access_token=${encodeURIComponent(gToken)}` : "";
                  const pdfUrl = `${API_BASE_URL}/invoices/${encodeURIComponent(invoice.id || order.id)}/pdf${invSuffix}`;
                  Linking.openURL(pdfUrl);
                }}
                style={[styles.pdfBtn, { backgroundColor: "#0f766e", paddingVertical: 10 }]}
              >
                <Text style={{ color: "#fff", fontWeight: "800", fontSize: 12 }}>
                  Download Official Tax Invoice PDF ({invoice.invoice_number})
                </Text>
              </Pressable>
            </View>
          )}
          <Pressable onPress={downloadOrShareReceipt} style={styles.pdfBtn}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>
              {Platform.OS === "web" || gToken ? "Download Printable PDF Receipt" : "Share / Save Digital Receipt"}
            </Text>
          </Pressable>
        </View>
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
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, backgroundColor: "#fdf8f0" },
  container: { flex: 1, backgroundColor: "#fdf8f0", padding: 16 },
  offlineBanner: { backgroundColor: "#fef3c7", borderRadius: 10, padding: 10 },
  termBanner: { backgroundColor: "#fee2e2", borderRadius: 12, padding: 12 },
  tokenBox: { backgroundColor: "#380106", borderRadius: 18, padding: 20, alignItems: "center" },
  smallLabel: { color: "#fdedce", fontSize: 11, fontWeight: "800" },
  ordNo: { color: "#fff", fontSize: 14, fontWeight: "700", marginTop: 4 },
  tokenBig: { color: "#fff", fontSize: 44, fontWeight: "900", marginVertical: 10, letterSpacing: 2 },
  counterSub: { color: "#86efac", fontSize: 12, fontWeight: "700", marginTop: 10, textAlign: "center" },
  qrWrap: { backgroundColor: "#fff", padding: 12, borderRadius: 12 },
  timelineRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  stepPill: { minWidth: 68, paddingVertical: 6, paddingHorizontal: 8, borderRadius: 8, backgroundColor: "#e2e8f0", alignItems: "center" },
  stepReached: { backgroundColor: "#d1fae5" },
  stepTxt: { fontSize: 11, fontWeight: "700", color: "#475569" },
  payBox: { backgroundColor: "#fff", borderRadius: 14, padding: 16, gap: 10, borderWidth: 1, borderColor: "#76010d" },
  payBtn: { backgroundColor: "#059669", borderRadius: 10, padding: 12, alignItems: "center" },
  cancelBtn: { backgroundColor: "#e2e8f0", borderRadius: 10, padding: 11, alignItems: "center" },
  pdfBtn: { backgroundColor: "#76010d", borderRadius: 12, padding: 14, alignItems: "center" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 16, gap: 8, borderWidth: 1, borderColor: "#e7d7c9" },
  secTitle: { fontWeight: "800", fontSize: 15, marginBottom: 4 },
  itemRow: { flexDirection: "row", justifyContent: "space-between" },
  divider: { height: 1, backgroundColor: "#e2e8f0", marginVertical: 6 },
});
