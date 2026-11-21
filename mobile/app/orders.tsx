import React from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";

export default function OrdersScreen() {
  const router = useRouter();
  const { user, guestOrderTokens } = useMobileStore();

  const { data: orders = [] } = useQuery<any[]>({
    queryKey: ["m-orders"],
    enabled: Boolean(user),
    queryFn: async () => (await mobileApi.get("/orders/my")).data,
  });

  const guestNums = Object.keys(guestOrderTokens);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Your Orders & Tokens</Text>
      {!user && guestNums.length > 0 && (
        <View style={{ gap: 8, marginBottom: 12 }}>
          {guestNums.map((num) => (
            <Pressable key={num} onPress={() => router.push(`/order/${num}`)} style={styles.card}>
              <Text style={styles.ordNo}>{num}</Text>
              <Text style={styles.meta}>Tap to view live token & receipt</Text>
            </Pressable>
          ))}
        </View>
      )}
      <FlatList
        data={orders}
        keyExtractor={(o) => o.id}
        contentContainerStyle={{ gap: 10 }}
        renderItem={({ item }) => (
          <Pressable onPress={() => router.push(`/order/${item.order_number}`)} style={styles.card}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={styles.ordNo}>{item.order_number}</Text>
              <Text style={styles.token}>{item.pickup_token_code || item.status}</Text>
            </View>
            <Text style={styles.meta}>
              {item.canteen_name} • ₹{item.total_amount} • {item.status}
            </Text>
          </Pressable>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16 },
  title: { fontSize: 20, fontWeight: "800", marginBottom: 12, color: "#0f172a" },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 14, borderWidth: 1, borderColor: "#e2e8f0" },
  ordNo: { fontWeight: "800", fontSize: 15, color: "#0f172a" },
  token: { fontWeight: "900", fontSize: 15, color: "#ea580c" },
  meta: { fontSize: 12, color: "#64748b", marginTop: 4 },
});
