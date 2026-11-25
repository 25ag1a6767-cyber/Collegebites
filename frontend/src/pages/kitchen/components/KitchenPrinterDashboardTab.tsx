import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  PauseCircle,
  Play,
  Plus,
  Printer,
  RefreshCw,
  RotateCcw,
  Wifi,
  WifiOff,
} from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { ReceiptSlip } from "../../../components/receipt/ReceiptSlip";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../../components/ui/Primitives";
import { useAppStore } from "../../../store/useAppStore";
import type { KitchenPrintDashboard, PrintJob, ReceiptSnapshot } from "../../../types";

interface Props {
  activeCanteenId: string;
}

export const KitchenPrinterDashboardTab: React.FC<Props> = ({ activeCanteenId }) => {
  const { pushToast } = useToast();
  const user = useAppStore((s) => s.user);
  const canRegisterPrinter = Boolean(
    user?.roles?.some((r) => ["super_admin", "college_admin", "canteen_manager"].includes(r))
  );

  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [busyJobId, setBusyJobId] = useState<string | null>(null);
  const [previewReceipt, setPreviewReceipt] = useState<ReceiptSnapshot | null>(null);

  // Register Printer / Local Agent Modal State
  const [regOpen, setRegOpen] = useState(false);
  const [devName, setDevName] = useState("Kitchen Main 80mm Thermal Printer");
  const [connType, setConnType] = useState<"local_usb" | "local_serial" | "network_escpos" | "os_spooler">("local_usb");
  const [netHost, setNetHost] = useState("192.168.1.200");
  const [netPort, setNetPort] = useState("9100");
  const [paperWidth, setPaperWidth] = useState<"80mm" | "58mm">("80mm");
  const [supportsResume, setSupportsResume] = useState(true);
  const [regBusy, setRegBusy] = useState(false);
  const [createdCreds, setCreatedCreds] = useState<{ agent_id: string; agent_token: string } | null>(null);

  const { data: dashboard, isLoading, refetch } = useQuery<KitchenPrintDashboard>({
    queryKey: ["kitchen-printer-dashboard", activeCanteenId, statusFilter],
    enabled: Boolean(activeCanteenId),
    staleTime: 3000,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
    queryFn: async () => {
      const qs = new URLSearchParams({ canteen_id: activeCanteenId });
      if (statusFilter !== "all") qs.set("status", statusFilter);
      return (await api.get(`/printing/kitchen/dashboard?${qs.toString()}`)).data;
    },
  });

  const handleRetryJob = async (job: PrintJob) => {
    setBusyJobId(job.id);
    try {
      await api.post(`/printing/jobs/${job.id}/retry`);
      pushToast(`Retrying print job for ${job.order_number || job.order_id}`, "success");
      refetch();
    } catch (err) {
      pushToast(getApiError(err, "Retry failed"), "error");
    } finally {
      setBusyJobId(null);
    }
  };

  const handleResumeJob = async (job: PrintJob) => {
    setBusyJobId(job.id);
    try {
      await api.post(`/printing/kitchen/jobs/${job.id}/resume`);
      pushToast(`Resumed print job for ${job.order_number || job.order_id}`, "success");
      refetch();
    } catch (err) {
      pushToast(getApiError(err, "Resume failed"), "error");
    } finally {
      setBusyJobId(null);
    }
  };

  const handleControlledReprint = async (job: PrintJob) => {
    const ref = job.order_number || job.order_id;
    setBusyJobId(job.id);
    try {
      await api.post(`/printing/kitchen/receipts/${encodeURIComponent(ref)}/reprint`);
      pushToast(`Queued controlled kitchen reprint for ${ref}`, "success");
      refetch();
    } catch (err) {
      pushToast(getApiError(err, "Controlled reprint failed"), "error");
    } finally {
      setBusyJobId(null);
    }
  };

  const handleViewIdenticalReceipt = async (job: PrintJob) => {
    const ref = job.order_number || job.order_id;
    setBusyJobId(job.id);
    try {
      const res = await api.get<ReceiptSnapshot>(`/tokens/receipts/${encodeURIComponent(ref)}`);
      setPreviewReceipt(res.data);
    } catch (err) {
      pushToast(getApiError(err, "Could not load receipt"), "error");
    } finally {
      setBusyJobId(null);
    }
  };

  const handleRegisterPrinter = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeCanteenId) return;
    setRegBusy(true);
    try {
      const res = await api.post("/printing/kitchen/printers/register", {
        canteen_id: activeCanteenId,
        department: "kitchen",
        device_name: devName,
        connection_type: connType,
        network_host: connType === "network_escpos" ? netHost : null,
        network_port: connType === "network_escpos" ? Number(netPort || 9100) : null,
        paper_width: paperWidth,
        supports_realtime_status: connType !== "os_spooler",
        supports_resume_offset: supportsResume && connType !== "os_spooler",
      });
      setCreatedCreds({ agent_id: res.data.agent_id, agent_token: res.data.agent_token });
      pushToast("Kitchen thermal printer registered!", "success");
      refetch();
    } catch (err) {
      pushToast(getApiError(err, "Failed to register kitchen printer"), "error");
    } finally {
      setRegBusy(false);
    }
  };

  const summary = dashboard?.summary;
  const printers = dashboard?.printers || [];
  const jobs = dashboard?.jobs || [];

  const statusTone = (status: string): "green" | "amber" | "red" | "blue" | "slate" => {
    if (status === "completed") return "green";
    if (status === "printing") return "blue";
    if (status === "paused") return "amber";
    if (status === "failed") return "red";
    return "slate";
  };

  return (
    <div className="space-y-4">
      <Card className="p-4 flex flex-wrap items-center justify-between gap-3 border-emerald-200 bg-emerald-50/60">
        <div>
          <h2 className="font-extrabold text-sm text-slate-900 flex items-center gap-2">
            <Printer className="h-4 w-4 text-[#76010d]" />
            Automatic Kitchen Receipt Queue &amp; Printer Recovery
          </h2>
          <p className="text-xs text-slate-600 mt-0.5">
            Every Razorpay-verified payment automatically queues the <b>exact canonical customer receipt</b> (identical branding, line items, totals, and QR code) to the kitchen printer without manual clicks.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh Status
          </Button>
          {canRegisterPrinter && (
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                setCreatedCreds(null);
                setRegOpen(true);
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Register Kitchen Printer
            </Button>
          )}
        </div>
      </Card>

      {/* Summary KPI Row */}
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        <Card className="p-3">
          <div className="text-[11px] font-bold uppercase text-slate-500">Currently Printing</div>
          <div className="mt-1 text-base font-black text-blue-700 truncate">
            {summary?.currently_printing_token
              ? `${summary.currently_printing_token} (${summary.currently_printing_order})`
              : "Idle"}
          </div>
        </Card>
        <Card className="p-3">
          <div className="text-[11px] font-bold uppercase text-slate-500">Pending Queue</div>
          <div className="mt-1 text-2xl font-black text-slate-900">{summary?.pending_count ?? 0}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[11px] font-bold uppercase text-amber-700">Paused (Paper Out)</div>
          <div className="mt-1 text-2xl font-black text-amber-700">{summary?.paused_count ?? 0}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[11px] font-bold uppercase text-emerald-700">Completed</div>
          <div className="mt-1 text-2xl font-black text-emerald-700">{summary?.completed_count ?? 0}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[11px] font-bold uppercase text-red-700">Failed</div>
          <div className="mt-1 text-2xl font-black text-red-700">{summary?.failed_count ?? 0}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[11px] font-bold uppercase text-slate-500">Printers Online</div>
          <div className="mt-1 text-2xl font-black text-slate-900">
            {summary?.online_printers ?? 0}/{summary?.total_printers ?? 0}
          </div>
        </Card>
      </div>

      {/* Registered Printers Live Hardware Status */}
      <Card className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-extrabold text-sm text-slate-900">Kitchen Printer Hardware Status</h3>
          <span className="text-xs text-slate-500">Auto-refreshes every 5s while tab is visible</span>
        </div>
        {printers.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 p-4 text-xs text-slate-600">
            No dedicated kitchen print agent is registered yet for this canteen. Paid receipts remain safely persisted in <b>pending</b> status inside PostgreSQL and will print automatically in FIFO order once a kitchen printer connects.
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {printers.map((p) => (
              <div key={p.id} className="rounded-xl border border-slate-200 p-3.5 space-y-2 bg-white">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-bold text-sm text-slate-900">{p.device_name}</div>
                    <div className="text-[11px] font-mono text-slate-500">
                      {p.agent_id} • {p.connection_type} • {p.paper_width}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5 justify-end">
                    <Badge tone={p.is_connected ? "green" : "red"}>
                      {p.is_connected ? <Wifi className="h-3 w-3 inline mr-1" /> : <WifiOff className="h-3 w-3 inline mr-1" />}
                      {p.is_connected ? "Connected" : "Disconnected"}
                    </Badge>
                    <Badge tone={p.is_online ? "green" : "slate"}>
                      {p.is_online ? "Online" : "Offline"}
                    </Badge>
                    <Badge tone={p.paper_status === "out_of_paper" ? "red" : p.paper_status === "low" ? "amber" : "green"}>
                      Paper: {p.paper_status.replace(/_/g, " ")}
                    </Badge>
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-between text-[11px] text-slate-500 border-t border-slate-100 pt-2">
                  <span>
                    Active Order: <b>{p.current_order_number || "None"}</b>
                  </span>
                  <span>
                    Continuation: <b>{p.supports_resume_offset ? "Exact Byte/Segment Offset" : "Controlled Reprint"}</b>
                  </span>
                </div>
                {p.paper_status === "out_of_paper" && (
                  <div className="rounded-lg bg-amber-50 border border-amber-200 p-2 text-xs text-amber-900 flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-amber-700 shrink-0" />
                    Paper roll empty — paused jobs will resume automatically as soon as staff loads a new roll.
                  </div>
                )}
                {p.last_error && (
                  <div className="text-[11px] text-red-700 bg-red-50 rounded-lg px-2 py-1">{p.last_error}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Queue Jobs Table */}
      <Card className="p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-extrabold text-sm text-slate-900">Kitchen Auto-Print Queue ({jobs.length})</h3>
          <div className="flex flex-wrap gap-1.5">
            {(["all", "pending", "printing", "paused", "completed", "failed"] as const).map((st) => (
              <button
                key={st}
                type="button"
                onClick={() => setStatusFilter(st)}
                className={`rounded-lg px-2.5 py-1 text-xs font-bold capitalize ${
                  statusFilter === st ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                }`}
              >
                {st}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="py-8 text-center text-xs text-slate-500">Loading kitchen print queue...</div>
        ) : jobs.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-500">No kitchen print jobs match this filter.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500 uppercase text-[10px]">
                  <th className="py-2 pr-3">Order &amp; Token</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Progress / Continuation</th>
                  <th className="py-2 pr-3">Printer Target</th>
                  <th className="py-2 pr-3">Retries / Notes</th>
                  <th className="py-2 text-right">Recovery Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {jobs.map((j) => (
                  <tr key={j.id} className="hover:bg-slate-50/80">
                    <td className="py-2.5 pr-3">
                      <div className="font-extrabold text-slate-900">
                        {j.pickup_token_code || "—"} • {j.order_number || j.order_id.slice(0, 8)}
                      </div>
                      <div className="text-[11px] text-slate-500">
                        {j.customer_name || "Customer"} • ₹{j.total_amount || "0.00"} {j.is_reprint ? "• REPRINT" : ""}
                      </div>
                    </td>
                    <td className="py-2.5 pr-3">
                      <Badge tone={statusTone(j.status)}>{j.status.toUpperCase()}</Badge>
                    </td>
                    <td className="py-2.5 pr-3 font-mono text-[11px] text-slate-700">
                      <div>
                        Seg {j.last_printed_segment_index}/{j.total_segments} ({j.last_printed_byte_offset}/{j.total_bytes} B)
                      </div>
                      <div className="text-[10px] text-slate-500">{j.resume_mode}</div>
                    </td>
                    <td className="py-2.5 pr-3 text-[11px] text-slate-700">
                      <div>{j.printer_name || j.printer_target}</div>
                      <div className="text-[10px] text-slate-400">{j.paper_width}</div>
                    </td>
                    <td className="py-2.5 pr-3 text-[11px]">
                      <div>Retries: {j.retry_count}/{j.max_retries}</div>
                      {(j.paused_reason || j.error_message) && (
                        <div className="text-red-700 max-w-xs truncate" title={j.error_message || j.paused_reason || ""}>
                          {j.paused_reason || j.error_message}
                        </div>
                      )}
                    </td>
                    <td className="py-2.5 text-right">
                      <div className="inline-flex flex-wrap gap-1.5 justify-end">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busyJobId === j.id}
                          onClick={() => handleViewIdenticalReceipt(j)}
                        >
                          <Eye className="h-3.5 w-3.5" /> Receipt
                        </Button>
                        {j.status === "paused" && (
                          <Button
                            size="sm"
                            variant="primary"
                            disabled={busyJobId === j.id}
                            onClick={() => handleResumeJob(j)}
                          >
                            <Play className="h-3.5 w-3.5" /> Resume
                          </Button>
                        )}
                        {(j.status === "failed" || j.status === "pending") && (
                          <Button
                            size="sm"
                            variant={j.status === "failed" ? "danger" : "outline"}
                            disabled={busyJobId === j.id}
                            onClick={() => handleRetryJob(j)}
                          >
                            <RotateCcw className="h-3.5 w-3.5" /> Retry
                          </Button>
                        )}
                        {j.status === "completed" && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busyJobId === j.id}
                            onClick={() => handleControlledReprint(j)}
                          >
                            <Printer className="h-3.5 w-3.5" /> Reprint
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Identical Receipt Preview Modal */}
      <Modal
        open={Boolean(previewReceipt)}
        onClose={() => setPreviewReceipt(null)}
        title={`Canonical Receipt (Identical Customer & Kitchen Copy) • ${previewReceipt?.order_number || ""}`}
      >
        {previewReceipt && <ReceiptSlip receipt={previewReceipt} allowStaffReprint onPrinted={() => refetch()} />}
      </Modal>

      {/* Register Kitchen Printer Modal */}
      <Modal
        open={regOpen}
        onClose={() => setRegOpen(false)}
        title="Register Kitchen Thermal Printer & Local Agent"
      >
        {createdCreds ? (
          <div className="space-y-3 text-xs">
            <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-3 text-emerald-900 flex items-start gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-700 shrink-0 mt-0.5" />
              <div>
                Printer registered! Copy these credentials into <code>print-agent/.env</code> on your kitchen PC. The token is displayed only once.
              </div>
            </div>
            <div className="rounded-xl bg-slate-900 text-slate-100 p-3 font-mono text-[11px] space-y-1 break-all">
              <div>PRINT_AGENT_ID={createdCreds.agent_id}</div>
              <div>PRINT_AGENT_TOKEN={createdCreds.agent_token}</div>
            </div>
            <Button variant="primary" className="w-full" onClick={() => setRegOpen(false)}>
              Done
            </Button>
          </div>
        ) : (
          <form onSubmit={handleRegisterPrinter} className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-bold text-slate-700">Printer Name</label>
              <Input value={devName} onChange={(e) => setDevName(e.target.value)} required />
            </div>
            <div className="grid gap-3 grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-bold text-slate-700">Connection Type</label>
                <Select value={connType} onChange={(e) => setConnType(e.target.value as any)}>
                  <option value="local_usb">Local USB / Print Agent</option>
                  <option value="local_serial">Local Serial (COM / ttyUSB)</option>
                  <option value="network_escpos">Network ESC/POS (TCP 9100)</option>
                  <option value="os_spooler">OS Spooler (Windows/CUPS)</option>
                </Select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold text-slate-700">Paper Width</label>
                <Select value={paperWidth} onChange={(e) => setPaperWidth(e.target.value as any)}>
                  <option value="80mm">80mm Thermal Roll</option>
                  <option value="58mm">58mm Thermal Roll</option>
                </Select>
              </div>
            </div>
            {connType === "network_escpos" && (
              <div className="grid gap-3 grid-cols-3">
                <div className="col-span-2">
                  <label className="mb-1 block text-xs font-bold text-slate-700">Printer IP / Host</label>
                  <Input value={netHost} onChange={(e) => setNetHost(e.target.value)} required />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-bold text-slate-700">Port</label>
                  <Input value={netPort} onChange={(e) => setNetPort(e.target.value)} required />
                </div>
              </div>
            )}
            <label className="flex items-center gap-2 text-xs text-slate-700">
              <input
                type="checkbox"
                checked={supportsResume}
                onChange={(e) => setSupportsResume(e.target.checked)}
                disabled={connType === "os_spooler"}
              />
              <span>Hardware supports ESC/POS real-time paper sensor &amp; byte-offset resume</span>
            </label>
            <Button type="submit" variant="primary" className="w-full" disabled={regBusy}>
              {regBusy ? "Registering..." : "Create Printer & Generate Agent Credentials"}
            </Button>
          </form>
        )}
      </Modal>
    </div>
  );
};
