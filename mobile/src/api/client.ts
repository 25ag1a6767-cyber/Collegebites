import axios from "axios";
import Constants from "expo-constants";
import { useMobileStore } from "../store/useMobileStore";

export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL ||
  (Constants.expoConfig?.extra?.apiUrl as string | undefined) ||
  "http://127.0.0.1:8000/api/v1";

export const mobileApi = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
});

export function getMobileApiError(err: unknown, fallback = "Request failed"): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  } else if (err && typeof err === "object" && "message" in err && typeof (err as any).message === "string") {
    return (err as any).message;
  }
  return fallback;
}

export function buildMobileWsUrl(
  path: string,
  opts?: { token?: string | null; guestToken?: string | null }
): string {
  const cleanBase = API_BASE_URL.replace(/^http/i, "ws").replace(/\/$/, "");
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const queryParts: string[] = [];
  if (opts?.token) queryParts.push(`token=${encodeURIComponent(opts.token)}`);
  if (opts?.guestToken) queryParts.push(`guest_token=${encodeURIComponent(opts.guestToken)}`);
  return `${cleanBase}${cleanPath}${queryParts.length > 0 ? `?${queryParts.join("&")}` : ""}`;
}

mobileApi.interceptors.request.use((config) => {
  const state = useMobileStore.getState();
  if (state.accessToken) {
    config.headers.Authorization = `Bearer ${state.accessToken}`;
  }
  config.headers["X-Guest-Session-ID"] = state.guestSessionId;
  return config;
});

let refreshingPromise: Promise<string | null> | null = null;

mobileApi.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    const state = useMobileStore.getState();
    if (error.response?.status === 401 && original && !original._retry && state.refreshToken) {
      original._retry = true;
      if (!refreshingPromise) {
        refreshingPromise = axios
          .post(`${API_BASE_URL}/auth/refresh`, {
            refresh_token: state.refreshToken,
          })
          .then(async (res) => {
            await state.setAuth(res.data.access_token, res.data.refresh_token, res.data.user);
            return res.data.access_token as string;
          })
          .catch(async () => {
            await state.logout(true);
            return null;
          })
          .finally(() => {
            refreshingPromise = null;
          });
      }
      const nextToken = await refreshingPromise;
      if (nextToken) {
        original.headers.Authorization = `Bearer ${nextToken}`;
        return mobileApi(original);
      }
    }
    return Promise.reject(error);
  }
);
