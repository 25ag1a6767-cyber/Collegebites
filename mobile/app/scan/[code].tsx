import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { getMobileApiError } from "../../src/api/client";
import { tokensApi } from "../../src/api/tokens.api";
import { useMobileStore } from "../../src/store/useMobileStore";

export default function ScanCodeDeepLinkScreen() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const router = useRouter();
  const setCanteen = useMobileStore((s) => s.setCanteen);
  const [error, setError] = useState("");
  const [info, setInfo] = useState<{ canteenName: string; locationLabel?: string } | null>(null);

  useEffect(() => {
    const cleanCode = decodeURIComponent(String(code || "")).trim();
    if (!cleanCode) {
      setError("Invalid QR code link");
      return;
    }
    let cancelled = false;
    tokensApi
      .resolveLocationQr(cleanCode)
      .then((data) => {
        if (cancelled) return;
        setCanteen(data.canteen.id, data.qr?.code || cleanCode);
        const label =
          data.table?.table_number
            ? `Table ${data.table.table_number}`
            : data.counter?.name || data.qr?.label || "Menu Ready";
        setInfo({ canteenName: data.canteen.name, locationLabel: label });
      })
      .catch((err) => {
        if (!cancelled) setError(getMobileApiError(err, "Invalid or revoked QR code"));
      });
    return () => {
      cancelled = true;
    };
  }, [code, setCanteen]);

  return (
    <View style={styles.container}>
      {error ? (
        <View style={styles.card}>
          <Text style={styles.errTitle}>QR Code Unavailable</Text>
          <Text style={styles.sub}>{error}</Text>
          <Pressable onPress={() => router.replace("/scan")} style={styles.btn}>
            <Text style={styles.btnText}>Scan Another Code</Text>
          </Pressable>
        </View>
      ) : info ? (
        <View style={styles.card}>
          <Text style={styles.badge}>CANTEEN CONNECTED</Text>
          <Text style={styles.title}>{info.canteenName}</Text>
          {info.locationLabel && <Text style={styles.sub}>{info.locationLabel}</Text>}
          <Pressable onPress={() => router.replace("/")} style={styles.btn}>
            <Text style={styles.btnText}>Open Menu &amp; Order</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.card}>
          <ActivityIndicator size="large" color="#ea580c" />
          <Text style={[styles.sub, { marginTop: 12 }]}>Verifying canteen QR...</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", justifyContent: "center", padding: 20 },
  card: {
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: "#e2e8f0",
    alignItems: "center",
  },
  badge: { fontSize: 11, fontWeight: "800", color: "#ea580c", letterSpacing: 1 },
  title: { fontSize: 22, fontWeight: "800", color: "#0f172a", marginTop: 6, textAlign: "center" },
  errTitle: { fontSize: 19, fontWeight: "800", color: "#dc2626", marginBottom: 6, textAlign: "center" },
  sub: { fontSize: 14, color: "#475569", marginTop: 4, textAlign: "center" },
  btn: {
    marginTop: 16,
    backgroundColor: "#ea580c",
    borderRadius: 12,
    paddingHorizontal: 20,
    paddingVertical: 12,
    width: "100%",
    alignItems: "center",
  },
  btnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
});
