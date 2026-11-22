import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { getMobileApiError } from "../src/api/client";
import { tokensApi } from "../src/api/tokens.api";
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
  const [verifyMethod, setVerifyMethod] = useState<"qr_scan" | "manual_token" | "order_number">("qr_scan");
  const [busy, setBusy] = useState(false);

  const resolveLocation = async (raw: string) => {
    const code = raw.includes("/scan/") ? (raw.split("/scan/").pop() || raw).split(/[?#]/)[0] : raw;
    setBusy(true);
    setStatusMsg("");
    try {
      const data = await tokensApi.resolveLocationQr(code);
      setCanteen(data.canteen.id, data.qr.code);
      setStatusMsg(`Selected ${data.canteen.name}`);
      router.push("/");
    } catch (e: unknown) {
      setStatusMsg(getMobileApiError(e, "Invalid or revoked QR code"));
    } finally {
      setBusy(false);
    }
  };

  const verifyPickup = async (raw: string) => {
    setStatusMsg("");
    setBusy(true);
    try {
      const trimmed = raw.trim();
      let payload: Record<string, string>;
      let method: "qr_scan" | "manual_token" | "order_number";
      if (trimmed.includes("CBQR") || trimmed.includes("/pickup/verify")) {
        payload = { qr_payload: trimmed };
        method = "qr_scan";
      } else if (/^CB-/i.test(trimmed)) {
        payload = { order_number: trimmed };
        method = "order_number";
      } else {
        payload = { pickup_token: trimmed };
        method = "manual_token";
      }
      setVerifyMethod(method);
      const data = await tokensApi.verifyPickup(payload);
      setPickupResult(data);
    } catch (e: unknown) {
      setStatusMsg(getMobileApiError(e, "Pickup verification failed"));
    } finally {
      setBusy(false);
    }
  };

  const confirmHandover = async () => {
    if (!pickupResult?.order_id) return;
    setBusy(true);
    try {
      await tokensApi.confirmHandover({
        order_id: pickupResult.order_id,
        counter_id: pickupResult.counter_id || null,
        verification_method: verifyMethod,
      });
      setPickupResult({ ...pickupResult, can_handover: false, result_code: "COMPLETED", message: "Handover confirmed." });
    } catch (e: unknown) {
      setStatusMsg(getMobileApiError(e, "Handover failed"));
    } finally {
      setBusy(false);
    }
  };

  const handleScanData = (raw: string) => {
    if (mode === "pickup" && isStaff) void verifyPickup(raw);
    else void resolveLocation(raw);
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
        <Pressable disabled={busy} onPress={() => handleScanData(manualCode)} style={styles.btn}>
          <Text style={styles.btnText}>{busy ? "..." : "Verify"}</Text>
        </Pressable>
      </View>

      {Boolean(statusMsg) && <Text style={styles.msg}>{statusMsg}</Text>}

      {pickupResult && (
        <View style={styles.card}>
          <Text style={{ fontWeight: "900", fontSize: 16, color: pickupResult.can_handover ? "#059669" : "#dc2626" }}>
            {pickupResult.result_code}
          </Text>
          <Text style={{ fontSize: 13, color: "#334155", marginTop: 4 }}>{pickupResult.message}</Text>
          {pickupResult.pickup_token && (
            <Text style={{ fontSize: 24, fontWeight: "900", color: "#0f172a", marginTop: 6 }}>
              Token {pickupResult.pickup_token} ({pickupResult.order_number})
            </Text>
          )}
          {pickupResult.can_handover && (
            <Pressable disabled={busy} onPress={confirmHandover} style={[styles.btn, { backgroundColor: "#059669", marginTop: 12 }]}>
              <Text style={styles.btnText}>Confirm Food Handover</Text>
            </Pressable>
          )}
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16 },
  title: { fontSize: 18, fontWeight: "800", color: "#0f172a" },
  camBox: { height: 240, borderRadius: 16, overflow: "hidden", backgroundColor: "#0f172a" },
  label: { fontSize: 12, fontWeight: "700", color: "#475569", marginTop: 8 },
  row: { flexDirection: "row", gap: 8 },
  input: { flex: 1, backgroundColor: "#fff", borderRadius: 10, borderWidth: 1, borderColor: "#cbd5e1", paddingHorizontal: 12 },
  btn: { backgroundColor: "#76010d", borderRadius: 10, paddingHorizontal: 16, paddingVertical: 12, alignItems: "center" },
  btnText: { color: "#fff", fontWeight: "800" },
  msg: { color: "#76010d", fontWeight: "700", marginTop: 6 },
  modeBtn: { flex: 1, paddingVertical: 8, borderRadius: 10, backgroundColor: "#e2e8f0", alignItems: "center" },
  modeBtnActive: { backgroundColor: "#0f172a" },
  modeTxt: { fontSize: 12, fontWeight: "800", color: "#334155" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 14, borderWidth: 1, borderColor: "#e2e8f0" },
});
