import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { canteensApi } from "../src/api/canteens.api";
import { tokensApi } from "../src/api/tokens.api";
import { useMobileRealtimeWs } from "../src/hooks/useMobileRealtimeWs";
import { useMobileStore } from "../src/store/useMobileStore";

export default function BoardScreen() {
  const { selectedCanteenId } = useMobileStore();
  const [pickedId, setPickedId] = useState("");

  const { data: canteens = [] } = useQuery<any[]>({
    queryKey: ["m-canteens"],
    queryFn: canteensApi.listCanteens,
  });

  const activeId = pickedId || selectedCanteenId || "all";

  const { status: syncStatus } = useMobileRealtimeWs({
    enabled: Boolean(activeId),
    wsPath: activeId === "all" ? "/ws/board/all" : `/ws/board/${activeId}`,
    queryKeys: [["m-board", activeId]],
  });

  const { data: board } = useQuery<any>({
    queryKey: ["m-board", activeId],
    enabled: Boolean(activeId),
    queryFn: () => tokensApi.getBoard(activeId),
    refetchInterval: syncStatus === "live" ? 15000 : 4000,
  });

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ gap: 14, paddingBottom: 32 }}>
      <View style={styles.statusRow}>
        <Text style={styles.boardTitle}>{board?.canteen_name || "Live Token Board"}</Text>
        <View style={[styles.syncBadge, syncStatus === "live" ? styles.syncLive : styles.syncWarn]}>
          <Text style={styles.syncTxt}>{syncStatus === "live" ? "LIVE" : "RECONNECTING"}</Text>
        </View>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <Pressable
          onPress={() => setPickedId("all")}
          style={[styles.pill, activeId === "all" && styles.pillActive]}
        >
          <Text style={[styles.pillTxt, activeId === "all" && { color: "#fff" }]}>All Canteens</Text>
        </Pressable>
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
          <View key={t.order_id || t.token_code} style={styles.prepCard}>
            <Text style={styles.prepToken}>{t.token_code}</Text>
            <Text style={styles.statusTxt}>{t.order_status}</Text>
            {t.item_summary ? <Text style={styles.itemTxt}>{t.item_summary}</Text> : null}
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
          <View key={t.order_id || t.token_code} style={styles.readyCard}>
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
  statusRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  boardTitle: { color: "#fff", fontSize: 16, fontWeight: "900" },
  syncBadge: { borderRadius: 12, paddingHorizontal: 8, paddingVertical: 3 },
  syncLive: { backgroundColor: "#065f46" },
  syncWarn: { backgroundColor: "#92400e" },
  syncTxt: { color: "#fff", fontSize: 10, fontWeight: "800" },
  pill: { backgroundColor: "#1e293b", paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20, marginRight: 8 },
  pillActive: { backgroundColor: "#76010d" },
  pillTxt: { color: "#cbd5e1", fontWeight: "700", fontSize: 12 },
  header: { color: "#fbbf24", fontWeight: "900", fontSize: 15, letterSpacing: 1 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  prepCard: { width: "47%", backgroundColor: "#1e293b", borderRadius: 14, padding: 16, alignItems: "center" },
  prepToken: { color: "#fff", fontSize: 28, fontWeight: "900" },
  statusTxt: { color: "#94a3b8", fontSize: 11, fontWeight: "700", marginTop: 4 },
  itemTxt: { color: "#cbd5e1", fontSize: 10, marginTop: 4, textAlign: "center" },
  readyCard: { width: "47%", backgroundColor: "#065f46", borderRadius: 14, padding: 16, alignItems: "center" },
  readyToken: { color: "#fff", fontSize: 32, fontWeight: "900" },
  counterTxt: { color: "#a7f3d0", fontSize: 11, fontWeight: "700", marginTop: 4, textAlign: "center" },
  emptyTxt: { color: "#64748b", fontSize: 12 },
});
