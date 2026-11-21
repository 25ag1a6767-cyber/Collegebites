import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Megaphone, Shield, Tag } from "lucide-react";
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
            <div key={c.id} className="flex justify-between">
              <span className="font-mono font-bold">{c.code}</span>
              <span>
                {c.discount_value} ({c.discount_type}) • Used {c.times_used}×
              </span>
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
            <div key={a.id} className="rounded-lg bg-amber-50 p-2">
              <div className="font-bold">{a.title}</div>
              <div className="text-slate-600">{a.body}</div>
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

  const [collegeName, setCollegeName] = useState(college?.college_name || "");
  const [policyText, setPolicyText] = useState(college?.cancellation_policy_text || "");

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
              <Input value={collegeName} onChange={(e) => setCollegeName(e.target.value)} placeholder="College Name" />
              <textarea
                rows={3}
                value={policyText}
                onChange={(e) => setPolicyText(e.target.value)}
                className="w-full rounded-xl border border-slate-300 p-2.5 text-xs"
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={async () => {
                    await api.put("/admin/college", {
                      college_name: collegeName || college.college_name,
                      cancellation_policy_text: policyText || college.cancellation_policy_text,
                    });
                    refetchCollege();
                    pushToast("College settings saved", "success");
                  }}
                >
                  Save Settings
                </Button>
                <Button
                  size="sm"
                  variant={college.kiosk_enabled ? "success" : "outline"}
                  onClick={async () => {
                    await api.put("/admin/college", { kiosk_enabled: !college.kiosk_enabled });
                    refetchCollege();
                    pushToast(`Kiosk mode ${!college.kiosk_enabled ? "enabled" : "disabled"}`, "info");
                  }}
                >
                  Kiosk: {college.kiosk_enabled ? "Enabled" : "Disabled"}
                </Button>
              </div>
            </div>
          )}
        </Card>

        <Card className="p-5 space-y-2 max-h-96 overflow-y-auto">
          <h2 className="font-bold text-slate-900">Recent Audit Logs</h2>
          {auditLogs.map((a) => (
            <div key={a.id} className="border-b border-slate-100 py-1.5 text-xs flex justify-between gap-2">
              <span className="font-mono font-semibold text-slate-800">{a.action}</span>
              <span className="text-slate-500">
                {a.entity_type}:{a.entity_id}
              </span>
            </div>
          ))}
        </Card>
      </div>

      <Card className="p-5 space-y-3">
        <h2 className="font-bold text-slate-900">Recent Payments & Reconciliation (No Refunds)</h2>
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
                      await api.post("/payments/reconcile", { payment_id: p.id, settled_amount: p.amount, notes: "Matched" });
                      pushToast("Payment reconciled", "success");
                      refetchPayments();
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
