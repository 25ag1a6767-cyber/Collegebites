import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Megaphone, Monitor, Shield, Tag } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import type { CollegeSettings } from "../../../types";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

export const PromotionsTab: React.FC<{ activeCanteenId: string }> = ({ activeCanteenId }) => {
  const { pushToast } = useToast();
  const { data: coupons = [], refetch: refetchCoupons } = useQuery<any[]>({
    queryKey: ["admin-coupons"],
    queryFn: async () => (await api.get("/promotions/coupons?active_only=false")).data,
  });
  const { data: announcements = [], refetch: refetchAnn } = useQuery<any[]>({
    queryKey: ["admin-announcements"],
    queryFn: async () => (await api.get("/notifications/announcements")).data,
  });

  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [discType, setDiscType] = useState<"percentage" | "fixed">("percentage");
  const [discVal, setDiscVal] = useState("10");
  const [minOrder, setMinOrder] = useState("100");
  const [annTitle, setAnnTitle] = useState("");
  const [annBody, setAnnBody] = useState("");

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Card className="p-5 space-y-3">
        <h2 className="font-bold text-slate-900 flex items-center gap-2">
          <Tag className="h-4 w-4 text-orange-600" /> Coupons & Offers ({coupons.length})
        </h2>
        <div className="grid grid-cols-2 gap-2">
          <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Code (FEST20)" />
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Select value={discType} onChange={(e) => setDiscType(e.target.value as any)}>
            <option value="percentage">% Off</option>
            <option value="fixed">Flat ₹</option>
          </Select>
          <Input value={discVal} onChange={(e) => setDiscVal(e.target.value)} placeholder="Value" />
          <Input value={minOrder} onChange={(e) => setMinOrder(e.target.value)} placeholder="Min ₹" />
        </div>
        <Button
          size="sm"
          onClick={async () => {
            try {
              await api.post("/promotions/coupons", {
                code,
                title,
                discount_type: discType,
                discount_value: discVal,
                min_order_amount: minOrder,
              });
              setCode("");
              setTitle("");
              refetchCoupons();
              pushToast("Coupon created", "success");
            } catch (err) {
              pushToast(getApiError(err), "error");
            }
          }}
        >
          Create Coupon
        </Button>
        <div className="space-y-1.5 pt-2 border-t border-slate-100 text-xs">
          {coupons.map((c) => (
            <div key={c.id} className="flex items-center justify-between gap-2">
              <span className="font-mono font-bold">
                {c.code} {!c.is_active && <span className="text-red-500">(Paused)</span>}
              </span>
              <div className="flex items-center gap-2">
                <span>
                  {c.discount_value} ({c.discount_type}) • Used {c.times_used}×
                </span>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await api.patch(`/promotions/coupons/${c.id}`, { is_active: !c.is_active });
                      refetchCoupons();
                      pushToast(`Coupon ${!c.is_active ? "activated" : "paused"}`, "info");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                  className="font-bold text-orange-600 hover:underline"
                >
                  {c.is_active ? "Pause" : "Activate"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card className="p-5 space-y-3">
        <h2 className="font-bold text-slate-900 flex items-center gap-2">
          <Megaphone className="h-4 w-4 text-amber-600" /> Campus Announcements ({announcements.length})
        </h2>
        <Input value={annTitle} onChange={(e) => setAnnTitle(e.target.value)} placeholder="Announcement title" />
        <Input value={annBody} onChange={(e) => setAnnBody(e.target.value)} placeholder="Announcement message..." />
        <Button
          size="sm"
          onClick={async () => {
            try {
              await api.post("/notifications/announcements", {
                canteen_id: activeCanteenId || null,
                title: annTitle,
                body: annBody,
                severity: "info",
              });
              setAnnTitle("");
              setAnnBody("");
              refetchAnn();
              pushToast("Announcement published", "success");
            } catch (err) {
              pushToast(getApiError(err), "error");
            }
          }}
        >
          Publish Announcement
        </Button>
        <div className="space-y-1.5 pt-2 border-t border-slate-100 text-xs">
          {announcements.map((a) => (
            <div key={a.id} className="flex items-start justify-between gap-2 rounded-lg bg-amber-50 p-2">
              <div>
                <div className="font-bold">{a.title}</div>
                <div className="text-slate-600">{a.body}</div>
              </div>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await api.delete(`/notifications/announcements/${a.id}`);
                    refetchAnn();
                    pushToast("Announcement removed", "info");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
                className="text-red-600 font-bold hover:underline shrink-0"
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};

export const SystemTab: React.FC<{
  college?: CollegeSettings;
  refetchCollege: () => void;
  health: any;
  auditLogs: any[];
}> = ({ college, refetchCollege, health, auditLogs }) => {
  const { pushToast } = useToast();
  const { data: payments = [], refetch: refetchPayments } = useQuery<any[]>({
    queryKey: ["admin-payments"],
    queryFn: async () => (await api.get("/payments?limit=20")).data,
  });
  const { data: kioskStatus, refetch: refetchKiosk } = useQuery<any>({
    queryKey: ["admin-kiosk-status"],
    queryFn: async () => (await api.get("/kiosk/status")).data,
  });
  const { data: sysEvents = [] } = useQuery<any[]>({
    queryKey: ["admin-system-events"],
    queryFn: async () => (await api.get("/admin/system-events")).data,
  });

  const [collegeName, setCollegeName] = useState(college?.college_name || "");
  const [policyText, setPolicyText] = useState(college?.cancellation_policy_text || "");
  const [timezone, setTimezone] = useState(college?.college_timezone || "Asia/Kolkata");

  useEffect(() => {
    if (college) {
      setCollegeName(college.college_name || "");
      setPolicyText(college.cancellation_policy_text || "");
      setTimezone(college.college_timezone || "Asia/Kolkata");
    }
  }, [college]);

  const toggleSetting = async (field: keyof CollegeSettings, val: boolean, label: string) => {
    try {
      await api.put("/admin/college", { [field]: val });
      refetchCollege();
      pushToast(`${label} ${val ? "enabled" : "disabled"}`, "info");
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-4">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <Shield className="h-4 w-4 text-emerald-600" /> College Settings & Hardware
          </h2>
          {health && (
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-xl bg-slate-50 p-3">Database: <strong>{health.database}</strong></div>
              <div className="rounded-xl bg-slate-50 p-3">Redis: <strong>{health.redis}</strong></div>
              <div className="rounded-xl bg-slate-50 p-3">Orders: <strong>{health.total_orders}</strong></div>
              <div className="rounded-xl bg-slate-50 p-3">Payments: <strong>{health.total_payments}</strong></div>
            </div>
          )}
          {college && (
            <div className="space-y-3 border-t border-slate-100 pt-3 text-xs">
              <div className="grid grid-cols-2 gap-2">
                <Input value={collegeName} onChange={(e) => setCollegeName(e.target.value)} placeholder="College Name" />
                <Input value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="Timezone (Asia/Kolkata)" />
              </div>
              <textarea
                rows={3}
                value={policyText}
                onChange={(e) => setPolicyText(e.target.value)}
                className="w-full rounded-xl border border-slate-300 p-2.5 text-xs"
              />
              <div className="grid grid-cols-2 gap-2">
                <label className="flex items-center gap-1.5 font-semibold cursor-pointer">
                  <input
                    type="checkbox"
                    checked={Boolean(college.razorpay_enabled)}
                    onChange={() => void toggleSetting("razorpay_enabled", !college.razorpay_enabled, "Razorpay")}
                  />
                  Razorpay Enabled
                </label>
                <label className="flex items-center gap-1.5 font-semibold cursor-pointer">
                  <input
                    type="checkbox"
                    checked={Boolean(college.stripe_enabled ?? true)}
                    onChange={() => void toggleSetting("stripe_enabled", !(college.stripe_enabled ?? true), "Stripe")}
                  />
                  Stripe Enabled
                </label>
                <label className="flex items-center gap-1.5 font-semibold cursor-pointer">
                  <input
                    type="checkbox"
                    checked={Boolean(college.cash_at_counter_enabled)}
                    onChange={() => void toggleSetting("cash_at_counter_enabled", !college.cash_at_counter_enabled, "Cash at Counter")}
                  />
                  Cash at Counter
                </label>
                <label className="flex items-center gap-1.5 font-semibold cursor-pointer">
                  <input
                    type="checkbox"
                    checked={Boolean(college.pay_at_pickup_enabled)}
                    onChange={() => void toggleSetting("pay_at_pickup_enabled", !college.pay_at_pickup_enabled, "Pay at Pickup")}
                  />
                  Pay at Pickup
                </label>
                <label className="flex items-center gap-1.5 font-semibold cursor-pointer">
                  <input
                    type="checkbox"
                    checked={Boolean(college.guest_otp_required)}
                    onChange={() => void toggleSetting("guest_otp_required", !college.guest_otp_required, "Guest OTP")}
                  />
                  Guest OTP Required
                </label>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={async () => {
                    try {
                      await api.put("/admin/college", {
                        college_name: collegeName || college.college_name,
                        cancellation_policy_text: policyText || college.cancellation_policy_text,
                        college_timezone: timezone || "Asia/Kolkata",
                      });
                      refetchCollege();
                      pushToast("College settings saved", "success");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  Save Settings
                </Button>
                <Button
                  size="sm"
                  variant={college.kiosk_enabled ? "success" : "outline"}
                  onClick={() => void toggleSetting("kiosk_enabled", !college.kiosk_enabled, "Kiosk Mode")}
                >
                  Kiosk: {college.kiosk_enabled ? "Enabled" : "Disabled"}
                </Button>
              </div>

              {kioskStatus?.devices?.length > 0 && (
                <div className="border-t border-slate-100 pt-2 space-y-1.5">
                  <div className="font-bold text-slate-700 flex items-center gap-1.5">
                    <Monitor className="h-3.5 w-3.5" /> Registered Kiosk Terminals
                  </div>
                  {kioskStatus.devices.map((dev: any) => (
                    <div key={dev.id} className="flex items-center justify-between rounded-lg border border-slate-200 px-2.5 py-1.5">
                      <span>
                        <strong>{dev.name}</strong> ({dev.device_code})
                      </span>
                      <Button
                        size="sm"
                        variant={dev.is_enabled ? "success" : "outline"}
                        onClick={async () => {
                          try {
                            await api.patch(`/kiosk/devices/${dev.id}`, { is_enabled: !dev.is_enabled });
                            refetchKiosk();
                            pushToast(`Device ${dev.device_code} ${!dev.is_enabled ? "enabled" : "disabled"}`, "info");
                          } catch (err) {
                            pushToast(getApiError(err), "error");
                          }
                        }}
                      >
                        {dev.is_enabled ? "Device On" : "Device Off"}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>

        <Card className="p-5 space-y-2 max-h-96 overflow-y-auto">
          <h2 className="font-bold text-slate-900">Recent Audit Logs & System Events</h2>
          {auditLogs.map((a) => (
            <div key={a.id} className="border-b border-slate-100 py-1.5 text-xs flex justify-between gap-2">
              <span className="font-mono font-semibold text-slate-800">{a.action}</span>
              <span className="text-slate-500">
                {a.entity_type}:{a.entity_id}
              </span>
            </div>
          ))}
          {sysEvents.slice(0, 10).map((ev) => (
            <div key={ev.id} className="border-b border-slate-100 py-1.5 text-xs flex justify-between gap-2">
              <span className="font-semibold text-amber-700">{ev.event_type}</span>
              <span className="text-slate-500 truncate">{ev.message}</span>
            </div>
          ))}
        </Card>
      </div>

      <Card className="p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-bold text-slate-900">Recent Payments & Reconciliation (No Refunds)</h2>
          <div className="flex flex-wrap gap-1.5 text-xs">
            <Badge tone="green">Razorpay Active (UPI / Cards / Netbanking)</Badge>
            <Badge tone="blue">Stripe Active (Cards / Apple Pay / Google Pay)</Badge>
          </div>
        </div>
        <div className="space-y-2 text-xs">
          {payments.map((p) => (
            <div key={p.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 py-2">
              <div>
                <span className="font-bold">₹{p.amount}</span> • {p.provider} ({p.method}) • Ref:{" "}
                <span className="font-mono">{p.payment_reference || p.provider_order_id || "Pending"}</span>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={p.status === "CONFIRMED" ? "green" : p.status === "FAILED" ? "red" : "amber"}>{p.status}</Badge>
                {p.status === "CONFIRMED" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      try {
                        await api.post("/payments/reconcile", { payment_id: p.id, settled_amount: p.amount, notes: "Matched" });
                        pushToast("Payment reconciled", "success");
                        refetchPayments();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Reconcile
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};
