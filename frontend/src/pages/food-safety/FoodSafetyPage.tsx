import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Download,
  Flame,
  ShieldCheck,
  Sparkles,
  Thermometer,
} from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen } from "../../types";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";

type FsTab = "dashboard" | "inspections" | "temperature" | "expiry" | "cleaning" | "incidents";

export const FoodSafetyPage: React.FC = () => {
  const { user, selectedCanteenId } = useAppStore();
  const { pushToast } = useToast();
  const isCollegeWide = Boolean(user?.roles?.some((r) => r === "super_admin" || r === "college_admin"));

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [canteenId, setCanteenId] = useState(user?.assigned_canteen_id || selectedCanteenId || "");
  useEffect(() => {
    if (!canteenId && canteens.length > 0) setCanteenId(canteens[0].id);
  }, [canteens, canteenId]);
  const activeId = (!isCollegeWide && user?.assigned_canteen_id) ? user.assigned_canteen_id : (canteenId || canteens[0]?.id || "");

  const [tab, setTab] = useState<FsTab>("dashboard");
  const [busy, setBusy] = useState(false);

  // Form states
  const [inspResults, setInspResults] = useState<Record<string, "pass" | "fail" | "not_applicable">>({});
  const [inspNotes, setInspNotes] = useState("");
  const [eqName, setEqName] = useState("");
  const [eqCode, setEqCode] = useState("");
  const [eqType, setEqType] = useState("refrigerator");
  const [eqMin, setEqMin] = useState("1");
  const [eqMax, setEqMax] = useState("4");
  const [logEqId, setLogEqId] = useState("");
  const [logTemp, setLogTemp] = useState("");
  const [logNotes, setLogNotes] = useState("");
  const [cleanArea, setCleanArea] = useState("");
  const [cleanFreq, setCleanFreq] = useState("daily");
  const [incTitle, setIncTitle] = useState("");
  const [incDesc, setIncDesc] = useState("");
  const [incSeverity, setIncSeverity] = useState("high");

  const { data: dashboard, refetch: refetchDash } = useQuery<any>({
    queryKey: ["fs-dashboard", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/food-safety/dashboard?canteen_id=${activeId}`)).data,
  });

  const { data: templates = [] } = useQuery<any[]>({
    queryKey: ["fs-templates", activeId],
    enabled: Boolean(activeId && tab === "inspections"),
    queryFn: async () => (await api.get(`/food-safety/templates?canteen_id=${activeId}&seed_default=true`)).data,
  });

  const { data: inspections = [], refetch: refetchInsp } = useQuery<any[]>({
    queryKey: ["fs-inspections", activeId],
    enabled: Boolean(activeId && tab === "inspections"),
    queryFn: async () => (await api.get(`/food-safety/inspections?canteen_id=${activeId}`)).data,
  });

  const { data: equipment = [], refetch: refetchEquip } = useQuery<any[]>({
    queryKey: ["fs-equipment", activeId],
    enabled: Boolean(activeId && tab === "temperature"),
    queryFn: async () => (await api.get(`/food-safety/equipment?canteen_id=${activeId}`)).data,
  });

  const { data: tempLogs = [], refetch: refetchTemps } = useQuery<any[]>({
    queryKey: ["fs-temps", activeId],
    enabled: Boolean(activeId && tab === "temperature"),
    queryFn: async () => (await api.get(`/food-safety/temperatures?canteen_id=${activeId}`)).data,
  });

  const { data: expiry, refetch: refetchExpiry } = useQuery<any>({
    queryKey: ["fs-expiry", activeId],
    enabled: Boolean(activeId && tab === "expiry"),
    queryFn: async () => (await api.get(`/food-safety/expiry-monitoring?canteen_id=${activeId}`)).data,
  });

  const { data: cleaning, refetch: refetchCleaning } = useQuery<any>({
    queryKey: ["fs-cleaning", activeId],
    enabled: Boolean(activeId && tab === "cleaning"),
    queryFn: async () => (await api.get(`/food-safety/cleaning?canteen_id=${activeId}`)).data,
  });

  const { data: incidents = [], refetch: refetchIncidents } = useQuery<any[]>({
    queryKey: ["fs-incidents", activeId],
    enabled: Boolean(activeId && tab === "incidents"),
    queryFn: async () => (await api.get(`/food-safety/incidents?canteen_id=${activeId}`)).data,
  });

  const activeTemplate = templates[0];

  const downloadInspectionPdf = async (id: string, num: string) => {
    try {
      const res = await api.get(`/food-safety/inspections/${id}/pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${num}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      pushToast(getApiError(err, "PDF export failed"), "error");
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-[#380106] p-4 text-white">
        <div className="flex items-center gap-3">
          <ShieldCheck className="h-6 w-6 text-emerald-300" />
          <div>
            <h1 className="text-xl font-extrabold">Food Safety &amp; Hygiene Compliance</h1>
            <p className="text-xs text-[#fdedce]/80">
              Daily hygiene checklists, equipment temperature thresholds, expiry disposal, sanitation &amp; incidents
            </p>
          </div>
        </div>
        <Select
          value={activeId}
          disabled={!isCollegeWide && Boolean(user?.assigned_canteen_id)}
          onChange={(e) => setCanteenId(e.target.value)}
          className="w-56 bg-slate-800 border-slate-700 text-white"
        >
          {canteens.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex flex-wrap gap-2">
        {(
          [
            { k: "dashboard", l: "Compliance Dashboard" },
            { k: "inspections", l: "Daily Hygiene Inspections" },
            { k: "temperature", l: "Equipment Temperatures" },
            { k: "expiry", l: "Expiry Monitoring" },
            { k: "cleaning", l: "Cleaning Schedules" },
            { k: "incidents", l: "Safety Incidents" },
          ] as const
        ).map((t) => (
          <Button key={t.k} size="sm" variant={tab === t.k ? "secondary" : "outline"} onClick={() => setTab(t.k)}>
            {t.l}
          </Button>
        ))}
      </div>

      {tab === "dashboard" && dashboard && (
        <div className="space-y-4">
          {dashboard.empty && (
            <Card className="p-4 border-amber-200 bg-amber-50 text-xs text-amber-900">
              {dashboard.message} (Strict actual records only — no synthetic compliance scores are displayed.)
            </Card>
          )}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="p-4">
              <div className="text-xs text-slate-500">Completed Inspections (30d)</div>
              <div className="text-2xl font-black text-slate-900">{dashboard.completed_inspections_count}</div>
              <div className="text-xs text-slate-500 mt-1">
                Pass rate:{" "}
                {dashboard.inspection_pass_rate_percent !== null
                  ? `${dashboard.inspection_pass_rate_percent}%`
                  : "No inspections recorded"}
              </div>
            </Card>
            <Card className="p-4 border-red-200 bg-red-50/40">
              <div className="text-xs text-red-700">Temperature Violations</div>
              <div className="text-2xl font-black text-red-900">{dashboard.temperature_violations_count}</div>
              <div className="text-xs text-red-700 mt-1">Total temp readings: {dashboard.temperature_logs_count}</div>
            </Card>
            <Card className="p-4 border-amber-200 bg-amber-50/40">
              <div className="text-xs text-amber-800">Expired / Expiring Batches</div>
              <div className="text-2xl font-black text-amber-900">
                {dashboard.expired_batches_count} / {dashboard.approaching_expiry_batches_count}
              </div>
              <div className="text-xs text-amber-800 mt-1">Expired / Within 7 days</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-slate-500">Overdue Cleaning &amp; Open Incidents</div>
              <div className="text-2xl font-black text-slate-900">
                {dashboard.overdue_cleaning_tasks_count} / {dashboard.open_incidents_count}
              </div>
              <div className="text-xs text-slate-500 mt-1">Resolved incidents: {dashboard.resolved_incidents_count}</div>
            </Card>
          </div>
        </div>
      )}

      {tab === "inspections" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4 space-y-3">
            <div className="flex items-center gap-2 font-bold text-slate-900">
              <ClipboardCheck className="h-4 w-4 text-[#76010d]" /> Record Daily Hygiene Inspection
            </div>
            {activeTemplate ? (
              <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
                {(activeTemplate.items || []).map((it: any) => {
                  const val = inspResults[it.code] || "pass";
                  return (
                    <div key={it.code} className="flex items-center justify-between gap-2 rounded-xl border border-slate-200 p-2.5 text-xs">
                      <div>
                        <div className="font-bold text-slate-900">{it.title}</div>
                        <div className="text-[11px] text-slate-500">{it.category}</div>
                      </div>
                      <Select
                        value={val}
                        onChange={(e) => setInspResults((p) => ({ ...p, [it.code]: e.target.value as any }))}
                        className="w-32"
                      >
                        <option value="pass">PASS</option>
                        <option value="fail">FAIL</option>
                        <option value="not_applicable">N/A</option>
                      </Select>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="text-xs text-slate-500">Loading checklist template...</div>
            )}
            <Input value={inspNotes} onChange={(e) => setInspNotes(e.target.value)} placeholder="Inspector observations / corrective notes..." />
            <Button
              variant="primary"
              disabled={busy || !activeTemplate}
              onClick={async () => {
                setBusy(true);
                try {
                  const itemsPayload = (activeTemplate.items || []).map((it: any) => ({
                    item_code: it.code,
                    item_title: it.title,
                    category: it.category || "general",
                    result: inspResults[it.code] || "pass",
                  }));
                  await api.post("/food-safety/inspections", {
                    canteen_id: activeId,
                    template_id: activeTemplate.id,
                    items: itemsPayload,
                    notes: inspNotes || null,
                  });
                  setInspNotes("");
                  pushToast("Hygiene inspection recorded", "success");
                  refetchInsp();
                  refetchDash();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Submit Inspection
            </Button>
          </Card>

          <Card className="p-4 space-y-3">
            <h2 className="font-bold text-slate-900">Recent Inspections ({inspections.length})</h2>
            <div className="space-y-2 max-h-[460px] overflow-y-auto">
              {inspections.length === 0 ? (
                <div className="text-xs text-slate-500 py-6 text-center">No inspections recorded yet.</div>
              ) : (
                inspections.map((i) => (
                  <div key={i.id} className="rounded-xl border border-slate-200 p-3 text-xs flex items-center justify-between gap-2">
                    <div>
                      <div className="font-bold text-slate-900">{i.inspection_number}</div>
                      <div className="text-slate-500">
                        {i.inspector_name || "Staff"} • {i.passed_items} Pass / {i.failed_items} Fail / {i.na_items} N/A
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge tone={i.overall_status === "pass" ? "green" : "red"}>{i.overall_status.toUpperCase()}</Badge>
                      <Button size="sm" variant="outline" onClick={() => downloadInspectionPdf(i.id, i.inspection_number)}>
                        <Download className="h-3.5 w-3.5" /> PDF
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>
      )}

      {tab === "temperature" && (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4 space-y-3">
              <div className="flex items-center gap-2 font-bold text-slate-900">
                <Thermometer className="h-4 w-4 text-sky-700" /> Configure Equipment Temperature Range
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Input value={eqName} onChange={(e) => setEqName(e.target.value)} placeholder="Equipment Name (e.g., Dairy Fridge 1)" />
                <Input value={eqCode} onChange={(e) => setEqCode(e.target.value)} placeholder="Code (e.g., FRIDGE-01)" />
                <Select value={eqType} onChange={(e) => setEqType(e.target.value)}>
                  <option value="refrigerator">Refrigerator</option>
                  <option value="freezer">Freezer</option>
                  <option value="storage_unit">Storage Unit</option>
                  <option value="prep_equipment">Prep Equipment</option>
                  <option value="holding_equipment">Hot Holding Unit</option>
                </Select>
                <div className="flex gap-2">
                  <Input type="number" step="0.5" value={eqMin} onChange={(e) => setEqMin(e.target.value)} placeholder="Min °C" />
                  <Input type="number" step="0.5" value={eqMax} onChange={(e) => setEqMax(e.target.value)} placeholder="Max °C" />
                </div>
              </div>
              <Button
                size="sm"
                variant="primary"
                disabled={busy || !eqName.trim() || !eqCode.trim()}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api.post("/food-safety/equipment", {
                      canteen_id: activeId,
                      equipment_name: eqName.trim(),
                      equipment_code: eqCode.trim(),
                      equipment_type: eqType,
                      min_temp_c: Number(eqMin),
                      max_temp_c: Number(eqMax),
                    });
                    setEqName("");
                    setEqCode("");
                    pushToast("Equipment threshold saved", "success");
                    refetchEquip();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Save Equipment Range
              </Button>
            </Card>

            <Card className="p-4 space-y-3">
              <div className="font-bold text-slate-900">Log Equipment Temperature Reading</div>
              <Select value={logEqId} onChange={(e) => setLogEqId(e.target.value)}>
                <option value="">Select Configured Equipment...</option>
                {equipment.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.equipment_name} ({e.equipment_code}) [{e.min_temp_c}°C to {e.max_temp_c}°C]
                  </option>
                ))}
              </Select>
              <div className="grid gap-2 sm:grid-cols-2">
                <Input type="number" step="0.1" value={logTemp} onChange={(e) => setLogTemp(e.target.value)} placeholder="Observed Temp (°C)" />
                <Input value={logNotes} onChange={(e) => setLogNotes(e.target.value)} placeholder="Notes / corrective action..." />
              </div>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy || !logEqId || logTemp === ""}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const res = await api.post("/food-safety/temperatures", {
                      equipment_id: logEqId,
                      recorded_temp_c: Number(logTemp),
                      notes: logNotes || null,
                    });
                    setLogTemp("");
                    setLogNotes("");
                    pushToast(
                      res.data.is_violation
                        ? "Temperature VIOLATION logged and critical alert dispatched!"
                        : "Temperature reading within configured range",
                      res.data.is_violation ? "error" : "success"
                    );
                    refetchTemps();
                    refetchDash();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Record Temperature
              </Button>
            </Card>
          </div>

          <Card className="p-4 space-y-2">
            <h3 className="font-bold text-slate-900 text-sm">Recent Temperature Readings ({tempLogs.length})</h3>
            {tempLogs.map((l) => (
              <div key={l.id} className="rounded-xl border border-slate-200 p-2.5 text-xs flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-bold">{l.equipment_name}</span> ({l.equipment_code}):{" "}
                  <span className="font-mono font-bold">{l.recorded_temp_c}°C</span>{" "}
                  <span className="text-slate-500">
                    (Allowed {l.min_allowed_c}°C – {l.max_allowed_c}°C)
                  </span>
                </div>
                <Badge tone={l.is_violation ? "red" : "green"}>{l.is_violation ? "VIOLATION" : "SAFE"}</Badge>
              </div>
            ))}
          </Card>
        </div>
      )}

      {tab === "expiry" && expiry && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4 border-red-200 space-y-2">
            <div className="flex items-center gap-2 font-bold text-red-900">
              <AlertTriangle className="h-4 w-4" /> Expired Batches ({expiry.expired_count})
            </div>
            {(expiry.expired_batches || []).length === 0 ? (
              <div className="text-xs text-slate-500">No expired batches with remaining stock.</div>
            ) : (
              expiry.expired_batches.map((b: any) => (
                <div key={b.batch_id} className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs flex items-center justify-between gap-2">
                  <div>
                    <div className="font-bold text-red-900">{b.ingredient_name} • {b.batch_number}</div>
                    <div className="text-red-700">
                      Remaining: {b.remaining_quantity} {b.unit} • Expired: {b.expiry_date}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      try {
                        await api.post(`/food-safety/batches/${b.batch_id}/dispose`, {
                          reason: "Expired batch safely disposed via Food Safety compliance monitor",
                        });
                        pushToast("Expired batch disposed & logged as wastage", "info");
                        refetchExpiry();
                        refetchDash();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Dispose
                  </Button>
                </div>
              ))
            )}
          </Card>

          <Card className="p-4 border-amber-200 space-y-2">
            <div className="flex items-center gap-2 font-bold text-amber-900">
              <Flame className="h-4 w-4" /> Approaching Expiry ≤7d ({expiry.approaching_expiry_count})
            </div>
            {(expiry.approaching_expiry_batches || []).length === 0 ? (
              <div className="text-xs text-slate-500">No batches expiring within 7 days.</div>
            ) : (
              expiry.approaching_expiry_batches.map((b: any) => (
                <div key={b.batch_id} className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs">
                  <div className="font-bold text-amber-900">{b.ingredient_name} • {b.batch_number}</div>
                  <div className="text-amber-800">
                    {b.remaining_quantity} {b.unit} • Expires {b.expiry_date} ({b.days_remaining}d left)
                  </div>
                </div>
              ))
            )}
          </Card>
        </div>
      )}

      {tab === "cleaning" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4 space-y-3">
            <div className="flex items-center gap-2 font-bold text-slate-900">
              <Sparkles className="h-4 w-4 text-emerald-700" /> Add Cleaning Schedule
            </div>
            <Input value={cleanArea} onChange={(e) => setCleanArea(e.target.value)} placeholder="Area (e.g., Main Prep Counter & Sinks)" />
            <Select value={cleanFreq} onChange={(e) => setCleanFreq(e.target.value)}>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </Select>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="primary"
                disabled={busy || !cleanArea.trim()}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api.post("/food-safety/cleaning/schedules", {
                      canteen_id: activeId,
                      area_name: cleanArea.trim(),
                      frequency: cleanFreq,
                    });
                    setCleanArea("");
                    pushToast("Cleaning schedule created", "success");
                    refetchCleaning();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Create Schedule
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    const res = await api.post(`/food-safety/cleaning/notify-overdue?canteen_id=${activeId}`);
                    pushToast(`Dispatched ${res.data.reminders_dispatched} overdue cleaning reminder(s)`, "info");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Notify Overdue Tasks
              </Button>
            </div>
          </Card>

          <Card className="p-4 space-y-2">
            <h3 className="font-bold text-slate-900 text-sm">
              Sanitation Tasks ({cleaning?.tasks?.length ?? 0} • {cleaning?.overdue_count ?? 0} Overdue)
            </h3>
            {(cleaning?.tasks || []).map((t: any) => (
              <div key={t.id} className="rounded-xl border border-slate-200 p-2.5 text-xs flex items-center justify-between gap-2">
                <div>
                  <div className="font-bold text-slate-900">{t.area_name} ({t.frequency})</div>
                  <div className="text-slate-500">Due: {t.due_at ? new Date(t.due_at).toLocaleString() : "-"}</div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={t.status === "completed" ? "green" : t.is_overdue ? "red" : "amber"}>
                    {t.is_overdue && t.status !== "completed" ? "OVERDUE" : t.status.toUpperCase()}
                  </Badge>
                  {t.status !== "completed" && (
                    <Button
                      size="sm"
                      variant="success"
                      onClick={async () => {
                        try {
                          await api.patch(`/food-safety/cleaning/tasks/${t.id}`, { status: "completed", notes: "Sanitized & verified" });
                          pushToast("Cleaning task completed", "success");
                          refetchCleaning();
                          refetchDash();
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" /> Complete
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </Card>
        </div>
      )}

      {tab === "incidents" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4 space-y-3">
            <h3 className="font-bold text-slate-900">Report Food Safety Incident</h3>
            <Input value={incTitle} onChange={(e) => setIncTitle(e.target.value)} placeholder="Incident Title" />
            <textarea
              value={incDesc}
              onChange={(e) => setIncDesc(e.target.value)}
              rows={3}
              placeholder="Detailed incident observations..."
              className="w-full rounded-xl border border-slate-300 p-2 text-sm"
            />
            <Select value={incSeverity} onChange={(e) => setIncSeverity(e.target.value)}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </Select>
            <Button
              size="sm"
              variant="danger"
              disabled={busy || incTitle.trim().length < 3 || incDesc.trim().length < 5}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.post("/food-safety/incidents", {
                    canteen_id: activeId,
                    title: incTitle.trim(),
                    description: incDesc.trim(),
                    severity: incSeverity,
                  });
                  setIncTitle("");
                  setIncDesc("");
                  pushToast("Food safety incident reported", "info");
                  refetchIncidents();
                  refetchDash();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Report Incident
            </Button>
          </Card>

          <Card className="p-4 space-y-2">
            <h3 className="font-bold text-slate-900">Incident Register ({incidents.length})</h3>
            {incidents.map((inc) => (
              <div key={inc.id} className="rounded-xl border border-slate-200 p-3 text-xs space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-bold text-slate-900">{inc.incident_number} — {inc.title}</div>
                  <div className="flex gap-1">
                    <Badge tone={inc.severity === "critical" || inc.severity === "high" ? "red" : "amber"}>{inc.severity}</Badge>
                    <Badge tone={inc.status === "resolved" || inc.status === "closed" ? "green" : "blue"}>{inc.status}</Badge>
                  </div>
                </div>
                <div className="text-slate-600">{inc.description}</div>
                {inc.status !== "resolved" && inc.status !== "closed" && (
                  <Button
                    size="sm"
                    variant="success"
                    onClick={async () => {
                      try {
                        await api.patch(`/food-safety/incidents/${inc.id}`, {
                          status: "resolved",
                          corrective_action: "Corrective sanitation & verification completed",
                        });
                        pushToast("Incident marked resolved", "success");
                        refetchIncidents();
                        refetchDash();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Mark Resolved
                  </Button>
                )}
              </div>
            ))}
          </Card>
        </div>
      )}
    </div>
  );
};
