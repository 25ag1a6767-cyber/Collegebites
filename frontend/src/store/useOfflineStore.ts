import { create } from "zustand";
import { persist } from "zustand/middleware";

export type NetworkState = "online" | "offline" | "reconnecting";

export type SyncQueueCategory = "kitchen_status" | "queue_control" | "staff_action" | "cart" | "other";

export type SyncActionStatus = "pending" | "syncing" | "synced" | "conflict" | "failed";

export interface PendingSyncAction {
  id: string;
  idempotencyKey: string;
  method: "POST" | "PATCH" | "PUT";
  url: string;
  data?: Record<string, any>;
  category: SyncQueueCategory;
  label: string;
  expectedUpdatedAt?: string | null;
  invalidateKeys?: string[][];
  attempts: number;
  status: SyncActionStatus;
  lastError?: string | null;
  createdAt: string;
}

export interface RecoveryLogEntry {
  id: string;
  timestamp: string;
  level: "info" | "warn" | "success" | "error";
  event: string;
  detail: string;
}

export interface CacheMetaEntry {
  key: string;
  cachedAt: string;
}

interface OfflineStoreState {
  isOnline: boolean;
  networkState: NetworkState;
  lastOnlineAt: string | null;
  lastSyncAt: string | null;
  isFlushingQueue: boolean;
  pendingQueue: PendingSyncAction[];
  recoveryLogs: RecoveryLogEntry[];
  cachedKeys: Record<string, string>;

  setNetworkStatus: (isOnline: boolean, networkState?: NetworkState) => void;
  setFlushing: (busy: boolean) => void;
  markSyncedNow: () => void;
  enqueueAction: (
    action: Omit<PendingSyncAction, "id" | "attempts" | "status" | "createdAt" | "lastError">
  ) => PendingSyncAction;
  updateActionStatus: (
    id: string,
    patch: Partial<Pick<PendingSyncAction, "status" | "attempts" | "lastError">>
  ) => void;
  removeAction: (id: string) => void;
  clearCompletedActions: () => void;
  addRecoveryLog: (level: RecoveryLogEntry["level"], event: string, detail: string) => void;
  clearRecoveryLogs: () => void;
  recordCacheWrite: (key: string, cachedAt: string) => void;
  clearCacheRegistry: () => void;
}

function makeId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const useOfflineStore = create<OfflineStoreState>()(
  persist(
    (set, get) => ({
      isOnline: typeof navigator === "undefined" ? true : navigator.onLine !== false,
      networkState:
        typeof navigator === "undefined"
          ? "online"
          : navigator.onLine === false
          ? "offline"
          : "online",
      lastOnlineAt: new Date().toISOString(),
      lastSyncAt: null,
      isFlushingQueue: false,
      pendingQueue: [],
      recoveryLogs: [],
      cachedKeys: {},

      setNetworkStatus: (isOnline, nextState) => {
        const prev = get();
        const computedState: NetworkState = nextState || (isOnline ? "online" : "offline");
        if (prev.isOnline === isOnline && prev.networkState === computedState) return;
        const nowIso = new Date().toISOString();
        set({
          isOnline,
          networkState: computedState,
          lastOnlineAt: isOnline ? nowIso : prev.lastOnlineAt,
        });
      },

      setFlushing: (busy) => set({ isFlushingQueue: busy }),

      markSyncedNow: () => set({ lastSyncAt: new Date().toISOString() }),

      enqueueAction: (action) => {
        const existing = get().pendingQueue.find(
          (item) =>
            item.idempotencyKey === action.idempotencyKey &&
            (item.status === "pending" || item.status === "syncing")
        );
        if (existing) return existing;

        const created: PendingSyncAction = {
          ...action,
          id: makeId("sync"),
          attempts: 0,
          status: "pending",
          lastError: null,
          createdAt: new Date().toISOString(),
        };
        set((state) => ({
          pendingQueue: [...state.pendingQueue, created].slice(-100),
        }));
        return created;
      },

      updateActionStatus: (id, patch) =>
        set((state) => ({
          pendingQueue: state.pendingQueue.map((item) =>
            item.id === id ? { ...item, ...patch } : item
          ),
        })),

      removeAction: (id) =>
        set((state) => ({
          pendingQueue: state.pendingQueue.filter((item) => item.id !== id),
        })),

      clearCompletedActions: () =>
        set((state) => ({
          pendingQueue: state.pendingQueue.filter((item) => item.status !== "synced"),
        })),

      addRecoveryLog: (level, event, detail) => {
        const entry: RecoveryLogEntry = {
          id: makeId("log"),
          timestamp: new Date().toISOString(),
          level,
          event,
          detail,
        };
        set((state) => ({
          recoveryLogs: [entry, ...state.recoveryLogs].slice(0, 60),
        }));
      },

      clearRecoveryLogs: () => set({ recoveryLogs: [] }),

      recordCacheWrite: (key, cachedAt) =>
        set((state) => ({
          cachedKeys: { ...state.cachedKeys, [key]: cachedAt },
        })),

      clearCacheRegistry: () => set({ cachedKeys: {} }),
    }),
    {
      name: "collegebites-offline-sync",
      partialize: (state) => ({
        lastOnlineAt: state.lastOnlineAt,
        lastSyncAt: state.lastSyncAt,
        pendingQueue: state.pendingQueue,
        recoveryLogs: state.recoveryLogs,
        cachedKeys: state.cachedKeys,
      }),
    }
  )
);
