import React, { useState } from "react";
import { FlatList, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { authApi } from "../src/api/auth.api";
import { cartApi } from "../src/api/cart.api";
import { getMobileApiError } from "../src/api/client";
import { ordersApi } from "../src/api/orders.api";
import { useMobileStore } from "../src/store/useMobileStore";
import { BrandLogo } from "../src/components/BrandLogo";

export default function OrdersScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const { user, guestOrderTokens, saveGuestOrderToken, setCanteen } = useMobileStore();
  const [lookupNo, setLookupNo] = useState("");
  const [lookupTok, setLookupTok] = useState("");
  const [recoverPhone, setRecoverPhone] = useState("");
  const [recoverOtp, setRecoverOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [recovered, setRecovered] = useState<any[]>([]);
  const [statusMsg, setStatusMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const reorder = async (o: any) => {
    setStatusMsg("");
    setBusy(true);
    try {
      let added = 0;
      for (const it of o.items || []) {
        if (!it.food_item_id) continue;
        const addons: { addon_id: string; quantity: number }[] = [];
        let spiceLevel: string | null = null;
        let sugarLevel: string | null = null;
        const removedIngredients: string[] = [];
        for (const c of it.customizations || []) {
          if (c.customization_type === "addon" && c.addon_id) {
            addons.push({ addon_id: c.addon_id, quantity: c.quantity || 1 });
          } else if (c.customization_type === "spice") {
            spiceLevel = c.option_value;
          } else if (c.customization_type === "sugar") {
            sugarLevel = c.option_value;
          } else if (c.customization_type === "remove_ingredient") {
            removedIngredients.push(c.option_value);
          }
        }
        await cartApi.addItem({
          canteen_id: o.canteen_id,
          food_item_id: it.food_item_id,
          variant_id: it.variant_id || null,
          quantity: it.quantity,
          spice_level: spiceLevel,
          sugar_level: sugarLevel,
          removed_ingredients: removedIngredients,
          addons,
          special_instructions: it.special_instructions || null,
        });
        added += 1;
      }
      if (added === 0) {
        setStatusMsg("No reorderable dishes found.");
        return;
      }
      setCanteen(o.canteen_id);
      qc.invalidateQueries({ queryKey: ["m-cart", o.canteen_id] });
      router.push("/checkout");
    } catch (e: unknown) {
      setStatusMsg(getMobileApiError(e, "Some items unavailable to reorder"));
    } finally {
      setBusy(false);
    }
  };

  const {
    data: orders = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<any[]>({
    queryKey: ["m-orders"],
    enabled: Boolean(user),
    queryFn: ordersApi.listMyOrders,
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
        <Text style={styles.title}>Orders &amp; Tokens</Text>
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
        {!user && (
          <View style={{ marginTop: 8, paddingTop: 8, borderTopWidth: 1, borderTopColor: "#f1f5f9", gap: 6 }}>
            <Text style={{ fontSize: 11, fontWeight: "700", color: "#475569" }}>Recover Lost Guest Orders via OTP</Text>
            <View style={{ flexDirection: "row", gap: 6 }}>
              <TextInput
                style={[styles.input, { flex: 1 }]}
                value={recoverPhone}
                onChangeText={setRecoverPhone}
                placeholder="+919876543210"
              />
              <Pressable
                disabled={busy || !recoverPhone.trim()}
                onPress={async () => {
                  setBusy(true);
                  setStatusMsg("");
                  try {
                    const r = await authApi.requestOtp({ target: recoverPhone.trim(), purpose: "guest_checkout" });
                    setOtpSent(true);
                    setDevOtp(r.dev_otp || null);
                  } catch (e: unknown) {
                    setStatusMsg(getMobileApiError(e, "Failed to send OTP"));
                  } finally {
                    setBusy(false);
                  }
                }}
                style={styles.goBtn}
              >
                <Text style={{ color: "#fff", fontWeight: "700", fontSize: 11 }}>{otpSent ? "Resend" : "Send OTP"}</Text>
              </Pressable>
            </View>
            {devOtp && <Text style={{ fontSize: 11, color: "#b45309" }}>Dev OTP: {devOtp}</Text>}
            {otpSent && (
              <View style={{ flexDirection: "row", gap: 6 }}>
                <TextInput
                  style={[styles.input, { flex: 1 }]}
                  value={recoverOtp}
                  onChangeText={setRecoverOtp}
                  placeholder="6-digit OTP"
                  maxLength={6}
                />
                <Pressable
                  disabled={busy || recoverOtp.trim().length < 6}
                  onPress={async () => {
                    setBusy(true);
                    setStatusMsg("");
                    try {
                      const ver = await authApi.verifyOtp({
                        target: recoverPhone.trim(),
                        purpose: "guest_checkout",
                        code: recoverOtp.trim(),
                      });
                      const rows = await ordersApi.lookupGuestOrders(recoverPhone.trim(), ver.verification_token);
                      (rows || []).forEach((ord: any) => {
                        if (ord.guest_access_token) saveGuestOrderToken(ord.order_number, ord.guest_access_token);
                      });
                      setRecovered(rows || []);
                    } catch (e: unknown) {
                      setStatusMsg(getMobileApiError(e, "Lookup failed"));
                    } finally {
                      setBusy(false);
                    }
                  }}
                  style={[styles.goBtn, { backgroundColor: "#0f172a" }]}
                >
                  <Text style={{ color: "#fff", fontWeight: "700", fontSize: 11 }}>Find</Text>
                </Pressable>
              </View>
            )}
            {recovered.map((ro) => (
              <Pressable key={ro.id} onPress={() => router.push(`/order/${ro.order_number}`)} style={styles.card}>
                <Text style={styles.ordNo}>{ro.order_number} ({ro.status})</Text>
                <Text style={styles.meta}>₹{ro.total_amount} • Tap to track</Text>
              </Pressable>
            ))}
          </View>
        )}
      </View>

      {!user && guestNums.length > 0 && (
        <View style={{ gap: 8, marginBottom: 12 }}>
          {guestNums.map((num) => (
            <Pressable key={num} onPress={() => router.push(`/order/${num}`)} style={styles.card}>
              <Text style={styles.ordNo}>{num}</Text>
              <Text style={styles.meta}>Tap to view live token, QR &amp; receipt</Text>
            </Pressable>
          ))}
        </View>
      )}

      {isError && (
        <View style={styles.errBox}>
          <Text style={styles.errTxt}>{getMobileApiError(error, "Could not load orders")}</Text>
          <Pressable onPress={() => void refetch()} style={styles.goBtn}>
            <Text style={{ color: "#fff", fontWeight: "800", fontSize: 11 }}>Retry</Text>
          </Pressable>
        </View>
      )}

      {Boolean(statusMsg) && <Text style={{ color: "#dc2626", fontSize: 12, marginBottom: 8 }}>{statusMsg}</Text>}

      <FlatList
        data={orders}
        keyExtractor={(o) => o.id}
        contentContainerStyle={{ gap: 10, paddingBottom: 30 }}
        ListEmptyComponent={
          user && !isLoading ? (
            <View style={{ alignItems: "center", gap: 10, marginTop: 24, paddingHorizontal: 16 }}>
              <BrandLogo size={52} />
              <Text style={{ textAlign: "center", color: "#5d010a", fontWeight: "700", fontSize: 13 }}>
                No orders placed yet. Explore the menu to place your first order.
              </Text>
            </View>
          ) : null
        }
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Pressable onPress={() => router.push(`/order/${item.order_number}`)}>
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={styles.ordNo}>{item.order_number}</Text>
                <Text style={styles.token}>{item.pickup_token_code || item.status}</Text>
              </View>
              <Text style={styles.meta}>
                {item.canteen_name} • ₹{item.total_amount} • {item.status} • {item.payment_status}
              </Text>
            </Pressable>
            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
              <Pressable disabled={busy} onPress={() => reorder(item)} style={styles.reorderBtn}>
                <Text style={{ fontSize: 11, fontWeight: "700", color: "#0f172a" }}>Reorder</Text>
              </Pressable>
            </View>
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#fdf8f0", padding: 16 },
  topBar: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  title: { fontSize: 20, fontWeight: "800", color: "#0f172a" },
  boardBtn: { backgroundColor: "#380106", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 10 },
  lookupBox: { backgroundColor: "#fff", borderRadius: 12, padding: 10, gap: 6, marginBottom: 12, borderWidth: 1, borderColor: "#e7d7c9" },
  input: { backgroundColor: "#fdf8f0", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 8, paddingHorizontal: 8, paddingVertical: 6, fontSize: 12 },
  goBtn: { backgroundColor: "#76010d", borderRadius: 8, paddingHorizontal: 12, justifyContent: "center", paddingVertical: 6 },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 14, borderWidth: 1, borderColor: "#e7d7c9" },
  reorderBtn: { backgroundColor: "#f1f5f9", borderRadius: 8, paddingHorizontal: 10, paddingVertical: 5, borderWidth: 1, borderColor: "#cbd5e1" },
  ordNo: { fontWeight: "800", fontSize: 15, color: "#0f172a" },
  token: { fontWeight: "900", fontSize: 15, color: "#76010d" },
  meta: { fontSize: 12, color: "#64748b", marginTop: 4 },
  errBox: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", backgroundColor: "#fee2e2", borderRadius: 10, padding: 10, marginBottom: 8 },
  errTxt: { flex: 1, color: "#991b1b", fontSize: 12, fontWeight: "700" },
});
