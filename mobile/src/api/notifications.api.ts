import { mobileApi } from "./client";

export const notificationsApi = {
  listMy: async () => (await mobileApi.get("/notifications/my")).data,
  markRead: async (notificationId: string) =>
    (await mobileApi.post(`/notifications/${encodeURIComponent(notificationId)}/read`)).data,
  markAllRead: async () => (await mobileApi.post("/notifications/mark-all-read")).data,
  getPreferences: async () => (await mobileApi.get("/notifications/preferences")).data,
  updatePreferences: async (payload: Record<string, boolean>) =>
    (await mobileApi.put("/notifications/preferences", payload)).data,
  registerPushToken: async (payload: { token: string; platform: string; device_name?: string }) =>
    (await mobileApi.post("/notifications/push-tokens", payload)).data,
};
