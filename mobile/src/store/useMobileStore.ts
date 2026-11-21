import { create } from "zustand";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

async function setSecure(key: string, val: string | null) {
  if (Platform.OS === "web") {
    if (val === null) localStorage.removeItem(key);
    else localStorage.setItem(key, val);
    return;
  }
  if (val === null) await SecureStore.deleteItemAsync(key);
  else await SecureStore.setItemAsync(key, val);
}

async function getSecure(key: string): Promise<string | null> {
  if (Platform.OS === "web") return localStorage.getItem(key);
  return await SecureStore.getItemAsync(key);
}

export interface MobileUser {
  id: string;
  full_name: string;
  email?: string | null;
  phone?: string | null;
  roles: string[];
}

interface MobileState {
  accessToken: string | null;
  refreshToken: string | null;
  user: MobileUser | null;
  guestSessionId: string;
  selectedCanteenId: string | null;
  scannedQrCode: string | null;
  guestOrderTokens: Record<string, string>;
  cachedOrders: Record<string, any>;
  hydrated: boolean;

  hydrate: () => Promise<void>;
  setAuth: (access: string, refresh: string, user: MobileUser) => Promise<void>;
  logout: () => Promise<void>;
  setCanteen: (canteenId: string, qrCode?: string | null) => void;
  saveGuestOrderToken: (orderNumber: string, token: string) => void;
  saveCachedOrder: (orderNumber: string, orderObj: any) => void;
}

export const useMobileStore = create<MobileState>((set, get) => ({
  accessToken: null,
  refreshToken: null,
  user: null,
  guestSessionId: "cb-mob-" + Math.random().toString(36).slice(2),
  selectedCanteenId: null,
  scannedQrCode: null,
  guestOrderTokens: {},
  cachedOrders: {},
  hydrated: false,

  hydrate: async () => {
    const [access, refresh, userRaw, guestTokRaw, cachedRaw] = await Promise.all([
      getSecure("cb_access"),
      getSecure("cb_refresh"),
      getSecure("cb_user"),
      getSecure("cb_guest_tokens"),
      getSecure("cb_cached_orders"),
    ]);
    set({
      accessToken: access,
      refreshToken: refresh,
      user: userRaw ? JSON.parse(userRaw) : null,
      guestOrderTokens: guestTokRaw ? JSON.parse(guestTokRaw) : {},
      cachedOrders: cachedRaw ? JSON.parse(cachedRaw) : {},
      hydrated: true,
    });
  },
  setAuth: async (access, refresh, user) => {
    await setSecure("cb_access", access);
    await setSecure("cb_refresh", refresh);
    await setSecure("cb_user", JSON.stringify(user));
    set({ accessToken: access, refreshToken: refresh, user });
  },
  logout: async () => {
    await setSecure("cb_access", null);
    await setSecure("cb_refresh", null);
    await setSecure("cb_user", null);
    set({ accessToken: null, refreshToken: null, user: null });
  },
  setCanteen: (selectedCanteenId, scannedQrCode = null) => set({ selectedCanteenId, scannedQrCode }),
  saveGuestOrderToken: (orderNumber, token) => {
    const next = { ...get().guestOrderTokens, [orderNumber]: token };
    set({ guestOrderTokens: next });
    setSecure("cb_guest_tokens", JSON.stringify(next)).catch(() => {});
  },
  saveCachedOrder: (orderNumber, orderObj) => {
    const next = { ...get().cachedOrders, [orderNumber]: orderObj };
    set({ cachedOrders: next });
    setSecure("cb_cached_orders", JSON.stringify(next)).catch(() => {});
  },
}));
