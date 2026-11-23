import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Award, Bell, Check, Gift, Heart, KeyRound, Laptop, ShieldOff } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { FoodItem } from "../../types";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, ConfirmModal, Input, useToast } from "../../components/ui/Primitives";

export const ProfilePage: React.FC = () => {
  const { user, logout, setSelectedCanteen } = useAppStore();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { pushToast } = useToast();

  const { data: profile } = useQuery<any>({
    queryKey: ["customer-profile"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/customers/profile")).data,
  });

  const { data: favourites = [], refetch: refetchFavs } = useQuery<FoodItem[]>({
    queryKey: ["customer-favourites"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/customers/favourites")).data,
  });

  const { data: loyalty } = useQuery<any>({
    queryKey: ["loyalty-me"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/promotions/loyalty/me")).data,
  });

  const { data: notifications = [], refetch: refetchNotifs } = useQuery<any[]>({
    queryKey: ["notifications-my"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/notifications/my")).data,
  });

  const { data: prefs } = useQuery<any>({
    queryKey: ["notif-prefs"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/notifications/preferences")).data,
  });

  const { data: sessions = [], refetch: refetchSessions } = useQuery<any[]>({
    queryKey: ["auth-sessions"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/auth/sessions")).data,
  });

  const { data: mealPlans = [] } = useQuery<any[]>({
    queryKey: ["available-meal-plans"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/meal-plans")).data,
  });

  const { data: mySubscriptions = [], refetch: refetchMySubs } = useQuery<any[]>({
    queryKey: ["my-meal-subscriptions"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/meal-plans/my-subscriptions")).data,
  });

  const { data: collegeEvents = [] } = useQuery<any[]>({
    queryKey: ["active-college-events"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/events")).data,
  });

  const { data: myBulkOrders = [] } = useQuery<any[]>({
    queryKey: ["my-bulk-orders"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/events/bulk-orders/my")).data,
  });

  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [collegeId, setCollegeId] = useState("");
  const [department, setDepartment] = useState("");
  const [referralInput, setReferralInput] = useState("");
  const [phoneOtpSent, setPhoneOtpSent] = useState(false);
  const [phoneOtpCode, setPhoneOtpCode] = useState("");
  const [devOtpHint, setDevOtpHint] = useState<string | null>(null);
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);

  useEffect(() => {
    if (profile) {
      setFullName(profile.full_name || "");
      setPhone(profile.phone || "");
      setCollegeId(profile.college_id_number || "");
      setDepartment(profile.department || "");
    }
  }, [profile]);

  if (!user) {
    return (
      <div className="mx-auto max-w-lg px-4 py-14 text-center">
        <Card className="p-8">Sign in to manage your profile, loyalty rewards, and notifications.</Card>
      </div>
    );
  }

  const saveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.patch("/customers/profile", {
        full_name: fullName,
        phone: phone.trim() || null,
        college_id_number: collegeId,
        department,
      });
      qc.invalidateQueries({ queryKey: ["customer-profile"] });
      pushToast("Profile updated", "success");
    } catch (err) {
      pushToast(getApiError(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const applyReferral = async () => {
    try {
      const res = await api.post(`/promotions/loyalty/apply-referral?referral_code=${encodeURIComponent(referralInput)}`);
      pushToast(res.data.message, "success");
      qc.invalidateQueries({ queryKey: ["loyalty-me"] });
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const togglePref = async (key: string, currentVal: boolean) => {
    try {
      await api.put("/notifications/preferences", { [key]: !currentVal });
      qc.invalidateQueries({ queryKey: ["notif-prefs"] });
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/auth/change-password", { current_password: curPw, new_password: newPw });
      setCurPw("");
      setNewPw("");
      pushToast("Password updated successfully", "success");
      refetchSessions();
    } catch (err) {
      pushToast(getApiError(err), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
      <div className="flex items-center gap-3">
        <BrandLogo size="md" />
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900">Account, Loyalty &amp; Notifications</h1>
          <p className="text-xs text-slate-500">{user.full_name} • {user.email || user.phone}</p>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-5 space-y-4">
          <h2 className="font-bold text-slate-900">Universal Profile</h2>
          <form onSubmit={saveProfile} className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-bold text-slate-600">Full Name</label>
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-bold text-slate-600">Mobile Number</label>
              <div className="flex gap-2">
                <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+919876543210" />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy || !phone.trim()}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      const r = await api.post("/auth/otp/request", { target: phone.trim(), purpose: "phone_verify" });
                      setPhoneOtpSent(true);
                      setDevOtpHint(r.data.dev_otp || null);
                      pushToast("Verification OTP sent", "success");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Verify OTP
                </Button>
              </div>
              {phoneOtpSent && (
                <div className="mt-2 flex gap-2 items-center">
                  <Input
                    value={phoneOtpCode}
                    onChange={(e) => setPhoneOtpCode(e.target.value)}
                    placeholder="6-digit OTP"
                    maxLength={6}
                    className="w-36"
                  />
                  <Button
                    type="button"
                    size="sm"
                    disabled={busy || phoneOtpCode.trim().length < 6}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await api.post("/auth/phone/verify", { target: phone.trim(), code: phoneOtpCode.trim() });
                        setPhoneOtpSent(false);
                        setPhoneOtpCode("");
                        qc.invalidateQueries({ queryKey: ["customer-profile"] });
                        pushToast("Mobile number verified!", "success");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Confirm
                  </Button>
                  {devOtpHint && <span className="text-xs font-mono text-slate-600">OTP: {devOtpHint}</span>}
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-bold text-slate-600">College ID / Roll No</label>
                <Input value={collegeId} onChange={(e) => setCollegeId(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold text-slate-600">Department</label>
                <Input value={department} onChange={(e) => setDepartment(e.target.value)} />
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {user.roles.map((r) => (
                <Badge key={r} tone="slate">
                  {r}
                </Badge>
              ))}
            </div>
            <Button type="submit" size="sm" disabled={busy}>
              Save Profile
            </Button>
          </form>
        </Card>

        <Card className="p-5 space-y-4 bg-gradient-to-br from-[#fdf8f0] to-[#fdedce]/60 border-[#76010d]/25">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-[#380106]">
              <Award className="h-5 w-5 text-[#76010d]" /> Campus Loyalty Rewards
            </div>
            <Badge tone="default">{loyalty?.tier_level || "BRONZE"}</Badge>
          </div>
          <div className="text-3xl font-black text-[#76010d]">{loyalty?.points_balance || 0} pts</div>
          <div className="text-xs text-slate-600">
            Your Referral Code: <strong className="font-mono text-slate-900">{loyalty?.referral_code || "N/A"}</strong>
          </div>
          <div className="flex gap-2">
            <Input
              value={referralInput}
              onChange={(e) => setReferralInput(e.target.value)}
              placeholder="Have a friend's referral code?"
            />
            <Button size="sm" variant="primary" onClick={applyReferral}>
              <Gift className="h-3.5 w-3.5" /> Apply
            </Button>
          </div>
          <div className="text-xs text-slate-500 flex items-center gap-1">
            <Heart className="h-3.5 w-3.5 text-red-500" /> {profile?.favourite_item_ids?.length || 0} saved favourite items
          </div>
        </Card>
      </div>

      {/* Notification Preferences & Inbox */}
      <div className="grid gap-6 md:grid-cols-3">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900">Notification Channels</h2>
          {typeof window !== "undefined" && "Notification" in window && Notification.permission !== "granted" && (
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                const { enableBrowserPushNotifications } = await import("../../utils/notifications");
                const r = await enableBrowserPushNotifications();
                if (r.granted) pushToast("Browser notifications enabled!", "success");
              }}
            >
              <Bell className="h-3.5 w-3.5" /> Enable Browser Alerts
            </Button>
          )}
          {prefs &&
            [
              ["in_app_enabled", "In-App Alerts"],
              ["push_enabled", "Mobile Push"],
              ["email_enabled", "Email Updates"],
              ["sms_enabled", "SMS Alerts"],
              ["whatsapp_enabled", "WhatsApp Updates"],
            ].map(([k, label]) => (
              <label key={k} className="flex items-center justify-between text-sm cursor-pointer">
                <span>{label}</span>
                <input type="checkbox" checked={Boolean(prefs[k])} onChange={() => togglePref(k, Boolean(prefs[k]))} />
              </label>
            ))}
        </Card>

        <Card className="md:col-span-2 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-slate-900">
              <Bell className="h-4 w-4 text-[#76010d]" /> Recent Notifications ({notifications.length})
            </div>
            {notifications.some((n) => !n.is_read) && (
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    await api.post("/notifications/mark-all-read");
                    refetchNotifs();
                    pushToast("All notifications marked read", "success");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Mark All Read
              </Button>
            )}
          </div>
          <div className="space-y-2 max-h-72 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="text-xs text-slate-500">No notifications yet.</div>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  className={`flex items-start justify-between rounded-xl border p-3 text-xs ${
                    n.is_read ? "border-slate-100 bg-white" : "border-[#76010d]/25 bg-[#fdf8f0]"
                  }`}
                >
                  <div>
                    <div className="font-bold text-slate-900">{n.title}</div>
                    <div className="text-slate-600 mt-0.5">{n.message}</div>
                  </div>
                  {!n.is_read && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        try {
                          await api.post(`/notifications/${n.id}/read`);
                          refetchNotifs();
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      <Check className="h-3.5 w-3.5" /> Read
                    </Button>
                  )}
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Saved Favourites */}
      <Card className="p-5 space-y-3">
        <div className="flex items-center gap-2 font-bold text-slate-900">
          <Heart className="h-4 w-4 text-red-500 fill-red-500" /> Saved Favourite Dishes ({favourites.length})
        </div>
        {favourites.length === 0 ? (
          <div className="text-xs text-slate-500">Tap the heart icon on any dish in the menu to save it here.</div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {favourites.map((item) => (
              <div key={item.id} className="flex items-center justify-between rounded-xl border border-slate-200 p-3 text-xs">
                <div>
                  <div className="font-bold text-slate-900">{item.name}</div>
                  <div className="text-slate-500">₹{item.base_price} • {item.category_name}</div>
                </div>
                <div className="flex items-center gap-1.5">
                  <Link
                    to="/"
                    onClick={() => setSelectedCanteen(item.canteen_id)}
                    className="rounded-lg bg-[#76010d] px-2.5 py-1 font-bold text-white"
                  >
                    Order
                  </Link>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await api.delete(`/customers/favourites/${item.id}`);
                        refetchFavs();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                    className="rounded-lg border border-slate-200 px-2 py-1 text-slate-500 hover:text-red-600"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Student Meal Plans & College Events Bulk Orders */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <div className="font-bold text-slate-900">Student Meal Plans ({mySubscriptions.length} Subscribed)</div>
          {mySubscriptions.length > 0 && (
            <div className="space-y-2 text-xs">
              {mySubscriptions.map((sub: any) => (
                <div key={sub.id} className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-3 space-y-1">
                  <div className="flex justify-between font-bold text-slate-900">
                    <span>{sub.meal_plan_name} ({sub.subscription_number})</span>
                    <Badge tone={sub.status === "active" ? "green" : "amber"}>{sub.status.toUpperCase()}</Badge>
                  </div>
                  <div className="text-slate-700">
                    Remaining Meals: <strong>{sub.remaining_meals} / {sub.total_meals}</strong> • Expires: {(sub.expires_at || "").slice(0, 10) || "Pending"}
                  </div>
                  {sub.redemption_code && (
                    <div className="font-mono text-[11px] bg-white border border-emerald-200 rounded px-2 py-1 text-emerald-900">
                      Redemption Code: <strong>{sub.redemption_code}</strong> • QR: {sub.redemption_qr_payload}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          <div className="space-y-2 pt-2 border-t border-slate-100 text-xs">
            <div className="font-bold text-slate-600 uppercase text-[11px]">Available Campus Meal Plans ({mealPlans.length})</div>
            {mealPlans.length === 0 ? (
              <div className="text-slate-500">No active meal plans configured right now.</div>
            ) : (
              mealPlans.map((mp: any) => (
                <div key={mp.id} className="flex items-center justify-between rounded-xl border border-slate-200 p-2.5">
                  <div>
                    <div className="font-bold text-slate-900">{mp.name}</div>
                    <div className="text-[11px] text-slate-500">
                      {mp.total_meals} Meals • {mp.validity_days} Days • ₹{mp.total_price}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    onClick={async () => {
                      try {
                        await api.post(`/meal-plans/${mp.id}/subscribe`, { payment_method: "razorpay" });
                        pushToast("Subscription created! Complete payment to activate.", "info");
                        refetchMySubs();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Subscribe
                  </Button>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card className="p-5 space-y-3">
          <div className="font-bold text-slate-900">College Events &amp; Bulk Orders ({myBulkOrders.length})</div>
          <div className="space-y-2 text-xs max-h-60 overflow-y-auto">
            {myBulkOrders.map((bo: any) => (
              <div key={bo.id} className="rounded-xl border border-slate-200 p-2.5 space-y-1">
                <div className="flex justify-between font-bold">
                  <span>{bo.bulk_order_number} — {bo.event_name}</span>
                  <Badge tone={bo.status === "completed" ? "green" : "amber"}>{bo.status}</Badge>
                </div>
                <div className="text-slate-600">
                  {bo.total_quantity} portions • ₹{bo.total_amount} • Payment: {bo.payment_status}
                  {bo.group_pickup_token ? ` • Token: ${bo.group_pickup_token}` : ""}
                </div>
              </div>
            ))}
            {collegeEvents.length === 0 ? (
              <div className="text-slate-500">No active college events open for bulk ordering right now.</div>
            ) : (
              collegeEvents.map((ev: any) => (
                <div key={ev.id} className="rounded-xl border border-blue-200 bg-blue-50/40 p-2.5">
                  <div className="font-bold text-slate-900">{ev.name} ({ev.department})</div>
                  <div className="text-[11px] text-slate-600">
                    Event Date: {ev.event_date} • Venue: {ev.location} • Min/Max Qty: {ev.min_order_quantity}–{ev.max_order_quantity}
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Password, Sessions & Account Closure */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <div className="flex items-center gap-2 font-bold text-slate-900">
            <KeyRound className="h-4 w-4 text-[#76010d]" /> Change Password
          </div>
          <form onSubmit={changePassword} className="space-y-3">
            <Input
              type="password"
              required
              value={curPw}
              onChange={(e) => setCurPw(e.target.value)}
              placeholder="Current Password"
            />
            <Input
              type="password"
              required
              minLength={8}
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              placeholder="New Password (8+ characters)"
            />
            <Button type="submit" size="sm" disabled={busy}>
              Update Password
            </Button>
          </form>

          {user.roles.includes("customer") && user.roles.length === 1 && (
            <div className="border-t border-slate-100 pt-3 flex items-center justify-between">
              <div className="text-xs text-slate-500">Leave campus or deactivate this customer account?</div>
              <Button size="sm" variant="danger" onClick={() => setConfirmDeactivate(true)}>
                <ShieldOff className="h-3.5 w-3.5" /> Deactivate Account
              </Button>
            </div>
          )}
        </Card>

        <Card className="p-5 space-y-3">
          <div className="flex items-center gap-2 font-bold text-slate-900">
            <Laptop className="h-4 w-4 text-[#76010d]" /> Active Sign-in Sessions ({sessions.length})
          </div>
          <div className="space-y-2 max-h-56 overflow-y-auto text-xs">
            {sessions.map((s) => (
              <div key={s.id} className="flex items-center justify-between rounded-xl border border-slate-200 p-2.5">
                <div>
                  <div className="font-bold text-slate-900">
                    {s.device_info || "Web / Mobile Session"} {s.is_current && <Badge tone="green">Current</Badge>}
                  </div>
                  <div className="text-slate-500">
                    IP: {s.ip_address || "unknown"} • {new Date(s.created_at).toLocaleString()}
                  </div>
                </div>
                {!s.is_current && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      try {
                        await api.delete(`/auth/sessions/${s.id}`);
                        refetchSessions();
                        pushToast("Session revoked", "info");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Revoke
                  </Button>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>

      <ConfirmModal
        open={confirmDeactivate}
        title="Deactivate Customer Account?"
        message="Your login sessions will be closed while historical order & payment records remain preserved. An administrator can reactivate your account later if needed."
        confirmLabel="Deactivate Account"
        busy={busy}
        onCancel={() => setConfirmDeactivate(false)}
        onConfirm={async () => {
          setBusy(true);
          try {
            await api.delete("/customers/me");
            setConfirmDeactivate(false);
            logout();
            qc.clear();
            pushToast("Account deactivated", "info");
            navigate("/");
          } catch (err) {
            pushToast(getApiError(err), "error");
          } finally {
            setBusy(false);
          }
        }}
      />
    </div>
  );
};
