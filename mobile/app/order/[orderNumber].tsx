import React from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import QRCode from "react-native-qrcode-svg";
import { mobileApi } from "../../src/api/client";
import { useMobileStore } from "../../src/store/useMobileStore";

export default function OrderDetailScreen() {
  const { orderNumber } = useLocalSearchParams<{ orderNumber: string }>();
  const guestTokens = useMobileStore((s) => s.guestOrderTokens);
  const gToken = orderNumber ? guestTokens[orderNumber] : undefined;
  const suffix = gToken ? `?guest_token=${encodeURIComponent(gToken)}` : "";

  const { data: order } = useQuery<any>({
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
          </>
        ) : (
          <Text style={{ color: "#fbbf24", fontWeight: "700", marginTop: 8 }}>
            Status: {order.status} (Payment: {order.payment_status})
          </Text>
        )}
      </View>

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
  qrWrap: { backgroundColor: "#fff", padding: 12, borderRadius: 12 },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 16, gap: 8 },
  secTitle: { fontWeight: "800", fontSize: 15, marginBottom: 4 },
  itemRow: { flexDirection: "row", justifyContent: "space-between" },
  divider: { height: 1, backgroundColor: "#e2e8f0", marginVertical: 6 },
});
