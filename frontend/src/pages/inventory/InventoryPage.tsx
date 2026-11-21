import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRightLeft, History, Package, Plus, Trash2, Truck } from "lucide-react";
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

  const { data: menuItems = [] } = useQuery<any[]>({
    queryKey: ["inv-menu", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/menus/canteens/${activeId}/items?include_inactive=true`)).data,
  });

  const { data: movements = [], refetch: refetchMovements } = useQuery<any[]>({
    queryKey: ["inv-movements", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeId}/movements?limit=25`)).data,
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
  const [recipeFoodId, setRecipeFoodId] = useState("");
  const [recipeIngId, setRecipeIngId] = useState("");
  const [recipeQty, setRecipeQty] = useState("150");
  const [recipeYield, setRecipeYield] = useState("1");
  const [recipeRows, setRecipeRows] = useState<{ ingredient_id: string; ingredient_name: string; quantity_required: string }[]>([]);
  const [adjItemId, setAdjItemId] = useState("");
  const [adjDelta, setAdjDelta] = useState("500");
  const [adjReason, setAdjReason] = useState("Physical stock count");
  const [transferToId, setTransferToId] = useState("");
  const [transferIngId, setTransferIngId] = useState("");
  const [transferQty, setTransferQty] = useState("100");
  const [transferNotes, setTransferNotes] = useState("");

  useEffect(() => {
    if (!recipeFoodId) {
      setRecipeRows([]);
      return;
    }
    api
      .get(`/inventory/recipes/${recipeFoodId}`)
      .then((res) => {
        setRecipeYield(String(res.data.yield_portions || 1));
        setRecipeRows(
          (res.data.ingredients || []).map((r: any) => ({
            ingredient_id: r.ingredient_id,
            ingredient_name: r.ingredient_name,
            quantity_required: String(r.quantity_required),
          }))
        );
      })
      .catch(() => {});
  }, [recipeFoodId]);

  const refreshAll = () => {
    refetchItems();
    refetchAlerts();
    refetchPos();
    refetchMovements();
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
          <div className="grid grid-cols-2 gap-2">
            <Input value={supName} onChange={(e) => setSupName(e.target.value)} placeholder="New supplier name" />
            <Input value={supPhone} onChange={(e) => setSupPhone(e.target.value)} placeholder="Phone (+91...)" />
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              try {
                await api.post("/inventory/suppliers", { name: supName, phone: supPhone.trim() || null });
                setSupName("");
                setSupPhone("");
                refetchSuppliers();
                pushToast("Supplier added", "success");
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Add Supplier
          </Button>
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
                    try {
                      await api.post(`/inventory/purchase-orders/${po.id}/receive`);
                      pushToast(`${po.po_number} received into stock!`, "success");
                      refreshAll();
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  Receive Stock
                </Button>
              )}
            </div>
          ))}
        </div>
      </Card>

      {/* Recipe Mapping & Manual Stock Adjustments */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 text-sm">Link Multi-Ingredient Recipe (Auto Stock Deduction)</h2>
          <Select value={recipeFoodId} onChange={(e) => setRecipeFoodId(e.target.value)}>
            <option value="">Select Menu Dish</option>
            {menuItems.map((m: any) => (
              <option key={m.id} value={m.id}>
                {m.name} (₹{m.base_price})
              </option>
            ))}
          </Select>
          <div className="flex gap-2">
            <Select value={recipeIngId} onChange={(e) => setRecipeIngId(e.target.value)}>
              <option value="">Add Ingredient</option>
              {items.map((it) => (
                <option key={it.ingredient_id} value={it.ingredient_id}>
                  {it.name} ({it.unit})
                </option>
              ))}
            </Select>
            <Input value={recipeQty} onChange={(e) => setRecipeQty(e.target.value)} placeholder="Qty" className="w-24" />
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                const ing = items.find((it) => it.ingredient_id === (recipeIngId || items[0]?.ingredient_id));
                if (!ing) return;
                setRecipeRows((prev) => {
                  const rest = prev.filter((r) => r.ingredient_id !== ing.ingredient_id);
                  return [...rest, { ingredient_id: ing.ingredient_id, ingredient_name: ing.name, quantity_required: recipeQty || "1" }];
                });
              }}
            >
              + Add
            </Button>
          </div>
          {recipeRows.length > 0 && (
            <div className="space-y-1 text-xs rounded-xl border border-slate-100 bg-slate-50 p-2">
              {recipeRows.map((r) => (
                <div key={r.ingredient_id} className="flex items-center justify-between">
                  <span>
                    <strong>{r.ingredient_name}</strong>: {r.quantity_required}
                  </span>
                  <button
                    type="button"
                    onClick={() => setRecipeRows((p) => p.filter((x) => x.ingredient_id !== r.ingredient_id))}
                    className="text-red-500 hover:text-red-700"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <Input value={recipeYield} onChange={(e) => setRecipeYield(e.target.value)} placeholder="Yield Portions (1)" />
          <Button
            size="sm"
            className="w-full"
            onClick={async () => {
              try {
                const payloadRows =
                  recipeRows.length > 0
                    ? recipeRows.map((r) => ({ ingredient_id: r.ingredient_id, quantity_required: r.quantity_required }))
                    : [{ ingredient_id: recipeIngId || items[0]?.ingredient_id, quantity_required: recipeQty }];
                await api.put(`/inventory/recipes/${recipeFoodId || menuItems[0]?.id}`, {
                  yield_portions: Number(recipeYield) || 1,
                  ingredients: payloadRows,
                });
                pushToast("Recipe linked! Orders will automatically deduct stock.", "success");
                refreshAll();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Save Dish Recipe
          </Button>
        </Card>

        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 text-sm">Manual Stock Adjustment</h2>
          <Select value={adjItemId} onChange={(e) => setAdjItemId(e.target.value)}>
            <option value="">Select Inventory Item</option>
            {items.map((it) => (
              <option key={it.inventory_item_id} value={it.inventory_item_id}>
                {it.name} ({it.current_quantity} {it.unit})
              </option>
            ))}
          </Select>
          <Input value={adjDelta} onChange={(e) => setAdjDelta(e.target.value)} placeholder="Delta (+/- qty)" />
          <Input value={adjReason} onChange={(e) => setAdjReason(e.target.value)} placeholder="Reason" />
          <Button
            size="sm"
            variant="outline"
            className="w-full"
            onClick={async () => {
              try {
                await api.post("/inventory/adjustments", {
                  inventory_item_id: adjItemId || items[0]?.inventory_item_id,
                  quantity_delta: adjDelta,
                  reason: adjReason,
                });
                pushToast("Stock level adjusted", "success");
                refreshAll();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Apply Stock Adjustment
          </Button>
        </Card>
      </div>

      {/* Inter-Canteen Stock Transfer & Ledger */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 text-sm flex items-center gap-1.5">
            <ArrowRightLeft className="h-4 w-4 text-orange-600" /> Inter-Canteen Stock Transfer
          </h2>
          <Select value={transferToId} onChange={(e) => setTransferToId(e.target.value)}>
            <option value="">Destination Canteen</option>
            {canteens
              .filter((c) => c.id !== activeId)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </Select>
          <Select value={transferIngId} onChange={(e) => setTransferIngId(e.target.value)}>
            <option value="">Ingredient to Transfer</option>
            {items.map((it) => (
              <option key={it.ingredient_id} value={it.ingredient_id}>
                {it.name} ({it.current_quantity} {it.unit})
              </option>
            ))}
          </Select>
          <div className="grid grid-cols-2 gap-2">
            <Input value={transferQty} onChange={(e) => setTransferQty(e.target.value)} placeholder="Quantity" />
            <Input value={transferNotes} onChange={(e) => setTransferNotes(e.target.value)} placeholder="Notes (optional)" />
          </div>
          <Button
            size="sm"
            className="w-full"
            onClick={async () => {
              try {
                const dest = transferToId || canteens.find((c) => c.id !== activeId)?.id;
                if (!dest) return pushToast("Another canteen is required for transfer", "error");
                await api.post("/inventory/transfers", {
                  from_canteen_id: activeId,
                  to_canteen_id: dest,
                  ingredient_id: transferIngId || items[0]?.ingredient_id,
                  quantity: transferQty,
                  notes: transferNotes || null,
                });
                setTransferNotes("");
                pushToast("Stock transferred cleanly!", "success");
                refreshAll();
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Transfer Stock
          </Button>
        </Card>

        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900 text-sm flex items-center gap-1.5">
            <History className="h-4 w-4 text-slate-600" /> Recent Stock Movements ({movements.length})
          </h2>
          <div className="space-y-1.5 max-h-56 overflow-y-auto text-xs">
            {movements.map((mv) => (
              <div key={mv.id} className="flex items-center justify-between border-b border-slate-100 py-1.5">
                <div>
                  <span className="font-bold text-slate-800">{mv.ingredient_name}</span> •{" "}
                  <Badge tone={Number(mv.quantity_delta) >= 0 ? "green" : "amber"}>{mv.movement_type}</Badge>
                </div>
                <span className="font-mono">
                  {Number(mv.quantity_delta) > 0 ? `+${mv.quantity_delta}` : mv.quantity_delta} {mv.unit} (Bal: {mv.balance_after})
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
};
