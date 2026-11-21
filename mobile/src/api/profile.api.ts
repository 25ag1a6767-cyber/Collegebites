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
};
