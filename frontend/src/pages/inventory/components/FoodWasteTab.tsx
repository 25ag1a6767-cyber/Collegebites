import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertTriangle, Download, Lightbulb, Plus, Trash2, Utensils } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

interface FoodWasteTabProps {
  activeCanteenId: string;
  inventoryItems: any[];
  menuItems: any[];
  onChanged?: () => void;
}

export const FoodWasteTab: React.FC<FoodWasteTabProps> = ({
  activeCanteenId,
  inventoryItems,
  menuItems,
  onChanged,
}) => {
  const { pushToast } = useToast();
  const todayStr = new Date().toISOString().slice(0, 10);
  const twoWeeksAgoStr = new Date(Date.now() - 13 * 86400_000).toISOString().slice(0, 10);

  const [period, setPeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const [startDate, setStartDate] = useState(twoWeeksAgoStr);
  const [endDate, setEndDate] = useState(todayStr);
  const [lossTypeFilter, setLossTypeFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");

  // Log Prep Form
  const [prepFoodId, setPrepFoodId] = useState("");
  const [prepDate, setPrepDate] = useState(todayStr);
  const [prepSession, setPrepSession] = useState("all_day");
  const [prepQty, setPrepQty] = useState("25");
  const [prepStaffId, setPrepStaffId] = useState("");

  // Unsold / Cooked Food Waste Quick Form
  const [wastePrepLogId, setWastePrepLogId] = useState("");
  const [wasteQty, setWasteQty] = useState("1");
  const [wasteReason, setWasteReason] = useState("unsold_end_of_day");
  const [wasteStaffId, setWasteStaffId] = useState("");

  // Raw Ingredient Waste Form (with Batch, Date, Staff)
  const [ingWasteInvId, setIngWasteInvId] = useState("");
  const [ingWasteBatchId, setIngWasteBatchId] = useState("");
  const [ingWasteType, setIngWasteType] = useState<"wastage" | "damaged" | "expired">("wastage");
  const [ingWasteQty, setIngWasteQty] = useState("");
  const [ingWasteDate, setIngWasteDate] = useState(todayStr);
  const [ingWasteReason, setIngWasteReason] = useState("Prep spillage / spoiled");
  const [ingWasteStaffId, setIngWasteStaffId] = useState("");

  const activeInvItems = useMemo(() => inventoryItems.filter((it) => !it.is_archived), [inventoryItems]);
  const selectedInv = activeInvItems.find((it) => it.inventory_item_id === (ingWasteInvId || activeInvItems[0]?.inventory_item_id));
  const selectedFoodId = prepFoodId || menuItems[0]?.id || "";

  const qsWindow = `start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`;

  const { data: analytics, refetch: refetchAnalytics } = useQuery<any>({
    queryKey: ["waste-analytics", activeCanteenId, period, startDate, endDate],
    enabled: Boolean(activeCanteenId),
    queryFn: async () =>
      (await api.get(`/inventory/canteens/${activeCanteenId}/waste-analytics?period=${period}&${qsWindow}`)).data,
  });

  const { data: prepLogs = [], refetch: refetchPrepLogs } = useQuery<any[]>({
    queryKey: ["food-prep-logs", activeCanteenId, startDate, endDate],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeCanteenId}/food-prep?${qsWindow}`)).data,
  });

  const { data: wasteRecords = [], refetch: refetchWasteList } = useQuery<any[]>({
    queryKey: ["waste-records-filtered", activeCanteenId, startDate, endDate, lossTypeFilter, sourceFilter],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => {
      const p = new URLSearchParams({ start_date: startDate, end_date: endDate, limit: "100" });
      if (lossTypeFilter !== "all") p.set("loss_type", lossTypeFilter);
      if (sourceFilter !== "all") p.set("source_type", sourceFilter);
      return (await api.get(`/inventory/canteens/${activeCanteenId}/wastage?${p.toString()}`)).data;
    },
  });

  const { data: consumption, refetch: refetchConsumption } = useQuery<any>({
    queryKey: ["consumption-report", activeCanteenId, startDate, endDate],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeCanteenId}/consumption-report?${qsWindow}`)).data,
  });

  const { data: recommendations = [], refetch: refetchRecs } = useQuery<any[]>({
    queryKey: ["waste-recommendations", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeCanteenId}/waste-recommendations?lookback_days=30`)).data,
  });

  const { data: staffMembers = [] } = useQuery<any[]>({
    queryKey: ["inv-canteen-staff", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeCanteenId}/staff-members`)).data,
  });

  const refreshWasteModule = () => {
    refetchAnalytics();
    refetchPrepLogs();
    refetchWasteList();
    refetchConsumption();
    refetchRecs();
    onChanged?.();
  };

  const downloadWasteCsv = async () => {
    try {
      const res = await api.get(
        `/inventory/canteens/${activeCanteenId}/wastage/csv?period=${period}&${qsWindow}`,
        { responseType: "blob" }
      );
      const url = window.URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `collegebites-food-waste-${startDate}-to-${endDate}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
      pushToast("Downloaded Food Waste CSV report", "success");
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const summary = analytics?.summary || {};
  const trendData = analytics?.trend_series || [];
  const mostWasted = analytics?.most_wasted_items || [];
  const consumptionItems = consumption?.items || [];

  return (
    <div className="space-y-6">
      {/* Toolbar: Period + Date Filter + Export */}
      <Card className="p-4 flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-2 text-xs">
          <div>
            <label className="block font-bold text-slate-500 mb-1">Report Granularity</label>
            <div className="flex gap-1">
              {(["daily", "weekly", "monthly"] as const).map((p) => (
                <Button key={p} size="sm" variant={period === p ? "secondary" : "outline"} onClick={() => setPeriod(p)}>
                  {p.charAt(0).toUpperCase() + p.slice(1)}
                </Button>
              ))}
            </div>
          </div>
          <div>
            <label className="block font-bold text-slate-500 mb-1">From Date</label>
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-36" />
          </div>
          <div>
            <label className="block font-bold text-slate-500 mb-1">To Date</label>
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-36" />
          </div>
        </div>
        <Button size="sm" variant="outline" onClick={downloadWasteCsv}>
          <Download className="h-3.5 w-3.5" /> Export Waste CSV
        </Button>
      </Card>

      {/* Food Waste KPI Cards */}
      <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
        <Card className="p-3.5">
          <div className="text-[11px] font-bold uppercase text-slate-400">Food Prepared</div>
          <div className="text-xl font-black text-slate-900">{summary.total_food_prepared ?? 0}</div>
          <div className="text-[11px] text-slate-500">Portions logged</div>
        </Card>
        <Card className="p-3.5 border-emerald-200 bg-emerald-50/40">
          <div className="text-[11px] font-bold uppercase text-emerald-700">Food Sold</div>
          <div className="text-xl font-black text-emerald-900">{summary.total_food_sold ?? 0}</div>
          <div className="text-[11px] text-emerald-700">Confirmed orders</div>
        </Card>
        <Card className="p-3.5 border-amber-200 bg-amber-50/40">
          <div className="text-[11px] font-bold uppercase text-amber-800">Food Wasted</div>
          <div className="text-xl font-black text-amber-900">{summary.total_food_wasted ?? 0}</div>
          <div className="text-[11px] text-amber-700">Unsold portions: {summary.unsold_food_quantity ?? 0}</div>
        </Card>
        <Card className="p-3.5 border-red-200 bg-red-50/40">
          <div className="text-[11px] font-bold uppercase text-red-700">Wastage Rate</div>
          <div className="text-xl font-black text-red-900">{summary.food_wastage_percent ?? 0}%</div>
          <div className="text-[11px] text-red-700">{summary.total_waste_events ?? 0} waste events</div>
        </Card>
        <Card className="p-3.5 border-red-200 bg-red-50/40">
          <div className="text-[11px] font-bold uppercase text-red-700">Est. Waste Cost</div>
          <div className="text-xl font-black text-red-900">₹{summary.estimated_wastage_cost ?? "0.00"}</div>
          <div className="text-[11px] text-red-700">
            Food ₹{summary.prepared_food_waste_cost ?? "0.00"} • Ing ₹{summary.ingredient_waste_cost ?? "0.00"}
          </div>
        </Card>
        <Card className="p-3.5">
          <div className="text-[11px] font-bold uppercase text-slate-500">Ingredient Waste</div>
          <div className="text-xl font-black text-slate-900">{summary.ingredient_wasted_quantity ?? "0.000"}</div>
          <div className="text-[11px] text-slate-500">Damaged / expired / prep</div>
        </Card>
      </div>

      {/* Trend Charts + Most Wasted Items */}
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-bold text-slate-900">Prepared vs Sold &amp; Wastage Trend ({period})</h2>
              <p className="text-xs text-slate-500">Derived from daily food prep logs, confirmed orders, and wastage records</p>
            </div>
          </div>
          <div className="h-60 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="prepared_qty" name="Prepared" fill="#64748b" radius={[4, 4, 0, 0]} />
                <Bar dataKey="sold_qty" name="Sold" fill="#10b981" radius={[4, 4, 0, 0]} />
                <Bar dataKey="food_wasted_qty" name="Food Wasted" fill="#dc2626" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="h-44 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Line type="monotone" dataKey="estimated_loss" name="Est. Loss (₹)" stroke="#76010d" strokeWidth={2.5} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-600" /> Most Wasted Items
          </h2>
          <div className="space-y-2 max-h-[380px] overflow-y-auto text-xs">
            {mostWasted.length === 0 ? (
              <div className="text-slate-500">No wastage logged in the selected date window.</div>
            ) : (
              mostWasted.map((m: any, idx: number) => (
                <div key={`${m.item_name}-${idx}`} className="rounded-xl border border-red-100 bg-red-50/40 p-2.5">
                  <div className="flex items-center justify-between font-bold text-red-900">
                    <span>
                      #{idx + 1} {m.item_name}
                    </span>
                    <span>₹{m.estimated_loss}</span>
                  </div>
                  <div className="text-[11px] text-red-800 flex justify-between mt-0.5">
                    <span>
                      {m.total_quantity} {m.unit} ({m.waste_count}x)
                    </span>
                    <Badge tone={m.source_type === "prepared_food" ? "amber" : "red"}>
                      {m.source_type === "prepared_food" ? "Dish" : "Ingredient"}
                    </Badge>
                  </div>
                  {m.top_reason && <div className="text-[10px] text-slate-600 mt-0.5">Top reason: {m.top_reason}</div>}
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Recommendations + Daily Food Prep & Unsold Waste */}
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-amber-600" /> Historical Waste Reduction Insights
          </h2>
          <div className="space-y-2 max-h-72 overflow-y-auto text-xs">
            {recommendations.length === 0 ? (
              <div className="text-slate-500">
                No chronic over-preparation or near-expiry excess detected over the last 30 days.
              </div>
            ) : (
              recommendations.map((rec: any) => (
                <div key={rec.id} className="rounded-xl border border-amber-200 bg-amber-50/50 p-3 space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold text-amber-950">{rec.title}</span>
                    <Badge tone={rec.severity === "high" ? "red" : "amber"}>{rec.severity}</Badge>
                  </div>
                  <p className="text-[11px] text-amber-900">{rec.detail}</p>
                  {Number(rec.potential_savings) > 0 && (
                    <div className="text-[10px] font-bold text-emerald-700">
                      Est. preventable loss: ₹{rec.potential_savings}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </Card>

        <Card className="p-5 lg:col-span-2 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-bold text-slate-900 flex items-center gap-2">
              <Utensils className="h-4 w-4 text-[#76010d]" /> Prepared vs Sold Quantity &amp; Unsold Food Waste
            </h2>
          </div>

          <div className="grid gap-2 md:grid-cols-6 text-xs">
            <Select value={selectedFoodId} onChange={(e) => setPrepFoodId(e.target.value)} className="md:col-span-2">
              {menuItems.map((fi) => (
                <option key={fi.id} value={fi.id}>
                  {fi.name}
                </option>
              ))}
            </Select>
            <Input type="date" value={prepDate} onChange={(e) => setPrepDate(e.target.value)} />
            <Select value={prepSession} onChange={(e) => setPrepSession(e.target.value)}>
              <option value="all_day">All Day</option>
              <option value="breakfast">Breakfast</option>
              <option value="lunch">Lunch</option>
              <option value="evening">Evening</option>
              <option value="dinner">Dinner</option>
            </Select>
            <Input type="number" min="0" value={prepQty} onChange={(e) => setPrepQty(e.target.value)} placeholder="Prepared qty" />
            <Button
              size="sm"
              variant="primary"
              disabled={!selectedFoodId}
              onClick={async () => {
                try {
                  await api.post("/inventory/food-prep", {
                    canteen_id: activeCanteenId,
                    food_item_id: selectedFoodId,
                    prep_date: prepDate,
                    meal_session: prepSession,
                    prepared_quantity: Number(prepQty || 0),
                    responsible_staff_id: prepStaffId || null,
                  });
                  pushToast("Daily prepared quantity saved", "success");
                  refreshWasteModule();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Save Prep
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Select value={prepStaffId} onChange={(e) => setPrepStaffId(e.target.value)} className="w-60">
              <option value="">Chef / Staff in Charge (Optional)</option>
              {staffMembers.map((st: any) => (
                <option key={st.user_id} value={st.user_id}>
                  {st.full_name} ({st.designation})
                </option>
              ))}
            </Select>
          </div>

          <div className="overflow-x-auto max-h-60 overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-[11px] uppercase text-slate-400">
                  <th className="py-1.5">Date</th>
                  <th>Dish</th>
                  <th>Session</th>
                  <th>Prepared</th>
                  <th>Sold</th>
                  <th>Unsold</th>
                  <th>Wasted</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {prepLogs.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-4 text-center text-slate-500">
                      No daily prepared batches logged yet in this window.
                    </td>
                  </tr>
                ) : (
                  prepLogs.map((log: any) => (
                    <tr key={log.id} className="border-b border-slate-100">
                      <td className="py-2">{log.prep_date}</td>
                      <td className="font-bold text-slate-900">{log.food_item_name}</td>
                      <td className="uppercase text-[10px]">{log.meal_session}</td>
                      <td>{log.prepared_quantity}</td>
                      <td className="text-emerald-700 font-bold">{log.sold_quantity}</td>
                      <td className="text-amber-700 font-bold">{log.unsold_quantity}</td>
                      <td className="text-red-700 font-bold">
                        {log.unsold_wasted_quantity} (₹{log.estimated_waste_cost})
                      </td>
                      <td>
                        {log.remaining_unlogged_unsold > 0 ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setWastePrepLogId(log.id);
                              setWasteQty(String(log.remaining_unlogged_unsold));
                            }}
                          >
                            Log Unsold ({log.remaining_unlogged_unsold})
                          </Button>
                        ) : (
                          <span className="text-[11px] text-slate-400">Balanced</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {wastePrepLogId && (
            <div className="rounded-xl border border-red-200 bg-red-50/50 p-3 flex flex-wrap items-center gap-2 text-xs">
              <span className="font-bold text-red-900">Record Unsold Dish Waste:</span>
              <Input type="number" min="1" value={wasteQty} onChange={(e) => setWasteQty(e.target.value)} className="w-20" />
              <Input value={wasteReason} onChange={(e) => setWasteReason(e.target.value)} placeholder="Waste reason" className="w-48" />
              <Select value={wasteStaffId} onChange={(e) => setWasteStaffId(e.target.value)} className="w-48">
                <option value="">Responsible Staff</option>
                {staffMembers.map((st: any) => (
                  <option key={st.user_id} value={st.user_id}>
                    {st.full_name}
                  </option>
                ))}
              </Select>
              <Button
                size="sm"
                variant="danger"
                onClick={async () => {
                  try {
                    await api.post(`/inventory/food-prep/${wastePrepLogId}/record-waste`, {
                      quantity: Number(wasteQty),
                      reason: wasteReason,
                      loss_type: "unsold",
                      responsible_staff_id: wasteStaffId || null,
                    });
                    setWastePrepLogId("");
                    pushToast("Unsold food waste recorded", "success");
                    refreshWasteModule();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Confirm Waste
              </Button>
              <Button size="sm" variant="outline" onClick={() => setWastePrepLogId("")}>
                Cancel
              </Button>
            </div>
          )}
        </Card>
      </div>

      {/* Raw Ingredient Wastage Form (Batch, Date, Responsible Staff) + Detailed Log */}
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <Trash2 className="h-4 w-4 text-red-600" /> Record Ingredient Wastage
          </h2>
          <Select
            value={ingWasteInvId || activeInvItems[0]?.inventory_item_id || ""}
            onChange={(e) => {
              setIngWasteInvId(e.target.value);
              setIngWasteBatchId("");
            }}
          >
            {activeInvItems.map((it) => (
              <option key={it.inventory_item_id} value={it.inventory_item_id}>
                {it.name} ({it.current_quantity} {it.unit})
              </option>
            ))}
          </Select>
          {selectedInv?.batches?.length > 0 && (
            <Select value={ingWasteBatchId} onChange={(e) => setIngWasteBatchId(e.target.value)}>
              <option value="">Auto-deduct via FEFO batch order</option>
              {selectedInv.batches.map((b: any) => (
                <option key={b.id} value={b.id}>
                  Batch {b.batch_number} ({b.remaining_quantity} {selectedInv.unit} • exp {b.expiry_date || "None"})
                </option>
              ))}
            </Select>
          )}
          <div className="grid grid-cols-2 gap-2">
            <Select value={ingWasteType} onChange={(e) => setIngWasteType(e.target.value as any)}>
              <option value="wastage">Prep / Spillage Wastage</option>
              <option value="expired">Expired Batch Write-off</option>
              <option value="damaged">Damaged Goods Loss</option>
            </Select>
            <Input type="date" value={ingWasteDate} onChange={(e) => setIngWasteDate(e.target.value)} />
          </div>
          <Input
            type="number"
            min="0.001"
            step="0.01"
            value={ingWasteQty}
            onChange={(e) => setIngWasteQty(e.target.value)}
            placeholder={`Waste quantity (${selectedInv?.unit || "units"})`}
          />
          <Select value={ingWasteStaffId} onChange={(e) => setIngWasteStaffId(e.target.value)}>
            <option value="">Responsible Staff Member (Optional)</option>
            {staffMembers.map((st: any) => (
              <option key={st.user_id} value={st.user_id}>
                {st.full_name} ({st.designation})
              </option>
            ))}
          </Select>
          <Input value={ingWasteReason} onChange={(e) => setIngWasteReason(e.target.value)} placeholder="Waste reason" />
          <Button
            size="sm"
            variant="danger"
            disabled={!selectedInv || !ingWasteQty}
            onClick={async () => {
              if (!selectedInv) return;
              try {
                await api.post("/inventory/wastage", {
                  inventory_item_id: selectedInv.inventory_item_id,
                  batch_id: ingWasteBatchId || null,
                  quantity: Math.abs(Number(ingWasteQty)),
                  operation_type: ingWasteType,
                  waste_date: ingWasteDate,
                  reason: ingWasteReason,
                  responsible_staff_id: ingWasteStaffId || null,
                });
                setIngWasteQty("");
                pushToast("Ingredient wastage logged and stock updated", "success");
                refreshWasteModule();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Record Ingredient Waste
          </Button>
        </Card>

        <Card className="p-5 lg:col-span-2 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-bold text-slate-900">Wastage Ledger ({wasteRecords.length})</h2>
            <div className="flex gap-2 text-xs">
              <Select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} className="w-36">
                <option value="all">All Sources</option>
                <option value="prepared_food">Prepared Food</option>
                <option value="ingredient">Raw Ingredients</option>
              </Select>
              <Select value={lossTypeFilter} onChange={(e) => setLossTypeFilter(e.target.value)} className="w-36">
                <option value="all">All Loss Types</option>
                <option value="unsold">Unsold</option>
                <option value="wastage">Prep/Spillage</option>
                <option value="expired">Expired</option>
                <option value="damaged">Damaged</option>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5 max-h-72 overflow-y-auto text-xs">
            {wasteRecords.length === 0 ? (
              <div className="text-slate-500">No wastage entries match the active filters.</div>
            ) : (
              wasteRecords.map((w: any) => (
                <div key={w.id} className="rounded-lg border border-red-100 bg-red-50/40 px-3 py-2">
                  <div className="flex justify-between font-bold text-red-900">
                    <span>
                      {w.food_item_name || w.ingredient_name || w.item_name} • {String(w.loss_type).toUpperCase()}
                    </span>
                    <span>
                      -₹{w.estimated_loss} ({w.quantity} {w.unit})
                    </span>
                  </div>
                  <div className="text-[11px] text-red-800 flex flex-wrap justify-between gap-2">
                    <span>Reason: {w.reason}</span>
                    <span>
                      Date: {w.waste_date || w.created_at?.slice(0, 10)}
                      {w.responsible_staff_name ? ` • Staff: ${w.responsible_staff_name}` : ""}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Inventory Consumption vs Theoretical Recipe Report */}
      <Card className="p-5 space-y-3">
        <div>
          <h2 className="font-bold text-slate-900">Inventory Consumption &amp; Recipe Variance Report</h2>
          <p className="text-xs text-slate-500">
            Compares real stock deducted &amp; wasted against theoretical recipe usage from confirmed orders ({startDate} to {endDate})
          </p>
        </div>
        <div className="overflow-x-auto max-h-72 overflow-y-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-left text-[11px] uppercase text-slate-400">
                <th className="py-1.5">Ingredient</th>
                <th>Stocked In</th>
                <th>Order Deducted</th>
                <th>Wasted</th>
                <th>Theoretical Recipe</th>
                <th>Actual Consumed</th>
                <th>Variance</th>
                <th>Waste Cost</th>
              </tr>
            </thead>
            <tbody>
              {consumptionItems.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-4 text-center text-slate-500">
                    No inventory items found for this canteen.
                  </td>
                </tr>
              ) : (
                consumptionItems.map((c: any) => (
                  <tr key={c.inventory_item_id} className="border-b border-slate-100">
                    <td className="py-2 font-bold text-slate-900">
                      {c.ingredient_name} <span className="font-normal text-slate-400">({c.unit})</span>
                    </td>
                    <td className="text-emerald-700">+{c.stocked_in}</td>
                    <td>{c.order_deducted}</td>
                    <td className="text-red-700 font-semibold">{c.wasted}</td>
                    <td>{c.theoretical_recipe_consumption}</td>
                    <td className="font-semibold">{c.actual_consumed}</td>
                    <td className={Number(c.variance_quantity) > 0 ? "text-amber-700 font-bold" : "text-slate-600"}>
                      {c.variance_quantity}
                    </td>
                    <td className="font-bold text-red-800">₹{c.estimated_waste_cost}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};
