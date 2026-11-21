import React, { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";
import { registerExpoPushToken } from "../src/notifications/registerPush";

export default function ProfileScreen() {
  const { user, setAuth, logout } = useMobileStore();
  const [identifier, setIdentifier] = useState("student@collegebites.edu");
  const [password, setPassword] = useState("Student@12345");
  const [msg, setMsg] = useState("");

  const login = async () => {
    try {
      const res = await mobileApi.post("/auth/login", { identifier, password });
      await setAuth(res.data.access_token, res.data.refresh_token, res.data.user);
      await registerExpoPushToken();
      setMsg("");
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || "Login failed");
    }
  };

  if (user) {
    return (
      <View style={styles.container}>
        <View style={styles.card}>
          <Text style={styles.title}>{user.full_name}</Text>
          <Text style={styles.sub}>{user.email || user.phone}</Text>
          <Text style={styles.sub}>Roles: {user.roles.join(", ")}</Text>
        </View>
        <Pressable onPress={logout} style={styles.logoutBtn}>
          <Text style={{ color: "#fff", fontWeight: "800" }}>Sign Out</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Universal Student / Staff Sign In</Text>
      <TextInput style={styles.input} value={identifier} onChangeText={setIdentifier} placeholder="Email or Phone" />
      <TextInput style={styles.input} value={password} onChangeText={setPassword} secureTextEntry placeholder="Password" />
      {Boolean(msg) && <Text style={{ color: "#dc2626" }}>{msg}</Text>}
      <Pressable onPress={login} style={styles.btn}>
        <Text style={{ color: "#fff", fontWeight: "800" }}>Sign In</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16, gap: 12 },
  title: { fontSize: 20, fontWeight: "800", color: "#0f172a" },
  sub: { fontSize: 13, color: "#475569", marginTop: 4 },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 16 },
  input: { backgroundColor: "#fff", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 12, padding: 12 },
  btn: { backgroundColor: "#ea580c", borderRadius: 12, padding: 14, alignItems: "center" },
  logoutBtn: { backgroundColor: "#0f172a", borderRadius: 12, padding: 14, alignItems: "center" },
});
