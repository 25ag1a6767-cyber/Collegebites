import React, { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Volume2, VolumeX } from "lucide-react";
import { api } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen } from "../../types";
import { Button, Select } from "../../components/ui/Primitives";

export const TokenBoardPage: React.FC = () => {
  const { canteenId: routeCanteenId } = useParams<{ canteenId?: string }>();
  const { selectedCanteenId } = useAppStore();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState(routeCanteenId || "");
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const announcedTokens = useRef<Set<string>>(new Set());

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const activeId = selectedId || routeCanteenId || selectedCanteenId || canteens[0]?.id || "";

  const { data: board } = useQuery<any>({
    queryKey: ["digital-board", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/pickup/board/${activeId}`)).data,
    refetchInterval: 4000,
  });

  useEffect(() => {
    if (!activeId) return;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`${proto}://${window.location.host}/api/v1/ws/board/${activeId}`);
      ws.onmessage = () => qc.invalidateQueries({ queryKey: ["digital-board", activeId] });
    } catch {
      // polling fallback
    }
    return () => ws?.close();
  }, [activeId, qc]);

  useEffect(() => {
    if (!board?.ready_for_pickup) return;
    for (const t of board.ready_for_pickup) {
      if (!announcedTokens.current.has(t.token_code)) {
        if (announcedTokens.current.size > 0 && voiceEnabled && "speechSynthesis" in window) {
          const utter = new SpeechSynthesisUtterance(
            `Token ${t.token_code.split("").join(" ")} is ready for pickup at ${t.counter_name}`
          );
          window.speechSynthesis.speak(utter);
        }
        announcedTokens.current.add(t.token_code);
      }
    }
  }, [board, voiceEnabled]);

  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div className="flex items-center gap-4">
          <Link to="/" className="rounded-xl bg-slate-800 p-2 text-slate-300 hover:text-white">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <div className="text-xs font-bold uppercase tracking-widest text-orange-400">COLLEGEBITES LIVE STATUS</div>
            <h1 className="text-3xl font-black tracking-tight">{board?.canteen_name || "Canteen Display Board"}</h1>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Select
            value={activeId}
            onChange={(e) => {
              announcedTokens.current.clear();
              setSelectedId(e.target.value);
            }}
            className="w-56 bg-slate-900 border-slate-700 text-white"
          >
            {canteens.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Button variant={voiceEnabled ? "primary" : "outline"} size="sm" onClick={() => setVoiceEnabled(!voiceEnabled)}>
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
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {(board?.now_preparing || []).map((t: any) => (
              <div key={t.token_code} className="rounded-2xl border border-slate-700 bg-slate-800 p-5 text-center">
                <div className="text-4xl font-black tracking-wider text-white">{t.token_code}</div>
                <div className="mt-1 text-xs font-semibold text-slate-400">{t.order_status}</div>
              </div>
            ))}
          </div>
        </div>

        {/* READY FOR PICKUP */}
        <div className="rounded-3xl border border-emerald-500/40 bg-emerald-950/30 p-6">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-2xl font-black tracking-wide text-emerald-400">READY FOR PICKUP</h2>
            <span className="rounded-full bg-emerald-500/20 px-3 py-1 text-sm font-bold text-emerald-300">
              {board?.ready_for_pickup?.length || 0}
            </span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {(board?.ready_for_pickup || []).map((t: any) => (
              <div
                key={t.token_code}
                className="flex items-center justify-between rounded-2xl border border-emerald-500/50 bg-emerald-900/50 px-6 py-5 shadow-lg"
              >
                <div className="text-5xl font-black tracking-wider text-white">{t.token_code}</div>
                <div className="text-right">
                  <div className="text-xs font-bold uppercase text-emerald-300">Collect at</div>
                  <div className="text-lg font-extrabold text-white">{t.counter_name}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {board?.recently_completed?.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900 px-5 py-3 flex flex-wrap items-center gap-3 text-sm">
          <span className="font-bold text-slate-400 uppercase text-xs">Recently Collected:</span>
          {board.recently_completed.map((t: any) => (
            <span key={t.token_code} className="rounded-lg bg-slate-800 px-2.5 py-1 font-mono font-bold text-slate-300">
              {t.token_code}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
