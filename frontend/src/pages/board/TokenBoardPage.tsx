import React, { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Flame, PackageCheck, Play, Volume2, VolumeX } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useRealtimeSync } from "../../hooks/useRealtimeSync";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, DigitalBoardResponse, TokenBoardItem } from "../../types";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Select, useToast } from "../../components/ui/Primitives";
import { RealtimeStatusBadge } from "../../components/ui/RealtimeStatusBadge";

const KITCHEN_PROCESS_ROLES = new Set(["super_admin", "college_admin", "canteen_manager", "kitchen_staff"]);
const HANDOVER_ROLES = new Set(["super_admin", "college_admin", "canteen_manager", "cashier", "pickup_staff"]);

export const TokenBoardPage: React.FC = () => {
  const { canteenId: routeCanteenId } = useParams<{ canteenId?: string }>();
  const { user, selectedCanteenId } = useAppStore();
  const { pushToast } = useToast();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState(routeCanteenId || "");
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [busyOrderId, setBusyOrderId] = useState<string | null>(null);
  const announcedTokens = useRef<Set<string>>(new Set());

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const userRoles = user?.roles || [];
  const isCollegeWide = userRoles.some((r) => r === "super_admin" || r === "college_admin");
  const isStaffUser = userRoles.some((r) => KITCHEN_PROCESS_ROLES.has(r) || HANDOVER_ROLES.has(r));
  const activeScope =
    selectedId ||
    routeCanteenId ||
    (isStaffUser && user?.assigned_canteen_id ? user.assigned_canteen_id : "") ||
    selectedCanteenId ||
    "all";

  const boardEndpoint = activeScope === "all" ? "/pickup/board" : `/pickup/board/${activeScope}`;
  const ssePath =
    activeScope === "all" ? "/realtime/board/stream" : `/realtime/board/stream?canteen_id=${activeScope}`;
  const wsPath = activeScope === "all" ? "/ws/board/all" : `/ws/board/${activeScope}`;

  const { status: syncStatus, lastSyncedAt, triggerSync } = useRealtimeSync<DigitalBoardResponse>({
    enabled: Boolean(activeScope),
    ssePath,
    wsPath,
    queryKeys: [["digital-board", activeScope]],
    onSnapshot: (snapshot) => {
      qc.setQueryData(["digital-board", activeScope], snapshot);
    },
  });

  const { data: board } = useQuery<DigitalBoardResponse>({
    queryKey: ["digital-board", activeScope],
    enabled: Boolean(activeScope),
    queryFn: async () => (await api.get(boardEndpoint)).data,
    refetchInterval: syncStatus === "live" ? 30000 : 4000,
    refetchIntervalInBackground: true,
  });

  useEffect(() => {
    if (!board?.ready_for_pickup) return;
    for (const t of board.ready_for_pickup) {
      const announceKey = `${t.order_id || t.token_code}:${t.token_code}`;
      if (!announcedTokens.current.has(announceKey)) {
        if (announcedTokens.current.size > 0 && voiceEnabled && "speechSynthesis" in window) {
          const utter = new SpeechSynthesisUtterance(
            `Token ${t.token_code.split("").join(" ")} is ready for pickup at ${t.counter_name}`
          );
          window.speechSynthesis.speak(utter);
        }
        announcedTokens.current.add(announceKey);
      }
    }
  }, [board, voiceEnabled]);

  const canActOnItem = (t: TokenBoardItem, allowedSet: Set<string>): boolean => {
    if (!t.order_id || !userRoles.some((r) => allowedSet.has(r))) return false;
    if (isCollegeWide || !user?.assigned_canteen_id || !t.canteen_id) return true;
    return user.assigned_canteen_id === t.canteen_id;
  };

  const processOrderAction = async (t: TokenBoardItem, action: "accept" | "start-preparing" | "mark-ready" | "handover") => {
    if (!t.order_id) return;
    setBusyOrderId(t.order_id);
    try {
      if (action === "handover") {
        await api.post("/pickup/handover", {
          order_id: t.order_id,
          verification_method: "manual_token",
        });
        pushToast(`Token ${t.token_code} handed over & completed`, "success");
      } else {
        await api.post(`/kitchen/orders/${t.order_id}/${action}`);
        const label =
          action === "accept" ? "Accepted" : action === "start-preparing" ? "Preparing" : "Ready for Pickup";
        pushToast(`Token ${t.token_code} → ${label}`, "success");
      }
      triggerSync();
    } catch (err) {
      pushToast(getApiError(err, "Could not update order status"), "error");
    } finally {
      setBusyOrderId(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div className="flex items-center gap-4">
          <Link to="/" className="rounded-xl bg-slate-800 p-2 text-slate-300 hover:text-white">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <BrandLogo size="md" variant="dark" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-widest text-[#fdedce]">
                COLLEGEBITES LIVE STATUS
              </span>
              <RealtimeStatusBadge status={syncStatus} lastSyncedAt={lastSyncedAt} darkSurface />
            </div>
            <h1 className="text-3xl font-black tracking-tight">{board?.canteen_name || "Canteen Display Board"}</h1>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Select
            value={activeScope}
            onChange={(e) => {
              announcedTokens.current.clear();
              setSelectedId(e.target.value);
            }}
            className="w-60 bg-slate-900 border-slate-700 text-white"
          >
            <option value="all">All Campus Canteens (Live)</option>
            {canteens.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Button
            variant={voiceEnabled ? "primary" : "outline"}
            size="sm"
            onClick={() => {
              const next = !voiceEnabled;
              setVoiceEnabled(next);
              if (next && "speechSynthesis" in window) {
                window.speechSynthesis.cancel();
                window.speechSynthesis.speak(new SpeechSynthesisUtterance("Voice announcements enabled"));
              }
            }}
          >
            {voiceEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
            {voiceEnabled ? "Audio ON" : "Audio OFF"}
          </Button>
        </div>
      </div>

      <div className="grid flex-1 gap-6 lg:grid-cols-2">
        {/* NOW PREPARING */}
        <div className="rounded-3xl border border-amber-500/30 bg-slate-900/80 p-6">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-2xl font-black tracking-wide text-amber-400">NOW PREPARING</h2>
            <span className="rounded-full bg-amber-500/20 px-3 py-1 text-sm font-bold text-amber-300">
              {board?.now_preparing?.length || 0}
            </span>
          </div>
          {!board?.now_preparing?.length ? (
            <div className="rounded-2xl border border-dashed border-slate-800 p-8 text-center text-sm text-slate-400">
              No active orders in queue right now. Confirmed orders appear automatically here.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {board.now_preparing.map((t) => {
                const showKitchenBtn = canActOnItem(t, KITCHEN_PROCESS_ROLES);
                const busy = busyOrderId === t.order_id;
                return (
                  <div
                    key={t.order_id || t.token_code}
                    className="rounded-2xl border border-slate-700 bg-slate-800/90 p-4 flex flex-col justify-between gap-3"
                  >
                    <div className="text-center">
                      <div className="flex items-center justify-between text-[11px] font-bold text-slate-400 mb-1">
                        <span>{t.order_number || ""}</span>
                        <span>{t.counter_name}</span>
                      </div>
                      <div className="text-4xl font-black tracking-wider text-white">{t.token_code}</div>
                      <div className="mt-1.5 flex flex-wrap items-center justify-center gap-1.5">
                        <Badge tone={t.order_status === "PREPARING" ? "amber" : t.order_status === "ACCEPTED" ? "blue" : "slate"}>
                          {t.order_status}
                        </Badge>
                        {Boolean(t.delayed_minutes && t.delayed_minutes > 0) && (
                          <Badge tone="red">+{t.delayed_minutes}m delay</Badge>
                        )}
                      </div>
                      {activeScope === "all" && t.canteen_name && (
                        <div className="mt-1 text-[11px] font-semibold text-[#fdedce]/80">{t.canteen_name}</div>
                      )}
                      {t.item_summary && (
                        <div className="mt-2 text-xs text-slate-300 line-clamp-2">{t.item_summary}</div>
                      )}
                    </div>

                    {showKitchenBtn && (
                      <div className="pt-2 border-t border-slate-700/80 flex justify-center">
                        {t.order_status === "PLACED" && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy}
                            onClick={() => processOrderAction(t, "accept")}
                            className="w-full"
                          >
                            <Check className="h-3.5 w-3.5" /> Accept
                          </Button>
                        )}
                        {t.order_status === "ACCEPTED" && (
                          <Button
                            size="sm"
                            variant="primary"
                            disabled={busy}
                            onClick={() => processOrderAction(t, "start-preparing")}
                            className="w-full"
                          >
                            <Play className="h-3.5 w-3.5" /> Start Preparing
                          </Button>
                        )}
                        {t.order_status === "PREPARING" && (
                          <Button
                            size="sm"
                            variant="success"
                            disabled={busy}
                            onClick={() => processOrderAction(t, "mark-ready")}
                            className="w-full"
                          >
                            <Flame className="h-3.5 w-3.5" /> Mark Ready
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* READY FOR PICKUP */}
        <div className="rounded-3xl border border-emerald-500/40 bg-emerald-950/30 p-6">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-2xl font-black tracking-wide text-emerald-400">READY FOR PICKUP</h2>
            <span className="rounded-full bg-emerald-500/20 px-3 py-1 text-sm font-bold text-emerald-300">
              {board?.ready_for_pickup?.length || 0}
            </span>
          </div>
          {!board?.ready_for_pickup?.length ? (
            <div className="rounded-2xl border border-dashed border-emerald-800/60 p-8 text-center text-sm text-emerald-200/70">
              No tokens currently waiting at the pickup counter.
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {board.ready_for_pickup.map((t) => {
                const showHandoverBtn = canActOnItem(t, HANDOVER_ROLES);
                const busy = busyOrderId === t.order_id;
                return (
                  <div
                    key={t.order_id || t.token_code}
                    className="flex flex-col justify-between gap-3 rounded-2xl border border-emerald-500/50 bg-emerald-900/50 px-5 py-4 shadow-lg"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-5xl font-black tracking-wider text-white">{t.token_code}</div>
                        {t.order_number && (
                          <div className="text-[11px] font-semibold text-emerald-200/80 mt-0.5">{t.order_number}</div>
                        )}
                      </div>
                      <div className="text-right">
                        <div className="text-xs font-bold uppercase text-emerald-300">Collect at</div>
                        <div className="text-lg font-extrabold text-white">{t.counter_name}</div>
                        {activeScope === "all" && t.canteen_name && (
                          <div className="text-[11px] text-emerald-200/80">{t.canteen_name}</div>
                        )}
                      </div>
                    </div>
                    {t.item_summary && (
                      <div className="text-xs text-emerald-100/90 line-clamp-2">{t.item_summary}</div>
                    )}
                    {showHandoverBtn && (
                      <Button
                        size="sm"
                        variant="success"
                        disabled={busy}
                        onClick={() => processOrderAction(t, "handover")}
                        className="w-full"
                      >
                        <PackageCheck className="h-3.5 w-3.5" /> Confirm Handover (Complete)
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {board?.recently_completed && board.recently_completed.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900 px-5 py-3 flex flex-wrap items-center gap-3 text-sm">
          <span className="font-bold text-slate-400 uppercase text-xs">Recently Collected:</span>
          {board.recently_completed.map((t) => (
            <span
              key={t.order_id || t.token_code}
              className="rounded-lg bg-slate-800 px-2.5 py-1 font-mono font-bold text-slate-300"
              title={t.order_number ? `${t.order_number} • ${t.counter_name}` : t.counter_name}
            >
              {t.token_code}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
