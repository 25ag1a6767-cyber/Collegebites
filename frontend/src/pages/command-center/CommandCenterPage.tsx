import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Bot,
  Calendar,
  CheckCircle2,
  ClipboardCheck,
  Download,
  FileSpreadsheet,
  FlaskConical,
  MapPin,
  Play,
  Power,
  RefreshCw,
  Search,
  ShieldAlert,
  Sliders,
  Users,
  Workflow,
} from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";
import { BrandLoadingState } from "../../components/branding/BrandLogo";

type TabId = "overview" | "campus_ops" | "ai_rca" | "map_sim" | "reports_gov";

export const CommandCenterPage: React.FC = () => {
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { user } = useAppStore();
  const isAdmin = Boolean(user?.roles?.some((r) => ["super_admin", "college_admin"].includes(r)));
  const isManager = Boolean(user?.roles?.some((r) => ["super_admin", "college_admin", "canteen_manager"].includes(r)));

  const [tab, setTab] = useState<TabId>("overview");
  const [selectedCanteenId, setSelectedCanteenId] = useState<string>("");
  const [busy, setBusy] = useState(false);

  // Incident form
  const [incCategory, setIncCategory] = useState("order_delay");
  const [incSeverity, setIncSeverity] = useState("medium");
  const [incTitle, setIncTitle] = useState("");
  const [incDesc, setIncDesc] = useState("");

  // NL Command Center
  const [nlQuestion, setNlQuestion] = useState("");
  const [nlResponses, setNlResponses] = useState<any[]>([]);

  // RCA
  const [rcaDomain, setRcaDomain] = useState("order_delays");
  const [rcaHours, setRcaHours] = useState("24");

  // Tray verification
  const [trayOrderRef, setTrayOrderRef] = useState("");
  const [trayContext, setTrayContext] = useState<any | null>(null);
  const [trayChecked, setTrayChecked] = useState<Record<string, number>>({});

  // Timetable upload
  const [ttFile, setTtFile] = useState<File | null>(null);

  // Seating form
  const [zoneCode, setZoneCode] = useState("HALL-A");
  const [zoneName, setZoneName] = useState("Main Dining Hall");
  const [zoneSeats, setZoneSeats] = useState("60");
  const [occUpdateMap, setOccUpdateMap] = useState<Record<string, string>>({});

  // Map historical hours
  const [mapHours, setMapHours] = useState("24");
  const [selectedMapZone, setSelectedMapZone] = useState<any | null>(null);

  // Simulation parameters
  const [simName, setSimName] = useState("Lunch Rush +40% Demand");
  const [simStaffDelta, setSimStaffDelta] = useState("0");
  const [simDemandMult, setSimDemandMult] = useState("1.4");
  const [simPrepMult, setSimPrepMult] = useState("1.0");
  const [simCounterShift, setSimCounterShift] = useState("0");
  const [simResult, setSimResult] = useState<any | null>(null);

  // Reports
  const [repPeriod, setRepPeriod] = useState<"daily" | "weekly" | "monthly">("daily");

  // Governance override
  const [govReason, setGovReason] = useState("");

  const qCanteen = selectedCanteenId ? `?canteen_id=${selectedCanteenId}` : "";

  const { data: unified, isLoading: uniLoading, refetch: refetchUnified } = useQuery<any>({
    queryKey: ["cc-unified", selectedCanteenId],
    staleTime: 15_000,
    refetchInterval: tab === "overview" ? 30_000 : false,
    refetchIntervalInBackground: false,
    queryFn: async () => (await api.get(`/command-center/unified-status${qCanteen}`)).data,
  });

  const { data: incidents = [], refetch: refetchIncidents } = useQuery<any[]>({
    queryKey: ["cc-incidents", selectedCanteenId],
    enabled: tab === "overview" || tab === "ai_rca",
    staleTime: 15_000,
    queryFn: async () => (await api.get(`/command-center/incidents${qCanteen}`)).data,
  });

  const { data: queueOverview, refetch: refetchQueue } = useQuery<any>({
    queryKey: ["cc-queue", selectedCanteenId],
    enabled: tab === "campus_ops",
    queryFn: async () => (await api.get(`/campus-intelligence/queue/overview${qCanteen}`)).data,
  });

  const { data: timetablePred, refetch: refetchTimetable } = useQuery<any>({
    queryKey: ["cc-timetable-pred", selectedCanteenId],
    enabled: tab === "campus_ops",
    queryFn: async () => (await api.get(`/campus-intelligence/timetables/demand-prediction${qCanteen}`)).data,
  });

  const { data: seatingData, refetch: refetchSeating } = useQuery<any>({
    queryKey: ["cc-seating", selectedCanteenId],
    enabled: tab === "campus_ops" || tab === "map_sim",
    queryFn: async () => (await api.get(`/campus-intelligence/seating${qCanteen}`)).data,
  });

  const { data: voiceAnalytics } = useQuery<any>({
    queryKey: ["cc-voice-analytics"],
    enabled: tab === "campus_ops" && isManager,
    queryFn: async () => (await api.get("/campus-intelligence/voice-assistant/analytics?days=14")).data,
  });

  const { data: trayHistory = [], refetch: refetchTrayHist } = useQuery<any[]>({
    queryKey: ["cc-tray-history", selectedCanteenId],
    enabled: tab === "campus_ops",
    queryFn: async () => (await api.get(`/campus-intelligence/tray-verification/history${qCanteen}`)).data,
  });

  const { data: investigations = [], refetch: refetchRca } = useQuery<any[]>({
    queryKey: ["cc-rca", selectedCanteenId],
    enabled: tab === "ai_rca" && isManager,
    queryFn: async () => (await api.get(`/command-center/investigations${qCanteen}`)).data,
  });

  const { data: prevention } = useQuery<any>({
    queryKey: ["cc-prevention", selectedCanteenId],
    enabled: tab === "ai_rca" && isManager,
    queryFn: async () => (await api.get(`/command-center/incident-prevention${qCanteen}`)).data,
  });

  const { data: resources } = useQuery<any>({
    queryKey: ["cc-resources", selectedCanteenId],
    enabled: tab === "ai_rca" && isManager,
    queryFn: async () => (await api.get(`/command-center/resource-allocation${qCanteen}`)).data,
  });

  const { data: mapData, refetch: refetchMap } = useQuery<any>({
    queryKey: ["cc-map", mapHours],
    enabled: tab === "map_sim",
    staleTime: 15_000,
    refetchInterval: tab === "map_sim" ? 30_000 : false,
    refetchIntervalInBackground: false,
    queryFn: async () => (await api.get(`/command-center/cafeteria-map?hours=${mapHours}`)).data,
  });

  const { data: simulations = [], refetch: refetchSims } = useQuery<any[]>({
    queryKey: ["cc-sims"],
    enabled: tab === "map_sim" && isManager,
    queryFn: async () => (await api.get("/command-center/simulations")).data,
  });

  const { data: reports = [], refetch: refetchReports } = useQuery<any[]>({
    queryKey: ["cc-reports"],
    enabled: tab === "reports_gov" && isManager,
    queryFn: async () => (await api.get("/command-center/reports")).data,
  });

  const { data: governance, refetch: refetchGov } = useQuery<any>({
    queryKey: ["cc-gov"],
    enabled: tab === "reports_gov" && isManager,
    queryFn: async () => (await api.get("/command-center/governance")).data,
  });

  const { data: workflows = [], refetch: refetchWorkflows } = useQuery<any[]>({
    queryKey: ["cc-workflows"],
    enabled: tab === "reports_gov" && isManager,
    queryFn: async () => (await api.get("/command-center/workflows")).data,
  });

  const { data: executions = [], refetch: refetchExecs } = useQuery<any[]>({
    queryKey: ["cc-executions"],
    enabled: tab === "reports_gov" && isManager,
    queryFn: async () => (await api.get("/command-center/executions")).data,
  });

  const downloadBlob = async (url: string, fallbackName: string) => {
    try {
      const res = await api.get(url, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = fallbackName;
      a.click();
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      pushToast(getApiError(err, "Export failed"), "error");
    }
  };

  const counters = unified?.counters || [];

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-6 w-6 text-[#76010d]" />
            <h1 className="text-2xl font-extrabold text-slate-900">CollegeBites AI Command Center</h1>
            {unified && (
              <Badge tone={unified.operational_health === "healthy" ? "green" : unified.operational_health === "degraded" ? "amber" : "red"}>
                {unified.operational_health?.replace("_", " ").toUpperCase()}
              </Badge>
            )}
          </div>
          <p className="text-xs text-slate-600 mt-0.5">
            Unified Smart Campus Intelligence &amp; Autonomous Operations Governance across Counter 1 &amp; Counter 2 (Human-Controlled • Verified DB Records Only).
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            aria-label="Filter Command Center by counter"
            value={selectedCanteenId}
            onChange={(e) => setSelectedCanteenId(e.target.value)}
            className="w-52"
          >
            <option value="">Both Cafeteria Counters</option>
            {counters.map((c: any) => (
              <option key={c.canteen_id} value={c.canteen_id}>
                {c.counter_slot}: {c.canteen_name}
              </option>
            ))}
          </Select>
          <Button size="sm" variant="outline" onClick={() => { refetchUnified(); refetchIncidents(); }}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </Button>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex flex-wrap gap-2 border-b border-slate-200 pb-3">
        {[
          { id: "overview", label: "Live Overview & Health", icon: Activity },
          { id: "campus_ops", label: "Queue, Tray, Timetables & Seating", icon: ClipboardCheck },
          { id: "ai_rca", label: "NL Command, RCA, Prevention & Staff", icon: Bot },
          { id: "map_sim", label: "Cafeteria Map & What-If Simulation", icon: MapPin },
          { id: "reports_gov", label: "Reports, Automation & Governance", icon: Workflow },
        ].map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id as TabId)}
              className={`inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-bold transition ${
                tab === t.id ? "bg-[#76010d] text-white shadow-sm" : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
              }`}
            >
              <Icon className="h-3.5 w-3.5" /> {t.label}
            </button>
          );
        })}
      </div>

      {/* TAB 1: UNIFIED OPERATIONAL INTELLIGENCE */}
      {tab === "overview" && (
        <div className="space-y-5">
          {uniLoading || !unified ? (
            <BrandLoadingState message="Loading unified cafeteria operations..." />
          ) : (
            <>
              {/* KPI Strip */}
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <Card className="p-4">
                  <div className="text-[11px] font-bold uppercase text-slate-500">Orders (24h)</div>
                  <div className="text-2xl font-extrabold text-slate-900 mt-1">{unified.orders_24h.total}</div>
                  <div className="text-[11px] text-slate-500">{unified.orders_24h.completed} completed • {unified.orders_24h.delayed_active} delayed</div>
                </Card>
                <Card className="p-4">
                  <div className="text-[11px] font-bold uppercase text-slate-500">Razorpay (24h)</div>
                  <div className="text-2xl font-extrabold text-emerald-700 mt-1">{unified.payments_razorpay_24h.confirmed}</div>
                  <div className="text-[11px] text-slate-500">{unified.payments_razorpay_24h.failed} failed • {unified.payments_razorpay_24h.open_reconciliation_discrepancies} discrepancies</div>
                </Card>
                <Card className="p-4">
                  <div className="text-[11px] font-bold uppercase text-slate-500">Menu &amp; Stock</div>
                  <div className="text-2xl font-extrabold text-slate-900 mt-1">{unified.menu_availability.available_now}/{unified.menu_availability.total_active}</div>
                  <div className="text-[11px] text-rose-600">{unified.inventory.low_stock_count} low stock • {unified.inventory.out_of_stock_count} out</div>
                </Card>
                <Card className="p-4">
                  <div className="text-[11px] font-bold uppercase text-slate-500">Open Incidents</div>
                  <div className="text-2xl font-extrabold text-amber-700 mt-1">
                    {unified.incidents_summary.open_operational_incidents + unified.incidents_summary.open_food_safety_incidents + unified.incidents_summary.open_security_alerts}
                  </div>
                  <div className="text-[11px] text-slate-500">
                    Ops {unified.incidents_summary.open_operational_incidents} • FS {unified.incidents_summary.open_food_safety_incidents} • Sec {unified.incidents_summary.open_security_alerts}
                  </div>
                </Card>
                <Card className="p-4">
                  <div className="text-[11px] font-bold uppercase text-slate-500">Seating / Refunds</div>
                  <div className="text-lg font-extrabold text-slate-900 mt-1">
                    {unified.seating.available_seats != null ? `${unified.seating.available_seats} free` : "Unmeasured"}
                  </div>
                  <div className="text-[11px] text-slate-500">App refunds: 0 (No-refund policy)</div>
                </Card>
              </div>

              {/* Counter 1 & Counter 2 */}
              <div className="grid gap-4 md:grid-cols-2">
                {counters.map((c: any) => (
                  <Card key={c.canteen_id} className="p-5 space-y-2">
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="text-[11px] font-bold uppercase text-[#76010d]">{c.counter_slot}</span>
                        <h3 className="text-base font-extrabold text-slate-900">{c.canteen_name}</h3>
                      </div>
                      <Badge tone={c.activity_level === "busy" ? "red" : c.activity_level === "moderate" ? "amber" : "green"}>
                        {c.workload_percent}% ({c.activity_level})
                      </Badge>
                    </div>
                    <div className="grid grid-cols-4 gap-2 text-center text-xs">
                      <div className="rounded-lg bg-slate-50 p-2"><strong>{c.active_orders}</strong><div className="text-[10px] text-slate-500">Active</div></div>
                      <div className="rounded-lg bg-amber-50 p-2"><strong>{c.waiting_orders}</strong><div className="text-[10px] text-amber-700">Waiting</div></div>
                      <div className="rounded-lg bg-sky-50 p-2"><strong>{c.preparing_orders}</strong><div className="text-[10px] text-sky-700">Prep</div></div>
                      <div className="rounded-lg bg-emerald-50 p-2"><strong>{c.ready_orders}</strong><div className="text-[10px] text-emerald-700">Ready</div></div>
                    </div>
                  </Card>
                ))}
              </div>

              {/* Critical Alerts + Incident Logging */}
              <div className="grid gap-5 lg:grid-cols-2">
                <Card className="p-5 space-y-3">
                  <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
                    <AlertTriangle className="h-4 w-4 text-amber-600" /> Correlated Operational Alerts
                  </h2>
                  {(unified.critical_alerts || []).length === 0 ? (
                    <div className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-xl p-3 flex items-center gap-2">
                      <CheckCircle2 className="h-4 w-4" /> All monitored modules operating normally.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {unified.critical_alerts.map((a: any, i: number) => (
                        <div key={i} className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs space-y-1">
                          <div className="flex items-center justify-between font-bold text-slate-900">
                            <span>{a.title}</span>
                            <Badge tone={a.severity === "high" ? "red" : "amber"}>{a.module}</Badge>
                          </div>
                          <div className="text-slate-600">{a.recommended_action}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>

                <Card className="p-5 space-y-3">
                  <h2 className="font-extrabold text-slate-900">Operational Incidents ({incidents.length})</h2>
                  <form
                    onSubmit={async (e) => {
                      e.preventDefault();
                      setBusy(true);
                      try {
                        await api.post("/command-center/incidents", {
                          canteen_id: selectedCanteenId || null,
                          category: incCategory,
                          severity: incSeverity,
                          title: incTitle,
                          description: incDesc,
                        });
                        setIncTitle("");
                        setIncDesc("");
                        refetchIncidents();
                        refetchUnified();
                        pushToast("Operational incident recorded", "success");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      } finally {
                        setBusy(false);
                      }
                    }}
                    className="space-y-2 text-xs"
                  >
                    <div className="grid grid-cols-2 gap-2">
                      <Select value={incCategory} onChange={(e) => setIncCategory(e.target.value)}>
                        <option value="order_delay">Order Delay</option>
                        <option value="stock_shortage">Stock Shortage</option>
                        <option value="payment_failure">Payment Failure</option>
                        <option value="printer_failure">Printer Failure</option>
                        <option value="qr_failure">QR Failure</option>
                        <option value="kitchen_bottleneck">Kitchen Bottleneck</option>
                      </Select>
                      <Select value={incSeverity} onChange={(e) => setIncSeverity(e.target.value)}>
                        <option value="low">Low</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                        <option value="critical">Critical</option>
                      </Select>
                    </div>
                    <Input required value={incTitle} onChange={(e) => setIncTitle(e.target.value)} placeholder="Incident title..." />
                    <Input required value={incDesc} onChange={(e) => setIncDesc(e.target.value)} placeholder="Observed operational details..." />
                    <Button type="submit" size="sm" variant="primary" disabled={busy}>Log Incident</Button>
                  </form>
                  <div className="space-y-1.5 max-h-44 overflow-y-auto pt-2 border-t border-slate-100">
                    {incidents.slice(0, 8).map((inc: any) => (
                      <div key={inc.id} className="rounded-lg border border-slate-200 p-2 text-xs flex items-center justify-between gap-2">
                        <div>
                          <div className="font-bold text-slate-900">{inc.incident_code} • {inc.title}</div>
                          <div className="text-[11px] text-slate-500">{inc.category} • {inc.severity}</div>
                        </div>
                        <Badge tone={inc.status === "resolved" || inc.status === "closed" ? "green" : "amber"}>{inc.status}</Badge>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            </>
          )}
        </div>
      )}

      {/* TAB 2: QUEUE, ORDER-TO-TRAY VERIFICATION, TIMETABLES, SEATING & VOICE ANALYTICS */}
      {tab === "campus_ops" && (
        <div className="grid gap-5 lg:grid-cols-2">
          {/* Feature 4: Order-to-Tray Verification */}
          <Card className="p-5 space-y-3">
            <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
              <ClipboardCheck className="h-4 w-4 text-[#76010d]" /> AI Order-to-Tray Verification
            </h2>
            <div className="rounded-xl bg-amber-50 border border-amber-200 p-2.5 text-[11px] text-amber-900">
              Camera/CV recognition hardware is unavailable until compatible hardware is connected. Manual staff item verification is active; zero camera frames retained.
            </div>
            <div className="flex gap-2">
              <Input value={trayOrderRef} onChange={(e) => setTrayOrderRef(e.target.value)} placeholder="Order # (e.g. CB-2026...)" />
              <Button
                size="sm"
                variant="outline"
                disabled={!trayOrderRef.trim()}
                onClick={async () => {
                  try {
                    const res = await api.get(`/campus-intelligence/tray-verification/order/${encodeURIComponent(trayOrderRef.trim())}`);
                    setTrayContext(res.data);
                    const init: Record<string, number> = {};
                    (res.data.expected_items || []).forEach((it: any) => {
                      init[it.item_name] = it.quantity;
                    });
                    setTrayChecked(init);
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                <Search className="h-3.5 w-3.5" /> Load Order
              </Button>
            </div>
            {trayContext && (
              <div className="rounded-xl border border-slate-200 p-3 space-y-2 text-xs">
                <div className="font-bold text-slate-900">Expected Items for {trayContext.order_number}</div>
                {(trayContext.expected_items || []).map((it: any) => (
                  <div key={it.order_item_id} className="flex items-center justify-between gap-2">
                    <span>{it.item_name} (expected: {it.quantity})</span>
                    <Input
                      type="number"
                      min={0}
                      max={50}
                      className="w-20"
                      value={trayChecked[it.item_name] ?? 0}
                      onChange={(e) => setTrayChecked((p) => ({ ...p, [it.item_name]: Number(e.target.value) }))}
                    />
                  </div>
                ))}
                <Button
                  size="sm"
                  variant="primary"
                  onClick={async () => {
                    try {
                      const res = await api.post("/campus-intelligence/tray-verification/verify", {
                        order_id: trayContext.order_id,
                        verification_mode: "manual_checklist",
                        human_confirmed: true,
                        verified_items: Object.entries(trayChecked).map(([item_name, quantity]) => ({ item_name, quantity })),
                      });
                      pushToast(`Tray verification saved: ${res.data.status}`, "success");
                      refetchTrayHist();
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  Confirm Manual Tray Check
                </Button>
              </div>
            )}
            <div className="space-y-1.5 max-h-40 overflow-y-auto pt-2 border-t border-slate-100">
              {trayHistory.slice(0, 8).map((v: any) => (
                <div key={v.id} className="flex items-center justify-between text-xs border border-slate-100 rounded-lg px-2.5 py-1.5">
                  <span><strong>{v.order_number}</strong> • {v.verified_by_name || "Staff"}</span>
                  <Badge tone={v.status === "verified" ? "green" : "amber"}>{v.status}</Badge>
                </div>
              ))}
            </div>
          </Card>

          {/* Feature 5: Class Timetable Import & Demand Prediction */}
          <Card className="p-5 space-y-3">
            <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
              <Calendar className="h-4 w-4 text-[#76010d]" /> Class Timetable Demand Prediction (CSV / Excel)
            </h2>
            {isManager && (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <input
                  type="file"
                  accept=".csv,.xlsx"
                  onChange={(e) => setTtFile(e.target.files?.[0] || null)}
                  className="text-xs file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:font-semibold"
                />
                <Button
                  size="sm"
                  variant="primary"
                  disabled={!ttFile || busy}
                  onClick={async () => {
                    if (!ttFile) return;
                    setBusy(true);
                    try {
                      const fd = new FormData();
                      fd.append("file", ttFile);
                      if (selectedCanteenId) fd.append("canteen_id", selectedCanteenId);
                      const res = await api.post("/campus-intelligence/timetables/import", fd);
                      pushToast(`Imported ${res.data.inserted_slots} timetable slot(s)`, "success");
                      setTtFile(null);
                      refetchTimetable();
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <FileSpreadsheet className="h-3.5 w-3.5" /> Import Timetable
                </Button>
              </div>
            )}
            {timetablePred && (
              <div className="space-y-2 text-xs">
                <div className="flex flex-wrap gap-2">
                  <Badge tone="blue">{timetablePred.timetable_slots_count} slots today</Badge>
                  <Badge tone="slate">{timetablePred.historical_same_weekday_orders} hist weekday orders</Badge>
                  <Badge tone="amber">{timetablePred.low_stock_ingredient_warnings} low stock</Badge>
                </div>
                {(timetablePred.predicted_break_periods || []).length === 0 ? (
                  <div className="text-slate-500">Import a CSV/XLSX timetable with columns `department,day_of_week,slot_type,start_time,end_time,estimated_cohort_size` to analyze break surges.</div>
                ) : (
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {timetablePred.predicted_break_periods.map((b: any, i: number) => (
                      <div key={i} className="rounded-lg border border-slate-200 p-2 flex items-center justify-between">
                        <div>
                          <div className="font-bold text-slate-900">{b.start_time}–{b.end_time} ({b.slot_type.replace("_", " ")})</div>
                          <div className="text-[11px] text-slate-500">Depts: {b.departments.join(", ")} • Cohort: {b.reported_cohort_size}</div>
                        </div>
                        <Badge tone={b.demand_level === "high" ? "red" : b.demand_level === "moderate" ? "amber" : "slate"}>
                          {b.forecast_estimated_orders != null ? `~${b.forecast_estimated_orders} est` : b.demand_level}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* Feature 8: Smart Seating Admin & Manual Updates */}
          <Card className="p-5 space-y-3">
            <h2 className="font-extrabold text-slate-900">Smart Seating Zones &amp; Manual Occupancy</h2>
            {isManager && (
              <div className="grid grid-cols-4 gap-2 text-xs">
                <Input value={zoneCode} onChange={(e) => setZoneCode(e.target.value)} placeholder="Code" />
                <Input value={zoneName} onChange={(e) => setZoneName(e.target.value)} placeholder="Zone Name" className="col-span-2" />
                <div className="flex gap-1">
                  <Input type="number" value={zoneSeats} onChange={(e) => setZoneSeats(e.target.value)} placeholder="Seats" />
                  <Button
                    size="sm"
                    onClick={async () => {
                      try {
                        await api.post("/campus-intelligence/seating/zones", {
                          zone_code: zoneCode,
                          zone_name: zoneName,
                          total_seats: Number(zoneSeats),
                          canteen_id: selectedCanteenId || null,
                        });
                        refetchSeating();
                        pushToast("Seating zone saved", "success");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Save
                  </Button>
                </div>
              </div>
            )}
            <div className="space-y-2">
              {(seatingData?.zones || []).map((z: any) => (
                <div key={z.id} className="rounded-xl border border-slate-200 p-2.5 flex flex-wrap items-center justify-between gap-2 text-xs">
                  <div>
                    <div className="font-bold text-slate-900">{z.zone_name} ({z.zone_code})</div>
                    <div className="text-[11px] text-slate-500">
                      Occupied: {z.occupied_seats ?? "Unmeasured"} / {z.total_seats} ({z.data_source})
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Input
                      type="number"
                      min={0}
                      max={z.total_seats}
                      className="w-20"
                      placeholder="Occ"
                      value={occUpdateMap[z.id] ?? ""}
                      onChange={(e) => setOccUpdateMap((p) => ({ ...p, [z.id]: e.target.value }))}
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        try {
                          await api.patch(`/campus-intelligence/seating/zones/${z.id}/occupancy`, {
                            occupied_seats: Number(occUpdateMap[z.id] || 0),
                            data_source: "manual",
                          });
                          refetchSeating();
                          pushToast("Occupancy updated", "success");
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      Update
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Feature 3 (Queue Overview) + Feature 9 (Voice Analytics) */}
          <Card className="p-5 space-y-3">
            <h2 className="font-extrabold text-slate-900">Virtual Queue &amp; Voice Assistant Analytics</h2>
            {voiceAnalytics && (
              <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 text-xs flex flex-wrap gap-3">
                <span><strong>Voice Queries (14d):</strong> {voiceAnalytics.total_queries}</span>
                <span><strong>EN:</strong> {voiceAnalytics.by_language?.en ?? 0}</span>
                <span><strong>TE:</strong> {voiceAnalytics.by_language?.te ?? 0}</span>
                <span><strong>Draft Orders:</strong> {voiceAnalytics.draft_orders_initiated}</span>
              </div>
            )}
            <div className="space-y-1.5 max-h-48 overflow-y-auto text-xs">
              {(queueOverview?.queues || []).map((q: any) => (
                <div key={q.canteen_id} className="rounded-lg border border-slate-200 p-2.5 flex items-center justify-between">
                  <div>
                    <div className="font-bold text-slate-900">{q.canteen_name}</div>
                    <div className="text-[11px] text-slate-500">Active: {q.active_count} • Delayed: {q.delayed_orders?.length ?? 0} • Load: {q.kitchen_workload_percent}%</div>
                  </div>
                  <Button size="sm" variant="outline" onClick={() => refetchQueue()}>Sync</Button>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* TAB 3: NATURAL LANGUAGE ADMIN COMMAND CENTER, AI RCA, INCIDENT PREVENTION & RESOURCE ALLOCATION */}
      {tab === "ai_rca" && (
        <div className="grid gap-5 lg:grid-cols-2">
          {/* Feature 15: Natural Language Administrative Command Center */}
          <Card className="p-5 space-y-3">
            <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
              <Bot className="h-4 w-4 text-[#76010d]" /> Natural Language Admin Command Center
            </h2>
            <p className="text-xs text-slate-500">Strictly read-only database-backed answers. Destructive actions &amp; secret queries are automatically blocked and audited.</p>
            <div className="flex flex-wrap gap-1.5">
              {[
                "Why are orders delayed at Counter 1?",
                "Which ingredients may run out soon?",
                "How many orders are waiting?",
                "What payment discrepancies need attention?",
                "Which incidents remain unresolved?",
              ].map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => setNlQuestion(q)}
                  className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-200"
                >
                  {q}
                </button>
              ))}
            </div>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (!nlQuestion.trim()) return;
                setBusy(true);
                try {
                  const res = await api.post("/command-center/nl-command", {
                    question: nlQuestion.trim(),
                    canteen_id: selectedCanteenId || null,
                  });
                  setNlResponses((p) => [{ q: nlQuestion.trim(), ...res.data }, ...p].slice(0, 6));
                  setNlQuestion("");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
              className="flex gap-2"
            >
              <Input value={nlQuestion} onChange={(e) => setNlQuestion(e.target.value)} placeholder="Ask an operational question..." />
              <Button type="submit" variant="primary" disabled={busy}>Ask</Button>
            </form>
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {nlResponses.map((r, i) => (
                <div key={i} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs space-y-1">
                  <div className="flex items-center justify-between font-bold">
                    <span>Q: {r.q}</span>
                    <Badge tone={r.status === "blocked" ? "red" : "green"}>{r.intent}</Badge>
                  </div>
                  <div className="text-slate-700">{r.answer}</div>
                  <div className="text-[10px] text-slate-400">Timestamp: {r.timestamp}</div>
                </div>
              ))}
            </div>
          </Card>

          {/* Feature 11: AI Root-Cause Investigation */}
          <Card className="p-5 space-y-3">
            <h2 className="font-extrabold text-slate-900">AI Root-Cause Investigation (Facts vs Hypotheses)</h2>
            <div className="flex flex-wrap gap-2 text-xs">
              <Select value={rcaDomain} onChange={(e) => setRcaDomain(e.target.value)} className="flex-1">
                <option value="order_delays">Order Delays</option>
                <option value="kitchen_bottlenecks">Kitchen Bottlenecks</option>
                <option value="stock_shortages">Stock Shortages</option>
                <option value="inventory_discrepancies">Inventory Discrepancies</option>
                <option value="payment_failures">Payment Failures</option>
                <option value="settlement_mismatches">Settlement Mismatches</option>
                <option value="printer_failures">Printer Failures</option>
                <option value="qr_failures">QR Scanner Failures</option>
                <option value="notification_failures">Notification Failures</option>
              </Select>
              <Input type="number" className="w-20" value={rcaHours} onChange={(e) => setRcaHours(e.target.value)} />
              <Button
                size="sm"
                variant="primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api.post("/command-center/investigations/run", {
                      target_domain: rcaDomain,
                      canteen_id: selectedCanteenId || null,
                      lookback_hours: Number(rcaHours || 24),
                    });
                    refetchRca();
                    pushToast("Root-cause investigation completed", "success");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Investigate
              </Button>
            </div>
            <div className="space-y-2 max-h-72 overflow-y-auto">
              {investigations.slice(0, 5).map((inv: any) => (
                <div key={inv.id} className="rounded-xl border border-slate-200 p-3 text-xs space-y-1.5">
                  <div className="flex items-center justify-between font-bold">
                    <span>{inv.query_summary}</span>
                    <Badge tone="blue">{inv.status}</Badge>
                  </div>
                  {(inv.confirmed_facts || []).map((f: any, idx: number) => (
                    <div key={idx} className="rounded bg-emerald-50 border border-emerald-200 px-2 py-1 text-emerald-900">
                      <strong>VERIFIED FACT:</strong> {f.summary}
                    </div>
                  ))}
                  {(inv.ai_hypotheses || []).map((h: any, idx: number) => (
                    <div key={idx} className="rounded bg-amber-50 border border-amber-200 px-2 py-1 text-amber-900">
                      <strong>AI HYPOTHESIS (UNVERIFIED • {h.confidence}):</strong> {h.hypothesis}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </Card>

          {/* Feature 13: Predictive Incident Prevention */}
          <Card className="p-5 space-y-3">
            <h2 className="font-extrabold text-slate-900">Predictive Incident Prevention</h2>
            <div className="space-y-2">
              {(prevention?.risk_assessments || []).map((r: any, idx: number) => (
                <div key={idx} className="rounded-xl border border-slate-200 p-3 text-xs space-y-1">
                  <div className="flex items-center justify-between font-bold">
                    <span className="capitalize">{r.category.replace("_", " ")}</span>
                    <Badge tone={r.risk_level === "high" ? "red" : r.risk_level === "medium" ? "amber" : "green"}>
                      {r.risk_level.toUpperCase()} {r.risk_score != null ? `(${r.risk_score}/100)` : ""}
                    </Badge>
                  </div>
                  <div className="text-slate-600">{r.evidence}</div>
                </div>
              ))}
            </div>
            {prevention?.disclaimer && <p className="text-[11px] text-slate-500">{prevention.disclaimer}</p>}
          </Card>

          {/* Feature 14: Intelligent Resource Allocation */}
          <Card className="p-5 space-y-3">
            <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
              <Users className="h-4 w-4 text-[#76010d]" /> Intelligent Resource Allocation (Advisory)
            </h2>
            <div className="space-y-2 text-xs">
              {(resources?.counters_allocation || []).map((c: any) => (
                <div key={c.canteen_id} className="rounded-lg border border-slate-200 p-2.5 flex justify-between">
                  <span className="font-bold">{c.counter_slot}: {c.canteen_name}</span>
                  <span>Load {c.workload_percent}% • On-Duty Staff: <strong>{c.on_duty_staff_count}</strong> / {c.assigned_staff_count}</span>
                </div>
              ))}
              {(resources?.recommendations || []).map((rec: any, i: number) => (
                <div key={i} className="rounded-xl bg-[#fdf8f0] border border-[#76010d]/20 p-2.5">
                  <div className="font-bold text-[#76010d]">{rec.target} ({rec.priority})</div>
                  <div className="text-slate-700">{rec.recommendation}</div>
                </div>
              ))}
            </div>
            {resources?.governance_notice && <p className="text-[11px] text-slate-500">{resources.governance_notice}</p>}
          </Card>
        </div>
      )}

      {/* TAB 4: LIVE DIGITAL CAFETERIA MAP & WHAT-IF SIMULATION ENGINE */}
      {tab === "map_sim" && (
        <div className="grid gap-5 lg:grid-cols-2">
          {/* Feature 16: Live Digital Cafeteria Map */}
          <Card className="p-5 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
                <MapPin className="h-4 w-4 text-[#76010d]" /> Live Digital Cafeteria Map
              </h2>
              <div className="flex items-center gap-1.5">
                <Select value={mapHours} onChange={(e) => setMapHours(e.target.value)} className="w-28">
                  <option value="6">Last 6h</option>
                  <option value="24">Last 24h</option>
                  <option value="72">Last 3d</option>
                </Select>
                <Button size="sm" variant="outline" onClick={() => refetchMap()}><RefreshCw className="h-3.5 w-3.5" /></Button>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {(mapData?.sections || []).map((sec: any) => (
                <button
                  key={sec.zone_id}
                  type="button"
                  onClick={() => setSelectedMapZone(sec)}
                  className={`rounded-2xl border p-4 text-left transition ${
                    selectedMapZone?.zone_id === sec.zone_id ? "border-[#76010d] ring-2 ring-[#76010d]/30 bg-[#fdf8f0]" : "border-slate-200 bg-white hover:bg-slate-50"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-bold uppercase text-slate-500">{sec.section_type.replace("_", " ")}</span>
                    <Badge tone={sec.status === "busy" || sec.status === "paused" ? "red" : sec.status === "moderate" ? "amber" : sec.status === "low" ? "green" : "slate"}>
                      {sec.status}
                    </Badge>
                  </div>
                  <div className="font-extrabold text-sm text-slate-900 mt-1">{sec.label}</div>
                  {sec.workload_percent != null && (
                    <div className="text-xs text-slate-600 mt-1">
                      Workload: <strong>{sec.workload_percent}%</strong> • Active: <strong>{sec.active_orders ?? sec.ready_orders ?? 0}</strong>
                    </div>
                  )}
                  {sec.total_seats != null && (
                    <div className="text-xs text-slate-600 mt-1">
                      Seats: {sec.available_seats != null ? `${sec.available_seats}/${sec.total_seats} free` : `${sec.total_seats} total (${sec.data_source})`}
                    </div>
                  )}
                </button>
              ))}
            </div>
            {selectedMapZone && (
              <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 text-xs space-y-1">
                <div className="font-bold text-slate-900">Selected Section: {selectedMapZone.label}</div>
                <div>Status: {selectedMapZone.status} • Alerts: {selectedMapZone.alerts_count ?? 0} • Window orders: {selectedMapZone.historical_orders_window ?? "N/A"}</div>
              </div>
            )}
            {mapData?.transparency_notice && <p className="text-[11px] text-slate-500">{mapData.transparency_notice}</p>}
          </Card>

          {/* Feature 17: Strictly Isolated What-If Simulation Engine */}
          <Card className="p-5 space-y-3">
            <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
              <FlaskConical className="h-4 w-4 text-[#76010d]" /> Isolated What-If Simulation Engine
            </h2>
            <div className="rounded-xl bg-indigo-50 border border-indigo-200 px-3 py-2 text-[11px] text-indigo-900 font-semibold">
              SIMULATION SANDBOX: Read-only against production baselines. Running scenarios NEVER modifies orders, payments, inventory, or customer records.
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <Input value={simName} onChange={(e) => setSimName(e.target.value)} placeholder="Scenario name" className="col-span-2" />
              <div>
                <label className="text-[11px] font-bold text-slate-600">Staff Delta (-5..+15)</label>
                <Input type="number" value={simStaffDelta} onChange={(e) => setSimStaffDelta(e.target.value)} />
              </div>
              <div>
                <label className="text-[11px] font-bold text-slate-600">Demand Multiplier (0.2..4.0)</label>
                <Input type="number" step="0.1" value={simDemandMult} onChange={(e) => setSimDemandMult(e.target.value)} />
              </div>
              <div>
                <label className="text-[11px] font-bold text-slate-600">Prep Capacity Mult (0.3..3.0)</label>
                <Input type="number" step="0.1" value={simPrepMult} onChange={(e) => setSimPrepMult(e.target.value)} />
              </div>
              <div>
                <label className="text-[11px] font-bold text-slate-600">Counter Shift % (-40..+40)</label>
                <Input type="number" value={simCounterShift} onChange={(e) => setSimCounterShift(e.target.value)} />
              </div>
            </div>
            <Button
              size="sm"
              variant="primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const res = await api.post("/command-center/simulations/run", {
                    name: simName,
                    canteen_id: selectedCanteenId || null,
                    parameters: {
                      staff_delta: Number(simStaffDelta),
                      demand_multiplier: Number(simDemandMult),
                      prep_capacity_multiplier: Number(simPrepMult),
                      counter_shift_percent: Number(simCounterShift),
                    },
                  });
                  setSimResult(res.data);
                  refetchSims();
                  pushToast("Simulation completed (production untouched)", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              <Sliders className="h-3.5 w-3.5" /> Run Isolated Simulation
            </Button>

            {simResult && (
              <div className="rounded-xl border-2 border-indigo-200 bg-indigo-50/50 p-3 text-xs space-y-1.5">
                <div className="flex items-center justify-between">
                  <Badge tone="blue">SIMULATED RESULT</Badge>
                  <Badge tone={simResult.simulated_outcomes?.bottleneck_risk === "high" ? "red" : simResult.simulated_outcomes?.bottleneck_risk === "moderate" ? "amber" : "green"}>
                    Risk: {simResult.simulated_outcomes?.bottleneck_risk}
                  </Badge>
                </div>
                <div>
                  Est. Wait Range:{" "}
                  <strong>
                    {simResult.simulated_outcomes?.estimated_wait_minutes?.low}–{simResult.simulated_outcomes?.estimated_wait_minutes?.high} min
                  </strong>{" "}
                  (expected {simResult.simulated_outcomes?.estimated_wait_minutes?.expected}m)
                </div>
                <div>
                  Simulated Throughput: <strong>{simResult.simulated_outcomes?.simulated_throughput_per_hour}/hr</strong> • Utilization:{" "}
                  <strong>{simResult.simulated_outcomes?.simulated_utilization_percent}%</strong>
                </div>
                <div className="flex gap-2 pt-1">
                  <Button size="sm" variant="outline" onClick={() => void downloadBlob(`/command-center/simulations/${simResult.id}/export/csv`, `sim_${simResult.id.slice(0, 8)}.csv`)}>
                    <Download className="h-3 w-3" /> CSV
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => void downloadBlob(`/command-center/simulations/${simResult.id}/export/pdf`, `sim_${simResult.id.slice(0, 8)}.pdf`)}>
                    <Download className="h-3 w-3" /> PDF
                  </Button>
                </div>
              </div>
            )}

            {simulations.length > 0 && (
              <div className="space-y-1 max-h-36 overflow-y-auto pt-2 border-t border-slate-100 text-xs">
                {simulations.slice(0, 6).map((s: any) => (
                  <div key={s.id} className="flex items-center justify-between py-1">
                    <span className="font-semibold text-slate-800">{s.name}</span>
                    <Badge tone="slate">{s.simulated_outcomes?.bottleneck_risk}</Badge>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* TAB 5: AUTOMATED REPORTS, WORKFLOW AUTOMATION & HUMAN GOVERNANCE */}
      {tab === "reports_gov" && (
        <div className="space-y-5">
          {/* Feature 19: Emergency Kill-Switch & Governance */}
          {governance && (
            <Card className={`p-5 border-2 ${governance.global_automation_enabled ? "border-emerald-200" : "border-rose-400 bg-rose-50/40"}`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="font-extrabold text-slate-900 flex items-center gap-1.5">
                    <Power className="h-4 w-4 text-[#76010d]" /> Human-Controlled Automation &amp; Emergency Override
                  </h2>
                  <p className="text-xs text-slate-600">
                    Global Automation: <strong>{governance.global_automation_enabled ? "ENABLED" : "EMERGENCY DISABLED"}</strong> • Pending Human Approvals:{" "}
                    <strong>{governance.pending_approvals_count}</strong>
                  </p>
                </div>
                {isAdmin && (
                  <div className="flex items-center gap-2">
                    <Input
                      className="w-56"
                      value={govReason}
                      onChange={(e) => setGovReason(e.target.value)}
                      placeholder="Audit reason for override..."
                    />
                    <Button
                      size="sm"
                      variant={governance.global_automation_enabled ? "outline" : "primary"}
                      disabled={govReason.trim().length < 3 || busy}
                      onClick={async () => {
                        setBusy(true);
                        try {
                          await api.post("/command-center/governance/emergency-toggle", {
                            enabled: !governance.global_automation_enabled,
                            reason: govReason.trim(),
                          });
                          setGovReason("");
                          refetchGov();
                          pushToast("Global automation governance updated", "success");
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      {governance.global_automation_enabled ? "Emergency Disable All" : "Re-Enable Automation"}
                    </Button>
                  </div>
                )}
              </div>
            </Card>
          )}

          <div className="grid gap-5 lg:grid-cols-2">
            {/* Feature 12: Workflow Automation */}
            <Card className="p-5 space-y-3">
              <h2 className="font-extrabold text-slate-900">Configurable Automation Workflows ({workflows.length})</h2>
              <div className="space-y-2 max-h-80 overflow-y-auto text-xs">
                {workflows.map((w: any) => (
                  <div key={w.id} className="rounded-xl border border-slate-200 p-3 space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-slate-900">{w.name}</span>
                      <div className="flex items-center gap-1">
                        {w.requires_approval && <Badge tone="amber">Approval Required</Badge>}
                        <Badge tone={w.is_enabled ? "green" : "slate"}>{w.is_enabled ? "Enabled" : "Disabled"}</Badge>
                      </div>
                    </div>
                    <div className="text-[11px] text-slate-500">{w.description}</div>
                    <div className="flex items-center gap-2 pt-1">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={async () => {
                          try {
                            await api.patch(`/command-center/workflows/${w.id}`, { is_enabled: !w.is_enabled });
                            refetchWorkflows();
                          } catch (err) {
                            pushToast(getApiError(err), "error");
                          }
                        }}
                      >
                        {w.is_enabled ? "Disable" : "Enable"}
                      </Button>
                      <Button
                        size="sm"
                        variant="primary"
                        disabled={!w.is_enabled || busy}
                        onClick={async () => {
                          setBusy(true);
                          try {
                            const res = await api.post(`/command-center/workflows/${w.id}/execute`, {
                              canteen_id: selectedCanteenId || null,
                            });
                            refetchExecs();
                            refetchGov();
                            pushToast(`Workflow status: ${res.data.status}`, "success");
                          } catch (err) {
                            pushToast(getApiError(err), "error");
                          } finally {
                            setBusy(false);
                          }
                        }}
                      >
                        <Play className="h-3 w-3" /> Run
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            {/* Feature 19: Approval Queue & Execution History */}
            <Card className="p-5 space-y-3">
              <h2 className="font-extrabold text-slate-900">Approval Queue &amp; Execution Audit Trail</h2>
              <div className="space-y-2 max-h-80 overflow-y-auto text-xs">
                {executions.length === 0 ? (
                  <div className="text-slate-500">No workflow executions recorded yet.</div>
                ) : (
                  executions.slice(0, 20).map((ex: any) => (
                    <div key={ex.id} className="rounded-xl border border-slate-200 p-3 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-slate-900">{ex.workflow_name}</span>
                        <Badge tone={ex.status === "executed" || ex.status === "approved" ? "green" : ex.status === "pending_approval" ? "amber" : "red"}>
                          {ex.status}
                        </Badge>
                      </div>
                      {ex.status === "pending_approval" && isManager && (
                        <div className="flex gap-2 pt-1">
                          <Button
                            size="sm"
                            variant="primary"
                            onClick={async () => {
                              try {
                                await api.post(`/command-center/executions/${ex.id}/decision`, {
                                  approve: true,
                                  notes: "Approved in Command Center",
                                });
                                refetchExecs();
                                refetchGov();
                                pushToast("Execution approved", "success");
                              } catch (err) {
                                pushToast(getApiError(err), "error");
                              }
                            }}
                          >
                            Approve
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={async () => {
                              try {
                                await api.post(`/command-center/executions/${ex.id}/decision`, {
                                  approve: false,
                                  notes: "Rejected in Command Center",
                                });
                                refetchExecs();
                                refetchGov();
                                pushToast("Execution rejected", "info");
                              } catch (err) {
                                pushToast(getApiError(err), "error");
                              }
                            }}
                          >
                            Reject
                          </Button>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </Card>
          </div>

          {/* Feature 18: Automated Daily / Weekly / Monthly Operations Reports */}
          <Card className="p-5 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-extrabold text-slate-900">Automated Operations Reports (Verified DB Records)</h2>
              <div className="flex items-center gap-2">
                <Select value={repPeriod} onChange={(e) => setRepPeriod(e.target.value as any)} className="w-32">
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </Select>
                <Button
                  size="sm"
                  variant="primary"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await api.post("/command-center/reports/generate", {
                        period_type: repPeriod,
                        canteen_id: selectedCanteenId || null,
                      });
                      refetchReports();
                      pushToast(`${repPeriod} operations report generated`, "success");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Generate Report
                </Button>
              </div>
            </div>
            <div className="space-y-2 text-xs">
              {reports.slice(0, 10).map((r: any) => (
                <div key={r.id} className="rounded-xl border border-slate-200 p-3 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="font-bold text-slate-900 uppercase">
                      {r.period_type} Report • {r.period_start} to {r.period_end}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      Orders: {r.summary?.orders?.total ?? 0} • Completed: {r.summary?.orders?.completed ?? 0} • Revenue: ₹{r.summary?.payments_and_refunds?.verified_revenue_inr ?? "0.00"}
                    </div>
                  </div>
                  <div className="flex gap-1.5">
                    <Button size="sm" variant="outline" onClick={() => void downloadBlob(`/command-center/reports/${r.id}/export/pdf`, `ops_${r.period_type}.pdf`)}>PDF</Button>
                    <Button size="sm" variant="outline" onClick={() => void downloadBlob(`/command-center/reports/${r.id}/export/csv`, `ops_${r.period_type}.csv`)}>CSV</Button>
                    <Button size="sm" variant="outline" onClick={() => void downloadBlob(`/command-center/reports/${r.id}/export/xlsx`, `ops_${r.period_type}.xlsx`)}>Excel</Button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
};

