import React, { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CloudOff, Database, RefreshCw, Trash2, Wifi } from "lucide-react";
import { api } from "../../api/client";
import { useOfflineStore } from "../../store/useOfflineStore";
import { clearAllOfflineCache, flushSyncQueue } from "../../utils/offlineSync";
import { Badge, Button, Card, useToast } from "./Primitives";

export const NetworkSyncPanel: React.FC = () => {
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const isOnline = useOfflineStore((s) => s.isOnline);
  const networkState = useOfflineStore((s) => s.networkState);
  const lastOnlineAt = useOfflineStore((s) => s.lastOnlineAt);
  const lastSyncAt = useOfflineStore((s) => s.lastSyncAt);
  const isFlushing = useOfflineStore((s) => s.isFlushingQueue);
  const pendingQueue = useOfflineStore((s) => s.pendingQueue);
  const recoveryLogs = useOfflineStore((s) => s.recoveryLogs);
  const cachedKeys = useOfflineStore((s) => s.cachedKeys);
  const updateActionStatus = useOfflineStore((s) => s.updateActionStatus);
  const removeAction = useOfflineStore((s) => s.removeAction);
  const clearCompletedActions = useOfflineStore((s) => s.clearCompletedActions);
  const clearRecoveryLogs = useOfflineStore((s) => s.clearRecoveryLogs);
  const addRecoveryLog = useOfflineStore((s) => s.addRecoveryLog);

  const [probing, setProbing] = useState(false);

  const pendingCnt = pendingQueue.filter((q) => q.status === "pending" || q.status === "syncing").length;
  const conflictCnt = pendingQueue.filter((q) => q.status === "conflict").length;
  const cachedCount = Object.keys(cachedKeys).length;

  const probeConnectivity = async () => {
    setProbing(true);
    try {
      const res = await api.get("/health", { baseURL: "" });
      useOfflineStore.getState().setNetworkStatus(true, "online");
      addRecoveryLog("success", "Manual health probe succeeded", `Server time: ${res.data?.server_time || "ok"}`);
      await flushSyncQueue(qc);
      pushToast("Backend reachable & sync queue checked", "success");
    } catch {
      useOfflineStore.getState().setNetworkStatus(false, "offline");
      addRecoveryLog("error", "Manual health probe failed", "Unable to reach /health endpoint.");
      pushToast("Server unreachable — offline mode active", "error");
    } finally {
      setProbing(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase text-slate-500 flex items-center gap-1.5">
            {isOnline ? <Wifi className="h-3.5 w-3.5 text-emerald-600" /> : <CloudOff className="h-3.5 w-3.5 text-red-600" />}
            Connectivity Status
          </div>
          <div className={`mt-1 text-2xl font-black uppercase ${isOnline ? "text-emerald-700" : "text-red-700"}`}>
            {networkState}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            Last online: {lastOnlineAt ? new Date(lastOnlineAt).toLocaleTimeString() : "N/A"}
          </div>
        </Card>

        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase text-slate-500">Pending Sync Queue</div>
          <div className="mt-1 text-2xl font-black text-slate-900">{pendingCnt}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            Last synced: {lastSyncAt ? new Date(lastSyncAt).toLocaleTimeString() : "None yet"}
          </div>
        </Card>

        <Card className={`p-4 ${conflictCnt > 0 ? "border-amber-300 bg-amber-50/40" : ""}`}>
          <div className="text-[11px] font-bold uppercase text-amber-800 flex items-center gap-1">
            <AlertTriangle className="h-3.5 w-3.5" /> Sync Conflicts
          </div>
          <div className="mt-1 text-2xl font-black text-amber-900">{conflictCnt}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">PostgreSQL remains authoritative source</div>
        </Card>

        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase text-slate-500 flex items-center gap-1">
            <Database className="h-3.5 w-3.5" /> Cached Snapshots
          </div>
          <div className="mt-1 text-2xl font-black text-slate-900">{cachedCount}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">Read-only sanitized data (no secrets)</div>
        </Card>
      </div>

      {/* Controls */}
      <Card className="p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-slate-600">
          Offline actions are restricted strictly to non-financial staff updates. Payments &amp; checkouts always require live server verification.
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={probing} onClick={() => void probeConnectivity()}>
            <RefreshCw className={`h-3.5 w-3.5 ${probing ? "animate-spin" : ""}`} /> Check Connection
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={!isOnline || isFlushing || pendingCnt === 0}
            onClick={() => void flushSyncQueue(qc)}
          >
            Sync Queue ({pendingCnt})
          </Button>
          <Button size="sm" variant="ghost" onClick={clearCompletedActions}>
            Clear Synced
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              clearAllOfflineCache();
              pushToast("Local sanitized offline cache cleared", "info");
            }}
          >
            <Trash2 className="h-3.5 w-3.5" /> Clear Cache
          </Button>
        </div>
      </Card>

      {/* Queue & Conflicts Table */}
      <Card className="p-5 space-y-3">
        <h3 className="font-bold text-slate-900 text-sm">Synchronization Queue &amp; Conflict Resolution ({pendingQueue.length})</h3>
        {pendingQueue.length === 0 ? (
          <div className="py-6 text-center text-xs text-slate-400">
            No pending, conflicted, or recently synced actions in local queue.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-[11px] uppercase text-slate-500">
                  <th className="py-2 pr-3">Action</th>
                  <th className="py-2 pr-3">Endpoint</th>
                  <th className="py-2 pr-3">Idempotency Key</th>
                  <th className="py-2 pr-3">Attempts</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Note / Conflict</th>
                  <th className="py-2 text-right">Resolve</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[...pendingQueue].reverse().map((item) => (
                  <tr key={item.id}>
                    <td className="py-2 pr-3 font-semibold text-slate-800">{item.label}</td>
                    <td className="py-2 pr-3 font-mono text-[11px] text-slate-600">
                      {item.method} {item.url}
                    </td>
                    <td className="py-2 pr-3 font-mono text-[10px] text-slate-500">{item.idempotencyKey}</td>
                    <td className="py-2 pr-3">{item.attempts}</td>
                    <td className="py-2 pr-3">
                      <Badge
                        tone={
                          item.status === "synced"
                            ? "green"
                            : item.status === "conflict"
                            ? "amber"
                            : item.status === "failed"
                            ? "red"
                            : "blue"
                        }
                      >
                        {item.status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 text-[11px] text-slate-600 max-w-xs truncate" title={item.lastError || ""}>
                      {item.lastError || "—"}
                    </td>
                    <td className="py-2 text-right space-x-1">
                      {(item.status === "failed" || item.status === "conflict") && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            updateActionStatus(item.id, { status: "pending", lastError: null });
                            void flushSyncQueue(qc);
                          }}
                        >
                          Retry
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => removeAction(item.id)}>
                        Dismiss
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Recovery Logs */}
      <Card className="p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-slate-900 text-sm">Network Recovery &amp; Reconnection Logs ({recoveryLogs.length})</h3>
          {recoveryLogs.length > 0 && (
            <Button size="sm" variant="ghost" onClick={clearRecoveryLogs}>
              Clear Logs
            </Button>
          )}
        </div>
        {recoveryLogs.length === 0 ? (
          <div className="py-4 text-center text-xs text-slate-400">No network transitions or sync events recorded yet.</div>
        ) : (
          <div className="space-y-1.5 max-h-60 overflow-y-auto text-xs">
            {recoveryLogs.map((log) => (
              <div key={log.id} className="flex items-start justify-between gap-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
                <div className="flex items-center gap-2">
                  {log.level === "success" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
                  ) : log.level === "warn" ? (
                    <AlertTriangle className="h-3.5 w-3.5 text-amber-600 shrink-0" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5 text-slate-500 shrink-0" />
                  )}
                  <div>
                    <span className="font-bold text-slate-800">{log.event}</span>{" "}
                    <span className="text-slate-600">— {log.detail}</span>
                  </div>
                </div>
                <span className="text-[10px] font-mono text-slate-400 shrink-0">
                  {new Date(log.timestamp).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};
