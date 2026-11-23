import { useEffect, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";
import { useQueryClient } from "@tanstack/react-query";
import { buildMobileWsUrl } from "../api/client";
import { useMobileStore } from "../store/useMobileStore";

export type MobileRealtimeStatus = "connecting" | "live" | "reconnecting" | "offline";

export function useMobileRealtimeWs(options: {
  enabled: boolean;
  wsPath: string | null;
  token?: string | null;
  guestToken?: string | null;
  queryKeys: readonly (readonly unknown[])[];
}) {
  const { enabled, wsPath, token, guestToken, queryKeys } = options;
  const qc = useQueryClient();
  const [status, setStatus] = useState<MobileRealtimeStatus>("connecting");

  const invalidateAll = () => {
    for (const key of queryKeys) {
      qc.invalidateQueries({ queryKey: [...key] });
    }
  };

  useEffect(() => {
    if (!enabled || !wsPath) return;
    let cancelled = false;
    let ws: WebSocket | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const connect = () => {
      if (cancelled) return;
      setStatus(attempt === 0 ? "connecting" : "reconnecting");
      try {
        ws = new WebSocket(buildMobileWsUrl(wsPath, { token, guestToken }));
        ws.onopen = () => {
          attempt = 0;
          setStatus("live");
          useMobileStore.getState().setOnlineStatus(true);
          invalidateAll();
          pingTimer = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send("ping");
            }
          }, 20000);
        };
        ws.onmessage = (ev) => {
          try {
            const payload = JSON.parse(String(ev.data || "{}"));
            if (payload?.event === "pong") return;
          } catch {
            // non-JSON update
          }
          setStatus("live");
          invalidateAll();
        };
        ws.onclose = () => {
          if (pingTimer) clearInterval(pingTimer);
          pingTimer = null;
          if (!cancelled) {
            attempt += 1;
            const online = useMobileStore.getState().isOnline;
            setStatus(online ? "reconnecting" : "offline");
            const delayMs =
              Math.min(15000, 1200 * Math.pow(2, Math.min(attempt, 4))) + Math.floor(Math.random() * 400);
            reconnectTimer = setTimeout(connect, delayMs);
          }
        };
        ws.onerror = () => {
          ws?.close();
        };
      } catch {
        attempt += 1;
        setStatus("reconnecting");
        reconnectTimer = setTimeout(connect, Math.min(15000, 1500 * attempt));
      }
    };

    const appStateSub = AppState.addEventListener("change", (nextState: AppStateStatus) => {
      if (nextState === "active") {
        invalidateAll();
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          if (reconnectTimer) clearTimeout(reconnectTimer);
          connect();
        }
      }
    });

    connect();

    return () => {
      cancelled = true;
      appStateSub.remove();
      if (pingTimer) clearInterval(pingTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [enabled, wsPath, token, guestToken]);

  return { status };
}
