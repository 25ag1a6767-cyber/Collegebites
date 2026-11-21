import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "../types";

function makeGuestSessionId() {
  return "cb-guest-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

interface AppState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  guestSessionId: string;
  selectedCanteenId: string | null;
  selectedCounterId: string | null;
  selectedTableId: string | null;
  scannedLocationQrCode: string | null;
  guestOrderTokens: Record<string, string>;
  printerWidth: "58mm" | "80mm" | "a4";
  autoPrintPos: boolean;

  setAuth: (accessToken: string, refreshToken: string, user: User) => void;
  logout: () => void;
  setSelectedCanteen: (canteenId: string, counterId?: string | null, tableId?: string | null, qrCode?: string | null) => void;
  saveGuestOrderToken: (orderNumber: string, token: string) => void;
  setPrinterPrefs: (width: "58mm" | "80mm" | "a4", autoPrintPos: boolean) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      guestSessionId: makeGuestSessionId(),
      selectedCanteenId: null,
      selectedCounterId: null,
      selectedTableId: null,
      scannedLocationQrCode: null,
      guestOrderTokens: {},
      printerWidth: "80mm",
      autoPrintPos: true,

      setAuth: (accessToken, refreshToken, user) => set({ accessToken, refreshToken, user }),
      logout: () => set({ accessToken: null, refreshToken: null, user: null }),
      setSelectedCanteen: (canteenId, counterId = null, tableId = null, qrCode = null) =>
        set({
          selectedCanteenId: canteenId,
          selectedCounterId: counterId,
          selectedTableId: tableId,
          scannedLocationQrCode: qrCode,
        }),
      saveGuestOrderToken: (orderNumber, token) =>
        set((state) => ({
          guestOrderTokens: { ...state.guestOrderTokens, [orderNumber]: token },
        })),
      setPrinterPrefs: (printerWidth, autoPrintPos) => set({ printerWidth, autoPrintPos }),
    }),
    {
      name: "collegebites-app-state",
    }
  )
);
