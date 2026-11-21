import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { mobileApi } from "../api/client";

export async function registerExpoPushToken(): Promise<string | null> {
  if (Platform.OS === "web") return null;
  const { status: existing } = await Notifications.getPermissionsAsync();
  let finalStatus = existing;
  if (existing !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== "granted") return null;
  try {
    const tokenObj = await Notifications.getExpoPushTokenAsync();
    await mobileApi.put("/notifications/preferences", {
      push_enabled: true,
      expo_push_token: tokenObj.data,
    });
    return tokenObj.data;
  } catch {
    return null;
  }
}
