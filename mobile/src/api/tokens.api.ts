import { API_BASE_URL, mobileApi } from "./client";

export const tokensApi = {
  resolveLocationQr: async (code: string) =>
    (await mobileApi.get(`/qr/locations/resolve/${encodeURIComponent(code.trim())}`)).data,

  getReceipt: async (orderNumber: string, guestToken?: string) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (await mobileApi.get(`/tokens/receipts/${encodeURIComponent(orderNumber)}${suffix}`)).data;
  },

  downloadReceiptPdfBlob: async (orderNumber: string, guestToken?: string) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (
      await mobileApi.get(`/tokens/receipts/${encodeURIComponent(orderNumber)}/pdf${suffix}`, {
        responseType: "blob",
      })
    ).data;
  },

  getGuestReceiptPdfUrl: (orderNumber: string, guestToken: string) =>
    `${API_BASE_URL}/tokens/receipts/${encodeURIComponent(orderNumber)}/pdf?guest_token=${encodeURIComponent(guestToken)}`,

  verifyPickup: async (payload: { qr_payload?: string; pickup_token?: string; order_number?: string }) =>
    (await mobileApi.post("/pickup/verify", payload)).data,

  confirmHandover: async (payload: {
    order_id: string;
    counter_id?: string | null;
    verification_method: "qr_scan" | "manual_token" | "order_number";
  }) => (await mobileApi.post("/pickup/handover", payload)).data,

  getBoard: async (canteenId: string) =>
    (await mobileApi.get(`/pickup/board/${encodeURIComponent(canteenId)}`)).data,
};
