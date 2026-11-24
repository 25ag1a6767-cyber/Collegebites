import { mobileApi } from "./client";

export const paymentsApi = {
  getRazorpayConfig: async (): Promise<{
    key_id: string | null;
    configured: boolean;
    live_api_enabled: boolean;
  }> => (await mobileApi.get("/payments/razorpay/config")).data,

  verifyRazorpay: async (
    payload: {
      order_id: string;
      razorpay_order_id: string;
      razorpay_payment_id: string;
      razorpay_signature: string;
      payment_method?: string;
    },
    guestToken?: string
  ) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (await mobileApi.post(`/payments/razorpay/verify${suffix}`, payload)).data;
  },

  syncRazorpay: async (orderId: string, guestToken?: string) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (await mobileApi.post(`/payments/razorpay/sync/${encodeURIComponent(orderId)}${suffix}`)).data;
  },

  failRazorpay: async (payload: { order_id: string; reason?: string }, guestToken?: string) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (await mobileApi.post(`/payments/razorpay/fail${suffix}`, payload)).data;
  },

  retryPayment: async (orderId: string, paymentMethod: "razorpay" = "razorpay", guestToken?: string) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (
      await mobileApi.post(`/payments/retry/${encodeURIComponent(orderId)}${suffix}`, {
        payment_method: paymentMethod,
      })
    ).data;
  },
};
