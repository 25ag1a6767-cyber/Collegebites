import React, { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Maximize2, Minimize2, Volume2, VolumeX } from "lucide-react";
import { api } from "../../api/client";
import { useRealtimeSync } from "../../hooks/useRealtimeSync";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, DigitalBoardResponse } from "../../types";
import { playOrderAlertChime } from "../../utils/notifications";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Select } from "../../components/ui/Primitives";
import { RealtimeStatusBadge } from "../../components/ui/RealtimeStatusBadge";

export const TokenBoardPage: React.FC = () => {
  const { canteenId: routeCanteenId } = useParams<{ canteenId?: string }>();
  const { selectedCanteenId } = useAppStore();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState(routeCanteenId || "");
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [latestReadyBanner, setLatestReadyBanner] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const announcedTokens = useRef<Set<string>>(new Set());
  const seededReadyRef = useRef(false);

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const activeScope = selectedId || routeCanteenId || selectedCanteenId || "all";

  const boardEndpoint = activeScope === "all" ? "/pickup/board" : `/pickup/board/${activeScope}`;
  const ssePath =
    activeScope === "all" ? "/realtime/board/stream" : `/realtime/board/stream?canteen_id=${activeScope}`;
  const wsPath = activeScope === "all" ? "/ws/board/all" : `/ws/board/${activeScope}`;

  const { status: syncStatus, lastSyncedAt } = useRealtimeSync<DigitalBoardResponse>({
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
    staleTime: 0,
    refetchInterval: 1000,
    refetchIntervalInBackground: true,
  });

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  useEffect(() => {
    seededReadyRef.current = false;
    announcedTokens.current.clear();
  }, [activeScope]);

  useEffect(() => {
    if (!board?.ready_for_pickup) return;
    if (!seededReadyRef.current) {
      for (const t of board.ready_for_pickup) {
        announcedTokens.current.add(`${t.order_id || t.token_code}:${t.token_code}`);
      }
      seededReadyRef.current = true;
      return;
    }

    for (const t of board.ready_for_pickup) {
      const announceKey = `${t.order_id || t.token_code}:${t.token_code}`;
      if (!announcedTokens.current.has(announceKey)) {
        announcedTokens.current.add(announceKey);
        setLatestReadyBanner(`NOW READY • Token ${t.token_code} at ${t.counter_name}`);
        if (voiceEnabled) {
          playOrderAlertChime(true);
          if ("speechSynthesis" in window) {
            const utter = new SpeechSynthesisUtterance(
              `Token ${t.token_code.split("").join(" ")} is ready for pickup at ${t.counter_name}`
            );
            window.speechSynthesis.speak(utter);
          }
        }
      }
    }
  }, [board, voiceEnabled]);

  useEffect(() => {
    if (!latestReadyBanner) return;
    const t = setTimeout(() => setLatestReadyBanner(null), 8000);
    return () => clearTimeout(t);
  }, [latestReadyBanner]);

  const toggleFullscreen = async () => {
    try {
      if (!document.fullscreenElement) {
        await (containerRef.current || document.documentElement).requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch {
      // fullscreen blocked by browser policy
    }
  };

  return (
    <div
      ref={containerRef}
      className="min-h-screen bg-slate-950 text-white p-4 md:p-6 flex flex-col gap-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div className="flex items-center gap-4">
          <Link to="/" className="rounded-xl bg-slate-800 p-2 text-slate-300 hover:text-white" title="Exit Display">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <BrandLogo size="md" variant="dark" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-widest text-[#fdedce]">
                COLLEGEBITES PICKUP DISPLAY
              </span>
              <RealtimeStatusBadge status={syncStatus} lastSyncedAt={lastSyncedAt} darkSurface />
              <span className="rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-0.5 text-[10px] font-bold text-emerald-300">
                Auto-refresh: 1s
              </span>
            </div>
            <h1 className="text-2xl md:text-4xl font-black tracking-tight">
              {board?.canteen_name || "All Campus Canteens"}
            </h1>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <Select
            value={activeScope}
            onChange={(e) => setSelectedId(e.target.value)}
            className="w-60 bg-slate-900 border-slate-700 text-white"
            aria-label="Select Pickup Display Canteen"
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
              if (next) {
                playOrderAlertChime();
                if ("speechSynthesis" in window) {
                  window.speechSynthesis.cancel();
                  window.speechSynthesis.speak(new SpeechSynthesisUtterance("Voice pickup announcements enabled"));
                }
              }
            }}
          >
            {voiceEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
            {voiceEnabled ? "Voice ON" : "Voice OFF"}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={toggleFullscreen}
            title="Toggle Fullscreen TV Mode"
          >
            {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            {isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
          </Button>
        </div>
      </div>

      {latestReadyBanner && (
        <div className="rounded-2xl border border-emerald-400 bg-emerald-600/90 px-6 py-3 text-center text-lg md:text-2xl font-black tracking-wide text-white shadow-lg animate-pulse">
          {latestReadyBanner}
        </div>
      )}

      {/* Strictly 3 Public Display Sections — Zero Customer PII or Payment Data */}
      <div className="grid flex-1 gap-5 lg:grid-cols-12">
        {/* 1. NOW PREPARING */}
        <section
          aria-label="Now Preparing Tokens"
          className="lg:col-span-4 rounded-3xl border border-amber-500/30 bg-slate-900/80 p-5 flex flex-col"
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xl md:text-2xl font-black tracking-wide text-amber-400">NOW PREPARING</h2>
            <span className="rounded-full bg-amber-500/20 px-3 py-1 text-sm font-bold text-amber-300">
              {board?.now_preparing?.length || 0}
            </span>
          </div>
          {!board?.now_preparing?.length ? (
            <div className="flex-1 flex items-center justify-center rounded-2xl border border-dashed border-slate-800 p-8 text-center text-sm text-slate-400">
              No tokens currently being prepared.
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-2 gap-3.5 content-start">
              {board.now_preparing.map((t) => (
                <div
                  key={t.order_id || t.token_code}
                  className="rounded-2xl border border-slate-700/80 bg-slate-800/90 p-4 text-center"
                >
                  <div className="text-4xl md:text-5xl font-black tracking-wider text-white font-mono">
                    {t.token_code}
                  </div>
                  <div className="mt-2 flex items-center justify-center gap-1.5">
                    <Badge tone={t.order_status === "PREPARING" ? "amber" : "slate"}>{t.order_status}</Badge>
                    {Boolean(t.delayed_minutes && t.delayed_minutes > 0) && (
                      <Badge tone="red">+{t.delayed_minutes}m</Badge>
                    )}
                  </div>
                  <div className="mt-1.5 text-xs font-semibold text-slate-400">{t.counter_name}</div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 2. READY FOR PICKUP */}
        <section
          aria-label="Ready for Pickup Tokens"
          className="lg:col-span-5 rounded-3xl border border-emerald-500/50 bg-emerald-950/35 p-5 flex flex-col"
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xl md:text-2xl font-black tracking-wide text-emerald-400">READY FOR PICKUP</h2>
            <span className="rounded-full bg-emerald-500/20 px-3 py-1 text-sm font-bold text-emerald-300">
              {board?.ready_for_pickup?.length || 0}
            </span>
          </div>
          {!board?.ready_for_pickup?.length ? (
            <div className="flex-1 flex items-center justify-center rounded-2xl border border-dashed border-emerald-800/60 p-8 text-center text-sm text-emerald-200/70">
              No tokens waiting at pickup counters right now.
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2 content-start">
              {board.ready_for_pickup.map((t) => (
                <div
                  key={t.order_id || t.token_code}
                  className="flex items-center justify-between gap-3 rounded-2xl border border-emerald-400/60 bg-emerald-900/60 px-6 py-5 shadow-lg"
                >
                  <div className="text-5xl md:text-6xl font-black tracking-wider text-white font-mono">
                    {t.token_code}
                  </div>
                  <div className="text-right">
                    <div className="text-xs font-bold uppercase tracking-wider text-emerald-300">Collect at</div>
                    <div className="text-lg md:text-xl font-extrabold text-white">{t.counter_name}</div>
                    {activeScope === "all" && t.canteen_name && (
                      <div className="text-xs text-emerald-200/80">{t.canteen_name}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 3. RECENTLY COMPLETED */}
        <section
          aria-label="Recently Completed Tokens"
          className="lg:col-span-3 rounded-3xl border border-slate-800 bg-slate-900/60 p-5 flex flex-col"
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xl md:text-2xl font-black tracking-wide text-slate-300">RECENTLY COMPLETED</h2>
            <span className="rounded-full bg-slate-800 px-3 py-1 text-sm font-bold text-slate-300">
              {board?.recently_completed?.length || 0}
            </span>
          </div>
          {!board?.recently_completed?.length ? (
            <div className="flex-1 flex items-center justify-center rounded-2xl border border-dashed border-slate-800 p-8 text-center text-sm text-slate-500">
              Completed tokens will appear here after collection.
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 content-start">
              {board.recently_completed.map((t) => (
                <div
                  key={t.order_id || t.token_code}
                  className="rounded-xl border border-slate-800 bg-slate-800/60 p-3 text-center"
                >
                  <div className="text-2xl md:text-3xl font-black font-mono text-slate-200">{t.token_code}</div>
                  <div className="text-[11px] text-slate-400 mt-0.5 truncate">{t.counter_name}</div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};
