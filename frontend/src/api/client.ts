import axios from "axios";
import { useAppStore } from "../store/useAppStore";

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
  (res) => res,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry && useAppStore.getState().refreshToken) {
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

export function getApiError(err: unknown, fallback = "Request failed"): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  }
  return fallback;
}
