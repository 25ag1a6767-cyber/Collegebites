import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Download, LayoutDashboard, QrCode, RefreshCw, Shield, Users } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, CollegeSettings, FoodItem } from "../../types";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";

export const AdminConsolePage: React.FC = () => {
  const { pushToast } = useToast();
  const { user, selectedCanteenId } = useAppStore();
  const [tab, setTab] = useState<
    "analytics" | "locations" | "menu" | "qr" | "queue" | "staff" | "support" | "system"
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
  const activeCanteen = canteens.find((c) => c.id === activeCanteenId);

  const { data: report } = useQuery<any>({
    queryKey: ["admin-report", activeCanteenId],
    enabled: tab === "analytics",
    queryFn: async () => (await api.get(`/reports/dashboard`)).data,
  });

  const { data: menuItems = [], refetch: refetchMenu } = useQuery<FoodItem[]>({
    queryKey: ["admin-menu", activeCanteenId],
    enabled: Boolean(activeCanteenId && tab === "menu"),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/items?include_inactive=true`)).data,
  });

  const { data: categories = [] } = useQuery<any[]>({
    queryKey: ["admin-cats", activeCanteenId],
    enabled: Boolean(activeCanteenId && tab === "menu"),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/categories?include_inactive=true`)).data,
  });

  const { data: locationQrs = [], refetch: refetchQrs } = useQuery<any[]>({
    queryKey: ["admin-qrs", activeCanteenId],
    enabled: tab === "qr",
    queryFn: async () => (await api.get(`/qr/locations?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: queueDash, refetch: refetchQueue } = useQuery<any>({
    queryKey: ["admin-queue", activeCanteenId],
    enabled: Boolean(activeCanteenId && tab === "queue"),
    queryFn: async () => (await api.get(`/queue/canteens/${activeCanteenId}`)).data,
  });

  const { data: staffList = [], refetch: refetchStaff } = useQuery<any[]>({
    queryKey: ["admin-staff"],
    enabled: tab === "staff",
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

  // Form states
  const [newCanteenName, setNewCanteenName] = useState("");
  const [newCanteenSlug, setNewCanteenSlug] = useState("");
  const [newCanteenCode, setNewCanteenCode] = useState("");
  const [newCanteenLoc, setNewCanteenLoc] = useState("");
  const [newDishName, setNewDishName] = useState("");
  const [newDishPrice, setNewDishPrice] = useState("60.00");
  const [newDishCatId, setNewDishCatId] = useState("");
  const [qrLabel, setQrLabel] = useState("Table T-05 QR");
  const [qrType, setQrType] = useState<"canteen" | "counter" | "table" | "kiosk">("table");
  const [newStaffName, setNewStaffName] = useState("");
  const [newStaffEmail, setNewStaffEmail] = useState("");
  const [newStaffEmp, setNewStaffEmp] = useState("");
  const [newStaffRole, setNewStaffRole] = useState("cashier");

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
          { k: "locations", l: "Canteens & Locations" },
          { k: "menu", l: "Menus & CSV" },
          { k: "qr", l: "Location QR Codes" },
          { k: "queue", l: "Queue & Crowd" },
          { k: "staff", l: "Staff & Roles" },
          { k: "support", l: "Support Tickets" },
          { k: "system", l: "Kiosk, Health & Audits" },
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
        <div className="grid gap-6 md:grid-cols-2">
          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900">Campus Canteens & Counters</h2>
            {canteens.map((c) => (
              <div key={c.id} className="flex items-center justify-between rounded-xl border border-slate-200 p-3 text-xs">
                <div>
                  <div className="font-bold text-sm">{c.name} ({c.code})</div>
                  <div className="text-slate-500">{c.location} • Token Prefix: {c.token_prefix}</div>
                </div>
                <Button
                  size="sm"
                  variant={c.is_temporarily_closed ? "danger" : "outline"}
                  onClick={async () => {
                    await api.patch(`/admin/canteens/${c.id}`, {
                      is_temporarily_closed: !c.is_temporarily_closed,
                    });
                    refetchCanteens();
                  }}
                >
                  {c.is_temporarily_closed ? "Reopen" : "Temp Close"}
                </Button>
              </div>
            ))}
          </Card>

          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900">Create New Campus Location</h2>
            <Input value={newCanteenName} onChange={(e) => setNewCanteenName(e.target.value)} placeholder="Name (e.g. MBA Block Cafe)" />
            <div className="grid grid-cols-2 gap-2">
              <Input value={newCanteenSlug} onChange={(e) => setNewCanteenSlug(e.target.value)} placeholder="slug (mba-cafe)" />
              <Input value={newCanteenCode} onChange={(e) => setNewCanteenCode(e.target.value)} placeholder="code (MBA)" />
            </div>
            <Input value={newCanteenLoc} onChange={(e) => setNewCanteenLoc(e.target.value)} placeholder="Building / Floor" />
            <Button
              onClick={async () => {
                try {
                  await api.post("/admin/canteens", {
                    name: newCanteenName,
                    slug: newCanteenSlug,
                    code: newCanteenCode,
                    location: newCanteenLoc,
                    token_prefix: newCanteenCode.slice(0, 1).toUpperCase() || "M",
                  });
                  setNewCanteenName("");
                  setNewCanteenSlug("");
                  setNewCanteenCode("");
                  setNewCanteenLoc("");
                  pushToast("Canteen location created!", "success");
                  refetchCanteens();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Canteen Location
            </Button>
          </Card>
        </div>
      )}

      {tab === "menu" && (
        <div className="space-y-4">
          <Card className="p-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-2 items-center">
              <Input value={newDishName} onChange={(e) => setNewDishName(e.target.value)} placeholder="New Dish Name" className="w-48" />
              <Input value={newDishPrice} onChange={(e) => setNewDishPrice(e.target.value)} placeholder="Price" className="w-24" />
              <Select value={newDishCatId} onChange={(e) => setNewDishCatId(e.target.value)} className="w-44">
                <option value="">Select Category</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
              <Button
                size="sm"
                onClick={async () => {
                  try {
                    const slug = newDishName.toLowerCase().replace(/[^a-z0-9]+/g, "-");
                    await api.post("/menus/items", {
                      canteen_id: activeCanteenId,
                      category_id: newDishCatId || categories[0]?.id,
                      name: newDishName,
                      slug,
                      base_price: newDishPrice,
                    });
                    setNewDishName("");
                    refetchMenu();
                    pushToast("Dish added", "success");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Add Item
              </Button>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => downloadBlob(`/menus/canteens/${activeCanteenId}/export-csv`, "menu.csv")}
            >
              <Download className="h-3.5 w-3.5" /> Export Menu CSV
            </Button>
          </Card>

          <Card className="p-4 space-y-2">
            {menuItems.map((it) => (
              <div key={it.id} className="flex items-center justify-between border-b border-slate-100 py-2 text-xs">
                <div>
                  <span className="font-bold text-slate-900">{it.name}</span> • ₹{it.base_price} • {it.category_name}
                </div>
                <Button
                  size="sm"
                  variant={it.is_available ? "success" : "danger"}
                  onClick={async () => {
                    await api.patch(`/menus/items/${it.id}`, { is_available: !it.is_available });
                    refetchMenu();
                  }}
                >
                  {it.is_available ? "Available" : "Disabled"}
                </Button>
              </div>
            ))}
          </Card>
        </div>
      )}

      {tab === "qr" && (
        <div className="space-y-4">
          <Card className="p-4 flex flex-wrap items-center gap-3">
            <Select value={qrType} onChange={(e) => setQrType(e.target.value as any)} className="w-40">
              <option value="canteen">Canteen QR</option>
              <option value="counter">Counter QR</option>
              <option value="table">Table QR</option>
              <option value="kiosk">Kiosk QR</option>
            </Select>
            <Input value={qrLabel} onChange={(e) => setQrLabel(e.target.value)} placeholder="QR Label" className="w-60" />
            <Button
              size="sm"
              onClick={async () => {
                await api.post("/qr/locations", {
                  target_type: qrType,
                  canteen_id: activeCanteenId,
                  label: qrLabel,
                });
                pushToast("Permanent location QR generated", "success");
                refetchQrs();
              }}
            >
              <QrCode className="h-3.5 w-3.5" /> Generate Location QR
            </Button>
          </Card>

          <div className="grid gap-3 md:grid-cols-2">
            {locationQrs.map((q) => (
              <Card key={q.id} className="p-4 flex items-center justify-between gap-3 text-xs">
                <div>
                  <div className="font-bold text-sm">{q.label}</div>
                  <div className="font-mono text-slate-600">{q.code}</div>
                  <Badge tone={q.is_active ? "green" : "red"} className="mt-1">
                    {q.is_active ? "Active" : "Revoked"}
                  </Badge>
                </div>
                {q.is_active && (
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        await api.post(`/qr/locations/${q.id}/replace`);
                        refetchQrs();
                      }}
                    >
                      <RefreshCw className="h-3.5 w-3.5" /> Replace
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={async () => {
                        await api.post(`/qr/locations/${q.id}/revoke`);
                        refetchQrs();
                      }}
                    >
                      Revoke
                    </Button>
                  </div>
                )}
              </Card>
            ))}
          </div>
        </div>
      )}

      {tab === "queue" && queueDash && (
        <Card className="p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-bold text-slate-900">Live Queue & Crowd Control</h2>
              <div className="text-xs text-slate-500">
                Active: {queueDash.active_order_count} • Crowd: {queueDash.crowd_level} • Est Wait: {queueDash.estimated_wait_minutes} min • Kitchen Workload: {queueDash.kitchen_workload_percent}%
              </div>
            </div>
            <Button
              variant={queueDash.ordering_paused ? "success" : "danger"}
              onClick={async () => {
                await api.patch(`/queue/canteens/${activeCanteenId}/controls`, {
                  ordering_paused: !queueDash.ordering_paused,
                  pause_reason: !queueDash.ordering_paused ? "Paused by manager due to peak crowd" : null,
                });
                refetchQueue();
              }}
            >
              {queueDash.ordering_paused ? "Resume Ordering" : "Pause Ordering Temporarily"}
            </Button>
          </div>
        </Card>
      )}

      {tab === "staff" && (
        <div className="grid gap-5 md:grid-cols-2">
          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900 flex items-center gap-2">
              <Users className="h-4 w-4 text-orange-600" /> Staff Directory ({staffList.length})
            </h2>
            {staffList.map((s) => (
              <div key={s.user_id} className="flex justify-between rounded-xl border border-slate-200 p-3 text-xs">
                <div>
                  <div className="font-bold text-slate-900">{s.full_name} ({s.employee_code})</div>
                  <div className="text-slate-500">{s.designation} • {s.email}</div>
                </div>
                <Badge tone={s.is_on_duty ? "green" : "slate"}>{s.is_on_duty ? "On Duty" : "Off Duty"}</Badge>
              </div>
            ))}
          </Card>

          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900">Create Staff Member</h2>
            <Input value={newStaffName} onChange={(e) => setNewStaffName(e.target.value)} placeholder="Full Name" />
            <Input value={newStaffEmail} onChange={(e) => setNewStaffEmail(e.target.value)} placeholder="Email" />
            <Input value={newStaffEmp} onChange={(e) => setNewStaffEmp(e.target.value)} placeholder="Employee Code (EMP-201)" />
            <Select value={newStaffRole} onChange={(e) => setNewStaffRole(e.target.value)}>
              <option value="cashier">Cashier</option>
              <option value="kitchen_staff">Kitchen Staff</option>
              <option value="pickup_staff">Pickup Staff</option>
              <option value="inventory_manager">Inventory Manager</option>
              <option value="canteen_manager">Canteen Manager</option>
            </Select>
            <Button
              onClick={async () => {
                try {
                  await api.post("/admin/users/staff", {
                    full_name: newStaffName,
                    email: newStaffEmail,
                    password: "StaffUser@123",
                    employee_code: newStaffEmp,
                    designation: newStaffRole.replace("_", " "),
                    role_names: [newStaffRole],
                    assigned_canteen_id: activeCanteenId,
                  });
                  setNewStaffName("");
                  setNewStaffEmail("");
                  setNewStaffEmp("");
                  pushToast("Staff user created", "success");
                  refetchStaff();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Staff Account
            </Button>
          </Card>
        </div>
      )}

      {tab === "support" && (
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900">Customer Support Tickets ({tickets.length})</h2>
          {tickets.map((t) => (
            <div key={t.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-3 text-xs">
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
          ))}
        </Card>
      )}

      {tab === "system" && (
        <div className="grid gap-5 md:grid-cols-2">
          <Card className="p-5 space-y-4">
            <h2 className="font-bold text-slate-900 flex items-center gap-2">
              <Shield className="h-4 w-4 text-emerald-600" /> System Health & Hardware Settings
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
              <div className="border-t border-slate-100 pt-3 flex items-center justify-between text-sm">
                <div>
                  <div className="font-bold">Self-Service Touch Kiosk Mode</div>
                  <div className="text-xs text-slate-500">Disabled by default until campus kiosk hardware is installed</div>
                </div>
                <Button
                  size="sm"
                  variant={college.kiosk_enabled ? "success" : "outline"}
                  onClick={async () => {
                    await api.put("/admin/college", { kiosk_enabled: !college.kiosk_enabled });
                    refetchCollege();
                    pushToast(`Kiosk mode ${!college.kiosk_enabled ? "enabled" : "disabled"}`, "info");
                  }}
                >
                  {college.kiosk_enabled ? "Enabled" : "Disabled"}
                </Button>
              </div>
            )}
          </Card>

          <Card className="p-5 space-y-2 max-h-96 overflow-y-auto">
            <h2 className="font-bold text-slate-900">Recent Audit Logs</h2>
            {auditLogs.map((a) => (
              <div key={a.id} className="border-b border-slate-100 py-1.5 text-xs flex justify-between gap-2">
                <span className="font-mono font-semibold text-slate-800">{a.action}</span>
                <span className="text-slate-500">{a.entity_type}:{a.entity_id}</span>
              </div>
            ))}
          </Card>
        </div>
      )}
    </div>
  );
};
