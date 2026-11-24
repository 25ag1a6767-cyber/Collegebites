import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ClipboardList,
  Clock,
  Flame,
  Layers,
  Plus,
  RefreshCw,
  Scale,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../../components/ui/Primitives";

interface Props {
  activeCanteenId: string;
}

const NEXT_STAGE_MAP: Record<string, { target: string; label: string }> = {
  planned: { target: "ingredients_allocated", label: "Allocate Ingredients" },
  ingredients_allocated: { target: "ready_for_preparation", label: "Mark Ready for Prep" },
  ready_for_preparation: { target: "preparing", label: "Start Preparing" },
  preparing: { target: "prepared", label: "Mark Prepared" },
  prepared: { target: "quality_checked", label: "Confirm QC Passed" },
  quality_checked: { target: "completed", label: "Complete Batch" },
};

export const ProductionManagementTab: React.FC<Props> = ({ activeCanteenId }) => {
  const { pushToast } = useToast();
  const [subTab, setSubTab] = useState<"planning" | "batches" | "recipes" | "grouped_kds" | "report">("planning");
  const [planDate, setPlanDate] = useState("");
  const [newFoodId, setNewFoodId] = useState("");
  const [newQty, setNewQty] = useState("20");
  const [newStrat, setNewStrat] = useState("FEFO");
  const [batchStatusFilter, setBatchStatusFilter] = useState("all");
  const [busy, setBusy] = useState(false);

  // Recipe shortage simulator
  const [reqFoodId, setReqFoodId] = useState<string | null>(null);
  const [reqQty, setReqQty] = useState("20");
  const [reqResult, setReqResult] = useState<any | null>(null);

  // Modals
  const [prepModal, setPrepModal] = useState<{ batch: any; actualQty: string; notes: string } | null>(null);
  const [allocModal, setAllocModal] = useState<{ batch: any; allowOverride: boolean; overrideReason: string } | null>(null);
  const [cancelModal, setCancelModal] = useState<{ batch: any; reason: string } | null>(null);
  const [delayModal, setDelayModal] = useState<{ batch: any; mins: string; reason: string } | null>(null);
  const [qcModal, setQcModal] = useState<{
    batch: any;
    appearance_ok: boolean;
    preparation_ok: boolean;
    hygiene_ok: boolean;
    temperature_c: string;
    status: "passed" | "failed" | "corrective_action_required";
    notes: string;
    evidence_url: string;
    corrective_action: string;
    approve_corrective_action: boolean;
  } | null>(null);
  const [qtyModal, setQtyModal] = useState<{
    batch: any;
    actual_quantity: string;
    sold_quantity: string;
    waste_quantity: string;
    waste_reason: string;
  } | null>(null);

  const {
    data: planning,
    isLoading: planningLoading,
    isError: planningError,
    refetch: refetchPlanning,
  } = useQuery<any>({
    queryKey: ["prod-planning", activeCanteenId, planDate],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => {
      const qs = new URLSearchParams({ canteen_id: activeCanteenId });
      if (planDate) qs.set("plan_date", planDate);
      return (await api.get(`/production/planning?${qs.toString()}`)).data;
    },
  });

  const {
    data: batches = [],
    isLoading: batchesLoading,
    isError: batchesError,
    refetch: refetchBatches,
  } = useQuery<any[]>({
    queryKey: ["prod-batches", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/production/batches?canteen_id=${activeCanteenId}`)).data,
  });

  const {
    data: recipes = [],
    isLoading: recipesLoading,
    isError: recipesError,
    refetch: refetchRecipes,
  } = useQuery<any[]>({
    queryKey: ["prod-recipes", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "recipes"),
    queryFn: async () => (await api.get(`/production/recipes?canteen_id=${activeCanteenId}`)).data,
  });

  const {
    data: groupedKds = [],
    isLoading: groupedLoading,
    isError: groupedError,
    refetch: refetchGrouped,
  } = useQuery<any[]>({
    queryKey: ["kds-grouped", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "grouped_kds"),
    queryFn: async () => (await api.get(`/kitchen/canteens/${activeCanteenId}/grouped-items`)).data,
    refetchInterval: 8000,
  });

  const {
    data: report,
    isLoading: reportLoading,
    isError: reportError,
    refetch: refetchReport,
  } = useQuery<any>({
    queryKey: ["prod-report", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "report"),
    queryFn: async () => (await api.get(`/production/report?canteen_id=${activeCanteenId}`)).data,
  });

  const filteredBatches = useMemo(() => {
    if (batchStatusFilter === "all") return batches;
    return batches.filter((b) => b.status === batchStatusFilter);
  }, [batches, batchStatusFilter]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={subTab === "planning" ? "secondary" : "outline"} onClick={() => setSubTab("planning")}>
          <ClipboardList className="h-3.5 w-3.5" /> Production Planning
        </Button>
        <Button size="sm" variant={subTab === "batches" ? "secondary" : "outline"} onClick={() => setSubTab("batches")}>
          <Flame className="h-3.5 w-3.5" /> Production Batches ({batches.length})
        </Button>
        <Button size="sm" variant={subTab === "recipes" ? "secondary" : "outline"} onClick={() => setSubTab("recipes")}>
          <BookOpen className="h-3.5 w-3.5" /> Verified Recipes &amp; Shortages
        </Button>
        <Button size="sm" variant={subTab === "grouped_kds" ? "secondary" : "outline"} onClick={() => setSubTab("grouped_kds")}>
          <Layers className="h-3.5 w-3.5" /> Item-Grouped KDS ({groupedKds.length})
        </Button>
        <Button size="sm" variant={subTab === "report" ? "secondary" : "outline"} onClick={() => setSubTab("report")}>
          Production Report
        </Button>
      </div>

      {subTab === "planning" && (
        <div className="space-y-3">
          {planningLoading ? (
            <Card className="p-6 text-center text-xs text-slate-500">Loading production planning overview...</Card>
          ) : planningError ? (
            <Card className="p-4 border-red-200 bg-red-50 text-xs text-red-700">Failed to load production planning data.</Card>
          ) : planning ? (
            <>
              <Card className="p-3 border-blue-200 bg-blue-50/50 text-xs text-blue-900 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <strong>No Double-Counting Guarantee:</strong> {planning.double_counting_guard}
                </div>
                <div className="flex items-center gap-2">
                  <Input type="date" value={planDate} onChange={(e) => setPlanDate(e.target.value)} className="w-40 bg-white" />
                  <Button size="sm" variant="outline" onClick={() => refetchPlanning()}>
                    <RefreshCw className="h-3 w-3" />
                  </Button>
                </div>
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
            </>
          ) : null}
        </div>
      )}

      {subTab === "batches" && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Select value={batchStatusFilter} onChange={(e) => setBatchStatusFilter(e.target.value)} className="w-56">
              <option value="all">All Lifecycle Stages ({batches.length})</option>
              <option value="planned">Planned</option>
              <option value="ingredients_allocated">Ingredients Allocated</option>
              <option value="ready_for_preparation">Ready for Preparation</option>
              <option value="preparing">Preparing</option>
              <option value="prepared">Prepared (Awaiting QC)</option>
              <option value="quality_checked">Quality Checked</option>
              <option value="completed">Completed</option>
              <option value="cancelled">Cancelled</option>
            </Select>
            <Button size="sm" variant="outline" onClick={() => refetchBatches()}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </Button>
          </div>

          {batchesLoading ? (
            <Card className="p-6 text-center text-xs text-slate-500">Loading production batches...</Card>
          ) : batchesError ? (
            <Card className="p-4 border-red-200 bg-red-50 text-xs text-red-700">Failed to load production batches.</Card>
          ) : filteredBatches.length === 0 ? (
            <Card className="p-6 text-center text-xs text-slate-500">No production batches match this filter.</Card>
          ) : (
            filteredBatches.map((b) => {
              const nextStep = NEXT_STAGE_MAP[b.status];
              const canCancel = !["completed", "cancelled"].includes(b.status);
              const latestQc = b.quality_checks?.length ? b.quality_checks[b.quality_checks.length - 1] : null;
              return (
                <Card key={b.id} className="p-4 space-y-2.5 text-xs">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="space-y-1">
                      <div className="font-extrabold text-sm text-slate-900">
                        {b.batch_code} — {b.food_item_name}
                      </div>
                      <div className="text-slate-600">
                        Planned: <strong>{b.planned_quantity}</strong> • Actual: <strong>{b.actual_quantity}</strong> • Sold:{" "}
                        <strong>{b.sold_quantity}</strong> • Remaining: <strong>{b.remaining_quantity}</strong> • Waste:{" "}
                        <strong>{b.waste_quantity}</strong> • Strategy: {b.allocation_strategy} • Ingredient Cost: ₹{b.allocated_ingredient_cost}
                      </div>
                      {latestQc && (
                        <div className="text-[11px] text-slate-600">
                          Latest QC: <Badge tone={latestQc.status === "passed" ? "green" : latestQc.status === "failed" ? "red" : "amber"}>{latestQc.status}</Badge>
                          {latestQc.temperature_c !== null ? ` • Temp: ${latestQc.temperature_c}°C` : ""}
                          {latestQc.notes ? ` • ${latestQc.notes}` : ""}
                        </div>
                      )}
                      {b.notes && <div className="text-[11px] text-slate-500">Notes: {b.notes}</div>}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={b.status === "completed" ? "green" : b.status === "cancelled" ? "red" : "blue"}>
                        {b.status.toUpperCase()}
                      </Badge>
                      {["prepared", "quality_checked"].includes(b.status) && (
                        <Button
                          size="sm"
                          variant="success"
                          onClick={() =>
                            setQcModal({
                              batch: b,
                              appearance_ok: true,
                              preparation_ok: true,
                              hygiene_ok: true,
                              temperature_c: "",
                              status: "passed",
                              notes: "",
                              evidence_url: "",
                              corrective_action: "",
                              approve_corrective_action: false,
                            })
                          }
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" /> Record QC
                        </Button>
                      )}
                      {nextStep && (
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={async () => {
                            if (nextStep.target === "ingredients_allocated") {
                              setAllocModal({ batch: b, allowOverride: false, overrideReason: "" });
                              return;
                            }
                            if (nextStep.target === "prepared") {
                              setPrepModal({ batch: b, actualQty: String(b.planned_quantity), notes: "" });
                              return;
                            }
                            try {
                              await api.post(`/production/batches/${b.id}/transition`, {
                                target_status: nextStep.target,
                              });
                              pushToast(`Batch moved to ${nextStep.target}`, "success");
                              refetchBatches();
                              refetchPlanning();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          {nextStep.label}
                        </Button>
                      )}
                      {["prepared", "quality_checked", "completed"].includes(b.status) && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            setQtyModal({
                              batch: b,
                              actual_quantity: String(b.actual_quantity ?? b.planned_quantity),
                              sold_quantity: String(b.sold_quantity ?? 0),
                              waste_quantity: String(b.waste_quantity ?? 0),
                              waste_reason: "",
                            })
                          }
                        >
                          <Scale className="h-3.5 w-3.5" /> Quantities / Waste
                        </Button>
                      )}
                      {canCancel && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setDelayModal({ batch: b, mins: "15", reason: "High batch demand" })}
                        >
                          <Clock className="h-3.5 w-3.5" /> Delay
                        </Button>
                      )}
                      {canCancel && (
                        <Button size="sm" variant="danger" onClick={() => setCancelModal({ batch: b, reason: "" })}>
                          <XCircle className="h-3.5 w-3.5" /> Cancel
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

      {subTab === "recipes" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4 space-y-2.5">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-slate-900 text-sm">Menu Recipes &amp; Verification ({recipes.length})</h3>
              <Button size="sm" variant="outline" onClick={() => refetchRecipes()}>Refresh</Button>
            </div>
            {recipesLoading ? (
              <div className="text-xs text-slate-500 py-6 text-center">Loading recipes...</div>
            ) : recipesError ? (
              <div className="text-xs text-red-700 bg-red-50 rounded-lg p-3">Failed to load recipes.</div>
            ) : recipes.length === 0 ? (
              <div className="text-xs text-slate-500 py-6 text-center">No active menu items found.</div>
            ) : (
              <div className="space-y-2 max-h-[500px] overflow-y-auto">
                {recipes.map((r) => (
                  <div key={r.food_item_id} className="rounded-xl border border-slate-200 p-3 text-xs space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-slate-900">{r.food_item_name}</span>
                      <Badge tone={r.is_verified ? "green" : r.has_recipe ? "amber" : "slate"}>
                        {r.is_verified ? "Verified" : r.has_recipe ? "Unverified" : "No Recipe"}
                      </Badge>
                    </div>
                    {r.has_recipe ? (
                      <>
                        <div className="text-slate-600">
                          Yield: {r.yield_portions} portion(s) • Ingredients: {(r.ingredients || []).length}
                        </div>
                        <div className="text-[11px] text-slate-500">
                          {(r.ingredients || []).map((i: any) => `${i.ingredient_name}: ${i.quantity_required} ${i.unit} (avail ${i.usable_stock})`).join(" • ")}
                        </div>
                        <div className="flex gap-2 pt-1">
                          {!r.is_verified && (
                            <Button
                              size="sm"
                              variant="success"
                              onClick={async () => {
                                try {
                                  await api.post(`/production/recipes/${r.food_item_id}/verify`);
                                  pushToast(`Verified recipe for ${r.food_item_name}`, "success");
                                  refetchRecipes();
                                  refetchPlanning();
                                } catch (err) {
                                  pushToast(getApiError(err), "error");
                                }
                              }}
                            >
                              <ShieldCheck className="h-3.5 w-3.5" /> Verify Recipe
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={async () => {
                              setReqFoodId(r.food_item_id);
                              try {
                                const res = await api.get(`/production/recipes/${r.food_item_id}/requirements?quantity=${Number(reqQty || 20)}`);
                                setReqResult(res.data);
                              } catch (err) {
                                pushToast(getApiError(err), "error");
                              }
                            }}
                          >
                            Check Shortages
                          </Button>
                        </div>
                      </>
                    ) : (
                      <div className="text-[11px] text-slate-500">Configure ingredients in Inventory → Dish Recipes first.</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="p-4 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-bold text-slate-900 text-sm">Ingredient Requirement &amp; Shortage Check</h3>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-500">Portions:</span>
                <Input type="number" min={1} value={reqQty} onChange={(e) => setReqQty(e.target.value)} className="w-20" />
                {reqFoodId && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={async () => {
                      try {
                        const res = await api.get(`/production/recipes/${reqFoodId}/requirements?quantity=${Number(reqQty || 20)}`);
                        setReqResult(res.data);
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Recalculate
                  </Button>
                )}
              </div>
            </div>
            {!reqResult ? (
              <div className="text-xs text-slate-500 py-8 text-center">
                Select any dish on the left to compute exact ingredient requirements and usable stock shortages.
              </div>
            ) : (
              <div className="space-y-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-slate-900">{reqResult.food_item_name} (×{reqResult.target_quantity})</span>
                  <Badge tone={reqResult.can_produce ? "green" : "red"}>
                    {reqResult.can_produce ? "Can Produce" : `${reqResult.shortages_count || 0} Shortage(s)`}
                  </Badge>
                </div>
                {reqResult.message && <div className="text-amber-800">{reqResult.message}</div>}
                {(reqResult.requirements || []).map((row: any) => (
                  <div key={row.ingredient_id} className={`rounded-lg border p-2 flex justify-between ${row.is_short ? "border-red-300 bg-red-50/50" : "border-slate-200"}`}>
                    <div>
                      <div className="font-semibold text-slate-900">{row.ingredient_name}</div>
                      <div className="text-[11px] text-slate-600">
                        Need: {row.required_quantity} {row.unit} • Usable Stock: {row.usable_stock} {row.unit}
                      </div>
                    </div>
                    {row.is_short && <Badge tone="red">Short {row.deficit_quantity} {row.unit}</Badge>}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {subTab === "grouped_kds" && (
        <Card className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-slate-900 text-sm">Active Kitchen Orders — Item-Grouped View</h3>
            <Button size="sm" variant="outline" onClick={() => refetchGrouped()}>Refresh</Button>
          </div>
          {groupedLoading ? (
            <div className="text-xs text-slate-500 py-6 text-center">Loading grouped kitchen items...</div>
          ) : groupedError ? (
            <div className="text-xs text-red-700 bg-red-50 rounded-lg p-3">Failed to load grouped kitchen items.</div>
          ) : groupedKds.length === 0 ? (
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

      {subTab === "report" && (
        <Card className="p-4 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-slate-900 text-sm">Production Summary Report (Last 30 Days — Actual Records)</h3>
            <Button size="sm" variant="outline" onClick={() => refetchReport()}>Refresh</Button>
          </div>
          {reportLoading ? (
            <div className="text-xs text-slate-500 py-6 text-center">Loading production report...</div>
          ) : reportError ? (
            <div className="text-xs text-red-700 bg-red-50 rounded-lg p-3">Failed to load production report.</div>
          ) : report?.empty ? (
            <div className="text-xs text-slate-500">{report.message}</div>
          ) : report ? (
            <>
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
              {report.ingredient_consumption?.length > 0 && (
                <div className="overflow-x-auto">
                  <div className="text-xs font-bold text-slate-800 mb-2">Verified Ingredient Consumption Across Production Batches</div>
                  <table className="w-full text-xs text-left">
                    <thead className="border-b border-slate-200 text-slate-500 uppercase">
                      <tr>
                        <th className="py-1.5 pr-3">Ingredient</th>
                        <th className="py-1.5 pr-3">Quantity Consumed</th>
                        <th className="py-1.5">Allocated Cost</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {report.ingredient_consumption.map((ic: any) => (
                        <tr key={ic.ingredient_id}>
                          <td className="py-1.5 pr-3 font-semibold text-slate-900">{ic.ingredient_name}</td>
                          <td className="py-1.5 pr-3 font-mono">{ic.quantity_consumed} {ic.unit}</td>
                          <td className="py-1.5 font-mono">₹{ic.total_cost}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : null}
        </Card>
      )}

      {/* Allocate Ingredients Modal (supports authorized override) */}
      <Modal open={Boolean(allocModal)} onClose={() => setAllocModal(null)} title={`Allocate Ingredients • ${allocModal?.batch?.batch_code || ""}`}>
        {allocModal && (
          <div className="space-y-3 text-xs">
            <p className="text-slate-600">
              Allocates verified recipe ingredients atomically via <strong>{allocModal.batch.allocation_strategy}</strong>. Expired, blocked, rejected, and recalled batches are excluded by default.
            </p>
            <label className="flex items-center gap-2 text-amber-900">
              <input
                type="checkbox"
                checked={allocModal.allowOverride}
                onChange={(e) => setAllocModal({ ...allocModal, allowOverride: e.target.checked })}
              />
              <span>Manager/Admin Override (audit-logged, mandatory reason)</span>
            </label>
            {allocModal.allowOverride && (
              <Input
                value={allocModal.overrideReason}
                onChange={(e) => setAllocModal({ ...allocModal, overrideReason: e.target.value })}
                placeholder="Documented override reason (min 5 chars)..."
              />
            )}
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setAllocModal(null)}>Cancel</Button>
              <Button
                size="sm"
                variant="primary"
                onClick={async () => {
                  try {
                    await api.post(`/production/batches/${allocModal.batch.id}/transition`, {
                      target_status: "ingredients_allocated",
                      allow_batch_override: allocModal.allowOverride,
                      override_reason: allocModal.allowOverride ? allocModal.overrideReason.trim() : null,
                    });
                    pushToast("Ingredients allocated atomically", "success");
                    setAllocModal(null);
                    refetchBatches();
                    refetchPlanning();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Confirm Allocation
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Mark Prepared Modal */}
      <Modal open={Boolean(prepModal)} onClose={() => setPrepModal(null)} title={`Mark Prepared • ${prepModal?.batch?.batch_code || ""}`}>
        {prepModal && (
          <div className="space-y-3 text-xs">
            <div>
              <label className="text-[11px] font-semibold text-slate-600">Actual Quantity Prepared</label>
              <Input type="number" min={0} value={prepModal.actualQty} onChange={(e) => setPrepModal({ ...prepModal, actualQty: e.target.value })} />
            </div>
            <Input value={prepModal.notes} onChange={(e) => setPrepModal({ ...prepModal, notes: e.target.value })} placeholder="Preparation notes (optional)" />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setPrepModal(null)}>Cancel</Button>
              <Button
                size="sm"
                variant="primary"
                onClick={async () => {
                  try {
                    await api.post(`/production/batches/${prepModal.batch.id}/transition`, {
                      target_status: "prepared",
                      actual_quantity: Number(prepModal.actualQty || 0),
                      notes: prepModal.notes.trim() || null,
                    });
                    pushToast("Batch marked prepared — ready for Quality Control", "success");
                    setPrepModal(null);
                    refetchBatches();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Confirm Prepared
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Full Quality Control Modal */}
      <Modal open={Boolean(qcModal)} onClose={() => setQcModal(null)} title={`Quality Control Inspection • ${qcModal?.batch?.batch_code || ""}`}>
        {qcModal && (
          <div className="space-y-2.5 text-xs">
            <div className="grid grid-cols-3 gap-2">
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={qcModal.appearance_ok} onChange={(e) => setQcModal({ ...qcModal, appearance_ok: e.target.checked })} /> Appearance OK</label>
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={qcModal.preparation_ok} onChange={(e) => setQcModal({ ...qcModal, preparation_ok: e.target.checked })} /> Prep/Taste OK</label>
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={qcModal.hygiene_ok} onChange={(e) => setQcModal({ ...qcModal, hygiene_ok: e.target.checked })} /> Hygiene OK</label>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Select value={qcModal.status} onChange={(e) => setQcModal({ ...qcModal, status: e.target.value as any })}>
                <option value="passed">Passed</option>
                <option value="corrective_action_required">Corrective Action Required</option>
                <option value="failed">Failed (Blocks Completion)</option>
              </Select>
              <Input type="number" step="0.1" value={qcModal.temperature_c} onChange={(e) => setQcModal({ ...qcModal, temperature_c: e.target.value })} placeholder="Core Temp °C (optional)" />
            </div>
            <Input value={qcModal.notes} onChange={(e) => setQcModal({ ...qcModal, notes: e.target.value })} placeholder="Inspector notes" />
            <Input value={qcModal.evidence_url} onChange={(e) => setQcModal({ ...qcModal, evidence_url: e.target.value })} placeholder="Photo evidence URL (optional)" />
            <Input value={qcModal.corrective_action} onChange={(e) => setQcModal({ ...qcModal, corrective_action: e.target.value })} placeholder="Corrective action (required if CA required)" />
            {qcModal.status === "corrective_action_required" && (
              <label className="flex items-center gap-2 text-amber-800">
                <input
                  type="checkbox"
                  checked={qcModal.approve_corrective_action}
                  onChange={(e) => setQcModal({ ...qcModal, approve_corrective_action: e.target.checked })}
                />
                <span>Approve corrective action (Manager / Admin / Inspector only)</span>
              </label>
            )}
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setQcModal(null)}>Cancel</Button>
              <Button
                size="sm"
                variant={qcModal.status === "failed" ? "danger" : "success"}
                onClick={async () => {
                  try {
                    await api.post(`/production/batches/${qcModal.batch.id}/quality-check`, {
                      appearance_ok: qcModal.appearance_ok,
                      preparation_ok: qcModal.preparation_ok,
                      hygiene_ok: qcModal.hygiene_ok,
                      temperature_c: qcModal.temperature_c.trim() ? qcModal.temperature_c.trim() : null,
                      status: qcModal.status,
                      notes: qcModal.notes.trim() || null,
                      evidence_url: qcModal.evidence_url.trim() || null,
                      corrective_action: qcModal.corrective_action.trim() || null,
                      approve_corrective_action: qcModal.approve_corrective_action,
                    });
                    pushToast(`Quality check (${qcModal.status.toUpperCase()}) saved`, qcModal.status === "failed" ? "error" : "success");
                    setQcModal(null);
                    refetchBatches();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Save Quality Check
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Update Quantities & Waste Modal */}
      <Modal open={Boolean(qtyModal)} onClose={() => setQtyModal(null)} title={`Batch Quantities & Waste • ${qtyModal?.batch?.batch_code || ""}`}>
        {qtyModal && (
          <div className="space-y-2.5 text-xs">
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="text-[11px] font-semibold text-slate-600">Actual Produced</label>
                <Input type="number" min={0} value={qtyModal.actual_quantity} onChange={(e) => setQtyModal({ ...qtyModal, actual_quantity: e.target.value })} />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-600">Sold Qty</label>
                <Input type="number" min={0} value={qtyModal.sold_quantity} onChange={(e) => setQtyModal({ ...qtyModal, sold_quantity: e.target.value })} />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-600">Waste Qty</label>
                <Input type="number" min={0} value={qtyModal.waste_quantity} onChange={(e) => setQtyModal({ ...qtyModal, waste_quantity: e.target.value })} />
              </div>
            </div>
            <Input value={qtyModal.waste_reason} onChange={(e) => setQtyModal({ ...qtyModal, waste_reason: e.target.value })} placeholder="Waste reason (logged into verified wastage records)" />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setQtyModal(null)}>Cancel</Button>
              <Button
                size="sm"
                variant="primary"
                onClick={async () => {
                  try {
                    await api.patch(`/production/batches/${qtyModal.batch.id}/quantities`, {
                      actual_quantity: Number(qtyModal.actual_quantity || 0),
                      sold_quantity: Number(qtyModal.sold_quantity || 0),
                      waste_quantity: Number(qtyModal.waste_quantity || 0),
                      waste_reason: qtyModal.waste_reason.trim() || null,
                    });
                    pushToast("Batch quantities & wastage updated", "success");
                    setQtyModal(null);
                    refetchBatches();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Save Quantities
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Report Delay Modal */}
      <Modal open={Boolean(delayModal)} onClose={() => setDelayModal(null)} title={`Report Production Delay • ${delayModal?.batch?.batch_code || ""}`}>
        {delayModal && (
          <div className="space-y-3 text-xs">
            <Input type="number" min={1} max={240} value={delayModal.mins} onChange={(e) => setDelayModal({ ...delayModal, mins: e.target.value })} placeholder="Delay in minutes" />
            <Input value={delayModal.reason} onChange={(e) => setDelayModal({ ...delayModal, reason: e.target.value })} placeholder="Reason for delay" />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setDelayModal(null)}>Cancel</Button>
              <Button
                size="sm"
                variant="primary"
                onClick={async () => {
                  try {
                    await api.post(`/production/batches/${delayModal.batch.id}/report-delay`, {
                      delay_minutes: Number(delayModal.mins || 10),
                      reason: delayModal.reason.trim(),
                    });
                    pushToast("Production delay alert dispatched", "info");
                    setDelayModal(null);
                    refetchBatches();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Notify Delay
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Cancel Batch Confirmation Modal */}
      <Modal open={Boolean(cancelModal)} onClose={() => setCancelModal(null)} title="Confirm Cancel Production Batch">
        {cancelModal && (
          <div className="space-y-3 text-xs">
            <div className="flex items-start gap-2 text-red-800">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>
                Cancel batch <strong>{cancelModal.batch.batch_code}</strong> ({cancelModal.batch.food_item_name})? If ingredients were allocated and cooking has not started, raw stock will be returned automatically.
              </span>
            </div>
            <Input value={cancelModal.reason} onChange={(e) => setCancelModal({ ...cancelModal, reason: e.target.value })} placeholder="Cancellation reason" />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setCancelModal(null)}>Keep Batch</Button>
              <Button
                size="sm"
                variant="danger"
                onClick={async () => {
                  try {
                    await api.post(`/production/batches/${cancelModal.batch.id}/transition`, {
                      target_status: "cancelled",
                      notes: cancelModal.reason.trim() || "Cancelled by kitchen staff",
                    });
                    pushToast("Production batch cancelled", "info");
                    setCancelModal(null);
                    refetchBatches();
                    refetchPlanning();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Confirm Cancel Batch
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
