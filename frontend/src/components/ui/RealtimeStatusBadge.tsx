import React from "react";
import type { RealtimeStatus } from "../../hooks/useRealtimeSync";

interface Props {
  status: RealtimeStatus;
  lastSyncedAt?: Date | null;
  darkSurface?: boolean;
}

export const RealtimeStatusBadge: React.FC<Props> = ({ status, lastSyncedAt, darkSurface = false }) => {
  const palette = (() => {
    if (status === "live") {
      return darkSurface
        ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-200"
        : "border-emerald-200 bg-emerald-50 text-emerald-700";
    }
    if (status === "offline") {
      return darkSurface
        ? "border-red-400/40 bg-red-500/20 text-red-200"
        : "border-red-200 bg-red-50 text-red-700";
    }
    return darkSurface
      ? "border-amber-400/40 bg-amber-500/15 text-amber-200"
      : "border-amber-200 bg-amber-50 text-amber-800";
  })();

  const dotClass =
    status === "live"
      ? "bg-emerald-400 animate-pulse"
      : status === "offline"
      ? "bg-red-500"
      : "bg-amber-400 animate-ping";

  const label =
    status === "live"
      ? "Live Sync"
      : status === "offline"
      ? "Offline — paused"
      : status === "reconnecting"
      ? "Reconnecting..."
      : "Connecting...";

  const timeLabel = lastSyncedAt
    ? lastSyncedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : null;

  return (
    <span
      data-testid="realtime-status-badge"
      className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-bold ${palette}`}
      title={timeLabel ? `Last synchronized at ${timeLabel}` : "Establishing real-time sync stream"}
    >
      <span className="relative flex h-2 w-2">
        <span className={`inline-flex h-2 w-2 rounded-full ${dotClass}`} />
      </span>
      <span>{label}</span>
      {timeLabel && <span className="opacity-75 font-mono text-[10px]">{timeLabel}</span>}
    </span>
  );
};
