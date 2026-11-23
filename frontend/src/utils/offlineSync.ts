import axios from "axios";
import type { QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useOfflineStore, type SyncQueueCategory } from "../store/useOfflineStore";

const CACHE_PREFIX = "cb_offline_cache_v1:";

const FORBIDDEN_OFFLINE_PATTERNS = [
  /\/payments\b/i,
  /\/orders\/checkout/i,
  /\/pos\/orders/i,
  /\/kiosk\/orders/i,
  /\/pickup\/handover/i,
  /razorpay/i,
  /stripe/i,
  /reconcil/i,
];

const SENSITIVE_CACHE_FIELDS = new Set([
  "stripe_client_secret",
  "razorpay_key_id",
  "stripe_publishable_key",
  "guest_access_token",
  "password",
  "password_hash",
  "card_number",
  "cvv",
  "secret",
]);

/**
 * Compute capped exponential backoff with jitter for WebSocket / SSE / retry loops.
 */
export function computeReconnectDelayMs(
  attempt: number,
  baseMs = 1000,
  capMs = 15000,
  jitterMs = 350
): number {
  const safeAttempt = Math.max(0, attempt);
  const exp = Math.min(capMs, baseMs * Math.pow(2, Math.min(safeAttempt, 5)));
  const jitter = jitterMs > 0 ? Math.floor(Math.random() * jitterMs) : 0;
  return exp + jitter;
}

/**
 * Strip payment gateway secrets, credentials, or sensitive tokens before saving snapshots locally.
 */
export function stripSensitivePaymentFields<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => stripSensitivePaymentFields(item)) as unknown as T;
  }
  if (value && typeof value === "object") {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(value as Record<string, any>)) {
      if (SENSITIVE_CACHE_FIELDS.has(k)) continue;
      out[k] = stripSensitivePaymentFields(v);
    }
    return out as T;
  }
  return value;
}

/**
 * Enforce strict payment restriction: financial & token-issuing routes must never be queued offline.
 */
export function assertQueueableMutation(url: string, data?: Record<string, any>): void {
  if (FORBIDDEN_OFFLINE_PATTERNS.some((rx) => rx.test(url))) {
    throw new Error(
      "Financial, checkout, and payment verification actions require live online server verification and cannot be queued offline."
    );
  }
  if (data && typeof data === "object") {
    for (const k of Object.keys(data)) {
      if (/card|cvv|secret|signature|pin/i.test(k)) {
        throw new Error(`Sensitive field '${k}' cannot be stored or queued offline.`);
      }
    }
  }
}

export function isNetworkOfflineError(err: unknown): boolean {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return true;
  if (axios.isAxiosError(err)) {
    if (!err.response) return true;
    return err.response.status >= 502;
  }
  return false;
}

export function saveOfflineCache<T>(key: string, data: T): string | null {
  if (typeof localStorage === "undefined") return null;
  const cachedAt = new Date().toISOString();
  try {
    const clean = stripSensitivePaymentFields(data);
    localStorage.setItem(`${CACHE_PREFIX}${key}`, JSON.stringify({ cachedAt, data: clean }));
    useOfflineStore.getState().recordCacheWrite(key, cachedAt);
    return cachedAt;
  } catch {
    return null;
  }
}

export function readOfflineCache<T>(key: string): { cachedAt: string; data: T } | null {
  if (typeof localStorage === "undefined") return null;
  try {
    const raw = localStorage.getItem(`${CACHE_PREFIX}${key}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || !("data" in parsed)) return null;
    return { cachedAt: String(parsed.cachedAt || ""), data: parsed.data as T };
  } catch {
    return null;
  }
}

export function clearAllOfflineCache(): void {
  if (typeof localStorage === "undefined") return;
  const toDelete: string[] = [];
  for (let i = 0; i < localStorage.length; i += 1) {
    const k = localStorage.key(i);
    if (k && k.startsWith(CACHE_PREFIX)) toDelete.push(k);
  }
  for (const k of toDelete) {
    localStorage.removeItem(k);
  }
  useOfflineStore.getState().clearCacheRegistry();
}

/**
 * Fetch live data from backend and cache read-only sanitized snapshot.
 * If network is unreachable and a cached snapshot exists, return cached data without crashing.
 */
export async function fetchWithOfflineCache<T>(
  cacheKey: string,
  fetcher: () => Promise<T>
): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    const cached = readOfflineCache<T>(cacheKey);
    if (cached) return cached.data;
  }
  try {
    const live = await fetcher();
    saveOfflineCache(cacheKey, live);
    return live;
  } catch (err) {
    if (isNetworkOfflineError(err)) {
      const cached = readOfflineCache<T>(cacheKey);
      if (cached) {
        return cached.data;
      }
    }
    throw err;
  }
}

export function createMutationIdempotencyKey(prefix = "cb-mut"): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Execute a safe non-financial staff mutation immediately if online, or queue cleanly for recovery sync.
 */
export async function executeOrQueueSafeMutation(opts: {
  method: "POST" | "PATCH" | "PUT";
  url: string;
  data?: Record<string, any>;
  category: SyncQueueCategory;
  label: string;
  expectedUpdatedAt?: string | null;
  invalidateKeys?: string[][];
}): Promise<{ queued: boolean; data?: any }> {
  assertQueueableMutation(opts.url, opts.data);
  const idemKey = createMutationIdempotencyKey("cb-sync");
  const isOnline = typeof navigator === "undefined" ? true : navigator.onLine !== false;

  if (isOnline && useOfflineStore.getState().isOnline) {
    try {
      const res = await api.request({
        method: opts.method,
        url: opts.url,
        data: opts.data,
        headers: { "X-Idempotency-Key": idemKey },
      });
      return { queued: false, data: res.data };
    } catch (err) {
      if (!isNetworkOfflineError(err)) {
        throw err;
      }
    }
  }

  useOfflineStore.getState().enqueueAction({
    idempotencyKey: idemKey,
    method: opts.method,
    url: opts.url,
    data: opts.data,
    category: opts.category,
    label: opts.label,
    expectedUpdatedAt: opts.expectedUpdatedAt ?? null,
    invalidateKeys: opts.invalidateKeys,
  });
  useOfflineStore
    .getState()
    .addRecoveryLog("info", "Action queued offline", `${opts.label} (${opts.method} ${opts.url})`);
  return { queued: true };
}

let flushLock: Promise<void> | null = null;

/**
 * Flush pending offline mutations sequentially on reconnection, detecting 409 conflicts safely.
 */
export async function flushSyncQueue(queryClient?: QueryClient): Promise<void> {
  if (flushLock) return flushLock;
  flushLock = (async () => {
    const store = useOfflineStore.getState();
    if (!store.isOnline || (typeof navigator !== "undefined" && navigator.onLine === false)) return;

    const pending = store.pendingQueue.filter((a) => a.status === "pending");
    if (pending.length === 0) return;

    store.setFlushing(true);
    let syncedCount = 0;

    try {
      for (const action of pending) {
        if (typeof navigator !== "undefined" && navigator.onLine === false) {
          break;
        }
        try {
          assertQueueableMutation(action.url, action.data);
        } catch (guardErr: any) {
          store.updateActionStatus(action.id, {
            status: "failed",
            attempts: action.attempts + 1,
            lastError: guardErr?.message || "Blocked unsafe queued action",
          });
          store.addRecoveryLog("error", "Unsafe queued action blocked", action.label);
          continue;
        }

        store.updateActionStatus(action.id, { status: "syncing", attempts: action.attempts + 1 });
        try {
          await api.request({
            method: action.method,
            url: action.url,
            data: action.data,
            headers: { "X-Idempotency-Key": action.idempotencyKey },
          });
          store.updateActionStatus(action.id, { status: "synced", lastError: null });
          store.markSyncedNow();
          syncedCount += 1;
          store.addRecoveryLog("success", "Synced offline action", action.label);
          if (queryClient && action.invalidateKeys) {
            for (const qk of action.invalidateKeys) {
              queryClient.invalidateQueries({ queryKey: qk });
            }
          }
        } catch (err: any) {
          if (isNetworkOfflineError(err)) {
            store.updateActionStatus(action.id, {
              status: "pending",
              lastError: "Connection interrupted while syncing; will retry automatically.",
            });
            store.setNetworkStatus(false, "offline");
            store.addRecoveryLog("warn", "Sync paused (offline)", action.label);
            break;
          }
          const status = axios.isAxiosError(err) ? err.response?.status : undefined;
          const detail =
            (axios.isAxiosError(err) && typeof err.response?.data?.detail === "string"
              ? err.response.data.detail
              : err?.message) || "Server rejected stale or invalid update";

          if (status === 409 || status === 400 || status === 412) {
            store.updateActionStatus(action.id, { status: "conflict", lastError: detail });
            store.addRecoveryLog("warn", "Sync conflict detected", `${action.label}: ${detail}`);
          } else {
            store.updateActionStatus(action.id, { status: "failed", lastError: detail });
            store.addRecoveryLog("error", "Sync action failed", `${action.label}: ${detail}`);
          }
        }
      }

      if (syncedCount > 0 && queryClient) {
        queryClient.invalidateQueries();
      }
    } finally {
      useOfflineStore.getState().setFlushing(false);
    }
  })().finally(() => {
    flushLock = null;
  });

  return flushLock;
}
