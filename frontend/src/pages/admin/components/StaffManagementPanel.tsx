import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, Calendar, Edit3, Users } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../../components/ui/Primitives";

export const StaffTab: React.FC<{ activeCanteenId: string; staffList: any[]; refetchStaff: () => void }> = ({
  activeCanteenId,
  staffList,
  refetchStaff,
}) => {
  const { pushToast } = useToast();
  const todayStr = new Date().toISOString().slice(0, 10);

  const { data: dashboard, refetch: refetchDash } = useQuery<any>({
    queryKey: ["staff-dashboard-kpis", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/staff/dashboard?canteen_id=${activeCanteenId}`)).data,
  });
  const { data: tasks = [], refetch: refetchTasks } = useQuery<any[]>({
    queryKey: ["admin-staff-tasks", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/staff/tasks?canteen_id=${activeCanteenId}`)).data,
  });
  const { data: shifts = [], refetch: refetchShifts } = useQuery<any[]>({
    queryKey: ["admin-staff-shifts", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/staff/shifts?canteen_id=${activeCanteenId}`)).data,
  });
  const { data: weeklySchedules = [], refetch: refetchWeekly } = useQuery<any[]>({
    queryKey: ["admin-staff-weekly", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/staff/weekly-schedules?canteen_id=${activeCanteenId}`)).data,
  });
  const { data: attendance = [], refetch: refetchAttendance } = useQuery<any[]>({
    queryKey: ["admin-staff-attendance", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/staff/attendance?canteen_id=${activeCanteenId}`)).data,
  });
  const { data: workload } = useQuery<any>({
    queryKey: ["staff-workload-report", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/staff/workload?canteen_id=${activeCanteenId}`)).data,
  });
  const { data: activityLogs = [] } = useQuery<any[]>({
    queryKey: ["staff-activity-logs", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/staff/activity?canteen_id=${activeCanteenId}&limit=40`)).data,
  });
  const { data: canteenDetail } = useQuery<any>({
    queryKey: ["staff-canteen-detail", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/canteens/${activeCanteenId}`)).data,
  });

  const counters = canteenDetail?.counters || [];
  const kitchens = canteenDetail?.kitchens || [];

  const [newStaffName, setNewStaffName] = useState("");
  const [newStaffEmail, setNewStaffEmail] = useState("");
  const [newStaffPhone, setNewStaffPhone] = useState("");
  const [newStaffEmp, setNewStaffEmp] = useState("");
  const [newStaffRole, setNewStaffRole] = useState("cashier");

  const [editTarget, setEditTarget] = useState<any | null>(null);
  const [editFullName, setEditFullName] = useState("");
  const [editPhone, setEditPhone] = useState("");
  const [editDesignation, setEditDesignation] = useState("");
  const [editCounterId, setEditCounterId] = useState("");
  const [editKitchenId, setEditKitchenId] = useState("");
  const [editAvailStatus, setEditAvailStatus] = useState("available");
  const [editWeeklyHours, setEditWeeklyHours] = useState("48");
  const [editIsActive, setEditIsActive] = useState(true);

  const [taskTitle, setTaskTitle] = useState("");
  const [taskAssignee, setTaskAssignee] = useState("");
  const [taskUrgent, setTaskUrgent] = useState(false);

  const [shiftUserId, setShiftUserId] = useState("");
  const [shiftDate, setShiftDate] = useState(todayStr);
  const [shiftStart, setShiftStart] = useState("08:00");
  const [shiftEnd, setShiftEnd] = useState("16:00");
  const [shiftType, setShiftType] = useState("regular");
  const [shiftCounterId, setShiftCounterId] = useState("");

  const [wkUserId, setWkUserId] = useState("");
  const [wkDay, setWkDay] = useState("0");
  const [wkStart, setWkStart] = useState("08:00");
  const [wkEnd, setWkEnd] = useState("16:00");
  const [wkType, setWkType] = useState("regular");
  const [genWeekDate, setGenWeekDate] = useState(todayStr);

  const [leaveUserId, setLeaveUserId] = useState("");
  const [leaveDate, setLeaveDate] = useState(todayStr);
  const [leaveStatusVal, setLeaveStatusVal] = useState<"leave" | "present" | "absent">("leave");
  const [leaveReason, setLeaveReason] = useState("");

  const staffNameById = (uid?: string) => staffList.find((s) => s.user_id === uid)?.full_name || uid?.slice(0, 8) || "Staff";
  const workloadRows = workload?.staff_metrics || [];

  return (
    <div className="space-y-6">
      {/* KPI Dashboard Cards */}
      <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
        <Card className="p-3.5">
          <div className="text-[11px] font-bold uppercase text-slate-400">Total Staff</div>
          <div className="text-xl font-black text-slate-900">{dashboard?.total_staff ?? staffList.length}</div>
          <div className="text-[11px] text-slate-500">{dashboard?.active_staff ?? 0} active</div>
        </Card>
        <Card className="p-3.5 border-emerald-200 bg-emerald-50/40">
          <div className="text-[11px] font-bold uppercase text-emerald-700">On Duty Now</div>
          <div className="text-xl font-black text-emerald-900">{dashboard?.on_duty_now ?? 0}</div>
          <div className="text-[11px] text-emerald-700">{dashboard?.present_today ?? 0} checked in today</div>
        </Card>
        <Card className="p-3.5 border-amber-200 bg-amber-50/40">
          <div className="text-[11px] font-bold uppercase text-amber-800">On Leave / Pending</div>
          <div className="text-xl font-black text-amber-900">{dashboard?.on_leave_today ?? 0}</div>
          <div className="text-[11px] text-amber-700">{dashboard?.pending_leave_requests ?? 0} pending review</div>
        </Card>
        <Card className="p-3.5">
          <div className="text-[11px] font-bold uppercase text-slate-400">Shifts Today</div>
          <div className="text-xl font-black text-slate-900">{dashboard?.scheduled_shifts_today ?? 0}</div>
          <div className="text-[11px] text-slate-500">{weeklySchedules.length} weekly rules</div>
        </Card>
        <Card className="p-3.5 border-red-200 bg-red-50/40">
          <div className="text-[11px] font-bold uppercase text-red-700">Open Tasks</div>
          <div className="text-xl font-black text-red-900">{dashboard?.open_tasks ?? 0}</div>
          <div className="text-[11px] text-red-700">{dashboard?.urgent_tasks ?? 0} urgent</div>
        </Card>
        <Card className="p-3.5">
          <div className="text-[11px] font-bold uppercase text-slate-400">Actions Logged</div>
          <div className="text-xl font-black text-slate-900">{activityLogs.length}</div>
          <div className="text-[11px] text-slate-500">Recent canteen activity</div>
        </Card>
      </div>

      {/* Directory + Create & Tasks */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-bold text-slate-900 flex items-center gap-2">
              <Users className="h-4 w-4 text-[#76010d]" /> Staff Directory ({staffList.length})
            </h2>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    await api.post(`/staff/attendance/check-in?canteen_id=${activeCanteenId}`);
                    pushToast("Checked in", "success");
                    refetchStaff();
                    refetchAttendance();
                    refetchDash();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                My Check-in
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    await api.post("/staff/attendance/check-out");
                    pushToast("Checked out", "info");
                    refetchStaff();
                    refetchAttendance();
                    refetchDash();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Check-out
              </Button>
            </div>
          </div>
          <div className="space-y-2 max-h-[380px] overflow-y-auto">
            {staffList.map((s) => (
              <div key={s.user_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 p-3 text-xs">
                <div>
                  <div className="font-bold text-slate-900 flex items-center gap-1.5">
                    <span>{s.full_name} ({s.employee_code})</span>
                    {!s.is_active && <Badge tone="red">Inactive</Badge>}
                  </div>
                  <div className="text-slate-500">
                    {s.designation} • {s.email} {s.phone ? `• ${s.phone}` : ""}
                  </div>
                  <div className="text-[10px] text-slate-400">
                    Roles: {(s.roles || []).join(", ") || "staff"} • Avail: {s.availability_status || "available"}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <Badge tone={s.is_on_duty ? "green" : "slate"}>{s.is_on_duty ? "On Duty" : "Off Duty"}</Badge>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditTarget(s);
                      setEditFullName(s.full_name || "");
                      setEditPhone(s.phone || "");
                      setEditDesignation(s.designation || "");
                      setEditCounterId(s.assigned_counter_id || "");
                      setEditKitchenId(s.assigned_kitchen_id || "");
                      setEditAvailStatus(s.availability_status || "available");
                      setEditWeeklyHours(String(s.weekly_hours_target || 48));
                      setEditIsActive(Boolean(s.is_active));
                    }}
                  >
                    <Edit3 className="h-3 w-3" /> Edit
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <div className="space-y-5">
          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900">Create Staff Member</h2>
            <div className="grid grid-cols-2 gap-2">
              <Input value={newStaffName} onChange={(e) => setNewStaffName(e.target.value)} placeholder="Full Name" />
              <Input value={newStaffEmp} onChange={(e) => setNewStaffEmp(e.target.value)} placeholder="Emp Code (EMP-201)" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input value={newStaffEmail} onChange={(e) => setNewStaffEmail(e.target.value)} placeholder="Email" />
              <Input value={newStaffPhone} onChange={(e) => setNewStaffPhone(e.target.value)} placeholder="Phone (optional)" />
            </div>
            <Select value={newStaffRole} onChange={(e) => setNewStaffRole(e.target.value)}>
              <option value="cashier">Cashier</option>
              <option value="kitchen_staff">Kitchen Staff</option>
              <option value="pickup_staff">Pickup Staff</option>
              <option value="inventory_manager">Inventory Manager</option>
              <option value="canteen_manager">Canteen Manager</option>
            </Select>
            <Button
              onClick={async () => {
                try {
                  await api.post("/admin/users/staff", {
                    full_name: newStaffName,
                    email: newStaffEmail,
                    phone: newStaffPhone.trim() || null,
                    password: "StaffUser@123",
                    employee_code: newStaffEmp,
                    designation: newStaffRole.replace("_", " "),
                    role_names: [newStaffRole],
                    assigned_canteen_id: activeCanteenId,
                  });
                  setNewStaffName("");
                  setNewStaffEmail("");
                  setNewStaffPhone("");
                  setNewStaffEmp("");
                  pushToast("Staff user created", "success");
                  refetchStaff();
                  refetchDash();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Staff Account
            </Button>
          </Card>

          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900">Assign Staff Task ({tasks.length})</h2>
            <div className="flex flex-wrap gap-2">
              <Input value={taskTitle} onChange={(e) => setTaskTitle(e.target.value)} placeholder="Task title" className="flex-1" />
              <Select value={taskAssignee} onChange={(e) => setTaskAssignee(e.target.value)} className="w-40">
                <option value="">Any Staff</option>
                {staffList.map((s) => (
                  <option key={s.user_id} value={s.user_id}>
                    {s.full_name}
                  </option>
                ))}
              </Select>
              <label className="inline-flex items-center gap-1 text-xs font-semibold">
                <input type="checkbox" checked={taskUrgent} onChange={(e) => setTaskUrgent(e.target.checked)} />
                Urgent
              </label>
              <Button
                size="sm"
                onClick={async () => {
                  if (!taskTitle.trim()) return;
                  try {
                    await api.post("/staff/tasks", {
                      canteen_id: activeCanteenId,
                      assigned_to_user_id: taskAssignee || null,
                      title: taskTitle,
                      priority: taskUrgent ? "high" : "normal",
                      is_urgent: taskUrgent,
                    });
                    setTaskTitle("");
                    setTaskUrgent(false);
                    refetchTasks();
                    refetchDash();
                    pushToast("Task assigned", "success");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Assign
              </Button>
            </div>
            <div className="space-y-1.5 max-h-36 overflow-y-auto text-xs">
              {tasks.map((t) => (
                <div key={t.id} className="flex items-center justify-between border-b border-slate-100 py-1.5">
                  <span>
                    <strong className="text-slate-900">{t.title}</strong>
                    {t.assigned_to_user_id ? ` • ${staffNameById(t.assigned_to_user_id)}` : ""}
                    {t.is_urgent && <Badge tone="red">Urgent</Badge>}
                  </span>
                  <Button
                    size="sm"
                    variant={t.status === "done" ? "success" : "outline"}
                    onClick={async () => {
                      try {
                        await api.patch(`/staff/tasks/${t.id}`, { status: t.status === "done" ? "pending" : "done" });
                        refetchTasks();
                        refetchDash();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    {t.status}
                  </Button>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* Weekly Duty Schedules + Shifts + Attendance & Leave */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-bold text-slate-900 flex items-center gap-2">
              <Calendar className="h-4 w-4 text-[#76010d]" /> Weekly Duty Roster ({weeklySchedules.length})
            </h2>
            <div className="flex items-center gap-1.5 text-xs">
              <Input type="date" value={genWeekDate} onChange={(e) => setGenWeekDate(e.target.value)} className="w-36" />
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    const res = await api.post("/staff/weekly-schedules/generate-week", {
                      canteen_id: activeCanteenId,
                      week_start_date: genWeekDate,
                    });
                    pushToast(`Generated ${res.data.created} shifts (${res.data.skipped_existing} skipped)`, "success");
                    refetchShifts();
                    refetchDash();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Generate Week
              </Button>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
            <Select value={wkUserId || staffList[0]?.user_id || ""} onChange={(e) => setWkUserId(e.target.value)}>
              {staffList.map((s) => (
                <option key={s.user_id} value={s.user_id}>
                  {s.full_name}
                </option>
              ))}
            </Select>
            <Select value={wkDay} onChange={(e) => setWkDay(e.target.value)}>
              {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, i) => (
                <option key={d} value={String(i)}>
                  {d}
                </option>
              ))}
            </Select>
            <Input type="time" value={wkStart} onChange={(e) => setWkStart(e.target.value)} />
            <Input type="time" value={wkEnd} onChange={(e) => setWkEnd(e.target.value)} />
          </div>
          <div className="flex gap-2 text-xs">
            <Select value={wkType} onChange={(e) => setWkType(e.target.value)} className="w-36">
              <option value="regular">Regular</option>
              <option value="morning">Morning</option>
              <option value="afternoon">Afternoon</option>
              <option value="evening">Evening</option>
              <option value="cashier">Cashier</option>
              <option value="kitchen">Kitchen</option>
              <option value="pickup">Pickup</option>
            </Select>
            <Button
              size="sm"
              onClick={async () => {
                const uid = wkUserId || staffList[0]?.user_id;
                if (!uid) return pushToast("Select a staff member first", "error");
                try {
                  await api.post("/staff/weekly-schedules", {
                    staff_user_id: uid,
                    canteen_id: activeCanteenId,
                    day_of_week: Number(wkDay),
                    start_time: `${wkStart}:00`,
                    end_time: `${wkEnd}:00`,
                    shift_type: wkType,
                  });
                  pushToast("Weekly rule saved", "success");
                  refetchWeekly();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Weekly Rule
            </Button>
          </div>

          <div className="space-y-1 max-h-36 overflow-y-auto text-xs border-b border-slate-100 pb-2">
            {weeklySchedules.map((w: any) => (
              <div key={w.id} className="flex items-center justify-between py-1">
                <span>
                  <strong>{w.day_name}</strong> • {w.staff_name} ({w.start_time.slice(0, 5)}–{w.end_time.slice(0, 5)}, {w.shift_type})
                </span>
                <button
                  type="button"
                  onClick={async () => {
                    await api.delete(`/staff/weekly-schedules/${w.id}`);
                    refetchWeekly();
                  }}
                  className="text-red-600 font-bold"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>

          <h3 className="text-xs font-bold uppercase text-slate-500 pt-1">Single-Day Shift Scheduling ({shifts.length})</h3>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <Select value={shiftUserId} onChange={(e) => setShiftUserId(e.target.value)}>
              <option value="">Select Staff Member</option>
              {staffList.map((s) => (
                <option key={s.user_id} value={s.user_id}>
                  {s.full_name}
                </option>
              ))}
            </Select>
            <Input type="date" value={shiftDate} onChange={(e) => setShiftDate(e.target.value)} />
            <Input type="time" value={shiftStart} onChange={(e) => setShiftStart(e.target.value)} />
            <Input type="time" value={shiftEnd} onChange={(e) => setShiftEnd(e.target.value)} />
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <Select value={shiftType} onChange={(e) => setShiftType(e.target.value)} className="w-32">
              <option value="regular">Regular</option>
              <option value="morning">Morning</option>
              <option value="afternoon">Afternoon</option>
              <option value="evening">Evening</option>
              <option value="cashier">Cashier</option>
            </Select>
            {counters.length > 0 && (
              <Select value={shiftCounterId} onChange={(e) => setShiftCounterId(e.target.value)} className="w-40">
                <option value="">Any Counter</option>
                {counters.map((c: any) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            )}
            <Button
              size="sm"
              onClick={async () => {
                try {
                  const uid = shiftUserId || staffList[0]?.user_id;
                  if (!uid) return pushToast("No staff found", "error");
                  await api.post("/staff/shifts", {
                    staff_user_id: uid,
                    canteen_id: activeCanteenId,
                    counter_id: shiftCounterId || null,
                    shift_date: shiftDate,
                    start_time: `${shiftStart}:00`,
                    end_time: `${shiftEnd}:00`,
                    shift_type: shiftType,
                  });
                  pushToast("Shift scheduled", "success");
                  refetchShifts();
                  refetchDash();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Schedule Shift
            </Button>
          </div>
          <div className="space-y-1.5 max-h-36 overflow-y-auto text-xs">
            {shifts.slice(0, 15).map((sh) => (
              <div key={sh.id} className="flex items-center justify-between border-b border-slate-100 py-1.5">
                <span>
                  <strong>{staffNameById(sh.staff_user_id)}</strong> • {sh.shift_date} ({String(sh.start_time).slice(0, 5)}–{String(sh.end_time).slice(0, 5)}){" "}
                  <Badge tone="slate">{sh.status}</Badge>
                </span>
                {sh.status !== "open" && (
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await api.delete(`/staff/shifts/${sh.id}`);
                        refetchShifts();
                        pushToast("Shift removed", "info");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                    className="text-red-600 font-bold hover:underline"
                  >
                    Delete
                  </button>
                )}
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900">Attendance &amp; Leave Approvals ({attendance.length})</h2>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <Select value={leaveUserId} onChange={(e) => setLeaveUserId(e.target.value)}>
              <option value="">Select Staff</option>
              {staffList.map((s) => (
                <option key={s.user_id} value={s.user_id}>
                  {s.full_name}
                </option>
              ))}
            </Select>
            <Input type="date" value={leaveDate} onChange={(e) => setLeaveDate(e.target.value)} />
            <Select value={leaveStatusVal} onChange={(e) => setLeaveStatusVal(e.target.value as any)}>
              <option value="leave">Mark Leave</option>
              <option value="present">Mark Present</option>
              <option value="absent">Mark Absent</option>
            </Select>
          </div>
          <div className="flex gap-2">
            <Input value={leaveReason} onChange={(e) => setLeaveReason(e.target.value)} placeholder="Notes / Leave reason..." />
            <Button
              size="sm"
              onClick={async () => {
                try {
                  const uid = leaveUserId || staffList[0]?.user_id;
                  if (!uid) return pushToast("Select staff first", "error");
                  await api.post("/staff/attendance/manual", {
                    staff_user_id: uid,
                    canteen_id: activeCanteenId,
                    attendance_date: leaveDate,
                    status: leaveStatusVal,
                    notes: leaveReason || `Manager marked ${leaveStatusVal}`,
                  });
                  setLeaveReason("");
                  refetchAttendance();
                  refetchDash();
                  pushToast("Attendance saved", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Save Record
            </Button>
          </div>
          <div className="space-y-1.5 max-h-72 overflow-y-auto text-xs">
            {attendance.map((att) => (
              <div key={att.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 py-2">
                <div>
                  <div>
                    <strong>{staffNameById(att.staff_user_id)}</strong> • {att.attendance_date}
                    {att.end_date && att.end_date !== att.attendance_date ? ` → ${att.end_date}` : ""} •{" "}
                    <Badge tone={att.status === "present" ? "green" : att.status === "leave_pending" ? "amber" : "slate"}>
                      {att.status}
                    </Badge>
                    {att.worked_minutes != null && <span className="ml-1 text-[10px] font-bold text-emerald-700">({att.worked_minutes}m worked)</span>}
                  </div>
                  {att.leave_reason && <div className="text-[11px] text-slate-600">Reason ({att.leave_type || "leave"}): {att.leave_reason}</div>}
                </div>
                {att.status === "leave_pending" && (
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant="success"
                      onClick={async () => {
                        try {
                          await api.patch(`/staff/attendance/${att.id}/review`, { approved: true });
                          refetchAttendance();
                          refetchDash();
                          pushToast("Leave approved", "success");
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={async () => {
                        try {
                          await api.patch(`/staff/attendance/${att.id}/review`, { approved: false });
                          refetchAttendance();
                          refetchDash();
                          pushToast("Leave rejected", "info");
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
            ))}
          </div>
        </Card>
      </div>

      {/* Workload Distribution & Performance + Activity Log */}
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2 space-y-4">
          <h2 className="font-bold text-slate-900">Staff Workload Distribution &amp; Performance (30d)</h2>
          {workloadRows.length > 0 && (
            <div className="h-52 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={workloadRows}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="full_name" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Bar dataKey="workload_score" name="Workload Ops (Orders/Handovers/Tasks)" fill="#76010d" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="overflow-x-auto max-h-56 overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-[11px] uppercase text-slate-400">
                  <th className="py-1.5">Staff</th>
                  <th>Present / Leave</th>
                  <th>Hours</th>
                  <th>Tasks</th>
                  <th>KDS / POS / Handover</th>
                </tr>
              </thead>
              <tbody>
                {workloadRows.map((m: any) => (
                  <tr key={m.user_id} className="border-b border-slate-100">
                    <td className="py-2 font-bold text-slate-900">{m.full_name}</td>
                    <td>{m.present_days}d / {m.leave_days}d</td>
                    <td>{m.worked_hours}h</td>
                    <td>{m.tasks_completed}/{m.tasks_total} ({m.task_completion_rate}%)</td>
                    <td>{m.orders_assigned_kds} / {m.pos_payments_processed} / {m.orders_handed_over}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <Activity className="h-4 w-4 text-[#76010d]" /> Staff Activity Feed ({activityLogs.length})
          </h2>
          <div className="space-y-1.5 max-h-80 overflow-y-auto text-xs">
            {activityLogs.length === 0 ? (
              <div className="text-slate-500">No staff activity recorded yet.</div>
            ) : (
              activityLogs.map((log: any) => (
                <div key={log.id} className="rounded-lg border border-slate-100 px-3 py-2">
                  <div className="font-bold text-slate-900">{log.user_name}</div>
                  <div className="text-slate-700">{log.description}</div>
                  <div className="text-[10px] text-slate-400">{log.activity_type} • {log.created_at?.slice(0, 16)}</div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Edit Staff Modal */}
      <Modal
        open={Boolean(editTarget)}
        onClose={() => setEditTarget(null)}
        title={`Edit Staff Profile • ${editTarget?.full_name || ""}`}
      >
        {editTarget && (
          <div className="space-y-3 text-xs">
            <div>
              <label className="mb-1 block font-bold text-slate-600">Full Name</label>
              <Input value={editFullName} onChange={(e) => setEditFullName(e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block font-bold text-slate-600">Phone</label>
                <Input value={editPhone} onChange={(e) => setEditPhone(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block font-bold text-slate-600">Designation</label>
                <Input value={editDesignation} onChange={(e) => setEditDesignation(e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block font-bold text-slate-600">Assigned Counter</label>
                <Select value={editCounterId} onChange={(e) => setEditCounterId(e.target.value)}>
                  <option value="">None</option>
                  {counters.map((c: any) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <label className="mb-1 block font-bold text-slate-600">Assigned Kitchen</label>
                <Select value={editKitchenId} onChange={(e) => setEditKitchenId(e.target.value)}>
                  <option value="">None</option>
                  {kitchens.map((k: any) => (
                    <option key={k.id} value={k.id}>
                      {k.name}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block font-bold text-slate-600">Availability Status</label>
                <Select value={editAvailStatus} onChange={(e) => setEditAvailStatus(e.target.value)}>
                  <option value="available">Available</option>
                  <option value="busy">Busy</option>
                  <option value="on_break">On Break</option>
                  <option value="off_duty">Off Duty</option>
                  <option value="on_leave">On Leave</option>
                </Select>
              </div>
              <div>
                <label className="mb-1 block font-bold text-slate-600">Weekly Hours Target</label>
                <Input type="number" min="1" max="84" value={editWeeklyHours} onChange={(e) => setEditWeeklyHours(e.target.value)} />
              </div>
            </div>
            <label className="flex items-center gap-2 font-semibold">
              <input type="checkbox" checked={editIsActive} onChange={(e) => setEditIsActive(e.target.checked)} />
              Account Active
            </label>
            <Button
              className="w-full"
              onClick={async () => {
                try {
                  await api.patch(`/staff/${editTarget.user_id}`, {
                    full_name: editFullName,
                    phone: editPhone || null,
                    designation: editDesignation,
                    assigned_counter_id: editCounterId || null,
                    assigned_kitchen_id: editKitchenId || null,
                    availability_status: editAvailStatus,
                    weekly_hours_target: Number(editWeeklyHours) || 48,
                    is_active: editIsActive,
                  });
                  pushToast("Staff profile updated", "success");
                  setEditTarget(null);
                  refetchStaff();
                  refetchDash();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Save Changes
            </Button>
          </div>
        )}
      </Modal>
    </div>
  );
};
