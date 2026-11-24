import React, { memo, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import {
  AlertTriangle,
  Check,
  Clock,
  Flame,
  PackageCheck,
  Play,
  QrCode,
  Search,
  Star,
} from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useRealtimeSync } from "../../hooks/useRealtimeSync";
import { useAppStore } from "../../store/useAppStore";
import { useOfflineStore } from "../../store/useOfflineStore";
import { executeOrQueueSafeMutation, isNetworkOfflineError, readOfflineCache, saveOfflineCache } from "../../utils/offlineSync";
import type { Canteen, OperationalTokenBoardResponse, OperationalTokenCard } from "../../types";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../components/ui/Primitives";
import { RealtimeStatusBadge } from "../../components/ui/RealtimeStatusBadge";

const KITCHEN_PROCESS_ROLES = new Set(["super_admin", "college_admin", "canteen_manager", "kitchen_staff"]);
const HANDOVER_ROLES = new Set(["super_admin", "college_admin", "canteen_manager", "cashier", "pickup_staff"]);

function formatDuration(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(safe / 60);
  const secs = safe % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

interface CardProps {
  card: OperationalTokenCard;
  nowMs: number;
  busy: boolean;
  canKitchen: boolean;
  canHandover: boolean;
  onAction: (card: OperationalTokenCard, action: "accept" | "start-preparing" | "mark-ready" | "handover") => void;
  onShowQr: (card: OperationalTokenCard) => void;
}

const TokenOrderCard: React.FC<CardProps> = memo(({
  card,
  nowMs,
  busy,
  canKitchen,
  canHandover,
  onAction,
  onShowQr,
}) => {
  const startIso = card.confirmed_at || card.created_at;
  const endIso = card.status === "COMPLETED" ? card.completed_at || card.ready_at : null;
  const elapsedSeconds = Math.max(
    0,
    ((endIso ? new Date(endIso).getTime() : nowMs) - new Date(startIso).getTime()) / 1000
  );
  const slaSeconds = (card.estimated_prep_minutes + card.delayed_minutes) * 60;
  const isOverdue = card.status !== "COMPLETED" && elapsedSeconds > slaSeconds;
  const orderTimeLabel = new Date(card.created_at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <Card
      data-testid={`token-card-${card.token_code}`}
      className={`p-3.5 space-y-2.5 transition-all ${
        card.is_priority
          ? "border-red-400 ring-2 ring-red-500/20 bg-red-50/30"
          : isOverdue
          ? "border-amber-400 ring-1 ring-amber-400/40"
          : "border-slate-200"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-1.5">
            <span className="text-2xl font-black tracking-wide text-slate-900 font-mono">
              {card.token_code}
            </span>
            {card.is_priority && (
              <Badge tone="red">
                <Star className="h-3 w-3 mr-0.5 inline fill-current" /> RUSH
              </Badge>
            )}
          </div>
          <div className="text-[11px] font-bold text-slate-700 mt-0.5">
            {card.order_number}
          </div>
          <div className="text-[11px] text-slate-500">
            {card.customer_label} • {card.order_type.replace("_", " ")}
          </div>
        </div>

        <div className="text-right space-y-1">
          <div
            className={`inline-flex items-center gap-1 rounded-lg px-2 py-0.5 text-xs font-mono font-extrabold ${
              isOverdue
                ? "bg-red-100 text-red-700 animate-pulse"
                : card.status === "COMPLETED"
                ? "bg-slate-100 text-slate-600"
                : "bg-amber-50 text-amber-800"
            }`}
            title="Live Preparation / Queue Timer"
          >
            <Clock className="h-3 w-3" />
            {formatDuration(elapsedSeconds)}
          </div>
          <div className="text-[10px] text-slate-500 font-semibold">
            {orderTimeLabel} • {card.counter_name}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
        <Badge tone={card.payment_status === "CONFIRMED" ? "green" : "amber"}>
          {card.payment_status} ({card.payment_method.toUpperCase()})
        </Badge>
        <Badge tone={card.status === "READY" ? "green" : card.status === "PREPARING" ? "amber" : "slate"}>
          {card.status}
        </Badge>
        {card.delayed_minutes > 0 && (
          <Badge tone="red">
            <AlertTriangle className="h-2.5 w-2.5 inline mr-0.5" />+{card.delayed_minutes}m
          </Badge>
        )}
        <button
          type="button"
          onClick={() => onShowQr(card)}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] font-bold text-slate-700 hover:bg-slate-100"
          title="Inspect Order Pickup QR Reference"
        >
          <QrCode className="h-3 w-3 text-[#76010d]" />
          {card.qr_reference || card.token_code}
        </button>
      </div>

      <div className="border-t border-slate-100 pt-2 space-y-1">
        {card.items.map((item) => (
          <div key={item.id} className="flex items-start justify-between gap-2 text-xs">
            <div className="text-slate-800 font-medium">
              <span className="font-extrabold text-[#76010d]">{item.quantity}x</span> {item.item_name}
              {item.variant_name && <span className="text-slate-500 text-[11px]"> ({item.variant_name})</span>}
              {item.special_instructions && (
                <div className="text-[10px] text-amber-700 italic">Note: {item.special_instructions}</div>
              )}
            </div>
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold shrink-0 ${
                item.prep_status === "READY"
                  ? "bg-emerald-50 text-emerald-700"
                  : item.prep_status === "PREPARING"
                  ? "bg-amber-50 text-amber-700"
                  : "bg-slate-100 text-slate-500"
              }`}
            >
              {item.prep_status}
            </span>
          </div>
        ))}
      </div>

      {(canKitchen || canHandover) && card.status !== "COMPLETED" && (
        <div className="pt-2 border-t border-slate-100 flex flex-wrap items-center justify-between gap-2">
          <span className="text-[11px] font-bold text-slate-500">₹{card.total_amount}</span>
          <div className="flex items-center gap-1.5">
            {canKitchen && card.status === "PLACED" && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => onAction(card, "accept")}>
                <Check className="h-3.5 w-3.5" /> Accept
              </Button>
            )}
            {canKitchen && card.status === "ACCEPTED" && (
              <Button size="sm" variant="primary" disabled={busy} onClick={() => onAction(card, "start-preparing")}>
                <Play className="h-3.5 w-3.5" /> Start Preparing
              </Button>
            )}
            {canKitchen && card.status === "PREPARING" && (
              <Button size="sm" variant="success" disabled={busy} onClick={() => onAction(card, "mark-ready")}>
                <Flame className="h-3.5 w-3.5" /> Mark Ready
              </Button>
            )}
            {canHandover && card.status === "READY" && (
              <Button size="sm" variant="success" disabled={busy} onClick={() => onAction(card, "handover")}>
                <PackageCheck className="h-3.5 w-3.5" /> Complete
              </Button>
            )}
          </div>
        </div>
      )}
    </Card>
  );
});
TokenOrderCard.displayName = "TokenOrderCard";

export const OperationalTokenBoardPage: React.FC = () => {
  const { canteenId: routeCanteenId } = useParams<{ canteenId?: string }>();
  const { user, accessToken, selectedCanteenId } = useAppStore();
  const { pushToast } = useToast();
  const qc = useQueryClient();

  const userRoles = user?.roles || [];
  const isCollegeWide = userRoles.some((r) => r === "super_admin" || r === "college_admin");
  const canKitchen = userRoles.some((r) => KITCHEN_PROCESS_ROLES.has(r));
  const canHandover = userRoles.some((r) => HANDOVER_ROLES.has(r));

  const [selectedId, setSelectedId] = useState(routeCanteenId || "");
  const [searchQuery, setSearchQuery] = useState("");
  const [counterFilter, setCounterFilter] = useState("");
  const [activeMobileTab, setActiveMobileTab] = useState<string>("all");
  const [busyOrderId, setBusyOrderId] = useState<string | null>(null);
  const [qrModalCard, setQrModalCard] = useState<OperationalTokenCard | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const activeScope =
    !isCollegeWide && user?.assigned_canteen_id
      ? user.assigned_canteen_id
      : selectedId || routeCanteenId || selectedCanteenId || "all";

  const ssePath =
    activeScope === "all"
      ? "/realtime/token-board/stream"
      : `/realtime/token-board/stream?canteen_id=${activeScope}`;
  const wsPath = activeScope === "all" ? "/ws/board/all" : `/ws/kitchen/${activeScope}`;

  const isOnline = useOfflineStore((s) => s.isOnline);
  const lastOpCachedVerRef = React.useRef<string | null>(null);

  const { status: syncStatus, lastSyncedAt, triggerSync } = useRealtimeSync<OperationalTokenBoardResponse>({
    enabled: Boolean(accessToken),
    ssePath,
    wsPath,
    queryKeys: [["operational-token-board", activeScope]],
    onSnapshot: (snap) => {
      if (snap?.version && snap.version !== lastOpCachedVerRef.current) {
        lastOpCachedVerRef.current = snap.version;
        saveOfflineCache(`op-board:${activeScope}`, snap);
      }
      qc.setQueryData(["operational-token-board", activeScope], snap);
    },
  });

  const { data: board, dataUpdatedAt: opUpdatedAt, isLoading } = useQuery<OperationalTokenBoardResponse>({
    queryKey: ["operational-token-board", activeScope],
    enabled: Boolean(accessToken),
    queryFn: async () => {
      const qs = activeScope === "all" ? "" : `?canteen_id=${encodeURIComponent(activeScope)}`;
      try {
        const res = await api.get<OperationalTokenBoardResponse>(`/pickup/token-board${qs}`, {
          headers: { "Cache-Control": "no-cache", Pragma: "no-cache" },
        });
        const live = res.data;
        if (live?.version && live.version !== lastOpCachedVerRef.current) {
          lastOpCachedVerRef.current = live.version;
          saveOfflineCache(`op-board:${activeScope}`, live);
        }
        return live;
      } catch (err) {
        if (isNetworkOfflineError(err)) {
          const cached = readOfflineCache<OperationalTokenBoardResponse>(`op-board:${activeScope}`);
          if (cached) return cached.data;
        }
        throw err;
      }
    },
    staleTime: 0,
    retry: false,
    refetchInterval: () =>
      typeof navigator !== "undefined" && navigator.onLine === false
        ? false
        : syncStatus === "live"
        ? 15000
        : 2000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const effectiveOpSyncedAt =
    opUpdatedAt && (!lastSyncedAt || opUpdatedAt > lastSyncedAt.getTime())
      ? new Date(opUpdatedAt)
      : lastSyncedAt;

  const handleAction = async (
    card: OperationalTokenCard,
    action: "accept" | "start-preparing" | "mark-ready" | "handover"
  ) => {
    setBusyOrderId(card.order_id);
    try {
      if (action === "handover") {
        if (!isOnline) {
          pushToast("Handover confirmation requires live connectivity.", "error");
          return;
        }
        await api.post("/pickup/handover", {
          order_id: card.order_id,
          counter_id: card.counter_id,
          verification_method: "manual_token",
        });
        pushToast(`Token ${card.token_code} completed`, "success");
      } else {
        const res = await executeOrQueueSafeMutation({
          method: "POST",
          url: `/kitchen/orders/${card.order_id}/${action}`,
          category: "kitchen_status",
          label: `Token ${card.token_code}: ${action}`,
          invalidateKeys: [["operational-token-board"], ["kitchen-orders"]],
        });
        pushToast(
          res.queued
            ? `Offline: "${action}" queued for ${card.token_code} and will sync on reconnect`
            : `Token ${card.token_code} moved to next stage`,
          res.queued ? "info" : "success"
        );
      }
      triggerSync();
    } catch (err) {
      pushToast(getApiError(err, "Action failed"), "error");
    } finally {
      setBusyOrderId(null);
    }
  };

  const sections = useMemo(() => {
    const rawSections = [
      { key: "new_orders", title: "New Orders", tone: "amber" as const, items: board?.new_orders || [] },
      { key: "accepted_orders", title: "Accepted Orders", tone: "blue" as const, items: board?.accepted_orders || [] },
      { key: "preparing_orders", title: "Preparing Orders", tone: "default" as const, items: board?.preparing_orders || [] },
      { key: "ready_for_pickup", title: "Ready for Pickup", tone: "green" as const, items: board?.ready_for_pickup || [] },
      { key: "completed_orders", title: "Completed Orders", tone: "slate" as const, items: board?.completed_orders || [] },
    ];
    const q = searchQuery.trim().toLowerCase();
    return rawSections.map((sec) => ({
      ...sec,
      items: sec.items.filter((card) => {
        if (counterFilter && card.counter_name !== counterFilter) return false;
        if (!q) return true;
        return (
          card.token_code.toLowerCase().includes(q) ||
          card.order_number.toLowerCase().includes(q) ||
          card.customer_label.toLowerCase().includes(q) ||
          card.items.some((i) => i.item_name.toLowerCase().includes(q))
        );
      }),
    }));
  }, [board, searchQuery, counterFilter]);

  const counterNames = useMemo(() => {
    const names = new Set<string>();
    const all = [
      ...(board?.new_orders || []),
      ...(board?.accepted_orders || []),
      ...(board?.preparing_orders || []),
      ...(board?.ready_for_pickup || []),
      ...(board?.completed_orders || []),
    ];
    for (const c of all) names.add(c.counter_name);
    return Array.from(names).sort();
  }, [board]);

  const visibleSections =
    activeMobileTab === "all" ? sections : sections.filter((s) => s.key === activeMobileTab);

  return (
    <div className="mx-auto max-w-[1520px] px-4 py-5 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-[#380106] p-4 text-white">
        <div className="flex items-center gap-3">
          <BrandLogo size="md" variant="dark" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-extrabold">Live Token Board — Order Management</h1>
              <RealtimeStatusBadge
                status={syncStatus}
                lastSyncedAt={effectiveOpSyncedAt}
                darkSurface
                connectedLabel="Connected • 1s Auto"
              />
            </div>
            <p className="text-xs text-[#fdedce]/80">
              {board?.canteen_name || "All Campus Canteens"} • Real-time PostgreSQL synchronized queue
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={activeScope}
            disabled={!isCollegeWide && Boolean(user?.assigned_canteen_id)}
            onChange={(e) => {
              setSelectedId(e.target.value);
              setCounterFilter("");
            }}
            className="w-52 bg-slate-900 border-slate-700 text-white"
          >
            {isCollegeWide && <option value="all">All Campus Canteens</option>}
            {canteens.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>

          <Select
            value={counterFilter}
            onChange={(e) => setCounterFilter(e.target.value)}
            className="w-44 bg-slate-900 border-slate-700 text-white"
          >
            <option value="">All Counters</option>
            {counterNames.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>

          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Token / Order / Item..."
              className="pl-8 w-48 bg-slate-900 border-slate-700 text-white placeholder:text-slate-400"
            />
          </div>
        </div>
      </div>

      {/* Section Filter Tabs & Counts */}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant={activeMobileTab === "all" ? "secondary" : "outline"}
          onClick={() => setActiveMobileTab("all")}
        >
          All 5 Sections
        </Button>
        {sections.map((s) => (
          <Button
            key={s.key}
            size="sm"
            variant={activeMobileTab === s.key ? "secondary" : "outline"}
            onClick={() => setActiveMobileTab(s.key)}
          >
            {s.title} ({s.items.length})
          </Button>
        ))}
      </div>

      {isLoading ? (
        <Card className="p-8 text-center text-sm text-slate-500">Connecting to real-time Token Board stream...</Card>
      ) : (
        <div
          className={`grid gap-4 ${
            activeMobileTab === "all" ? "md:grid-cols-2 xl:grid-cols-5" : "grid-cols-1 md:grid-cols-2 xl:grid-cols-3"
          }`}
        >
          {visibleSections.map((section) => (
            <div
              key={section.key}
              data-testid={`section-${section.key}`}
              className="rounded-2xl border border-slate-200 bg-slate-100/70 p-3 space-y-3 min-h-[360px]"
            >
              <div className="flex items-center justify-between px-1">
                <h2 className="font-extrabold text-sm text-slate-900">{section.title}</h2>
                <Badge tone={section.tone}>{section.items.length}</Badge>
              </div>

              {section.items.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-300 bg-white/60 p-6 text-center text-xs text-slate-400">
                  No orders in {section.title.toLowerCase()}.
                </div>
              ) : (
                <div className={activeMobileTab === "all" ? "space-y-3" : "contents"}>
                  {section.items.map((card) => (
                    <TokenOrderCard
                      key={card.order_id}
                      card={card}
                      nowMs={nowMs}
                      busy={busyOrderId === card.order_id}
                      canKitchen={canKitchen}
                      canHandover={canHandover}
                      onAction={handleAction}
                      onShowQr={setQrModalCard}
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <Modal
        open={Boolean(qrModalCard)}
        onClose={() => setQrModalCard(null)}
        title={qrModalCard ? `Order ${qrModalCard.order_number} • Token ${qrModalCard.token_code}` : ""}
      >
        {qrModalCard && (
          <div className="space-y-3 text-center">
            <div className="text-xs font-mono font-bold text-slate-600">{qrModalCard.qr_reference}</div>
            {qrModalCard.qr_verification_path && (
              <div className="inline-block rounded-2xl border border-slate-200 bg-white p-4">
                <QRCodeSVG
                  value={`${window.location.origin}${qrModalCard.qr_verification_path}`}
                  size={180}
                />
              </div>
            )}
            <div className="text-xs text-slate-500">
              {qrModalCard.canteen_name} • {qrModalCard.counter_name} • {qrModalCard.customer_label}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
