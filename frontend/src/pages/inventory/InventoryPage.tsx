import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Package, Plus, Truck } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen } from "../../types";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";

export const InventoryPage: React.FC = () => {
  const { pushToast } = useToast();
  const { user, selectedCanteenId } = useAppStore();

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [canteenId, setCanteenId] = useState(user?.assigned_canteen_id || selectedCanteenId || "");
  const activeId = canteenId || canteens[0]?.id || "";

  const { data: items = [], refetch: refetchItems } = useQuery<any[]>({
    queryKey: ["inv-items", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeId}/items`)).data,
  });

  const { data: alerts, refetch: refetchAlerts } = useQuery<any>({
    queryKey: ["inv-alerts", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeId}/alerts`)).data,
  });

  const { data: suppliers = [], refetch: refetchSuppliers } = useQuery<any[]>({
    queryKey: ["inv-suppliers"],
    queryFn: async () => (await api.get("/inventory/suppliers")).data,
  });

  const { data: pos = [], refetch: refetchPos } = useQuery<any[]>({
    queryKey: ["inv-pos", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeId}/purchase-orders`)).data,
  });

  // Form states
  const [ingName, setIngName] = useState("");
  const [ingSku, setIngSku] = useState("");
  const [ingUnit, setIngUnit] = useState("grams");
  const [ingQty, setIngQty] = useState("1000");
  const [ingReorder, setIngReorder] = useState("200");
  const [supName, setSupName] = useState("");
  const [supPhone, setSupPhone] = useState("");
  const [poSupId, setPoSupId] = useState("");
  const [poIngId, setPoIngId] = useState("");
  const [poQty, setPoQty] = useState("5000");
  const [poCost, setPoCost] = useState("0.20");
  const [wasteItemId, setWasteItemId] = useState("");
  const [wasteQty, setWasteQty] = useState("100");
  const [wasteReason, setWasteReason] = useState("Expired batch");

  const refreshAll = () => {
    refetchItems();
    refetchAlerts();
    refetchPos();
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-slate-900 p-4 text-white">
        <div className="flex items-center gap-3">
          <Package className="h-7 w-7 text-purple-400" />
          <div>
            <h1 className="text-xl font-extrabold">Inventory, Recipes & Purchase Orders</h1>
            <p className="text-xs text-slate-400">
              Batch expiry tracking, automatic recipe deductions, wastage logging & low-stock food blocking
            </p>
          </div>
        </div>
        <Select
          value={activeId}
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

      {/* Alerts Bar */}
      {alerts && (
        <div className="grid gap-4 md:grid-cols-3">
          <Card className="p-4 border-amber-200 bg-amber-50">
            <div className="flex items-center gap-2 font-bold text-amber-900 text-sm">
              <AlertTriangle className="h-4 w-4" /> Low Stock Ingredients ({alerts.low_stock.length})
            </div>
            <div className="mt-2 space-y-1 text-xs text-amber-800">
              {alerts.low_stock.map((l: any) => (
                <div key={l.inventory_item_id}>
                  {l.ingredient_name}: {l.current_quantity} / {l.reorder_level} {l.unit}
                </div>
              ))}
            </div>
          </Card>
          <Card className="p-4 border-red-200 bg-red-50">
            <div className="font-bold text-red-900 text-sm">Expiring Within 7 Days ({alerts.expiring_soon.length})</div>
            <div className="mt-2 space-y-1 text-xs text-red-800">
              {alerts.expiring_soon.map((e: any) => (
                <div key={e.batch_number}>
                  {e.ingredient_name} ({e.batch_number}) • Exp: {e.expiry_date}
                </div>
              ))}
            </div>
          </Card>
          <Card className="p-4 border-slate-200 bg-slate-50">
            <div className="font-bold text-slate-900 text-sm">Blocked Menu Items ({alerts.blocked_food_items.length})</div>
            <div className="mt-2 space-y-1 text-xs text-slate-600">
              {alerts.blocked_food_items.map((b: any) => (
                <div key={b.id}>• {b.name} (Insufficient ingredients)</div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* Current Stock Table */}
      <Card className="p-5 overflow-x-auto">
        <h2 className="font-bold text-slate-900 mb-3">Stock Quantities & Batches</h2>
        <table className="w-full text-left text-xs">
          <thead className="border-b border-slate-200 text-slate-500 uppercase">
            <tr>
              <th className="py-2">Ingredient</th>
              <th>SKU</th>
              <th>On Hand</th>
              <th>Reorder Level</th>
              <th>Status</th>
              <th>Active Batches (Expiry)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((it) => (
              <tr key={it.inventory_item_id}>
                <td className="py-2.5 font-bold text-slate-900">{it.name}</td>
                <td className="font-mono">{it.sku}</td>
                <td className="font-bold">
                  {it.current_quantity} {it.unit}
                </td>
                <td>
                  {it.reorder_level} {it.unit}
                </td>
                <td>
                  <Badge tone={it.is_low_stock ? "red" : "green"}>{it.is_low_stock ? "Low Stock" : "Healthy"}</Badge>
                </td>
                <td className="text-slate-500">
                  {it.batches.map((b: any) => `${b.batch_number} (${b.remaining_quantity}, exp ${b.expiry_date || "N/A"})`).join("; ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Actions Grid */}
      <div className="grid gap-5 md:grid-cols-3">
        <Card className="p-4 space-y-3">
          <h3 className="font-bold text-sm text-slate-900 flex items-center gap-1.5">
            <Plus className="h-4 w-4 text-orange-600" /> Add Ingredient
          </h3>
          <Input value={ingName} onChange={(e) => setIngName(e.target.value)} placeholder="Name (e.g. Paneer)" />
          <Input value={ingSku} onChange={(e) => setIngSku(e.target.value)} placeholder="SKU (e.g. PNR-01)" />
          <div className="grid grid-cols-3 gap-2">
            <Input value={ingUnit} onChange={(e) => setIngUnit(e.target.value)} placeholder="Unit" />
            <Input value={ingQty} onChange={(e) => setIngQty(e.target.value)} placeholder="Init Qty" />
            <Input value={ingReorder} onChange={(e) => setIngReorder(e.target.value)} placeholder="Reorder" />
          </div>
          <Button
            size="sm"
            className="w-full"
            onClick={async () => {
              try {
                await api.post("/inventory/ingredients", {
                  canteen_id: activeId,
                  name: ingName,
                  sku: ingSku,
                  unit: ingUnit,
                  initial_quantity: ingQty,
                  reorder_level: ingReorder,
                });
                setIngName("");
                setIngSku("");
                pushToast("Ingredient created", "success");
                refreshAll();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Add Ingredient
          </Button>
        </Card>

        <Card className="p-4 space-y-3">
          <h3 className="font-bold text-sm text-slate-900 flex items-center gap-1.5">
            <Truck className="h-4 w-4 text-sky-600" /> Purchase Orders & Suppliers
          </h3>
          <div className="flex gap-2">
            <Input value={supName} onChange={(e) => setSupName(e.target.value)} placeholder="New supplier name" />
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                await api.post("/inventory/suppliers", { name: supName, phone: supPhone || "+91-9000000000" });
                setSupName("");
                refetchSuppliers();
                pushToast("Supplier added", "success");
              }}
            >
              Add
            </Button>
          </div>
          <Select value={poSupId} onChange={(e) => setPoSupId(e.target.value)}>
            <option value="">Select Supplier</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
          <Select value={poIngId} onChange={(e) => setPoIngId(e.target.value)}>
            <option value="">Select Ingredient</option>
            {items.map((it) => (
              <option key={it.ingredient_id} value={it.ingredient_id}>
                {it.name} ({it.unit})
              </option>
            ))}
          </Select>
          <div className="grid grid-cols-2 gap-2">
            <Input value={poQty} onChange={(e) => setPoQty(e.target.value)} placeholder="Qty" />
            <Input value={poCost} onChange={(e) => setPoCost(e.target.value)} placeholder="Unit Cost" />
          </div>
          <Button
            size="sm"
            className="w-full"
            onClick={async () => {
              try {
                await api.post("/inventory/purchase-orders", {
                  canteen_id: activeId,
                  supplier_id: poSupId || suppliers[0]?.id,
                  items: [{ ingredient_id: poIngId || items[0]?.ingredient_id, quantity_ordered: poQty, unit_cost: poCost }],
                });
                pushToast("Purchase order created", "success");
                refreshAll();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Create Purchase Order
          </Button>
        </Card>

        <Card className="p-4 space-y-3">
          <h3 className="font-bold text-sm text-slate-900">Record Wastage / Spoilage</h3>
          <Select value={wasteItemId} onChange={(e) => setWasteItemId(e.target.value)}>
            <option value="">Select Inventory Item</option>
            {items.map((it) => (
              <option key={it.inventory_item_id} value={it.inventory_item_id}>
                {it.name} ({it.current_quantity} {it.unit})
              </option>
            ))}
          </Select>
          <Input value={wasteQty} onChange={(e) => setWasteQty(e.target.value)} placeholder="Quantity wasted" />
          <Input value={wasteReason} onChange={(e) => setWasteReason(e.target.value)} placeholder="Reason" />
          <Button
            size="sm"
            variant="danger"
            className="w-full"
            onClick={async () => {
              try {
                await api.post("/inventory/wastage", {
                  inventory_item_id: wasteItemId || items[0]?.inventory_item_id,
                  quantity: wasteQty,
                  reason: wasteReason,
                });
                pushToast("Wastage recorded", "info");
                refreshAll();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Log Wastage
          </Button>
        </Card>
      </div>

      {/* Purchase Orders List */}
      <Card className="p-5 space-y-3">
        <h2 className="font-bold text-slate-900">Recent Purchase Orders ({pos.length})</h2>
        <div className="space-y-2">
          {pos.map((po) => (
            <div key={po.id} className="flex items-center justify-between rounded-xl border border-slate-200 p-3 text-xs">
              <div>
                <span className="font-bold">{po.po_number}</span> • ₹{po.total_cost} •{" "}
                <Badge tone={po.status === "received" ? "green" : "amber"}>{po.status}</Badge>
              </div>
              {po.status !== "received" && (
                <Button
                  size="sm"
                  variant="success"
                  onClick={async () => {
                    await api.post(`/inventory/purchase-orders/${po.id}/receive`);
                    pushToast(`${po.po_number} received into stock!`, "success");
                    refreshAll();
                  }}
                >
                  Receive Stock
                </Button>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};
