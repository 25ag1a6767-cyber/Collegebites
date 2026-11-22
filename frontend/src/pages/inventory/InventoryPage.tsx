import React, { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Archive,
  ArrowRightLeft,
  CheckCircle2,
  Download,
  Edit3,
  History,
  IndianRupee,
  Plus,
  RotateCcw,
  Search,
  ShieldAlert,
  Trash2,
  Truck,
  Upload,
} from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useRealtimeSync } from "../../hooks/useRealtimeSync";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen } from "../../types";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, ConfirmModal, Input, Modal, Select, useToast } from "../../components/ui/Primitives";
import { RealtimeStatusBadge } from "../../components/ui/RealtimeStatusBadge";

type SectionTab = "all" | "items" | "menu" | "stock" | "pricing" | "suppliers" | "recipes" | "audit";

export const InventoryPage: React.FC = () => {
  const { user, selectedCanteenId } = useAppStore();
  const { pushToast } = useToast();
  const qc = useQueryClient();

  const canApproveSellingPrice = Boolean(
    user?.roles?.some((r) => ["super_admin", "college_admin", "canteen_manager"].includes(r))
  );
  const isSuperOrCollegeAdmin = Boolean(
    user?.roles?.some((r) => ["super_admin", "college_admin"].includes(r))
  );

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [canteenId, setCanteenId] = useState(user?.assigned_canteen_id || selectedCanteenId || "");
  useEffect(() => {
    if (!canteenId && canteens.length > 0) setCanteenId(canteens[0].id);
  }, [canteens, canteenId]);
  const activeId = canteenId || canteens[0]?.id || "";

  const [section, setSection] = useState<SectionTab>("all");
  const [search, setSearch] = useState("");
  const [catFilter, setCatFilter] = useState("all");
  const [stockFilter, setStockFilter] = useState("all");
  const [showArchived, setShowArchived] = useState(false);

  const { status: invSyncStatus, lastSyncedAt: invLastSyncedAt } = useRealtimeSync({
    enabled: Boolean(activeId),
    ssePath: activeId ? `/realtime/staff/orders/stream?canteen_id=${activeId}` : undefined,
    wsPath: activeId ? `/ws/kitchen/${activeId}` : undefined,
    queryKeys: [
      ["inv-dashboard"],
      ["inv-items"],
      ["inv-alerts"],
      ["inv-movements"],
      ["inv-audit-logs"],
      ["inv-wastage"],
      ["inv-adjustments"],
      ["inv-menu"],
    ],
  });

  const { data: dashboard, refetch: refetchDashboard, isError: dashError } = useQuery<any>({
    queryKey: ["inv-dashboard", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeId}/dashboard`)).data,
    refetchInterval: invSyncStatus === "live" ? 30000 : 10000,
  });

  const { data: items = [], refetch: refetchItems } = useQuery<any[]>({
    queryKey: ["inv-items", activeId, search, catFilter, stockFilter, showArchived],
    enabled: Boolean(activeId),
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (search.trim()) qs.set("search", search.trim());
      if (catFilter !== "all") qs.set("category", catFilter);
      if (stockFilter !== "all") qs.set("stock_status", stockFilter);
      if (showArchived) qs.set("include_archived", "true");
      return (await api.get(`/inventory/canteens/${activeId}/items?${qs.toString()}`)).data;
    },
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

  const { data: menuItems = [], refetch: refetchMenu } = useQuery<any[]>({
    queryKey: ["inv-menu", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/menus/canteens/${activeId}/items?include_inactive=true`)).data,
  });

  const { data: foodCategories = [], refetch: refetchFoodCategories } = useQuery<any[]>({
    queryKey: ["inv-food-categories", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/menus/canteens/${activeId}/categories?include_inactive=true`)).data,
  });

  const { data: movements = [], refetch: refetchMovements } = useQuery<any[]>({
    queryKey: ["inv-movements", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeId}/movements?limit=35`)).data,
  });

  const { data: priceChanges = [], refetch: refetchPrices } = useQuery<any[]>({
    queryKey: ["inv-price-changes", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeId}/price-changes`)).data,
  });

  const { data: auditLogs = [], refetch: refetchAudit } = useQuery<any[]>({
    queryKey: ["inv-audit-logs", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeId}/audit-logs?limit=50`)).data,
  });

  const { data: wastageRecords = [], refetch: refetchWastage } = useQuery<any[]>({
    queryKey: ["inv-wastage", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeId}/wastage?limit=40`)).data,
  });

  const { data: adjustmentRecords = [], refetch: refetchAdjustments } = useQuery<any[]>({
    queryKey: ["inv-adjustments", activeId],
    enabled: Boolean(activeId),
    queryFn: async () => (await api.get(`/inventory/canteens/${activeId}/adjustments?limit=40`)).data,
  });

  const refreshAll = () => {
    refetchDashboard();
    refetchItems();
    refetchAlerts();
    refetchPos();
    refetchMovements();
    refetchPrices();
    refetchAudit();
    refetchWastage();
    refetchAdjustments();
    refetchMenu();
    refetchFoodCategories();
    qc.invalidateQueries({ queryKey: ["menu-items"] });
    qc.invalidateQueries({ queryKey: ["categories"] });
    qc.invalidateQueries({ queryKey: ["smart-recs"] });
    qc.invalidateQueries({ queryKey: ["pos-menu"] });
    qc.invalidateQueries({ queryKey: ["kitchen-menu"] });
    qc.invalidateQueries({ queryKey: ["admin-menu"] });
    qc.invalidateQueries({ queryKey: ["admin-cats"] });
  };

  // Add Item Form State (Section 3.3)
  const [ingName, setIngName] = useState("");
  const [ingSku, setIngSku] = useState("");
  const [ingCategory, setIngCategory] = useState("Dry Goods");
  const [ingDescription, setIngDescription] = useState("");
  const [ingImageUrl, setIngImageUrl] = useState("");
  const [ingUnit, setIngUnit] = useState("grams");
  const [ingQty, setIngQty] = useState("1000");
  const [ingReorder, setIngReorder] = useState("200");
  const [ingCost, setIngCost] = useState("0.20");
  const [ingStorage, setIngStorage] = useState("Dry Rack A1");
  const [ingSupplierId, setIngSupplierId] = useState("");
  const [ingExpiry, setIngExpiry] = useState("");
  const [ingAvailable, setIngAvailable] = useState(true);
  const [ingAllergen, setIngAllergen] = useState(false);

  // Edit Item Modal State (Section 3.4)
  const [editItem, setEditItem] = useState<any | null>(null);
  const [editName, setEditName] = useState("");
  const [editCat, setEditCat] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editImg, setEditImg] = useState("");
  const [editUnit, setEditUnit] = useState("grams");
  const [editReorder, setEditReorder] = useState("100");
  const [editCost, setEditCost] = useState("0.00");
  const [editStorage, setEditStorage] = useState("");
  const [editSupId, setEditSupId] = useState("");
  const [editAvail, setEditAvail] = useState(true);
  const [editAllergen, setEditAllergen] = useState(false);
  const [editReason, setEditReason] = useState("");

  // Customer Menu Management State (Inventory Manager menu ops; selling price updates remain approval-gated)
  const [newMenuCatName, setNewMenuCatName] = useState("");
  const [newFoodCatId, setNewFoodCatId] = useState("");
  const [newFoodName, setNewFoodName] = useState("");
  const [newFoodDesc, setNewFoodDesc] = useState("");
  const [newFoodPrice, setNewFoodPrice] = useState("");
  const [newFoodPrepMins, setNewFoodPrepMins] = useState("10");
  const [newFoodVeg, setNewFoodVeg] = useState(true);
  const [editFood, setEditFood] = useState<any | null>(null);
  const [editFoodName, setEditFoodName] = useState("");
  const [editFoodCatId, setEditFoodCatId] = useState("");
  const [editFoodDesc, setEditFoodDesc] = useState("");
  const [editFoodPrepMins, setEditFoodPrepMins] = useState("10");
  const [editFoodVeg, setEditFoodVeg] = useState(true);
  const [editFoodAvail, setEditFoodAvail] = useState(true);
  const [editFoodActive, setEditFoodActive] = useState(true);
  const [uploadingFoodId, setUploadingFoodId] = useState<string | null>(null);

  // Item History Drawer / Modal
  const [historyItem, setHistoryItem] = useState<any | null>(null);
  const { data: itemAuditRows = [] } = useQuery<any[]>({
    queryKey: ["inv-item-audit", activeId, historyItem?.inventory_item_id],
    enabled: Boolean(activeId && historyItem?.inventory_item_id),
    queryFn: async () =>
      (
        await api.get(
          `/inventory/canteens/${activeId}/audit-logs?inventory_item_id=${historyItem.inventory_item_id}`
        )
      ).data,
  });

  // Archive Confirmation Modal (Section 3.5)
  const [archiveTarget, setArchiveTarget] = useState<any | null>(null);
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [deleteFoodTarget, setDeleteFoodTarget] = useState<any | null>(null);
  const [deleteFoodBusy, setDeleteFoodBusy] = useState(false);

  // 1-Click Restock Modal (Section 3.7)
  const [restockTarget, setRestockTarget] = useState<any | null>(null);
  const [restockQty, setRestockQty] = useState("500");
  const [restockCost, setRestockCost] = useState("");
  const [restockSupId, setRestockSupId] = useState("");
  const [restockExpiry, setRestockExpiry] = useState("");

  // Stock Management & Loss Form State (Section 3.5)
  const [adjInvId, setAdjInvId] = useState("");
  const [adjOpType, setAdjOpType] = useState<
    "add_stock" | "reduce_stock" | "damaged" | "expired" | "wastage"
  >("add_stock");
  const [adjQty, setAdjQty] = useState("");
  const [adjReason, setAdjReason] = useState("Physical stock count update");
  const [adjExpiry, setAdjExpiry] = useState("");

  // Transfer State
  const [trfIngId, setTrfIngId] = useState("");
  const [trfToCanteenId, setTrfToCanteenId] = useState("");
  const [trfQty, setTrfQty] = useState("50");
  const [trfNotes, setTrfNotes] = useState("Inter-canteen stock balancing");

  // Price Management State (Section 3.6)
  const [purInvId, setPurInvId] = useState("");
  const [purNewPrice, setPurNewPrice] = useState("");
  const [purReason, setPurReason] = useState("Supplier invoice rate revision");
  const [sellFoodId, setSellFoodId] = useState("");
  const [sellNewPrice, setSellNewPrice] = useState("");
  const [sellReason, setSellReason] = useState("Ingredient cost change");

  // Supplier & PO State
  const [supName, setSupName] = useState("");
  const [supPhone, setSupPhone] = useState("");
  const [supGst, setSupGst] = useState("");
  const [poSupplierId, setPoSupplierId] = useState("");
  const [poIngId, setPoIngId] = useState("");
  const [poQty, setPoQty] = useState("500");
  const [poCost, setPoCost] = useState("0.20");
  const [poExpiry, setPoExpiry] = useState("");

  // Recipe Builder State (multi-ingredient)
  const [recipeFoodId, setRecipeFoodId] = useState("");
  const [recipeYield, setRecipeYield] = useState("1");
  const [recipeRows, setRecipeRows] = useState<Array<{ ingredient_id: string; quantity_required: string }>>([
    { ingredient_id: "", quantity_required: "50" },
  ]);

  const activeRecipeFoodId = recipeFoodId || menuItems[0]?.id || "";
  useEffect(() => {
    if (!activeRecipeFoodId) return;
    let cancelled = false;
    api
      .get(`/inventory/recipes/${activeRecipeFoodId}`)
      .then((res) => {
        if (cancelled) return;
        setRecipeYield(String(res.data?.yield_portions || 1));
        const rows = (res.data?.ingredients || []).map((ri: any) => ({
          ingredient_id: ri.ingredient_id,
          quantity_required: String(ri.quantity_required),
        }));
        setRecipeRows(rows.length > 0 ? rows : [{ ingredient_id: "", quantity_required: "50" }]);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [activeRecipeFoodId]);

  const categories = useMemo(() => {
    const s = new Set<string>(["Dry Goods", "Dairy", "Vegetables", "Spices", "Beverages", "Packaging", "General"]);
    items.forEach((it) => {
      if (it.category) s.add(it.category);
    });
    return Array.from(s);
  }, [items]);

  const activeItems = useMemo(() => items.filter((i) => !i.is_archived), [items]);
  const selectedAdjItem = activeItems.find((i) => i.inventory_item_id === (adjInvId || activeItems[0]?.inventory_item_id));
  const selectedSellFood = menuItems.find((m) => m.id === (sellFoodId || menuItems[0]?.id));
  const selectedPurItem = activeItems.find((i) => i.inventory_item_id === (purInvId || activeItems[0]?.inventory_item_id));

  const downloadInventoryReport = async (fmt: "csv" | "pdf") => {
    if (!activeId) return;
    try {
      const res = await api.get(`/inventory/canteens/${activeId}/reports/${fmt}`, { responseType: "blob" });
      const blob = new Blob([res.data], { type: fmt === "csv" ? "text/csv" : "application/pdf" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `collegebites-inventory-report.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
      pushToast(`Inventory ${fmt.toUpperCase()} downloaded`, "success");
    } catch (err) {
      pushToast(getApiError(err, "Report download failed"), "error");
    }
  };

  const openEditModal = (it: any) => {
    setEditItem(it);
    setEditName(it.name || "");
    setEditCat(it.category || "General");
    setEditDesc(it.description || "");
    setEditImg(it.image_url || "");
    setEditUnit(it.unit || "grams");
    setEditReorder(String(it.reorder_level || "0"));
    setEditCost(String(it.unit_cost || "0.00"));
    setEditStorage(it.storage_location || "");
    setEditSupId(it.preferred_supplier_id || "");
    setEditAvail(Boolean(it.is_available));
    setEditAllergen(Boolean(it.is_allergen));
    setEditReason("");
  };

  const openRestockModal = (it: any) => {
    setRestockTarget(it);
    setRestockQty(String(it.suggested_restock_qty || Math.max(10, Number(it.reorder_level || 50))));
    setRestockCost(String(it.unit_cost || "0.00"));
    setRestockSupId(it.preferred_supplier_id || suppliers[0]?.id || "");
    setRestockExpiry("");
  };

  const showBlock = (key: SectionTab) => section === "all" || section === key;

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-[#380106] p-5 text-white">
        <div className="flex items-center gap-3">
          <BrandLogo size="md" variant="dark" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-extrabold">Inventory Manager Portal</h1>
              <RealtimeStatusBadge status={invSyncStatus} lastSyncedAt={invLastSyncedAt} darkSurface />
            </div>
            <p className="text-xs text-[#fdedce]/80">
              Real-time stock control, damaged/expired loss tracking, supplier POs, approval-gated selling prices &amp; audit logs
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={activeId}
            disabled={!isSuperOrCollegeAdmin && Boolean(user?.assigned_canteen_id)}
            onChange={(e) => setCanteenId(e.target.value)}
            className="w-52 bg-slate-800 border-slate-700 text-white"
          >
            {canteens.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Button
            size="sm"
            variant="outline"
            className="bg-slate-800 border-slate-700 text-white hover:bg-slate-700"
            onClick={() => downloadInventoryReport("csv")}
          >
            <Download className="h-3.5 w-3.5" /> CSV
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="bg-slate-800 border-slate-700 text-white hover:bg-slate-700"
            onClick={() => downloadInventoryReport("pdf")}
          >
            <Download className="h-3.5 w-3.5" /> PDF
          </Button>
        </div>
      </div>

      {/* Section Filter Pills */}
      <div className="flex flex-wrap gap-2">
        {(
          [
            { k: "all", l: "All Modules" },
            { k: "items", l: `All Inventory Items (${dashboard?.total_inventory_items ?? 0})` },
            { k: "menu", l: `Customer Menu (${menuItems.length})` },
            { k: "stock", l: "Stock Ops, Loss & Transfers" },
            {
              k: "pricing",
              l: `Price Management${
                (dashboard?.pending_price_requests_count || 0) > 0
                  ? ` (${dashboard.pending_price_requests_count} Pending)`
                  : ""
              }`,
            },
            { k: "suppliers", l: `Suppliers & POs (${pos.length})` },
            { k: "recipes", l: "Dish Recipes" },
            { k: "audit", l: `Audit & Reports (${auditLogs.length})` },
          ] as const
        ).map((t) => (
          <Button
            key={t.k}
            size="sm"
            variant={section === t.k ? "secondary" : "outline"}
            onClick={() => setSection(t.k)}
          >
            {t.l}
          </Button>
        ))}
      </div>

      {/* 3.1 Inventory Manager Dashboard KPIs (Real DB Records Only) */}
      {dashError ? (
        <Card className="p-4 border-red-200 bg-red-50 text-xs text-red-800">
          Failed to load live inventory metrics from the server.
        </Card>
      ) : (
        <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
          <Card className="p-3.5">
            <div className="text-[11px] font-bold uppercase text-slate-400">Active Items</div>
            <div className="text-xl font-black text-slate-900">{dashboard?.total_inventory_items ?? 0}</div>
            <div className="text-[11px] text-slate-500">{dashboard?.archived_items ?? 0} archived</div>
          </Card>
          <Card className="p-3.5 border-emerald-200 bg-emerald-50/40">
            <div className="text-[11px] font-bold uppercase text-emerald-700">Available Stock</div>
            <div className="text-xl font-black text-emerald-900">{dashboard?.available_items ?? 0}</div>
            <div className="text-[11px] text-emerald-700">Ready for kitchen</div>
          </Card>
          <Card className="p-3.5 border-amber-200 bg-amber-50/50">
            <div className="text-[11px] font-bold uppercase text-amber-800">Low Stock Alerts</div>
            <div className="text-xl font-black text-amber-900">{dashboard?.low_stock_alerts_count ?? 0}</div>
            <div className="text-[11px] text-amber-700">{dashboard?.out_of_stock_items ?? 0} out of stock</div>
          </Card>
          <Card className="p-3.5 border-red-200 bg-red-50/40">
            <div className="text-[11px] font-bold uppercase text-red-700">Damaged / Expired Loss</div>
            <div className="text-xl font-black text-red-900">₹{dashboard?.total_loss_amount ?? "0.00"}</div>
            <div className="text-[11px] text-red-700">
              {dashboard?.expiring_soon_count ?? 0} expiring soon ({dashboard?.expired_batches_count ?? 0} expired)
            </div>
          </Card>
          <Card className="p-3.5 border-blue-200 bg-blue-50/40">
            <div className="text-[11px] font-bold uppercase text-blue-700">Stock Valuation</div>
            <div className="text-xl font-black text-blue-900">₹{dashboard?.total_stock_valuation ?? "0.00"}</div>
            <div className="text-[11px] text-blue-700">Sum(qty × unit cost)</div>
          </Card>
          <Card className="p-3.5">
            <div className="text-[11px] font-bold uppercase text-slate-500">Price Approvals</div>
            <div className="text-xl font-black text-slate-900">{dashboard?.pending_price_requests_count ?? 0}</div>
            <div className="text-[11px] text-slate-500">Pending manager sign-off</div>
          </Card>
        </div>
      )}

      {/* 3.7 Low Stock Alerts + Blocked Menu Dishes + 1-Click Restock */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-4 border-amber-200 bg-amber-50/50">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2 font-bold text-amber-900 text-sm">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              Low-Stock Alerts ({dashboard?.low_stock_items?.length ?? 0}) & Blocked Dishes (
              {alerts?.blocked_food_items?.length ?? 0})
            </div>
          </div>
          {alerts?.blocked_food_items?.length > 0 && (
            <div className="mb-2 rounded-lg bg-red-100/80 px-3 py-1.5 text-xs font-bold text-red-900">
              Menu Dishes Auto-Blocked: {alerts.blocked_food_items.map((b: any) => b.name).join(", ")}
            </div>
          )}
          <div className="space-y-1.5 text-xs max-h-48 overflow-y-auto">
            {(!dashboard?.low_stock_items || dashboard.low_stock_items.length === 0) ? (
              <span className="text-amber-800">All active inventory items are above reorder levels.</span>
            ) : (
              dashboard.low_stock_items.map((l: any) => (
                <div
                  key={l.inventory_item_id}
                  className="flex items-center justify-between gap-2 rounded-lg bg-white/90 px-3 py-2 border border-amber-200"
                >
                  <div>
                    <div className="font-bold text-slate-900">{l.name} ({l.sku})</div>
                    <div className="text-slate-600">
                      Current: <span className="font-bold text-red-700">{l.current_quantity} {l.unit}</span> • Reorder at {l.reorder_level} {l.unit}
                    </div>
                  </div>
                  <Button size="sm" variant="primary" onClick={() => openRestockModal(l)}>
                    Quick Restock
                  </Button>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card className="p-4 border-red-200 bg-red-50/40">
          <div className="font-bold text-red-900 text-sm mb-2">
            Expiring Batches (Next 7 Days: {alerts?.expiring_soon?.length || 0}) & Loss Summary
          </div>
          <div className="grid grid-cols-3 gap-2 mb-2 text-[11px]">
            {(["damaged", "expired", "wastage"] as const).map((k) => {
              const row = dashboard?.loss_breakdown?.[k] || { quantity: "0.000", loss_amount: "0.00" };
              return (
                <div key={k} className="rounded-lg bg-white/90 border border-red-100 p-2">
                  <div className="font-bold uppercase text-red-700">{k}</div>
                  <div className="font-black text-slate-900">₹{row.loss_amount}</div>
                  <div className="text-slate-500">{row.quantity} units</div>
                </div>
              );
            })}
          </div>
          <div className="space-y-1 text-xs max-h-32 overflow-y-auto">
            {(alerts?.expiring_soon || []).length === 0 ? (
              <div className="text-slate-600">No batches expiring within the next 7 days.</div>
            ) : (
              alerts.expiring_soon.map((e: any, idx: number) => (
                <div key={idx} className="flex justify-between rounded bg-white/80 px-2.5 py-1 border border-red-100">
                  <span className="font-semibold">{e.ingredient_name} ({e.batch_number})</span>
                  <span className="font-mono text-red-700">
                    {e.remaining_quantity} • Exp: {e.expiry_date}
                  </span>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* 3.2 View All Inventory Items + 3.3 Add New Inventory Item */}
      {showBlock("items") && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="p-5 lg:col-span-2 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-bold text-slate-900">All Inventory Items ({items.length})</h2>
              <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showArchived}
                  onChange={(e) => setShowArchived(e.target.checked)}
                />
                Show Archived Items
              </label>
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              <div className="relative">
                <Search className="h-3.5 w-3.5 text-slate-400 absolute left-3 top-2.5" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search item, SKU, location..."
                  className="pl-8"
                />
              </div>
              <Select value={catFilter} onChange={(e) => setCatFilter(e.target.value)}>
                <option value="all">All Categories</option>
                {categories.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </Select>
              <Select value={stockFilter} onChange={(e) => setStockFilter(e.target.value)}>
                <option value="all">All Stock Status</option>
                <option value="in_stock">In Stock</option>
                <option value="low_stock">Low Stock</option>
                <option value="out_of_stock">Out of Stock</option>
              </Select>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-left text-slate-500">
                  <tr>
                    <th className="p-2.5">Item & Category</th>
                    <th className="p-2.5">Current Stock</th>
                    <th className="p-2.5">Purchase Cost</th>
                    <th className="p-2.5">Storage / Supplier</th>
                    <th className="p-2.5">Status</th>
                    <th className="p-2.5">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="p-6 text-center text-slate-500">
                        No inventory records available matching your filters.
                      </td>
                    </tr>
                  ) : (
                    items.map((it) => (
                      <tr key={it.inventory_item_id} className={it.is_archived ? "bg-slate-50/80 opacity-75" : ""}>
                        <td className="p-2.5">
                          <div className="font-bold text-slate-900">{it.name}</div>
                          <div className="text-[11px] text-slate-500 font-mono">
                            {it.sku} • {it.category}
                          </div>
                          {it.linked_food_items?.length > 0 && (
                            <div className="mt-0.5 text-[10px] text-blue-700">
                              Used in: {it.linked_food_items.map((d: any) => `${d.name} (₹${d.base_price})`).join(", ")}
                            </div>
                          )}
                        </td>
                        <td className="p-2.5 font-mono">
                          <div className="font-bold">
                            {it.current_quantity} {it.unit}
                          </div>
                          <div className="text-[10px] text-slate-500">Reorder ≤ {it.reorder_level}</div>
                        </td>
                        <td className="p-2.5 font-mono">
                          <div>₹{it.unit_cost}/{it.unit}</div>
                          <div className="text-[10px] text-slate-500">Val: ₹{it.stock_value}</div>
                        </td>
                        <td className="p-2.5">
                          <div>{it.storage_location || "—"}</div>
                          <div className="text-[10px] text-slate-500">{it.preferred_supplier_name || "No preferred supplier"}</div>
                        </td>
                        <td className="p-2.5 space-y-1">
                          {it.is_archived ? (
                            <Badge tone="slate">Archived</Badge>
                          ) : it.stock_status === "out_of_stock" ? (
                            <Badge tone="red">Out of Stock</Badge>
                          ) : it.stock_status === "low_stock" ? (
                            <Badge tone="amber">Low Stock</Badge>
                          ) : (
                            <Badge tone="green">In Stock</Badge>
                          )}
                          {!it.is_available && !it.is_archived && <Badge tone="red">Paused</Badge>}
                        </td>
                        <td className="p-2.5">
                          <div className="flex flex-wrap gap-1.5">
                            <Button size="sm" variant="outline" onClick={() => openEditModal(it)} title="Edit item">
                              <Edit3 className="h-3 w-3" />
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setHistoryItem(it)}
                              title="View item audit history"
                            >
                              <History className="h-3 w-3" />
                            </Button>
                            {!it.is_archived ? (
                              <>
                                {it.is_low_stock && (
                                  <Button size="sm" variant="primary" onClick={() => openRestockModal(it)}>
                                    Restock
                                  </Button>
                                )}
                                <Button
                                  size="sm"
                                  variant="danger"
                                  onClick={() => setArchiveTarget(it)}
                                  title="Archive item"
                                >
                                  <Archive className="h-3 w-3" />
                                </Button>
                              </>
                            ) : (
                              <Button
                                size="sm"
                                variant="success"
                                onClick={async () => {
                                  try {
                                    await api.post(`/inventory/items/${it.inventory_item_id}/restore`);
                                    pushToast(`${it.name} restored`, "success");
                                    refreshAll();
                                  } catch (err) {
                                    pushToast(getApiError(err), "error");
                                  }
                                }}
                                title="Restore item"
                              >
                                <RotateCcw className="h-3 w-3" />
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          {/* 3.3 Add New Inventory Item */}
          <Card className="p-5 space-y-2.5">
            <h2 className="font-bold text-slate-900 flex items-center gap-2">
              <Plus className="h-4 w-4 text-[#76010d]" /> Add Inventory Item
            </h2>
            <Input value={ingName} onChange={(e) => setIngName(e.target.value)} placeholder="Item Name (e.g. Mozzarella Cheese)" />
            <div className="grid grid-cols-2 gap-2">
              <Input value={ingSku} onChange={(e) => setIngSku(e.target.value)} placeholder="SKU (auto if blank)" />
              <Select value={ingCategory} onChange={(e) => setIngCategory(e.target.value)}>
                {categories.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </Select>
            </div>
            <Input value={ingDescription} onChange={(e) => setIngDescription(e.target.value)} placeholder="Description / Spec (optional)" />
            <Input value={ingImageUrl} onChange={(e) => setIngImageUrl(e.target.value)} placeholder="Image URL (optional)" />
            <div className="grid grid-cols-3 gap-2">
              <Select value={ingUnit} onChange={(e) => setIngUnit(e.target.value)}>
                {["grams", "kg", "ml", "liters", "pcs", "packs"].map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </Select>
              <Input type="number" min={0} step="0.01" value={ingQty} onChange={(e) => setIngQty(e.target.value)} placeholder="Initial Qty" />
              <Input type="number" min={0} step="0.01" value={ingReorder} onChange={(e) => setIngReorder(e.target.value)} placeholder="Reorder Lvl" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input type="number" min={0} step="0.01" value={ingCost} onChange={(e) => setIngCost(e.target.value)} placeholder="Purchase Cost ₹" />
              <Input value={ingStorage} onChange={(e) => setIngStorage(e.target.value)} placeholder="Storage Location" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Select value={ingSupplierId} onChange={(e) => setIngSupplierId(e.target.value)}>
                <option value="">Preferred Supplier (optional)</option>
                {suppliers.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </Select>
              <Input type="date" value={ingExpiry} onChange={(e) => setIngExpiry(e.target.value)} title="Initial batch expiry date" />
            </div>
            <div className="flex items-center justify-between text-xs pt-1">
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={ingAvailable} onChange={(e) => setIngAvailable(e.target.checked)} />
                Available immediately
              </label>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={ingAllergen} onChange={(e) => setIngAllergen(e.target.checked)} />
                Allergen ingredient
              </label>
            </div>
            <Button
              size="sm"
              className="w-full"
              disabled={!ingName.trim()}
              onClick={async () => {
                try {
                  await api.post("/inventory/ingredients", {
                    canteen_id: activeId,
                    name: ingName.trim(),
                    sku: ingSku.trim() || null,
                    category: ingCategory,
                    description: ingDescription.trim() || null,
                    image_url: ingImageUrl.trim() || null,
                    unit: ingUnit,
                    initial_quantity: ingQty || "0",
                    reorder_level: ingReorder || "0",
                    unit_cost: ingCost || "0.00",
                    storage_location: ingStorage.trim() || null,
                    preferred_supplier_id: ingSupplierId || null,
                    expiry_date: ingExpiry || null,
                    is_available: ingAvailable,
                    is_allergen: ingAllergen,
                  });
                  setIngName("");
                  setIngSku("");
                  setIngDescription("");
                  setIngImageUrl("");
                  pushToast("Inventory item created", "success");
                  refreshAll();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Item & Opening Batch
            </Button>
          </Card>
        </div>
      )}

      {/* 3.5 Stock Management (Add, Reduce, Damaged, Expired, Wastage), Inter-Canteen Transfer & Ledger */}
      {showBlock("stock") && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900">Manual Stock Adjustment</h2>
            <p className="text-[11px] text-slate-500">
              Add stock, reduce stock manually, or record damaged / expired / wastage losses. Negative stock is strictly blocked.
            </p>
            <Select value={adjInvId || activeItems[0]?.inventory_item_id || ""} onChange={(e) => setAdjInvId(e.target.value)}>
              {activeItems.map((it) => (
                <option key={it.inventory_item_id} value={it.inventory_item_id}>
                  {it.name} ({it.current_quantity} {it.unit})
                </option>
              ))}
            </Select>
            <Select value={adjOpType} onChange={(e) => setAdjOpType(e.target.value as any)}>
              <option value="add_stock">Add Stock (+)</option>
              <option value="reduce_stock">Reduce Stock (-)</option>
              <option value="damaged">Damaged Goods Loss (-)</option>
              <option value="expired">Expired Batch Write-off (-)</option>
              <option value="wastage">Prep / Spillage Wastage (-)</option>
            </Select>
            <Input
              type="number"
              min="0.001"
              step="0.01"
              value={adjQty}
              onChange={(e) => setAdjQty(e.target.value)}
              placeholder={`Quantity (${selectedAdjItem?.unit || "units"})`}
            />
            {adjOpType === "add_stock" && (
              <Input type="date" value={adjExpiry} onChange={(e) => setAdjExpiry(e.target.value)} placeholder="Batch Expiry (optional)" />
            )}
            <Input value={adjReason} onChange={(e) => setAdjReason(e.target.value)} placeholder="Reason / Audit Note" />
            <Button
              size="sm"
              variant={adjOpType === "add_stock" ? "primary" : "danger"}
              disabled={!selectedAdjItem || !adjQty}
              onClick={async () => {
                if (!selectedAdjItem) return;
                try {
                  const qtyNum = Math.abs(Number(adjQty));
                  if (adjOpType === "damaged" || adjOpType === "expired" || adjOpType === "wastage") {
                    await api.post("/inventory/wastage", {
                      inventory_item_id: selectedAdjItem.inventory_item_id,
                      quantity: qtyNum,
                      reason: adjReason,
                      operation_type: adjOpType,
                    });
                  } else {
                    await api.post("/inventory/adjustments", {
                      inventory_item_id: selectedAdjItem.inventory_item_id,
                      quantity_delta: adjOpType === "add_stock" ? qtyNum : -qtyNum,
                      operation_type: adjOpType,
                      reason: adjReason,
                      expiry_date: adjOpType === "add_stock" && adjExpiry ? adjExpiry : null,
                    });
                  }
                  setAdjQty("");
                  pushToast("Stock operation recorded", "success");
                  refreshAll();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Apply Stock Update
            </Button>
          </Card>

          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900 flex items-center gap-2">
              <ArrowRightLeft className="h-4 w-4 text-blue-600" /> Inter-Canteen Stock Transfer
            </h2>
            <Select value={trfIngId || activeItems[0]?.ingredient_id || ""} onChange={(e) => setTrfIngId(e.target.value)}>
              {activeItems.map((it) => (
                <option key={it.ingredient_id} value={it.ingredient_id}>
                  {it.name} ({it.current_quantity} {it.unit})
                </option>
              ))}
            </Select>
            <Select
              value={trfToCanteenId || canteens.find((c) => c.id !== activeId)?.id || ""}
              onChange={(e) => setTrfToCanteenId(e.target.value)}
            >
              {canteens
                .filter((c) => c.id !== activeId)
                .map((c) => (
                  <option key={c.id} value={c.id}>To: {c.name}</option>
                ))}
            </Select>
            <Input type="number" min="0.01" step="0.01" value={trfQty} onChange={(e) => setTrfQty(e.target.value)} placeholder="Quantity" />
            <Input value={trfNotes} onChange={(e) => setTrfNotes(e.target.value)} placeholder="Transfer notes" />
            <Button
              size="sm"
              variant="secondary"
              disabled={canteens.length < 2}
              onClick={async () => {
                const targetCanteen = trfToCanteenId || canteens.find((c) => c.id !== activeId)?.id;
                const ing = trfIngId || activeItems[0]?.ingredient_id;
                if (!targetCanteen || !ing) return;
                try {
                  await api.post("/inventory/transfers", {
                    from_canteen_id: activeId,
                    to_canteen_id: targetCanteen,
                    ingredient_id: ing,
                    quantity: trfQty,
                    notes: trfNotes,
                  });
                  pushToast("Stock transferred across canteens", "success");
                  refreshAll();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Transfer Non-Expired Stock
            </Button>
          </Card>

          <Card className="p-5 space-y-2.5">
            <h2 className="font-bold text-slate-900">Recent Stock Movements ({movements.length})</h2>
            <div className="space-y-1.5 max-h-64 overflow-y-auto text-xs">
              {movements.length === 0 ? (
                <div className="text-slate-500">No stock movements recorded yet.</div>
              ) : (
                movements.map((m) => (
                  <div key={m.id} className="rounded-lg border border-slate-100 px-3 py-2 flex items-center justify-between gap-2">
                    <div>
                      <span className="font-bold text-slate-900">{m.ingredient_name}</span>
                      <div className="text-[11px] text-slate-500">
                        <span className="uppercase font-semibold">{m.movement_type}</span> • {m.notes || m.reference_type}
                      </div>
                    </div>
                    <div className="text-right font-mono shrink-0">
                      <span className={Number(m.quantity_delta) < 0 ? "text-red-600 font-bold" : "text-emerald-700 font-bold"}>
                        {Number(m.quantity_delta) > 0 ? `+${m.quantity_delta}` : m.quantity_delta} {m.unit}
                      </span>
                      <div className="text-[10px] text-slate-400">Bal: {m.balance_after}</div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>
      )}

      {/* 3.6 Price Management: Purchase Cost Direct vs Approval-Gated Selling Prices */}
      {showBlock("pricing") && (
        <Card className="p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="font-bold text-slate-900 flex items-center gap-2">
                <IndianRupee className="h-4 w-4 text-[#76010d]" /> Price Management &amp; Selling Price Approvals
              </h2>
              <p className="text-xs text-slate-500">
                Purchase/cost updates apply immediately. Selling-price changes require Canteen Manager / College Admin approval before going live on menus; historical order prices never change.
              </p>
            </div>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* Purchase / Cost Price Form */}
            <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4 space-y-2.5">
              <div className="text-xs font-extrabold uppercase text-slate-700">1. Update Purchase / Cost Price (Immediate)</div>
              <Select value={purInvId || activeItems[0]?.inventory_item_id || ""} onChange={(e) => setPurInvId(e.target.value)}>
                {activeItems.map((it) => (
                  <option key={it.inventory_item_id} value={it.inventory_item_id}>
                    {it.name} (Current: ₹{it.unit_cost}/{it.unit})
                  </option>
                ))}
              </Select>
              <div className="grid grid-cols-2 gap-2">
                <Input
                  type="number"
                  min={0}
                  step="0.01"
                  value={purNewPrice}
                  onChange={(e) => setPurNewPrice(e.target.value)}
                  placeholder="New cost price ₹"
                />
                <Input value={purReason} onChange={(e) => setPurReason(e.target.value)} placeholder="Invoice / cost reason" />
              </div>
              <Button
                size="sm"
                variant="secondary"
                disabled={!selectedPurItem || !purNewPrice}
                onClick={async () => {
                  if (!selectedPurItem) return;
                  try {
                    await api.post(`/inventory/items/${selectedPurItem.inventory_item_id}/purchase-price`, {
                      new_purchase_price: purNewPrice,
                      reason: purReason || "Cost update",
                    });
                    setPurNewPrice("");
                    pushToast("Purchase cost updated & logged", "success");
                    refreshAll();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Save Purchase Cost
              </Button>
            </div>

            {/* Selling Price Change Request Form */}
            <div className="rounded-xl border border-[#76010d]/25 bg-[#fdf8f0] p-4 space-y-2.5">
              <div className="text-xs font-extrabold uppercase text-[#76010d]">
                2. Request Menu Selling Price Change (Approval-Gated)
              </div>
              <Select value={sellFoodId || menuItems[0]?.id || ""} onChange={(e) => setSellFoodId(e.target.value)}>
                {menuItems.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} (Live: ₹{m.base_price})
                  </option>
                ))}
              </Select>
              <div className="grid grid-cols-2 gap-2">
                <Input
                  type="number"
                  min="1"
                  step="0.01"
                  value={sellNewPrice}
                  onChange={(e) => setSellNewPrice(e.target.value)}
                  placeholder="Proposed price ₹"
                />
                <Input value={sellReason} onChange={(e) => setSellReason(e.target.value)} placeholder="Margin / cost justification" />
              </div>
              <Button
                size="sm"
                disabled={!selectedSellFood || !sellNewPrice}
                onClick={async () => {
                  if (!selectedSellFood) return;
                  try {
                    await api.post("/inventory/price-changes", {
                      canteen_id: activeId,
                      food_item_id: selectedSellFood.id,
                      new_price: sellNewPrice,
                      reason: sellReason || "Cost adjustment",
                    });
                    setSellNewPrice("");
                    pushToast("Selling price request submitted for manager approval", "success");
                    refreshAll();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Submit Selling Price Request
              </Button>
            </div>
          </div>

          {/* Price Change History & Manager Approvals Table */}
          <div className="space-y-2 pt-2 border-t border-slate-100">
            <div className="text-xs font-bold uppercase text-slate-500">
              Price Change Audit & Approval Queue ({priceChanges.length})
            </div>
            {priceChanges.length === 0 ? (
              <div className="text-xs text-slate-500 py-2">No price changes recorded for this canteen yet.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-left text-slate-500">
                    <tr>
                      <th className="p-2">Type</th>
                      <th className="p-2">Item / Dish</th>
                      <th className="p-2">Price Change</th>
                      <th className="p-2">Reason & By</th>
                      <th className="p-2">Status / Approval</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {priceChanges.map((p) => (
                      <tr key={p.id}>
                        <td className="p-2 font-bold uppercase">
                          {p.price_kind === "purchase_cost" ? "Purchase Cost" : "Selling Price"}
                        </td>
                        <td className="p-2 font-semibold">{p.food_item_name || p.ingredient_name || "—"}</td>
                        <td className="p-2 font-mono">
                          ₹{p.old_price} → <span className="font-bold text-slate-900">₹{p.new_price}</span>
                        </td>
                        <td className="p-2 text-slate-600">
                          <div>{p.reason}</div>
                          <div className="text-[10px] text-slate-400">
                            By {p.requested_by_name || "Staff"} {p.reviewed_by_name ? `• Reviewed by ${p.reviewed_by_name}` : ""}
                          </div>
                        </td>
                        <td className="p-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge
                              tone={
                                p.status === "approved" || p.status === "applied"
                                  ? "green"
                                  : p.status === "rejected"
                                  ? "red"
                                  : "amber"
                              }
                            >
                              {p.status}
                            </Badge>
                            {p.status === "pending_approval" && canApproveSellingPrice && (
                              <>
                                <Button
                                  size="sm"
                                  variant="success"
                                  onClick={async () => {
                                    try {
                                      await api.post(`/inventory/price-changes/${p.id}/review`, {
                                        decision: "approve",
                                        review_notes: "Approved from Inventory Portal",
                                      });
                                      pushToast("Selling price approved and live on menu", "success");
                                      refreshAll();
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
                                      await api.post(`/inventory/price-changes/${p.id}/review`, {
                                        decision: "reject",
                                        review_notes: "Rejected by manager",
                                      });
                                      pushToast("Selling price request rejected", "info");
                                      refreshAll();
                                    } catch (err) {
                                      pushToast(getApiError(err), "error");
                                    }
                                  }}
                                >
                                  Reject
                                </Button>
                              </>
                            )}
                            {p.status === "pending_approval" && !canApproveSellingPrice && (
                              <span className="text-[10px] text-amber-800 inline-flex items-center gap-1">
                                <ShieldAlert className="h-3 w-3" /> Manager approval required
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Suppliers & Purchase Orders */}
      {showBlock("suppliers") && (
        <div className="grid gap-6 md:grid-cols-2">
          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900 flex items-center gap-2">
              <Truck className="h-4 w-4 text-slate-700" /> Suppliers ({suppliers.length}) & Purchase Orders
            </h2>
            <div className="grid grid-cols-3 gap-2">
              <Input value={supName} onChange={(e) => setSupName(e.target.value)} placeholder="Supplier Name" />
              <Input value={supPhone} onChange={(e) => setSupPhone(e.target.value)} placeholder="Phone" />
              <Input value={supGst} onChange={(e) => setSupGst(e.target.value)} placeholder="GST (optional)" />
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={!supName.trim()}
              onClick={async () => {
                try {
                  await api.post("/inventory/suppliers", {
                    name: supName.trim(),
                    phone: supPhone.trim() || null,
                    gst_number: supGst.trim() || null,
                  });
                  setSupName("");
                  setSupPhone("");
                  setSupGst("");
                  refetchSuppliers();
                  pushToast("Supplier added", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Supplier
            </Button>

            <div className="border-t border-slate-100 pt-3 space-y-2">
              <div className="text-xs font-bold text-slate-500 uppercase">Create Purchase Order</div>
              <div className="grid grid-cols-2 gap-2">
                <Select value={poSupplierId || suppliers[0]?.id || ""} onChange={(e) => setPoSupplierId(e.target.value)}>
                  {suppliers.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </Select>
                <Select value={poIngId || activeItems[0]?.ingredient_id || ""} onChange={(e) => setPoIngId(e.target.value)}>
                  {activeItems.map((it) => (
                    <option key={it.ingredient_id} value={it.ingredient_id}>{it.name}</option>
                  ))}
                </Select>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <Input type="number" min="0.01" step="0.01" value={poQty} onChange={(e) => setPoQty(e.target.value)} placeholder="Qty" />
                <Input type="number" min="0" step="0.01" value={poCost} onChange={(e) => setPoCost(e.target.value)} placeholder="Unit Cost ₹" />
                <Input type="date" value={poExpiry} onChange={(e) => setPoExpiry(e.target.value)} />
              </div>
              <Button
                size="sm"
                variant="secondary"
                disabled={suppliers.length === 0 || activeItems.length === 0}
                onClick={async () => {
                  try {
                    await api.post("/inventory/purchase-orders", {
                      canteen_id: activeId,
                      supplier_id: poSupplierId || suppliers[0]?.id,
                      items: [
                        {
                          ingredient_id: poIngId || activeItems[0]?.ingredient_id,
                          quantity_ordered: poQty,
                          unit_cost: poCost,
                          expiry_date: poExpiry || null,
                        },
                      ],
                    });
                    pushToast("Purchase order created", "success");
                    refetchPos();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Create Purchase Order
              </Button>
            </div>
          </Card>

          <Card className="p-5 space-y-2.5">
            <h2 className="font-bold text-slate-900">Purchase Orders ({pos.length})</h2>
            <div className="space-y-2 max-h-72 overflow-y-auto">
              {pos.length === 0 ? (
                <div className="text-xs text-slate-500">No purchase orders created yet.</div>
              ) : (
                pos.map((po) => (
                  <div key={po.id} className="flex items-center justify-between rounded-xl border border-slate-100 p-3 text-xs">
                    <div>
                      <div className="font-mono font-bold text-slate-900">{po.po_number}</div>
                      <div className="text-slate-500">Total Cost: ₹{po.total_cost}</div>
                    </div>
                    {po.status === "received" ? (
                      <Badge tone="green">
                        <CheckCircle2 className="h-3 w-3" /> Received
                      </Badge>
                    ) : po.status === "cancelled" ? (
                      <Badge tone="red">Cancelled</Badge>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <Button
                          size="sm"
                          variant="success"
                          onClick={async () => {
                            try {
                              await api.post(`/inventory/purchase-orders/${po.id}/receive`);
                              pushToast(`Received ${po.po_number} — Stock & Batches Updated!`, "success");
                              refreshAll();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Receive Stock
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            try {
                              await api.post(`/inventory/purchase-orders/${po.id}/cancel?reason=Cancelled%20from%20Inventory%20Portal`);
                              pushToast(`Cancelled ${po.po_number}`, "info");
                              refetchPos();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Cancel
                        </Button>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>
      )}

      {/* Dish Recipes & Field-Level Audit History */}
      <div className="grid gap-6 md:grid-cols-2">
        {showBlock("recipes") && (
          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900">Link Dish Recipe (Auto Stock Deduction)</h2>
            <p className="text-xs text-slate-500">
              When orders are paid/confirmed, mapped ingredients automatically deduct via FEFO batch tracking.
            </p>
            <Select value={recipeFoodId || menuItems[0]?.id || ""} onChange={(e) => setRecipeFoodId(e.target.value)}>
              {menuItems.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </Select>
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold text-slate-600">Recipe Ingredients &amp; Yield Portions</div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-slate-500">Yield:</span>
                <Input
                  type="number"
                  min={1}
                  value={recipeYield}
                  onChange={(e) => setRecipeYield(e.target.value)}
                  className="w-20"
                  placeholder="Yield"
                />
              </div>
            </div>
            <div className="space-y-2">
              {recipeRows.map((row, idx) => (
                <div key={idx} className="grid grid-cols-12 gap-2 items-center">
                  <div className="col-span-7">
                    <Select
                      value={row.ingredient_id || activeItems[0]?.ingredient_id || ""}
                      onChange={(e) =>
                        setRecipeRows((prev) =>
                          prev.map((r, i) => (i === idx ? { ...r, ingredient_id: e.target.value } : r))
                        )
                      }
                    >
                      {activeItems.map((it) => (
                        <option key={it.ingredient_id} value={it.ingredient_id}>
                          {it.name} ({it.unit})
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="col-span-3">
                    <Input
                      type="number"
                      min="0.001"
                      step="0.01"
                      value={row.quantity_required}
                      onChange={(e) =>
                        setRecipeRows((prev) =>
                          prev.map((r, i) => (i === idx ? { ...r, quantity_required: e.target.value } : r))
                        )
                      }
                      placeholder="Qty"
                    />
                  </div>
                  <div className="col-span-2 flex justify-end">
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={recipeRows.length <= 1}
                      onClick={() => setRecipeRows((prev) => prev.filter((_, i) => i !== idx))}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-red-600" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={activeItems.length === 0}
                onClick={() =>
                  setRecipeRows((prev) => [
                    ...prev,
                    { ingredient_id: activeItems[0]?.ingredient_id || "", quantity_required: "10" },
                  ])
                }
              >
                <Plus className="h-3.5 w-3.5" /> Add Ingredient
              </Button>
              <Button
                size="sm"
                disabled={menuItems.length === 0 || activeItems.length === 0}
                onClick={async () => {
                  try {
                    const cleanRows = recipeRows.map((r) => ({
                      ingredient_id: r.ingredient_id || activeItems[0]?.ingredient_id,
                      quantity_required: r.quantity_required,
                    }));
                    await api.put(`/inventory/recipes/${activeRecipeFoodId}`, {
                      yield_portions: Number(recipeYield) || 1,
                      ingredients: cleanRows,
                    });
                    pushToast("Multi-ingredient recipe updated", "success");
                    refreshAll();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Save Dish Recipe
              </Button>
            </div>
          </Card>
        )}

        {showBlock("audit") && (
          <Card className="p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-slate-900">Inventory Audit, Wastage &amp; Adjustments</h2>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => downloadInventoryReport("csv")}>
                  <Download className="h-3.5 w-3.5" /> Export CSV
                </Button>
                <Button size="sm" variant="outline" onClick={() => downloadInventoryReport("pdf")}>
                  <Download className="h-3.5 w-3.5" /> Export PDF
                </Button>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1.5 max-h-60 overflow-y-auto text-xs">
                <div className="text-[11px] font-bold uppercase text-slate-500">Audit Log ({auditLogs.length})</div>
                {auditLogs.length === 0 ? (
                  <div className="text-slate-500">No inventory edit or price audit records yet.</div>
                ) : (
                  auditLogs.map((a) => (
                    <div key={a.id} className="rounded-lg border border-slate-100 px-3 py-2">
                      <div className="flex justify-between font-semibold text-slate-900">
                        <span>
                          {a.ingredient_name || "Menu/Canteen"} • <span className="uppercase">{a.action}</span>
                        </span>
                        <span className="text-[10px] text-slate-400">{a.created_at?.slice(0, 16)}</span>
                      </div>
                      <div className="text-[11px] text-slate-600">
                        {a.field_name}: {a.old_value ?? "—"} → <span className="font-bold">{a.new_value ?? "—"}</span>
                        {a.reason ? ` (${a.reason})` : ""}
                      </div>
                      <div className="text-[10px] text-slate-400">By: {a.changed_by_name || "Staff"}</div>
                    </div>
                  ))
                )}
              </div>
              <div className="space-y-2 max-h-60 overflow-y-auto text-xs">
                <div className="text-[11px] font-bold uppercase text-slate-500">
                  Wastage ({wastageRecords.length}) &amp; Adjustments ({adjustmentRecords.length})
                </div>
                {wastageRecords.map((w) => (
                  <div key={w.id} className="rounded-lg border border-red-100 bg-red-50/40 px-3 py-1.5">
                    <div className="flex justify-between font-semibold text-red-900">
                      <span>{w.ingredient_name} • {w.loss_type.toUpperCase()}</span>
                      <span>-₹{w.estimated_loss} ({w.quantity} {w.unit})</span>
                    </div>
                    <div className="text-[11px] text-red-700">{w.reason}</div>
                  </div>
                ))}
                {adjustmentRecords.map((adj) => (
                  <div key={adj.id} className="rounded-lg border border-slate-100 px-3 py-1.5">
                    <div className="flex justify-between font-semibold text-slate-900">
                      <span>{adj.ingredient_name}</span>
                      <span className={Number(adj.quantity_delta) < 0 ? "text-amber-700" : "text-emerald-700"}>
                        {Number(adj.quantity_delta) > 0 ? `+${adj.quantity_delta}` : adj.quantity_delta} {adj.unit}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-600">{adj.reason}</div>
                  </div>
                ))}
                {wastageRecords.length === 0 && adjustmentRecords.length === 0 && (
                  <div className="text-slate-500">No wastage or manual adjustments recorded yet.</div>
                )}
              </div>
            </div>
          </Card>
        )}
      </div>

      {/* Customer-Facing Menu Management (Add Items, Categories, Images & Availability; Selling Prices Approval-Gated) */}
      {showBlock("menu") && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="p-5 lg:col-span-2 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <BrandLogo size="xs" />
                <h2 className="font-bold text-slate-900">Customer Menu Catalog ({menuItems.length})</h2>
              </div>
              <Badge tone="amber">Selling Price Changes Approval-Gated</Badge>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-left text-slate-500">
                  <tr>
                    <th className="p-2">Dish</th>
                    <th className="p-2">Category</th>
                    <th className="p-2">Live Selling Price</th>
                    <th className="p-2">Status</th>
                    <th className="p-2">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {menuItems.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="p-4 text-center text-slate-500">
                        No food items configured for this canteen yet.
                      </td>
                    </tr>
                  ) : (
                    menuItems.map((m) => (
                      <tr key={m.id}>
                        <td className="p-2">
                          <div className="flex items-center gap-2">
                            {m.images?.[0]?.image_url ? (
                              <img
                                src={m.images[0].image_url}
                                alt={m.name}
                                className="h-8 w-8 rounded-lg object-cover border border-slate-200"
                              />
                            ) : (
                              <div className="h-8 w-8 rounded-lg bg-slate-100 flex items-center justify-center text-[10px] text-slate-400">
                                No Img
                              </div>
                            )}
                            <div>
                              <div className="font-bold text-slate-900">{m.name}</div>
                              <div className="text-[10px] text-slate-500">
                                {m.is_veg ? "Veg" : "Non-Veg"} • {m.prep_time_minutes}m prep
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="p-2">{m.category_name || "—"}</td>
                        <td className="p-2 font-extrabold text-slate-900">₹{m.base_price}</td>
                        <td className="p-2">
                          <Badge tone={m.is_active && m.is_available ? "green" : "red"}>
                            {!m.is_active ? "Archived" : m.is_available ? "Available" : "Out of Stock"}
                          </Badge>
                        </td>
                        <td className="p-2">
                          <div className="flex flex-wrap gap-1.5">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setEditFood(m);
                                setEditFoodName(m.name);
                                setEditFoodCatId(m.category_id);
                                setEditFoodDesc(m.description || "");
                                setEditFoodPrepMins(String(m.prep_time_minutes || 10));
                                setEditFoodVeg(Boolean(m.is_veg));
                                setEditFoodAvail(Boolean(m.is_available));
                                setEditFoodActive(Boolean(m.is_active));
                              }}
                            >
                              <Edit3 className="h-3 w-3" /> Edit
                            </Button>
                            <label className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-bold text-slate-700 hover:bg-slate-50">
                              <Upload className="h-3 w-3" />
                              {uploadingFoodId === m.id ? "Uploading..." : "Photo"}
                              <input
                                type="file"
                                accept="image/png,image/jpeg,image/webp"
                                className="hidden"
                                disabled={uploadingFoodId === m.id}
                                onChange={async (e) => {
                                  const file = e.target.files?.[0];
                                  e.target.value = "";
                                  if (!file) return;
                                  setUploadingFoodId(m.id);
                                  try {
                                    const fd = new FormData();
                                    fd.append("file", file);
                                    await api.post(`/menus/items/${m.id}/upload-image`, fd, {
                                      headers: { "Content-Type": "multipart/form-data" },
                                    });
                                    pushToast(`Updated image for ${m.name}`, "success");
                                    refreshAll();
                                  } catch (err) {
                                    pushToast(getApiError(err, "Image upload failed"), "error");
                                  } finally {
                                    setUploadingFoodId(null);
                                  }
                                }}
                              />
                            </label>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={async () => {
                                try {
                                  await api.patch(`/menus/items/${m.id}`, { is_available: !m.is_available });
                                  pushToast(`${m.name} marked ${!m.is_available ? "Available" : "Unavailable"}`, "success");
                                  refreshAll();
                                } catch (err) {
                                  pushToast(getApiError(err), "error");
                                }
                              }}
                            >
                              {m.is_available ? "Pause" : "Enable"}
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              onClick={() => setDeleteFoodTarget(m)}
                              title="Delete Dish"
                              aria-label={`Delete ${m.name}`}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          <Card className="p-5 space-y-4">
            <div className="space-y-2 border-b border-slate-100 pb-3">
              <div className="text-xs font-extrabold uppercase text-slate-600">Add Menu Category</div>
              <div className="flex gap-2">
                <Input
                  value={newMenuCatName}
                  onChange={(e) => setNewMenuCatName(e.target.value)}
                  placeholder="e.g. Beverages"
                />
                <Button
                  size="sm"
                  disabled={!newMenuCatName.trim()}
                  onClick={async () => {
                    const slug = newMenuCatName
                      .trim()
                      .toLowerCase()
                      .replace(/[^a-z0-9]+/g, "-")
                      .replace(/^-|-$/g, "");
                    try {
                      const created = await api.post("/menus/categories", {
                        canteen_id: activeId,
                        name: newMenuCatName.trim(),
                        slug: slug || `cat-${Date.now()}`,
                      });
                      setNewMenuCatName("");
                      setNewFoodCatId(created.data.id);
                      pushToast("Menu category created", "success");
                      refreshAll();
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  Add
                </Button>
              </div>
            </div>

            <div className="space-y-2.5 text-xs">
              <div className="font-extrabold uppercase text-slate-600">Add Customer Menu Item</div>
              <Select value={newFoodCatId || foodCategories[0]?.id || ""} onChange={(e) => setNewFoodCatId(e.target.value)}>
                <option value="">Select Category</option>
                {foodCategories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </Select>
              <Input value={newFoodName} onChange={(e) => setNewFoodName(e.target.value)} placeholder="Dish Name *" />
              <Input value={newFoodDesc} onChange={(e) => setNewFoodDesc(e.target.value)} placeholder="Short description" />
              <div className="grid grid-cols-2 gap-2">
                <Input
                  type="number"
                  min="1"
                  step="0.01"
                  value={newFoodPrice}
                  onChange={(e) => setNewFoodPrice(e.target.value)}
                  placeholder="Initial Price ₹ *"
                />
                <Input
                  type="number"
                  min="1"
                  max="180"
                  value={newFoodPrepMins}
                  onChange={(e) => setNewFoodPrepMins(e.target.value)}
                  placeholder="Prep mins"
                />
              </div>
              <label className="flex items-center gap-2 font-semibold text-slate-700">
                <input type="checkbox" checked={newFoodVeg} onChange={(e) => setNewFoodVeg(e.target.checked)} />
                Vegetarian Dish
              </label>
              <Button
                className="w-full"
                disabled={!newFoodName.trim() || !newFoodPrice || !(newFoodCatId || foodCategories[0]?.id)}
                onClick={async () => {
                  const catId = newFoodCatId || foodCategories[0]?.id;
                  if (!catId) return;
                  const slug = `${newFoodName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}-${Date.now().toString().slice(-4)}`;
                  try {
                    await api.post("/menus/items", {
                      canteen_id: activeId,
                      category_id: catId,
                      name: newFoodName.trim(),
                      slug,
                      description: newFoodDesc.trim() || null,
                      base_price: newFoodPrice,
                      prep_time_minutes: Number(newFoodPrepMins) || 10,
                      is_veg: newFoodVeg,
                    });
                    setNewFoodName("");
                    setNewFoodDesc("");
                    setNewFoodPrice("");
                    pushToast("Food item added to customer menu", "success");
                    refreshAll();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                <Plus className="h-3.5 w-3.5" /> Add Menu Item
              </Button>
            </div>
          </Card>
        </div>
      )}

      {/* Edit Menu Item Modal (Non-Price Fields; Selling Price Redirects to Approval Workflow) */}
      <Modal
        open={Boolean(editFood)}
        onClose={() => setEditFood(null)}
        title={`Edit Menu Dish: ${editFood?.name || ""}`}
        maxWidth="max-w-md"
      >
        {editFood && (
          <div className="space-y-3 text-xs">
            <div>
              <label className="font-bold text-slate-600 block mb-1">Dish Name</label>
              <Input value={editFoodName} onChange={(e) => setEditFoodName(e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="font-bold text-slate-600 block mb-1">Category</label>
                <Select value={editFoodCatId} onChange={(e) => setEditFoodCatId(e.target.value)}>
                  {foodCategories.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </Select>
              </div>
              <div>
                <label className="font-bold text-slate-600 block mb-1">Prep Time (mins)</label>
                <Input type="number" min={1} max={180} value={editFoodPrepMins} onChange={(e) => setEditFoodPrepMins(e.target.value)} />
              </div>
            </div>
            <div>
              <label className="font-bold text-slate-600 block mb-1">Description</label>
              <Input value={editFoodDesc} onChange={(e) => setEditFoodDesc(e.target.value)} />
            </div>
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 flex items-center justify-between">
              <div>
                <div className="font-bold text-amber-900">Selling Price: ₹{editFood.base_price}</div>
                <div className="text-[11px] text-amber-800">Changes require Canteen Manager / Admin approval</div>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setSellFoodId(editFood.id);
                  setEditFood(null);
                  setSection("pricing");
                }}
              >
                Request Price Change
              </Button>
            </div>
            <div className="flex gap-4">
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={editFoodVeg} onChange={(e) => setEditFoodVeg(e.target.checked)} />
                Veg
              </label>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={editFoodAvail} onChange={(e) => setEditFoodAvail(e.target.checked)} />
                Available
              </label>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={editFoodActive} onChange={(e) => setEditFoodActive(e.target.checked)} />
                Active (Uncheck to Archive)
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button size="sm" variant="outline" onClick={() => setEditFood(null)}>Cancel</Button>
              <Button
                size="sm"
                onClick={async () => {
                  try {
                    await api.patch(`/menus/items/${editFood.id}`, {
                      name: editFoodName.trim(),
                      category_id: editFoodCatId,
                      description: editFoodDesc.trim() || null,
                      prep_time_minutes: Number(editFoodPrepMins) || 10,
                      is_veg: editFoodVeg,
                      is_available: editFoodAvail,
                      is_active: editFoodActive,
                    });
                    setEditFood(null);
                    pushToast("Menu item updated", "success");
                    refreshAll();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Save Menu Item
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Edit Item Modal (Section 3.4) */}
      <Modal
        open={Boolean(editItem)}
        onClose={() => setEditItem(null)}
        title={`Edit Inventory Item: ${editItem?.name || ""}`}
        maxWidth="max-w-lg"
      >
        {editItem && (
          <div className="space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="font-bold text-slate-600 block mb-1">Item Name</label>
                <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
              </div>
              <div>
                <label className="font-bold text-slate-600 block mb-1">Category</label>
                <Select value={editCat} onChange={(e) => setEditCat(e.target.value)}>
                  {categories.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </Select>
              </div>
            </div>
            <div>
              <label className="font-bold text-slate-600 block mb-1">Description</label>
              <Input value={editDesc} onChange={(e) => setEditDesc(e.target.value)} placeholder="Description" />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="font-bold text-slate-600 block mb-1">Unit</label>
                <Select value={editUnit} onChange={(e) => setEditUnit(e.target.value)}>
                  {["grams", "kg", "ml", "liters", "pcs", "packs"].map((u) => (
                    <option key={u} value={u}>{u}</option>
                  ))}
                </Select>
              </div>
              <div>
                <label className="font-bold text-slate-600 block mb-1">Reorder Level</label>
                <Input type="number" min={0} step="0.01" value={editReorder} onChange={(e) => setEditReorder(e.target.value)} />
              </div>
              <div>
                <label className="font-bold text-slate-600 block mb-1">Purchase Cost ₹</label>
                <Input type="number" min={0} step="0.01" value={editCost} onChange={(e) => setEditCost(e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="font-bold text-slate-600 block mb-1">Storage Location</label>
                <Input value={editStorage} onChange={(e) => setEditStorage(e.target.value)} placeholder="Freezer B2" />
              </div>
              <div>
                <label className="font-bold text-slate-600 block mb-1">Preferred Supplier</label>
                <Select value={editSupId} onChange={(e) => setEditSupId(e.target.value)}>
                  <option value="">None</option>
                  {suppliers.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </Select>
              </div>
            </div>
            <div>
              <label className="font-bold text-slate-600 block mb-1">Image URL</label>
              <Input value={editImg} onChange={(e) => setEditImg(e.target.value)} placeholder="https://..." />
            </div>
            <div className="flex gap-4">
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={editAvail} onChange={(e) => setEditAvail(e.target.checked)} />
                Available
              </label>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={editAllergen} onChange={(e) => setEditAllergen(e.target.checked)} />
                Allergen
              </label>
            </div>
            <Input value={editReason} onChange={(e) => setEditReason(e.target.value)} placeholder="Audit reason for edit (optional)" />
            <div className="flex justify-end gap-2 pt-2">
              <Button size="sm" variant="outline" onClick={() => setEditItem(null)}>Cancel</Button>
              <Button
                size="sm"
                onClick={async () => {
                  try {
                    await api.patch(`/inventory/items/${editItem.inventory_item_id}`, {
                      name: editName.trim() || null,
                      category: editCat,
                      description: editDesc.trim() || null,
                      image_url: editImg.trim() || null,
                      unit: editUnit,
                      reorder_level: editReorder,
                      unit_cost: editCost,
                      storage_location: editStorage.trim() || null,
                      preferred_supplier_id: editSupId || null,
                      is_available: editAvail,
                      is_allergen: editAllergen,
                      reason: editReason.trim() || null,
                    });
                    setEditItem(null);
                    pushToast("Item updated & audited", "success");
                    refreshAll();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Save Changes
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Item Audit History Modal */}
      <Modal
        open={Boolean(historyItem)}
        onClose={() => setHistoryItem(null)}
        title={`Audit History: ${historyItem?.name || ""}`}
        maxWidth="max-w-lg"
      >
        <div className="space-y-2 max-h-80 overflow-y-auto text-xs">
          {itemAuditRows.length === 0 ? (
            <div className="text-slate-500">No changes logged for this item yet.</div>
          ) : (
            itemAuditRows.map((r) => (
              <div key={r.id} className="rounded-lg border border-slate-100 p-2.5">
                <div className="flex justify-between font-bold">
                  <span className="uppercase">{r.action} • {r.field_name}</span>
                  <span className="text-[10px] text-slate-400">{r.created_at?.slice(0, 16)}</span>
                </div>
                <div className="text-slate-700 mt-0.5">
                  {r.old_value ?? "—"} → <span className="font-bold">{r.new_value ?? "—"}</span>
                </div>
                {r.reason && <div className="text-slate-500">Reason: {r.reason}</div>}
                <div className="text-[10px] text-slate-400">By: {r.changed_by_name || "Staff"}</div>
              </div>
            ))
          )}
        </div>
      </Modal>

      {/* 1-Click Restock Modal (Section 3.7) */}
      <Modal
        open={Boolean(restockTarget)}
        onClose={() => setRestockTarget(null)}
        title={`Quick Restock: ${restockTarget?.name || ""}`}
        maxWidth="max-w-md"
      >
        {restockTarget && (
          <div className="space-y-3 text-xs">
            <div className="rounded-lg bg-amber-50 border border-amber-200 p-2.5">
              Current Stock: <strong>{restockTarget.current_quantity} {restockTarget.unit}</strong> • Reorder Level: <strong>{restockTarget.reorder_level} {restockTarget.unit}</strong>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="font-bold block mb-1">Restock Quantity ({restockTarget.unit})</label>
                <Input type="number" min="0.01" step="0.01" value={restockQty} onChange={(e) => setRestockQty(e.target.value)} />
              </div>
              <div>
                <label className="font-bold block mb-1">Unit Cost ₹</label>
                <Input type="number" min={0} step="0.01" value={restockCost} onChange={(e) => setRestockCost(e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="font-bold block mb-1">Supplier</label>
                <Select value={restockSupId} onChange={(e) => setRestockSupId(e.target.value)}>
                  <option value="">Direct Stock Add</option>
                  {suppliers.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </Select>
              </div>
              <div>
                <label className="font-bold block mb-1">Batch Expiry</label>
                <Input type="date" value={restockExpiry} onChange={(e) => setRestockExpiry(e.target.value)} />
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setRestockTarget(null)}>Cancel</Button>
              <Button
                size="sm"
                variant="primary"
                onClick={async () => {
                  try {
                    await api.post(`/inventory/items/${restockTarget.inventory_item_id}/restock`, {
                      quantity: restockQty,
                      unit_cost: restockCost || null,
                      supplier_id: restockSupId || null,
                      expiry_date: restockExpiry || null,
                    });
                    setRestockTarget(null);
                    pushToast("Item restocked & alert updated", "success");
                    refreshAll();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Confirm Restock
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Archive Confirmation Modal (Section 3.5) */}
      <ConfirmModal
        open={Boolean(archiveTarget)}
        title={`Archive "${archiveTarget?.name || ""}"?`}
        message="Archiving removes this inventory item from active kitchen/inventory lists without corrupting historical stock movements or past orders. Items used in open active orders cannot be archived."
        confirmLabel="Archive Item"
        confirmVariant="danger"
        busy={archiveBusy}
        onCancel={() => setArchiveTarget(null)}
        onConfirm={async () => {
          if (!archiveTarget) return;
          setArchiveBusy(true);
          try {
            await api.post(`/inventory/items/${archiveTarget.inventory_item_id}/archive`, {
              reason: "Archived by inventory manager",
            });
            setArchiveTarget(null);
            pushToast("Inventory item archived cleanly", "info");
            refreshAll();
          } catch (err) {
            pushToast(getApiError(err), "error");
          } finally {
            setArchiveBusy(false);
          }
        }}
      />

      <ConfirmModal
        open={Boolean(deleteFoodTarget)}
        title={`Delete "${deleteFoodTarget?.name || ""}"?`}
        message="Menu dishes with no past orders are deleted permanently. Dishes referenced in past customer orders are archived and removed from the live menu cleanly."
        confirmLabel="Delete Dish"
        confirmVariant="danger"
        busy={deleteFoodBusy}
        onCancel={() => setDeleteFoodTarget(null)}
        onConfirm={async () => {
          if (!deleteFoodTarget) return;
          setDeleteFoodBusy(true);
          try {
            const res = await api.delete(`/menus/items/${deleteFoodTarget.id}`);
            setDeleteFoodTarget(null);
            pushToast(res.data?.message || "Dish removed from menu", "info");
            refreshAll();
          } catch (err) {
            pushToast(getApiError(err), "error");
          } finally {
            setDeleteFoodBusy(false);
          }
        }}
      />
    </div>
  );
};
