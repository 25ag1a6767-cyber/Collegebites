import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Users } from "lucide-react";
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

  return (
    <div className="grid gap-5 md:grid-cols-2">
      <Card className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-bold text-slate-900">Live Queue & Crowd Control</h2>
            <div className="text-xs text-slate-500">
              Active: {queueDash?.active_order_count} • Crowd: {queueDash?.crowd_level} • Wait: {queueDash?.estimated_wait_minutes} min • Kitchen Workload: {queueDash?.kitchen_workload_percent}%
            </div>
          </div>
          <Button
            size="sm"
            variant={queueDash?.ordering_paused ? "success" : "danger"}
            onClick={async () => {
              await api.patch(`/queue/canteens/${activeCanteenId}/controls`, {
                ordering_paused: !queueDash?.ordering_paused,
                pause_reason: !queueDash?.ordering_paused ? "Paused by manager due to peak crowd" : null,
              });
              refetchQueue();
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
              await api.patch(`/queue/canteens/${activeCanteenId}/controls`, {
                max_concurrent_orders: Number(maxConcurrent),
              });
              pushToast("Capacity updated", "success");
              refetchQueue();
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
              pushToast("Pickup slot configured", "success");
            } catch (err) {
              pushToast(getApiError(err), "error");
            }
          }}
        >
          Save Pickup Slot
        </Button>
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

  const [newStaffName, setNewStaffName] = useState("");
  const [newStaffEmail, setNewStaffEmail] = useState("");
  const [newStaffEmp, setNewStaffEmp] = useState("");
  const [newStaffRole, setNewStaffRole] = useState("cashier");
  const [taskTitle, setTaskTitle] = useState("");
  const [taskAssignee, setTaskAssignee] = useState("");

  return (
    <div className="grid gap-5 md:grid-cols-2">
      <Card className="p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <Users className="h-4 w-4 text-orange-600" /> Staff Directory ({staffList.length})
          </h2>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                await api.post(`/staff/attendance/check-in?canteen_id=${activeCanteenId}`);
                pushToast("Checked in", "success");
                refetchStaff();
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
                await api.post("/staff/tasks", {
                  canteen_id: activeCanteenId,
                  assigned_to_user_id: taskAssignee || null,
                  title: taskTitle,
                  priority: "normal",
                });
                setTaskTitle("");
                refetchTasks();
                pushToast("Task assigned", "success");
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
                    await api.patch(`/staff/tasks/${t.id}`, { status: t.status === "done" ? "pending" : "done" });
                    refetchTasks();
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
  );
};
