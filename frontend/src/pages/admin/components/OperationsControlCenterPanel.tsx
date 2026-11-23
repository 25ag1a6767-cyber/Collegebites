import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Calendar,
  CreditCard,
  Filter,
  LifeBuoy,
  Package,
  RefreshCw,
  ShoppingBag,
  Truck,
  Utensils,
} from "lucide-react";
import { api } from "../../../api/client";
import { Badge, Button, Card, Input, Select } from "../../../components/ui/Primitives";

interface OperationsControlCenterPanelProps {
  activeCanteenId: string;
  isCollegeAdmin: boolean;
}

export const OperationsControlCenterPanel: React.FC<OperationsControlCenterPanelProps> = ({
  activeCanteenId,
  isCollegeAdmin,
}) => {
  const [scopeToCanteen, setScopeToCanteen] = useState(!isCollegeAdmin);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [orderStatus, setOrderStatus] = useState("all");
  const [productQuery, setProductQuery] = useState("");
  const [opCategory, setOpCategory] = useState<
    "all" | "orders" | "meal_plans" | "inventory" | "procurement" | "events" | "support" | "sales"
  >("all");

  const { data, isLoading, refetch } = useQuery<any>({
    queryKey: [
      "operations-control-center",
      activeCanteenId,
      scopeToCanteen,
      startDate,
      endDate,
      orderStatus,
      productQuery,
      opCategory,
    ],
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (scopeToCanteen && activeCanteenId) qs.set("canteen_id", activeCanteenId);
      if (startDate) qs.set("start_date", startDate);
      if (endDate) qs.set("end_date", endDate);
      if (orderStatus !== "all") qs.set("order_status", orderStatus);
      if (productQuery.trim()) qs.set("product_q", productQuery.trim());
      qs.set("operational_category", opCategory);
      return (await api.get(`/reports/operations-control-center?${qs.toString()}`)).data;
    },
    refetchInterval: 8000,
  });

  const showSection = (sec: typeof opCategory) => opCategory === "all" || opCategory === sec;
  const s = data?.sales_and_operational_summaries || {};

  return (
    <div className="space-y-6">
      <Card className="p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Activity className="h-5 w-5 text-[#76010d]" />
            <div>
              <h2 className="text-lg font-extrabold text-slate-900">Canteen Operations Control Center</h2>
              <p className="text-xs text-slate-500">
                Centralized real-time PostgreSQL command center across orders, meal plans, inventory, procurement, events, support &amp; billing
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isCollegeAdmin && (
              <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
                <input
                  type="checkbox"
                  checked={scopeToCanteen}
                  onChange={(e) => setScopeToCanteen(e.target.checked)}
                />
                Scope to Selected Canteen
              </label>
            )}
            <Button size="sm" variant="outline" onClick={() => refetch()}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh Live Data
            </Button>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5 pt-2 border-t border-slate-100 text-xs">
          <div>
            <label className="font-bold text-slate-600 block mb-1">Operational Category</label>
            <Select value={opCategory} onChange={(e) => setOpCategory(e.target.value as any)}>
              <option value="all">All Operational Modules</option>
              <option value="orders">Live &amp; Completed Orders</option>
              <option value="meal_plans">Student Meal Plans</option>
              <option value="inventory">Inventory &amp; Low-Stock Alerts</option>
              <option value="procurement">Purchase Orders &amp; Vendor Balances</option>
              <option value="events">College Events &amp; Bulk Orders</option>
              <option value="support">Customer Support Tickets</option>
              <option value="sales">Sales &amp; Invoice Summaries</option>
            </Select>
          </div>
          <div>
            <label className="font-bold text-slate-600 block mb-1">Order Status Filter</label>
            <Select value={orderStatus} onChange={(e) => setOrderStatus(e.target.value)}>
              <option value="all">All Confirmed Statuses</option>
              <option value="PLACED">Placed (New)</option>
              <option value="ACCEPTED">Accepted</option>
              <option value="PREPARING">Preparing</option>
              <option value="READY">Ready for Pickup</option>
              <option value="COMPLETED">Completed</option>
            </Select>
          </div>
          <div>
            <label className="font-bold text-slate-600 block mb-1">Filter by Product / Dish</label>
            <Input
              value={productQuery}
              onChange={(e) => setProductQuery(e.target.value)}
              placeholder="e.g. Biryani, Dosa..."
            />
          </div>
          <div>
            <label className="font-bold text-slate-600 block mb-1">From Date</label>
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <label className="font-bold text-slate-600 block mb-1">To Date</label>
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
        </div>
      </Card>

      {isLoading && !data ? (
        <Card className="p-8 text-center text-xs text-slate-500">Loading real-time operations control center...</Card>
      ) : (
        <>
          {/* Top KPI Grid */}
          {showSection("sales") && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Card className="p-4 border-l-4 border-l-[#76010d]">
                <div className="text-[11px] font-bold uppercase text-slate-500">Combined Verified Revenue</div>
                <div className="text-2xl font-extrabold text-slate-900 mt-1">₹{s.combined_verified_revenue || "0.00"}</div>
                <div className="text-[11px] text-slate-500 mt-1">
                  Orders: ₹{s.orders_revenue || "0.00"} • Meal Plans: ₹{s.active_meal_plans_revenue || "0.00"} • Events: ₹{s.event_bulk_orders_revenue || "0.00"}
                </div>
              </Card>
              <Card className="p-4 border-l-4 border-l-amber-500">
                <div className="text-[11px] font-bold uppercase text-slate-500">Live Order Pipeline</div>
                <div className="text-2xl font-extrabold text-slate-900 mt-1">
                  {s.current_active_orders_count ?? 0} Active
                </div>
                <div className="text-[11px] text-slate-500 mt-1">
                  Pending: {s.pending_orders_count ?? 0} • Prep: {s.preparing_orders_count ?? 0} • Ready: {s.ready_orders_count ?? 0} • Done: {s.completed_orders_count ?? 0}
                </div>
              </Card>
              <Card className="p-4 border-l-4 border-l-emerald-600">
                <div className="text-[11px] font-bold uppercase text-slate-500">Meal Plans &amp; Redemptions</div>
                <div className="text-2xl font-extrabold text-slate-900 mt-1">
                  {data?.active_meal_plans?.active_subscriptions_count ?? 0} Active Plans
                </div>
                <div className="text-[11px] text-slate-500 mt-1">
                  Remaining Meals: {data?.active_meal_plans?.total_remaining_meals ?? 0} • Redeemed: {data?.meal_plan_redemptions?.total_meals_redeemed_recent ?? 0}
                </div>
              </Card>
              <Card className="p-4 border-l-4 border-l-blue-600">
                <div className="text-[11px] font-bold uppercase text-slate-500">Invoices &amp; Vendor Payables</div>
                <div className="text-2xl font-extrabold text-slate-900 mt-1">
                  {s.invoices_issued_count ?? 0} Tax Invoices
                </div>
                <div className="text-[11px] text-slate-500 mt-1">
                  Vendor Due: ₹{data?.vendor_outstanding_balances?.total_outstanding_amount || "0.00"} • Active Offers: {s.active_promotional_campaigns_count ?? 0}
                </div>
              </Card>
            </div>
          )}

          {/* Live Orders Breakdown */}
          {showSection("orders") && (
            <div className="grid gap-4 lg:grid-cols-4">
              {[
                { title: "Pending Orders", list: data?.pending_orders || [], tone: "amber" as const },
                { title: "Preparing in Kitchen", list: data?.preparing_orders || [], tone: "blue" as const },
                { title: "Ready for Pickup", list: data?.ready_orders || [], tone: "green" as const },
                { title: "Completed Orders", list: (data?.completed_orders || []).slice(0, 15), tone: "slate" as const },
              ].map((col) => (
                <Card key={col.title} className="p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-extrabold uppercase text-slate-700 flex items-center gap-1.5">
                      <ShoppingBag className="h-3.5 w-3.5" /> {col.title}
                    </h3>
                    <Badge tone={col.tone}>{col.list.length}</Badge>
                  </div>
                  <div className="space-y-1.5 max-h-60 overflow-y-auto text-xs">
                    {col.list.length === 0 ? (
                      <div className="text-slate-400 py-2">None</div>
                    ) : (
                      col.list.map((o: any) => (
                        <div key={o.id} className="rounded-lg border border-slate-100 p-2 flex justify-between items-center">
                          <div>
                            <div className="font-mono font-bold text-slate-900">
                              {o.pickup_token_code ? `[${o.pickup_token_code}] ` : ""}{o.order_number}
                            </div>
                            <div className="text-[10px] text-slate-500 uppercase">{o.order_type}</div>
                          </div>
                          <div className="font-extrabold text-slate-900">₹{o.total_amount}</div>
                        </div>
                      ))
                    )}
                  </div>
                </Card>
              ))}
            </div>
          )}

          {/* Inventory Alerts & Vendor Procurement */}
          <div className="grid gap-6 lg:grid-cols-2">
            {showSection("inventory") && (
              <Card className="p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="font-bold text-slate-900 flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-amber-600" />
                    Inventory Alerts &amp; Low-Stock Items ({data?.low_stock_items?.length || 0})
                  </h3>
                  <Badge tone={(data?.inventory_alerts?.out_of_stock_count || 0) > 0 ? "red" : "amber"}>
                    {data?.inventory_alerts?.out_of_stock_count || 0} Out of Stock • {data?.inventory_alerts?.blocked_food_items_count || 0} Blocked Dishes
                  </Badge>
                </div>
                <div className="space-y-1.5 max-h-60 overflow-y-auto text-xs">
                  {(data?.low_stock_items || []).length === 0 ? (
                    <div className="text-slate-500">All inventory items are above reorder thresholds.</div>
                  ) : (
                    (data?.low_stock_items || []).map((it: any) => (
                      <div key={it.inventory_item_id} className="flex items-center justify-between rounded-lg border border-amber-100 bg-amber-50/40 p-2">
                        <div>
                          <div className="font-bold text-slate-900">{it.name} ({it.sku})</div>
                          <div className="text-[11px] text-slate-500">Reorder Level: {it.reorder_level} {it.unit}</div>
                        </div>
                        <Badge tone={it.is_out_of_stock ? "red" : "amber"}>
                          {it.current_quantity} {it.unit}
                        </Badge>
                      </div>
                    ))
                  )}
                </div>
              </Card>
            )}

            {showSection("procurement") && (
              <Card className="p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="font-bold text-slate-900 flex items-center gap-2">
                    <Truck className="h-4 w-4 text-slate-700" />
                    Pending Purchase Orders ({data?.pending_purchase_orders?.length || 0}) &amp; Vendor Dues
                  </h3>
                  <Badge tone="amber">
                    Total Vendor Payable: ₹{data?.vendor_outstanding_balances?.total_outstanding_amount || "0.00"}
                  </Badge>
                </div>
                <div className="grid gap-3 md:grid-cols-2 text-xs">
                  <div className="space-y-1.5 max-h-56 overflow-y-auto">
                    <div className="font-bold text-slate-500 uppercase text-[10px]">Open Purchase Orders</div>
                    {(data?.pending_purchase_orders || []).length === 0 ? (
                      <div className="text-slate-400">No pending purchase orders.</div>
                    ) : (
                      (data?.pending_purchase_orders || []).map((po: any) => (
                        <div key={po.id} className="rounded-lg border border-slate-100 p-2 flex justify-between">
                          <div>
                            <div className="font-mono font-bold">{po.po_number}</div>
                            <div className="text-[10px] uppercase text-slate-500">{po.status}</div>
                          </div>
                          <div className="font-bold">₹{po.total_cost}</div>
                        </div>
                      ))
                    )}
                  </div>
                  <div className="space-y-1.5 max-h-56 overflow-y-auto">
                    <div className="font-bold text-slate-500 uppercase text-[10px]">Vendor Outstanding Balances</div>
                    {(data?.vendor_outstanding_balances?.vendors || []).length === 0 ? (
                      <div className="text-slate-400">All vendor balances settled.</div>
                    ) : (
                      (data?.vendor_outstanding_balances?.vendors || []).map((v: any) => (
                        <div key={v.supplier_id} className="rounded-lg border border-slate-100 p-2 flex justify-between">
                          <div>
                            <div className="font-bold">{v.supplier_name}</div>
                            <div className="text-[10px] text-slate-500">Billed: ₹{v.total_billed_amount}</div>
                          </div>
                          <div className="font-extrabold text-amber-900">₹{v.outstanding_balance}</div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </Card>
            )}
          </div>

          {/* Meal Plans, Events Bulk Orders & Support Tickets */}
          <div className="grid gap-6 lg:grid-cols-3">
            {showSection("meal_plans") && (
              <Card className="p-5 space-y-2.5">
                <h3 className="font-bold text-slate-900 flex items-center gap-2">
                  <Utensils className="h-4 w-4 text-emerald-700" />
                  Active Meal Plans &amp; Redemptions
                </h3>
                <div className="text-xs text-slate-600">
                  Configured Plans: <strong>{data?.active_meal_plans?.plans_count || 0}</strong> • Active Student Subscriptions:{" "}
                  <strong>{data?.active_meal_plans?.active_subscriptions_count || 0}</strong>
                </div>
                <div className="space-y-1.5 max-h-52 overflow-y-auto text-xs">
                  {(data?.meal_plan_redemptions?.redemptions || []).length === 0 ? (
                    <div className="text-slate-400">No recent meal plan redemptions.</div>
                  ) : (
                    (data?.meal_plan_redemptions?.redemptions || []).map((r: any) => (
                      <div key={r.id} className="rounded-lg border border-slate-100 p-2 flex justify-between">
                        <div>
                          <div className="font-bold">{r.meal_item_name}</div>
                          <div className="font-mono text-[10px] text-slate-400">{r.redemption_number}</div>
                        </div>
                        <div className="text-right">
                          <Badge tone="green">-{r.meals_deducted} Meal</Badge>
                          <div className="text-[10px] text-slate-500">{r.remaining_meals_after} left</div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </Card>
            )}

            {showSection("events") && (
              <Card className="p-5 space-y-2.5">
                <h3 className="font-bold text-slate-900 flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-blue-700" />
                  College Event Bulk Orders ({data?.event_bulk_orders?.total_count || 0})
                </h3>
                <div className="text-xs text-slate-600">
                  Pending Approval: <strong>{data?.event_bulk_orders?.pending_approval_count || 0}</strong> • Active:{" "}
                  <strong>{data?.event_bulk_orders?.active_count || 0}</strong> • Completed:{" "}
                  <strong>{data?.event_bulk_orders?.completed_count || 0}</strong>
                </div>
                <div className="space-y-1.5 max-h-52 overflow-y-auto text-xs">
                  {(data?.event_bulk_orders?.orders || []).length === 0 ? (
                    <div className="text-slate-400">No event bulk orders yet.</div>
                  ) : (
                    (data?.event_bulk_orders?.orders || []).map((bo: any) => (
                      <div key={bo.id} className="rounded-lg border border-slate-100 p-2 flex justify-between">
                        <div>
                          <div className="font-bold">{bo.event_name}</div>
                          <div className="font-mono text-[10px] text-slate-500">
                            {bo.bulk_order_number} • {bo.total_quantity} portions
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="font-bold">₹{bo.total_amount}</div>
                          <Badge tone={bo.status === "completed" ? "green" : bo.status === "pending_approval" ? "amber" : "blue"}>
                            {bo.status}
                          </Badge>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </Card>
            )}

            {showSection("support") && (
              <Card className="p-5 space-y-2.5">
                <h3 className="font-bold text-slate-900 flex items-center gap-2">
                  <LifeBuoy className="h-4 w-4 text-[#76010d]" />
                  Support Tickets ({data?.support_tickets?.total_count || 0})
                </h3>
                <div className="text-xs text-slate-600">
                  Open: <strong>{data?.support_tickets?.open_count || 0}</strong> • In Progress:{" "}
                  <strong>{data?.support_tickets?.in_progress_count || 0}</strong> • Resolved/Closed:{" "}
                  <strong>{(data?.support_tickets?.resolved_count || 0) + (data?.support_tickets?.closed_count || 0)}</strong>
                </div>
                <div className="space-y-1.5 max-h-52 overflow-y-auto text-xs">
                  {(data?.support_tickets?.tickets || []).length === 0 ? (
                    <div className="text-slate-400">No support tickets logged.</div>
                  ) : (
                    (data?.support_tickets?.tickets || []).map((t: any) => (
                      <div key={t.id} className="rounded-lg border border-slate-100 p-2 flex justify-between">
                        <div>
                          <div className="font-bold">{t.ticket_number} — {t.subject}</div>
                          <div className="text-[10px] text-slate-500 uppercase">{t.category} • {t.priority}</div>
                        </div>
                        <Badge tone={t.status === "resolved" || t.status === "closed" ? "green" : "amber"}>
                          {t.status}
                        </Badge>
                      </div>
                    ))
                  )}
                </div>
              </Card>
            )}
          </div>
        </>
      )}
    </div>
  );
};
