import axios from "axios";
import Constants from "expo-constants";
import { create } from "zustand";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const API_URL =
  process.env.EXPO_PUBLIC_API_URL ||
  (Constants.expoConfig?.extra?.apiUrl as string | undefined) ||
  "http://127.0.0.1:8000/api/v1";

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
  onboardingSeen: boolean;
  hydrated: boolean;

  hydrate: () => Promise<void>;
  setAuth: (access: string, refresh: string, user: MobileUser) => Promise<void>;
  logout: (skipServer?: boolean) => Promise<void>;
  setCanteen: (canteenId: string, qrCode?: string | null) => void;
  saveGuestOrderToken: (orderNumber: string, token: string) => void;
  saveCachedOrder: (orderNumber: string, orderObj: any) => void;
  markOnboardingSeen: () => Promise<void>;
}

const MAX_CACHED_ORDERS = 10;

export const useMobileStore = create<MobileState>((set, get) => ({
  accessToken: null,
  refreshToken: null,
  user: null,
  guestSessionId: "cb-mob-" + Math.random().toString(36).slice(2),
  selectedCanteenId: null,
  scannedQrCode: null,
  guestOrderTokens: {},
  cachedOrders: {},
  onboardingSeen: false,
  hydrated: false,

  hydrate: async () => {
    const [access, refresh, userRaw, guestTokRaw, guestSess, orderKeysRaw, onboardingRaw] = await Promise.all([
      getSecure("cb_access"),
      getSecure("cb_refresh"),
      getSecure("cb_user"),
      getSecure("cb_guest_tokens"),
      getSecure("cb_guest_session"),
      getSecure("cb_order_keys"),
      getSecure("cb_onboarding_seen"),
    ]);

    let finalGuestSess = guestSess;
    if (!finalGuestSess) {
      finalGuestSess = "cb-mob-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
      await setSecure("cb_guest_session", finalGuestSess).catch(() => {});
    }

    let validAccess = access;
    let validRefresh = refresh;
    let validUser: MobileUser | null = userRaw ? JSON.parse(userRaw) : null;

    if (validAccess) {
      try {
        const meRes = await axios.get(`${API_URL}/auth/me`, {
          headers: { Authorization: `Bearer ${validAccess}` },
          timeout: 6000,
        });
        validUser = meRes.data;
      } catch (err: any) {
        if (err?.response?.status === 401 && validRefresh) {
          try {
            const refRes = await axios.post(`${API_URL}/auth/refresh`, { refresh_token: validRefresh }, { timeout: 6000 });
            validAccess = refRes.data.access_token;
            validRefresh = refRes.data.refresh_token;
            validUser = refRes.data.user;
            await setSecure("cb_access", validAccess);
            await setSecure("cb_refresh", validRefresh);
            await setSecure("cb_user", JSON.stringify(validUser));
          } catch {
            validAccess = null;
            validRefresh = null;
            validUser = null;
            await setSecure("cb_access", null);
            await setSecure("cb_refresh", null);
            await setSecure("cb_user", null);
          }
        }
      }
    }

    const keys: string[] = orderKeysRaw ? JSON.parse(orderKeysRaw) : [];
    const loadedOrders: Record<string, any> = {};
    await Promise.all(
      keys.map(async (ordNo) => {
        const raw = await getSecure(`cb_order_${ordNo}`).catch(() => null);
        if (raw) {
          try {
            loadedOrders[ordNo] = JSON.parse(raw);
          } catch {
            // ignore corrupted entry
          }
        }
      })
    );

    set({
      accessToken: validAccess,
      refreshToken: validRefresh,
      user: validUser,
      guestSessionId: finalGuestSess,
      guestOrderTokens: guestTokRaw ? JSON.parse(guestTokRaw) : {},
      cachedOrders: loadedOrders,
      onboardingSeen: onboardingRaw === "true",
      hydrated: true,
    });
  },
  markOnboardingSeen: async () => {
    set({ onboardingSeen: true });
    await setSecure("cb_onboarding_seen", "true").catch(() => {});
  },
  setAuth: async (access, refresh, user) => {
    await setSecure("cb_access", access);
    await setSecure("cb_refresh", refresh);
    await setSecure("cb_user", JSON.stringify(user));
    set({ accessToken: access, refreshToken: refresh, user });
  },
  logout: async (skipServer = false) => {
    const token = get().accessToken;
    if (!skipServer && token) {
      await axios.post(`${API_URL}/auth/logout`, {}, { headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
    }
    await setSecure("cb_access", null);
    await setSecure("cb_refresh", null);
    await setSecure("cb_user", null);
    set({ accessToken: null, refreshToken: null, user: null });
  },
  setCanteen: (selectedCanteenId, scannedQrCode = null) => set({ selectedCanteenId, scannedQrCode }),
  saveGuestOrderToken: (orderNumber, token) => {
    const entries = Object.entries({ ...get().guestOrderTokens, [orderNumber]: token }).slice(-20);
    const next = Object.fromEntries(entries);
    set({ guestOrderTokens: next });
    setSecure("cb_guest_tokens", JSON.stringify(next)).catch(() => {});
  },
  saveCachedOrder: (orderNumber, orderObj) => {
    const nextMap = { ...get().cachedOrders, [orderNumber]: orderObj };
    const existingKeys = Object.keys(nextMap);
    const evicted = existingKeys.slice(0, Math.max(0, existingKeys.length - MAX_CACHED_ORDERS));
    const keptKeys = existingKeys.slice(-MAX_CACHED_ORDERS);
    evicted.forEach((k) => {
      delete nextMap[k];
      setSecure(`cb_order_${k}`, null).catch(() => {});
    });
    // Store compact snapshot to stay well below SecureStore's 2KB limit per item
    const compact = {
      id: orderObj.id,
      order_number: orderObj.order_number,
      canteen_id: orderObj.canteen_id,
      canteen_name: orderObj.canteen_name,
      counter_name: orderObj.counter_name,
      status: orderObj.status,
      payment_status: orderObj.payment_status,
      payment_method: orderObj.payment_method,
      subtotal_amount: orderObj.subtotal_amount,
      discount_amount: orderObj.discount_amount,
      tax_amount: orderObj.tax_amount,
      total_amount: orderObj.total_amount,
      pickup_token_code: orderObj.pickup_token_code,
      qr_token_raw: orderObj.qr_token_raw,
      guest_name: orderObj.guest_name,
      items: (orderObj.items || []).slice(0, 12).map((i: any) => ({
        id: i.id,
        item_name: i.item_name,
        variant_name: i.variant_name,
        quantity: i.quantity,
        line_subtotal: i.line_subtotal,
      })),
    };
    set({ cachedOrders: nextMap });
    setSecure(`cb_order_${orderNumber}`, JSON.stringify(compact)).catch(() => {});
    setSecure("cb_order_keys", JSON.stringify(keptKeys)).catch(() => {});
  },
}));
