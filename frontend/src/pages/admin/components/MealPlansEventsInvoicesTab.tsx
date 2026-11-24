import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Calendar,
  CheckCircle2,
  Download,
  FileText,
  QrCode,
  Utensils,
} from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

interface MealPlansEventsInvoicesTabProps {
  activeCanteenId: string;
  menuItems: any[];
  downloadBlob: (url: string, filename: string) => Promise<void>;
}

export const MealPlansEventsInvoicesTab: React.FC<MealPlansEventsInvoicesTabProps> = ({
  activeCanteenId,
  menuItems,
  downloadBlob,
}) => {
  const { pushToast } = useToast();
  const [subTab, setSubTab] = useState<"meal_plans" | "events" | "invoices">("meal_plans");

  // Meal Plan creation state
  const [mpName, setMpName] = useState("");
  const [mpCode, setMpCode] = useState("");
  const [mpType, setMpType] = useState("monthly");
  const [mpPrice, setMpPrice] = useState("1200.00");
  const [mpDays, setMpDays] = useState("30");
  const [mpMeals, setMpMeals] = useState("30");
  const [mpDesc, setMpDesc] = useState("");

  // Meal Plan Staff Redemption state
  const [redeemCode, setRedeemCode] = useState("");
  const [redeemFoodId, setRedeemFoodId] = useState("");
  const [redeemMealsCount, setRedeemMealsCount] = useState("1");
  const [lastRedemptionResult, setLastRedemptionResult] = useState<any | null>(null);

  // College Event creation state
  const [evName, setEvName] = useState("");
  const [evDept, setEvDept] = useState("");
  const [evOrgName, setEvOrgName] = useState("");
  const [evPhone, setEvPhone] = useState("");
  const [evEmail, setEvEmail] = useState("");
  const [evDate, setEvDate] = useState("");
  const [evDeadline, setEvDeadline] = useState("");
  const [evLocation, setEvLocation] = useState("");
  const [evMinQty, setEvMinQty] = useState("10");
  const [evMaxQty, setEvMaxQty] = useState("300");
  const [evDesc, setEvDesc] = useState("");

  const { data: mealPlans = [], refetch: refetchMealPlans } = useQuery<any[]>({
    queryKey: ["admin-meal-plans", activeCanteenId],
    enabled: subTab === "meal_plans",
    queryFn: async () =>
      (await api.get(`/meal-plans?include_inactive=true${activeCanteenId ? `&canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: mealSubscriptions = [], refetch: refetchMealSubs } = useQuery<any[]>({
    queryKey: ["admin-meal-subs", activeCanteenId],
    enabled: subTab === "meal_plans",
    queryFn: async () =>
      (await api.get(`/meal-plans/subscriptions${activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: events = [], refetch: refetchEvents } = useQuery<any[]>({
    queryKey: ["admin-events", activeCanteenId],
    enabled: subTab === "events",
    queryFn: async () =>
      (await api.get(`/events?include_inactive=true${activeCanteenId ? `&canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: bulkOrders = [], refetch: refetchBulkOrders } = useQuery<any[]>({
    queryKey: ["admin-bulk-orders", activeCanteenId],
    enabled: subTab === "events",
    queryFn: async () =>
      (await api.get(`/events/bulk-orders${activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: eventsReport, refetch: refetchEventsReport } = useQuery<any>({
    queryKey: ["admin-events-report", activeCanteenId],
    enabled: subTab === "events",
    queryFn: async () =>
      (await api.get(`/events/reports/summary${activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: invoices = [] } = useQuery<any[]>({
    queryKey: ["admin-invoices", activeCanteenId],
    enabled: subTab === "invoices",
    queryFn: async () =>
      (await api.get(`/invoices${activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant={subTab === "meal_plans" ? "primary" : "outline"}
          onClick={() => setSubTab("meal_plans")}
        >
          <Utensils className="h-3.5 w-3.5" /> Student Meal Plans &amp; QR Redemption
        </Button>
        <Button
          size="sm"
          variant={subTab === "events" ? "primary" : "outline"}
          onClick={() => setSubTab("events")}
        >
          <Calendar className="h-3.5 w-3.5" /> College Events &amp; Bulk Ordering
        </Button>
        <Button
          size="sm"
          variant={subTab === "invoices" ? "primary" : "outline"}
          onClick={() => setSubTab("invoices")}
        >
          <FileText className="h-3.5 w-3.5" /> Tax Invoices &amp; Billing Ledger
        </Button>
      </div>

      {subTab === "meal_plans" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="p-5 space-y-3">
            <h3 className="font-bold text-slate-900">Create Student Meal Plan</h3>
            <div className="space-y-2 text-xs">
              <Input value={mpName} onChange={(e) => setMpName(e.target.value)} placeholder="Plan Name (e.g. Monthly 30-Meal Thali Plan) *" />
              <div className="grid grid-cols-2 gap-2">
                <Input value={mpCode} onChange={(e) => setMpCode(e.target.value)} placeholder="Code (optional)" />
                <Select value={mpType} onChange={(e) => setMpType(e.target.value)}>
                  <option value="daily">Daily Plan</option>
                  <option value="weekly">Weekly Plan</option>
                  <option value="monthly">Monthly Plan</option>
                  <option value="custom">Custom Plan</option>
                </Select>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="font-bold text-slate-600 block mb-1">Price ₹</label>
                  <Input type="number" min="1" step="0.01" value={mpPrice} onChange={(e) => setMpPrice(e.target.value)} />
                </div>
                <div>
                  <label className="font-bold text-slate-600 block mb-1">Total Meals</label>
                  <Input type="number" min="1" value={mpMeals} onChange={(e) => setMpMeals(e.target.value)} />
                </div>
                <div>
                  <label className="font-bold text-slate-600 block mb-1">Validity Days</label>
                  <Input type="number" min="1" value={mpDays} onChange={(e) => setMpDays(e.target.value)} />
                </div>
              </div>
              <Input value={mpDesc} onChange={(e) => setMpDesc(e.target.value)} placeholder="Description / Eligible meal details" />
              <Button
                className="w-full"
                disabled={!mpName.trim() || !mpPrice}
                onClick={async () => {
                  try {
                    await api.post("/meal-plans", {
                      canteen_id: activeCanteenId || null,
                      code: mpCode.trim() || null,
                      name: mpName.trim(),
                      description: mpDesc.trim() || null,
                      plan_type: mpType,
                      price: mpPrice,
                      validity_days: Number(mpDays) || 30,
                      total_meals: Number(mpMeals) || 30,
                    });
                    setMpName("");
                    setMpCode("");
                    setMpDesc("");
                    pushToast("Student meal plan published", "success");
                    refetchMealPlans();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Publish Meal Plan
              </Button>
            </div>

            {/* Staff Meal Redemption Scanner / Verifier */}
            <div className="border-t border-slate-200 pt-4 space-y-2 text-xs">
              <div className="font-extrabold uppercase text-emerald-800 flex items-center gap-1.5">
                <QrCode className="h-4 w-4" /> Staff Meal Plan QR / Code Redemption
              </div>
              <Input
                value={redeemCode}
                onChange={(e) => setRedeemCode(e.target.value)}
                placeholder="Scan QR payload or enter CBMP-... code"
              />
              <div className="grid grid-cols-2 gap-2">
                <Select value={redeemFoodId} onChange={(e) => setRedeemFoodId(e.target.value)}>
                  <option value="">Standard Plan Meal</option>
                  {menuItems.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </Select>
                <Input
                  type="number"
                  min="1"
                  max="10"
                  value={redeemMealsCount}
                  onChange={(e) => setRedeemMealsCount(e.target.value)}
                  placeholder="Meals to deduct"
                />
              </div>
              <Button
                className="w-full"
                variant="success"
                disabled={!redeemCode.trim() || !activeCanteenId}
                onClick={async () => {
                  try {
                    const res = await api.post("/meal-plans/redeem", {
                      canteen_id: activeCanteenId,
                      qr_payload: redeemCode.trim(),
                      redemption_code: redeemCode.trim(),
                      food_item_id: redeemFoodId || null,
                      meals_to_deduct: Number(redeemMealsCount) || 1,
                    });
                    setLastRedemptionResult(res.data);
                    setRedeemCode("");
                    pushToast(`Meal redeemed! ${res.data.remaining_meals_after} meals remaining`, "success");
                    refetchMealSubs();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                <CheckCircle2 className="h-3.5 w-3.5" /> Verify &amp; Deduct Meal
              </Button>
              {lastRedemptionResult && (
                <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-2.5 text-emerald-950">
                  <div className="font-bold">Redeemed: {lastRedemptionResult.redemption_number}</div>
                  <div>Student: {lastRedemptionResult.subscription?.student_name}</div>
                  <div>Remaining Balance: <strong>{lastRedemptionResult.remaining_meals_after} meals</strong></div>
                </div>
              )}
            </div>
          </Card>

          <Card className="p-5 lg:col-span-2 space-y-4">
            <div>
              <h3 className="font-bold text-slate-900 mb-2">Configured Meal Plans ({mealPlans.length})</h3>
              <div className="grid gap-2 sm:grid-cols-2 text-xs">
                {mealPlans.map((p) => (
                  <div key={p.id} className="rounded-xl border border-slate-200 p-3 flex justify-between items-start">
                    <div>
                      <div className="font-bold text-slate-900">{p.name}</div>
                      <div className="text-[11px] text-slate-500">
                        {p.code} • {p.plan_type.toUpperCase()} • {p.total_meals} Meals • {p.validity_days} Days
                      </div>
                      <div className="font-extrabold text-[#76010d] mt-1">₹{p.price}</div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        try {
                          await api.patch(`/meal-plans/${p.id}`, { is_active: !p.is_active });
                          refetchMealPlans();
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      {p.is_active ? "Active" : "Disabled"}
                    </Button>
                  </div>
                ))}
              </div>
            </div>

            <div className="border-t border-slate-100 pt-3">
              <h3 className="font-bold text-slate-900 mb-2">Student Subscriptions ({mealSubscriptions.length})</h3>
              <div className="overflow-x-auto max-h-72">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-left text-slate-500">
                    <tr>
                      <th className="p-2">Sub #</th>
                      <th className="p-2">Student</th>
                      <th className="p-2">Plan</th>
                      <th className="p-2">Remaining / Total</th>
                      <th className="p-2">Redemption Code</th>
                      <th className="p-2">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {mealSubscriptions.map((s) => (
                      <tr key={s.id}>
                        <td className="p-2 font-mono font-bold">{s.subscription_number}</td>
                        <td className="p-2">{s.student_name}</td>
                        <td className="p-2">{s.meal_plan_name}</td>
                        <td className="p-2 font-extrabold">{s.remaining_meals} / {s.total_meals}</td>
                        <td className="p-2 font-mono text-emerald-800">{s.redemption_code || "Pending Payment"}</td>
                        <td className="p-2">
                          <Badge tone={s.status === "active" ? "green" : s.status === "exhausted" ? "blue" : "amber"}>
                            {s.status}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </Card>
        </div>
      )}

      {subTab === "events" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="p-5 space-y-3">
            <h3 className="font-bold text-slate-900">Create College Event</h3>
            <div className="space-y-2 text-xs">
              <Input value={evName} onChange={(e) => setEvName(e.target.value)} placeholder="Event Name (e.g. TechFest 2026) *" />
              <Input value={evDept} onChange={(e) => setEvDept(e.target.value)} placeholder="Department / Club *" />
              <div className="grid grid-cols-2 gap-2">
                <Input value={evOrgName} onChange={(e) => setEvOrgName(e.target.value)} placeholder="Organizer Name *" />
                <Input value={evPhone} onChange={(e) => setEvPhone(e.target.value)} placeholder="Contact Phone *" />
              </div>
              <Input value={evEmail} onChange={(e) => setEvEmail(e.target.value)} placeholder="Organizer Email" />
              <Input value={evLocation} onChange={(e) => setEvLocation(e.target.value)} placeholder="Campus Venue / Auditorium *" />
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="font-bold text-slate-600 block mb-1">Event Date *</label>
                  <Input type="date" value={evDate} onChange={(e) => setEvDate(e.target.value)} />
                </div>
                <div>
                  <label className="font-bold text-slate-600 block mb-1">Ordering Deadline *</label>
                  <Input type="datetime-local" value={evDeadline} onChange={(e) => setEvDeadline(e.target.value)} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="font-bold text-slate-600 block mb-1">Min Bulk Qty</label>
                  <Input type="number" min="1" value={evMinQty} onChange={(e) => setEvMinQty(e.target.value)} />
                </div>
                <div>
                  <label className="font-bold text-slate-600 block mb-1">Max Bulk Qty</label>
                  <Input type="number" min="1" value={evMaxQty} onChange={(e) => setEvMaxQty(e.target.value)} />
                </div>
              </div>
              <Input value={evDesc} onChange={(e) => setEvDesc(e.target.value)} placeholder="Event catering notes..." />
              <Button
                className="w-full"
                disabled={!evName.trim() || !evDept.trim() || !evOrgName.trim() || !evPhone.trim() || !evDate || !evDeadline || !evLocation.trim()}
                onClick={async () => {
                  try {
                    await api.post("/events", {
                      canteen_id: activeCanteenId,
                      name: evName.trim(),
                      department: evDept.trim(),
                      organizer_name: evOrgName.trim(),
                      contact_phone: evPhone.trim(),
                      contact_email: evEmail.trim() || null,
                      event_date: evDate,
                      location: evLocation.trim(),
                      description: evDesc.trim() || null,
                      ordering_deadline: new Date(evDeadline).toISOString(),
                      min_order_quantity: Number(evMinQty) || 5,
                      max_order_quantity: Number(evMaxQty) || 500,
                    });
                    setEvName("");
                    setEvDept("");
                    setEvLocation("");
                    pushToast("College event created for bulk ordering", "success");
                    refetchEvents();
                    refetchEventsReport();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Create College Event
              </Button>
            </div>
          </Card>

          <Card className="p-5 lg:col-span-2 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="font-bold text-slate-900">Event Bulk Orders &amp; Reports ({bulkOrders.length})</h3>
                {eventsReport && (
                  <p className="text-xs text-slate-500">
                    Confirmed Event Revenue: <strong>₹{eventsReport.total_event_revenue}</strong> • Pending: {eventsReport.pending_event_orders} • Completed: {eventsReport.completed_event_orders}
                  </p>
                )}
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  downloadBlob(
                    `/events/reports/csv${activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`,
                    "collegebites-events-report.csv"
                  )
                }
              >
                <Download className="h-3.5 w-3.5" /> Export Events CSV
              </Button>
            </div>

            <div className="space-y-2.5 max-h-96 overflow-y-auto text-xs">
              {bulkOrders.length === 0 ? (
                <div className="text-slate-500">No event bulk orders submitted yet.</div>
              ) : (
                bulkOrders.map((bo) => (
                  <div key={bo.id} className="rounded-xl border border-slate-200 p-3 space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="font-bold text-slate-900">
                          {bo.bulk_order_number} — {bo.event_name} ({bo.department})
                        </div>
                        <div className="text-[11px] text-slate-500">
                          Organizer: {bo.organizer_name} • Total Qty: <strong>{bo.total_quantity}</strong> • Total: <strong>₹{bo.total_amount}</strong> • Payment: {bo.payment_status}
                        </div>
                        {bo.group_pickup_token && (
                          <div className="text-[11px] font-mono text-emerald-800">
                            Pickup Token: {bo.group_pickup_token} ({bo.pickup_arrangement})
                          </div>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge tone={bo.status === "completed" ? "green" : bo.status === "rejected" ? "red" : "amber"}>
                          {bo.status.toUpperCase()}
                        </Badge>
                        {bo.status === "pending_approval" && (
                          <>
                            <Button
                              size="sm"
                              variant="success"
                              onClick={async () => {
                                try {
                                  await api.post(`/events/bulk-orders/${bo.id}/review`, { decision: "approve" });
                                  pushToast("Bulk order approved", "success");
                                  refetchBulkOrders();
                                  refetchEventsReport();
                                } catch (err) {
                                  pushToast(getApiError(err), "error");
                                }
                              }}
                            >
                              Approve
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              onClick={async () => {
                                try {
                                  await api.post(`/events/bulk-orders/${bo.id}/review`, {
                                    decision: "reject",
                                    rejection_reason: "Kitchen capacity full for requested slot",
                                  });
                                  pushToast("Bulk order rejected", "info");
                                  refetchBulkOrders();
                                } catch (err) {
                                  pushToast(getApiError(err), "error");
                                }
                              }}
                            >
                              Reject
                            </Button>
                          </>
                        )}
                        {bo.payment_status === "CONFIRMED" && bo.status === "approved" && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={async () => {
                              await api.post(`/events/bulk-orders/${bo.id}/status`, { status: "preparing" });
                              refetchBulkOrders();
                            }}
                          >
                            Start Prep
                          </Button>
                        )}
                        {bo.status === "preparing" && (
                          <Button
                            size="sm"
                            variant="success"
                            onClick={async () => {
                              await api.post(`/events/bulk-orders/${bo.id}/status`, { status: "ready" });
                              refetchBulkOrders();
                            }}
                          >
                            Mark Ready
                          </Button>
                        )}
                        {bo.status === "ready" && (
                          <Button
                            size="sm"
                            variant="primary"
                            onClick={async () => {
                              await api.post(`/events/bulk-orders/${bo.id}/status`, { status: "completed" });
                              refetchBulkOrders();
                              refetchEventsReport();
                            }}
                          >
                            Complete Handover
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>
      )}

      {subTab === "invoices" && (
        <Card className="p-5 space-y-3">
          <h3 className="font-bold text-slate-900">Verified Tax Invoices Ledger ({invoices.length})</h3>
          <div className="overflow-x-auto max-h-96">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="p-2">Invoice #</th>
                  <th className="p-2">Type</th>
                  <th className="p-2">Reference #</th>
                  <th className="p-2">Customer</th>
                  <th className="p-2">Subtotal</th>
                  <th className="p-2">Tax Status / Historical Tax</th>
                  <th className="p-2">Total Paid</th>
                  <th className="p-2">PDF</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {invoices.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="p-4 text-center text-slate-500">
                      No tax invoices issued yet. Invoices are generated automatically upon verified payment.
                    </td>
                  </tr>
                ) : (
                  invoices.map((inv) => (
                    <tr key={inv.id}>
                      <td className="p-2 font-mono font-bold text-slate-900">{inv.invoice_number}</td>
                      <td className="p-2 uppercase">{inv.invoice_type}</td>
                      <td className="p-2 font-mono">{inv.reference_number}</td>
                      <td className="p-2">{inv.customer_name}</td>
                      <td className="p-2">
                        ₹{inv.subtotal_amount} {Number(inv.discount_amount) > 0 ? `(-₹${inv.discount_amount})` : ""}
                      </td>
                      <td className="p-2">
                        {Number(inv.tax_amount) > 0 ? `₹${inv.tax_amount}` : "Included in listed price"}
                      </td>
                      <td className="p-2 font-extrabold text-slate-900">₹{inv.total_amount}</td>
                      <td className="p-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => downloadBlob(`/invoices/${inv.invoice_number}/pdf`, `${inv.invoice_number}.pdf`)}
                        >
                          <Download className="h-3 w-3" /> PDF
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
};
