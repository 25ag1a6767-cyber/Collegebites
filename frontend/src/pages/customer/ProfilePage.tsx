import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Award, Bell, Check, Gift, Heart } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { FoodItem } from "../../types";
import { Badge, Button, Card, Input, useToast } from "../../components/ui/Primitives";

export const ProfilePage: React.FC = () => {
  const { user, setSelectedCanteen } = useAppStore();
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

  const [fullName, setFullName] = useState("");
  const [collegeId, setCollegeId] = useState("");
  const [department, setDepartment] = useState("");
  const [referralInput, setReferralInput] = useState("");

  useEffect(() => {
    if (profile) {
      setFullName(profile.full_name || "");
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
    try {
      await api.patch("/customers/profile", {
        full_name: fullName,
        college_id_number: collegeId,
        department,
      });
      qc.invalidateQueries({ queryKey: ["customer-profile"] });
      pushToast("Profile updated", "success");
    } catch (err) {
      pushToast(getApiError(err), "error");
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
    await api.put("/notifications/preferences", { [key]: !currentVal });
    qc.invalidateQueries({ queryKey: ["notif-prefs"] });
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
      <h1 className="text-2xl font-extrabold text-slate-900">Account, Loyalty & Notifications</h1>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-5 space-y-4">
          <h2 className="font-bold text-slate-900">Universal Profile</h2>
          <form onSubmit={saveProfile} className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-bold text-slate-600">Full Name</label>
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
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
            <Button type="submit" size="sm">
              Save Profile
            </Button>
          </form>
        </Card>

        <Card className="p-5 space-y-4 bg-gradient-to-br from-orange-50 to-amber-50 border-orange-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-orange-950">
              <Award className="h-5 w-5 text-orange-600" /> Campus Loyalty Rewards
            </div>
            <Badge tone="default">{loyalty?.tier_level || "BRONZE"}</Badge>
          </div>
          <div className="text-3xl font-black text-orange-700">{loyalty?.points_balance || 0} pts</div>
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
          <div className="flex items-center gap-2 font-bold text-slate-900">
            <Bell className="h-4 w-4 text-orange-600" /> Recent Notifications ({notifications.length})
          </div>
          <div className="space-y-2 max-h-72 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="text-xs text-slate-500">No notifications yet.</div>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  className={`flex items-start justify-between rounded-xl border p-3 text-xs ${
                    n.is_read ? "border-slate-100 bg-white" : "border-orange-200 bg-orange-50/50"
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
                        await api.post(`/notifications/${n.id}/read`);
                        refetchNotifs();
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
                    className="rounded-lg bg-orange-600 px-2.5 py-1 font-bold text-white"
                  >
                    Order
                  </Link>
                  <button
                    type="button"
                    onClick={async () => {
                      await api.delete(`/customers/favourites/${item.id}`);
                      refetchFavs();
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
    </div>
  );
};
