import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { Award, Bell, Calendar, Check, CreditCard, Download, Gift, Heart, KeyRound, Laptop, Plus, ShieldOff, Utensils } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { FoodItem } from "../../types";
import { enableBrowserPushNotifications } from "../../utils/notifications";
import { openRazorpayCustomCheckout } from "../../utils/razorpay";
import { OtpVerificationBox } from "../../components/auth/OtpVerificationBox";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, ConfirmModal, Input, Modal, Select, useToast } from "../../components/ui/Primitives";

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

  const { data: myBulkOrders = [], refetch: refetchMyBulkOrders } = useQuery<any[]>({
    queryKey: ["my-bulk-orders"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/events/bulk-orders/my")).data,
  });

  const [bulkEventTarget, setBulkEventTarget] = useState<any | null>(null);
  const [bulkPrepTime, setBulkPrepTime] = useState("");
  const [bulkPickupTime, setBulkPickupTime] = useState("");
  const [bulkArrangement, setBulkArrangement] = useState<"grouped_token" | "individual_tokens">("grouped_token");
  const [bulkNotes, setBulkNotes] = useState("");
  const [bulkFoodId, setBulkFoodId] = useState("");
  const [bulkQty, setBulkQty] = useState("20");

  const { data: bulkEventMenu = [] } = useQuery<FoodItem[]>({
    queryKey: ["bulk-event-menu", bulkEventTarget?.canteen_id],
    enabled: Boolean(bulkEventTarget?.canteen_id),
    queryFn: async () => (await api.get(`/menus/canteens/${bulkEventTarget.canteen_id}/items`)).data,
  });

  const downloadInvoicePdf = async (refNumber: string) => {
    try {
      const res = await api.get(`/invoices/${refNumber}/pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Invoice-${refNumber}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      pushToast(getApiError(err, "Failed to download tax invoice"), "error");
    }
  };

  const launchMealPlanPayment = async (sub: any) => {
    const opened = await openRazorpayCustomCheckout({
      razorpayOrderId: sub.razorpay_order_id || sub.provider_order_id,
      razorpayKeyId: sub.razorpay_key_id,
      amountInr: sub.total_amount,
      description: `Meal Plan ${sub.meal_plan_name} (${sub.subscription_number})`,
      prefill: { name: user?.full_name, email: user?.email || undefined, contact: user?.phone || undefined },
      verifyEndpoint: `/meal-plans/subscriptions/${sub.id}/verify-payment`,
      onVerified: () => {
        pushToast("Meal Plan payment verified! Your QR Meal Pass is now active.", "success");
        refetchMySubs();
      },
      onError: (err) => pushToast(getApiError(err, "Meal plan payment failed"), "error"),
    });
    if (!opened) {
      pushToast("Subscription created. Complete Razorpay checkout to activate your QR Meal Pass.", "info");
    }
  };

  const launchBulkOrderPayment = async (bo: any) => {
    const opened = await openRazorpayCustomCheckout({
      razorpayOrderId: bo.razorpay_order_id || bo.provider_order_id,
      razorpayKeyId: bo.razorpay_key_id,
      amountInr: bo.total_amount,
      description: `Event Bulk Order ${bo.bulk_order_number}`,
      prefill: { name: user?.full_name, email: user?.email || undefined, contact: user?.phone || undefined },
      verifyEndpoint: `/events/bulk-orders/${bo.id}/verify-payment`,
      onVerified: () => {
        pushToast("Bulk order payment verified! Dispatched to canteen kitchen.", "success");
        refetchMyBulkOrders();
      },
      onError: (err) => pushToast(getApiError(err, "Bulk order payment failed"), "error"),
    });
    if (!opened) {
      pushToast("Bulk order awaiting live Razorpay gateway credentials.", "info");
    }
  };

  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [collegeId, setCollegeId] = useState("");
  const [department, setDepartment] = useState("");
  const [referralInput, setReferralInput] = useState("");
  const [showEmailVerify, setShowEmailVerify] = useState(false);
  const [showPhoneVerify, setShowPhoneVerify] = useState(false);
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
            {user.email && (
              <div>
                <div className="mb-1 flex items-center justify-between text-xs font-bold text-slate-600">
                  <span>Email Address ({user.email})</span>
                  {user.is_verified ? (
                    <Badge tone="green">Verified</Badge>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setShowEmailVerify((v) => !v)}
                      className="text-xs font-bold text-[#76010d] hover:underline"
                    >
                      {showEmailVerify ? "Hide Email OTP" : "Verify Email via OTP"}
                    </button>
                  )}
                </div>
                {showEmailVerify && !user.is_verified && (
                  <OtpVerificationBox
                    target={user.email}
                    purpose="email_verify"
                    verifyButtonLabel="Confirm Email OTP"
                    customVerifyRequest={async (code) => {
                      await api.post("/auth/email/verify", { target: user.email, code });
                      setShowEmailVerify(false);
                      qc.invalidateQueries({ queryKey: ["customer-profile"] });
                      pushToast("Email verified!", "success");
                    }}
                  />
                )}
              </div>
            )}
            <div>
              <label className="mb-1 block text-xs font-bold text-slate-600">Mobile Number</label>
              <div className="flex gap-2">
                <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+919876543210" />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy || !phone.trim()}
                  onClick={() => setShowPhoneVerify((v) => !v)}
                >
                  {showPhoneVerify ? "Close" : "Verify OTP"}
                </Button>
              </div>
              {showPhoneVerify && phone.trim() && (
                <div className="mt-2">
                  <OtpVerificationBox
                    target={phone.trim()}
                    purpose="phone_verify"
                    verifyButtonLabel="Confirm Phone OTP"
                    customVerifyRequest={async (code) => {
                      await api.post("/auth/phone/verify", { target: phone.trim(), code });
                      setShowPhoneVerify(false);
                      qc.invalidateQueries({ queryKey: ["customer-profile"] });
                      pushToast("Mobile number verified!", "success");
                    }}
                  />
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
          <div className="font-bold text-slate-900 flex items-center gap-2">
            <Utensils className="h-4 w-4 text-emerald-700" /> Student Meal Plans ({mySubscriptions.length} Subscribed)
          </div>
          {mySubscriptions.length > 0 && (
            <div className="space-y-2.5 text-xs">
              {mySubscriptions.map((sub: any) => (
                <div key={sub.id} className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-3 space-y-2">
                  <div className="flex justify-between items-center font-bold text-slate-900">
                    <span>{sub.meal_plan_name} ({sub.subscription_number})</span>
                    <Badge tone={sub.status === "active" ? "green" : sub.status === "exhausted" ? "blue" : "amber"}>
                      {sub.status.toUpperCase()}
                    </Badge>
                  </div>
                  <div className="text-slate-700">
                    Remaining Meals: <strong>{sub.remaining_meals} / {sub.total_meals}</strong> ({sub.used_meals || 0} used) •{" "}
                    {sub.expires_at ? `Valid until ${sub.expires_at.slice(0, 10)}` : "Awaiting Payment Verification"}
                  </div>
                  {sub.payment_status === "CONFIRMED" && sub.redemption_qr_payload ? (
                    <div className="flex flex-wrap items-center gap-3 rounded-xl bg-white border border-emerald-200 p-2.5">
                      <QRCodeSVG value={sub.redemption_qr_payload} size={84} />
                      <div className="space-y-1 flex-1">
                        <div className="text-[11px] text-slate-500">Present at Canteen Pickup Counter:</div>
                        <div className="font-mono text-sm font-black text-emerald-900">{sub.redemption_code}</div>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => downloadInvoicePdf(sub.subscription_number)}
                        >
                          <Download className="h-3 w-3" /> Tax Invoice PDF
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <Button size="sm" variant="primary" onClick={() => launchMealPlanPayment(sub)}>
                      <CreditCard className="h-3.5 w-3.5" /> Pay ₹{sub.total_amount} to Activate Pass
                    </Button>
                  )}
                  {(sub.redemptions || []).length > 0 && (
                    <div className="border-t border-emerald-200/70 pt-1.5 space-y-1 text-[11px] text-slate-600">
                      <div className="font-bold text-slate-700">Recent Meal Redemptions:</div>
                      {sub.redemptions.slice(0, 4).map((r: any) => (
                        <div key={r.id} className="flex justify-between">
                          <span>{r.meal_item_name} (-{r.meals_deducted})</span>
                          <span>{(r.redeemed_at || "").slice(0, 16).replace("T", " ")} • {r.remaining_meals_after} left</span>
                        </div>
                      ))}
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
                      {mp.plan_type.toUpperCase()} • {mp.total_meals} Meals • {mp.validity_days} Days • <strong>₹{mp.total_price}</strong>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    onClick={async () => {
                      try {
                        const res = await api.post(`/meal-plans/${mp.id}/subscribe`, { payment_method: "razorpay" });
                        await refetchMySubs();
                        await launchMealPlanPayment(res.data);
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Subscribe &amp; Pay
                  </Button>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card className="p-5 space-y-3">
          <div className="font-bold text-slate-900 flex items-center gap-2">
            <Calendar className="h-4 w-4 text-blue-700" /> College Events &amp; Bulk Orders ({myBulkOrders.length})
          </div>
          <div className="space-y-2 text-xs max-h-80 overflow-y-auto">
            {myBulkOrders.map((bo: any) => (
              <div key={bo.id} className="rounded-xl border border-slate-200 p-3 space-y-1.5">
                <div className="flex justify-between font-bold">
                  <span>{bo.bulk_order_number} — {bo.event_name}</span>
                  <Badge tone={bo.status === "completed" ? "green" : bo.status === "rejected" ? "red" : "amber"}>
                    {bo.status.toUpperCase()}
                  </Badge>
                </div>
                <div className="text-slate-600">
                  {bo.total_quantity} portions • <strong>₹{bo.total_amount}</strong> • Payment: {bo.payment_status}
                  {bo.group_pickup_token ? ` • Token: ${bo.group_pickup_token}` : ""}
                </div>
                <div className="flex flex-wrap gap-2 pt-1">
                  {bo.payment_status !== "CONFIRMED" && bo.status !== "rejected" && bo.status !== "cancelled" && (
                    <Button size="sm" variant="primary" onClick={() => launchBulkOrderPayment(bo)}>
                      <CreditCard className="h-3 w-3" /> Pay ₹{bo.total_amount}
                    </Button>
                  )}
                  {bo.payment_status === "CONFIRMED" && (
                    <Button size="sm" variant="outline" onClick={() => downloadInvoicePdf(bo.bulk_order_number)}>
                      <Download className="h-3 w-3" /> Event Tax Invoice PDF
                    </Button>
                  )}
                </div>
              </div>
            ))}
            {collegeEvents.length === 0 ? (
              <div className="text-slate-500">No active college events open for bulk ordering right now.</div>
            ) : (
              collegeEvents.map((ev: any) => (
                <div key={ev.id} className="rounded-xl border border-blue-200 bg-blue-50/40 p-3 flex items-center justify-between gap-2">
                  <div>
                    <div className="font-bold text-slate-900">{ev.name} ({ev.department})</div>
                    <div className="text-[11px] text-slate-600">
                      Date: {ev.event_date} • Venue: {ev.location} • Qty: {ev.min_order_quantity}–{ev.max_order_quantity}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={Boolean(ev.deadline_passed)}
                    onClick={() => {
                      setBulkEventTarget(ev);
                      setBulkQty(String(ev.min_order_quantity || 10));
                    }}
                  >
                    <Plus className="h-3 w-3" /> {ev.deadline_passed ? "Closed" : "Bulk Order"}
                  </Button>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Place College Event Bulk Order Modal */}
      <Modal
        open={Boolean(bulkEventTarget)}
        onClose={() => setBulkEventTarget(null)}
        title={`Event Bulk Order — ${bulkEventTarget?.name || ""}`}
        maxWidth="max-w-lg"
      >
        {bulkEventTarget && (
          <div className="space-y-3 text-xs">
            <div className="rounded-lg bg-blue-50 border border-blue-200 p-2.5 text-blue-950">
              Department: <strong>{bulkEventTarget.department}</strong> • Venue: <strong>{bulkEventTarget.location}</strong> • Allowed Quantity:{" "}
              <strong>{bulkEventTarget.min_order_quantity} – {bulkEventTarget.max_order_quantity} portions</strong>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="font-bold text-slate-600 block mb-1">Menu Dish *</label>
                <Select
                  value={bulkFoodId || bulkEventMenu[0]?.id || ""}
                  onChange={(e) => setBulkFoodId(e.target.value)}
                >
                  {bulkEventMenu.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} (₹{m.base_price})
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <label className="font-bold text-slate-600 block mb-1">Portion Quantity *</label>
                <Input
                  type="number"
                  min={bulkEventTarget.min_order_quantity}
                  max={bulkEventTarget.max_order_quantity}
                  value={bulkQty}
                  onChange={(e) => setBulkQty(e.target.value)}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="font-bold text-slate-600 block mb-1">Scheduled Preparation Time *</label>
                <Input type="datetime-local" value={bulkPrepTime} onChange={(e) => setBulkPrepTime(e.target.value)} />
              </div>
              <div>
                <label className="font-bold text-slate-600 block mb-1">Scheduled Pickup Time *</label>
                <Input type="datetime-local" value={bulkPickupTime} onChange={(e) => setBulkPickupTime(e.target.value)} />
              </div>
            </div>
            <div>
              <label className="font-bold text-slate-600 block mb-1">Token Arrangement</label>
              <Select value={bulkArrangement} onChange={(e) => setBulkArrangement(e.target.value as any)}>
                <option value="grouped_token">Single Grouped Event Pickup Token</option>
                <option value="individual_tokens">Individual Attendee Meal Tokens</option>
              </Select>
            </div>
            <Input
              value={bulkNotes}
              onChange={(e) => setBulkNotes(e.target.value)}
              placeholder="Packaging or event delivery instructions..."
            />
            <div className="flex justify-end gap-2 pt-2">
              <Button size="sm" variant="outline" onClick={() => setBulkEventTarget(null)}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant="primary"
                disabled={!bulkPrepTime || !bulkPickupTime || bulkEventMenu.length === 0}
                onClick={async () => {
                  const chosenFoodId = bulkFoodId || bulkEventMenu[0]?.id;
                  if (!chosenFoodId) return;
                  try {
                    const res = await api.post(`/events/${bulkEventTarget.id}/bulk-orders`, {
                      scheduled_prep_at: new Date(bulkPrepTime).toISOString(),
                      scheduled_pickup_at: new Date(bulkPickupTime).toISOString(),
                      pickup_arrangement: bulkArrangement,
                      payment_method: "razorpay",
                      notes: bulkNotes.trim() || null,
                      items: [{ food_item_id: chosenFoodId, quantity: Number(bulkQty) || bulkEventTarget.min_order_quantity }],
                    });
                    setBulkEventTarget(null);
                    pushToast(`Bulk order ${res.data.bulk_order_number} submitted!`, "success");
                    await refetchMyBulkOrders();
                    await launchBulkOrderPayment(res.data);
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Submit Bulk Order &amp; Pay
              </Button>
            </div>
          </div>
        )}
      </Modal>

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
