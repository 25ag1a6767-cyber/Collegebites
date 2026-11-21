import { mobileApi } from "./client";

export const canteensApi = {
  getCollegeSettings: async () => (await mobileApi.get("/canteens/college")).data,
  listCanteens: async () => (await mobileApi.get("/canteens")).data,
  getCanteenDetail: async (canteenId: string) => (await mobileApi.get(`/canteens/${canteenId}`)).data,
  listActivePromotions: async (canteenId?: string) =>
    (await mobileApi.get(`/promotions${canteenId ? `?canteen_id=${encodeURIComponent(canteenId)}` : ""}`)).data,
  listAnnouncements: async () => (await mobileApi.get("/notifications/announcements")).data,
};
