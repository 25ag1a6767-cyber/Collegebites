import { useEffect, useState } from "react";

export interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
  prompt(): Promise<void>;
}

let deferredInstallPrompt: BeforeInstallPromptEvent | null = null;
const listeners = new Set<() => void>();

function notifyListeners() {
  listeners.forEach((fn) => fn());
}

export function initPwaListeners() {
  if (typeof window === "undefined") return;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredInstallPrompt = e as BeforeInstallPromptEvent;
    notifyListeners();
  });
  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    notifyListeners();
  });
}

export function isRunningStandalone(): boolean {
  if (typeof window === "undefined") return false;
  const nav = window.navigator as Navigator & { standalone?: boolean };
  return window.matchMedia?.("(display-mode: standalone)")?.matches === true || nav.standalone === true;
}

export function isIosSafari(): boolean {
  if (typeof window === "undefined") return false;
  const ua = window.navigator.userAgent || "";
  return /iphone|ipad|ipod/i.test(ua) && !/(crios|fxios|edgios)/i.test(ua);
}

export function usePwaInstall() {
  const [canPrompt, setCanPrompt] = useState(Boolean(deferredInstallPrompt));
  const [installed, setInstalled] = useState(isRunningStandalone());

  useEffect(() => {
    const sync = () => {
      setCanPrompt(Boolean(deferredInstallPrompt));
      setInstalled(isRunningStandalone());
    };
    listeners.add(sync);
    sync();
    return () => {
      listeners.delete(sync);
    };
  }, []);

  const promptInstall = async (): Promise<"accepted" | "dismissed" | "manual"> => {
    if (!deferredInstallPrompt) return "manual";
    try {
      await deferredInstallPrompt.prompt();
      const res = await deferredInstallPrompt.userChoice;
      if (res.outcome === "accepted") {
        deferredInstallPrompt = null;
        notifyListeners();
      }
      return res.outcome;
    } catch {
      return "manual";
    }
  };

  return {
    canPrompt,
    installed,
    isIos: isIosSafari(),
    promptInstall,
  };
}
