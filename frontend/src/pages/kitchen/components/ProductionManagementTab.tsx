import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList, Flame, Layers, Plus } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

interface Props {
  activeCanteenId: string;
}

const NEXT_STAGE_MAP: Record<string, { target: string; label: string }> = {
  planned: { target: "ingredients_allocated", label: "Allocate Ingredients (FEFO)" },
  ingredients_allocated: { target: "ready_for_preparation", label: "Mark Ready for Prep" },
  ready_for_preparation: { target: "preparing", label: "Start Preparing" },
  preparing: { target: "prepared", label: "Mark Prepared" },
  prepared: { target: "quality_checked", label: "Confirm QC Passed" },
  quality_checked: { target: "completed", label: "Complete Batch" },
};

export const ProductionManagementTab: React.FC<Props> = ({ activeCanteenId }) => {
  const { pushToast } = useToast();
  const [subTab, setSubTab] = useState<"planning" | "batches" | "grouped_kds" | "report">("planning");
  const [newFoodId, setNewFoodId] = useState("");
  const [newQty, setNewQty] = useState("20");
  const [newStrat, setNewStrat] = useState("FEFO");
  const [busy, setBusy] = useState(false);

  const { data: planning, refetch: refetchPlanning } = useQuery<any>({
    queryKey: ["prod-planning", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/production/planning?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: batches = [], refetch: refetchBatches } = useQuery<any[]>({
    queryKey: ["prod-batches", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/production/batches?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: groupedKds = [], refetch: refetchGrouped } = useQuery<any[]>({
    queryKey: ["kds-grouped", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "grouped_kds"),
    queryFn: async () => (await api.get(`/kitchen/canteens/${activeCanteenId}/grouped-items`)).data,
    refetchInterval: 8000,
  });

  const { data: report } = useQuery<any>({
    queryKey: ["prod-report", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "report"),
    queryFn: async () => (await api.get(`/production/report?canteen_id=${activeCanteenId}`)).data,
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={subTab === "planning" ? "secondary" : "outline"} onClick={() => setSubTab("planning")}>
          <ClipboardList className="h-3.5 w-3.5" /> Production Planning
        </Button>
        <Button size="sm" variant={subTab === "batches" ? "secondary" : "outline"} onClick={() => setSubTab("batches")}>
          <Flame className="h-3.5 w-3.5" /> Production Batches ({batches.length})
        </Button>
        <Button size="sm" variant={subTab === "grouped_kds" ? "secondary" : "outline"} onClick={() => setSubTab("grouped_kds")}>
          <Layers className="h-3.5 w-3.5" /> Item-Grouped KDS ({groupedKds.length})
        </Button>
        <Button size="sm" variant={subTab === "report" ? "secondary" : "outline"} onClick={() => setSubTab("report")}>
          Production Report
        </Button>
      </div>

      {subTab === "planning" && planning && (
        <div className="space-y-3">
          <Card className="p-3 border-blue-200 bg-blue-50/50 text-xs text-blue-900">
            <strong>No Double-Counting Guarantee:</strong> {planning.double_counting_guard}
          </Card>

          <Card className="p-4 flex flex-wrap items-end gap-2">
            <div className="flex-1 min-w-[200px]">
              <div className="text-[11px] font-bold text-slate-600 mb-1">Create Production Batch</div>
              <Select value={newFoodId} onChange={(e) => setNewFoodId(e.target.value)}>
                <option value="">Select Menu Dish...</option>
                {(planning.items || []).map((it: any) => (
                  <option key={it.food_item_id} value={it.food_item_id}>
                    {it.food_item_name} {it.has_verified_recipe ? "✓ Verified Recipe" : "(Unverified Recipe)"}
                  </option>
                ))}
              </Select>
            </div>
            <div className="w-28">
              <div className="text-[11px] font-bold text-slate-600 mb-1">Planned Qty</div>
              <Input type="number" min={1} value={newQty} onChange={(e) => setNewQty(e.target.value)} />
            </div>
            <div className="w-28">
              <div className="text-[11px] font-bold text-slate-600 mb-1">Strategy</div>
              <Select value={newStrat} onChange={(e) => setNewStrat(e.target.value)}>
                <option value="FEFO">FEFO</option>
                <option value="FIFO">FIFO</option>
              </Select>
            </div>
            <Button
              size="sm"
              variant="primary"
              disabled={busy || !newFoodId || Number(newQty) < 1}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.post("/production/batches", {
                    canteen_id: activeCanteenId,
                    food_item_id: newFoodId,
                    planned_quantity: Number(newQty),
                    allocation_strategy: newStrat,
                  });
                  pushToast("Production batch planned", "success");
                  refetchBatches();
                  refetchPlanning();
                  setSubTab("batches");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Plan Batch
            </Button>
          </Card>

          <Card className="p-4 overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="border-b border-slate-200 text-slate-500 uppercase">
                <tr>
                  <th className="py-2 pr-3">Food Item</th>
                  <th className="py-2 pr-3">Recipe</th>
                  <th className="py-2 pr-3">Confirmed Active</th>
                  <th className="py-2 pr-3">Event Bulk</th>
                  <th className="py-2 pr-3">Planned Batches</th>
                  <th className="py-2 pr-3">AI Forecast</th>
                  <th className="py-2">Suggested Add&apos;l Prep</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(planning.items || []).map((it: any) => (
                  <tr key={it.food_item_id}>
                    <td className="py-2 pr-3 font-bold text-slate-900">{it.food_item_name}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={it.has_verified_recipe ? "green" : "slate"}>
                        {it.has_verified_recipe ? "Verified" : "Unverified"}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 font-mono">{it.confirmed_active_orders_qty}</td>
                    <td className="py-2 pr-3 font-mono">{it.confirmed_event_bulk_qty}</td>
                    <td className="py-2 pr-3 font-mono">{it.already_planned_batches_qty}</td>
                    <td className="py-2 pr-3 font-mono">
                      {it.ai_forecasted_qty !== null ? `${it.ai_forecasted_qty} (AI)` : "Unavailable"}
                    </td>
                    <td className="py-2 font-black text-[#76010d]">{it.suggested_additional_prep_qty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {subTab === "batches" && (
        <div className="space-y-3">
          {batches.length === 0 ? (
            <Card className="p-6 text-center text-xs text-slate-500">No production batches planned yet.</Card>
          ) : (
            batches.map((b) => {
              const nextStep = NEXT_STAGE_MAP[b.status];
              return (
                <Card key={b.id} className="p-4 space-y-2 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="font-extrabold text-sm text-slate-900">
                        {b.batch_code} — {b.food_item_name}
                      </div>
                      <div className="text-slate-600">
                        Planned: <strong>{b.planned_quantity}</strong> • Actual: <strong>{b.actual_quantity}</strong> • Sold:{" "}
                        <strong>{b.sold_quantity}</strong> • Waste: <strong>{b.waste_quantity}</strong> • Strategy: {b.allocation_strategy} • Ingredient Cost: ₹{b.allocated_ingredient_cost}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={b.status === "completed" ? "green" : b.status === "cancelled" ? "red" : "blue"}>
                        {b.status.toUpperCase()}
                      </Badge>
                      {b.status === "prepared" && (
                        <Button
                          size="sm"
                          variant="success"
                          onClick={async () => {
                            try {
                              await api.post(`/production/batches/${b.id}/quality-check`, {
                                appearance_ok: true,
                                preparation_ok: true,
                                hygiene_ok: true,
                                status: "passed",
                                notes: "Visual, taste & hygiene check passed",
                              });
                              pushToast("Quality Control PASSED recorded", "success");
                              refetchBatches();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" /> Record QC Pass
                        </Button>
                      )}
                      {nextStep && (
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={async () => {
                            try {
                              await api.post(`/production/batches/${b.id}/transition`, {
                                target_status: nextStep.target,
                                actual_quantity: nextStep.target === "prepared" ? b.planned_quantity : undefined,
                              });
                              pushToast(`Batch moved to ${nextStep.target}`, "success");
                              refetchBatches();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          {nextStep.label}
                        </Button>
                      )}
                    </div>
                  </div>
                </Card>
              );
            })
          )}
        </div>
      )}

      {subTab === "grouped_kds" && (
        <Card className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-slate-900 text-sm">Active Kitchen Orders — Item-Grouped View</h3>
            <Button size="sm" variant="outline" onClick={() => refetchGrouped()}>Refresh</Button>
          </div>
          {groupedKds.length === 0 ? (
            <div className="text-xs text-slate-500 py-6 text-center">No active orders pending preparation.</div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {groupedKds.map((g, idx) => (
                <Card key={idx} className="p-3.5 space-y-1.5 border-slate-200">
                  <div className="flex items-center justify-between">
                    <div className="font-extrabold text-sm text-slate-900">
                      {g.item_name} {g.variant_name ? `(${g.variant_name})` : ""}
                    </div>
                    <Badge tone="red">×{g.total_quantity}</Badge>
                  </div>
                  <div className="text-xs text-slate-600">
                    Pending: {g.pending_quantity} • Preparing: {g.preparing_quantity} • Ready: {g.ready_quantity}
                  </div>
                  <div className="text-[11px] text-slate-500">
                    Orders: {(g.orders || []).map((o: any) => `${o.order_number} (×${o.quantity})`).join(", ")}
                  </div>
                </Card>
              ))}
            </div>
          )}
        </Card>
      )}

      {subTab === "report" && report && (
        <Card className="p-4 space-y-3">
          <h3 className="font-bold text-slate-900 text-sm">Production Summary Report (Last 30 Days — Actual Records)</h3>
          {report.empty ? (
            <div className="text-xs text-slate-500">{report.message}</div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-4 text-xs">
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-slate-500">Total / Completed Batches</div>
                <div className="text-lg font-black">{report.total_batches} / {report.completed_batches}</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-slate-500">Planned vs Actual Qty</div>
                <div className="text-lg font-black">{report.total_planned_qty} / {report.total_actual_qty}</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-slate-500">Recorded Waste Qty</div>
                <div className="text-lg font-black text-red-700">{report.total_waste_qty}</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-slate-500">Allocated Ingredient Cost</div>
                <div className="text-lg font-black text-[#76010d]">₹{report.total_ingredient_cost}</div>
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
};
