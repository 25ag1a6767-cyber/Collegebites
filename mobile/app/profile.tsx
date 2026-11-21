import React, { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";
import { registerExpoPushToken } from "../src/notifications/registerPush";

export default function ProfileScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const { user, setAuth, logout } = useMobileStore();

  const [mode, setMode] = useState<"login" | "register">("login");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [regName, setRegName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPhone, setRegPhone] = useState("");
  const [regCollegeId, setRegCollegeId] = useState("");
  const [msg, setMsg] = useState("");

  // Signed-in edit fields
  const [fullName, setFullName] = useState("");
  const [collegeId, setCollegeId] = useState("");
  const [department, setDepartment] = useState("");
  const [referralInput, setReferralInput] = useState("");

  const { data: profile } = useQuery<any>({
    queryKey: ["m-profile"],
    enabled: Boolean(user),
    queryFn: async () => (await mobileApi.get("/customers/profile")).data,
  });

  const { data: loyalty } = useQuery<any>({
    queryKey: ["m-loyalty"],
    enabled: Boolean(user),
    queryFn: async () => (await mobileApi.get("/promotions/loyalty/me")).data,
  });

  const { data: notifications = [], refetch: refetchNotifs } = useQuery<any[]>({
    queryKey: ["m-notifs"],
    enabled: Boolean(user),
    queryFn: async () => (await mobileApi.get("/notifications/my")).data,
  });

  const { data: prefs } = useQuery<any>({
    queryKey: ["m-notif-prefs"],
    enabled: Boolean(user),
    queryFn: async () => (await mobileApi.get("/notifications/preferences")).data,
  });

  useEffect(() => {
    if (profile) {
      setFullName(profile.full_name || "");
      setCollegeId(profile.college_id_number || "");
      setDepartment(profile.department || "");
    }
  }, [profile]);

  const login = async () => {
    setMsg("");
    try {
      const res = await mobileApi.post("/auth/login", { identifier: identifier.trim(), password });
      await setAuth(res.data.access_token, res.data.refresh_token, res.data.user);
      await registerExpoPushToken();
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || "Login failed");
    }
  };

  const register = async () => {
    setMsg("");
    try {
      const res = await mobileApi.post("/auth/register", {
        full_name: regName.trim(),
        email: regEmail.trim() || null,
        phone: regPhone.trim() || null,
        password,
        college_id_number: regCollegeId.trim() || null,
      });
      await setAuth(res.data.access_token, res.data.refresh_token, res.data.user);
      await registerExpoPushToken();
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || "Registration failed");
    }
  };

  if (user) {
    return (
      <ScrollView style={styles.container} contentContainerStyle={{ gap: 12, paddingBottom: 40 }}>
        <View style={styles.card}>
          <Text style={styles.title}>{user.full_name}</Text>
          <Text style={styles.sub}>
            {user.email || user.phone} • Roles: {user.roles.join(", ")}
          </Text>
          <TextInput style={styles.input} value={fullName} onChangeText={setFullName} placeholder="Full Name" />
          <TextInput style={styles.input} value={collegeId} onChangeText={setCollegeId} placeholder="College ID / Roll No" />
          <TextInput style={styles.input} value={department} onChangeText={setDepartment} placeholder="Department" />
          <Pressable
            onPress={async () => {
              await mobileApi.patch("/customers/profile", {
                full_name: fullName,
                college_id_number: collegeId,
                department,
              });
              qc.invalidateQueries({ queryKey: ["m-profile"] });
              setMsg("Profile saved.");
            }}
            style={styles.btn}
          >
            <Text style={{ color: "#fff", fontWeight: "800" }}>Save Profile</Text>
          </Pressable>
          {Boolean(msg) && <Text style={{ color: "#059669", fontWeight: "700", fontSize: 12 }}>{msg}</Text>}
        </View>

        <View style={[styles.card, { backgroundColor: "#fff7ed", borderColor: "#fed7aa" }]}>
          <Text style={styles.secTitle}>
            Loyalty: {loyalty?.points_balance || 0} pts ({loyalty?.tier_level || "BRONZE"})
          </Text>
          <Text style={styles.sub}>
            Referral Code: {loyalty?.referral_code || "N/A"} • Saved Favourites:{" "}
            {profile?.favourite_item_ids?.length || 0}
          </Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <TextInput
              style={[styles.input, { flex: 1 }]}
              value={referralInput}
              onChangeText={setReferralInput}
              placeholder="Friend's referral code"
            />
            <Pressable
              onPress={async () => {
                try {
                  const res = await mobileApi.post(
                    `/promotions/loyalty/apply-referral?referral_code=${encodeURIComponent(referralInput)}`
                  );
                  setMsg(res.data.message);
                  qc.invalidateQueries({ queryKey: ["m-loyalty"] });
                } catch (e: any) {
                  setMsg(e?.response?.data?.detail || "Invalid referral");
                }
              }}
              style={[styles.btn, { paddingHorizontal: 14 }]}
            >
              <Text style={{ color: "#fff", fontWeight: "700" }}>Apply</Text>
            </Pressable>
          </View>
        </View>

        {prefs && (
          <View style={styles.card}>
            <Text style={styles.secTitle}>Notification Preferences</Text>
            {[
              ["push_enabled", "Push Alerts"],
              ["email_enabled", "Email Receipts"],
              ["sms_enabled", "SMS Alerts"],
            ].map(([key, label]) => (
              <View key={key} style={styles.prefRow}>
                <Text style={{ fontWeight: "600", fontSize: 13 }}>{label}</Text>
                <Switch
                  value={Boolean(prefs[key])}
                  onValueChange={async () => {
                    await mobileApi.put("/notifications/preferences", { [key]: !prefs[key] });
                    qc.invalidateQueries({ queryKey: ["m-notif-prefs"] });
                  }}
                />
              </View>
            ))}
          </View>
        )}

        <View style={styles.card}>
          <Text style={styles.secTitle}>Notifications ({notifications.length})</Text>
          {notifications.slice(0, 6).map((n) => (
            <View key={n.id} style={styles.notifRow}>
              <Text style={{ fontWeight: "700", fontSize: 12 }}>{n.title}</Text>
              <Text style={{ fontSize: 11, color: "#475569" }}>{n.message}</Text>
              {!n.is_read && (
                <Pressable
                  onPress={async () => {
                    await mobileApi.post(`/notifications/${n.id}/read`);
                    refetchNotifs();
                  }}
                >
                  <Text style={{ fontSize: 11, color: "#ea580c", fontWeight: "700", marginTop: 2 }}>Mark Read</Text>
                </Pressable>
              )}
            </View>
          ))}
        </View>

        <View style={{ flexDirection: "row", gap: 8 }}>
          <Pressable onPress={() => router.push("/board")} style={[styles.btnAlt, { flex: 1 }]}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>Live Token Board</Text>
          </Pressable>
          <Pressable onPress={() => router.push("/support")} style={[styles.btnAlt, { flex: 1 }]}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>Customer Support</Text>
          </Pressable>
        </View>

        <Pressable onPress={logout} style={styles.logoutBtn}>
          <Text style={{ color: "#fff", fontWeight: "800" }}>Sign Out</Text>
        </Pressable>
      </ScrollView>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ gap: 12, paddingBottom: 40 }}>
      <View style={styles.tabRow}>
        <Pressable
          onPress={() => setMode("login")}
          style={[styles.tabBtn, mode === "login" && styles.tabBtnActive]}
        >
          <Text style={[styles.tabTxt, mode === "login" && { color: "#fff" }]}>Sign In</Text>
        </Pressable>
        <Pressable
          onPress={() => setMode("register")}
          style={[styles.tabBtn, mode === "register" && styles.tabBtnActive]}
        >
          <Text style={[styles.tabTxt, mode === "register" && { color: "#fff" }]}>Create Account</Text>
        </Pressable>
      </View>

      {mode === "login" ? (
        <View style={styles.card}>
          <Text style={styles.title}>Universal Campus Sign In</Text>
          <TextInput style={styles.input} value={identifier} onChangeText={setIdentifier} placeholder="Email or Phone" autoCapitalize="none" />
          <TextInput style={styles.input} value={password} onChangeText={setPassword} secureTextEntry placeholder="Password" />
          {Boolean(msg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{msg}</Text>}
          <Pressable onPress={login} style={styles.btn}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>Sign In</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.title}>Universal Customer Account</Text>
          <Text style={styles.sub}>One account for students, faculty & campus visitors.</Text>
          <TextInput style={styles.input} value={regName} onChangeText={setRegName} placeholder="Full Name *" />
          <TextInput style={styles.input} value={regEmail} onChangeText={setRegEmail} placeholder="Email (or enter phone)" autoCapitalize="none" />
          <TextInput style={styles.input} value={regPhone} onChangeText={setRegPhone} placeholder="Mobile (+9198...)" />
          <TextInput style={styles.input} value={regCollegeId} onChangeText={setRegCollegeId} placeholder="College ID / Roll No (optional)" />
          <TextInput style={styles.input} value={password} onChangeText={setPassword} secureTextEntry placeholder="Password (min 8 chars)" />
          {Boolean(msg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{msg}</Text>}
          <Pressable onPress={register} style={styles.btn}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>Create Universal Account</Text>
          </Pressable>
        </View>
      )}

      <View style={{ flexDirection: "row", gap: 8 }}>
        <Pressable onPress={() => router.push("/board")} style={[styles.btnAlt, { flex: 1 }]}>
          <Text style={{ color: "#fff", fontWeight: "800" }}>Live Token Board</Text>
        </Pressable>
        <Pressable onPress={() => router.push("/support")} style={[styles.btnAlt, { flex: 1 }]}>
          <Text style={{ color: "#fff", fontWeight: "800" }}>Support & Help</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16 },
  title: { fontSize: 19, fontWeight: "800", color: "#0f172a" },
  secTitle: { fontSize: 14, fontWeight: "800", color: "#0f172a" },
  sub: { fontSize: 12, color: "#475569" },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 14, gap: 10, borderWidth: 1, borderColor: "#e2e8f0" },
  input: { backgroundColor: "#fff", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9 },
  btn: { backgroundColor: "#ea580c", borderRadius: 10, paddingVertical: 12, alignItems: "center", justifyContent: "center" },
  btnAlt: { backgroundColor: "#334155", borderRadius: 10, paddingVertical: 12, alignItems: "center" },
  logoutBtn: { backgroundColor: "#0f172a", borderRadius: 10, padding: 13, alignItems: "center" },
  prefRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  notifRow: { borderBottomWidth: 1, borderBottomColor: "#f1f5f9", paddingBottom: 6 },
  tabRow: { flexDirection: "row", gap: 8 },
  tabBtn: { flex: 1, backgroundColor: "#e2e8f0", borderRadius: 10, paddingVertical: 10, alignItems: "center" },
  tabBtnActive: { backgroundColor: "#0f172a" },
  tabTxt: { fontWeight: "800", color: "#334155" },
});
