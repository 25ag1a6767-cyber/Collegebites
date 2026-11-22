import React, { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BellRing, Check, Clock, Flame, Printer, Search, Star, Volume2, VolumeX } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useRealtimeSync } from "../../hooks/useRealtimeSync";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, FoodItem, Order } from "../../types";
import { playOrderAlertChime, showBrowserNotification } from "../../utils/notifications";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, InputPromptModal, Modal, Select, useToast } from "../../components/ui/Primitives";
import { RealtimeStatusBadge } from "../../components/ui/RealtimeStatusBadge";

function formatClockSeconds(totalSecs: number): string {
  const safe = Math.max(0, Math.floor(totalSecs));
  const m = Math.floor(safe / 60);
  const s = safe % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export const KitchenDisplayPage: React.FC = () => {
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { user, accessToken, selectedCanteenId } = useAppStore();
  const isCollegeWide = Boolean(user?.roles?.some((r) => r === "super_admin" || r === "college_admin"));

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [canteenId, setCanteenId] = useState<string>(user?.assigned_canteen_id || selectedCanteenId || "");
  const activeCanteenId =
    !isCollegeWide && user?.assigned_canteen_id ? user.assigned_canteen_id : canteenId || canteens[0]?.id || "";
  const [kitchenId, setKitchenId] = useState("");
  const [stationId, setStationId] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [delayedOnly, setDelayedOnly] = useState(false);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [delayModalOrder, setDelayModalOrder] = useState<Order | null>(null);
  const [delayMins, setDelayMins] = useState(10);
  const [delayReason, setDelayReason] = useState("High kitchen load");
  const [rejectOrderTarget, setRejectOrderTarget] = useState<Order | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAvailabilityModal, setShowAvailabilityModal] = useState(false);
  const [availModalTab, setAvailModalTab] = useState<"dishes" | "ingredients">("dishes");
  const [nowMs, setNowMs] = useState(() => Date.now());

  const prevPlacedIds = useRef<Set<string>>(new Set());
  const initialLoadedRef = useRef(false);

  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    prevPlacedIds.current.clear();
    initialLoadedRef.current = false;
  }, [activeCanteenId]);

  const { data: canteenDetail } = useQuery<Canteen>({
    queryKey: ["kitchen-canteen-detail", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/canteens/${activeCanteenId}`)).data,
  });

  const { status: kdsSyncStatus, lastSyncedAt: kdsLastSyncedAt } = useRealtimeSync<{ orders?: Order[] }>({
    enabled: Boolean(activeCanteenId && accessToken),
    ssePath: activeCanteenId ? `/realtime/staff/orders/stream?canteen_id=${activeCanteenId}` : null,
    wsPath: activeCanteenId ? `/ws/kitchen/${activeCanteenId}` : null,
    queryKeys: [["kitchen-orders", activeCanteenId, kitchenId, stationId], ["kitchen-stations", activeCanteenId]],
    onSnapshot: (snap) => {
      if (snap?.orders) {
        const activeOnly = snap.orders.filter(
          (o) =>
            ["PLACED", "ACCEPTED", "PREPARING", "READY"].includes(o.status) &&
            (!kitchenId || o.kitchen_id === kitchenId) &&
            (!stationId || o.items.some((it) => it.station_id === stationId))
        );
        qc.setQueryData(["kitchen-orders", activeCanteenId, kitchenId, stationId], activeOnly);
      } else {
        qc.invalidateQueries({ queryKey: ["kitchen-orders", activeCanteenId] });
      }
    },
    onEvent: () => {
      qc.invalidateQueries({ queryKey: ["kitchen-orders", activeCanteenId] });
      qc.invalidateQueries({ queryKey: ["kitchen-stations", activeCanteenId] });
    },
  });

  const { data: stations = [] } = useQuery<any[]>({
    queryKey: ["kitchen-stations", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/kitchen/canteens/${activeCanteenId}/stations`)).data,
    refetchInterval: kdsSyncStatus === "live" ? 30000 : 8000,
  });

  const { data: orders = [], refetch } = useQuery<Order[]>({
    queryKey: ["kitchen-orders", activeCanteenId, kitchenId, stationId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (kitchenId) qs.set("kitchen_id", kitchenId);
      if (stationId) qs.set("station_id", stationId);
      const q = qs.toString() ? `?${qs.toString()}` : "";
      return (await api.get(`/kitchen/canteens/${activeCanteenId}/orders${q}`)).data;
    },
    refetchInterval: kdsSyncStatus === "live" ? 30000 : 4000,
    refetchIntervalInBackground: true,
  });

  const { data: menuItems = [], refetch: refetchMenu } = useQuery<FoodItem[]>({
    queryKey: ["kitchen-menu", activeCanteenId],
    enabled: Boolean(activeCanteenId && showAvailabilityModal),
    refetchInterval: showAvailabilityModal ? 10000 : false,
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/items?include_inactive=false`)).data,
  });

  const { data: ingredients = [], refetch: refetchIngredients } = useQuery<any[]>({
    queryKey: ["kitchen-ingredients", activeCanteenId],
    enabled: Boolean(activeCanteenId && showAvailabilityModal),
    queryFn: async () => (await api.get(`/kitchen/canteens/${activeCanteenId}/ingredients`)).data,
  });

  // Sound + visual alert on new PLACED orders (works even when queue goes 0 -> 1)
  useEffect(() => {
    const placedOrders = orders.filter((o) => o.status === "PLACED");
    const placedIds = new Set(placedOrders.map((o) => o.id));
    if (!initialLoadedRef.current) {
      prevPlacedIds.current = placedIds;
      initialLoadedRef.current = true;
      return;
    }
    const newArrivals = placedOrders.filter((o) => !prevPlacedIds.current.has(o.id));
    if (newArrivals.length > 0) {
      if (soundEnabled) playOrderAlertChime(true);
      const first = newArrivals[0];
      pushToast(
        `New kitchen order ${first.pickup_token_code || first.order_number} (${first.items.length} items)`,
        "info"
      );
      void showBrowserNotification(
        `New Kitchen Order • ${first.pickup_token_code || first.order_number}`,
        `${first.items.map((i) => `${i.quantity}x ${i.item_name}`).join(", ")}`,
        "/kitchen"
      );
    }
    prevPlacedIds.current = placedIds;
  }, [orders, soundEnabled, pushToast]);

  // Real-time stream + WS handled by useRealtimeSync above

  const act = async (url: string, msg: string) => {
    try {
      await api.post(url);
      pushToast(msg, "success");
      refetch();
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const submitDelay = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!delayModalOrder) return;
    try {
      await api.post(`/kitchen/orders/${delayModalOrder.id}/report-delay`, {
        additional_minutes: delayMins,
        reason: delayReason,
      });
      pushToast("Delay reported and customer notified", "info");
      setDelayModalOrder(null);
      refetch();
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const columns = [
    { key: "PLACED", title: "New Orders", tone: "amber" as const },
    { key: "ACCEPTED", title: "Accepted", tone: "blue" as const },
    { key: "PREPARING", title: "Preparing", tone: "default" as const },
    { key: "READY", title: "Ready for Counter", tone: "green" as const },
  ];

  const overdueCount = useMemo(() => {
    return orders.filter((o) => {
      if (o.status === "READY") return false;
      const elapsedSecs = (nowMs - new Date(o.confirmed_at || o.created_at).getTime()) / 1000;
      const slaSecs = (o.estimated_prep_minutes + o.delayed_minutes) * 60;
      return elapsedSecs > slaSecs;
    }).length;
  }, [orders, nowMs]);

  const delayedCount = orders.filter((o) => o.delayed_minutes > 0).length;

  const filteredOrders = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return [...orders]
      .sort((a, b) => Number(Boolean(b.is_priority)) - Number(Boolean(a.is_priority)))
      .filter((o) => {
        if (delayedOnly) {
          const elapsedSecs = (nowMs - new Date(o.confirmed_at || o.created_at).getTime()) / 1000;
          const slaSecs = (o.estimated_prep_minutes + o.delayed_minutes) * 60;
          if (o.delayed_minutes === 0 && elapsedSecs <= slaSecs) return false;
        }
        if (!q) return true;
        return (
          (o.pickup_token_code || "").toLowerCase().includes(q) ||
          o.order_number.toLowerCase().includes(q) ||
          o.items.some((i) => i.item_name.toLowerCase().includes(q))
        );
      });
  }, [orders, delayedOnly, searchQuery, nowMs]);

  const cycleItemPrepStatus = async (itemId: string, current?: string) => {
    const next = current === "PENDING" || !current ? "PREPARING" : current === "PREPARING" ? "READY" : "PENDING";
    try {
      await api.post(`/kitchen/order-items/${itemId}/prep-status`, { prep_status: next });
      refetch();
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-5 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-[#380106] p-4 text-white">
        <div className="flex items-center gap-3">
          <BrandLogo size="md" variant="dark" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-extrabold">Kitchen Display System (KDS)</h1>
              <RealtimeStatusBadge status={kdsSyncStatus} lastSyncedAt={kdsLastSyncedAt} darkSurface />
              {overdueCount > 0 && (
                <Badge tone="red">
                  <AlertTriangle className="h-3 w-3 inline mr-1" />
                  {overdueCount} Overdue
                </Badge>
              )}
            </div>
            <p className="text-xs text-[#fdedce]/80">
              {orders.length} active orders • {delayedCount} marked delayed
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Token / Order..."
              className="pl-8 w-40 bg-slate-800 border-slate-700 text-white placeholder:text-slate-400"
            />
          </div>
          <Button
            size="sm"
            variant={delayedOnly ? "danger" : "outline"}
            onClick={() => setDelayedOnly((v) => !v)}
          >
            Delayed/SLA ({delayedCount + overdueCount})
          </Button>
          <Select
            value={activeCanteenId}
            disabled={!isCollegeWide && Boolean(user?.assigned_canteen_id)}
            onChange={(e) => {
              setCanteenId(e.target.value);
              setKitchenId("");
              setStationId("");
            }}
            className="w-48 bg-slate-800 border-slate-700 text-white"
          >
            {canteens.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          {stations.length > 0 && (
            <Select
              value={stationId}
              onChange={(e) => setStationId(e.target.value)}
              className="w-44 bg-slate-800 border-slate-700 text-white"
            >
              <option value="">All Stations</option>
              {stations.map((s: any) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.pending_units} items)
                </option>
              ))}
            </Select>
          )}
          {canteenDetail?.kitchens && canteenDetail.kitchens.length > 0 && (
            <Select
              value={kitchenId}
              onChange={(e) => setKitchenId(e.target.value)}
              className="w-40 bg-slate-800 border-slate-700 text-white"
            >
              <option value="">All Kitchens</option>
              {canteenDetail.kitchens.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
            </Select>
          )}
          <Button size="sm" variant="outline" onClick={() => setShowAvailabilityModal(true)}>
            <AlertTriangle className="h-4 w-4 text-amber-600" /> Ingredient / Item Availability
          </Button>
          <Button
            size="sm"
            variant={soundEnabled ? "primary" : "outline"}
            onClick={() => {
              setSoundEnabled(!soundEnabled);
              if (!soundEnabled) playOrderAlertChime();
            }}
          >
            {soundEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
            {soundEnabled ? "Sound Alerts ON" : "Muted"}
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {columns.map((col) => {
          const colOrders = filteredOrders.filter((o) => o.status === col.key);
          return (
            <div key={col.key} className="rounded-2xl border border-slate-200 bg-slate-100/70 p-3 space-y-3 min-h-[420px]">
              <div className="flex items-center justify-between px-1">
                <h2 className="font-extrabold text-sm text-slate-800">{col.title}</h2>
                <Badge tone={col.tone}>{colOrders.length}</Badge>
              </div>

              {colOrders.map((o) => {
                const startIso = o.confirmed_at || o.created_at;
                const elapsedSecs = Math.max(0, (nowMs - new Date(startIso).getTime()) / 1000);
                const slaSecs = (o.estimated_prep_minutes + o.delayed_minutes) * 60;
                const isOverdue = o.status !== "READY" && elapsedSecs > slaSecs;
                return (
                  <Card
                    key={o.id}
                    className={`p-4 space-y-3 ${
                      o.is_priority
                        ? "border-red-500 ring-2 ring-red-500/30 bg-red-50/30"
                        : isOverdue
                        ? "border-amber-500 ring-2 ring-amber-400/30"
                        : o.status === "PLACED"
                        ? "border-amber-400 ring-2 ring-amber-400/20"
                        : ""
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-2xl font-black text-slate-900">{o.pickup_token_code || o.order_number}</span>
                          {o.is_priority && (
                            <Badge tone="red">
                              <Star className="h-3 w-3 inline fill-current mr-0.5" /> RUSH
                            </Badge>
                          )}
                        </div>
                        <div className="text-[11px] font-semibold text-slate-500">
                          {o.order_number} • {o.counter_name}
                        </div>
                      </div>
                      <div className="text-right space-y-1">
                        <Badge tone={isOverdue ? "red" : "slate"}>
                          <Clock className="h-3 w-3" /> {formatClockSeconds(elapsedSecs)}
                        </Badge>
                        {o.delayed_minutes > 0 && (
                          <div className="text-[10px] font-bold text-red-600">+{o.delayed_minutes}m delay</div>
                        )}
                        <div>
                          <button
                            type="button"
                            onClick={() =>
                              api
                                .post(`/kitchen/orders/${o.id}/priority`, { is_priority: !o.is_priority })
                                .then(() => refetch())
                                .catch((err) => pushToast(getApiError(err), "error"))
                            }
                            className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                              o.is_priority ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                            }`}
                          >
                            <Star className={`h-2.5 w-2.5 ${o.is_priority ? "fill-current" : ""}`} />
                            {o.is_priority ? "Priority" : "Bump"}
                          </button>
                        </div>
                      </div>
                    </div>

                    <div className="space-y-1.5 border-y border-slate-100 py-2 text-xs">
                      {o.items.map((it) => {
                        const prepState = it.prep_status || "PENDING";
                        return (
                          <div key={it.id} className="space-y-0.5">
                            <div className="flex items-start justify-between gap-2">
                              <div className="font-bold text-slate-900">
                                {it.quantity}× {it.item_name} {it.variant_name ? `(${it.variant_name})` : ""}
                              </div>
                              {o.status !== "READY" && (
                                <button
                                  type="button"
                                  onClick={() => cycleItemPrepStatus(it.id, prepState)}
                                  className={`rounded px-1.5 py-0.5 text-[10px] font-bold shrink-0 ${
                                    prepState === "READY"
                                      ? "bg-emerald-100 text-emerald-800"
                                      : prepState === "PREPARING"
                                      ? "bg-amber-100 text-amber-800"
                                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                                  }`}
                                  title="Click to cycle item prep status (PENDING → PREPARING → READY)"
                                >
                                  {prepState}
                                </button>
                              )}
                            </div>
                            {it.customizations.map((c) => (
                              <div key={c.id} className="pl-3 text-slate-600">
                                • {c.option_name}: {c.option_value}
                              </div>
                            ))}
                            {it.special_instructions && (
                              <div className="pl-3 font-semibold text-[#76010d]">Note: {it.special_instructions}</div>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    <div className="flex flex-wrap gap-1.5">
                      {o.status === "PLACED" && (
                        <Button
                          size="sm"
                          variant="primary"
                          className="flex-1"
                          onClick={() => act(`/kitchen/orders/${o.id}/accept`, `Accepted ${o.pickup_token_code}`)}
                        >
                          <BellRing className="h-3.5 w-3.5" /> Accept
                        </Button>
                      )}
                      {o.status === "ACCEPTED" && (
                        <Button
                          size="sm"
                          variant="secondary"
                          className="flex-1"
                          onClick={() =>
                            act(`/kitchen/orders/${o.id}/start-preparing`, `Preparing ${o.pickup_token_code}`)
                          }
                        >
                          <Flame className="h-3.5 w-3.5" /> Start Prep
                        </Button>
                      )}
                      {o.status === "PREPARING" && (
                        <Button
                          size="sm"
                          variant="success"
                          className="flex-1"
                          onClick={() => act(`/kitchen/orders/${o.id}/mark-ready`, `${o.pickup_token_code} marked READY!`)}
                        >
                          <Check className="h-3.5 w-3.5" /> Mark Ready
                        </Button>
                      )}
                      {o.status !== "READY" && (
                        <Button size="sm" variant="outline" onClick={() => setDelayModalOrder(o)}>
                          Delay
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        title="Download KOT ESC/POS Thermal Ticket"
                        onClick={async () => {
                          try {
                            const stParam = stationId ? `&station_id=${stationId}` : "";
                            const res = await api.get(`/printing/kitchen-ticket/${o.order_number}/escpos?width=80mm${stParam}`);
                            pushToast(`KOT prepared (${res.data.item_count} items, ${res.data.byte_length} bytes)`, "success");
                          } catch (err) {
                            pushToast(getApiError(err, "KOT export failed"), "error");
                          }
                        }}
                      >
                        <Printer className="h-3.5 w-3.5" /> KOT
                      </Button>
                      {o.status === "PLACED" && (
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => setRejectOrderTarget(o)}
                        >
                          Reject
                        </Button>
                      )}
                    </div>
                  </Card>
                );
              })}
            </div>
          );
        })}
      </div>

      {/* Report Delay Modal */}
      <Modal
        open={Boolean(delayModalOrder)}
        onClose={() => setDelayModalOrder(null)}
        title={`Report Delay • ${delayModalOrder?.pickup_token_code}`}
      >
        <form onSubmit={submitDelay} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-bold text-slate-700">Additional Minutes</label>
            <Input type="number" min={1} max={120} value={delayMins} onChange={(e) => setDelayMins(Number(e.target.value))} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-bold text-slate-700">Reason</label>
            <Input value={delayReason} onChange={(e) => setDelayReason(e.target.value)} required />
          </div>
          <Button type="submit" variant="primary" className="w-full">
            Update ETA & Notify Customer
          </Button>
        </form>
      </Modal>

      {/* Unavailable Item & Ingredient Modal */}
      <Modal
        open={showAvailabilityModal}
        onClose={() => setShowAvailabilityModal(false)}
        title="Kitchen Availability & Ingredient Reporting"
      >
        <div className="space-y-3">
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={availModalTab === "dishes" ? "primary" : "outline"}
              onClick={() => setAvailModalTab("dishes")}
            >
              Dishes ({menuItems.length})
            </Button>
            <Button
              size="sm"
              variant={availModalTab === "ingredients" ? "primary" : "outline"}
              onClick={() => setAvailModalTab("ingredients")}
            >
              Ingredients ({ingredients.length})
            </Button>
          </div>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {availModalTab === "dishes"
              ? menuItems.map((item) => (
                  <div key={item.id} className="flex items-center justify-between rounded-xl border border-slate-200 p-3 text-xs">
                    <div>
                      <div className="font-bold text-slate-900">{item.name}</div>
                      <div className="text-slate-500">₹{item.base_price}</div>
                    </div>
                    <Button
                      size="sm"
                      variant={item.is_available ? "success" : "danger"}
                      onClick={async () => {
                        try {
                          await api.post(`/kitchen/items/${item.id}/unavailable`, {
                            is_available: !item.is_available,
                            reason: "Toggled from Kitchen Display",
                          });
                          refetchMenu();
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      {item.is_available ? "Available" : "Unavailable"}
                    </Button>
                  </div>
                ))
              : ingredients.map((ing) => (
                  <div
                    key={ing.inventory_item_id}
                    className="flex items-center justify-between rounded-xl border border-slate-200 p-3 text-xs"
                  >
                    <div>
                      <div className="font-bold text-slate-900">{ing.name}</div>
                      <div className="text-slate-500">
                        On hand: {ing.current_quantity} {ing.unit}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant={Number(ing.current_quantity) <= 0 || ing.is_available === false ? "danger" : "outline"}
                        disabled={Number(ing.current_quantity) <= 0 || ing.is_available === false}
                        onClick={async () => {
                          try {
                            await api.post(`/kitchen/ingredients/${ing.inventory_item_id}/unavailable`, {
                              reason: "Reported exhausted from Kitchen Display",
                            });
                            pushToast(`Reported ${ing.name} unavailable & notified Inventory Manager`, "info");
                            refetchIngredients();
                            refetchMenu();
                          } catch (err) {
                            pushToast(getApiError(err), "error");
                          }
                        }}
                      >
                        {Number(ing.current_quantity) <= 0 || ing.is_available === false ? "Reported Out" : "Report Out"}
                      </Button>
                      {ing.is_available === false && Number(ing.current_quantity) > 0 && (
                        <Button
                          size="sm"
                          variant="success"
                          onClick={async () => {
                            try {
                              await api.post(`/kitchen/ingredients/${ing.inventory_item_id}/restore`);
                              pushToast(`Restored ${ing.name}`, "success");
                              refetchIngredients();
                              refetchMenu();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Restore
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
          </div>
        </div>
      </Modal>

      <InputPromptModal
        open={Boolean(rejectOrderTarget)}
        title={`Reject Order • ${rejectOrderTarget?.pickup_token_code || rejectOrderTarget?.order_number || ""}`}
        label="Rejection Reason (payment records remain retained per college policy)"
        defaultValue="Ingredient unavailable"
        placeholder="Reason for rejecting order"
        submitLabel="Reject Order"
        busy={busy}
        onCancel={() => setRejectOrderTarget(null)}
        onSubmit={async (reason: string) => {
          if (!rejectOrderTarget) return;
          setBusy(true);
          try {
            await api.post(`/kitchen/orders/${rejectOrderTarget.id}/reject`, { reason });
            pushToast(`Order ${rejectOrderTarget.pickup_token_code || rejectOrderTarget.order_number} rejected`, "info");
            setRejectOrderTarget(null);
            refetch();
          } catch (err) {
            pushToast(getApiError(err), "error");
          } finally {
            setBusy(false);
          }
        }}
      />
    </div>
  );
};
