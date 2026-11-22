import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Download } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useRealtimeSync } from "../../hooks/useRealtimeSync";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, CollegeSettings, FoodItem } from "../../types";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";
import { RealtimeStatusBadge } from "../../components/ui/RealtimeStatusBadge";
import { LocationsTab } from "./components/LocationsTab";
import { MenuTab, QRTab } from "./components/MenuQrTab";
import { QueueTab, StaffTab } from "./components/QueueStaffTab";
import { PromotionsTab, SystemTab } from "./components/PromotionsSystemTab";
import { OrdersUsersTab } from "./components/OrdersUsersTab";
import { WebsiteQrTab } from "./components/WebsiteQrTab";

export const AdminConsolePage: React.FC = () => {
  const { pushToast } = useToast();
  const { user, selectedCanteenId } = useAppStore();
  const isCollegeAdmin = Boolean(user?.roles?.some((r) => r === "super_admin" || r === "college_admin"));
  const [tab, setTab] = useState<
    "analytics" | "orders" | "locations" | "menu" | "qr" | "website_qr" | "queue" | "staff" | "promotions" | "support" | "system"
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
  const activeCanteenId = (!isCollegeAdmin && user?.assigned_canteen_id) ? user.assigned_canteen_id : (canteenId || canteens[0]?.id || "");
  const [scopeReportToCanteen, setScopeReportToCanteen] = useState(!isCollegeAdmin);
  const [reportStartDate, setReportStartDate] = useState("");
  const [reportEndDate, setReportEndDate] = useState("");
  const [chartPeriod, setChartPeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const [expandedTicketId, setExpandedTicketId] = useState<string | null>(null);
  const [ticketThreadMap, setTicketThreadMap] = useState<Record<string, any[]>>({});

  const reportParams = new URLSearchParams();
  if (scopeReportToCanteen && activeCanteenId) reportParams.set("canteen_id", activeCanteenId);
  if (reportStartDate) reportParams.set("start_date", reportStartDate);
  if (reportEndDate) reportParams.set("end_date", reportEndDate);
  const reportQueryCanteen = reportParams.toString() ? `?${reportParams.toString()}` : "";

  const streamCanteenScope =
    !isCollegeAdmin && user?.assigned_canteen_id
      ? user.assigned_canteen_id
      : scopeReportToCanteen && activeCanteenId
      ? activeCanteenId
      : "";
  const { status: adminSyncStatus, lastSyncedAt: adminLastSyncedAt } = useRealtimeSync({
    enabled: tab === "analytics" || tab === "queue",
    ssePath: `/realtime/staff/orders/stream${streamCanteenScope ? `?canteen_id=${streamCanteenScope}` : ""}`,
    wsPath: activeCanteenId ? `/ws/kitchen/${activeCanteenId}` : "/ws/board/all",
    queryKeys: [["admin-report"], ["admin-queue"], ["admin-all-orders"]],
  });

  const { data: report } = useQuery<any>({
    queryKey: ["admin-report", activeCanteenId, scopeReportToCanteen, reportStartDate, reportEndDate],
    enabled: tab === "analytics",
    queryFn: async () => (await api.get(`/reports/dashboard${reportQueryCanteen}`)).data,
    refetchInterval: adminSyncStatus === "live" ? 30000 : 6000,
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
    queryKey: ["admin-staff", activeCanteenId],
    enabled: tab === "staff" || tab === "support",
    queryFn: async () => (await api.get(`/staff${activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: tickets = [], refetch: refetchTickets } = useQuery<any[]>({
    queryKey: ["admin-tickets", activeCanteenId],
    enabled: tab === "support",
    queryFn: async () => (await api.get(`/support/tickets${!isCollegeAdmin && activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: auditLogs = [] } = useQuery<any[]>({
    queryKey: ["admin-audits"],
    enabled: tab === "system" && isCollegeAdmin,
    queryFn: async () => (await api.get("/admin/audit-logs?limit=40")).data,
  });

  const { data: health } = useQuery<any>({
    queryKey: ["admin-health"],
    enabled: tab === "system" && isCollegeAdmin,
    queryFn: async () => (await api.get("/admin/health")).data,
  });

  const [replyByTicket, setReplyByTicket] = useState<Record<string, string>>({});

  const downloadBlob = async (url: string, filename: string) => {
    try {
      const res = await api.get(url, { responseType: "blob" });
      const objUrl = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(objUrl);
    } catch (err) {
      pushToast(getApiError(err, "Export failed"), "error");
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 space-y-6">
      <div className="no-print flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-[#380106] p-4 text-white">
        <div className="flex items-center gap-3">
          <BrandLogo size="md" variant="dark" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-extrabold">CollegeBites Operations &amp; Admin Console</h1>
              <RealtimeStatusBadge status={adminSyncStatus} lastSyncedAt={adminLastSyncedAt} darkSurface />
            </div>
            <p className="text-xs text-[#fdedce]/80">{college?.college_name} • Real-time database analytics &amp; controls</p>
          </div>
        </div>
        <Select
          value={activeCanteenId}
          disabled={!isCollegeAdmin && Boolean(user?.assigned_canteen_id)}
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

      <div className="no-print flex flex-wrap gap-2">
        {[
          { k: "analytics", l: "Analytics & Reports" },
          { k: "orders", l: "Orders & Users" },
          { k: "locations", l: "Locations, Counters & Hours" },
          { k: "menu", l: "Menus & CSV" },
          { k: "qr", l: "Location QR Codes" },
          ...(isCollegeAdmin ? [{ k: "website_qr", l: "Website QR Generator" }] : []),
          { k: "queue", l: "Queue, Crowd & Slots" },
          { k: "staff", l: "Staff, Attendance & Tasks" },
          { k: "promotions", l: "Announcements & Banners" },
          { k: "support", l: "Support Tickets" },
          ...(isCollegeAdmin ? [{ k: "system", l: "Settings, Reconcile & Audits" }] : []),
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
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              {isCollegeAdmin ? (
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-600 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={scopeReportToCanteen}
                    onChange={(e) => setScopeReportToCanteen(e.target.checked)}
                  />
                  Filter report to selected canteen
                </label>
              ) : (
                <span className="text-xs font-semibold text-slate-500">Scoped to assigned canteen</span>
              )}
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <input
                  type="date"
                  value={reportStartDate}
                  onChange={(e) => setReportStartDate(e.target.value)}
                  aria-label="Report start date"
                  className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs"
                />
                <span className="text-slate-400">to</span>
                <input
                  type="date"
                  value={reportEndDate}
                  onChange={(e) => setReportEndDate(e.target.value)}
                  aria-label="Report end date"
                  className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs"
                />
                {(reportStartDate || reportEndDate) && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setReportStartDate("");
                      setReportEndDate("");
                    }}
                  >
                    Clear
                  </Button>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => downloadBlob(`/reports/export/csv${reportQueryCanteen}`, "collegebites-report.csv")}>
                <Download className="h-3.5 w-3.5" /> Export CSV
              </Button>
              <Button size="sm" variant="primary" onClick={() => downloadBlob(`/reports/export/pdf${reportQueryCanteen}`, "collegebites-report.pdf")}>
                <Download className="h-3.5 w-3.5" /> Export PDF
              </Button>
            </div>
          </div>

          {report.today_summary && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <Card className="p-4 border-[#76010d]/20 bg-[#76010d]/[0.03]">
                <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Orders Today</div>
                <div className="text-2xl font-black text-slate-900">{report.today_summary.total_orders_today}</div>
                <div className="text-xs text-slate-500 mt-0.5">{report.today_summary.date}</div>
              </Card>
              <Card className="p-4 border-emerald-200 bg-emerald-50/40">
                <div className="text-[11px] font-bold uppercase tracking-wide text-emerald-700">Completed Today</div>
                <div className="text-2xl font-black text-emerald-900">{report.today_summary.completed_orders_today}</div>
                <div className="text-xs text-emerald-700 mt-0.5">
                  Completion rate: {report.operations.completion_rate_percent ?? 0}%
                </div>
              </Card>
              <Card className="p-4 border-amber-200 bg-amber-50/50">
                <div className="text-[11px] font-bold uppercase tracking-wide text-amber-800">Active Pending Queue</div>
                <div className="text-2xl font-black text-amber-900">{report.today_summary.active_pending_orders}</div>
                <div className="text-xs text-amber-700 mt-0.5">
                  Today incl. unpaid: {report.today_summary.pending_orders_today}
                </div>
              </Card>
              <Card className="p-4">
                <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Sales Today</div>
                <div className="text-2xl font-black text-[#76010d]">₹{report.today_summary.revenue_today}</div>
                <div className="text-xs text-slate-500 mt-0.5">Confirmed revenue</div>
              </Card>
              <Card className="p-4">
                <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Payment Success</div>
                <div className="text-2xl font-black text-slate-900">{report.payment_stats?.success_rate_percent ?? 0}%</div>
                <div className="text-xs text-slate-500 mt-0.5">
                  {report.payment_stats?.confirmed_count ?? 0} ok / {report.payment_stats?.failed_count ?? 0} failed
                </div>
              </Card>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="p-4">
              <div className="text-xs text-slate-500">Confirmed Orders (Range)</div>
              <div className="text-2xl font-black text-slate-900">{report.sales.total_orders}</div>
              <div className="text-xs text-emerald-700 mt-1">
                Completed: {report.operations.completed_orders} • Pending: {report.operations.pending_orders ?? 0} • Cancelled: {report.operations.cancelled_orders}
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-slate-500">Net Sales Revenue</div>
              <div className="text-2xl font-black text-[#76010d]">₹{report.sales.net_sales}</div>
              <div className="text-xs text-slate-500 mt-1">
                AOV: ₹{report.sales.average_order_value} • Tax: ₹{report.sales.tax_collected}
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-slate-500">Prep &amp; Wait Times</div>
              <div className="text-2xl font-black text-slate-900">{report.operations.avg_prep_minutes} min</div>
              <div className="text-xs text-slate-500 mt-1">
                Pickup wait: {report.operations.avg_pickup_wait_minutes} min • Delayed: {report.operations.delayed_orders}
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-slate-500">Customers &amp; Support</div>
              <div className="text-2xl font-black text-slate-900">{report.customers.repeat_order_rate_percent}%</div>
              <div className="text-xs text-slate-500 mt-1">
                Rating: ★ {report.customers.average_food_rating} • Open tickets: {report.support?.open_tickets ?? 0}
              </div>
            </Card>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card className="p-5">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h3 className="font-bold text-slate-900 text-sm">
                  {chartPeriod === "daily" ? "Daily" : chartPeriod === "weekly" ? "Weekly" : "Monthly"} Revenue Trend (₹)
                </h3>
                <div className="flex gap-1">
                  {(["daily", "weekly", "monthly"] as const).map((period) => (
                    <Button
                      key={period}
                      size="sm"
                      variant={chartPeriod === period ? "secondary" : "outline"}
                      onClick={() => setChartPeriod(period)}
                    >
                      {period === "daily" ? "Daily" : period === "weekly" ? "Weekly" : "Monthly"}
                    </Button>
                  ))}
                </div>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={
                      chartPeriod === "weekly"
                        ? report.sales.weekly_series || []
                        : chartPeriod === "monthly"
                        ? report.sales.monthly_series || []
                        : report.sales.daily_series || []
                    }
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey={chartPeriod === "weekly" ? "week" : chartPeriod === "monthly" ? "month" : "date"} tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="revenue" fill="#76010d" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <Card className="p-5">
              <h3 className="font-bold text-slate-900 mb-3 text-sm">Top Selling Dishes</h3>
              <div className="space-y-2 text-xs">
                {report.sales.top_items.length === 0 ? (
                  <div className="py-8 text-center text-slate-400">No dish sales recorded for selected range.</div>
                ) : (
                  report.sales.top_items.map((ti: any) => (
                    <div key={ti.item_name} className="flex items-center justify-between border-b border-slate-100 pb-2">
                      <span className="font-bold text-slate-800">{ti.item_name}</span>
                      <span>
                        {ti.quantity_sold} sold • <strong>₹{ti.revenue.toFixed(2)}</strong>
                      </span>
                    </div>
                  ))
                )}
              </div>
            </Card>
          </div>

          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-4">
            <Card className="p-4">
              <h3 className="font-bold text-slate-900 mb-2 text-xs uppercase tracking-wide">Category-wise Sales</h3>
              <div className="space-y-1.5 text-xs">
                {(report.sales.category_sales || []).length === 0 ? (
                  <div className="text-slate-400">No category sales yet.</div>
                ) : (
                  (report.sales.category_sales || []).map((c: any) => (
                    <div key={c.category} className="flex justify-between">
                      <span className="text-slate-700 font-medium">{c.category}</span>
                      <span className="font-bold">₹{Number(c.revenue).toFixed(2)} ({c.quantity})</span>
                    </div>
                  ))
                )}
              </div>
            </Card>

            <Card className="p-4">
              <h3 className="font-bold text-slate-900 mb-2 text-xs uppercase tracking-wide">Counter-wise Sales</h3>
              <div className="space-y-1.5 text-xs">
                {(report.sales.counter_sales || []).length === 0 ? (
                  <div className="text-slate-400">No counter sales yet.</div>
                ) : (
                  (report.sales.counter_sales || []).map((c: any) => (
                    <div key={c.counter} className="flex justify-between">
                      <span className="text-slate-700 font-medium">{c.counter}</span>
                      <span className="font-bold">₹{Number(c.revenue).toFixed(2)} ({c.orders})</span>
                    </div>
                  ))
                )}
              </div>
            </Card>

            <Card className="p-4">
              <h3 className="font-bold text-slate-900 mb-2 text-xs uppercase tracking-wide">Payment Breakdown</h3>
              <div className="space-y-1.5 text-xs">
                {(report.sales.payment_breakdown || []).length === 0 ? (
                  <div className="text-slate-400">No confirmed payments yet.</div>
                ) : (
                  (report.sales.payment_breakdown || []).map((p: any) => (
                    <div key={p.method} className="flex justify-between">
                      <span className="uppercase text-slate-700 font-medium">{p.method}</span>
                      <span className="font-bold">₹{Number(p.amount).toFixed(2)} ({p.orders})</span>
                    </div>
                  ))
                )}
              </div>
            </Card>

            <Card className="p-4">
              <h3 className="font-bold text-slate-900 mb-2 text-xs uppercase tracking-wide">Peak Hours</h3>
              <div className="space-y-1.5 text-xs">
                {(report.operations.peak_hours || []).length === 0 ? (
                  <div className="text-slate-400">No hourly activity yet.</div>
                ) : (
                  (report.operations.peak_hours || []).slice(0, 6).map((h: any) => (
                    <div key={h.hour} className="flex justify-between">
                      <span className="font-mono text-slate-700">{h.hour}</span>
                      <span className="font-bold">
                        {h.orders} orders{h.revenue !== undefined ? ` • ₹${Number(h.revenue).toFixed(0)}` : ""}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4 space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <div className="font-bold text-slate-900">Inventory Shortage Alerts &amp; Wastage</div>
                <div className="text-sm font-black text-red-600">₹{report.inventory?.total_wastage_loss ?? "0.00"} loss</div>
              </div>
              <div className="text-slate-500">
                Tracked (Active): {report.inventory?.tracked_ingredients ?? 0} • Low stock: {report.inventory?.low_stock_count ?? 0} • Expiring (7d): {report.inventory?.expiring_within_7_days ?? 0}
              </div>
              {(report.inventory?.low_stock_items || []).length > 0 && (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {(report.inventory.low_stock_items || []).slice(0, 8).map((item: any) => (
                    <Badge key={item.inventory_item_id} tone="red">
                      {item.ingredient_name}: {item.current_quantity}/{item.reorder_level} {item.unit}
                    </Badge>
                  ))}
                </div>
              )}
            </Card>

            <Card className="p-4 space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <div className="font-bold text-slate-900">Staff &amp; Operations Activity</div>
                <div className="text-sm font-black text-slate-900">{report.staff_performance?.cashier_walkin_orders ?? 0} Walk-in POS</div>
              </div>
              <div className="text-slate-500">
                Check-ins: {report.staff_performance?.present_checkins ?? 0} • Leaves: {report.staff_performance?.leave_records ?? 0} • Tasks done: {report.staff_performance?.tasks_completed ?? 0}/{report.staff_performance?.tasks_total ?? 0}
              </div>
              {(report.staff_performance?.staff_breakdown || []).length > 0 && (
                <div className="overflow-x-auto pt-1">
                  <table className="w-full text-left text-[11px]">
                    <thead>
                      <tr className="border-b border-slate-200 text-slate-500">
                        <th className="py-1 pr-2">Staff</th>
                        <th className="py-1 pr-2">Check-ins</th>
                        <th className="py-1 pr-2">Tasks</th>
                        <th className="py-1 pr-2">POS</th>
                        <th className="py-1">Updates</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {(report.staff_performance.staff_breakdown || []).slice(0, 10).map((sb: any) => (
                        <tr key={sb.user_id}>
                          <td className="py-1 pr-2 font-semibold text-slate-800">{sb.full_name}</td>
                          <td className="py-1 pr-2">{sb.checkins}</td>
                          <td className="py-1 pr-2">{sb.tasks_completed}/{sb.tasks_total}</td>
                          <td className="py-1 pr-2">{sb.cashier_orders}</td>
                          <td className="py-1 font-semibold">{sb.status_updates}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>
        </div>
      )}

      {tab === "orders" && <OrdersUsersTab activeCanteenId={activeCanteenId} />}

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

      {tab === "website_qr" && isCollegeAdmin && (
        <WebsiteQrTab canteens={canteens} defaultCanteenId={activeCanteenId} downloadBlob={downloadBlob} />
      )}

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
                      try {
                        await api.post(`/support/tickets/${t.id}/assign`, { assigned_to_user_id: e.target.value });
                        pushToast("Ticket assigned", "success");
                        refetchTickets();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
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
                        try {
                          await api.post(`/support/tickets/${t.id}/resolve?resolution_note=Resolved%20by%20admin`);
                          pushToast("Ticket marked resolved", "success");
                          refetchTickets();
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      Resolve
                    </Button>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    if (expandedTicketId === t.id) {
                      setExpandedTicketId(null);
                      return;
                    }
                    try {
                      const msgs = (await api.get(`/support/tickets/${t.id}/messages`)).data;
                      setTicketThreadMap((p) => ({ ...p, [t.id]: msgs }));
                      setExpandedTicketId(t.id);
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  {expandedTicketId === t.id ? "Hide Thread" : "View Thread"}
                </Button>
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
                    try {
                      await api.post(`/support/tickets/${t.id}/messages`, { message: msg });
                      setReplyByTicket((p) => ({ ...p, [t.id]: "" }));
                      const msgs = (await api.get(`/support/tickets/${t.id}/messages`)).data;
                      setTicketThreadMap((p) => ({ ...p, [t.id]: msgs }));
                      setExpandedTicketId(t.id);
                      pushToast("Reply sent", "success");
                      refetchTickets();
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  Send Reply
                </Button>
              </div>
              {expandedTicketId === t.id && (
                <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 space-y-1.5">
                  {(ticketThreadMap[t.id] || []).length === 0 ? (
                    <div className="text-slate-400">No messages in thread yet.</div>
                  ) : (
                    (ticketThreadMap[t.id] || []).map((m: any) => (
                      <div key={m.id} className="text-xs">
                        <span className="font-bold uppercase text-slate-700">{m.sender_role}:</span>{" "}
                        <span className="text-slate-700">{m.message}</span>{" "}
                        <span className="text-[10px] text-slate-400">{m.created_at?.slice(11, 16)}</span>
                      </div>
                    ))
                  )}
                </div>
              )}
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
