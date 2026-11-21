import React, { useState } from "react";
import { FlatList, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";

export default function OrdersScreen() {
  const router = useRouter();
  const { user, guestOrderTokens, saveGuestOrderToken } = useMobileStore();
  const [lookupNo, setLookupNo] = useState("");
  const [lookupTok, setLookupTok] = useState("");

  const { data: orders = [] } = useQuery<any[]>({
    queryKey: ["m-orders"],
    enabled: Boolean(user),
    queryFn: async () => (await mobileApi.get("/orders/my")).data,
    refetchInterval: 8000,
  });

  const guestNums = Object.keys(guestOrderTokens);

  const openLookup = () => {
    const trimmed = lookupNo.trim();
    if (!trimmed) return;
    if (lookupTok.trim()) saveGuestOrderToken(trimmed, lookupTok.trim());
    router.push(`/order/${trimmed}`);
  };

  return (
    <View style={styles.container}>
      <View style={styles.topBar}>
        <Text style={styles.title}>Orders & Tokens</Text>
        <Pressable onPress={() => router.push("/board")} style={styles.boardBtn}>
          <Text style={{ color: "#fff", fontWeight: "700", fontSize: 12 }}>Live Token Board</Text>
        </Pressable>
      </View>

      <View style={styles.lookupBox}>
        <Text style={{ fontWeight: "800", fontSize: 12, color: "#0f172a" }}>Track Any Order / Guest Order</Text>
        <View style={{ flexDirection: "row", gap: 6 }}>
          <TextInput
            style={[styles.input, { flex: 1 }]}
            value={lookupNo}
            onChangeText={setLookupNo}
            placeholder="CB-20261121-..."
          />
          <TextInput
            style={[styles.input, { flex: 1 }]}
            value={lookupTok}
            onChangeText={setLookupTok}
            placeholder="Guest Token (opt)"
          />
          <Pressable onPress={openLookup} style={styles.goBtn}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>Open</Text>
          </Pressable>
        </View>
      </View>

      {!user && guestNums.length > 0 && (
        <View style={{ gap: 8, marginBottom: 12 }}>
          {guestNums.map((num) => (
            <Pressable key={num} onPress={() => router.push(`/order/${num}`)} style={styles.card}>
              <Text style={styles.ordNo}>{num}</Text>
              <Text style={styles.meta}>Tap to view live token, QR & receipt</Text>
            </Pressable>
          ))}
        </View>
      )}

      <FlatList
        data={orders}
        keyExtractor={(o) => o.id}
        contentContainerStyle={{ gap: 10, paddingBottom: 30 }}
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
  topBar: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  title: { fontSize: 20, fontWeight: "800", color: "#0f172a" },
  boardBtn: { backgroundColor: "#0f172a", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 10 },
  lookupBox: { backgroundColor: "#fff", borderRadius: 12, padding: 10, gap: 6, marginBottom: 12, borderWidth: 1, borderColor: "#e2e8f0" },
  input: { backgroundColor: "#f8fafc", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 8, paddingHorizontal: 8, paddingVertical: 6, fontSize: 12 },
  goBtn: { backgroundColor: "#ea580c", borderRadius: 8, paddingHorizontal: 12, justifyContent: "center" },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 14, borderWidth: 1, borderColor: "#e2e8f0" },
  ordNo: { fontWeight: "800", fontSize: 15, color: "#0f172a" },
  token: { fontWeight: "900", fontSize: 15, color: "#ea580c" },
  meta: { fontSize: 12, color: "#64748b", marginTop: 4 },
});
