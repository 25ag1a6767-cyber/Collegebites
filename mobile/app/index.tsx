import React, { useState } from "react";
import { FlatList, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";

export default function MenuScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const { selectedCanteenId, setCanteen } = useMobileStore();
  const [search, setSearch] = useState("");
  const [vegOnly, setVegOnly] = useState(false);

  const { data: canteens = [] } = useQuery<any[]>({
    queryKey: ["m-canteens"],
    queryFn: async () => (await mobileApi.get("/canteens")).data,
  });

  const activeCanteen = canteens.find((c) => c.id === selectedCanteenId) || canteens[0];

  const { data: items = [] } = useQuery<any[]>({
    queryKey: ["m-items", activeCanteen?.id, search, vegOnly],
    enabled: Boolean(activeCanteen?.id),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (search.trim()) params.set("q", search.trim());
      if (vegOnly) params.set("is_veg", "true");
      return (await mobileApi.get(`/menus/canteens/${activeCanteen.id}/items?${params.toString()}`)).data;
    },
  });

  const { data: cart } = useQuery<any>({
    queryKey: ["m-cart", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: async () => (await mobileApi.get(`/carts?canteen_id=${activeCanteen.id}`)).data,
  });

  const addQuick = async (item: any) => {
    if (!activeCanteen) return;
    const defVar = item.variants?.find((v: any) => v.is_default) || item.variants?.[0];
    await mobileApi.post("/carts/items", {
      canteen_id: activeCanteen.id,
      food_item_id: item.id,
      variant_id: defVar?.id || null,
      quantity: 1,
    });
    qc.invalidateQueries({ queryKey: ["m-cart", activeCanteen.id] });
  };

  return (
    <View style={styles.container}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.canteenBar}>
        {canteens.map((c) => {
          const active = c.id === activeCanteen?.id;
          return (
            <Pressable
              key={c.id}
              onPress={() => setCanteen(c.id)}
              style={[styles.canteenPill, active && styles.canteenPillActive]}
            >
              <Text style={[styles.canteenTitle, active && { color: "#fff" }]}>{c.name}</Text>
              <Text style={[styles.canteenSub, active && { color: "#fed7aa" }]}>
                {c.crowd_level} • ~{c.estimated_wait_minutes}m
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>

      <View style={styles.searchRow}>
        <TextInput
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          placeholder="Search biryani, dosa, coffee..."
        />
        <Pressable
          onPress={() => setVegOnly(!vegOnly)}
          style={[styles.vegBtn, vegOnly && { backgroundColor: "#059669", borderColor: "#059669" }]}
        >
          <Text style={[styles.vegText, vegOnly && { color: "#fff" }]}>Veg</Text>
        </Pressable>
      </View>

      <FlatList
        data={items}
        keyExtractor={(item) => item.id}
        contentContainerStyle={{ paddingBottom: 90, gap: 10 }}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <View style={{ flex: 1 }}>
              <Text style={styles.itemTitle}>
                {item.is_veg ? "🟢" : "🔴"} {item.name}
              </Text>
              <Text style={styles.itemDesc} numberOfLines={2}>
                {item.description}
              </Text>
              <Text style={styles.itemMeta}>
                ₹{item.base_price} • {item.prep_time_minutes} min • ★ {item.average_rating}
              </Text>
            </View>
            <Pressable
              disabled={!item.is_available || item.insufficient_ingredients}
              onPress={() => addQuick(item)}
              style={[styles.addBtn, (!item.is_available || item.insufficient_ingredients) && { backgroundColor: "#cbd5e1" }]}
            >
              <Text style={styles.addBtnText}>{item.is_available ? "+ Add" : "Sold Out"}</Text>
            </Pressable>
          </View>
        )}
      />

      {cart && cart.items?.length > 0 && (
        <Pressable onPress={() => router.push("/checkout")} style={styles.cartBar}>
          <Text style={styles.cartBarText}>
            {cart.items.reduce((s: number, i: any) => s + i.quantity, 0)} items • ₹{cart.total_amount}
          </Text>
          <Text style={styles.cartBarText}>Checkout →</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 12 },
  canteenBar: { maxHeight: 68, marginBottom: 10 },
  canteenPill: { backgroundColor: "#fff", borderRadius: 12, padding: 10, marginRight: 8, borderWidth: 1, borderColor: "#e2e8f0" },
  canteenPillActive: { backgroundColor: "#0f172a", borderColor: "#0f172a" },
  canteenTitle: { fontWeight: "700", fontSize: 13, color: "#0f172a" },
  canteenSub: { fontSize: 11, color: "#64748b", marginTop: 2 },
  searchRow: { flexDirection: "row", gap: 8, marginBottom: 10 },
  searchInput: { flex: 1, backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#cbd5e1", paddingHorizontal: 12, paddingVertical: 8 },
  vegBtn: { justifyContent: "center", paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: "#cbd5e1", backgroundColor: "#fff" },
  vegText: { fontWeight: "700", color: "#0f172a" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 14, flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderColor: "#e2e8f0" },
  itemTitle: { fontWeight: "800", fontSize: 15, color: "#0f172a" },
  itemDesc: { fontSize: 12, color: "#64748b", marginTop: 2 },
  itemMeta: { fontSize: 12, fontWeight: "700", color: "#ea580c", marginTop: 6 },
  addBtn: { backgroundColor: "#ea580c", borderRadius: 10, paddingHorizontal: 14, paddingVertical: 8 },
  addBtnText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  cartBar: { position: "absolute", bottom: 14, left: 14, right: 14, backgroundColor: "#0f172a", borderRadius: 14, padding: 14, flexDirection: "row", justifyContent: "space-between" },
  cartBarText: { color: "#fff", fontWeight: "800", fontSize: 14 },
});
