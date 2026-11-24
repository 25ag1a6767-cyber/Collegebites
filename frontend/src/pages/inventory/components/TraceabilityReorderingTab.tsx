import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertOctagon, Download, FilePlus2, GitBranch, RefreshCw, ShieldAlert } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

interface Props {
  activeCanteenId: string;
  suppliers: any[];
}

export const TraceabilityReorderingTab: React.FC<Props> = ({ activeCanteenId, suppliers }) => {
  const { pushToast } = useToast();
  const [subTab, setSubTab] = useState<"traceability" | "recalls" | "reordering">("traceability");
  const [selectedChain, setSelectedChain] = useState<any | null>(null);
  const [recallTitle, setRecallTitle] = useState("");
  const [recallReason, setRecallReason] = useState("");
  const [recallBatchId, setRecallBatchId] = useState("");
  const [busy, setBusy] = useState(false);

  const { data: batches = [], refetch: refetchBatches } = useQuery<any[]>({
    queryKey: ["trace-batches", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/traceability/batches?canteen_id=${activeCanteenId}&include_empty=true`)).data,
  });

  const { data: recalls = [], refetch: refetchRecalls } = useQuery<any[]>({
    queryKey: ["trace-recalls", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "recalls"),
    queryFn: async () => (await api.get(`/traceability/recalls?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: recs = [], refetch: refetchRecs } = useQuery<any[]>({
    queryKey: ["reorder-recs", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "reordering"),
    queryFn: async () => (await api.get(`/reordering/recommendations?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: rules = [], refetch: refetchRules } = useQuery<any[]>({
    queryKey: ["reorder-rules", activeCanteenId],
    enabled: Boolean(activeCanteenId && subTab === "reordering"),
    queryFn: async () => (await api.get(`/reordering/rules?canteen_id=${activeCanteenId}`)).data,
  });

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
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4 space-y-2">
            <h3 className="font-bold text-slate-900 text-sm">Ingredient Batches (FEFO Ordered)</h3>
            <div className="space-y-2 max-h-[460px] overflow-y-auto">
              {batches.length === 0 ? (
                <div className="text-xs text-slate-500 py-6 text-center">No stock batches recorded yet.</div>
              ) : (
                batches.map((b) => (
                  <div key={b.id} className="rounded-xl border border-slate-200 p-3 text-xs space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-bold text-slate-900">{b.ingredient_name} • {b.batch_number}</div>
                      <div className="flex gap-1">
                        {b.is_expired && <Badge tone="red">EXPIRED</Badge>}
                        <Badge tone={b.quality_status === "approved" ? "green" : b.quality_status === "recalled" || b.quality_status === "blocked" ? "red" : "amber"}>
                          {b.quality_status}
                        </Badge>
                      </div>
                    </div>
                    <div className="text-slate-600">
                      Rem: <strong>{b.remaining_quantity}</strong> / {b.initial_quantity} {b.unit} • Exp: {b.expiry_date || "Not specified"} • PO: {b.po_number || "N/A"}
                    </div>
                    <div className="flex gap-2">
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
                        Inspect Trace Chain
                      </Button>
                      {b.quality_status === "approved" && (
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={async () => {
                            try {
                              await api.patch(`/traceability/batches/${b.id}/quality`, {
                                quality_status: "blocked",
                                block_reason: "Quarantined pending quality review",
                              });
                              pushToast("Batch quarantined", "info");
                              refetchBatches();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Block Batch
                        </Button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>

          <Card className="p-4 space-y-3">
            <h3 className="font-bold text-slate-900 text-sm">End-to-End Traceability Chain</h3>
            {!selectedChain ? (
              <div className="text-xs text-slate-500 py-8 text-center">
                Select any stock batch to trace Vendor → PO → GRN → Stock Batch → Production Batch → Orders.
              </div>
            ) : (
              <div className="space-y-2.5 text-xs">
                <div className="flex items-center gap-2">
                  <Badge tone={selectedChain.trace_completeness === "complete" ? "green" : "amber"}>
                    Completeness: {selectedChain.trace_completeness.toUpperCase()}
                  </Badge>
                  {selectedChain.missing_links?.length > 0 && (
                    <span className="text-amber-700">Missing links: {selectedChain.missing_links.join(", ")}</span>
                  )}
                </div>
                <div className="rounded-lg bg-slate-50 p-2.5 space-y-1">
                  <div><strong>Vendor:</strong> {selectedChain.vendor?.name || "Not linked"}</div>
                  <div><strong>Purchase Order:</strong> {selectedChain.purchase_order?.po_number || "Not linked"}</div>
                  <div><strong>Goods Receipt:</strong> {selectedChain.goods_receipt?.grn_number || "Not linked"}</div>
                  <div><strong>Production Batches:</strong> {selectedChain.production_batches?.length || 0}</div>
                  <div><strong>Affected Confirmed Orders:</strong> {selectedChain.affected_orders?.length || 0}</div>
                </div>
              </div>
            )}
          </Card>
        </div>
      )}

      {subTab === "recalls" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4 space-y-3">
            <div className="flex items-center gap-2 font-bold text-red-900">
              <ShieldAlert className="h-4 w-4" /> Initiate Ingredient Batch Recall
            </div>
            <Select value={recallBatchId} onChange={(e) => setRecallBatchId(e.target.value)}>
              <option value="">Select Suspected Stock Batch...</option>
              {batches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.ingredient_name} • {b.batch_number} ({b.quality_status})
                </option>
              ))}
            </Select>
            <Input value={recallTitle} onChange={(e) => setRecallTitle(e.target.value)} placeholder="Recall Title (e.g., Dairy Contamination Investigation)" />
            <Input value={recallReason} onChange={(e) => setRecallReason(e.target.value)} placeholder="Reason / Supplier notice details..." />
            <Button
              size="sm"
              variant="danger"
              disabled={busy || !recallBatchId || recallTitle.trim().length < 3 || recallReason.trim().length < 5}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.post("/traceability/recalls", {
                    canteen_id: activeCanteenId,
                    title: recallTitle.trim(),
                    reason: recallReason.trim(),
                    severity: "critical",
                    stock_batch_ids: [recallBatchId],
                  });
                  setRecallTitle("");
                  setRecallReason("");
                  pushToast("Recall initiated (pending authorized approval)", "info");
                  refetchRecalls();
                  refetchBatches();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Initiate Recall (Under Review)
            </Button>
          </Card>

          <Card className="p-4 space-y-2">
            <h3 className="font-bold text-slate-900 text-sm">Recall Register ({recalls.length})</h3>
            {recalls.map((r) => (
              <div key={r.id} className="rounded-xl border border-red-200 p-3 text-xs space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-900">{r.recall_number} — {r.title}</span>
                  <Badge tone={r.status === "active_recall" ? "red" : r.status === "resolved" ? "green" : "amber"}>{r.status}</Badge>
                </div>
                <div className="text-slate-600">
                  Batches: {r.affected_stock_batch_ids?.length || 0} • Prod Batches: {r.affected_production_batch_ids?.length || 0} • Orders: {r.affected_order_ids?.length || 0}
                </div>
                <div className="flex gap-2">
                  {r.status === "under_review" && (
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={async () => {
                        try {
                          await api.post(`/traceability/recalls/${r.id}/approve`);
                          pushToast("Recall approved and batches marked RECALLED", "info");
                          refetchRecalls();
                          refetchBatches();
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      Approve Active Recall
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
                    <Download className="h-3.5 w-3.5" /> PDF
                  </Button>
                </div>
              </div>
            ))}
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

          <Card className="p-4 space-y-2">
            <h3 className="font-bold text-slate-900 text-sm">Reorder Recommendations ({recs.length})</h3>
            {recs.length === 0 ? (
              <div className="text-xs text-slate-500 py-4 text-center">No reorder recommendations pending.</div>
            ) : (
              recs.map((rec) => (
                <div key={rec.id} className="rounded-xl border border-slate-200 p-3 text-xs flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="font-bold text-slate-900">
                      {rec.recommendation_number} • {rec.ingredient_name} — Suggested: {rec.recommended_quantity} {rec.unit}
                    </div>
                    <div className="text-slate-600">
                      Usable: {rec.available_stock} • Incoming PO: {rec.incoming_po_stock} • Safety: {rec.safety_stock} • Lead Time: {rec.lead_time_days}d
                    </div>
                    <div className="text-[11px] text-amber-800">{(rec.trigger_reasons || []).join(" | ")}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={rec.status === "draft_po_created" ? "green" : rec.status === "dismissed" ? "slate" : "amber"}>
                      {rec.status}
                    </Badge>
                    {rec.status === "pending_review" && (
                      <>
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={async () => {
                            const supId = rec.recommended_supplier_id || suppliers.find((s) => s.is_active)?.id;
                            if (!supId) {
                              pushToast("Configure an active supplier first", "error");
                              return;
                            }
                            try {
                              const res = await api.post(`/reordering/recommendations/${rec.id}/create-draft-po`, {
                                supplier_id: supId,
                              });
                              pushToast(`Draft PO ${res.data.draft_purchase_order.po_number} created (awaiting approval)`, "success");
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
                      </>
                    )}
                  </div>
                </div>
              ))
            )}
          </Card>

          <Card className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-slate-900 text-sm">Configured Reorder Rules ({rules.length})</h3>
              <Button size="sm" variant="outline" onClick={() => refetchRules()}>Refresh</Button>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {rules.slice(0, 12).map((r) => (
                <div key={r.inventory_item_id} className="rounded-xl border border-slate-200 p-2.5 text-xs">
                  <div className="font-bold text-slate-900">{r.ingredient_name}</div>
                  <div className="text-slate-600">
                    Reorder: {r.reorder_level} {r.unit} • Safety: {r.safety_stock} • Lead: {r.supplier_lead_time_days}d
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
};
