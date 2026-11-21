import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";

const STAFF_ROLES = new Set(["super_admin", "college_admin", "canteen_manager", "cashier", "pickup_staff"]);

export default function ScanScreen() {
  const router = useRouter();
  const [permission, requestPermission] = useCameraPermissions();
  const { user, setCanteen } = useMobileStore();
  const isStaff = Boolean(user?.roles?.some((r) => STAFF_ROLES.has(r)));

  const [mode, setMode] = useState<"location" | "pickup">("location");
  const [manualCode, setManualCode] = useState("CB-MAIN-T01");
  const [statusMsg, setStatusMsg] = useState("");
  const [scanned, setScanned] = useState(false);
  const [pickupResult, setPickupResult] = useState<any | null>(null);

  const resolveLocation = async (raw: string) => {
    const code = raw.includes("/scan/") ? raw.split("/scan/").pop() || raw : raw;
    try {
      const res = await mobileApi.get(`/qr/locations/resolve/${encodeURIComponent(code.trim())}`);
      setCanteen(res.data.canteen.id, res.data.qr.code);
      setStatusMsg(`Selected ${res.data.canteen.name}`);
      router.push("/");
    } catch (e: any) {
      setStatusMsg(e?.response?.data?.detail || "Invalid or revoked QR code");
    }
  };

  const verifyPickup = async (raw: string) => {
    setStatusMsg("");
    try {
      const trimmed = raw.trim();
      const payload =
        trimmed.length <= 8 && !trimmed.includes("CBQR")
          ? { pickup_token: trimmed }
          : { qr_payload: trimmed };
      const res = await mobileApi.post("/pickup/verify", payload);
      setPickupResult(res.data);
    } catch (e: any) {
      setStatusMsg(e?.response?.data?.detail || "Pickup verification failed");
    }
  };

  const confirmHandover = async () => {
    if (!pickupResult?.order_id) return;
    try {
      await mobileApi.post("/pickup/handover", {
        order_id: pickupResult.order_id,
        counter_id: pickupResult.counter_id || null,
        verification_method: "qr_scan",
      });
      setPickupResult({ ...pickupResult, can_handover: false, result_code: "COMPLETED", message: "Handover confirmed." });
    } catch (e: any) {
      setStatusMsg(e?.response?.data?.detail || "Handover failed");
    }
  };

  const handleScanData = (raw: string) => {
    if (mode === "pickup" && isStaff) verifyPickup(raw);
    else resolveLocation(raw);
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ gap: 12, paddingBottom: 32 }}>
      <Text style={styles.title}>{mode === "pickup" ? "Staff Pickup QR & Token Verify" : "Scan Canteen / Table QR Code"}</Text>

      {isStaff && (
        <View style={{ flexDirection: "row", gap: 8 }}>
          <Pressable
            onPress={() => {
              setMode("location");
              setPickupResult(null);
              setManualCode("CB-MAIN-T01");
            }}
            style={[styles.modeBtn, mode === "location" && styles.modeBtnActive]}
          >
            <Text style={[styles.modeTxt, mode === "location" && { color: "#fff" }]}>Table / Menu QR</Text>
          </Pressable>
          <Pressable
            onPress={() => {
              setMode("pickup");
              setManualCode("");
            }}
            style={[styles.modeBtn, mode === "pickup" && styles.modeBtnActive]}
          >
            <Text style={[styles.modeTxt, mode === "pickup" && { color: "#fff" }]}>Staff Pickup Verify</Text>
          </Pressable>
        </View>
      )}

      {!permission?.granted ? (
        <Pressable onPress={requestPermission} style={styles.btn}>
          <Text style={styles.btnText}>Grant Camera Permission</Text>
        </Pressable>
      ) : (
        <View style={styles.camBox}>
          <CameraView
            style={{ flex: 1 }}
            barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
            onBarcodeScanned={(res) => {
              if (scanned) return;
              setScanned(true);
              handleScanData(res.data);
            }}
          />
        </View>
      )}

      {scanned && (
        <Pressable onPress={() => setScanned(false)} style={[styles.btn, { backgroundColor: "#0f172a" }]}>
          <Text style={styles.btnText}>Scan Another QR</Text>
        </Pressable>
      )}

      <Text style={styles.label}>
        {mode === "pickup" ? "Or enter Pickup Token (A001) / QR Payload:" : "Or enter location QR code manually:"}
      </Text>
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          value={manualCode}
          onChangeText={setManualCode}
          placeholder={mode === "pickup" ? "e.g. A001" : "e.g. CB-MAIN-T01"}
        />
        <Pressable onPress={() => handleScanData(manualCode)} style={styles.btn}>
          <Text style={styles.btnText}>{mode === "pickup" ? "Verify" : "Open"}</Text>
        </Pressable>
      </View>

      {Boolean(statusMsg) && <Text style={styles.msg}>{statusMsg}</Text>}

      {pickupResult && (
        <View style={styles.verifyCard}>
          <Text style={{ fontWeight: "900", fontSize: 15, color: "#0f172a" }}>{pickupResult.result_code}</Text>
          <Text style={{ fontSize: 12, color: "#475569" }}>{pickupResult.message}</Text>
          {pickupResult.order_number && (
            <Text style={{ fontSize: 12, fontWeight: "700" }}>
              {pickupResult.order_number} • Token {pickupResult.pickup_token} ({pickupResult.counter_name})
            </Text>
          )}
          {pickupResult.can_handover && (
            <Pressable onPress={confirmHandover} style={[styles.btn, { backgroundColor: "#059669" }]}>
              <Text style={styles.btnText}>Confirm Food Handover</Text>
            </Pressable>
          )}
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16, backgroundColor: "#f8fafc" },
  title: { fontSize: 18, fontWeight: "800", color: "#0f172a" },
  modeBtn: { flex: 1, backgroundColor: "#e2e8f0", borderRadius: 10, paddingVertical: 8, alignItems: "center" },
  modeBtnActive: { backgroundColor: "#0f172a" },
  modeTxt: { fontSize: 12, fontWeight: "700", color: "#334155" },
  camBox: { height: 260, borderRadius: 16, overflow: "hidden", backgroundColor: "#000" },
  label: { fontSize: 12, fontWeight: "700", color: "#475569" },
  row: { flexDirection: "row", gap: 8 },
  input: { flex: 1, backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#cbd5e1", paddingHorizontal: 12, paddingVertical: 10 },
  btn: { backgroundColor: "#ea580c", borderRadius: 12, paddingHorizontal: 16, paddingVertical: 12, justifyContent: "center", alignItems: "center" },
  btnText: { color: "#fff", fontWeight: "700" },
  msg: { color: "#dc2626", fontWeight: "700" },
  verifyCard: { backgroundColor: "#fff", borderRadius: 14, padding: 14, gap: 8, borderWidth: 1, borderColor: "#cbd5e1" },
});
