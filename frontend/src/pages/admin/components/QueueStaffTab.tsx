import React, { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Flame, Layers, RefreshCw, Timer, Zap } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { useRealtimeSync } from "../../../hooks/useRealtimeSync";
import { RealtimeStatusBadge } from "../../../components/ui/RealtimeStatusBadge";
import { Badge, Button, Card, ConfirmModal, Input, useToast } from "../../../components/ui/Primitives";
export { StaffTab } from "./StaffManagementPanel";

export const QueueTab: React.FC<{ activeCanteenId: string; queueDash: any; refetchQueue: () => void }> = ({
  activeCanteenId,
  queueDash,
  refetchQueue,
}) => {
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const [maxConcurrent, setMaxConcurrent] = useState(String(queueDash?.max_concurrent_orders || 80));
  const [defaultPrepMins, setDefaultPrepMins] = useState("10");
  const [slotDate, setSlotDate] = useState(new Date().toISOString().slice(0, 10));
  const [startTime, setStartTime] = useState("12:00");
  const [endTime, setEndTime] = useState("13:00");
  const [slotCap, setSlotCap] = useState("40");
  const [busyOrderId, setBusyOrderId] = useState<string | null>(null);
  const [escalating, setEscalating] = useState(false);
  const [confirmPauseOpen, setConfirmPauseOpen] = useState(false);
  const [pauseBusy, setPauseBusy] = useState(false);

  const { data: accuracyData, isLoading: accLoading, isError: accError } = useQuery<any>({
    queryKey: ["queue-accuracy", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/queue/canteens/${activeCanteenId}/accuracy?days=30`)).data,
    refetchInterval: 60000,
  });

  const { status: queueSyncStatus, lastSyncedAt: queueLastSyncedAt } = useRealtimeSync<{ queue?: any }>({
    enabled: Boolean(activeCanteenId),
    ssePath: activeCanteenId ? `/realtime/queue/${activeCanteenId}/stream` : null,
    wsPath: activeCanteenId ? `/ws/kitchen/${activeCanteenId}` : null,
    queryKeys: [["admin-queue", activeCanteenId]],
    onSnapshot: (snap) => {
      if (snap?.queue) {
        qc.setQueryData(["admin-queue", activeCanteenId], snap.queue);
      }
    },
  });

  const { data: pickupSlots = [], refetch: refetchSlots } = useQuery<any[]>({
    queryKey: ["admin-pickup-slots", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/orders/slots/${activeCanteenId}`)).data,
  });

  useEffect(() => {
    if (queueDash?.max_concurrent_orders) {
      setMaxConcurrent(String(queueDash.max_concurrent_orders));
    }
    if (queueDash?.estimated_wait_minutes) {
      setDefaultPrepMins(String(Math.max(1, Math.min(60, Number(queueDash.estimated_wait_minutes) || 10))));
    }
  }, [queueDash?.max_concurrent_orders, queueDash?.estimated_wait_minutes]);

  const activeQueue: any[] = queueDash?.active_orders_queue || [];
  const delayedOrders: any[] = queueDash?.delayed_orders || [];
  const counters: any[] = queueDash?.counter_workloads || [];

  const handleReassignCounter = async (orderId: string, counterId: string) => {
    setBusyOrderId(orderId);
    try {
      const res = await api.post(`/queue/orders/${orderId}/assign-counter`, { counter_id: counterId });
      qc.setQueryData(["admin-queue", activeCanteenId], res.data);
      pushToast("Order counter updated", "success");
    } catch (err) {
      pushToast(getApiError(err, "Counter reassignment failed"), "error");
    } finally {
      setBusyOrderId(null);
    }
  };

  const handleTogglePriority = async (orderId: string, nextPriority: boolean) => {
    setBusyOrderId(orderId);
    try {
      await api.post(`/kitchen/orders/${orderId}/priority`, { is_priority: nextPriority });
      await refetchQueue();
      pushToast(nextPriority ? "Order marked priority fast-track" : "Priority flag cleared", "success");
    } catch (err) {
      pushToast(getApiError(err, "Failed to update priority"), "error");
    } finally {
      setBusyOrderId(null);
    }
  };

  const handleEscalateOverdue = async () => {
    setEscalating(true);
    try {
      const res = await api.post(`/queue/canteens/${activeCanteenId}/escalate-overdue`);
      if (res.data?.dashboard) {
        qc.setQueryData(["admin-queue", activeCanteenId], res.data.dashboard);
      } else {
        refetchQueue();
      }
      const cnt = Number(res.data?.escalated_count || 0);
      pushToast(
        cnt > 0 ? `Escalated ${cnt} overdue order(s) to priority` : "No overdue orders needed escalation",
        cnt > 0 ? "success" : "info"
      );
    } catch (err) {
      pushToast(getApiError(err, "Escalation failed"), "error");
    } finally {
      setEscalating(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Live Queue Header & Real-time Badge */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">Smart Live Queue & Counter Balancing</h2>
          <p className="text-xs text-slate-500">
            Real-time queue order tracking, express counter routing, SLA wait recalculation & auto-removal on handover.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RealtimeStatusBadge status={queueSyncStatus} lastSyncedAt={queueLastSyncedAt} />
          <Button size="sm" variant="outline" disabled={escalating} onClick={() => void handleEscalateOverdue()}>
            <Zap className="h-3.5 w-3.5" /> {escalating ? "Escalating..." : "Auto-Escalate Overdue"}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => refetchQueue()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </Button>
        </div>
      </div>

      {/* Live KPI Cards */}
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Card className="p-3.5">
          <div className="text-[11px] font-bold uppercase text-slate-500">Active Queue</div>
          <div className="mt-1 text-2xl font-black text-slate-900">{queueDash?.active_order_count ?? 0}</div>
          <div className="text-[11px] text-slate-500">Crowd: {queueDash?.crowd_level || "LOW"}</div>
        </Card>
        <Card className="p-3.5">
          <div className="text-[11px] font-bold uppercase text-amber-700">Waiting Prep</div>
          <div className="mt-1 text-2xl font-black text-amber-700">{queueDash?.waiting_prep_count ?? 0}</div>
          <div className="text-[11px] text-slate-500">
            Placed {queueDash?.placed_count ?? 0} / Acc {queueDash?.accepted_count ?? 0}
          </div>
        </Card>
        <Card className="p-3.5">
          <div className="text-[11px] font-bold uppercase text-indigo-700">Preparing</div>
          <div className="mt-1 text-2xl font-black text-indigo-700">{queueDash?.preparing_count ?? 0}</div>
          <div className="text-[11px] text-slate-500">Load {queueDash?.kitchen_workload_percent ?? 0}%</div>
        </Card>
        <Card className="p-3.5">
          <div className="text-[11px] font-bold uppercase text-emerald-700">Ready for Pickup</div>
          <div className="mt-1 text-2xl font-black text-emerald-700">{queueDash?.ready_count ?? 0}</div>
          <div className="text-[11px] text-slate-500">Removed on completion</div>
        </Card>
        <Card className="p-3.5">
          <div className="text-[11px] font-bold uppercase text-slate-500 flex items-center gap-1">
            <Timer className="h-3.5 w-3.5" /> Avg Wait Time
          </div>
          <div className="mt-1 text-2xl font-black text-slate-900">{queueDash?.average_wait_minutes ?? 0}m</div>
          <div className="text-[11px] text-slate-500">{queueDash?.orders_per_minute ?? 0} orders/min</div>
        </Card>
        <Card className={`p-3.5 ${delayedOrders.length > 0 ? "border-red-300 bg-red-50/40" : ""}`}>
          <div className="text-[11px] font-bold uppercase text-red-700 flex items-center gap-1">
            <AlertTriangle className="h-3.5 w-3.5" /> Delayed / Overdue
          </div>
          <div className="mt-1 text-2xl font-black text-red-700">{queueDash?.delayed_order_count ?? 0}</div>
          <div className="text-[11px] text-slate-500">{queueDash?.on_duty_staff_count ?? 0} staff on duty</div>
        </Card>
      </div>

      {queueDash?.waiting_time_available === false && (
        <div className="rounded-2xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 font-semibold">
          {queueDash?.waiting_time_message || "Waiting time currently unavailable."}
        </div>
      )}

      {(queueDash?.congestion_warnings?.length || 0) > 0 && (
        <div className="rounded-2xl border border-amber-300 bg-amber-50/70 p-3.5 text-xs text-amber-950 space-y-1">
          <div className="font-bold flex items-center gap-1.5">
            <AlertTriangle className="h-4 w-4 text-amber-600" /> Live Queue Congestion &amp; Capacity Warnings
          </div>
          <ul className="list-disc pl-5 space-y-0.5">
            {queueDash.congestion_warnings.map((w: string, i: number) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Prediction Accuracy Telemetry (Real QueueEstimateHistory vs Actual Ready Time) */}
      <Card className="p-4 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-bold text-slate-900">Wait-Time Prediction Accuracy (30-Day Real Audit)</h3>
          <Badge tone="slate">Data: {accuracyData?.data_classification || "calculated"}</Badge>
        </div>
        {accLoading ? (
          <div className="text-xs text-slate-500">Loading prediction accuracy metrics...</div>
        ) : accError ? (
          <div className="text-xs text-red-700">Unable to load wait-time accuracy telemetry.</div>
        ) : !accuracyData || accuracyData.sample_count === 0 ? (
          <div className="text-xs text-slate-500">
            {accuracyData?.message || "Insufficient historical data to evaluate queue prediction accuracy."}
          </div>
        ) : (
          <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-5 text-xs">
            <div className="rounded-xl bg-slate-50 p-2.5">
              <div className="text-[10px] font-bold uppercase text-slate-500">Samples</div>
              <div className="text-base font-black text-slate-900">{accuracyData.sample_count}</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-2.5">
              <div className="text-[10px] font-bold uppercase text-slate-500">MAE</div>
              <div className="text-base font-black text-slate-900">{accuracyData.mae_minutes}m</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-2.5">
              <div className="text-[10px] font-bold uppercase text-slate-500">Median Error</div>
              <div className="text-base font-black text-slate-900">{accuracyData.median_error_minutes}m</div>
            </div>
            <div className="rounded-xl bg-emerald-50 p-2.5">
              <div className="text-[10px] font-bold uppercase text-emerald-700">Within ±5 min</div>
              <div className="text-base font-black text-emerald-800">{accuracyData.within_5_min_percent}%</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-2.5">
              <div className="text-[10px] font-bold uppercase text-slate-500">Est vs Actual Avg</div>
              <div className="text-sm font-black text-slate-900">
                {accuracyData.average_estimated_minutes}m / {accuracyData.average_actual_minutes}m
              </div>
            </div>
          </div>
        )}
      </Card>

      {delayedOrders.length > 0 && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-3.5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-xs text-red-900 font-semibold">
            <AlertTriangle className="h-4 w-4 text-red-600 shrink-0" />
            <span>
              <strong>{delayedOrders.length} Delayed Order Alert(s):</strong>{" "}
              {delayedOrders
                .slice(0, 4)
                .map((d) => `${d.token_code || d.order_number} (${d.elapsed_minutes}m / ${d.counter_name})`)
                .join(", ")}
            </span>
          </div>
          <Button size="sm" variant="danger" disabled={escalating} onClick={() => void handleEscalateOverdue()}>
            {escalating ? "Escalating..." : "Prioritize Overdue Orders"}
          </Button>
        </div>
      )}

      {/* Counter Load Balancing Overview */}
      {counters.length > 0 && (
        <Card className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Layers className="h-4 w-4 text-[#76010d]" /> Counter Load & Express Capacity
            </h3>
            <span className="text-xs text-slate-500">Auto-balanced checkout counter routing active</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {counters.map((c) => (
              <div
                key={c.counter_id}
                className={`rounded-xl border p-3 ${
                  c.is_overloaded ? "border-red-300 bg-red-50/40" : "border-slate-200 bg-slate-50/60"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="font-bold text-sm text-slate-900 truncate">{c.name}</div>
                  <Badge tone={c.counter_type === "express" ? "green" : "slate"}>
                    {String(c.counter_type || "pickup").toUpperCase()}
                  </Badge>
                </div>
                <div className="mt-1 text-xs text-slate-600">
                  In Queue: <strong>{c.waiting_orders ?? c.active_orders}</strong> / {c.max_queue_capacity} • Ready:{" "}
                  <strong>{c.ready_orders ?? 0}</strong> ({c.utilization_percent}%)
                </div>
                <div className="mt-2 h-2 w-full rounded-full bg-slate-200 overflow-hidden">
                  <div
                    className={`h-full transition-all ${
                      c.utilization_percent >= 85
                        ? "bg-red-500"
                        : c.utilization_percent >= 55
                        ? "bg-amber-500"
                        : "bg-emerald-500"
                    }`}
                    style={{ width: `${Math.min(100, c.utilization_percent)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Active Queue Table (Auto-excludes COMPLETED/CANCELLED/REJECTED) */}
      <Card className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
            <Flame className="h-4 w-4 text-amber-600" /> Live Waiting & Ready Queue ({activeQueue.length})
          </h3>
          <span className="text-xs text-slate-500">Priority orders lead queue • Completed orders auto-remove</span>
        </div>
        {activeQueue.length === 0 ? (
          <div className="py-8 text-center text-sm text-slate-500">
            No active orders currently in queue. Completed orders are automatically cleared.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500 uppercase text-[10px]">
                  <th className="py-2 pr-3">Pos</th>
                  <th className="py-2 pr-3">Token / Order</th>
                  <th className="py-2 pr-3">Customer</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Wait / Elapsed</th>
                  <th className="py-2 pr-3">Assigned Counter</th>
                  <th className="py-2 text-right">Priority</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {activeQueue.map((row) => (
                  <tr key={row.order_id} className={row.is_overdue ? "bg-red-50/40" : ""}>
                    <td className="py-2 pr-3 font-black text-[#5d010a]">
                      {row.status === "READY" ? "RDY" : `#${row.queue_position ?? "-"}`}
                    </td>
                    <td className="py-2 pr-3">
                      <div className="font-bold text-slate-900">
                        {row.token_code || row.order_number}{" "}
                        {row.is_priority && <Badge tone="red">PRIORITY</Badge>}
                      </div>
                      <div className="text-[11px] text-slate-500">
                        {row.order_number} • {row.item_count} items
                      </div>
                    </td>
                    <td className="py-2 pr-3 font-medium text-slate-800">{row.customer_name}</td>
                    <td className="py-2 pr-3">
                      <Badge
                        tone={
                          row.status === "READY"
                            ? "green"
                            : row.status === "PREPARING"
                            ? "blue"
                            : "amber"
                        }
                      >
                        {row.status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <div className="font-semibold text-slate-800">
                        {row.status === "READY" ? "0m wait" : `~${row.dynamic_wait_minutes ?? row.estimated_prep_minutes}m ETA`}
                      </div>
                      <div className={`text-[11px] ${row.is_overdue ? "text-red-700 font-bold" : "text-slate-500"}`}>
                        {row.elapsed_minutes}m elapsed{row.is_overdue ? " • OVERDUE" : ""}
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <select
                        aria-label={`Counter for ${row.order_number}`}
                        disabled={busyOrderId === row.order_id || counters.length === 0}
                        value={row.counter_id}
                        onChange={(e) => void handleReassignCounter(row.order_id, e.target.value)}
                        className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-800"
                      >
                        {counters.map((c) => (
                          <option key={c.counter_id} value={c.counter_id}>
                            {c.name} ({c.counter_type})
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="py-2 text-right">
                      <Button
                        size="sm"
                        variant={row.is_priority ? "danger" : "outline"}
                        disabled={busyOrderId === row.order_id}
                        onClick={() => void handleTogglePriority(row.order_id, !row.is_priority)}
                      >
                        {row.is_priority ? "Clear Priority" : "Prioritize"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Crowd Control + Pickup Slot Configuration */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-bold text-slate-900">Queue & Crowd Controls</h2>
              <div className="text-xs text-slate-500">
                Kitchen Workload: {queueDash?.kitchen_workload_percent ?? 0}% • Staff On Duty:{" "}
                {queueDash?.on_duty_staff_count ?? 1}
              </div>
            </div>
            <Button
              size="sm"
              variant={queueDash?.ordering_paused ? "success" : "danger"}
              disabled={pauseBusy}
              onClick={async () => {
                if (!queueDash?.ordering_paused) {
                  setConfirmPauseOpen(true);
                  return;
                }
                setPauseBusy(true);
                try {
                  await api.patch(`/queue/canteens/${activeCanteenId}/controls`, {
                    ordering_paused: false,
                    pause_reason: null,
                  });
                  pushToast("Ordering resumed for this canteen", "success");
                  refetchQueue();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setPauseBusy(false);
                }
              }}
            >
              {queueDash?.ordering_paused ? "Resume Ordering" : "Pause Ordering"}
            </Button>
          </div>

          <div className="grid grid-cols-2 gap-2 border-t border-slate-100 pt-3">
            <label className="text-[11px] font-semibold text-slate-600 space-y-1">
              <span>Max Concurrent Orders</span>
              <Input type="number" value={maxConcurrent} onChange={(e) => setMaxConcurrent(e.target.value)} />
            </label>
            <label className="text-[11px] font-semibold text-slate-600 space-y-1">
              <span>Default Prep (mins)</span>
              <Input type="number" value={defaultPrepMins} onChange={(e) => setDefaultPrepMins(e.target.value)} />
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              onClick={async () => {
                try {
                  await api.patch(`/queue/canteens/${activeCanteenId}/controls`, {
                    max_concurrent_orders: Number(maxConcurrent),
                    default_prep_time_minutes: Number(defaultPrepMins),
                  });
                  pushToast("Queue controls updated", "success");
                  refetchQueue();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Save Queue Settings
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                try {
                  await api.patch(`/queue/canteens/${activeCanteenId}/controls`, {
                    auto_throttle_enabled: !queueDash?.auto_throttle_enabled,
                  });
                  pushToast(
                    queueDash?.auto_throttle_enabled ? "Auto-throttle disabled" : "Auto-throttle enabled",
                    "info"
                  );
                  refetchQueue();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Auto-Throttle: {queueDash?.auto_throttle_enabled ? "ON" : "OFF"}
            </Button>
          </div>
        </Card>

        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900">Create / Update Pickup Slot</h2>
          <div className="grid grid-cols-2 gap-2">
            <Input type="date" value={slotDate} onChange={(e) => setSlotDate(e.target.value)} />
            <Input type="number" value={slotCap} onChange={(e) => setSlotCap(e.target.value)} placeholder="Slot capacity" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
            <Input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
          </div>
          <Button
            size="sm"
            onClick={async () => {
              try {
                await api.post(`/queue/canteens/${activeCanteenId}/slots`, {
                  slot_date: slotDate,
                  start_time: `${startTime}:00`,
                  end_time: `${endTime}:00`,
                  capacity: Number(slotCap),
                  is_active: true,
                });
                refetchSlots();
                pushToast("Pickup slot configured", "success");
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Save Pickup Slot
          </Button>

          {pickupSlots.length > 0 && (
            <div className="border-t border-slate-100 pt-3 space-y-1.5">
              <div className="text-[11px] font-bold uppercase text-slate-500">
                Configured Upcoming Slots ({pickupSlots.length})
              </div>
              <div className="space-y-1.5 max-h-40 overflow-y-auto">
                {pickupSlots.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-1.5 text-xs"
                  >
                    <span>
                      <strong>{s.slot_date}</strong> • {String(s.start_time).slice(0, 5)}–{String(s.end_time).slice(0, 5)}{" "}
                      <span className="text-slate-500">
                        ({s.reserved_count}/{s.capacity} reserved)
                      </span>
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        try {
                          await api.post(`/queue/canteens/${activeCanteenId}/slots`, {
                            slot_date: s.slot_date,
                            start_time: s.start_time,
                            end_time: s.end_time,
                            capacity: s.capacity,
                            is_active: false,
                          });
                          refetchSlots();
                          pushToast("Pickup slot disabled", "info");
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      Disable
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      </div>
      <ConfirmModal
        open={confirmPauseOpen}
        title="Pause Canteen Ordering?"
        message="Customers will temporarily be prevented from placing new orders until you resume ordering. Active paid orders continue to be prepared."
        confirmLabel="Pause Ordering"
        busy={pauseBusy}
        onCancel={() => setConfirmPauseOpen(false)}
        onConfirm={async () => {
          setPauseBusy(true);
          try {
            await api.patch(`/queue/canteens/${activeCanteenId}/controls`, {
              ordering_paused: true,
              pause_reason: "Paused by manager due to peak crowd",
            });
            setConfirmPauseOpen(false);
            pushToast("Canteen ordering paused", "info");
            refetchQueue();
          } catch (err) {
            pushToast(getApiError(err), "error");
          } finally {
            setPauseBusy(false);
          }
        }}
      />
    </div>
  );
};
