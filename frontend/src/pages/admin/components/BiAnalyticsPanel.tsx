import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Download, Search } from "lucide-react";
import { api } from "../../../api/client";
import { Badge, Button, Card, Input } from "../../../components/ui/Primitives";

const PIE_COLORS = ["#76010d", "#b45309", "#0f766e", "#1d4ed8", "#7c3aed", "#be123c"];

interface BiAnalyticsPanelProps {
  report: any;
  isCollegeAdmin: boolean;
  scopeReportToCanteen: boolean;
  setScopeReportToCanteen: (v: boolean) => void;
  reportPreset: string;
  setReportPreset: (v: string) => void;
  reportStartDate: string;
  setReportStartDate: (v: string) => void;
  reportEndDate: string;
  setReportEndDate: (v: string) => void;
  reportQueryCanteen: string;
  downloadBlob: (url: string, filename: string) => void;
}

export const BiAnalyticsPanel: React.FC<BiAnalyticsPanelProps> = ({
  report,
  isCollegeAdmin,
  scopeReportToCanteen,
  setScopeReportToCanteen,
  reportPreset,
  setReportPreset,
  reportStartDate,
  setReportStartDate,
  reportEndDate,
  setReportEndDate,
  reportQueryCanteen,
  downloadBlob,
}) => {
  const [chartPeriod, setChartPeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const [detailTab, setDetailTab] = useState<"orders" | "items" | "inventory">("orders");
  const [detailSearch, setDetailSearch] = useState("");
  const [itemSortDir, setItemSortDir] = useState<"desc" | "asc">("desc");
  const [lowOnly, setLowOnly] = useState(false);
  const [page, setPage] = useState(1);

  const detailParams = new URLSearchParams(reportQueryCanteen.startsWith("?") ? reportQueryCanteen.slice(1) : reportQueryCanteen);
  detailParams.set("page", String(page));
  detailParams.set("page_size", "10");
  if (detailSearch.trim()) detailParams.set("q", detailSearch.trim());
  if (detailTab === "items") detailParams.set("sort", itemSortDir);
  if (detailTab === "inventory" && lowOnly) detailParams.set("low_only", "true");

  const { data: detailData } = useQuery<any>({
    queryKey: ["bi-details", detailTab, detailParams.toString()],
    queryFn: async () => (await api.get(`/reports/details/${detailTab}?${detailParams.toString()}`)).data,
  });

  const presets = [
    { key: "today", label: "Today" },
    { key: "yesterday", label: "Yesterday" },
    { key: "last_7_days", label: "Last 7 Days" },
    { key: "last_30_days", label: "Last 30 Days" },
    { key: "this_month", label: "This Month" },
    { key: "custom", label: "Custom" },
  ];

  const activeTrendData =
    chartPeriod === "weekly"
      ? report.sales.weekly_series || []
      : chartPeriod === "monthly"
      ? report.sales.monthly_series || []
      : report.sales.daily_series || [];

  const nonEmptyHours = (report.sales.hourly_series || []).filter(
    (h: any) => h.orders > 0 || (Number(h.hour.slice(0, 2)) >= 7 && Number(h.hour.slice(0, 2)) <= 22)
  );

  return (
    <div className="space-y-5">
      {/* Preset Bar + Date Range + Exports */}
      <Card className="p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {presets.map((p) => (
              <Button
                key={p.key}
                size="sm"
                variant={reportPreset === p.key ? "secondary" : "outline"}
                onClick={() => {
                  setReportPreset(p.key);
                  setPage(1);
                  if (p.key !== "custom") {
                    setReportStartDate("");
                    setReportEndDate("");
                  }
                }}
              >
                {p.label}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => downloadBlob(`/reports/export/xlsx${reportQueryCanteen}`, "collegebites-bi-report.xlsx")}
            >
              <Download className="h-3.5 w-3.5" /> Excel (.xlsx)
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => downloadBlob(`/reports/export/csv${reportQueryCanteen}`, "collegebites-report.csv")}
            >
              <Download className="h-3.5 w-3.5" /> CSV
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => downloadBlob(`/reports/export/pdf${reportQueryCanteen}`, "collegebites-report.pdf")}
            >
              <Download className="h-3.5 w-3.5" /> PDF
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-2.5 text-xs">
          <div className="flex flex-wrap items-center gap-3">
            {isCollegeAdmin ? (
              <label className="flex items-center gap-2 font-semibold text-slate-600 cursor-pointer">
                <input
                  type="checkbox"
                  checked={scopeReportToCanteen}
                  onChange={(e) => {
                    setScopeReportToCanteen(e.target.checked);
                    setPage(1);
                  }}
                />
                Filter BI to selected canteen
              </label>
            ) : (
              <span className="font-semibold text-slate-500">Scoped to assigned canteen</span>
            )}
            <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-mono text-slate-600">
              Active Window: {report.range.start_date} to {report.range.end_date}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <input
              type="date"
              value={reportStartDate}
              onChange={(e) => {
                setReportPreset("custom");
                setReportStartDate(e.target.value);
                setPage(1);
              }}
              aria-label="Report start date"
              className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs"
            />
            <span className="text-slate-400">to</span>
            <input
              type="date"
              value={reportEndDate}
              onChange={(e) => {
                setReportPreset("custom");
                setReportEndDate(e.target.value);
                setPage(1);
              }}
              aria-label="Report end date"
              className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs"
            />
          </div>
        </div>
      </Card>

      {/* Today Snapshot */}
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
            <div className="text-xs text-amber-700 mt-0.5">Today incl. unpaid: {report.today_summary.pending_orders_today}</div>
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

      {/* Range KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="p-4">
          <div className="text-xs text-slate-500">Confirmed Orders (Range)</div>
          <div className="text-2xl font-black text-slate-900">{report.sales.total_orders}</div>
          <div className="text-xs text-emerald-700 mt-1">
            Completed: {report.operations.completed_orders} • Cancelled: {report.operations.cancelled_orders}
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

      {/* Charts Row 1: Revenue AreaChart + Hourly Throughput BarChart */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
            <h3 className="font-bold text-slate-900 text-sm">
              {chartPeriod === "daily" ? "Daily" : chartPeriod === "weekly" ? "Weekly" : "Monthly"} Revenue &amp; Order Trend
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
              <AreaChart data={activeTrendData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={chartPeriod === "weekly" ? "week" : chartPeriod === "monthly" ? "month" : "date"} tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Area type="monotone" dataKey="revenue" name="Revenue (₹)" stroke="#76010d" fill="#76010d" fillOpacity={0.18} />
                <Area type="monotone" dataKey="orders" name="Orders" stroke="#0f766e" fill="#0f766e" fillOpacity={0.12} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="p-5">
          <h3 className="font-bold text-slate-900 mb-3 text-sm">Hourly Order &amp; Completion Throughput</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={nonEmptyHours}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="hour" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="orders" name="Paid Orders" fill="#76010d" radius={[4, 4, 0, 0]} />
                <Bar dataKey="completed_orders" name="Completed" fill="#059669" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* Charts Row 2: Category PieChart + Inventory Consumption LineChart */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="p-5">
          <h3 className="font-bold text-slate-900 mb-3 text-sm">Category Revenue Distribution</h3>
          {(report.sales.category_sales || []).length === 0 ? (
            <div className="h-60 flex items-center justify-center text-xs text-slate-400">
              No category revenue data in selected date window.
            </div>
          ) : (
            <div className="h-60">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={report.sales.category_sales}
                    dataKey="revenue"
                    nameKey="category"
                    innerRadius={52}
                    outerRadius={88}
                    paddingAngle={2}
                  >
                    {(report.sales.category_sales || []).map((_entry: any, index: number) => (
                      <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v: any) => `₹${Number(v).toFixed(2)}`} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card className="p-5">
          <h3 className="font-bold text-slate-900 mb-3 text-sm">Inventory Consumption, Restock &amp; Wastage Trend</h3>
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={report.inventory?.consumption_trends || []}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="consumed_qty" name="Consumed" stroke="#76010d" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="restocked_qty" name="Restocked" stroke="#059669" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="wastage_qty" name="Wasted" stroke="#d97706" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* Top Selling vs Least Ordered Food Items */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="p-5">
          <h3 className="font-bold text-slate-900 mb-3 text-sm">Most Popular Dishes (Top 10)</h3>
          <div className="space-y-2 text-xs">
            {report.sales.top_items.length === 0 ? (
              <div className="py-6 text-center text-slate-400">No dish sales recorded for selected range.</div>
            ) : (
              report.sales.top_items.slice(0, 10).map((ti: any) => (
                <div key={ti.item_name} className="flex items-center justify-between border-b border-slate-100 pb-2">
                  <span className="font-bold text-slate-800">{ti.item_name}</span>
                  <span>
                    {ti.quantity_sold} sold • <strong>₹{Number(ti.revenue).toFixed(2)}</strong>
                  </span>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card className="p-5">
          <h3 className="font-bold text-slate-900 mb-3 text-sm">Least Ordered / Slow-Moving Items</h3>
          <div className="space-y-2 text-xs">
            {(report.sales.least_ordered_items || []).length === 0 ? (
              <div className="py-6 text-center text-slate-400">No active menu items found.</div>
            ) : (
              (report.sales.least_ordered_items || []).slice(0, 10).map((li: any) => (
                <div key={li.food_item_id} className="flex items-center justify-between border-b border-slate-100 pb-2">
                  <div>
                    <span className="font-bold text-slate-800">{li.item_name}</span>
                    <span className="ml-2 text-[11px] text-slate-400">{li.category_name}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={li.quantity_sold === 0 ? "amber" : "slate"}>{li.quantity_sold} sold</Badge>
                    <span className="font-semibold text-slate-700">₹{Number(li.revenue).toFixed(2)}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Counter Utilization + Payment + Inventory Shortages + Staff Activity */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4 space-y-2 text-xs">
          <div className="flex items-center justify-between">
            <div className="font-bold text-slate-900">Counter Performance &amp; Utilization</div>
            <span className="text-slate-500">{(report.sales.counter_performance || []).length} active counters</span>
          </div>
          {(report.sales.counter_performance || []).length === 0 ? (
            <div className="text-slate-400 py-4">No active counter metrics.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[11px]">
                <thead>
                  <tr className="border-b border-slate-200 text-slate-500">
                    <th className="py-1 pr-2">Counter</th>
                    <th className="py-1 pr-2">Orders</th>
                    <th className="py-1 pr-2">Revenue</th>
                    <th className="py-1 pr-2">Avg Prep</th>
                    <th className="py-1">Live Util</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {(report.sales.counter_performance || []).map((c: any) => (
                    <tr key={c.counter_id}>
                      <td className="py-1.5 pr-2 font-semibold text-slate-800">
                        {c.counter_name} <span className="text-[10px] text-slate-400 uppercase">({c.counter_type})</span>
                      </td>
                      <td className="py-1.5 pr-2">{c.orders}</td>
                      <td className="py-1.5 pr-2 font-semibold">₹{Number(c.revenue).toFixed(2)}</td>
                      <td className="py-1.5 pr-2">{c.avg_prep_minutes}m</td>
                      <td className="py-1.5">
                        <Badge tone={c.utilization_percent >= 80 ? "red" : "green"}>{c.utilization_percent}%</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card className="p-4 space-y-2 text-xs">
          <div className="flex items-center justify-between">
            <div className="font-bold text-slate-900">Staff &amp; Operations Activity</div>
            <div className="text-sm font-black text-slate-900">{report.staff_performance?.cashier_walkin_orders ?? 0} Walk-in POS</div>
          </div>
          <div className="text-slate-500">
            Check-ins: {report.staff_performance?.present_checkins ?? 0} • Leaves: {report.staff_performance?.leave_records ?? 0} • Tasks done:{" "}
            {report.staff_performance?.tasks_completed ?? 0}/{report.staff_performance?.tasks_total ?? 0}
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
                      <td className="py-1 pr-2">
                        {sb.tasks_completed}/{sb.tasks_total}
                      </td>
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

      {/* Low Stock Shortage Summary */}
      <Card className="p-4 space-y-2 text-xs">
        <div className="flex items-center justify-between">
          <div className="font-bold text-slate-900">Inventory Shortage Alerts &amp; Wastage Loss</div>
          <div className="text-sm font-black text-red-600">₹{report.inventory?.total_wastage_loss ?? "0.00"} loss</div>
        </div>
        <div className="text-slate-500">
          Tracked (Active): {report.inventory?.tracked_ingredients ?? 0} • Low stock: {report.inventory?.low_stock_count ?? 0} • Expiring (7d):{" "}
          {report.inventory?.expiring_within_7_days ?? 0} • Purchases: ₹{report.inventory?.total_purchases_received ?? "0.00"}
        </div>
        {(report.inventory?.low_stock_items || []).length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {(report.inventory.low_stock_items || []).slice(0, 10).map((item: any) => (
              <Badge key={item.inventory_item_id} tone="red">
                {item.ingredient_name}: {item.current_quantity}/{item.reorder_level} {item.unit}
              </Badge>
            ))}
          </div>
        )}
      </Card>

      {/* Searchable Paginated Detail Tables */}
      <Card className="p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {[
              { key: "orders", label: "Orders Drill-Down" },
              { key: "items", label: "Menu Item Analytics" },
              { key: "inventory", label: "Inventory Consumption" },
            ].map((t) => (
              <Button
                key={t.key}
                size="sm"
                variant={detailTab === t.key ? "secondary" : "outline"}
                onClick={() => {
                  setDetailTab(t.key as any);
                  setPage(1);
                }}
              >
                {t.label}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {detailTab === "items" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setItemSortDir((d) => (d === "desc" ? "asc" : "desc"));
                  setPage(1);
                }}
              >
                Sort Qty: {itemSortDir === "desc" ? "High → Low" : "Low → High"}
              </Button>
            )}
            {detailTab === "inventory" && (
              <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-600 cursor-pointer">
                <input
                  type="checkbox"
                  checked={lowOnly}
                  onChange={(e) => {
                    setLowOnly(e.target.checked);
                    setPage(1);
                  }}
                />
                Low stock only
              </label>
            )}
            <div className="relative">
              <Search className="h-3.5 w-3.5 text-slate-400 absolute left-2.5 top-2.5" />
              <Input
                value={detailSearch}
                onChange={(e) => {
                  setDetailSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Search details..."
                className="pl-8 w-52"
              />
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          {detailTab === "orders" && (
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-[11px] uppercase text-slate-500">
                  <th className="py-2 pr-3">Order / Token</th>
                  <th className="py-2 pr-3">Customer</th>
                  <th className="py-2 pr-3">Counter</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Method</th>
                  <th className="py-2 pr-3">Prep / Wait</th>
                  <th className="py-2 text-right">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(detailData?.items || []).map((row: any) => (
                  <tr key={row.order_id}>
                    <td className="py-2 pr-3 font-bold text-slate-900">
                      {row.order_number} {row.token_code ? `• ${row.token_code}` : ""}
                    </td>
                    <td className="py-2 pr-3">{row.customer_name}</td>
                    <td className="py-2 pr-3">{row.counter_name}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={row.status === "COMPLETED" ? "green" : row.status === "CANCELLED" ? "red" : "blue"}>
                        {row.status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 uppercase text-[11px]">{row.payment_method}</td>
                    <td className="py-2 pr-3 text-slate-500">
                      {row.prep_minutes ?? "-"}m / {row.pickup_wait_minutes ?? "-"}m
                    </td>
                    <td className="py-2 text-right font-bold">₹{row.total_amount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {detailTab === "items" && (
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-[11px] uppercase text-slate-500">
                  <th className="py-2 pr-3">Dish Name</th>
                  <th className="py-2 pr-3">Category</th>
                  <th className="py-2 pr-3">Unit Price</th>
                  <th className="py-2 pr-3">Orders</th>
                  <th className="py-2 pr-3">Qty Sold</th>
                  <th className="py-2 pr-3">Revenue</th>
                  <th className="py-2 text-right">Availability</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(detailData?.items || []).map((row: any) => (
                  <tr key={row.food_item_id}>
                    <td className="py-2 pr-3 font-bold text-slate-900">{row.item_name}</td>
                    <td className="py-2 pr-3 text-slate-600">{row.category_name}</td>
                    <td className="py-2 pr-3">₹{row.unit_price}</td>
                    <td className="py-2 pr-3">{row.order_count}</td>
                    <td className="py-2 pr-3 font-bold">{row.quantity_sold}</td>
                    <td className="py-2 pr-3 font-bold text-[#76010d]">₹{Number(row.revenue).toFixed(2)}</td>
                    <td className="py-2 text-right">
                      <Badge tone={row.is_available ? "green" : "amber"}>{row.is_available ? "Available" : "Unavailable"}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {detailTab === "inventory" && (
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-[11px] uppercase text-slate-500">
                  <th className="py-2 pr-3">Ingredient</th>
                  <th className="py-2 pr-3">Consumed</th>
                  <th className="py-2 pr-3">Restocked</th>
                  <th className="py-2 pr-3">Wasted</th>
                  <th className="py-2 pr-3">Current Stock</th>
                  <th className="py-2 pr-3">Reorder Level</th>
                  <th className="py-2 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(detailData?.items || []).map((row: any) => (
                  <tr key={row.inventory_item_id}>
                    <td className="py-2 pr-3 font-bold text-slate-900">{row.ingredient_name}</td>
                    <td className="py-2 pr-3">
                      {row.consumed_quantity} {row.unit}
                    </td>
                    <td className="py-2 pr-3 text-emerald-700">
                      +{row.restocked_quantity} {row.unit}
                    </td>
                    <td className="py-2 pr-3 text-amber-700">
                      {row.wastage_quantity} {row.unit}
                    </td>
                    <td className="py-2 pr-3 font-bold">
                      {row.current_quantity} {row.unit}
                    </td>
                    <td className="py-2 pr-3">
                      {row.reorder_level} {row.unit}
                    </td>
                    <td className="py-2 text-right">
                      <Badge tone={row.is_low_stock ? "red" : "green"}>{row.is_low_stock ? "LOW STOCK" : "Healthy"}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {(!detailData?.items || detailData.items.length === 0) && (
            <div className="py-8 text-center text-xs text-slate-400">No detail rows match the current filter.</div>
          )}
        </div>

        {/* Pagination Controls */}
        <div className="flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-600">
          <span>
            Page <strong>{detailData?.page ?? page}</strong> of <strong>{detailData?.total_pages ?? 1}</strong> • Total{" "}
            <strong>{detailData?.total ?? 0}</strong> records
          </span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page >= (detailData?.total_pages ?? 1)}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
};
