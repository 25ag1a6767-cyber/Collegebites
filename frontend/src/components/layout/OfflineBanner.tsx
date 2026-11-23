import React, { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CloudOff, RefreshCw, Wifi } from "lucide-react";
import { useOfflineStore } from "../../store/useOfflineStore";
import { flushSyncQueue } from "../../utils/offlineSync";
import { Button } from "../ui/Primitives";

export const OfflineBanner: React.FC = () => {
  const qc = useQueryClient();
  const isOnline = useOfflineStore((s) => s.isOnline);
  const networkState = useOfflineStore((s) => s.networkState);
  const isFlushing = useOfflineStore((s) => s.isFlushingQueue);
  const pendingQueue = useOfflineStore((s) => s.pendingQueue);
  const setNetworkStatus = useOfflineStore((s) => s.setNetworkStatus);
  const addRecoveryLog = useOfflineStore((s) => s.addRecoveryLog);

  const pendingCount = pendingQueue.filter((i) => i.status === "pending" || i.status === "syncing").length;
  const conflictCount = pendingQueue.filter((i) => i.status === "conflict").length;

  useEffect(() => {
    const syncConnectivity = () => {
      const online = typeof navigator === "undefined" ? true : navigator.onLine !== false;
      if (online) {
        setNetworkStatus(true, "online");
        addRecoveryLog("info", "Browser online detected", "Refreshing active queries and flushing sync queue.");
        qc.invalidateQueries();
        void flushSyncQueue(qc);
      } else {
        setNetworkStatus(false, "offline");
        addRecoveryLog("warn", "Browser offline detected", "Switched to cached offline read mode.");
      }
    };

    window.addEventListener("online", syncConnectivity);
    window.addEventListener("offline", syncConnectivity);
    return () => {
      window.removeEventListener("online", syncConnectivity);
      window.removeEventListener("offline", syncConnectivity);
    };
  }, [qc, setNetworkStatus, addRecoveryLog]);

  if (isOnline && networkState === "online" && pendingCount === 0 && conflictCount === 0) {
    return null;
  }

  return (
    <div
      data-testid="global-offline-banner"
      className={`no-print border-b px-4 py-2 text-xs font-semibold ${
        !isOnline
          ? "border-red-300 bg-red-600 text-white"
          : conflictCount > 0
          ? "border-amber-300 bg-amber-100 text-amber-950"
          : "border-indigo-200 bg-indigo-50 text-indigo-900"
      }`}
    >
      <div className="mx-auto max-w-7xl flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {!isOnline ? (
            <CloudOff className="h-4 w-4 shrink-0" />
          ) : conflictCount > 0 ? (
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-700" />
          ) : (
            <Wifi className="h-4 w-4 shrink-0" />
          )}
          <span>
            {!isOnline
              ? `Offline Mode: Viewing last synchronized menu & orders. Payments & checkout require internet connection.${
                  pendingCount > 0 ? ` (${pendingCount} safe action queued)` : ""
                }`
              : conflictCount > 0
              ? `Sync Conflict Alert: ${conflictCount} offline action(s) require manager review in Network & Sync.${
                  pendingCount > 0 ? ` • ${pendingCount} pending sync` : ""
                }`
              : isFlushing
              ? `Reconnected — synchronizing ${pendingCount} pending offline action(s)...`
              : `${pendingCount} offline action(s) ready to synchronize.`}
          </span>
        </div>

        {isOnline && (pendingCount > 0 || networkState === "reconnecting") && (
          <Button
            size="sm"
            variant="secondary"
            disabled={isFlushing}
            onClick={() => void flushSyncQueue(qc)}
          >
            <RefreshCw className={`h-3 w-3 ${isFlushing ? "animate-spin" : ""}`} /> Sync Now
          </Button>
        )}
      </div>
    </div>
  );
};
