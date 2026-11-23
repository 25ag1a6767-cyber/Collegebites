import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calendar, CheckCircle2, Clock, LogIn, LogOut, ShieldCheck, UserCheck } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen } from "../../types";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";

export const StaffPortalPage: React.FC = () => {
  const { user } = useAppStore();
  const { pushToast } = useToast();

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [selectedCanteen, setSelectedCanteen] = useState(user?.assigned_canteen_id || "");
  const effectiveCanteenId = user?.assigned_canteen_id || selectedCanteen || canteens[0]?.id || "";

  const { data: overview, refetch } = useQuery<any>({
    queryKey: ["staff-my-overview"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/staff/me/overview")).data,
    refetchInterval: 20000,
  });

  const [leaveDate, setLeaveDate] = useState(new Date().toISOString().slice(0, 10));
  const [leaveEndDate, setLeaveEndDate] = useState(new Date().toISOString().slice(0, 10));
  const [leaveType, setLeaveType] = useState("casual");
  const [leaveReason, setLeaveReason] = useState("");
  const [busy, setBusy] = useState(false);

  const profile = overview?.profile;
  const todayAtt = overview?.today_attendance;
  const isCheckedIn = Boolean(todayAtt?.status === "present" && todayAtt?.check_in_at && !todayAtt?.check_out_at);

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-[#380106] p-5 text-white">
        <div className="flex items-center gap-3">
          <BrandLogo size="md" variant="dark" />
          <div>
            <h1 className="text-xl font-extrabold">Staff Self-Service Workspace</h1>
            <p className="text-xs text-[#fdedce]/80">
              {profile?.full_name || user?.full_name} • {profile?.employee_code || "STAFF"} • {profile?.designation || (user?.roles || []).join(", ")}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!user?.assigned_canteen_id && canteens.length > 0 && (
            <Select
              value={effectiveCanteenId}
              onChange={(e) => setSelectedCanteen(e.target.value)}
              className="w-48 bg-slate-800 border-slate-700 text-white"
            >
              {canteens.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}
          <Select
            value={profile?.availability_status || "available"}
            onChange={async (e) => {
              try {
                await api.patch("/staff/me/availability", { availability_status: e.target.value });
                pushToast(`Availability updated to ${e.target.value.replace("_", " ")}`, "success");
                refetch();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
            className="w-40 bg-slate-800 border-slate-700 text-white"
            aria-label="Availability Status"
          >
            <option value="available">Available</option>
            <option value="busy">Busy</option>
            <option value="on_break">On Break</option>
            <option value="off_duty">Off Duty</option>
          </Select>
          {!isCheckedIn ? (
            <Button
              size="sm"
              variant="success"
              disabled={!effectiveCanteenId || busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.post(`/staff/attendance/check-in?canteen_id=${effectiveCanteenId}`);
                  pushToast("Checked in for duty!", "success");
                  refetch();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              <LogIn className="h-3.5 w-3.5" /> Check In
            </Button>
          ) : (
            <Button
              size="sm"
              variant="danger"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.post("/staff/attendance/check-out");
                  pushToast("Checked out cleanly", "info");
                  refetch();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              <LogOut className="h-3.5 w-3.5" /> Check Out
            </Button>
          )}
        </div>
      </div>

      {/* Status KPIs */}
      <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase text-slate-400">Duty Status</div>
          <div className="mt-1 flex items-center gap-2">
            <Badge tone={profile?.is_on_duty ? "green" : "slate"}>{profile?.is_on_duty ? "ON DUTY" : "OFF DUTY"}</Badge>
            <Badge tone="amber">{String(profile?.availability_status || "available").toUpperCase()}</Badge>
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            {todayAtt?.check_in_at ? `In: ${new Date(todayAtt.check_in_at).toLocaleTimeString()}` : "Not checked in today"}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase text-slate-400">Assigned Shifts</div>
          <div className="text-2xl font-black text-slate-900">{overview?.upcoming_shifts?.length ?? 0}</div>
          <div className="text-[11px] text-slate-500">Target {profile?.weekly_hours_target ?? 48}h / week</div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase text-slate-400">Open Tasks</div>
          <div className="text-2xl font-black text-[#76010d]">
            {(overview?.tasks || []).filter((t: any) => t.status !== "done").length}
          </div>
          <div className="text-[11px] text-slate-500">{overview?.tasks?.length ?? 0} total assigned</div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase text-slate-400">Granted Permissions</div>
          <div className="text-2xl font-black text-slate-900">{user?.permissions?.length ?? 0}</div>
          <div className="text-[11px] text-slate-500 flex items-center gap-1">
            <ShieldCheck className="h-3 w-3 text-emerald-600" /> Active RBAC scope
          </div>
        </Card>
      </div>

      {/* Weekly Roster & Upcoming Shifts */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <Calendar className="h-4 w-4 text-[#76010d]" /> My Weekly Duty Schedule &amp; Shifts
          </h2>
          {overview?.weekly_schedules?.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
              {overview.weekly_schedules.map((ws: any) => (
                <div key={ws.id} className="rounded-xl border border-slate-200 bg-slate-50 p-2.5">
                  <div className="font-bold text-slate-900">{ws.day_name} • {ws.shift_type}</div>
                  <div className="text-[11px] text-slate-600">
                    {ws.start_time.slice(0, 5)} – {ws.end_time.slice(0, 5)}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="space-y-1.5 max-h-56 overflow-y-auto text-xs border-t border-slate-100 pt-2">
            <div className="text-[11px] font-bold uppercase text-slate-400">Upcoming Scheduled Shifts</div>
            {(!overview?.upcoming_shifts || overview.upcoming_shifts.length === 0) ? (
              <div className="text-slate-500">No upcoming concrete shifts scheduled yet.</div>
            ) : (
              overview.upcoming_shifts.map((s: any) => (
                <div key={s.id} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2">
                  <span>
                    <strong>{s.shift_date}</strong> • {String(s.start_time).slice(0, 5)}–{String(s.end_time).slice(0, 5)} ({s.shift_type})
                  </span>
                  <Badge tone="slate">{s.status}</Badge>
                </div>
              ))
            )}
          </div>
        </Card>

        {/* Leave Request + Attendance History */}
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <UserCheck className="h-4 w-4 text-[#76010d]" /> Request Leave &amp; Attendance History
          </h2>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <Input type="date" value={leaveDate} onChange={(e) => setLeaveDate(e.target.value)} title="Leave Start Date" />
            <Input type="date" value={leaveEndDate} onChange={(e) => setLeaveEndDate(e.target.value)} title="Leave End Date" />
          </div>
          <div className="flex gap-2 text-xs">
            <Select value={leaveType} onChange={(e) => setLeaveType(e.target.value)} className="w-36">
              <option value="casual">Casual Leave</option>
              <option value="sick">Sick Leave</option>
              <option value="emergency">Emergency</option>
              <option value="unpaid">Unpaid Leave</option>
            </Select>
            <Input value={leaveReason} onChange={(e) => setLeaveReason(e.target.value)} placeholder="Leave reason..." className="flex-1" />
            <Button
              size="sm"
              disabled={!leaveReason.trim()}
              onClick={async () => {
                try {
                  await api.post("/staff/attendance/leave/request", {
                    canteen_id: effectiveCanteenId || null,
                    attendance_date: leaveDate,
                    end_date: leaveEndDate,
                    leave_type: leaveType,
                    reason: leaveReason,
                  });
                  setLeaveReason("");
                  pushToast("Leave request submitted for manager approval", "success");
                  refetch();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Submit
            </Button>
          </div>

          <div className="space-y-1.5 max-h-52 overflow-y-auto text-xs border-t border-slate-100 pt-2">
            {(overview?.attendance_history || []).map((a: any) => (
              <div key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-100 px-3 py-2">
                <div>
                  <span className="font-bold text-slate-900">{a.attendance_date}</span>
                  {a.end_date && a.end_date !== a.attendance_date ? ` → ${a.end_date}` : ""} •{" "}
                  <Badge tone={a.status === "present" || a.status === "leave" ? "green" : a.status === "leave_pending" ? "amber" : "red"}>
                    {a.status}
                  </Badge>
                  {a.leave_reason && <div className="text-[11px] text-slate-500">{a.leave_reason}</div>}
                </div>
                <div className="text-[11px] text-slate-500 text-right">
                  {a.check_in_at && <div>In: {new Date(a.check_in_at).toLocaleTimeString()}</div>}
                  {a.check_out_at && <div>Out: {new Date(a.check_out_at).toLocaleTimeString()}</div>}
                  {a.worked_minutes != null && <div className="font-bold text-emerald-700">{a.worked_minutes} mins</div>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Assigned Tasks & Personal Activity */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" /> Assigned Tasks ({overview?.tasks?.length ?? 0})
          </h2>
          <div className="space-y-2 max-h-60 overflow-y-auto text-xs">
            {(!overview?.tasks || overview.tasks.length === 0) ? (
              <div className="text-slate-500">No tasks assigned to you right now.</div>
            ) : (
              overview.tasks.map((t: any) => (
                <div key={t.id} className="flex items-center justify-between rounded-xl border border-slate-200 p-3">
                  <div>
                    <div className="font-bold text-slate-900">
                      {t.title} {t.is_urgent && <Badge tone="red">Urgent</Badge>}
                    </div>
                    {t.description && <div className="text-slate-500">{t.description}</div>}
                  </div>
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant={t.status === "done" ? "success" : t.status === "in_progress" ? "secondary" : "outline"}
                      onClick={async () => {
                        const next = t.status === "pending" ? "in_progress" : t.status === "in_progress" ? "done" : "pending";
                        try {
                          await api.patch(`/staff/tasks/${t.id}`, { status: next });
                          refetch();
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      {t.status}
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <Clock className="h-4 w-4 text-slate-600" /> Recent Activity Log ({overview?.activity_logs?.length ?? 0})
          </h2>
          <div className="space-y-1.5 max-h-60 overflow-y-auto text-xs">
            {(overview?.activity_logs || []).map((log: any) => (
              <div key={log.id} className="rounded-lg border border-slate-100 px-3 py-2 flex justify-between gap-2">
                <div>
                  <span className="font-semibold text-slate-900">{log.description}</span>
                  <div className="text-[10px] uppercase text-slate-400">{log.activity_type}</div>
                </div>
                <span className="text-[10px] text-slate-400 shrink-0">{log.created_at?.slice(0, 16)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
};
