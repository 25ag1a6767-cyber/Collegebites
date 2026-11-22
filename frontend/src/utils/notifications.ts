import { api } from "../api/client";

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export function playOrderAlertChime(urgent = false): void {
  try {
    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = urgent ? "triangle" : "sine";
    osc.frequency.setValueAtTime(urgent ? 980 : 840, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(urgent ? 1320 : 1140, ctx.currentTime + 0.14);
    gain.gain.setValueAtTime(0.14, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.42);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.44);
  } catch {
    // autoplay / audio policy restricted until gesture
  }
}

export async function showBrowserNotification(title: string, body: string, urlPath = "/orders"): Promise<void> {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  try {
    if ("serviceWorker" in navigator) {
      const reg = await navigator.serviceWorker.getRegistration();
      if (reg) {
        await reg.showNotification(title, {
          body,
          icon: "/icons/icon-192.png",
          badge: "/icons/icon-192.png",
          data: { url: urlPath },
        });
        return;
      }
    }
    new Notification(title, { body, icon: "/icons/icon-192.png" });
  } catch {
    // browser notification blocked
  }
}

export async function enableBrowserPushNotifications(): Promise<{ granted: boolean; pushSubscribed: boolean }> {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return { granted: false, pushSubscribed: false };
  }
  const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
  if (perm !== "granted") {
    return { granted: false, pushSubscribed: false };
  }
  let pushSubscribed = false;
  try {
    const { data } = await api.get<{ public_key?: string | null; supported: boolean }>("/notifications/web-push/public-key");
    if (data?.supported && data.public_key && "serviceWorker" in navigator && "PushManager" in window) {
      const reg = await navigator.serviceWorker.ready;
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        const keyBytes = urlBase64ToUint8Array(data.public_key);
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: keyBytes.buffer as ArrayBuffer,
        });
      }
      const subJson = sub.toJSON();
      await api.post("/notifications/web-push/subscribe", {
        endpoint: sub.endpoint,
        keys: subJson.keys || {},
        device_name: navigator.userAgent.slice(0, 80),
      });
      pushSubscribed = true;
    }
  } catch {
    // Local HTML5/SW Notifications still operate via SSE + WS when VAPID keys are absent
  }
  return { granted: true, pushSubscribed };
}
