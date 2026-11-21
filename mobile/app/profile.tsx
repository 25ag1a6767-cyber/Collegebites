import React, { useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { z } from "zod";
import { authApi } from "../src/api/auth.api";
import { canteensApi } from "../src/api/canteens.api";
import { getMobileApiError } from "../src/api/client";
import { notificationsApi } from "../src/api/notifications.api";
import { profileApi } from "../src/api/profile.api";
import { registerExpoPushToken } from "../src/notifications/registerPush";
import { useMobileStore } from "../src/store/useMobileStore";

const DIETARY_OPTS = [
  { key: "veg", label: "Veg" },
  { key: "non_veg", label: "Non-Veg" },
  { key: "eggetarian", label: "Eggetarian" },
  { key: "vegan", label: "Vegan" },
];

const loginFormSchema = z.object({
  identifier: z.string().trim().min(3, "Enter email or mobile number"),
  password: z.string().min(1, "Enter your password"),
});

const registerFormSchema = z
  .object({
    fullName: z.string().trim().min(2, "Full name must be at least 2 characters"),
    email: z.string().trim().optional(),
    phone: z.string().trim().optional(),
    collegeId: z.string().trim().optional(),
    referralCode: z.string().trim().optional(),
    password: z.string().min(8, "Password must be at least 8 characters"),
  })
  .refine((d) => Boolean(d.email?.trim() || d.phone?.trim()), {
    message: "Provide either email or mobile number",
    path: ["email"],
  });

export default function ProfileScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const { user, setAuth, logout } = useMobileStore();

  const [mode, setMode] = useState<"login" | "register">("login");
  const [loginMethod, setLoginMethod] = useState<"password" | "otp">("password");
  const [identifier, setIdentifier] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [resetMode, setResetMode] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [policyModalOpen, setPolicyModalOpen] = useState(false);

  const {
    control: loginControl,
    handleSubmit: handleLoginSubmit,
    formState: { errors: loginErrors },
  } = useForm<z.infer<typeof loginFormSchema>>({
    resolver: zodResolver(loginFormSchema),
    defaultValues: { identifier: "", password: "" },
  });

  const {
    control: regControl,
    handleSubmit: handleRegSubmit,
    formState: { errors: regErrors },
  } = useForm<z.infer<typeof registerFormSchema>>({
    resolver: zodResolver(registerFormSchema),
    defaultValues: { fullName: "", email: "", phone: "", collegeId: "", referralCode: "", password: "" },
  });

  // Signed-in edit fields
  const [fullName, setFullName] = useState("");
  const [phoneInput, setPhoneInput] = useState("");
  const [collegeId, setCollegeId] = useState("");
  const [department, setDepartment] = useState("");
  const [dietaryPref, setDietaryPref] = useState("");
  const [referralInput, setReferralInput] = useState("");
  const [curPw, setCurPw] = useState("");
  const [chgNewPw, setChgNewPw] = useState("");
  const [confirmDeact, setConfirmDeact] = useState(false);

  const { data: college } = useQuery<any>({
    queryKey: ["m-college"],
    queryFn: canteensApi.getCollegeSettings,
  });

  const { data: profile } = useQuery<any>({
    queryKey: ["m-profile"],
    enabled: Boolean(user),
    queryFn: profileApi.getProfile,
  });

  const { data: loyalty } = useQuery<any>({
    queryKey: ["m-loyalty"],
    enabled: Boolean(user),
    queryFn: profileApi.getMyLoyalty,
  });

  const { data: favourites = [] } = useQuery<any[]>({
    queryKey: ["m-favourites"],
    enabled: Boolean(user),
    queryFn: profileApi.listFavourites,
  });

  const { data: notifications = [], refetch: refetchNotifs } = useQuery<any[]>({
    queryKey: ["m-notifs"],
    enabled: Boolean(user),
    queryFn: notificationsApi.listMy,
  });

  const { data: prefs } = useQuery<any>({
    queryKey: ["m-notif-prefs"],
    enabled: Boolean(user),
    queryFn: notificationsApi.getPreferences,
  });

  useEffect(() => {
    if (profile) {
      setFullName(profile.full_name || "");
      setPhoneInput(profile.phone || "");
      setCollegeId(profile.college_id_number || "");
      setDepartment(profile.department || "");
      setDietaryPref(profile.dietary_preference || "");
    }
  }, [profile]);

  const onPasswordLogin = async (values: z.infer<typeof loginFormSchema>) => {
    setMsg("");
    setBusy(true);
    try {
      const res = await authApi.login({
        identifier: values.identifier.trim(),
        password: values.password,
        device_info: "CollegeBites Mobile App",
      });
      await setAuth(res.access_token, res.refresh_token, res.user);
      await registerExpoPushToken();
    } catch (e: unknown) {
      setMsg(getMobileApiError(e, "Login failed"));
    } finally {
      setBusy(false);
    }
  };

  const onOtpLogin = async () => {
    setMsg("");
    setBusy(true);
    try {
      const res = await authApi.otpLogin({
        target: identifier.trim(),
        code: otpCode.trim(),
        device_info: "CollegeBites Mobile App",
      });
      await setAuth(res.access_token, res.refresh_token, res.user);
      await registerExpoPushToken();
    } catch (e: unknown) {
      setMsg(getMobileApiError(e, "OTP login failed"));
    } finally {
      setBusy(false);
    }
  };

  const onRegister = async (values: z.infer<typeof registerFormSchema>) => {
    setMsg("");
    setBusy(true);
    try {
      const res = await authApi.register({
        full_name: values.fullName.trim(),
        email: values.email?.trim() || null,
        phone: values.phone?.trim() || null,
        password: values.password,
        college_id_number: values.collegeId?.trim() || null,
        referral_code: values.referralCode?.trim() || null,
      });
      await setAuth(res.access_token, res.refresh_token, res.user);
      await registerExpoPushToken();
    } catch (e: unknown) {
      setMsg(getMobileApiError(e, "Registration failed"));
    } finally {
      setBusy(false);
    }
  };

  const policyModal = (
    <Modal visible={policyModalOpen} animationType="slide" onRequestClose={() => setPolicyModalOpen(false)}>
      <ScrollView style={styles.container} contentContainerStyle={{ gap: 14, paddingTop: 28, paddingBottom: 40 }}>
        <View style={styles.prefRow}>
          <Text style={styles.title}>Privacy, Terms &amp; Payment Policy</Text>
          <Pressable onPress={() => setPolicyModalOpen(false)} style={styles.closeBtn}>
            <Text style={{ fontWeight: "800" }}>Close</Text>
          </Pressable>
        </View>
        <View style={styles.card}>
          <Text style={styles.secTitle}>College Cancellation &amp; Payment Policy</Text>
          <Text style={styles.sub}>
            {college?.cancellation_policy_text ||
              "All online payments processed through CollegeBites are final. No in-app refunds or wallets are provided; exceptional adjustments require college finance review."}
          </Text>
        </View>
        <View style={styles.card}>
          <Text style={styles.secTitle}>Privacy &amp; Data Protection</Text>
          <Text style={styles.sub}>
            Tokens and session secrets are stored strictly in encrypted Expo SecureStore (or browser storage on Web). Card details are never stored by CollegeBites. Location and pickup QR codes carry only signed identifiers — never personal phone numbers or credentials.
          </Text>
        </View>
      </ScrollView>
    </Modal>
  );

  if (user) {
    return (
      <ScrollView style={styles.container} contentContainerStyle={{ gap: 12, paddingBottom: 40 }}>
        {policyModal}
        <View style={styles.card}>
          <Text style={styles.title}>{user.full_name}</Text>
          <Text style={styles.sub}>{user.email || user.phone}</Text>
          <TextInput style={styles.input} value={fullName} onChangeText={setFullName} placeholder="Full Name" />
          <TextInput style={styles.input} value={phoneInput} onChangeText={setPhoneInput} placeholder="Mobile (+91...)" />
          <TextInput style={styles.input} value={collegeId} onChangeText={setCollegeId} placeholder="College ID / Roll No" />
          <TextInput style={styles.input} value={department} onChangeText={setDepartment} placeholder="Department" />
          <View style={{ gap: 6 }}>
            <Text style={{ fontSize: 12, fontWeight: "700", color: "#334155" }}>Dietary Preference</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {DIETARY_OPTS.map((d) => (
                <Pressable
                  key={d.key}
                  onPress={() => setDietaryPref(d.key)}
                  style={[styles.prefPill, dietaryPref === d.key && styles.prefPillActive]}
                >
                  <Text style={{ fontSize: 11, fontWeight: "700", color: dietaryPref === d.key ? "#fff" : "#334155" }}>
                    {d.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
          <Pressable
            disabled={busy}
            onPress={async () => {
              setBusy(true);
              setMsg("");
              try {
                await profileApi.updateProfile({
                  full_name: fullName,
                  phone: phoneInput.trim() || null,
                  college_id_number: collegeId,
                  department,
                  dietary_preference: dietaryPref || null,
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
            Referral Code: {loyalty?.referral_code || "Place 1st order to unlock"} • Saved Favourites:{" "}
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
                  const res = await profileApi.applyReferral(referralInput);
                  setMsg(res.message);
                  qc.invalidateQueries({ queryKey: ["m-loyalty"] });
                } catch (e: unknown) {
                  setMsg(getMobileApiError(e, "Invalid referral code"));
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
                      await notificationsApi.updatePreferences({ [key]: !prefs[key] });
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
                    await notificationsApi.markAllRead();
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
                      await notificationsApi.markRead(n.id);
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
                await authApi.changePassword({ current_password: curPw, new_password: chgNewPw });
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

        <Pressable onPress={() => setPolicyModalOpen(true)} style={styles.policyBtn}>
          <Text style={{ color: "#0f172a", fontWeight: "700", fontSize: 12 }}>
            Privacy Policy, Terms &amp; No-Refund Disclosure
          </Text>
        </Pressable>

        {user.roles.includes("customer") && user.roles.length === 1 && (
          <Pressable
            onPress={async () => {
              if (!confirmDeact) {
                setConfirmDeact(true);
                return;
              }
              try {
                await profileApi.deactivateAccount();
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
      {policyModal}
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

          {resetMode ? (
            <>
              <TextInput
                style={styles.input}
                value={identifier}
                onChangeText={setIdentifier}
                placeholder="Email or Phone"
                autoCapitalize="none"
              />
              <View style={{ flexDirection: "row", gap: 6 }}>
                <TextInput
                  style={[styles.input, { flex: 1 }]}
                  value={otpCode}
                  onChangeText={setOtpCode}
                  placeholder="Reset OTP"
                  maxLength={6}
                />
                <Pressable
                  disabled={busy || !identifier.trim()}
                  onPress={async () => {
                    setBusy(true);
                    try {
                      const r = await authApi.requestOtp({ target: identifier.trim(), purpose: "password_reset" });
                      setDevOtp(r.dev_otp || null);
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
              <TextInput
                style={styles.input}
                secureTextEntry
                value={newPassword}
                onChangeText={setNewPassword}
                placeholder="New Password (8+ chars)"
              />
              {Boolean(msg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{msg}</Text>}
              <Pressable
                disabled={busy || otpCode.trim().length < 6 || newPassword.length < 8}
                onPress={async () => {
                  setBusy(true);
                  try {
                    await authApi.confirmPasswordReset({
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
              <TextInput
                style={styles.input}
                value={identifier}
                onChangeText={setIdentifier}
                placeholder="Email or Phone"
                autoCapitalize="none"
              />
              <View style={{ flexDirection: "row", gap: 6 }}>
                <TextInput
                  style={[styles.input, { flex: 1 }]}
                  value={otpCode}
                  onChangeText={setOtpCode}
                  placeholder="6-digit OTP"
                  maxLength={6}
                />
                <Pressable
                  disabled={busy || !identifier.trim()}
                  onPress={async () => {
                    setBusy(true);
                    try {
                      const r = await authApi.requestOtp({ target: identifier.trim(), purpose: "login" });
                      setDevOtp(r.dev_otp || null);
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
              <Pressable disabled={busy} onPress={onOtpLogin} style={styles.btn}>
                <Text style={{ color: "#fff", fontWeight: "800" }}>{busy ? "Signing in..." : "Verify OTP & Sign In"}</Text>
              </Pressable>
            </>
          ) : (
            <>
              <Controller
                control={loginControl}
                name="identifier"
                render={({ field: { onChange, value } }) => (
                  <TextInput
                    style={styles.input}
                    value={value}
                    onChangeText={onChange}
                    placeholder="Email or Phone"
                    autoCapitalize="none"
                  />
                )}
              />
              {loginErrors.identifier && <Text style={styles.fieldErr}>{loginErrors.identifier.message}</Text>}
              <Controller
                control={loginControl}
                name="password"
                render={({ field: { onChange, value } }) => (
                  <TextInput
                    style={styles.input}
                    value={value}
                    onChangeText={onChange}
                    secureTextEntry
                    placeholder="Password"
                  />
                )}
              />
              {loginErrors.password && <Text style={styles.fieldErr}>{loginErrors.password.message}</Text>}
              {Boolean(msg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{msg}</Text>}
              <Pressable disabled={busy} onPress={handleLoginSubmit(onPasswordLogin)} style={styles.btn}>
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
          <Text style={styles.sub}>One account for students, faculty &amp; campus visitors.</Text>
          <Controller
            control={regControl}
            name="fullName"
            render={({ field: { onChange, value } }) => (
              <TextInput style={styles.input} value={value} onChangeText={onChange} placeholder="Full Name *" />
            )}
          />
          {regErrors.fullName && <Text style={styles.fieldErr}>{regErrors.fullName.message}</Text>}
          <Controller
            control={regControl}
            name="email"
            render={({ field: { onChange, value } }) => (
              <TextInput
                style={styles.input}
                value={value || ""}
                onChangeText={onChange}
                placeholder="Email (or enter phone)"
                autoCapitalize="none"
              />
            )}
          />
          {regErrors.email && <Text style={styles.fieldErr}>{regErrors.email.message}</Text>}
          <Controller
            control={regControl}
            name="phone"
            render={({ field: { onChange, value } }) => (
              <TextInput style={styles.input} value={value || ""} onChangeText={onChange} placeholder="Mobile (+9198...)" />
            )}
          />
          <Controller
            control={regControl}
            name="collegeId"
            render={({ field: { onChange, value } }) => (
              <TextInput
                style={styles.input}
                value={value || ""}
                onChangeText={onChange}
                placeholder="College ID / Roll No (optional)"
              />
            )}
          />
          <Controller
            control={regControl}
            name="referralCode"
            render={({ field: { onChange, value } }) => (
              <TextInput
                style={styles.input}
                value={value || ""}
                onChangeText={onChange}
                placeholder="Referral Code (optional)"
              />
            )}
          />
          <Controller
            control={regControl}
            name="password"
            render={({ field: { onChange, value } }) => (
              <TextInput
                style={styles.input}
                value={value}
                onChangeText={onChange}
                secureTextEntry
                placeholder="Password (min 8 chars)"
              />
            )}
          />
          {regErrors.password && <Text style={styles.fieldErr}>{regErrors.password.message}</Text>}
          {Boolean(msg) && <Text style={{ color: "#dc2626", fontSize: 12 }}>{msg}</Text>}
          <Pressable disabled={busy} onPress={handleRegSubmit(onRegister)} style={styles.btn}>
            <Text style={{ color: "#fff", fontWeight: "800" }}>
              {busy ? "Creating..." : "Create Universal Account"}
            </Text>
          </Pressable>
        </View>
      )}

      <View style={{ flexDirection: "row", gap: 8 }}>
        <Pressable onPress={() => router.push("/board")} style={[styles.btnAlt, { flex: 1 }]}>
          <Text style={{ color: "#fff", fontWeight: "800" }}>Live Token Board</Text>
        </Pressable>
        <Pressable onPress={() => router.push("/support")} style={[styles.btnAlt, { flex: 1 }]}>
          <Text style={{ color: "#fff", fontWeight: "800" }}>Support &amp; Help</Text>
        </Pressable>
      </View>

      <Pressable onPress={() => setPolicyModalOpen(true)} style={styles.policyBtn}>
        <Text style={{ color: "#0f172a", fontWeight: "700", fontSize: 12 }}>
          Privacy Policy, Terms &amp; No-Refund Disclosure
        </Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16 },
  title: { fontSize: 19, fontWeight: "800", color: "#0f172a" },
  secTitle: { fontSize: 14, fontWeight: "800", color: "#0f172a" },
  sub: { fontSize: 12, color: "#475569", lineHeight: 18 },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 14, gap: 10, borderWidth: 1, borderColor: "#e2e8f0" },
  input: { backgroundColor: "#fff", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9 },
  fieldErr: { fontSize: 11, color: "#dc2626", fontWeight: "700" },
  btn: { backgroundColor: "#ea580c", borderRadius: 10, paddingVertical: 12, alignItems: "center", justifyContent: "center" },
  btnAlt: { backgroundColor: "#334155", borderRadius: 10, paddingVertical: 12, alignItems: "center" },
  logoutBtn: { backgroundColor: "#0f172a", borderRadius: 10, padding: 13, alignItems: "center" },
  policyBtn: { backgroundColor: "#e2e8f0", borderRadius: 10, padding: 12, alignItems: "center" },
  closeBtn: { backgroundColor: "#e2e8f0", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8 },
  prefRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  prefPill: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 14, backgroundColor: "#f1f5f9", borderWidth: 1, borderColor: "#cbd5e1" },
  prefPillActive: { backgroundColor: "#ea580c", borderColor: "#ea580c" },
  notifRow: { borderBottomWidth: 1, borderBottomColor: "#f1f5f9", paddingBottom: 6 },
  tabRow: { flexDirection: "row", gap: 8 },
  tabBtn: { flex: 1, backgroundColor: "#e2e8f0", borderRadius: 10, paddingVertical: 10, alignItems: "center" },
  tabBtnActive: { backgroundColor: "#0f172a" },
  tabTxt: { fontWeight: "800", color: "#334155" },
});
