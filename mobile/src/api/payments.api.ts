import { mobileApi } from "./client";

export const paymentsApi = {
  verifyRazorpay: async (payload: {
    order_id: string;
    razorpay_order_id: string;
    razorpay_payment_id: string;
    razorpay_signature: string;
    payment_method?: string;
  }) => (await mobileApi.post("/payments/razorpay/verify", payload)).data,

  failRazorpay: async (payload: { order_id: string; reason?: string }, guestToken?: string) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (await mobileApi.post(`/payments/razorpay/fail${suffix}`, payload)).data;
  },

  verifyStripe: async (payload: {
    order_id: string;
    stripe_payment_intent_id?: string;
    stripe_session_id?: string;
    stripe_signature?: string;
    payment_method?: string;
  }) => (await mobileApi.post("/payments/stripe/verify", payload)).data,

  getStripeConfig: async (): Promise<{
    publishable_key: string | null;
    configured: boolean;
    live_api_enabled: boolean;
  }> => (await mobileApi.get("/payments/stripe/config")).data,

  failStripe: async (payload: { order_id: string; reason?: string }, guestToken?: string) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (await mobileApi.post(`/payments/stripe/fail${suffix}`, payload)).data;
  },

  retryPayment: async (orderId: string, paymentMethod: "razorpay" | "stripe", guestToken?: string) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (
      await mobileApi.post(`/payments/retry/${encodeURIComponent(orderId)}${suffix}`, {
        payment_method: paymentMethod,
      })
    ).data;
  },
};
