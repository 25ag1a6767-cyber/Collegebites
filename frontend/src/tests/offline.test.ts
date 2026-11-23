import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { useAppStore } from "../store/useAppStore";
import { useOfflineStore } from "../store/useOfflineStore";
import {
  assertQueueableMutation,
  computeReconnectDelayMs,
  executeOrQueueSafeMutation,
  fetchWithOfflineCache,
  flushSyncQueue,
  readOfflineCache,
  saveOfflineCache,
  stripSensitivePaymentFields,
} from "../utils/offlineSync";

vi.hoisted(() => {
  const store = new Map<string, string>();
  const mockStorage: Storage = {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, String(value));
    },
  };
  vi.stubGlobal("localStorage", mockStorage);
  vi.stubGlobal("navigator", { onLine: true });
});

describe("Phase 1: Offline Mode, Sync Queue & Payment Guardrails", () => {
  beforeEach(() => {
    localStorage.clear();
    useOfflineStore.setState({
      isOnline: true,
      networkState: "online",
      lastOnlineAt: null,
      lastSyncAt: null,
      isFlushingQueue: false,
      pendingQueue: [],
      recoveryLogs: [],
      cachedKeys: {},
    });
    useAppStore.setState({
      pendingCheckoutKey: null,
      pendingCheckoutCartSig: null,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
  });

  it("strips sensitive payment credentials and gateway secrets from local offline cache", () => {
    const rawOrder = {
      id: "ord-1",
      order_number: "CB-101",
      total_amount: "120.00",
      stripe_client_secret: "pi_secret_should_never_persist",
      razorpay_key_id: "rzp_live_secret_key",
      stripe_publishable_key: "pk_live_123",
      guest_access_token: "CBG_secret",
      card_number: "4111",
    };

    const clean = stripSensitivePaymentFields(rawOrder);
    expect(clean.order_number).toBe("CB-101");
    expect("stripe_client_secret" in clean).toBe(false);
    expect("razorpay_key_id" in clean).toBe(false);
    expect("stripe_publishable_key" in clean).toBe(false);
    expect("guest_access_token" in clean).toBe(false);
    expect("card_number" in clean).toBe(false);

    saveOfflineCache("order:CB-101", rawOrder);
    const loaded = readOfflineCache<any>("order:CB-101");
    expect(loaded?.data?.order_number).toBe("CB-101");
    expect(loaded?.data?.stripe_client_secret).toBeUndefined();
  });

  it("blocks financial, payment, and token-issuing routes from being queued offline", async () => {
    expect(() => assertQueueableMutation("/orders/checkout")).toThrow(/live online/i);
    expect(() => assertQueueableMutation("/payments/razorpay/verify")).toThrow(/live online/i);
    expect(() => assertQueueableMutation("/pos/orders")).toThrow(/live online/i);
    expect(() => assertQueueableMutation("/pickup/handover")).toThrow(/live online/i);
    expect(() => assertQueueableMutation("/kitchen/orders/1/accept", { cvv: "123" })).toThrow(/Sensitive field/i);

    await expect(
      executeOrQueueSafeMutation({
        method: "POST",
        url: "/orders/checkout",
        category: "other",
        label: "Illegal offline checkout",
      })
    ).rejects.toThrow(/cannot be queued offline/i);
  });

  it("keeps deterministic checkout idempotency key for same cart and rotates when cart changes", () => {
    const store = useAppStore.getState();
    const k1 = store.getOrCreateCheckoutIdemKey("c1:100.00:item1:razorpay");
    const k2 = useAppStore.getState().getOrCreateCheckoutIdemKey("c1:100.00:item1:razorpay");
    expect(k1).toBe(k2);

    const k3 = useAppStore.getState().getOrCreateCheckoutIdemKey("c1:200.00:item1,item2:razorpay");
    expect(k3).not.toBe(k1);

    useAppStore.getState().clearCheckoutIdemKey();
    const k4 = useAppStore.getState().getOrCreateCheckoutIdemKey("c1:200.00:item1,item2:razorpay");
    expect(k4).not.toBe(k3);
  });

  it("serves sanitized cached menu offline and recovers queued non-financial kitchen mutations with conflict detection", async () => {
    // 1. Live fetch populates cache
    const cachedMenu = await fetchWithOfflineCache("menu:c1:all", async () => [
      { id: "m1", name: "Masala Dosa", base_price: "55.00" },
    ]);
    expect(cachedMenu).toHaveLength(1);

    // 2. Simulate offline mode -> serves cached menu without crashing
    Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
    useOfflineStore.getState().setNetworkStatus(false, "offline");
    const offlineMenu = await fetchWithOfflineCache<any[]>("menu:c1:all", async () => {
      throw new Error("Network down");
    });
    expect(offlineMenu[0].name).toBe("Masala Dosa");

    // 3. Enqueue safe non-financial kitchen actions while offline
    const res1 = await executeOrQueueSafeMutation({
      method: "POST",
      url: "/kitchen/orders/ord-1/accept",
      category: "kitchen_status",
      label: "Accept Order CB-01",
    });
    const res2 = await executeOrQueueSafeMutation({
      method: "POST",
      url: "/kitchen/orders/ord-2/mark-ready",
      category: "kitchen_status",
      label: "Ready Order CB-02",
    });
    expect(res1.queued).toBe(true);
    expect(res2.queued).toBe(true);
    expect(useOfflineStore.getState().pendingQueue).toHaveLength(2);

    // 4. Reconnect -> first succeeds cleanly with idempotency key, second hits 409 Conflict from backend
    Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
    useOfflineStore.getState().setNetworkStatus(true, "online");

    const spy = vi.spyOn(api, "request").mockImplementation(async (cfg: any) => {
      if (String(cfg.url).includes("ord-1")) {
        expect(cfg.headers["X-Idempotency-Key"]).toMatch(/^cb-sync-/);
        return { data: { status: "ACCEPTED" } } as any;
      }
      const err: any = new Error("Conflict");
      err.isAxiosError = true;
      err.response = { status: 409, data: { detail: "Order already completed by another terminal" } };
      throw err;
    });

    await flushSyncQueue();
    expect(spy).toHaveBeenCalledTimes(2);

    const queue = useOfflineStore.getState().pendingQueue;
    expect(queue[0].status).toBe("synced");
    expect(queue[1].status).toBe("conflict");
    expect(queue[1].lastError).toContain("already completed");
  });

  it("caps exponential backoff reconnection delays cleanly", () => {
    const d0 = computeReconnectDelayMs(0, 1000, 15000, 0);
    const d2 = computeReconnectDelayMs(2, 1000, 15000, 0);
    const d6 = computeReconnectDelayMs(6, 1000, 15000, 0);
    expect(d0).toBe(1000);
    expect(d2).toBe(4000);
    expect(d6).toBe(15000);
  });
});
