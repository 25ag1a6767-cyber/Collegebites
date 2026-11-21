import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Download, LayoutDashboard } from "lucide-react";
import { api } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, CollegeSettings, FoodItem } from "../../types";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";
import { LocationsTab } from "./components/LocationsTab";
import { MenuTab, QRTab } from "./components/MenuQrTab";
import { QueueTab, StaffTab } from "./components/QueueStaffTab";
import { PromotionsTab, SystemTab } from "./components/PromotionsSystemTab";

export const AdminConsolePage: React.FC = () => {
  const { pushToast } = useToast();
  const { user, selectedCanteenId } = useAppStore();
  const [tab, setTab] = useState<
    "analytics" | "locations" | "menu" | "qr" | "queue" | "staff" | "promotions" | "support" | "system"
  >("analytics");

  const { data: college, refetch: refetchCollege } = useQuery<CollegeSettings>({
    queryKey: ["college-settings"],
    queryFn: async () => (await api.get("/canteens/college")).data,
  });

  const { data: canteens = [], refetch: refetchCanteens } = useQuery<Canteen[]>({
    queryKey: ["canteens-all"],
    queryFn: async () => (await api.get("/canteens?include_inactive=true")).data,
  });

  const [canteenId, setCanteenId] = useState(user?.assigned_canteen_id || selectedCanteenId || "");
  const activeCanteenId = canteenId || canteens[0]?.id || "";

  const { data: report } = useQuery<any>({
    queryKey: ["admin-report", activeCanteenId],
    enabled: tab === "analytics",
    queryFn: async () => (await api.get("/reports/dashboard")).data,
  });

  const { data: menuItems = [], refetch: refetchMenu } = useQuery<FoodItem[]>({
    queryKey: ["admin-menu", activeCanteenId],
    enabled: Boolean(activeCanteenId && tab === "menu"),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/items?include_inactive=true`)).data,
  });

  const { data: categories = [], refetch: refetchCategories } = useQuery<any[]>({
    queryKey: ["admin-cats", activeCanteenId],
    enabled: Boolean(activeCanteenId && tab === "menu"),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/categories?include_inactive=true`)).data,
  });

  const { data: locationQrs = [], refetch: refetchQrs } = useQuery<any[]>({
    queryKey: ["admin-qrs", activeCanteenId],
    enabled: Boolean(activeCanteenId && tab === "qr"),
    queryFn: async () => (await api.get(`/qr/locations?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: queueDash, refetch: refetchQueue } = useQuery<any>({
    queryKey: ["admin-queue", activeCanteenId],
    enabled: Boolean(activeCanteenId && tab === "queue"),
    queryFn: async () => (await api.get(`/queue/canteens/${activeCanteenId}`)).data,
  });

  const { data: staffList = [], refetch: refetchStaff } = useQuery<any[]>({
    queryKey: ["admin-staff"],
    enabled: tab === "staff" || tab === "support",
    queryFn: async () => (await api.get("/staff")).data,
  });

  const { data: tickets = [], refetch: refetchTickets } = useQuery<any[]>({
    queryKey: ["admin-tickets"],
    enabled: tab === "support",
    queryFn: async () => (await api.get("/support/tickets")).data,
  });

  const { data: auditLogs = [] } = useQuery<any[]>({
    queryKey: ["admin-audits"],
    enabled: tab === "system",
    queryFn: async () => (await api.get("/admin/audit-logs?limit=40")).data,
  });

  const { data: health } = useQuery<any>({
    queryKey: ["admin-health"],
    enabled: tab === "system",
    queryFn: async () => (await api.get("/admin/health")).data,
  });

  const [replyByTicket, setReplyByTicket] = useState<Record<string, string>>({});

  const downloadBlob = async (url: string, filename: string) => {
    const res = await api.get(url, { responseType: "blob" });
    const objUrl = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = objUrl;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(objUrl);
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-slate-900 p-4 text-white">
        <div className="flex items-center gap-3">
          <LayoutDashboard className="h-7 w-7 text-orange-400" />
          <div>
            <h1 className="text-xl font-extrabold">CollegeBites Operations & Admin Console</h1>
            <p className="text-xs text-slate-400">{college?.college_name} • Real-time database analytics & controls</p>
          </div>
        </div>
        <Select
          value={activeCanteenId}
          onChange={(e) => setCanteenId(e.target.value)}
          className="w-56 bg-slate-800 border-slate-700 text-white"
        >
          {canteens.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex flex-wrap gap-2">
        {[
          { k: "analytics", l: "Analytics & Reports" },
          { k: "locations", l: "Locations, Counters & Hours" },
          { k: "menu", l: "Menus & CSV" },
          { k: "qr", l: "Location QR Codes" },
          { k: "queue", l: "Queue, Crowd & Slots" },
          { k: "staff", l: "Staff, Attendance & Tasks" },
          { k: "promotions", l: "Coupons & Announcements" },
          { k: "support", l: "Support Tickets" },
          { k: "system", l: "Settings, Reconcile & Audits" },
        ].map((item) => (
          <Button
            key={item.k}
            size="sm"
            variant={tab === item.k ? "secondary" : "outline"}
            onClick={() => setTab(item.k as any)}
          >
            {item.l}
          </Button>
        ))}
      </div>

      {tab === "analytics" && report && (
        <div className="space-y-5">
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => downloadBlob("/reports/export/csv", "collegebites-report.csv")}>
              <Download className="h-3.5 w-3.5" /> Export CSV
            </Button>
            <Button size="sm" variant="primary" onClick={() => downloadBlob("/reports/export/pdf", "collegebites-report.pdf")}>
              <Download className="h-3.5 w-3.5" /> Export PDF
            </Button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="p-4">
              <div className="text-xs text-slate-500">Confirmed Orders</div>
              <div className="text-2xl font-black text-slate-900">{report.sales.total_orders}</div>
              <div className="text-xs text-emerald-700 mt-1">Completed: {report.operations.completed_orders}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-slate-500">Net Sales Revenue</div>
              <div className="text-2xl font-black text-orange-600">₹{report.sales.net_sales}</div>
              <div className="text-xs text-slate-500 mt-1">AOV: ₹{report.sales.average_order_value}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-slate-500">Avg Prep Time</div>
              <div className="text-2xl font-black text-slate-900">{report.operations.avg_prep_minutes} min</div>
              <div className="text-xs text-slate-500 mt-1">Delayed: {report.operations.delayed_orders}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-slate-500">Repeat Customer Rate</div>
              <div className="text-2xl font-black text-slate-900">{report.customers.repeat_order_rate_percent}%</div>
              <div className="text-xs text-slate-500 mt-1">Avg Rating: ★ {report.customers.average_food_rating}</div>
            </Card>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card className="p-5">
              <h3 className="font-bold text-slate-900 mb-3 text-sm">Daily Revenue Trend (₹)</h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={report.sales.daily_series}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="revenue" fill="#ea580c" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <Card className="p-5">
              <h3 className="font-bold text-slate-900 mb-3 text-sm">Top Selling Dishes</h3>
              <div className="space-y-2 text-xs">
                {report.sales.top_items.map((ti: any) => (
                  <div key={ti.item_name} className="flex items-center justify-between border-b border-slate-100 pb-2">
                    <span className="font-bold text-slate-800">{ti.item_name}</span>
                    <span>
                      {ti.quantity_sold} sold • <strong>₹{ti.revenue.toFixed(2)}</strong>
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      )}

      {tab === "locations" && (
        <LocationsTab canteens={canteens} activeCanteenId={activeCanteenId} refetchCanteens={refetchCanteens} />
      )}

      {tab === "menu" && (
        <MenuTab
          activeCanteenId={activeCanteenId}
          menuItems={menuItems}
          categories={categories}
          refetchMenu={refetchMenu}
          refetchCategories={refetchCategories}
          downloadBlob={downloadBlob}
        />
      )}

      {tab === "qr" && <QRTab activeCanteenId={activeCanteenId} locationQrs={locationQrs} refetchQrs={refetchQrs} />}

      {tab === "queue" && <QueueTab activeCanteenId={activeCanteenId} queueDash={queueDash} refetchQueue={refetchQueue} />}

      {tab === "staff" && <StaffTab activeCanteenId={activeCanteenId} staffList={staffList} refetchStaff={refetchStaff} />}

      {tab === "promotions" && <PromotionsTab activeCanteenId={activeCanteenId} />}

      {tab === "support" && (
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900">Customer Support Tickets ({tickets.length})</h2>
          {tickets.map((t) => (
            <div key={t.id} className="rounded-xl border border-slate-200 p-4 text-xs space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-bold text-sm">
                    {t.ticket_number} — {t.subject}
                  </div>
                  <div className="text-slate-500">
                    {t.category} • {t.description}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={t.status === "resolved" ? "green" : "amber"}>{t.status}</Badge>
                  <Select
                    value={t.assigned_to_user_id || ""}
                    onChange={async (e) => {
                      if (!e.target.value) return;
                      await api.post(`/support/tickets/${t.id}/assign`, { assigned_to_user_id: e.target.value });
                      pushToast("Ticket assigned", "success");
                      refetchTickets();
                    }}
                    className="w-40"
                  >
                    <option value="">Assign Staff...</option>
                    {staffList.map((s) => (
                      <option key={s.user_id} value={s.user_id}>
                        {s.full_name}
                      </option>
                    ))}
                  </Select>
                  {t.status !== "resolved" && (
                    <Button
                      size="sm"
                      variant="success"
                      onClick={async () => {
                        await api.post(`/support/tickets/${t.id}/resolve?resolution_note=Resolved%20by%20admin`);
                        refetchTickets();
                      }}
                    >
                      Resolve
                    </Button>
                  )}
                </div>
              </div>
              <div className="flex gap-2">
                <Input
                  value={replyByTicket[t.id] || ""}
                  onChange={(e) => setReplyByTicket((p) => ({ ...p, [t.id]: e.target.value }))}
                  placeholder="Write response to customer..."
                />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    const msg = replyByTicket[t.id];
                    if (!msg?.trim()) return;
                    await api.post(`/support/tickets/${t.id}/messages`, { message: msg });
                    setReplyByTicket((p) => ({ ...p, [t.id]: "" }));
                    pushToast("Reply sent", "success");
                    refetchTickets();
                  }}
                >
                  Send Reply
                </Button>
              </div>
            </div>
          ))}
        </Card>
      )}

      {tab === "system" && (
        <SystemTab college={college} refetchCollege={refetchCollege} health={health} auditLogs={auditLogs} />
      )}
    </div>
  );
};
