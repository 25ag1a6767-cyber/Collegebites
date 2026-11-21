import { mobileApi } from "./client";

export const ordersApi = {
  getPickupSlots: async (canteenId: string) =>
    (await mobileApi.get(`/orders/slots/${encodeURIComponent(canteenId)}`)).data,

  checkout: async (
    payload: {
      canteen_id: string;
      counter_id?: string | null;
      location_qr_code?: string | null;
      pickup_slot_id?: string | null;
      order_type?: "pickup" | "dine_in" | "walk_in" | "kiosk" | "qr_table";
      order_channel?: "web" | "mobile" | "qr" | "pos" | "kiosk";
      payment_method: "razorpay" | "stripe";
      redeem_loyalty_points?: number;
      idempotency_key: string;
      guest_name?: string | null;
      guest_phone?: string | null;
      guest_email?: string | null;
      guest_otp_verification_token?: string | null;
      notes?: string | null;
      accepted_policy: boolean;
    },
    idempotencyKey: string
  ) =>
    (
      await mobileApi.post("/orders/checkout", payload, {
        headers: { "X-Idempotency-Key": idempotencyKey },
      })
    ).data,

  listMyOrders: async () => (await mobileApi.get("/orders/my")).data,

  getOrder: async (orderIdOrNumber: string, guestToken?: string) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (await mobileApi.get(`/orders/${encodeURIComponent(orderIdOrNumber)}${suffix}`)).data;
  },

  lookupGuestOrders: async (guestPhone: string, otpVerificationToken: string) =>
    (
      await mobileApi.post("/orders/guest/lookup", {
        guest_phone: guestPhone,
        otp_verification_token: otpVerificationToken,
      })
    ).data,

  cancelOrder: async (orderId: string, reason: string, guestToken?: string) => {
    const suffix = guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : "";
    return (await mobileApi.post(`/orders/${encodeURIComponent(orderId)}/cancel${suffix}`, { reason })).data;
  },
};
