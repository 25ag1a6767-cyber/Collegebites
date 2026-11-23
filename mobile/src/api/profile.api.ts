import { mobileApi } from "./client";

export const profileApi = {
  getProfile: async () => (await mobileApi.get("/customers/profile")).data,

  updateProfile: async (payload: {
    full_name?: string;
    phone?: string | null;
    college_id_number?: string | null;
    department?: string | null;
    dietary_preference?: string | null;
  }) => (await mobileApi.patch("/customers/profile", payload)).data,

  listFavourites: async () => (await mobileApi.get("/customers/favourites")).data,

  addFavourite: async (foodItemId: string) =>
    (await mobileApi.post(`/customers/favourites/${encodeURIComponent(foodItemId)}`)).data,

  removeFavourite: async (foodItemId: string) =>
    (await mobileApi.delete(`/customers/favourites/${encodeURIComponent(foodItemId)}`)).data,

  deactivateAccount: async () => (await mobileApi.delete("/customers/me")).data,

  getMyLoyalty: async () => (await mobileApi.get("/promotions/loyalty/me")).data,

  applyReferral: async (referralCode: string) =>
    (await mobileApi.post(`/promotions/loyalty/apply-referral?referral_code=${encodeURIComponent(referralCode)}`)).data,

  listMyTickets: async () => (await mobileApi.get("/support/tickets/my")).data,

  submitTicket: async (payload: Record<string, unknown>) =>
    (await mobileApi.post("/support/tickets", payload)).data,

  listMealPlans: async (canteenId?: string) =>
    (
      await mobileApi.get(
        `/meal-plans${canteenId ? `?canteen_id=${encodeURIComponent(canteenId)}` : ""}`
      )
    ).data,

  subscribeMealPlan: async (
    planId: string,
    payload: { payment_method: "razorpay" | "stripe"; auto_confirm_demo?: boolean }
  ) => (await mobileApi.post(`/meal-plans/${encodeURIComponent(planId)}/subscribe`, payload)).data,

  listMyMealSubscriptions: async () => (await mobileApi.get("/meal-plans/my-subscriptions")).data,

  listCollegeEvents: async () => (await mobileApi.get("/events")).data,

  createEventBulkOrder: async (
    eventId: string,
    payload: {
      canteen_id: string;
      organizer_name: string;
      organizer_phone: string;
      organizer_email?: string | null;
      department?: string | null;
      headcount: number;
      requested_delivery_at: string;
      delivery_venue?: string | null;
      special_instructions?: string | null;
      payment_method: "razorpay" | "stripe";
      items: Array<{ food_item_id: string; quantity: number }>;
    }
  ) => (await mobileApi.post(`/events/${encodeURIComponent(eventId)}/bulk-orders`, payload)).data,

  listMyBulkOrders: async () => (await mobileApi.get("/events/bulk-orders/my")).data,

  getOrderInvoice: async (orderId: string, guestToken?: string) =>
    (
      await mobileApi.get(
        `/invoices/${encodeURIComponent(orderId)}${
          guestToken ? `?guest_token=${encodeURIComponent(guestToken)}` : ""
        }`
      )
    ).data,
};
