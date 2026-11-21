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

mobileApi.interceptors.request.use((config) => {
  const state = useMobileStore.getState();
  if (state.accessToken) {
    config.headers.Authorization = `Bearer ${state.accessToken}`;
  }
  config.headers["X-Guest-Session-ID"] = state.guestSessionId;
  return config;
});

mobileApi.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    const state = useMobileStore.getState();
    if (error.response?.status === 401 && !original?._retry && state.refreshToken) {
      original._retry = true;
      try {
        const res = await axios.post(`${API_BASE_URL}/auth/refresh`, {
          refresh_token: state.refreshToken,
        });
        await state.setAuth(res.data.access_token, res.data.refresh_token, res.data.user);
        original.headers.Authorization = `Bearer ${res.data.access_token}`;
        return mobileApi(original);
      } catch {
        await state.logout();
      }
    }
    return Promise.reject(error);
  }
);
