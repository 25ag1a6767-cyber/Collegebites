import React, { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";

export default function ScanScreen() {
  const router = useRouter();
  const [permission, requestPermission] = useCameraPermissions();
  const { setCanteen } = useMobileStore();
  const [manualCode, setManualCode] = useState("CB-MAIN-T01");
  const [statusMsg, setStatusMsg] = useState("");
  const [scanned, setScanned] = useState(false);

  const resolveCode = async (raw: string) => {
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

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Scan Canteen / Table QR Code</Text>
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
              resolveCode(res.data);
            }}
          />
        </View>
      )}

      <Text style={styles.label}>Or enter location QR code manually:</Text>
      <View style={styles.row}>
        <TextInput style={styles.input} value={manualCode} onChangeText={setManualCode} />
        <Pressable onPress={() => resolveCode(manualCode)} style={styles.btn}>
          <Text style={styles.btnText}>Open</Text>
        </Pressable>
      </View>
      {Boolean(statusMsg) && <Text style={styles.msg}>{statusMsg}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16, backgroundColor: "#f8fafc", gap: 12 },
  title: { fontSize: 18, fontWeight: "800", color: "#0f172a" },
  camBox: { height: 280, borderRadius: 16, overflow: "hidden", backgroundColor: "#000" },
  label: { fontSize: 12, fontWeight: "700", color: "#475569" },
  row: { flexDirection: "row", gap: 8 },
  input: { flex: 1, backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#cbd5e1", paddingHorizontal: 12, paddingVertical: 10 },
  btn: { backgroundColor: "#ea580c", borderRadius: 12, paddingHorizontal: 16, paddingVertical: 12, justifyContent: "center" },
  btnText: { color: "#fff", fontWeight: "700" },
  msg: { color: "#dc2626", fontWeight: "700" },
});
