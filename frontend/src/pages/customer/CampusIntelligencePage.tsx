import React, { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Armchair,
  CheckCircle2,
  Clock,
  Mic,
  MicOff,
  RefreshCw,
  Send,
  ShoppingBag,
  Sparkles,
  UtensilsCrossed,
  Volume2,
} from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../components/ui/Primitives";
import { BrandLoadingState } from "../../components/branding/BrandLogo";

export const CampusIntelligencePage: React.FC = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { selectedCanteenId, setSelectedCanteen } = useAppStore();

  const [voiceLang, setVoiceLang] = useState<"en" | "te">("en");
  const [transcript, setTranscript] = useState("");
  const [listening, setListening] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceHistory, setVoiceHistory] = useState<any[]>([]);
  const [draftConfirm, setDraftConfirm] = useState<any | null>(null);
  const [addingDraft, setAddingDraft] = useState(false);
  const recognitionRef = useRef<any>(null);

  const speechApiSupported =
    typeof window !== "undefined" && Boolean((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);

  const { data: crowd, isLoading: crowdLoading, refetch: refetchCrowd } = useQuery<any>({
    queryKey: ["campus-crowd-live"],
    staleTime: 15_000,
    refetchInterval: 45_000,
    refetchIntervalInBackground: false,
    queryFn: async () => (await api.get("/campus-intelligence/crowd/live?days=7")).data,
  });

  const activeCanteenId = useMemo(() => {
    if (selectedCanteenId) return selectedCanteenId;
    return crowd?.counters?.[0]?.canteen_id || null;
  }, [selectedCanteenId, crowd]);

  const { data: pickupPred } = useQuery<any>({
    queryKey: ["campus-pickup-pred", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    staleTime: 15_000,
    refetchInterval: 45_000,
    refetchIntervalInBackground: false,
    queryFn: async () => (await api.get(`/campus-intelligence/pickup-predictions/${activeCanteenId}`)).data,
  });

  const { data: seating } = useQuery<any>({
    queryKey: ["campus-seating"],
    staleTime: 20_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    queryFn: async () => (await api.get("/campus-intelligence/seating")).data,
  });

  const { data: menuAvail } = useQuery<any>({
    queryKey: ["campus-menu-avail", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    staleTime: 20_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    queryFn: async () => (await api.get(`/campus-intelligence/menu-availability/${activeCanteenId}?include_history=false`)).data,
  });

  const speakResponse = (text: string, speechLang: string) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    try {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = speechLang;
      window.speechSynthesis.speak(utter);
    } catch {
      // Graceful fallback when TTS voice is unavailable
    }
  };

  const sendVoiceQuery = async (textOverride?: string) => {
    const q = (textOverride ?? transcript).trim();
    setVoiceBusy(true);
    try {
      const res = await api.post("/campus-intelligence/voice-assistant/query", {
        transcript: q,
        language: voiceLang,
        canteen_id: activeCanteenId || null,
      });
      setVoiceHistory((prev) => [{ q: q || "(empty)", ...res.data }, ...prev].slice(0, 8));
      setTranscript("");
      speakResponse(res.data.response_text, res.data.speech_lang || (voiceLang === "te" ? "te-IN" : "en-IN"));
      if (res.data.draft_order) {
        setDraftConfirm(res.data.draft_order);
      }
    } catch (err) {
      pushToast(getApiError(err, "Voice assistant query failed"), "error");
    } finally {
      setVoiceBusy(false);
    }
  };

  const toggleMic = () => {
    if (!speechApiSupported) {
      pushToast("Browser microphone speech recognition is unavailable on this device. Please use the text input below.", "info");
      return;
    }
    if (listening && recognitionRef.current) {
      recognitionRef.current.stop();
      setListening(false);
      return;
    }
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const rec = new SR();
    rec.lang = voiceLang === "te" ? "te-IN" : "en-IN";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onstart = () => setListening(true);
    rec.onerror = () => {
      setListening(false);
      pushToast("Microphone could not capture speech cleanly. Try again or type your query.", "info");
    };
    rec.onend = () => setListening(false);
    rec.onresult = (evt: any) => {
      const spoken = evt.results?.[0]?.[0]?.transcript || "";
      setTranscript(spoken);
      if (spoken.trim()) {
        void sendVoiceQuery(spoken);
      }
    };
    recognitionRef.current = rec;
    rec.start();
  };

  const confirmDraftToCart = async () => {
    if (!draftConfirm) return;
    setAddingDraft(true);
    try {
      setSelectedCanteen(draftConfirm.canteen_id);
      for (const it of draftConfirm.items || []) {
        await api.post("/carts/items", {
          canteen_id: draftConfirm.canteen_id,
          food_item_id: it.food_item_id,
          quantity: it.quantity,
        });
      }
      qc.invalidateQueries({ queryKey: ["cart", draftConfirm.canteen_id] });
      pushToast("Items added to cart. Complete checkout securely via Razorpay.", "success");
      setDraftConfirm(null);
      navigate("/checkout");
    } catch (err) {
      pushToast(getApiError(err, "Could not add drafted items to cart"), "error");
    } finally {
      setAddingDraft(false);
    }
  };

  const quickPrompts =
    voiceLang === "te"
      ? ["ఈరోజు మెనూ ఏంటి?", "ఏ ఐటమ్స్ అందుబాటులో లేవు?", "తక్కువ రద్దీ ఉన్న కౌంటర్ ఏది?", "నా ఆర్డర్ స్థితి ఏంటి?"]
      : ["What food items are available?", "Which items are unavailable?", "Which counter has a lower workload?", "What is my order status?"];

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-[#76010d]" />
            <h1 className="text-2xl font-extrabold text-slate-900">Smart Campus Intelligence Hub</h1>
          </div>
          <p className="text-xs text-slate-600 mt-0.5">
            Live Counter 1 &amp; Counter 2 order-based activity estimates, AI pickup time estimates, seating status &amp; English/Telugu Voice Assistant.
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => refetchCrowd()}>
          <RefreshCw className="h-3.5 w-3.5" /> Refresh Live Data
        </Button>
      </div>

      {/* Feature 1: Live Cafeteria Crowd Intelligence */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-extrabold uppercase tracking-wide text-slate-700 flex items-center gap-1.5">
            <Activity className="h-4 w-4 text-[#76010d]" /> Live Counter Activity (Order-Based Activity Estimate)
          </h2>
          {crowd?.last_updated_at && (
            <span className="text-[11px] text-slate-500">
              Updated: {new Date(crowd.last_updated_at).toLocaleTimeString()}
            </span>
          )}
        </div>

        {crowdLoading ? (
          <BrandLoadingState message="Loading live Counter 1 & Counter 2 activity..." />
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {(crowd?.counters || []).map((c: any) => (
              <Card
                key={c.canteen_id}
                className={`p-5 space-y-3 cursor-pointer transition ${
                  activeCanteenId === c.canteen_id ? "ring-2 ring-[#76010d]" : ""
                }`}
                onClick={() => setSelectedCanteen(c.canteen_id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-[11px] font-bold uppercase text-[#76010d]">{c.counter_slot}</div>
                    <h3 className="text-lg font-extrabold text-slate-900">{c.canteen_name}</h3>
                    <div className="text-xs text-slate-500">{c.location}</div>
                  </div>
                  <Badge tone={c.activity_level === "busy" ? "red" : c.activity_level === "moderate" ? "amber" : "green"}>
                    {c.ordering_paused ? "PAUSED" : !c.is_open_now ? "CLOSED" : c.activity_level.toUpperCase()}
                  </Badge>
                </div>

                <div className="grid grid-cols-4 gap-2 text-center">
                  <div className="rounded-xl bg-slate-50 p-2">
                    <div className="text-base font-extrabold text-slate-900">{c.active_orders}</div>
                    <div className="text-[10px] text-slate-500">Active</div>
                  </div>
                  <div className="rounded-xl bg-amber-50 p-2">
                    <div className="text-base font-extrabold text-amber-800">{c.waiting_orders}</div>
                    <div className="text-[10px] text-amber-700">Waiting</div>
                  </div>
                  <div className="rounded-xl bg-sky-50 p-2">
                    <div className="text-base font-extrabold text-sky-800">{c.preparing_orders}</div>
                    <div className="text-[10px] text-sky-700">Preparing</div>
                  </div>
                  <div className="rounded-xl bg-emerald-50 p-2">
                    <div className="text-base font-extrabold text-emerald-800">{c.ready_orders}</div>
                    <div className="text-[10px] text-emerald-700">Ready</div>
                  </div>
                </div>

                <div className="space-y-1">
                  <div className="flex justify-between text-xs font-semibold text-slate-600">
                    <span>Counter Workload (Order-Based Estimate)</span>
                    <span>{c.workload_percent}%</span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        c.workload_percent >= 70 ? "bg-rose-600" : c.workload_percent >= 35 ? "bg-amber-500" : "bg-emerald-500"
                      }`}
                      style={{ width: `${Math.min(100, c.workload_percent)}%` }}
                    />
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500 pt-1">
                  <span>
                    Peak hours:{" "}
                    {c.peak_periods?.length > 0
                      ? c.peak_periods.map((p: any) => p.label).join(", ")
                      : "Insufficient history"}
                  </span>
                  <span>
                    Est. wait: {c.estimated_wait_minutes != null ? `~${c.estimated_wait_minutes} min` : "Unavailable"}
                  </span>
                </div>
              </Card>
            ))}
          </div>
        )}
        {crowd?.disclaimer && (
          <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-[11px] text-slate-600">
            {crowd.disclaimer}
          </div>
        )}
      </section>

      {/* Feature 2 (AI Pickup Prediction) + Feature 8 (Smart Seating) */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
              <Clock className="h-4 w-4 text-[#76010d]" /> AI Smart Pickup Time Prediction
            </h2>
            {pickupPred && (
              <Badge tone={pickupPred.confidence_label === "high" ? "green" : pickupPred.confidence_label === "medium" ? "amber" : "slate"}>
                {pickupPred.confidence_label?.toUpperCase()} CONFIDENCE
              </Badge>
            )}
          </div>
          {pickupPred ? (
            <>
              <div className="rounded-2xl bg-[#fdf8f0] border border-[#76010d]/15 p-4 flex items-center justify-between">
                <div>
                  <div className="text-xs font-bold text-[#76010d]">{pickupPred.canteen_name}</div>
                  <div className="text-2xl font-extrabold text-slate-900">
                    {pickupPred.prediction_available && pickupPred.predicted_wait_minutes != null
                      ? `~${pickupPred.predicted_wait_minutes} mins`
                      : "Unavailable"}
                  </div>
                  {pickupPred.predicted_pickup_at && (
                    <div className="text-xs text-slate-600">
                      Est. pickup: {new Date(pickupPred.predicted_pickup_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </div>
                  )}
                </div>
                <div className="text-right text-[11px] text-slate-600 space-y-0.5">
                  <div>Model: <strong>{pickupPred.model_version}</strong></div>
                  <div>History: <strong>{pickupPred.historical_sample_count}</strong> orders</div>
                  <div>Staff on duty: <strong>{pickupPred.factors?.staff_on_duty}</strong></div>
                </div>
              </div>
              <p className="text-[11px] text-slate-500">{pickupPred.disclaimer}</p>
            </>
          ) : (
            <div className="text-xs text-slate-500">Select a counter above to view live pickup prediction.</div>
          )}
        </Card>

        <Card className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
              <Armchair className="h-4 w-4 text-[#76010d]" /> Smart Seating Availability
            </h2>
            <Badge tone="slate">No Facial Recognition</Badge>
          </div>
          {seating?.configured ? (
            <div className="space-y-2">
              {(seating.zones || []).map((z: any) => (
                <div key={z.id} className="rounded-xl border border-slate-200 p-3 flex items-center justify-between text-xs">
                  <div>
                    <div className="font-bold text-slate-900">{z.zone_name} ({z.zone_code})</div>
                    <div className="text-[11px] text-slate-500">
                      Source: {z.data_source} • Sensors: {z.sensor_status}
                    </div>
                  </div>
                  <div className="text-right">
                    {z.available_seats != null ? (
                      <>
                        <div className="font-extrabold text-emerald-700">{z.available_seats} / {z.total_seats} free</div>
                        <div className="text-[11px] text-slate-500">{z.occupancy_percent}% occupied</div>
                      </>
                    ) : (
                      <Badge tone="slate">{z.total_seats} seats • Unmeasured</Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-xs text-slate-600 space-y-1">
              <div className="font-bold text-slate-800">Live seating zones not yet configured</div>
              <div>
                Registered dining table seats: <strong>{seating?.registered_dining_table_seats ?? 0}</strong>. Occupied seat counts are never fabricated without manual updates or sensors.
              </div>
            </div>
          )}
          {seating?.privacy_notice && <p className="text-[11px] text-slate-500">{seating.privacy_notice}</p>}
        </Card>
      </div>

      {/* Feature 9: Voice-Based Campus Food Assistant (English & Telugu) */}
      <Card className="p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
              <Mic className="h-4 w-4 text-[#76010d]" /> Voice-Based Campus Food Assistant (English &amp; తెలుగు)
            </h2>
            <p className="text-xs text-slate-500">
              Ask about available items, ingredients, counter workload, your order status, or say &ldquo;Order 2 Idli&rdquo; (explicit confirmation &amp; Razorpay checkout always required).
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Select
              aria-label="Voice assistant language"
              value={voiceLang}
              onChange={(e) => setVoiceLang(e.target.value as "en" | "te")}
              className="w-36"
            >
              <option value="en">English (en-IN)</option>
              <option value="te">తెలుగు / Telugu</option>
            </Select>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {quickPrompts.map((qp) => (
            <button
              key={qp}
              type="button"
              onClick={() => void sendVoiceQuery(qp)}
              className="rounded-full border border-[#76010d]/25 bg-[#fdf8f0] px-3 py-1 text-xs font-semibold text-[#76010d] hover:bg-[#fdedce]"
            >
              {qp}
            </button>
          ))}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void sendVoiceQuery();
          }}
          className="flex gap-2"
        >
          <Button
            type="button"
            variant={listening ? "primary" : "outline"}
            onClick={toggleMic}
            aria-label={listening ? "Stop voice listening" : "Start voice listening"}
          >
            {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            {listening ? "Listening..." : "Speak"}
          </Button>
          <Input
            aria-label="Ask the voice campus food assistant"
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            placeholder={
              voiceLang === "te"
                ? "ఉదా: ఈరోజు మెనూ ఏంటి? లేదా 2 ఇడ్లీ ఆర్డర్ చేయి..."
                : "e.g., What food items are available? Or: Order 2 Masala Dosa"
            }
          />
          <Button type="submit" variant="primary" disabled={voiceBusy || !transcript.trim()}>
            <Send className="h-4 w-4" /> Ask
          </Button>
        </form>

        {!speechApiSupported && (
          <div className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2">
            Browser microphone STT is unavailable here; full text fallback is active for English and Telugu queries.
          </div>
        )}

        {voiceHistory.length > 0 && (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {voiceHistory.map((item, idx) => (
              <div key={item.session_id || idx} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-slate-800">You: {item.q}</span>
                  <div className="flex items-center gap-1.5">
                    <Badge tone="slate">{item.language?.toUpperCase()}</Badge>
                    <Badge tone="blue">{item.detected_intent}</Badge>
                    <button
                      type="button"
                      aria-label="Read response aloud"
                      onClick={() => speakResponse(item.response_text, item.speech_lang)}
                      className="text-slate-500 hover:text-[#76010d]"
                    >
                      <Volume2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <div className="text-slate-700">{item.response_text}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Feature 6: Intelligent Menu Availability Snapshot */}
      {menuAvail && (
        <Card className="p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
              <UtensilsCrossed className="h-4 w-4 text-[#76010d]" /> Live Menu Availability — {menuAvail.canteen_name}
            </h2>
            <div className="flex flex-wrap gap-1.5 text-xs">
              <Badge tone="green">{menuAvail.summary?.available_now} Available</Badge>
              <Badge tone="red">{menuAvail.summary?.stock_blocked} Stock-Blocked</Badge>
              <Badge tone="amber">{menuAvail.summary?.manually_paused} Paused</Badge>
            </div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {(menuAvail.items || []).slice(0, 12).map((it: any) => (
              <div key={it.food_item_id} className="rounded-xl border border-slate-200 px-3 py-2 flex items-center justify-between text-xs">
                <div>
                  <div className="font-bold text-slate-900">{it.name}</div>
                  <div className="text-[11px] text-slate-500">
                    ₹{it.base_price} • ~{it.prep_time_minutes}m
                    {it.unavailable_reason ? ` • ${it.unavailable_reason}` : ""}
                  </div>
                </div>
                <Badge tone={it.effective_available ? "green" : "red"}>
                  {it.effective_available ? "Live" : "Unavailable"}
                </Badge>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Voice Order Explicit Confirmation Modal */}
      <Modal open={Boolean(draftConfirm)} onClose={() => setDraftConfirm(null)} title="Confirm Voice-Drafted Order">
        {draftConfirm && (
          <div className="space-y-4 text-xs">
            <div className="rounded-xl bg-amber-50 border border-amber-200 p-3 text-amber-900">
              <strong>Explicit Confirmation Required:</strong> Voice assistant never submits orders or payments automatically. Review the exact listed price below and proceed to Razorpay Checkout.
            </div>
            <div className="space-y-1.5">
              <div className="font-bold text-slate-800">Counter: {draftConfirm.canteen_name}</div>
              {(draftConfirm.items || []).map((it: any) => (
                <div key={it.food_item_id} className="flex justify-between border-b border-slate-100 py-1.5">
                  <span>{it.quantity} × {it.item_name}</span>
                  <span className="font-bold">₹{it.line_total}</span>
                </div>
              ))}
              <div className="flex justify-between pt-2 text-sm font-extrabold text-slate-900">
                <span>Exact Total (Zero Tax / Zero Discounts)</span>
                <span>₹{draftConfirm.exact_total_amount}</span>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setDraftConfirm(null)}>Cancel</Button>
              <Button variant="primary" size="sm" disabled={addingDraft} onClick={() => void confirmDraftToCart()}>
                <ShoppingBag className="h-3.5 w-3.5" /> {addingDraft ? "Adding..." : "Confirm & Proceed to Razorpay"}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

