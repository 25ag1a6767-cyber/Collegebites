import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, Play, RefreshCw, ShieldAlert } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

export const ReconciliationPanel: React.FC<{
  isCollegeAdmin: boolean;
  activeCanteenId: string;
  downloadBlob: (url: string, filename: string) => Promise<void>;
}> = ({ isCollegeAdmin, activeCanteenId, downloadBlob }) => {
  const { pushToast } = useToast();
  const [gatewayFilter, setGatewayFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [runningAuto, setRunningAuto] = useState(false);
  const [selectedPaymentId, setSelectedPaymentId] = useState<string | null>(null);
  const [manualAmountByPay, setManualAmountByPay] = useState<Record<string, string>>({});
  const [settlementByPay, setSettlementByPay] = useState<Record<string, string>>({});

  const scopeParam = !isCollegeAdmin && activeCanteenId ? `canteen_id=${activeCanteenId}` : "";

  const { data: dash, refetch: refetchDash } = useQuery<any>({
    queryKey: ["reconcil-dashboard", activeCanteenId, isCollegeAdmin],
    queryFn: async () => (await api.get(`/payments/reconciliations/dashboard${scopeParam ? `?${scopeParam}` : ""}`)).data,
  });

  const { data: ledger = [], refetch: refetchLedger } = useQuery<any[]>({
    queryKey: ["reconcil-ledger", activeCanteenId, isCollegeAdmin, gatewayFilter, statusFilter, search],
    queryFn: async () => {
      const p = new URLSearchParams();
      if (scopeParam && activeCanteenId) p.set("canteen_id", activeCanteenId);
      if (gatewayFilter) p.set("gateway", gatewayFilter);
      if (statusFilter) p.set("reconciliation_status", statusFilter);
      if (search.trim()) p.set("search", search.trim());
      return (await api.get(`/payments/reconciliations/ledger?${p.toString()}`)).data;
    },
  });

  const { data: webhooks = [] } = useQuery<any[]>({
    queryKey: ["reconcil-webhooks"],
    enabled: isCollegeAdmin,
    queryFn: async () => (await api.get("/payments/webhooks?limit=30")).data,
  });

  const { data: txHistory = [] } = useQuery<any[]>({
    queryKey: ["reconcil-tx", selectedPaymentId],
    enabled: Boolean(selectedPaymentId),
    queryFn: async () => (await api.get(`/payments/${selectedPaymentId}/transactions`)).data,
  });

  const refreshAll = () => {
    void refetchDash();
    void refetchLedger();
  };

  const handleAutoRun = async () => {
    setRunningAuto(true);
    try {
      const res = (
        await api.post("/payments/reconciliations/auto-run", {
          canteen_id: !isCollegeAdmin && activeCanteenId ? activeCanteenId : null,
          fetch_gateway: true,
        })
      ).data;
      pushToast(
        `Reconciled ${res.total_checked} payments • ${res.matched_count} matched • ${res.discrepancy_count} discrepancies`,
        res.discrepancy_count > 0 ? "info" : "success"
      );
      refreshAll();
    } catch (err) {
      pushToast(getApiError(err), "error");
    } finally {
      setRunningAuto(false);
    }
  };

  const exportParams = new URLSearchParams();
  if (scopeParam && activeCanteenId) exportParams.set("canteen_id", activeCanteenId);
  if (gatewayFilter) exportParams.set("gateway", gatewayFilter);
  if (statusFilter) exportParams.set("reconciliation_status", statusFilter);
  const expQuery = exportParams.toString() ? `?${exportParams.toString()}` : "";

  return (
    <div className="space-y-5">
      <Card className="p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-extrabold text-slate-900">
              Financial Reconciliation &amp; Settlement Ledger
            </h2>
            <p className="text-xs text-slate-500">
              Gateway cross-checking across Orders, Razorpay &amp; Counter POS • Strictly Online-Only &amp; No Refunds Policy
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {isCollegeAdmin && (
              <Button size="sm" onClick={handleAutoRun} disabled={runningAuto}>
                <Play className="h-3.5 w-3.5" /> {runningAuto ? "Reconciling..." : "Run Auto-Reconcile"}
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => void downloadBlob(`/payments/reconciliations/export/csv${expQuery}`, "collegebites-reconciliation.csv")}
            >
              <Download className="h-3.5 w-3.5" /> CSV
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void downloadBlob(`/payments/reconciliations/export/xlsx${expQuery}`, "collegebites-reconciliation.xlsx")}
            >
              <Download className="h-3.5 w-3.5" /> Excel (.xlsx)
            </Button>
            <Button size="sm" variant="ghost" onClick={refreshAll}>
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-[11px] font-semibold text-slate-500">Verified Collections</div>
            <div className="text-lg font-black text-emerald-700">₹{(dash?.verified_collections_inr ?? 0).toFixed(2)}</div>
          </div>
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-[11px] font-semibold text-slate-500">Confirmed</div>
            <div className="text-lg font-black text-slate-900">
              {dash?.confirmed_count ?? 0} / {dash?.total_attempts ?? 0}
            </div>
          </div>
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-[11px] font-semibold text-slate-500">Matched Ledger</div>
            <div className="text-lg font-black text-emerald-700">{dash?.matched_count ?? 0}</div>
          </div>
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-[11px] font-semibold text-slate-500">Discrepancies</div>
            <div className="text-lg font-black text-red-600">
              {dash?.discrepancy_count ?? 0} (₹{(dash?.discrepancy_total_inr ?? 0).toFixed(2)})
            </div>
          </div>
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-[11px] font-semibold text-slate-500">Pending / Failed</div>
            <div className="text-lg font-black text-amber-700">
              {dash?.pending_count ?? 0} / {dash?.failed_count ?? 0}
            </div>
          </div>
          <div className="rounded-xl bg-slate-50 p-3">
            <div className="text-[11px] font-semibold text-slate-500">Invalid Webhooks</div>
            <div className="text-lg font-black text-rose-700">{dash?.invalid_webhooks_count ?? 0}</div>
          </div>
        </div>

        {dash?.gateway_breakdown?.length > 0 && (
          <div className="flex flex-wrap gap-2 text-xs">
            {dash.gateway_breakdown.map((g: any) => (
              <div key={g.provider} className="rounded-xl border border-slate-200 px-3 py-2">
                <strong className="uppercase">{g.provider}</strong>: {g.confirmed} confirmed • ₹{g.amount_inr.toFixed(2)} •{" "}
                <span className="text-red-600">{g.failed} failed</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-bold text-slate-900">Transaction &amp; Reconciliation Ledger ({ledger.length})</h3>
          <div className="flex flex-wrap gap-2">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search order # / ref..."
              className="w-44"
            />
            <Select value={gatewayFilter} onChange={(e) => setGatewayFilter(e.target.value)} className="w-36">
              <option value="">All Gateways</option>
              <option value="razorpay">Razorpay</option>
              <option value="counter_pos">Counter POS</option>
            </Select>
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="w-40">
              <option value="">All States</option>
              <option value="matched">Matched</option>
              <option value="discrepancy">Discrepancy</option>
              <option value="pending">Pending</option>
              <option value="failed">Failed</option>
              <option value="unreconciled">Unreconciled</option>
            </Select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                <th className="py-2 pr-3">Order</th>
                <th className="py-2 pr-3">Gateway</th>
                <th className="py-2 pr-3">Payment</th>
                <th className="py-2 pr-3">Expected / Settled</th>
                <th className="py-2 pr-3">Reconciliation</th>
                <th className="py-2 pr-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {ledger.map((row) => {
                const isSelected = selectedPaymentId === row.payment_id;
                const manualVal = manualAmountByPay[row.payment_id] ?? String(row.expected_amount.toFixed(2));
                const settleVal = settlementByPay[row.payment_id] ?? (row.gateway_settlement_id || "");
                return (
                  <React.Fragment key={row.payment_id}>
                    <tr className={`border-b border-slate-100 ${row.reconciliation_status === "discrepancy" ? "bg-red-50/40" : ""}`}>
                      <td className="py-2.5 pr-3">
                        <div className="font-bold text-slate-900">{row.order_number}</div>
                        <div className="text-[11px] text-slate-500">
                          {row.canteen_name} • {row.order_status}
                        </div>
                      </td>
                      <td className="py-2.5 pr-3">
                        <div className="font-semibold uppercase">{row.provider}</div>
                        <div className="font-mono text-[10px] text-slate-500">
                          {row.payment_reference || row.provider_order_id || "-"}
                        </div>
                      </td>
                      <td className="py-2.5 pr-3">
                        <Badge
                          tone={
                            row.payment_status === "CONFIRMED"
                              ? "green"
                              : row.payment_status === "FAILED"
                              ? "red"
                              : "amber"
                          }
                        >
                          {row.payment_status}
                        </Badge>
                      </td>
                      <td className="py-2.5 pr-3 font-mono">
                        ₹{row.expected_amount.toFixed(2)} / ₹{row.settled_amount.toFixed(2)}
                        {row.discrepancy_amount !== 0 && (
                          <div className="text-red-600 font-bold">Diff: ₹{row.discrepancy_amount.toFixed(2)}</div>
                        )}
                      </td>
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center gap-1">
                          {row.reconciliation_status === "matched" && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />}
                          {row.reconciliation_status === "discrepancy" && <AlertTriangle className="h-3.5 w-3.5 text-red-600" />}
                          <Badge
                            tone={
                              row.reconciliation_status === "matched"
                                ? "green"
                                : row.reconciliation_status === "discrepancy" || row.reconciliation_status === "failed"
                                ? "red"
                                : "amber"
                            }
                          >
                            {row.reconciliation_status}
                          </Badge>
                        </div>
                        {row.discrepancy_type !== "none" && (
                          <div className="text-[10px] text-red-700 font-mono">{row.discrepancy_type}</div>
                        )}
                      </td>
                      <td className="py-2.5 pr-3">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setSelectedPaymentId(isSelected ? null : row.payment_id)}
                          >
                            {isSelected ? "Hide Steps" : "Audit"}
                          </Button>
                          {isCollegeAdmin && (
                            <>
                              <Input
                                type="number"
                                step="0.01"
                                value={manualVal}
                                onChange={(e) =>
                                  setManualAmountByPay((p) => ({ ...p, [row.payment_id]: e.target.value }))
                                }
                                className="w-20"
                              />
                              <Input
                                value={settleVal}
                                onChange={(e) =>
                                  setSettlementByPay((p) => ({ ...p, [row.payment_id]: e.target.value }))
                                }
                                placeholder="Settle ID"
                                className="w-24"
                              />
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={async () => {
                                  try {
                                    await api.post("/payments/reconcile", {
                                      payment_id: row.payment_id,
                                      settled_amount: Number(manualVal || 0),
                                      gateway_settlement_id: settleVal || undefined,
                                      notes: "Verified in Reconciliation Console",
                                    });
                                    pushToast("Reconciliation saved", "success");
                                    refreshAll();
                                  } catch (err) {
                                    pushToast(getApiError(err), "error");
                                  }
                                }}
                              >
                                Save
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                    {isSelected && (
                      <tr className="bg-slate-50">
                        <td colSpan={6} className="p-3 text-xs space-y-1">
                          <div className="font-bold text-slate-700">Gateway Transaction History</div>
                          {txHistory.length === 0 ? (
                            <div className="text-slate-400">No gateway transaction steps logged.</div>
                          ) : (
                            txHistory.map((tx) => (
                              <div key={tx.id} className="flex justify-between border-b border-slate-200/70 py-1">
                                <span className="font-mono">
                                  {tx.transaction_type} • {tx.status} ({tx.external_reference || "-"})
                                </span>
                                <span>
                                  ₹{tx.amount.toFixed(2)} • {new Date(tx.created_at).toLocaleString()}
                                </span>
                              </div>
                            ))
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {isCollegeAdmin && webhooks.length > 0 && (
        <Card className="p-5 space-y-3">
          <h3 className="font-bold text-slate-900 flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-amber-600" /> Recent Payment Webhook Callbacks ({webhooks.length})
          </h3>
          <div className="space-y-1.5 text-xs">
            {webhooks.map((wh) => (
              <div key={wh.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 py-1.5">
                <div>
                  <span className="font-bold uppercase">{wh.provider}</span> •{" "}
                  <span className="font-mono">{wh.event_type}</span> ({wh.event_id})
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={wh.signature_verified ? "green" : "red"}>
                    {wh.signature_verified ? "Verified" : "Invalid Sig"}
                  </Badge>
                  <Badge tone={wh.processed ? "green" : "amber"}>{wh.processed ? "Processed" : "Failed"}</Badge>
                  {wh.processing_error && <span className="text-red-600">{wh.processing_error}</span>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
};
