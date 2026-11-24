import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { buildWsUrl } from "../api/client";
import { useAppStore } from "../store/useAppStore";
import { useOfflineStore } from "../store/useOfflineStore";
import { computeReconnectDelayMs, flushSyncQueue } from "../utils/offlineSync";

export type RealtimeStatus = "connecting" | "live" | "reconnecting" | "offline";

export interface ParsedSseMessage {
  id?: string;
  event: string;
  data: any;
  retry?: number;
}

/**
 * Parse raw SSE chunk text into structured events while returning any trailing incomplete frame buffer.
 */
export function parseSseChunks(buffer: string): { messages: ParsedSseMessage[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const messages: ParsedSseMessage[] = [];

  for (const block of blocks) {
    if (!block.trim()) continue;
    let id: string | undefined;
    let event = "message";
    let retry: number | undefined;
    const dataLines: string[] = [];

    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const idx = line.indexOf(":");
      const field = idx >= 0 ? line.slice(0, idx).trim() : line.trim();
      const rawVal = idx >= 0 ? line.slice(idx + 1) : "";
      const val = rawVal.startsWith(" ") ? rawVal.slice(1) : rawVal;

      if (field === "id") id = val;
      else if (field === "event") event = val || "message";
      else if (field === "data") dataLines.push(val);
      else if (field === "retry") {
        const parsed = Number(val);
        if (!Number.isNaN(parsed) && parsed > 0) retry = parsed;
      }
    }

    if (dataLines.length === 0) continue;
    const joined = dataLines.join("\n");
    let parsedData: any = joined;
    try {
      parsedData = JSON.parse(joined);
    } catch {
      // Keep plain text payload if non-JSON
    }
    messages.push({ id, event, data: parsedData, retry });
  }

  return { messages, rest };
}

/**
 * Prevent duplicate state updates when the same version fingerprint arrives over both SSE and WebSocket.
 */
export function shouldAcceptRealtimeVersion(
  lastVersion: string | null,
  nextVersion?: string | null
): boolean {
  if (!nextVersion) return true;
  if (!lastVersion) return true;
  return lastVersion !== nextVersion;
}

function buildApiHttpUrl(path: string): string {
  const base = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/$/, "");
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${cleanPath}`;
}

export interface UseRealtimeSyncOptions<T = any> {
  enabled?: boolean;
  ssePath?: string | null;
  wsPath?: string | null;
  wsToken?: string | null;
  wsGuestToken?: string | null;
  queryKeys?: readonly (readonly unknown[])[];
  onSnapshot?: (data: T, eventName: string) => void;
  onEvent?: (payload: any, eventName: string) => void;
}

export function useRealtimeSync<T = any>(options: UseRealtimeSyncOptions<T>) {
  const {
    enabled = true,
    ssePath,
    wsPath,
    wsToken,
    wsGuestToken,
    queryKeys,
    onSnapshot,
    onEvent,
  } = options;

  const qc = useQueryClient();
  const accessToken = useAppStore((s) => s.accessToken);
  const guestSessionId = useAppStore((s) => s.guestSessionId);

  const [status, setStatus] = useState<RealtimeStatus>(() =>
    typeof navigator !== "undefined" && navigator.onLine === false ? "offline" : "connecting"
  );
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null);
  const [reconnectTick, setReconnectTick] = useState(0);

  const lastVersionRef = useRef<string | null>(null);
  const prevStatusRef = useRef<RealtimeStatus>(status);
  const onSnapshotRef = useRef(onSnapshot);
  const onEventRef = useRef(onEvent);
  const queryKeysRef = useRef(queryKeys);
  onSnapshotRef.current = onSnapshot;
  onEventRef.current = onEvent;
  queryKeysRef.current = queryKeys;

  const invalidateAll = () => {
    for (const key of queryKeysRef.current || []) {
      qc.invalidateQueries({ queryKey: [...key] });
    }
  };

  // Track connectivity transitions into recovery logs & flush pending offline actions on live restore
  useEffect(() => {
    if (!enabled) return;
    const prev = prevStatusRef.current;
    prevStatusRef.current = status;
    const offStore = useOfflineStore.getState();

    if (status === "live") {
      offStore.setNetworkStatus(true, "online");
      if (prev === "offline" || prev === "reconnecting") {
        offStore.addRecoveryLog(
          "success",
          "Real-time stream recovered",
          `${ssePath || wsPath || "Realtime"} reconnected and refreshed latest state.`
        );
        invalidateAll();
        void flushSyncQueue(qc);
      }
    } else if (status === "offline") {
      offStore.setNetworkStatus(false, "offline");
      if (prev !== "offline") {
        offStore.addRecoveryLog("warn", "Real-time stream offline", "Internet connection unavailable.");
      }
    } else if (status === "reconnecting" && prev === "live") {
      offStore.setNetworkStatus(true, "reconnecting");
      offStore.addRecoveryLog(
        "warn",
        "Real-time connection interrupted",
        "Attempting exponential backoff reconnection."
      );
    }
  }, [status, enabled, ssePath, wsPath, qc]);

  // Keep statusRef in sync so visibilitychange never tears down an already-live SSE/WS connection
  const statusRef = useRef(status);
  statusRef.current = status;

  // Reset deduplication cursor when subscription target changes
  useEffect(() => {
    lastVersionRef.current = null;
  }, [ssePath, wsPath]);

  // Network & tab visibility catch-up listeners
  useEffect(() => {
    if (!enabled) return;
    const handleOnline = () => {
      setStatus("connecting");
      setReconnectTick((n) => n + 1);
      invalidateAll();
      void flushSyncQueue(qc);
    };
    const handleOffline = () => {
      setStatus("offline");
    };
    const handleVisible = () => {
      if (document.visibilityState === "visible") {
        if (navigator.onLine !== false) {
          // Only tear down & reconnect if stream is not already live
          if (statusRef.current !== "live") {
            setReconnectTick((n) => n + 1);
            invalidateAll();
          }
          void flushSyncQueue(qc);
        }
      }
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    document.addEventListener("visibilitychange", handleVisible);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      document.removeEventListener("visibilitychange", handleVisible);
    };
  }, [enabled]);

  // Primary cross-instance SSE connection (with Last-Event-ID + exponential backoff)
  useEffect(() => {
    if (!enabled || !ssePath) return;
    let cancelled = false;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const connectSse = async () => {
      if (cancelled) return;
      if (typeof navigator !== "undefined" && navigator.onLine === false) {
        setStatus("offline");
        return;
      }

      setStatus(attempt === 0 ? "connecting" : "reconnecting");
      controller = new AbortController();

      try {
        const rawUrl = buildApiHttpUrl(ssePath);
        const headers: Record<string, string> = {
          Accept: "text/event-stream",
          "X-Guest-Session-ID": guestSessionId,
        };
        const bearer = wsToken ?? accessToken;
        if (bearer) {
          headers.Authorization = `Bearer ${bearer}`;
        }
        if (lastVersionRef.current) {
          headers["Last-Event-ID"] = lastVersionRef.current;
        }
        if (wsGuestToken) {
          headers["X-Guest-Token"] = wsGuestToken;
        }

        const sep = rawUrl.includes("?") ? "&" : "?";
        const fullUrl = lastVersionRef.current
          ? `${rawUrl}${sep}last_version=${encodeURIComponent(lastVersionRef.current)}`
          : rawUrl;

        const resp = await fetch(fullUrl, {
          method: "GET",
          headers,
          signal: controller.signal,
          cache: "no-store",
        });

        if (!resp.ok || !resp.body) {
          throw new Error(`SSE stream HTTP ${resp.status}`);
        }

        attempt = 0;
        setStatus("live");
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let cycleRequested = false;

        while (!cancelled) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parsed = parseSseChunks(buffer);
          buffer = parsed.rest;

          for (const msg of parsed.messages) {
            if (msg.event === "stream.reconnect") {
              cycleRequested = true;
              continue;
            }
            const nextVer: string | null = msg.id || msg.data?.version || null;
            if (!shouldAcceptRealtimeVersion(lastVersionRef.current, nextVer)) {
              setLastSyncedAt(new Date());
              continue;
            }
            if (nextVer) lastVersionRef.current = nextVer;
            setLastSyncedAt(new Date());
            setStatus("live");
            if (msg.event.endsWith(".snapshot")) {
              onSnapshotRef.current?.(msg.data as T, msg.event);
            } else {
              onEventRef.current?.(msg.data, msg.event);
              invalidateAll();
            }
          }
        }

        if (!cancelled) {
          const delayMs = cycleRequested ? 150 : 1200;
          timer = setTimeout(connectSse, delayMs);
        }
      } catch (err: any) {
        if (cancelled || err?.name === "AbortError") return;
        attempt += 1;
        setStatus(typeof navigator !== "undefined" && navigator.onLine === false ? "offline" : "reconnecting");
        const delayMs = computeReconnectDelayMs(attempt, 1000, 15000, 400);
        timer = setTimeout(connectSse, delayMs);
      }
    };

    void connectSse();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      controller?.abort();
    };
  }, [enabled, ssePath, accessToken, wsToken, wsGuestToken, guestSessionId, reconnectTick]);

  // Low-latency WebSocket push channel with ping keepalive & auto-reconnect (skipped on serverless vercel.app unless explicitly enabled)
  useEffect(() => {
    const isVercelServerless =
      typeof window !== "undefined" &&
      window.location.hostname.endsWith(".vercel.app") &&
      import.meta.env.VITE_WS_ENABLED !== "true";
    if (!enabled || !wsPath || isVercelServerless) return;
    let cancelled = false;
    let ws: WebSocket | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const connectWs = () => {
      if (cancelled) return;
      if (typeof navigator !== "undefined" && navigator.onLine === false) return;
      try {
        ws = new WebSocket(buildWsUrl(wsPath, { token: wsToken ?? accessToken, guestToken: wsGuestToken }));
        ws.onopen = () => {
          attempt = 0;
          setStatus("live");
          pingTimer = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send("ping");
            }
          }, 20000);
        };
        ws.onmessage = (ev) => {
          try {
            const payload = JSON.parse(ev.data);
            if (payload?.event === "pong") return;
            if (payload?.version) {
              if (!shouldAcceptRealtimeVersion(lastVersionRef.current, payload.version)) {
                setLastSyncedAt(new Date());
                return;
              }
              lastVersionRef.current = payload.version;
            }
            setLastSyncedAt(new Date());
            onEventRef.current?.(payload, payload?.event || "ws.event");
            invalidateAll();
          } catch {
            invalidateAll();
          }
        };
        ws.onclose = () => {
          if (pingTimer) clearInterval(pingTimer);
          pingTimer = null;
          if (!cancelled) {
            attempt += 1;
            if (!ssePath) {
              setStatus(typeof navigator !== "undefined" && navigator.onLine === false ? "offline" : "reconnecting");
            }
            const delayMs = computeReconnectDelayMs(attempt, 1200, 15000, 400);
            reconnectTimer = setTimeout(connectWs, delayMs);
          }
        };
        ws.onerror = () => {
          ws?.close();
        };
      } catch {
        // SSE stream handles synchronization cleanly
      }
    };

    connectWs();

    return () => {
      cancelled = true;
      if (pingTimer) clearInterval(pingTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [enabled, wsPath, accessToken, wsToken, wsGuestToken, reconnectTick]);

  return {
    status,
    lastSyncedAt,
    triggerSync: invalidateAll,
  };
}
