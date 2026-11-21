import React, { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { getMobileApiError, mobileApi } from "../src/api/client";
import { useMobileStore } from "../src/store/useMobileStore";
import { registerExpoPushToken } from "../src/notifications/registerPush";

export default function ProfileScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const { user, setAuth, logout } = useMobileStore();

  const [mode, setMode] = useState<"login" | "register">("login");
  const [loginMethod, setLoginMethod] = useState<"password" | "otp">("password");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [resetMode, setResetMode] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [regName, setRegName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPhone, setRegPhone] = useState("");
  const [regCollegeId, setRegCollegeId] = useState("");
  const [regReferral, setRegReferral] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  // Signed-in edit fields
  const [fullName, setFullName] = useState("");
  const [phoneInput, setPhoneInput] = useState("");
  const [collegeId, setCollegeId] = useState("");
  const [department, setDepartment] = useState("");
  const [referralInput, setReferralInput] = useState("");
  const [curPw, setCurPw] = useState("");
  const [chgNewPw, setChgNewPw] = useState("");
  const [confirmDeact, setConfirmDeact] = useState(false);

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

  const { data: favourites = [] } = useQuery<any[]>({
    queryKey: ["m-favourites"],
    enabled: Boolean(user),
    queryFn: async () => (await mobileApi.get("/customers/favourites")).data,
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
      setPhoneInput(profile.phone || "");
      setCollegeId(profile.college_id_number || "");
      setDepartment(profile.department || "");
    }
  }, [profile]);

  const login = async () => {
    setMsg("");
    setBusy(true);
    try {
      const res =
        loginMethod === "otp"
          ? await mobileApi.post("/auth/otp/login", { target: identifier.trim(), code: otpCode.trim() })
          : await mobileApi.post("/auth/login", { identifier: identifier.trim(), password });
      await setAuth(res.data.access_token, res.data.refresh_token, res.data.user);
      await registerExpoPushToken();
    } catch (e: unknown) {
      setMsg(getMobileApiError(e, "Login failed"));
    } finally {
      setBusy(false);
    }
  };

  const register = async () => {
    setMsg("");
    setBusy(true);
    try {
      const res = await mobileApi.post("/auth/register", {
        full_name: regName.trim(),
        email: regEmail.trim() || null,
        phone: regPhone.trim() || null,
        password,
        college_id_number: regCollegeId.trim() || null,
        referral_code: regReferral.trim() || null,
      });
      await setAuth(res.data.access_token, res.data.refresh_token, res.data.user);
      await registerExpoPushToken();
    } catch (e: unknown) {
      setMsg(getMobileApiError(e, "Registration failed"));
    } finally {
      setBusy(false);
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
          <TextInput style={styles.input} value={phoneInput} onChangeText={setPhoneInput} placeholder="Mobile (+91...)" />
          <TextInput style={styles.input} value={collegeId} onChangeText={setCollegeId} placeholder="College ID / Roll No" />
          <TextInput style={styles.input} value={department} onChangeText={setDepartment} placeholder="Department" />
          <Pressable
            disabled={busy}
            onPress={async () => {
              setBusy(true);
              setMsg("");
              try {
                await mobileApi.patch("/customers/profile", {
                  full_name: fullName,
                  phone: phoneInput.trim() || null,
                  college_id_number: collegeId,
                  department,
                });
                qc.invalidateQueries({ queryKey: ["m-profile"] });
                setMsg("Profile saved.");
              } catch (e: unknown) {
                setMsg(getMobileApiError(e, "Could not update profile"));
              } finally {
                setBusy(false);
              }
            }}
            style={styles.btn}
          >
            <Text style={{ color: "#fff", fontWeight: "800" }}>{busy ? "Saving..." : "Save Profile"}</Text>
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
                    try {
                      await mobileApi.put("/notifications/preferences", { [key]: !prefs[key] });
                      qc.invalidateQueries({ queryKey: ["m-notif-prefs"] });
                    } catch (e: unknown) {
                      setMsg(getMobileApiError(e, "Preference update failed"));
                    }
                  }}
                />
              </View>
            ))}
          </View>
        )}

        <View style={styles.card}>
          <Text style={styles.secTitle}>Saved Favourite Dishes ({favourites.length})</Text>
          {favourites.length === 0 ? (
            <Text style={styles.sub}>Tap the heart icon on any menu dish to save it.</Text>
          ) : (
            favourites.slice(0, 5).map((f) => (
              <View key={f.id} style={styles.prefRow}>
                <Text style={{ fontWeight: "700", fontSize: 12 }}>
                  {f.name} • ₹{f.base_price}
                </Text>
                <Pressable onPress={() => router.push("/")}>
                  <Text style={{ color: "#ea580c", fontWeight: "800", fontSize: 12 }}>Order</Text>
                </Pressable>
              </View>
            ))
          )}
        </View>

        <View style={styles.card}>
          <View style={styles.prefRow}>
            <Text style={styles.secTitle}>Notifications ({notifications.length})</Text>
            {notifications.some((n) => !n.is_read) && (
              <Pressable
                onPress={async () => {
                  try {
                    await mobileApi.post("/notifications/mark-all-read");
                    refetchNotifs();
                  } catch (e: unknown) {
                    setMsg(getMobileApiError(e));
                  }
                }}
              >
                <Text style={{ fontSize: 11, color: "#ea580c", fontWeight: "800" }}>Mark All Read</Text>
              </Pressable>
            )}
          </View>
          {notifications.slice(0, 6).map((n) => (
            <View key={n.id} style={styles.notifRow}>
              <Text style={{ fontWeight: "700", fontSize: 12 }}>{n.title}</Text>
              <Text style={{ fontSize: 11, color: "#475569" }}>{n.message}</Text>
              {!n.is_read && (
                <Pressable
                  onPress={async () => {
                    try {
                      await mobileApi.post(`/notifications/${n.id}/read`);
                      refetchNotifs();
                    } catch (e: unknown) {
                      setMsg(getMobileApiError(e));
                    }
                  }}
                >
                  <Text style={{ fontSize: 11, color: "#ea580c", fontWeight: "700", marginTop: 2 }}>Mark Read</Text>
                </Pressable>
              )}
            </View>
          ))}
        </View>

        <View style={styles.card}>
          <Text style={styles.secTitle}>Change Password</Text>
          <TextInput style={styles.input} secureTextEntry value={curPw} onChangeText={setCurPw} placeholder="Current password" />
          <TextInput style={styles.input} secureTextEntry value={chgNewPw} onChangeText={setChgNewPw} placeholder="New password (8+ chars)" />
          <Pressable
            disabled={busy || !curPw || chgNewPw.length < 8}
            onPress={async () => {
              setBusy(true);
              try {
                await mobileApi.post("/auth/change-password", { current_password: curPw, new_password: chgNewPw });
                setCurPw("");
                setChgNewPw("");
                setMsg("Password updated.");
              } catch (e: unknown) {
                setMsg(getMobileApiError(e, "Could not update password"));
              } finally {
                setBusy(false);
              }
            }}
            style={styles.btnAlt}
          >
            <Text style={{ color: "#fff", fontWeight: "800" }}>Update Password</Text>
          </Pressable>
        </View>

        <View style={{ flexDirection: "row", gap: 8 }}>
          <Pressable onPress={() => router.push("/board")} style={[styles.btnAlt, { flex: 1 }]}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>Live Token Board</Text>
          </Pressable>
          <Pressable onPress={() => router.push("/support")} style={[styles.btnAlt, { flex: 1 }]}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>Customer Support</Text>
          </Pressable>
        </View>

        {user.roles.includes("customer") && user.roles.length === 1 && (
          <Pressable
            onPress={async () => {
              if (!confirmDeact) {
                setConfirmDeact(true);
                return;
              }
              try {
                await mobileApi.delete("/customers/me");
                qc.clear();
                await logout(true);
              } catch (e: unknown) {
                setMsg(getMobileApiError(e));
              }
            }}
            style={[styles.logoutBtn, { backgroundColor: "#dc2626" }]}
          >
            <Text style={{ color: "#fff", fontWeight: "800" }}>
              {confirmDeact ? "Tap Again to Confirm Account Deactivation" : "Deactivate My Account"}
            </Text>
          </Pressable>
        )}

        <Pressable
          onPress={async () => {
            await logout();
            qc.clear();
          }}
          style={styles.logoutBtn}
        >
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
          <View style={styles.tabRow}>
            <Pressable
              onPress={() => {
                setLoginMethod("password");
                setResetMode(false);
              }}
              style={[styles.tabBtn, loginMethod === "password" && !resetMode && styles.tabBtnActive]}
            >
              <Text style={[styles.tabTxt, loginMethod === "password" && !resetMode && { color: "#fff" }]}>Password</Text>
            </Pressable>
            <Pressable
              onPress={() => {
                setLoginMethod("otp");
                setResetMode(false);
              }}
              style={[styles.tabBtn, loginMethod === "otp" && !resetMode && styles.tabBtnActive]}
            >
              <Text style={[styles.tabTxt, loginMethod === "otp" && !resetMode && { color: "#fff" }]}>OTP Login</Text>
            </Pressable>
          </View>
          <TextInput style={styles.input} value={identifier} onChangeText={setIdentifier} placeholder="Email or Phone" autoCapitalize="none" />

          {resetMode ? (
            <>
              <View style={{ flexDirection: "row", gap: 6 }}>
                <TextInput style={[styles.input, { flex: 1 }]} value={otpCode} onChangeText={setOtpCode} placeholder="Reset OTP" maxLength={6} />
                <Pressable
                  disabled={busy || !identifier.trim()}
                  onPress={async () => {
                    setBusy(true);
                    try {
                      const r = await mobileApi.post("/auth/otp/request", { target: identifier.trim(), purpose: "password_reset" });
                      setDevOtp(r.data.dev_otp || null);
                    } catch (e: unknown) {
                      setMsg(getMobileApiError(e));
                    } finally {
                      setBusy(false);
                    }
                  }}
                  style={[styles.btn, { paddingHorizontal: 12 }]}
                >
                  <Text style={{ color: "#fff", fontWeight: "700" }}>Send OTP</Text>
                </Pressable>
              </View>
              {devOtp && <Text style={{ fontSize: 11, color: "#b45309" }}>Dev OTP: {devOtp}</Text>}
              <TextInput style={styles.input} secureTextEntry value={newPassword} onChangeText={setNewPassword} placeholder="New Password (8+ chars)" />
              <Pressable
                disabled={busy || otpCode.trim().length < 6 || newPassword.length < 8}
                onPress={async () => {
                  setBusy(true);
                  try {
                    await mobileApi.post("/auth/password-reset/confirm", {
                      target: identifier.trim(),
                      code: otpCode.trim(),
                      new_password: newPassword,
                    });
                    setResetMode(false);
                    setMsg("Password updated! Please sign in.");
                  } catch (e: unknown) {
                    setMsg(getMobileApiError(e));
                  } finally {
                    setBusy(false);
                  }
                }}
                style={styles.btn}
              >
                <Text style={{ color: "#fff", fontWeight: "800" }}>Reset Password</Text>
              </Pressable>
            </>
          ) : loginMethod === "otp" ? (
            <>
              <View style={{ flexDirection: "row", gap: 6 }}>
                <TextInput style={[styles.input, { flex: 1 }]} value={otpCode} onChangeText={setOtpCode} placeholder="6-digit OTP" maxLength={6} />
                <Pressable
                  disabled={busy || !identifier.trim()}
                  onPress={async () => {
                    setBusy(true);
                    try {
                      const r = await mobileApi.post("/auth/otp/request", { target: identifier.trim(), purpose: "login" });
                      setDevOtp(r.data.dev_otp || null);
                    } catch (e: unknown) {
                      setMsg(getMobileApiError(e));
                    } finally {
                      setBusy(false);
                    }
                  }}
                  style={[styles.btn, { paddingHorizontal: 12 }]}
                >
                  <Text style={{ color: "#fff", fontWeight: "700" }}>Send OTP</Text>
                </Pressable>
              </View>
              {devOtp && <Text style={{ fontSize: 11, color: "#b45309" }}>Dev OTP: {devOtp}</Text>}
              {Boolean(msg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{msg}</Text>}
              <Pressable disabled={busy} onPress={login} style={styles.btn}>
                <Text style={{ color: "#fff", fontWeight: "800" }}>{busy ? "Signing in..." : "Verify OTP & Sign In"}</Text>
              </Pressable>
            </>
          ) : (
            <>
              <TextInput style={styles.input} value={password} onChangeText={setPassword} secureTextEntry placeholder="Password" />
              {Boolean(msg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{msg}</Text>}
              <Pressable disabled={busy} onPress={login} style={styles.btn}>
                <Text style={{ color: "#fff", fontWeight: "800" }}>{busy ? "Signing in..." : "Sign In"}</Text>
              </Pressable>
              <Pressable onPress={() => setResetMode(true)}>
                <Text style={{ color: "#ea580c", fontSize: 12, fontWeight: "700", textAlign: "right" }}>Forgot Password?</Text>
              </Pressable>
            </>
          )}
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.title}>Universal Customer Account</Text>
          <Text style={styles.sub}>One account for students, faculty & campus visitors.</Text>
          <TextInput style={styles.input} value={regName} onChangeText={setRegName} placeholder="Full Name *" />
          <TextInput style={styles.input} value={regEmail} onChangeText={setRegEmail} placeholder="Email (or enter phone)" autoCapitalize="none" />
          <TextInput style={styles.input} value={regPhone} onChangeText={setRegPhone} placeholder="Mobile (+9198...)" />
          <TextInput style={styles.input} value={regCollegeId} onChangeText={setRegCollegeId} placeholder="College ID / Roll No (optional)" />
          <TextInput style={styles.input} value={regReferral} onChangeText={setRegReferral} placeholder="Referral Code (optional)" />
          <TextInput style={styles.input} value={password} onChangeText={setPassword} secureTextEntry placeholder="Password (min 8 chars)" />
          {Boolean(msg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{msg}</Text>}
          <Pressable disabled={busy} onPress={register} style={styles.btn}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>{busy ? "Creating..." : "Create Universal Account"}</Text>
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
