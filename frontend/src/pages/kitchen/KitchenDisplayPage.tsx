import React, { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BellRing, Check, ChefHat, Clock, Flame, Volume2, VolumeX } from "lucide-react";
import { api, buildWsUrl, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, FoodItem, Order } from "../../types";
import { Badge, Button, Card, Input, InputPromptModal, Modal, Select, useToast } from "../../components/ui/Primitives";

function playChime() {
  try {
    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(1174, ctx.currentTime + 0.12);
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.42);
  } catch {
    // browser autoplay policy may require user interaction first
  }
}

export const KitchenDisplayPage: React.FC = () => {
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { user, accessToken, selectedCanteenId } = useAppStore();

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [canteenId, setCanteenId] = useState<string>(user?.assigned_canteen_id || selectedCanteenId || "");
  const activeCanteenId = canteenId || canteens[0]?.id || "";
  const [kitchenId, setKitchenId] = useState("");
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [delayModalOrder, setDelayModalOrder] = useState<Order | null>(null);
  const [delayMins, setDelayMins] = useState(10);
  const [delayReason, setDelayReason] = useState("High kitchen load");
  const [rejectOrderTarget, setRejectOrderTarget] = useState<Order | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAvailabilityModal, setShowAvailabilityModal] = useState(false);
  const [availModalTab, setAvailModalTab] = useState<"dishes" | "ingredients">("dishes");

  const prevPlacedIds = useRef<Set<string>>(new Set());

  const { data: canteenDetail } = useQuery<Canteen>({
    queryKey: ["kitchen-canteen-detail", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/canteens/${activeCanteenId}`)).data,
  });

  const { data: orders = [], refetch } = useQuery<Order[]>({
    queryKey: ["kitchen-orders", activeCanteenId, kitchenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => {
      const q = kitchenId ? `?kitchen_id=${kitchenId}` : "";
      return (await api.get(`/kitchen/canteens/${activeCanteenId}/orders${q}`)).data;
    },
    refetchInterval: 4000,
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

  // Sound alert on new PLACED orders
  useEffect(() => {
    const placedIds = new Set(orders.filter((o) => o.status === "PLACED").map((o) => o.id));
    let hasNew = false;
    placedIds.forEach((id) => {
      if (!prevPlacedIds.current.has(id)) hasNew = true;
    });
    if (hasNew && prevPlacedIds.current.size > 0 && soundEnabled) {
      playChime();
    }
    prevPlacedIds.current = placedIds;
  }, [orders, soundEnabled]);

  // WebSocket live push
  useEffect(() => {
    if (!activeCanteenId || !accessToken) return;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(buildWsUrl(`/ws/kitchen/${activeCanteenId}`, { token: accessToken }));
      ws.onmessage = () => {
        if (soundEnabled) playChime();
        qc.invalidateQueries({ queryKey: ["kitchen-orders", activeCanteenId] });
      };
    } catch {
      // polling handles updates
    }
    return () => ws?.close();
  }, [activeCanteenId, accessToken, soundEnabled, qc]);

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

  const delayedCount = orders.filter((o) => o.delayed_minutes > 0).length;

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-5 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-slate-900 p-4 text-white">
        <div className="flex items-center gap-3">
          <ChefHat className="h-7 w-7 text-orange-400" />
          <div>
            <h1 className="text-xl font-extrabold">Kitchen Display System (KDS)</h1>
            <p className="text-xs text-slate-400">
              {orders.length} active orders • {delayedCount} delayed
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={activeCanteenId}
            onChange={(e) => {
              setCanteenId(e.target.value);
              setKitchenId("");
            }}
            className="w-48 bg-slate-800 border-slate-700 text-white"
          >
            {canteens.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
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
              if (!soundEnabled) playChime();
            }}
          >
            {soundEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
            {soundEnabled ? "Sound Alerts ON" : "Muted"}
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {columns.map((col) => {
          const colOrders = orders.filter((o) => o.status === col.key);
          return (
            <div key={col.key} className="rounded-2xl border border-slate-200 bg-slate-100/70 p-3 space-y-3 min-h-[420px]">
              <div className="flex items-center justify-between px-1">
                <h2 className="font-extrabold text-sm text-slate-800">{col.title}</h2>
                <Badge tone={col.tone}>{colOrders.length}</Badge>
              </div>

              {colOrders.map((o) => {
                const elapsedMins = Math.max(0, Math.floor((Date.now() - new Date(o.created_at).getTime()) / 60000));
                return (
                  <Card
                    key={o.id}
                    className={`p-4 space-y-3 ${
                      o.status === "PLACED" ? "border-amber-400 ring-2 ring-amber-400/30" : ""
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="text-2xl font-black text-slate-900">{o.pickup_token_code || o.order_number}</div>
                        <div className="text-[11px] font-semibold text-slate-500">
                          {o.order_number} • {o.counter_name}
                        </div>
                      </div>
                      <div className="text-right">
                        <Badge tone={elapsedMins > o.estimated_prep_minutes ? "red" : "slate"}>
                          <Clock className="h-3 w-3" /> {elapsedMins}m
                        </Badge>
                        {o.delayed_minutes > 0 && (
                          <div className="mt-1 text-[10px] font-bold text-red-600">+{o.delayed_minutes}m delay</div>
                        )}
                      </div>
                    </div>

                    <div className="space-y-1.5 border-y border-slate-100 py-2 text-xs">
                      {o.items.map((it) => (
                        <div key={it.id} className="space-y-0.5">
                          <div className="font-bold text-slate-900">
                            {it.quantity}× {it.item_name} {it.variant_name ? `(${it.variant_name})` : ""}
                          </div>
                          {it.customizations.map((c) => (
                            <div key={c.id} className="pl-3 text-slate-600">
                              • {c.option_name}: {c.option_value}
                            </div>
                          ))}
                          {it.special_instructions && (
                            <div className="pl-3 font-semibold text-orange-700">Note: {it.special_instructions}</div>
                          )}
                        </div>
                      ))}
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
                    <Button
                      size="sm"
                      variant={Number(ing.current_quantity) <= 0 ? "danger" : "outline"}
                      disabled={Number(ing.current_quantity) <= 0}
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
                      {Number(ing.current_quantity) <= 0 ? "Reported Out" : "Report Out"}
                    </Button>
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
