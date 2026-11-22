import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calendar, Users } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

export const QueueTab: React.FC<{ activeCanteenId: string; queueDash: any; refetchQueue: () => void }> = ({
  activeCanteenId,
  queueDash,
  refetchQueue,
}) => {
  const { pushToast } = useToast();
  const [maxConcurrent, setMaxConcurrent] = useState(String(queueDash?.max_concurrent_orders || 80));
  const [slotDate, setSlotDate] = useState(new Date().toISOString().slice(0, 10));
  const [startTime, setStartTime] = useState("12:00");
  const [endTime, setEndTime] = useState("13:00");
  const [slotCap, setSlotCap] = useState("40");

  const { data: pickupSlots = [], refetch: refetchSlots } = useQuery<any[]>({
    queryKey: ["admin-pickup-slots", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/orders/slots/${activeCanteenId}`)).data,
  });

  useEffect(() => {
    if (queueDash?.max_concurrent_orders) {
      setMaxConcurrent(String(queueDash.max_concurrent_orders));
    }
  }, [queueDash?.max_concurrent_orders]);

  return (
    <div className="grid gap-5 md:grid-cols-2">
      <Card className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-bold text-slate-900">Live Queue & Crowd Control</h2>
            <div className="text-xs text-slate-500">
              Active: {queueDash?.active_order_count} • Crowd: {queueDash?.crowd_level} • Wait: {queueDash?.estimated_wait_minutes} min • Kitchen Workload: {queueDash?.kitchen_workload_percent}% • Staff On Duty: {queueDash?.on_duty_staff_count ?? 1}
            </div>
          </div>
          <Button
            size="sm"
            variant={queueDash?.ordering_paused ? "success" : "danger"}
            onClick={async () => {
              try {
                await api.patch(`/queue/canteens/${activeCanteenId}/controls`, {
                  ordering_paused: !queueDash?.ordering_paused,
                  pause_reason: !queueDash?.ordering_paused ? "Paused by manager due to peak crowd" : null,
                });
                refetchQueue();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            {queueDash?.ordering_paused ? "Resume Ordering" : "Pause Ordering"}
          </Button>
        </div>

        <div className="flex items-center gap-2 border-t border-slate-100 pt-3">
          <Input
            type="number"
            value={maxConcurrent}
            onChange={(e) => setMaxConcurrent(e.target.value)}
            placeholder="Max concurrent orders"
          />
          <Button
            size="sm"
            onClick={async () => {
              try {
                await api.patch(`/queue/canteens/${activeCanteenId}/controls`, {
                  max_concurrent_orders: Number(maxConcurrent),
                });
                pushToast("Capacity updated", "success");
                refetchQueue();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Update Capacity
          </Button>
        </div>
      </Card>

      <Card className="p-5 space-y-3">
        <h2 className="font-bold text-slate-900">Create / Update Pickup Slot</h2>
        <div className="grid grid-cols-2 gap-2">
          <Input type="date" value={slotDate} onChange={(e) => setSlotDate(e.target.value)} />
          <Input type="number" value={slotCap} onChange={(e) => setSlotCap(e.target.value)} placeholder="Slot capacity" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
          <Input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
        </div>
        <Button
          size="sm"
          onClick={async () => {
            try {
              await api.post(`/queue/canteens/${activeCanteenId}/slots`, {
                slot_date: slotDate,
                start_time: `${startTime}:00`,
                end_time: `${endTime}:00`,
                capacity: Number(slotCap),
                is_active: true,
              });
              refetchSlots();
              pushToast("Pickup slot configured", "success");
            } catch (err) {
              pushToast(getApiError(err), "error");
            }
          }}
        >
          Save Pickup Slot
        </Button>

        {pickupSlots.length > 0 && (
          <div className="border-t border-slate-100 pt-3 space-y-1.5">
            <div className="text-[11px] font-bold uppercase text-slate-500">Configured Upcoming Slots ({pickupSlots.length})</div>
            <div className="space-y-1.5 max-h-40 overflow-y-auto">
              {pickupSlots.map((s) => (
                <div key={s.id} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-1.5 text-xs">
                  <span>
                    <strong>{s.slot_date}</strong> • {String(s.start_time).slice(0, 5)}–{String(s.end_time).slice(0, 5)}{" "}
                    <span className="text-slate-500">({s.reserved_count}/{s.capacity} reserved)</span>
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      try {
                        await api.post(`/queue/canteens/${activeCanteenId}/slots`, {
                          slot_date: s.slot_date,
                          start_time: s.start_time,
                          end_time: s.end_time,
                          capacity: s.capacity,
                          is_active: false,
                        });
                        refetchSlots();
                        pushToast("Pickup slot disabled", "info");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Disable
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
};

export const StaffTab: React.FC<{ activeCanteenId: string; staffList: any[]; refetchStaff: () => void }> = ({
  activeCanteenId,
  staffList,
  refetchStaff,
}) => {
  const { pushToast } = useToast();
  const { data: tasks = [], refetch: refetchTasks } = useQuery<any[]>({
    queryKey: ["admin-staff-tasks", activeCanteenId],
    queryFn: async () => (await api.get(`/staff/tasks?canteen_id=${activeCanteenId}`)).data,
  });
  const { data: shifts = [], refetch: refetchShifts } = useQuery<any[]>({
    queryKey: ["admin-staff-shifts", activeCanteenId],
    queryFn: async () => (await api.get(`/staff/shifts?canteen_id=${activeCanteenId}`)).data,
  });
  const { data: attendance = [], refetch: refetchAttendance } = useQuery<any[]>({
    queryKey: ["admin-staff-attendance", activeCanteenId],
    queryFn: async () => (await api.get(`/staff/attendance?canteen_id=${activeCanteenId}`)).data,
  });

  const [newStaffName, setNewStaffName] = useState("");
  const [newStaffEmail, setNewStaffEmail] = useState("");
  const [newStaffEmp, setNewStaffEmp] = useState("");
  const [newStaffRole, setNewStaffRole] = useState("cashier");
  const [taskTitle, setTaskTitle] = useState("");
  const [taskAssignee, setTaskAssignee] = useState("");
  const [shiftUserId, setShiftUserId] = useState("");
  const [shiftDate, setShiftDate] = useState(new Date().toISOString().slice(0, 10));
  const [shiftStart, setShiftStart] = useState("08:00");
  const [shiftEnd, setShiftEnd] = useState("16:00");
  const [shiftType, setShiftType] = useState("regular");
  const [leaveUserId, setLeaveUserId] = useState("");
  const [leaveDate, setLeaveDate] = useState(new Date().toISOString().slice(0, 10));
  const [leaveReason, setLeaveReason] = useState("");

  const staffNameById = (uid?: string) => staffList.find((s) => s.user_id === uid)?.full_name || uid?.slice(0, 8) || "Staff";

  return (
    <div className="space-y-5">
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <div className="flex items-center justify-between">
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
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Check-out
              </Button>
            </div>
          </div>
          {staffList.map((s) => (
            <div key={s.user_id} className="flex justify-between rounded-xl border border-slate-200 p-3 text-xs">
              <div>
                <div className="font-bold text-slate-900">
                  {s.full_name} ({s.employee_code})
                </div>
                <div className="text-slate-500">
                  {s.designation} • {s.email}
                </div>
              </div>
              <Badge tone={s.is_on_duty ? "green" : "slate"}>{s.is_on_duty ? "On Duty" : "Off Duty"}</Badge>
            </div>
          ))}
        </Card>

        <div className="space-y-5">
          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900">Create Staff Member</h2>
            <Input value={newStaffName} onChange={(e) => setNewStaffName(e.target.value)} placeholder="Full Name" />
            <Input value={newStaffEmail} onChange={(e) => setNewStaffEmail(e.target.value)} placeholder="Email" />
            <Input value={newStaffEmp} onChange={(e) => setNewStaffEmp(e.target.value)} placeholder="Employee Code (EMP-201)" />
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
                    password: "StaffUser@123",
                    employee_code: newStaffEmp,
                    designation: newStaffRole.replace("_", " "),
                    role_names: [newStaffRole],
                    assigned_canteen_id: activeCanteenId,
                  });
                  setNewStaffName("");
                  setNewStaffEmail("");
                  setNewStaffEmp("");
                  pushToast("Staff user created", "success");
                  refetchStaff();
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
            <div className="flex gap-2">
              <Input value={taskTitle} onChange={(e) => setTaskTitle(e.target.value)} placeholder="Task title (e.g. Restock cups)" />
              <Select value={taskAssignee} onChange={(e) => setTaskAssignee(e.target.value)} className="w-40">
                <option value="">Any Staff</option>
                {staffList.map((s) => (
                  <option key={s.user_id} value={s.user_id}>
                    {s.full_name}
                  </option>
                ))}
              </Select>
              <Button
                size="sm"
                onClick={async () => {
                  if (!taskTitle.trim()) return;
                  try {
                    await api.post("/staff/tasks", {
                      canteen_id: activeCanteenId,
                      assigned_to_user_id: taskAssignee || null,
                      title: taskTitle,
                      priority: "normal",
                    });
                    setTaskTitle("");
                    refetchTasks();
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
                  <span className="font-semibold">{t.title}</span>
                  <Button
                    size="sm"
                    variant={t.status === "done" ? "success" : "outline"}
                    onClick={async () => {
                      try {
                        await api.patch(`/staff/tasks/${t.id}`, { status: t.status === "done" ? "pending" : "done" });
                        refetchTasks();
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

      {/* Shifts & Leave Management */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <Calendar className="h-4 w-4 text-[#76010d]" /> Staff Shift Roster ({shifts.length})
          </h2>
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
          <div className="flex gap-2">
            <Select value={shiftType} onChange={(e) => setShiftType(e.target.value)}>
              <option value="regular">Regular</option>
              <option value="morning">Morning</option>
              <option value="afternoon">Afternoon</option>
              <option value="cashier">Cashier</option>
            </Select>
            <Button
              size="sm"
              onClick={async () => {
                try {
                  const uid = shiftUserId || staffList[0]?.user_id;
                  if (!uid) return pushToast("No staff found", "error");
                  await api.post("/staff/shifts", {
                    staff_user_id: uid,
                    canteen_id: activeCanteenId,
                    shift_date: shiftDate,
                    start_time: `${shiftStart}:00`,
                    end_time: `${shiftEnd}:00`,
                    shift_type: shiftType,
                  });
                  pushToast("Shift scheduled", "success");
                  refetchShifts();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Schedule Shift
            </Button>
          </div>
          <div className="space-y-1.5 max-h-40 overflow-y-auto text-xs">
            {shifts.slice(0, 15).map((sh) => (
              <div key={sh.id} className="flex items-center justify-between border-b border-slate-100 py-1.5">
                <span>
                  <strong>{staffNameById(sh.staff_user_id)}</strong> • {sh.shift_date} ({sh.start_time.slice(0, 5)}–{sh.end_time.slice(0, 5)}) <Badge tone="slate">{sh.status}</Badge>
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
          <h2 className="font-bold text-slate-900">Attendance & Leave Approvals ({attendance.length})</h2>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <Select value={leaveUserId} onChange={(e) => setLeaveUserId(e.target.value)}>
              <option value="">Select Staff for Leave</option>
              {staffList.map((s) => (
                <option key={s.user_id} value={s.user_id}>
                  {s.full_name}
                </option>
              ))}
            </Select>
            <Input type="date" value={leaveDate} onChange={(e) => setLeaveDate(e.target.value)} />
          </div>
          <div className="flex gap-2">
            <Input value={leaveReason} onChange={(e) => setLeaveReason(e.target.value)} placeholder="Leave reason..." />
            <Button
              size="sm"
              onClick={async () => {
                try {
                  const uid = leaveUserId || staffList[0]?.user_id;
                  if (!uid) return pushToast("Select staff first", "error");
                  await api.post("/staff/attendance/leave", {
                    staff_user_id: uid,
                    canteen_id: activeCanteenId,
                    attendance_date: leaveDate,
                    reason: leaveReason || "Manager recorded leave",
                  });
                  setLeaveReason("");
                  refetchAttendance();
                  pushToast("Leave recorded", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Record Leave
            </Button>
          </div>
          <div className="space-y-1.5 max-h-40 overflow-y-auto text-xs">
            {attendance.slice(0, 15).map((att) => (
              <div key={att.id} className="flex items-center justify-between border-b border-slate-100 py-1.5">
                <span>
                  <strong>{staffNameById(att.staff_user_id)}</strong> • {att.attendance_date} • <Badge tone={att.status === "present" ? "green" : att.status === "leave_pending" ? "amber" : "slate"}>{att.status}</Badge>
                </span>
                {att.status === "leave_pending" && (
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant="success"
                      onClick={async () => {
                        try {
                          await api.patch(`/staff/attendance/${att.id}/review`, { approved: true });
                          refetchAttendance();
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
    </div>
  );
};
