import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ClipboardList, Search, ShieldCheck } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

export const OrdersUsersTab: React.FC<{ activeCanteenId: string }> = ({ activeCanteenId }) => {
  const { pushToast } = useToast();
  const [statusFilter, setStatusFilter] = useState("");
  const [orderSearch, setOrderSearch] = useState("");
  const [userKindFilter, setUserKindFilter] = useState("");
  const [roleEdits, setRoleEdits] = useState<Record<string, string>>({});

  const { data: orders = [], refetch: refetchOrders } = useQuery<any[]>({
    queryKey: ["admin-all-orders", activeCanteenId, statusFilter, orderSearch],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (statusFilter) params.set("status", statusFilter);
      if (orderSearch.trim()) params.set("q", orderSearch.trim());
      params.set("limit", "100");
      return (await api.get(`/admin/orders?${params.toString()}`)).data;
    },
  });

  const { data: users = [], refetch: refetchUsers } = useQuery<any[]>({
    queryKey: ["admin-all-users", userKindFilter],
    queryFn: async () => {
      const qs = userKindFilter ? `?user_kind=${encodeURIComponent(userKindFilter)}` : "";
      return (await api.get(`/admin/users${qs}`)).data;
    },
  });

  return (
    <div className="space-y-6">
      <Card className="p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-orange-600" /> All Campus Orders ({orders.length})
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
              <Input
                value={orderSearch}
                onChange={(e) => setOrderSearch(e.target.value)}
                placeholder="Order No / Token / Guest..."
                className="pl-8 w-52"
              />
            </div>
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="w-40">
              <option value="">All Statuses</option>
              <option value="PLACED">PLACED</option>
              <option value="ACCEPTED">ACCEPTED</option>
              <option value="PREPARING">PREPARING</option>
              <option value="READY">READY</option>
              <option value="COMPLETED">COMPLETED</option>
              <option value="CANCELLED">CANCELLED</option>
              <option value="PAYMENT_PENDING">PAYMENT_PENDING</option>
            </Select>
          </div>
        </div>

        <div className="space-y-2 max-h-96 overflow-y-auto text-xs">
          {orders.map((o) => (
            <div key={o.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-3">
              <div>
                <div className="flex flex-wrap items-center gap-2 font-bold text-sm">
                  <span>{o.order_number}</span>
                  {o.pickup_token_code && <Badge tone="default">Token {o.pickup_token_code}</Badge>}
                  <Badge tone={o.payment_status === "CONFIRMED" ? "green" : "amber"}>{o.payment_status}</Badge>
                  <Badge tone="slate">{o.status}</Badge>
                </div>
                <div className="text-slate-500 mt-1">
                  {o.canteen_name} • {o.guest_name || "Registered Customer"} • ₹{o.total_amount} ({o.payment_method})
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Link to={`/orders/${o.order_number}`}>
                  <Button size="sm" variant="outline">
                    View Receipt
                  </Button>
                </Link>
                {["PAYMENT_PENDING", "PLACED", "ACCEPTED"].includes(o.status) && (
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      if (!window.confirm("Cancel this order? Payment records remain retained (no in-app refunds).")) return;
                      try {
                        await api.post(`/orders/${o.id}/cancel`, { reason: "Cancelled by college administrator" });
                        pushToast("Order cancelled (payment record retained)", "info");
                        refetchOrders();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Cancel
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card className="p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-600" /> Customers, Users & Permissions ({users.length})
          </h2>
          <Select value={userKindFilter} onChange={(e) => setUserKindFilter(e.target.value)} className="w-44">
            <option value="">All Accounts</option>
            <option value="customer">Customers</option>
            <option value="staff">Staff</option>
            <option value="admin">Admins</option>
          </Select>
        </div>

        <div className="space-y-2 max-h-96 overflow-y-auto text-xs">
          {users.map((u) => {
            const currentRole = roleEdits[u.id] ?? u.roles?.[0] ?? "customer";
            return (
              <div key={u.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-3">
                <div>
                  <div className="flex items-center gap-2 font-bold text-sm text-slate-900">
                    <span>{u.full_name}</span>
                    <Badge tone={u.is_active ? "green" : "red"}>{u.is_active ? "Active" : "Suspended"}</Badge>
                    {(u.roles || []).map((r: string) => (
                      <Badge key={r} tone="slate">
                        {r}
                      </Badge>
                    ))}
                  </div>
                  <div className="text-slate-500 mt-0.5">
                    {u.email || u.phone || "No contact"} • Type: {u.user_kind}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Select
                    value={currentRole}
                    onChange={(e) => setRoleEdits((p) => ({ ...p, [u.id]: e.target.value }))}
                    className="w-40"
                  >
                    <option value="customer">customer</option>
                    <option value="cashier">cashier</option>
                    <option value="kitchen_staff">kitchen_staff</option>
                    <option value="pickup_staff">pickup_staff</option>
                    <option value="inventory_manager">inventory_manager</option>
                    <option value="canteen_manager">canteen_manager</option>
                    <option value="college_admin">college_admin</option>
                    <option value="super_admin">super_admin</option>
                  </Select>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      try {
                        await api.patch(`/admin/users/${u.id}/roles`, {
                          role_names: [currentRole],
                          canteen_id: activeCanteenId || null,
                        });
                        pushToast("User role updated", "success");
                        refetchUsers();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Save Role
                  </Button>
                  <Button
                    size="sm"
                    variant={u.is_active ? "danger" : "success"}
                    onClick={async () => {
                      try {
                        await api.patch(`/admin/users/${u.id}/status`, { is_active: !u.is_active });
                        pushToast(`User ${!u.is_active ? "activated" : "suspended"}`, "info");
                        refetchUsers();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    {u.is_active ? "Suspend" : "Activate"}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
};
