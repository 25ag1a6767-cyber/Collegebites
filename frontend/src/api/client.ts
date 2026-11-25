import axios from "axios";
import { useAppStore } from "../store/useAppStore";
import { useOfflineStore } from "../store/useOfflineStore";

const baseURL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export const api = axios.create({
  baseURL,
  timeout: 15000,
});

api.interceptors.request.use((config) => {
  const state = useAppStore.getState();
  if (state.accessToken) {
    config.headers.Authorization = `Bearer ${state.accessToken}`;
  }
  config.headers["X-Guest-Session-ID"] = state.guestSessionId;
  return config;
});

let refreshingPromise: Promise<string | null> | null = null;

api.interceptors.response.use(
  (res) => {
    const off = useOfflineStore.getState();
    if (!off.isOnline || off.networkState !== "online") {
      off.setNetworkStatus(true, "online");
      off.addRecoveryLog("success", "API connection restored", "Backend responded successfully.");
    }
    return res;
  },
  async (error) => {
    const original = error.config;

    // Auto-retry safe/idempotent GET requests on transient network or 502/503/504 errors
    if (
      original &&
      String(original.method || "get").toLowerCase() === "get" &&
      (typeof navigator === "undefined" || navigator.onLine !== false) &&
      (!error.response || error.response.status >= 502)
    ) {
      const retryCount = Number(original._getRetryCount || 0);
      if (retryCount < 1) {
        original._getRetryCount = retryCount + 1;
        const delayMs = 450;
        await new Promise((resolve) => setTimeout(resolve, delayMs));
        return api(original);
      }
    }

    if (!error.response && typeof navigator !== "undefined" && navigator.onLine === false) {
      const off = useOfflineStore.getState();
      if (off.isOnline) {
        off.setNetworkStatus(false, "offline");
        off.addRecoveryLog("warn", "Network offline detected", "Browser is offline; serving cached read-only state.");
      }
    }

    if (error.response?.status === 401 && original && !original._retry && useAppStore.getState().refreshToken) {
      original._retry = true;
      if (!refreshingPromise) {
        refreshingPromise = axios
          .post(`${baseURL}/auth/refresh`, { refresh_token: useAppStore.getState().refreshToken })
          .then((r) => {
            useAppStore.getState().setAuth(r.data.access_token, r.data.refresh_token, r.data.user);
            return r.data.access_token as string;
          })
          .catch(() => {
            useAppStore.getState().logout();
            return null;
          })
          .finally(() => {
            refreshingPromise = null;
          });
      }
      const newToken = await refreshingPromise;
      if (newToken) {
        original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      }
    }
    return Promise.reject(error);
  }
);

export function buildWsUrl(
  path: string,
  opts?: { token?: string | null; guestToken?: string | null }
): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const base = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/$/, "");
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const rawUrl =
    base.startsWith("http://") || base.startsWith("https://")
      ? `${base.replace(/^http/, "ws")}${cleanPath}`
      : `${proto}://${window.location.host}${base}${cleanPath}`;
  const url = new URL(rawUrl);
  if (opts?.token) url.searchParams.set("token", opts.token);
  if (opts?.guestToken) url.searchParams.set("guest_token", opts.guestToken);
  return url.toString();
}

export function getApiError(err: unknown, fallback = "Request failed"): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  }
  return fallback;
}
