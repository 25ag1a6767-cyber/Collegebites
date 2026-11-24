import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck, Megaphone, RefreshCw, Search, ShieldAlert } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";

export const NotificationCenterPage: React.FC = () => {
  const { user } = useAppStore();
  const { pushToast } = useToast();
  const qc = useQueryClient();

  const roles = new Set(user?.roles || []);
  const isStaffManager = roles.has("super_admin") || roles.has("college_admin") || roles.has("canteen_manager");
  const isAdmin = roles.has("super_admin") || roles.has("college_admin");

  const [tab, setTab] = useState<"inbox" | "deliveries" | "broadcast">("inbox");
  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("all");
  const [category, setCategory] = useState("all");
  const [readFilter, setReadFilter] = useState("all");

  const [maintTitle, setMaintTitle] = useState("");
  const [maintMsg, setMaintMsg] = useState("");
  const [maintPriority, setMaintPriority] = useState("high");
  const [busy, setBusy] = useState(false);

  const qs = new URLSearchParams();
  if (search.trim()) qs.set("q", search.trim());
  if (priority !== "all") qs.set("priority", priority);
  if (category !== "all") qs.set("category", category);
  if (readFilter === "unread") qs.set("is_read", "false");
  if (readFilter === "read") qs.set("is_read", "true");

  const { data: notifications = [], refetch } = useQuery<any[]>({
    queryKey: ["notif-center-list", qs.toString()],
    enabled: Boolean(user),
    queryFn: async () => (await api.get(`/notifications/my?${qs.toString()}`)).data,
  });

  const { data: unreadData } = useQuery<{ unread_count: number }>({
    queryKey: ["notif-unread-count"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/notifications/unread-count")).data,
  });

  const { data: deliveries = [], refetch: refetchDeliveries } = useQuery<any[]>({
    queryKey: ["notif-deliveries"],
    enabled: Boolean(user && isStaffManager && tab === "deliveries"),
    queryFn: async () => (await api.get("/notifications/deliveries?limit=100")).data,
  });

  const priorityTone = (p: string): "red" | "amber" | "blue" | "slate" =>
    p === "critical" ? "red" : p === "high" ? "amber" : p === "normal" ? "blue" : "slate";

  const statusTone = (s: string): "green" | "amber" | "red" | "slate" =>
    s === "delivered" || s === "sent" ? "green" : s === "pending" ? "amber" : s === "failed" ? "red" : "slate";

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-[#380106] p-4 text-white">
        <div className="flex items-center gap-3">
          <Bell className="h-6 w-6 text-[#fdedce]" />
          <div>
            <h1 className="text-xl font-extrabold">Notification &amp; Communication Center</h1>
            <p className="text-xs text-[#fdedce]/80">
              Real-time role-targeted operational alerts, delivery tracking, and audit history
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="amber">{unreadData?.unread_count ?? 0} Unread</Badge>
          <Button
            size="sm"
            variant="outline"
            className="bg-slate-800 border-slate-700 text-white hover:bg-slate-700"
            onClick={async () => {
              try {
                await api.post("/notifications/mark-all-read");
                qc.invalidateQueries({ queryKey: ["notifications-my"] });
                qc.invalidateQueries({ queryKey: ["notif-unread-count"] });
                refetch();
                pushToast("All notifications marked read", "success");
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            <CheckCheck className="h-3.5 w-3.5" /> Mark All Read
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={tab === "inbox" ? "secondary" : "outline"} onClick={() => setTab("inbox")}>
          Inbox ({notifications.length})
        </Button>
        {isStaffManager && (
          <Button size="sm" variant={tab === "deliveries" ? "secondary" : "outline"} onClick={() => setTab("deliveries")}>
            Channel Delivery Logs
          </Button>
        )}
        {isAdmin && (
          <Button size="sm" variant={tab === "broadcast" ? "secondary" : "outline"} onClick={() => setTab("broadcast")}>
            <Megaphone className="h-3.5 w-3.5" /> System Maintenance Broadcast
          </Button>
        )}
      </div>

      {tab === "inbox" && (
        <div className="space-y-4">
          <Card className="p-4 flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="h-4 w-4 text-slate-400 absolute left-3 top-2.5" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search title, message, event..."
                className="pl-9"
              />
            </div>
            <Select value={priority} onChange={(e) => setPriority(e.target.value)} className="w-36">
              <option value="all">All Priorities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </Select>
            <Select value={category} onChange={(e) => setCategory(e.target.value)} className="w-40">
              <option value="all">All Categories</option>
              <option value="order">Order</option>
              <option value="payment">Payment</option>
              <option value="inventory">Inventory</option>
              <option value="procurement">Procurement</option>
              <option value="food_safety">Food Safety</option>
              <option value="queue">Queue</option>
              <option value="system">System</option>
            </Select>
            <Select value={readFilter} onChange={(e) => setReadFilter(e.target.value)} className="w-32">
              <option value="all">All</option>
              <option value="unread">Unread</option>
              <option value="read">Read</option>
            </Select>
          </Card>

          <div className="space-y-2">
            {notifications.length === 0 ? (
              <Card className="p-8 text-center text-sm text-slate-500">
                No notifications match the selected filters.
              </Card>
            ) : (
              notifications.map((n) => (
                <Card
                  key={n.id}
                  className={`p-4 flex flex-wrap items-start justify-between gap-3 ${
                    n.is_read ? "bg-white" : "border-[#76010d]/30 bg-[#fdf8f0]"
                  }`}
                >
                  <div className="space-y-1 flex-1 min-w-[240px]">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={priorityTone(n.priority)}>{(n.priority || "normal").toUpperCase()}</Badge>
                      <Badge tone="slate">{n.category || "order"}</Badge>
                      <Badge tone={statusTone(n.delivery_status)}>{n.delivery_status}</Badge>
                      <span className="text-[11px] text-slate-400 font-mono">
                        {n.created_at ? new Date(n.created_at).toLocaleString() : ""}
                      </span>
                    </div>
                    <div className="font-bold text-sm text-slate-900">{n.title}</div>
                    <div className="text-xs text-slate-600">{n.message}</div>
                    {n.last_error && (
                      <div className="text-[11px] text-red-700 font-medium">Delivery error: {n.last_error}</div>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {!n.is_read && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={async () => {
                          try {
                            await api.post(`/notifications/${n.id}/read`);
                            qc.invalidateQueries({ queryKey: ["notifications-my"] });
                            qc.invalidateQueries({ queryKey: ["notif-unread-count"] });
                            refetch();
                          } catch (err) {
                            pushToast(getApiError(err), "error");
                          }
                        }}
                      >
                        Mark Read
                      </Button>
                    )}
                    {isStaffManager && (n.delivery_status === "failed" || n.delivery_status === "pending") && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={async () => {
                          try {
                            await api.post(`/notifications/${n.id}/retry`);
                            pushToast("Retry attempt triggered", "info");
                            refetch();
                            refetchDeliveries();
                          } catch (err) {
                            pushToast(getApiError(err), "error");
                          }
                        }}
                      >
                        <RefreshCw className="h-3.5 w-3.5" /> Retry
                      </Button>
                    )}
                  </div>
                </Card>
              ))
            )}
          </div>
        </div>
      )}

      {tab === "deliveries" && isStaffManager && (
        <Card className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-bold text-slate-900">Channel Delivery Audit Log (PII Masked)</h2>
            <Button size="sm" variant="outline" onClick={() => refetchDeliveries()}>
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </Button>
          </div>
          {deliveries.length === 0 ? (
            <div className="text-xs text-slate-500 py-4 text-center">No delivery records found.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="border-b border-slate-200 text-slate-500 uppercase">
                  <tr>
                    <th className="py-2 pr-3">Channel</th>
                    <th className="py-2 pr-3">Recipient (Masked)</th>
                    <th className="py-2 pr-3">Status</th>
                    <th className="py-2 pr-3">Attempts</th>
                    <th className="py-2 pr-3">Provider</th>
                    <th className="py-2">Last Error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {deliveries.map((d) => (
                    <tr key={d.id}>
                      <td className="py-2 pr-3 font-semibold">{d.channel}</td>
                      <td className="py-2 pr-3 font-mono">{d.recipient_masked}</td>
                      <td className="py-2 pr-3">
                        <Badge tone={statusTone(d.status)}>{d.status}</Badge>
                      </td>
                      <td className="py-2 pr-3">{d.attempt_count}</td>
                      <td className="py-2 pr-3">{d.provider_name || "-"}</td>
                      <td className="py-2 text-red-700">{d.last_error || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {tab === "broadcast" && isAdmin && (
        <Card className="p-5 space-y-3 max-w-2xl">
          <div className="flex items-center gap-2 font-bold text-slate-900">
            <ShieldAlert className="h-4 w-4 text-[#76010d]" /> Broadcast System Maintenance Notice
          </div>
          <p className="text-xs text-slate-500">
            Sends an audited role-wide maintenance alert to all campus staff and student accounts.
          </p>
          <Input
            value={maintTitle}
            onChange={(e) => setMaintTitle(e.target.value)}
            placeholder="Title (e.g., Scheduled Canteen Server Maintenance at 10 PM)"
          />
          <textarea
            value={maintMsg}
            onChange={(e) => setMaintMsg(e.target.value)}
            rows={3}
            placeholder="Describe maintenance window and impact..."
            className="w-full rounded-xl border border-slate-300 p-2.5 text-sm focus:border-[#76010d] focus:outline-none"
          />
          <div className="flex items-center gap-3">
            <Select value={maintPriority} onChange={(e) => setMaintPriority(e.target.value)} className="w-40">
              <option value="high">High Priority</option>
              <option value="critical">Critical Priority</option>
              <option value="normal">Normal Priority</option>
            </Select>
            <Button
              variant="primary"
              disabled={busy || maintTitle.trim().length < 3 || maintMsg.trim().length < 5}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.post("/notifications/system-maintenance", {
                    title: maintTitle.trim(),
                    message: maintMsg.trim(),
                    priority: maintPriority,
                  });
                  setMaintTitle("");
                  setMaintMsg("");
                  pushToast("System maintenance alert broadcasted", "success");
                  refetch();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Send Broadcast
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
};
