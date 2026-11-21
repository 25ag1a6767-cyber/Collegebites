import React, { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { canteensApi } from "../src/api/canteens.api";
import { buildMobileWsUrl } from "../src/api/client";
import { tokensApi } from "../src/api/tokens.api";
import { useMobileStore } from "../src/store/useMobileStore";

export default function BoardScreen() {
  const { selectedCanteenId } = useMobileStore();
  const qc = useQueryClient();
  const [pickedId, setPickedId] = useState("");

  const { data: canteens = [] } = useQuery<any[]>({
    queryKey: ["m-canteens"],
    queryFn: canteensApi.listCanteens,
  });

  const activeId = pickedId || selectedCanteenId || canteens[0]?.id || "";

  const { data: board } = useQuery<any>({
    queryKey: ["m-board", activeId],
    enabled: Boolean(activeId),
    queryFn: () => tokensApi.getBoard(activeId),
    refetchInterval: 4000,
  });

  useEffect(() => {
    if (!activeId) return;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(buildMobileWsUrl(`/ws/board/${activeId}`));
      ws.onmessage = () => qc.invalidateQueries({ queryKey: ["m-board", activeId] });
    } catch {
      // polling handles fallback
    }
    return () => ws?.close();
  }, [activeId, qc]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ gap: 14, paddingBottom: 32 }}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        {canteens.map((c) => {
          const active = c.id === activeId;
          return (
            <Pressable
              key={c.id}
              onPress={() => setPickedId(c.id)}
              style={[styles.pill, active && styles.pillActive]}
            >
              <Text style={[styles.pillTxt, active && { color: "#fff" }]}>{c.name}</Text>
            </Pressable>
          );
        })}
      </ScrollView>

      <Text style={styles.header}>NOW PREPARING ({board?.now_preparing?.length || 0})</Text>
      <View style={styles.grid}>
        {(board?.now_preparing || []).map((t: any) => (
          <View key={t.token_code} style={styles.prepCard}>
            <Text style={styles.prepToken}>{t.token_code}</Text>
            <Text style={styles.statusTxt}>{t.order_status}</Text>
          </View>
        ))}
        {(!board?.now_preparing || board.now_preparing.length === 0) && (
          <Text style={styles.emptyTxt}>No orders currently in preparation.</Text>
        )}
      </View>

      <Text style={[styles.header, { color: "#34d399" }]}>
        READY FOR PICKUP ({board?.ready_for_pickup?.length || 0})
      </Text>
      <View style={styles.grid}>
        {(board?.ready_for_pickup || []).map((t: any) => (
          <View key={t.token_code} style={styles.readyCard}>
            <Text style={styles.readyToken}>{t.token_code}</Text>
            <Text style={styles.counterTxt}>Collect at {t.counter_name}</Text>
          </View>
        ))}
        {(!board?.ready_for_pickup || board.ready_for_pickup.length === 0) && (
          <Text style={styles.emptyTxt}>No orders waiting at counter right now.</Text>
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0f172a", padding: 16 },
  pill: { backgroundColor: "#1e293b", paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20, marginRight: 8 },
  pillActive: { backgroundColor: "#ea580c" },
  pillTxt: { color: "#cbd5e1", fontWeight: "700", fontSize: 12 },
  header: { color: "#fbbf24", fontWeight: "900", fontSize: 15, letterSpacing: 1 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  prepCard: { width: "47%", backgroundColor: "#1e293b", borderRadius: 14, padding: 16, alignItems: "center" },
  prepToken: { color: "#fff", fontSize: 28, fontWeight: "900" },
  statusTxt: { color: "#94a3b8", fontSize: 11, fontWeight: "700", marginTop: 4 },
  readyCard: { width: "47%", backgroundColor: "#065f46", borderRadius: 14, padding: 16, alignItems: "center" },
  readyToken: { color: "#fff", fontSize: 32, fontWeight: "900" },
  counterTxt: { color: "#a7f3d0", fontSize: 11, fontWeight: "700", marginTop: 4, textAlign: "center" },
  emptyTxt: { color: "#64748b", fontSize: 12 },
});
