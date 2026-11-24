import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertOctagon,
  Download,
  Edit3,
  FilePlus2,
  GitBranch,
  History,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../../components/ui/Primitives";

interface Props {
  activeCanteenId: string;
  suppliers: any[];
  items?: any[];
}

export const TraceabilityReorderingTab: React.FC<Props> = ({ activeCanteenId, suppliers, items = [] }) => {
  const { pushToast } = useToast();
  const [subTab, setSubTab] = useState<"traceability" | "recalls" | "reordering">("traceability");

  // Traceability state
  const [batchSearch, setBatchSearch] = useState("");
  const [batchQualityFilter, setBatchQualityFilter] = useState("all");
  const [selectedChain, setSelectedChain] = useState<any | null>(null);
  const [orderLookupId, setOrderLookupId] = useState("");
  const [orderChain, setOrderChain] = useState<any | null>(null);
  const [movementsModal, setMovementsModal] = useState<{ batch: any; rows: any[] } | null>(null);
  const [qualityModal, setQualityModal] = useState<{ batch: any; targetStatus: string; reason: string; storage: string } | null>(null);

  // Register batch form
  const [showRegisterBatch, setShowRegisterBatch] = useState(false);
  const [regItemId, setRegItemId] = useState("");
  const [regQty, setRegQty] = useState("");
  const [regCost, setRegCost] = useState("");
  const [regSupplierId, setRegSupplierId] = useState("");
  const [regBatchNo, setRegBatchNo] = useState("");
  const [regMfgDate, setRegMfgDate] = useState("");
  const [regExpDate, setRegExpDate] = useState("");
  const [regStorage, setRegStorage] = useState("Main Store");

  // Recall state
  const [recallTitle, setRecallTitle] = useState("");
  const [recallReason, setRecallReason] = useState("");
  const [recallSeverity, setRecallSeverity] = useState<"medium" | "high" | "critical">("critical");
  const [recallNotes, setRecallNotes] = useState("");
  const [recallBatchIds, setRecallBatchIds] = useState<string[]>([]);
  const [confirmApproveRecall, setConfirmApproveRecall] = useState<any | null>(null);
  const [editingRecall, setEditingRecall] = useState<{
    recall: any;
    status: string;
    investigation_notes: string;
    corrective_actions: string;
  } | null>(null);

  // Reordering state
  const [poOverrides, setPoOverrides] = useState<Record<string, { supplier_id: string; qty: string; unit_cost: string; notes: string }>>({});
  const [ruleSearch, setRuleSearch] = useState("");
  const [editingRule, setEditingRule] = useState<{
    inventory_item_id: string;
    ingredient_name: string;
    unit: string;
    min_stock_level: string;
    reorder_level: string;
    safety_stock: string;
    supplier_lead_time_days: string;
    target_days_of_cover: string;
    preferred_supplier_id: string;
    is_active: boolean;
  } | null>(null);

  const [busy, setBusy] = useState(false);

  const {
    data: batches = [],
    isLoading: batchesLoading,
    isError: batchesError,
    refetch: refetchBatches,
  } = useQuery<any[]>({
    queryKey: ["trace-batches", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/traceability/batches?canteen_id=${activeCanteenId}&include_empty=true`)).data,
  });

  const {
    data: recalls = [],
    isLoading: recallsLoading,
    isError: recallsError,
    refetch: refetchRecalls,
  } = useQuery<any[]>({
    queryKey: ["trace-recalls", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "recalls"),
    queryFn: async () => (await api.get(`/traceability/recalls?canteen_id=${activeCanteenId}`)).data,
  });

  const {
    data: recs = [],
    isLoading: recsLoading,
    isError: recsError,
    refetch: refetchRecs,
  } = useQuery<any[]>({
    queryKey: ["reorder-recs", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "reordering"),
    queryFn: async () => (await api.get(`/reordering/recommendations?canteen_id=${activeCanteenId}`)).data,
  });

  const {
    data: rules = [],
    isLoading: rulesLoading,
    isError: rulesError,
    refetch: refetchRules,
  } = useQuery<any[]>({
    queryKey: ["reorder-rules", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "reordering"),
    queryFn: async () => (await api.get(`/reordering/rules?canteen_id=${activeCanteenId}`)).data,
  });

  const activeSuppliers = useMemo(() => suppliers.filter((s) => s.is_active !== false), [suppliers]);

  const filteredBatches = useMemo(() => {
    const q = batchSearch.trim().toLowerCase();
    return batches.filter((b) => {
      if (batchQualityFilter !== "all" && b.quality_status !== batchQualityFilter) return false;
      if (!q) return true;
      return (
        String(b.ingredient_name || "").toLowerCase().includes(q) ||
        String(b.batch_number || "").toLowerCase().includes(q) ||
        String(b.po_number || "").toLowerCase().includes(q) ||
        String(b.supplier_name || "").toLowerCase().includes(q)
      );
    });
  }, [batches, batchSearch, batchQualityFilter]);

  const filteredRules = useMemo(() => {
    const q = ruleSearch.trim().toLowerCase();
    if (!q) return rules;
    return rules.filter(
      (r) =>
        String(r.ingredient_name || "").toLowerCase().includes(q) ||
        String(r.preferred_supplier_name || "").toLowerCase().includes(q)
    );
  }, [rules, ruleSearch]);

  const toggleRecallBatch = (bid: string) => {
    setRecallBatchIds((prev) => (prev.includes(bid) ? prev.filter((x) => x !== bid) : [...prev, bid]));
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={subTab === "traceability" ? "secondary" : "outline"} onClick={() => setSubTab("traceability")}>
          <GitBranch className="h-3.5 w-3.5" /> Batch Traceability (FIFO/FEFO) ({batches.length})
        </Button>
        <Button size="sm" variant={subTab === "recalls" ? "secondary" : "outline"} onClick={() => setSubTab("recalls")}>
          <AlertOctagon className="h-3.5 w-3.5" /> Recalls &amp; Quarantine ({recalls.length})
        </Button>
        <Button size="sm" variant={subTab === "reordering" ? "secondary" : "outline"} onClick={() => setSubTab("reordering")}>
          <FilePlus2 className="h-3.5 w-3.5" /> Automated Reordering ({recs.length})
        </Button>
      </div>

      {subTab === "traceability" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2 flex-1">
              <div className="relative min-w-[200px] flex-1 max-w-xs">
                <Search className="h-3.5 w-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <Input
                  className="pl-8"
                  value={batchSearch}
                  onChange={(e) => setBatchSearch(e.target.value)}
                  placeholder="Search batch, ingredient, PO, supplier..."
                />
              </div>
              <Select value={batchQualityFilter} onChange={(e) => setBatchQualityFilter(e.target.value)} className="w-40">
                <option value="all">All Quality Statuses</option>
                <option value="approved">Approved</option>
                <option value="pending">Pending</option>
                <option value="blocked">Blocked / Quarantined</option>
                <option value="rejected">Rejected</option>
                <option value="recalled">Recalled</option>
              </Select>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => refetchBatches()}>
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </Button>
              <Button size="sm" variant="primary" onClick={() => setShowRegisterBatch((v) => !v)}>
                <Plus className="h-3.5 w-3.5" /> Register Stock Batch
              </Button>
            </div>
          </div>

          {showRegisterBatch && (
            <Card className="p-4 space-y-3 border-emerald-200 bg-emerald-50/30">
              <div className="font-bold text-slate-900 text-sm">Register Traceable Stock Batch</div>
              <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
                <Select value={regItemId} onChange={(e) => setRegItemId(e.target.value)}>
                  <option value="">Select Inventory Item...</option>
                  {items.filter((i) => !i.is_archived).map((i) => (
                    <option key={i.inventory_item_id} value={i.inventory_item_id}>
                      {i.name} ({i.unit})
                    </option>
                  ))}
                </Select>
                <Input type="number" step="0.001" min="0.001" value={regQty} onChange={(e) => setRegQty(e.target.value)} placeholder="Quantity *" />
                <Input type="number" step="0.01" min="0" value={regCost} onChange={(e) => setRegCost(e.target.value)} placeholder="Unit Cost ₹ (optional)" />
                <Select value={regSupplierId} onChange={(e) => setRegSupplierId(e.target.value)}>
                  <option value="">Supplier (optional)</option>
                  {activeSuppliers.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </Select>
                <Input value={regBatchNo} onChange={(e) => setRegBatchNo(e.target.value)} placeholder="Batch No. (auto if blank)" />
                <Input type="date" value={regMfgDate} onChange={(e) => setRegMfgDate(e.target.value)} title="Manufacturing Date" />
                <Input type="date" value={regExpDate} onChange={(e) => setRegExpDate(e.target.value)} title="Expiry Date" />
                <Input value={regStorage} onChange={(e) => setRegStorage(e.target.value)} placeholder="Storage Location" />
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  disabled={busy || !regItemId || !regQty || Number(regQty) <= 0}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await api.post("/traceability/batches", {
                        inventory_item_id: regItemId,
                        quantity: regQty,
                        unit_cost: regCost.trim() ? regCost.trim() : null,
                        supplier_id: regSupplierId || null,
                        batch_number: regBatchNo.trim() || null,
                        manufacturing_date: regMfgDate || null,
                        expiry_date: regExpDate || null,
                        storage_location: regStorage.trim() || "Main Store",
                        quality_status: "approved",
                      });
                      pushToast("Traceable stock batch registered", "success");
                      setShowRegisterBatch(false);
                      setRegQty("");
                      setRegBatchNo("");
                      refetchBatches();
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Save Batch
                </Button>
                <Button size="sm" variant="outline" onClick={() => setShowRegisterBatch(false)}>Cancel</Button>
              </div>
            </Card>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4 space-y-2">
              <h3 className="font-bold text-slate-900 text-sm">Ingredient Batches (FEFO Ordered) ({filteredBatches.length})</h3>
              {batchesLoading ? (
                <div className="text-xs text-slate-500 py-6 text-center">Loading stock batches...</div>
              ) : batchesError ? (
                <div className="text-xs text-red-700 bg-red-50 rounded-lg p-3">Failed to load stock batches.</div>
              ) : filteredBatches.length === 0 ? (
                <div className="text-xs text-slate-500 py-6 text-center">No stock batches match the selected filters.</div>
              ) : (
                <div className="space-y-2 max-h-[500px] overflow-y-auto">
                  {filteredBatches.map((b) => (
                    <div key={b.id} className="rounded-xl border border-slate-200 p-3 text-xs space-y-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-bold text-slate-900">{b.ingredient_name} • {b.batch_number}</div>
                        <div className="flex gap-1">
                          {b.is_expired && <Badge tone="red">EXPIRED</Badge>}
                          <Badge tone={b.quality_status === "approved" ? "green" : b.quality_status === "recalled" || b.quality_status === "blocked" || b.quality_status === "rejected" ? "red" : "amber"}>
                            {b.quality_status}
                          </Badge>
                        </div>
                      </div>
                      <div className="text-slate-600">
                        Usable: <strong>{b.available_quantity ?? b.remaining_quantity}</strong> | Rem: {b.remaining_quantity} / {b.initial_quantity} {b.unit} • Exp: {b.expiry_date || "Not specified"}
                      </div>
                      <div className="text-[11px] text-slate-500">
                        Vendor: {b.supplier_name || "N/A"} • PO: {b.po_number || "N/A"} • GRN: {b.grn_number || "N/A"} • Loc: {b.storage_location || "Main Store"}
                      </div>
                      {b.block_reason && <div className="text-[11px] text-red-700">Reason: {b.block_reason}</div>}
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            try {
                              const res = await api.get(`/traceability/batches/${b.id}/chain`);
                              setSelectedChain(res.data);
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Inspect Chain
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            try {
                              const res = await api.get(`/traceability/batches/${b.id}/movements`);
                              setMovementsModal({ batch: b, rows: res.data });
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          <History className="h-3 w-3" /> Movements
                        </Button>
                        {b.quality_status !== "recalled" && b.quality_status !== "rejected" && (
                          <Button
                            size="sm"
                            variant={b.quality_status === "blocked" ? "secondary" : "danger"}
                            onClick={() =>
                              setQualityModal({
                                batch: b,
                                targetStatus: b.quality_status === "blocked" ? "approved" : "blocked",
                                reason: b.block_reason || "",
                                storage: b.storage_location || "Main Store",
                              })
                            }
                          >
                            {b.quality_status === "blocked" ? "Update / Unblock" : "Quarantine / Reject"}
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <div className="space-y-4">
              <Card className="p-4 space-y-3">
                <h3 className="font-bold text-slate-900 text-sm">End-to-End Traceability Chain</h3>
                {!selectedChain ? (
                  <div className="text-xs text-slate-500 py-6 text-center">
                    Select any stock batch to trace Vendor → PO → GRN → Stock Batch → Recipes → Production Batches → Orders.
                  </div>
                ) : (
                  <div className="space-y-2.5 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={selectedChain.trace_completeness === "complete" ? "green" : "amber"}>
                        Completeness: {String(selectedChain.trace_completeness || "").toUpperCase()}
                      </Badge>
                      <Badge tone="slate">Data: {selectedChain.data_classification || "actual"}</Badge>
                      {selectedChain.missing_links?.length > 0 && (
                        <span className="text-amber-700">Missing links: {selectedChain.missing_links.join(", ")}</span>
                      )}
                    </div>
                    <div className="rounded-lg bg-slate-50 p-3 space-y-1.5 border border-slate-200">
                      <div><strong>Batch:</strong> {selectedChain.batch?.ingredient_name} ({selectedChain.batch?.batch_number})</div>
                      <div><strong>Vendor:</strong> {selectedChain.vendor?.name || "Not linked"} {selectedChain.vendor?.phone ? `(${selectedChain.vendor.phone})` : ""}</div>
                      <div><strong>Purchase Order:</strong> {selectedChain.purchase_order?.po_number ? `${selectedChain.purchase_order.po_number} (${selectedChain.purchase_order.status})` : "Not linked"}</div>
                      <div><strong>Goods Receipt:</strong> {selectedChain.goods_receipt?.grn_number || "Not linked"}</div>
                      <div>
                        <strong>Recipes ({selectedChain.recipes?.length || 0}):</strong>{" "}
                        {selectedChain.recipes?.length > 0
                          ? selectedChain.recipes.map((r: any) => `${r.food_item_name || r.food_item_id} (${r.is_verified ? "Verified" : "Unverified"})`).join(", ")
                          : "None linked"}
                      </div>
                      <div>
                        <strong>Production Batches ({selectedChain.production_batches?.length || 0}):</strong>
                        {selectedChain.production_batches?.length > 0 && (
                          <ul className="list-disc pl-5 mt-1 space-y-0.5 text-[11px]">
                            {selectedChain.production_batches.map((pb: any) => (
                              <li key={pb.id}>
                                {pb.batch_code} — {pb.food_item_name || pb.food_item_id} ({pb.status}, actual {pb.actual_quantity ?? 0}/{pb.planned_quantity})
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                      <div>
                        <strong>Affected Confirmed Orders ({selectedChain.affected_orders?.length || 0}):</strong>
                        {selectedChain.affected_orders?.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1">
                            {selectedChain.affected_orders.slice(0, 20).map((o: any) => (
                              <Badge key={o.id} tone="slate">{o.order_number} ({o.status})</Badge>
                            ))}
                            {selectedChain.affected_orders.length > 20 && (
                              <span className="text-[11px] text-slate-500">+{selectedChain.affected_orders.length - 20} more</span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </Card>

              <Card className="p-4 space-y-2.5">
                <h3 className="font-bold text-slate-900 text-sm">Trace By Customer Order ID</h3>
                <div className="flex gap-2">
                  <Input
                    value={orderLookupId}
                    onChange={(e) => setOrderLookupId(e.target.value)}
                    placeholder="Paste Order UUID..."
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={!orderLookupId.trim()}
                    onClick={async () => {
                      try {
                        const res = await api.get(`/traceability/orders/${orderLookupId.trim()}/chain`);
                        setOrderChain(res.data);
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Trace Order
                  </Button>
                </div>
                {orderChain && (
                  <div className="rounded-lg bg-slate-50 border border-slate-200 p-2.5 text-xs space-y-1">
                    <div className="font-bold text-slate-900">
                      Order {orderChain.order_number} • Completeness: {String(orderChain.trace_completeness).toUpperCase()} ({orderChain.linked_batches_count} batch links)
                    </div>
                    {orderChain.missing_links?.length > 0 && (
                      <div className="text-amber-700">Missing: {orderChain.missing_links.join(", ")}</div>
                    )}
                    {orderChain.linked_batches?.map((ch: any) => (
                      <div key={ch.batch?.id} className="text-[11px] text-slate-600">
                        • {ch.batch?.ingredient_name} ({ch.batch?.batch_number}) ← Vendor: {ch.vendor?.name || "N/A"} / PO: {ch.purchase_order?.po_number || "N/A"}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>
          </div>
        </div>
      )}

      {subTab === "recalls" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4 space-y-3">
            <div className="flex items-center gap-2 font-bold text-red-900 text-sm">
              <ShieldAlert className="h-4 w-4" /> Initiate Ingredient Batch Recall
            </div>
            <div className="text-xs text-slate-600">Select one or more suspected batches to quarantine immediately under recall review:</div>
            <div className="max-h-40 overflow-y-auto rounded-lg border border-slate-200 p-2 space-y-1.5 text-xs">
              {batches.length === 0 ? (
                <div className="text-slate-400 text-center py-3">No batches available</div>
              ) : (
                batches.map((b) => (
                  <label key={b.id} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={recallBatchIds.includes(b.id)}
                      onChange={() => toggleRecallBatch(b.id)}
                    />
                    <span className="font-semibold text-slate-800">{b.ingredient_name}</span>
                    <span className="text-slate-500">• {b.batch_number} ({b.quality_status})</span>
                  </label>
                ))
              )}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input value={recallTitle} onChange={(e) => setRecallTitle(e.target.value)} placeholder="Recall Title *" />
              <Select value={recallSeverity} onChange={(e) => setRecallSeverity(e.target.value as any)}>
                <option value="medium">Severity: Medium</option>
                <option value="high">Severity: High</option>
                <option value="critical">Severity: Critical</option>
              </Select>
            </div>
            <Input value={recallReason} onChange={(e) => setRecallReason(e.target.value)} placeholder="Reason / Supplier notice details *" />
            <Input value={recallNotes} onChange={(e) => setRecallNotes(e.target.value)} placeholder="Initial investigation notes (optional)" />
            <Button
              size="sm"
              variant="danger"
              disabled={busy || recallBatchIds.length === 0 || recallTitle.trim().length < 3 || recallReason.trim().length < 5}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.post("/traceability/recalls", {
                    canteen_id: activeCanteenId,
                    title: recallTitle.trim(),
                    reason: recallReason.trim(),
                    severity: recallSeverity,
                    stock_batch_ids: recallBatchIds,
                    investigation_notes: recallNotes.trim() || null,
                  });
                  setRecallTitle("");
                  setRecallReason("");
                  setRecallNotes("");
                  setRecallBatchIds([]);
                  pushToast("Recall initiated and batches quarantined (pending approval)", "info");
                  refetchRecalls();
                  refetchBatches();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Initiate Recall ({recallBatchIds.length} batch{recallBatchIds.length === 1 ? "" : "es"})
            </Button>
          </Card>

          <Card className="p-4 space-y-2.5">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-slate-900 text-sm">Recall Register ({recalls.length})</h3>
              <Button size="sm" variant="outline" onClick={() => refetchRecalls()}>Refresh</Button>
            </div>
            {recallsLoading ? (
              <div className="text-xs text-slate-500 py-6 text-center">Loading recalls...</div>
            ) : recallsError ? (
              <div className="text-xs text-red-700 bg-red-50 rounded-lg p-3">Failed to load recall incidents.</div>
            ) : recalls.length === 0 ? (
              <div className="text-xs text-slate-500 py-6 text-center">No food recall incidents recorded.</div>
            ) : (
              recalls.map((r) => (
                <div key={r.id} className="rounded-xl border border-red-200 p-3 text-xs space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold text-slate-900">{r.recall_number} — {r.title}</span>
                    <div className="flex gap-1">
                      <Badge tone={r.severity === "critical" ? "red" : "amber"}>{r.severity}</Badge>
                      <Badge tone={r.status === "active_recall" ? "red" : r.status === "resolved" || r.status === "closed" ? "green" : "amber"}>
                        {r.status}
                      </Badge>
                    </div>
                  </div>
                  <div className="text-slate-700">{r.reason}</div>
                  <div className="text-slate-600">
                    Batches: {r.affected_stock_batch_ids?.length || 0} • Prod Batches: {r.affected_production_batch_ids?.length || 0} • Orders: {r.affected_order_ids?.length || 0}
                  </div>
                  {r.investigation_notes && <div className="text-[11px] text-slate-600"><strong>Investigation:</strong> {r.investigation_notes}</div>}
                  {r.corrective_actions && <div className="text-[11px] text-emerald-800"><strong>Corrective Actions:</strong> {r.corrective_actions}</div>}
                  <div className="flex flex-wrap gap-2">
                    {r.status === "under_review" && (
                      <Button size="sm" variant="danger" onClick={() => setConfirmApproveRecall(r)}>
                        Approve Active Recall
                      </Button>
                    )}
                    {r.status !== "closed" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          setEditingRecall({
                            recall: r,
                            status: r.status === "active_recall" ? "resolved" : "closed",
                            investigation_notes: r.investigation_notes || "",
                            corrective_actions: r.corrective_actions || "",
                          })
                        }
                      >
                        <Edit3 className="h-3 w-3" /> Update / Resolve
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        try {
                          const res = await api.get(`/traceability/recalls/${r.id}/report.pdf`, { responseType: "blob" });
                          const url = URL.createObjectURL(res.data);
                          const a = document.createElement("a");
                          a.href = url;
                          a.download = `${r.recall_number}.pdf`;
                          a.click();
                          URL.revokeObjectURL(url);
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      <Download className="h-3.5 w-3.5" /> PDF Report
                    </Button>
                  </div>
                </div>
              ))
            )}
          </Card>
        </div>
      )}

      {subTab === "reordering" && (
        <div className="space-y-4">
          <Card className="p-4 flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs text-slate-600">
              <strong>Safety Guard:</strong> Automated Reordering ONLY generates <strong>Draft</strong> Purchase Orders. Authorized manager approval and verified Goods Receipt are mandatory before stock updates or vendor payments.
            </div>
            <Button
              size="sm"
              variant="primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const res = await api.post(`/reordering/recommendations/generate?canteen_id=${activeCanteenId}`);
                  pushToast(`Generated ${res.data.generated_count} reorder recommendation(s)`, "success");
                  refetchRecs();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              <RefreshCw className="h-3.5 w-3.5" /> Run Reorder Scan
            </Button>
          </Card>

          <Card className="p-4 space-y-2.5">
            <h3 className="font-bold text-slate-900 text-sm">Reorder Recommendations ({recs.length})</h3>
            {recsLoading ? (
              <div className="text-xs text-slate-500 py-4 text-center">Loading reorder recommendations...</div>
            ) : recsError ? (
              <div className="text-xs text-red-700 bg-red-50 rounded-lg p-3">Failed to load reorder recommendations.</div>
            ) : recs.length === 0 ? (
              <div className="text-xs text-slate-500 py-4 text-center">No reorder recommendations pending.</div>
            ) : (
              recs.map((rec) => {
                const ov = poOverrides[rec.id] || {
                  supplier_id: rec.recommended_supplier_id || activeSuppliers[0]?.id || "",
                  qty: String(rec.recommended_quantity || ""),
                  unit_cost: String(rec.verified_unit_cost || ""),
                  notes: "",
                };
                return (
                  <div key={rec.id} className="rounded-xl border border-slate-200 p-3 text-xs space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="font-bold text-slate-900">
                          {rec.recommendation_number} • {rec.ingredient_name} — Suggested: {rec.recommended_quantity} {rec.unit}
                          {rec.estimated_total_cost ? ` (Est. ₹${rec.estimated_total_cost})` : ""}
                        </div>
                        <div className="text-slate-600">
                          Usable: {rec.available_stock} • Incoming PO: {rec.incoming_po_stock} • Safety: {rec.safety_stock} • Lead Time: {rec.lead_time_days}d
                          {rec.avg_daily_consumption ? ` • 14d Avg: ${rec.avg_daily_consumption}/d` : ""}
                        </div>
                        <div className="text-[11px] text-amber-800">{(rec.trigger_reasons || []).join(" | ")}</div>
                        {rec.po_number && <div className="text-[11px] text-emerald-700 font-semibold">Linked Draft PO: {rec.po_number}</div>}
                      </div>
                      <Badge tone={rec.status === "draft_po_created" || rec.status === "fulfilled" ? "green" : rec.status === "dismissed" ? "slate" : "amber"}>
                        {rec.status}
                      </Badge>
                    </div>
                    {rec.status === "pending_review" && (
                      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5 pt-1 border-t border-slate-100">
                        <Select
                          value={ov.supplier_id}
                          onChange={(e) => setPoOverrides((p) => ({ ...p, [rec.id]: { ...ov, supplier_id: e.target.value } }))}
                        >
                          <option value="">Select Supplier...</option>
                          {activeSuppliers.map((s) => (
                            <option key={s.id} value={s.id}>{s.name}</option>
                          ))}
                        </Select>
                        <Input
                          type="number"
                          step="0.001"
                          value={ov.qty}
                          onChange={(e) => setPoOverrides((p) => ({ ...p, [rec.id]: { ...ov, qty: e.target.value } }))}
                          placeholder="Qty override"
                        />
                        <Input
                          type="number"
                          step="0.01"
                          value={ov.unit_cost}
                          onChange={(e) => setPoOverrides((p) => ({ ...p, [rec.id]: { ...ov, unit_cost: e.target.value } }))}
                          placeholder="Unit cost ₹"
                        />
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={async () => {
                            if (!ov.supplier_id) {
                              pushToast("Select an active supplier first", "error");
                              return;
                            }
                            try {
                              const res = await api.post(`/reordering/recommendations/${rec.id}/create-draft-po`, {
                                supplier_id: ov.supplier_id,
                                quantity_override: ov.qty.trim() ? ov.qty.trim() : null,
                                unit_cost_override: ov.unit_cost.trim() ? ov.unit_cost.trim() : null,
                                notes: ov.notes.trim() || null,
                              });
                              pushToast(`Draft PO ${res.data.draft_purchase_order.po_number} created (awaiting manager approval)`, "success");
                              refetchRecs();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Create Draft PO
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            try {
                              await api.post(`/reordering/recommendations/${rec.id}/dismiss`, { notes: "Dismissed by staff" });
                              refetchRecs();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Dismiss
                        </Button>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </Card>

          <Card className="p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-bold text-slate-900 text-sm">Configured Reorder Rules ({filteredRules.length} of {rules.length})</h3>
              <div className="flex items-center gap-2">
                <Input
                  value={ruleSearch}
                  onChange={(e) => setRuleSearch(e.target.value)}
                  placeholder="Filter rules by ingredient or vendor..."
                  className="w-56"
                />
                <Button size="sm" variant="outline" onClick={() => refetchRules()}>Refresh</Button>
              </div>
            </div>
            {rulesLoading ? (
              <div className="text-xs text-slate-500 py-4 text-center">Loading reorder rules...</div>
            ) : rulesError ? (
              <div className="text-xs text-red-700 bg-red-50 rounded-lg p-3">Failed to load reorder rules.</div>
            ) : filteredRules.length === 0 ? (
              <div className="text-xs text-slate-500 py-4 text-center">No reorder rules match your filter.</div>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 max-h-[420px] overflow-y-auto">
                {filteredRules.map((r) => (
                  <div key={r.inventory_item_id} className="rounded-xl border border-slate-200 p-2.5 text-xs space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-slate-900">{r.ingredient_name}</span>
                      <Badge tone={r.is_active ? "green" : "slate"}>{r.is_active ? "Active" : "Paused"}</Badge>
                    </div>
                    <div className="text-slate-600">
                      Min: {r.min_stock_level} • Reorder: {r.reorder_level} {r.unit} • Safety: {r.safety_stock}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      Lead: {r.supplier_lead_time_days}d • Cover: {r.target_days_of_cover}d • Vendor: {r.preferred_supplier_name || "Unset"}
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        setEditingRule({
                          inventory_item_id: r.inventory_item_id,
                          ingredient_name: r.ingredient_name,
                          unit: r.unit,
                          min_stock_level: String(r.min_stock_level),
                          reorder_level: String(r.reorder_level),
                          safety_stock: String(r.safety_stock),
                          supplier_lead_time_days: String(r.supplier_lead_time_days),
                          target_days_of_cover: String(r.target_days_of_cover),
                          preferred_supplier_id: r.preferred_supplier_id || "",
                          is_active: Boolean(r.is_active),
                        })
                      }
                    >
                      <Edit3 className="h-3 w-3" /> Edit Rule
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* Batch Quality Update Modal */}
      <Modal open={Boolean(qualityModal)} onClose={() => setQualityModal(null)} title="Update Batch Quality & Quarantine">
        {qualityModal && (
          <div className="space-y-3 text-xs">
            <div className="font-semibold text-slate-800">
              {qualityModal.batch.ingredient_name} • {qualityModal.batch.batch_number}
            </div>
            <Select
              value={qualityModal.targetStatus}
              onChange={(e) => setQualityModal({ ...qualityModal, targetStatus: e.target.value })}
            >
              <option value="approved">Approved (Usable)</option>
              <option value="pending">Pending Inspection</option>
              <option value="blocked">Blocked / Quarantined</option>
              <option value="rejected">Rejected (Write off remaining stock)</option>
            </Select>
            <Input
              value={qualityModal.reason}
              onChange={(e) => setQualityModal({ ...qualityModal, reason: e.target.value })}
              placeholder="Reason (required for blocked/rejected)"
            />
            <Input
              value={qualityModal.storage}
              onChange={(e) => setQualityModal({ ...qualityModal, storage: e.target.value })}
              placeholder="Storage location"
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setQualityModal(null)}>Cancel</Button>
              <Button
                size="sm"
                variant={qualityModal.targetStatus === "rejected" || qualityModal.targetStatus === "blocked" ? "danger" : "primary"}
                onClick={async () => {
                  try {
                    await api.patch(`/traceability/batches/${qualityModal.batch.id}/quality`, {
                      quality_status: qualityModal.targetStatus,
                      block_reason: qualityModal.reason.trim() || null,
                      storage_location: qualityModal.storage.trim() || null,
                    });
                    pushToast("Batch quality status updated", "success");
                    setQualityModal(null);
                    refetchBatches();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Confirm Quality Update
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Batch Movements Modal */}
      <Modal open={Boolean(movementsModal)} onClose={() => setMovementsModal(null)} title={`Batch Movements • ${movementsModal?.batch?.batch_number || ""}`}>
        {movementsModal && (
          <div className="space-y-2 max-h-80 overflow-y-auto text-xs">
            {movementsModal.rows.length === 0 ? (
              <div className="text-slate-500 text-center py-4">No movements recorded for this batch.</div>
            ) : (
              movementsModal.rows.map((m) => (
                <div key={m.id} className="rounded-lg border border-slate-200 p-2">
                  <div className="flex justify-between font-semibold">
                    <span>{m.movement_type}</span>
                    <span>{Number(m.quantity_delta) > 0 ? `+${m.quantity_delta}` : m.quantity_delta} {m.unit} (bal: {m.balance_after})</span>
                  </div>
                  <div className="text-slate-600">{m.notes || m.reference_type}</div>
                  <div className="text-[10px] text-slate-400">{m.created_at ? new Date(m.created_at).toLocaleString() : ""}</div>
                </div>
              ))
            )}
          </div>
        )}
      </Modal>

      {/* Approve Recall Confirmation Modal */}
      <Modal open={Boolean(confirmApproveRecall)} onClose={() => setConfirmApproveRecall(null)} title="Confirm Active Food Recall">
        {confirmApproveRecall && (
          <div className="space-y-3 text-xs">
            <p className="text-red-800 font-semibold">
              Approving recall <strong>{confirmApproveRecall.recall_number}</strong> will permanently mark all {confirmApproveRecall.affected_stock_batch_ids?.length || 0} batch(es) as RECALLED, block allocation, recalculate menu availability, and trigger critical alerts.
            </p>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setConfirmApproveRecall(null)}>Cancel</Button>
              <Button
                size="sm"
                variant="danger"
                onClick={async () => {
                  try {
                    await api.post(`/traceability/recalls/${confirmApproveRecall.id}/approve`);
                    pushToast("Recall approved and batches permanently marked RECALLED", "info");
                    setConfirmApproveRecall(null);
                    refetchRecalls();
                    refetchBatches();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Confirm Active Recall
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Edit / Resolve Recall Modal */}
      <Modal open={Boolean(editingRecall)} onClose={() => setEditingRecall(null)} title={`Update Recall • ${editingRecall?.recall?.recall_number || ""}`}>
        {editingRecall && (
          <div className="space-y-3 text-xs">
            <Select
              value={editingRecall.status}
              onChange={(e) => setEditingRecall({ ...editingRecall, status: e.target.value })}
            >
              {editingRecall.recall.status === "active_recall" && <option value="resolved">Resolved</option>}
              <option value="closed">Closed</option>
            </Select>
            <Input
              value={editingRecall.investigation_notes}
              onChange={(e) => setEditingRecall({ ...editingRecall, investigation_notes: e.target.value })}
              placeholder="Investigation notes"
            />
            <Input
              value={editingRecall.corrective_actions}
              onChange={(e) => setEditingRecall({ ...editingRecall, corrective_actions: e.target.value })}
              placeholder="Corrective actions taken (required to resolve)"
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setEditingRecall(null)}>Cancel</Button>
              <Button
                size="sm"
                variant="primary"
                onClick={async () => {
                  try {
                    await api.patch(`/traceability/recalls/${editingRecall.recall.id}`, {
                      status: editingRecall.status,
                      investigation_notes: editingRecall.investigation_notes.trim() || null,
                      corrective_actions: editingRecall.corrective_actions.trim() || null,
                    });
                    pushToast("Recall updated", "success");
                    setEditingRecall(null);
                    refetchRecalls();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Save Recall Update
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Edit Reorder Rule Modal */}
      <Modal open={Boolean(editingRule)} onClose={() => setEditingRule(null)} title={`Edit Reorder Rule • ${editingRule?.ingredient_name || ""}`}>
        {editingRule && (
          <div className="space-y-2.5 text-xs">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[11px] font-semibold text-slate-600">Min Stock ({editingRule.unit})</label>
                <Input type="number" step="0.001" value={editingRule.min_stock_level} onChange={(e) => setEditingRule({ ...editingRule, min_stock_level: e.target.value })} />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-600">Reorder Level ({editingRule.unit})</label>
                <Input type="number" step="0.001" value={editingRule.reorder_level} onChange={(e) => setEditingRule({ ...editingRule, reorder_level: e.target.value })} />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-600">Safety Stock ({editingRule.unit})</label>
                <Input type="number" step="0.001" value={editingRule.safety_stock} onChange={(e) => setEditingRule({ ...editingRule, safety_stock: e.target.value })} />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-600">Lead Time (days)</label>
                <Input type="number" value={editingRule.supplier_lead_time_days} onChange={(e) => setEditingRule({ ...editingRule, supplier_lead_time_days: e.target.value })} />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-600">Target Cover (days)</label>
                <Input type="number" value={editingRule.target_days_of_cover} onChange={(e) => setEditingRule({ ...editingRule, target_days_of_cover: e.target.value })} />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-600">Preferred Supplier</label>
                <Select value={editingRule.preferred_supplier_id} onChange={(e) => setEditingRule({ ...editingRule, preferred_supplier_id: e.target.value })}>
                  <option value="">None</option>
                  {activeSuppliers.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </Select>
              </div>
            </div>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={editingRule.is_active}
                onChange={(e) => setEditingRule({ ...editingRule, is_active: e.target.checked })}
              />
              <span>Rule Active</span>
            </label>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setEditingRule(null)}>Cancel</Button>
              <Button
                size="sm"
                variant="primary"
                onClick={async () => {
                  try {
                    await api.put(`/reordering/rules/${editingRule.inventory_item_id}`, {
                      min_stock_level: editingRule.min_stock_level,
                      reorder_level: editingRule.reorder_level,
                      safety_stock: editingRule.safety_stock,
                      supplier_lead_time_days: Number(editingRule.supplier_lead_time_days || 2),
                      target_days_of_cover: Number(editingRule.target_days_of_cover || 7),
                      preferred_supplier_id: editingRule.preferred_supplier_id || null,
                      is_active: editingRule.is_active,
                    });
                    pushToast("Reorder rule saved", "success");
                    setEditingRule(null);
                    refetchRules();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Save Rule
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
