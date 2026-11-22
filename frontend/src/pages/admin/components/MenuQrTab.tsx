import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Download, Eye, Plus, QrCode, RefreshCw, Trash2, Upload, X } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import type { FoodItem } from "../../../types";
import { Badge, Button, Card, ConfirmModal, Input, Modal, Select, useToast } from "../../../components/ui/Primitives";

function toCleanSlug(raw: string, existingSlugs: string[], fallbackPrefix = "item"): string {
  const base0 = raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const base = base0.length >= 2 ? base0.slice(0, 120) : `${fallbackPrefix}-${Date.now().toString(36)}`;
  const existing = new Set(existingSlugs.map((s) => s.toLowerCase()));
  if (!existing.has(base)) return base;
  for (let i = 2; i < 1000; i++) {
    const candidate = `${base.slice(0, 112)}-${i}`;
    if (!existing.has(candidate)) return candidate;
  }
  return `${base.slice(0, 108)}-${Date.now().toString(36)}`;
}

function parseValidPrice(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0 || n > 99999999.99) return null;
  return Number(n.toFixed(2));
}

export const MenuTab: React.FC<{
  activeCanteenId: string;
  menuItems: FoodItem[];
  categories: any[];
  refetchMenu: () => void;
  refetchCategories: () => void;
  downloadBlob: (url: string, filename: string) => Promise<void>;
}> = ({ activeCanteenId, menuItems, categories, refetchMenu, refetchCategories, downloadBlob }) => {
  const { pushToast } = useToast();
  const qc = useQueryClient();
  const syncAllMenus = () => {
    refetchMenu();
    refetchCategories();
    qc.invalidateQueries({ queryKey: ["admin-menu"] });
    qc.invalidateQueries({ queryKey: ["admin-cats"] });
    qc.invalidateQueries({ queryKey: ["menu-items"] });
    qc.invalidateQueries({ queryKey: ["categories"] });
    qc.invalidateQueries({ queryKey: ["smart-recs"] });
    qc.invalidateQueries({ queryKey: ["pos-menu"] });
    qc.invalidateQueries({ queryKey: ["kitchen-menu"] });
    qc.invalidateQueries({ queryKey: ["inv-menu"] });
    qc.invalidateQueries({ queryKey: ["inv-food-categories"] });
    qc.invalidateQueries({ queryKey: ["canteens"] });
  };
  const { data: schedules = [], refetch: refetchSchedules } = useQuery<any[]>({
    queryKey: ["menu-schedules", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/schedules`)).data,
  });
  const { data: pendingPriceRequests = [], refetch: refetchPriceRequests } = useQuery<any[]>({
    queryKey: ["admin-pending-price-changes", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () =>
      (await api.get(`/inventory/canteens/${activeCanteenId}/price-changes?status=pending_approval`)).data,
  });

  const [catName, setCatName] = useState("");
  const [newDishName, setNewDishName] = useState("");
  const [newDishDesc, setNewDishDesc] = useState("");
  const [newDishPrice, setNewDishPrice] = useState("60.00");
  const [newDishPrep, setNewDishPrep] = useState("10");
  const [newDishCatId, setNewDishCatId] = useState("");
  const [isVeg, setIsVeg] = useState(true);
  const [newDishAvailable, setNewDishAvailable] = useState(true);
  const [newDishFile, setNewDishFile] = useState<File | null>(null);
  const [savingDish, setSavingDish] = useState(false);

  const [editItem, setEditItem] = useState<FoodItem | null>(null);
  const [editName, setEditName] = useState("");
  const [editCatId, setEditCatId] = useState("");
  const [editVeg, setEditVeg] = useState(true);
  const [editPrice, setEditPrice] = useState("");
  const [editPrep, setEditPrep] = useState("10");
  const [editDesc, setEditDesc] = useState("");
  const [editImg, setEditImg] = useState("");
  const [editAllergens, setEditAllergens] = useState("");
  const [editAvailable, setEditAvailable] = useState(true);
  const [editActive, setEditActive] = useState(true);
  const [editFeatured, setEditFeatured] = useState(false);
  const [editSpecial, setEditSpecial] = useState(false);
  const [uploadingImg, setUploadingImg] = useState(false);
  const [newVarName, setNewVarName] = useState("");
  const [newVarPrice, setNewVarPrice] = useState("");
  const [newAddonName, setNewAddonName] = useState("");
  const [newAddonPrice, setNewAddonPrice] = useState("");
  const [schedName, setSchedName] = useState("");
  const [schedType, setSchedType] = useState("breakfast");
  const [schedStart, setSchedStart] = useState("07:30");
  const [schedEnd, setSchedEnd] = useState("11:00");
  const [assignSched, setAssignSched] = useState<any | null>(null);
  const [assignIds, setAssignIds] = useState<string[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<FoodItem | null>(null);
  const [deletingDish, setDeletingDish] = useState(false);

  const refreshEditingItem = async (itemId: string) => {
    syncAllMenus();
    try {
      const fresh = await api.get<FoodItem>(`/menus/items/${itemId}`);
      setEditItem(fresh.data);
      setEditImg(fresh.data.images?.[0]?.image_url || "");
    } catch {
      // ignore if deleted
    }
  };

  const openEditor = (it: FoodItem) => {
    setEditItem(it);
    setEditName(it.name);
    setEditCatId(it.category_id);
    setEditVeg(Boolean(it.is_veg));
    setEditPrice(String(it.base_price));
    setEditPrep(String(it.prep_time_minutes));
    setEditDesc(it.description || "");
    setEditImg(it.images?.[0]?.image_url || "");
    setEditAllergens((it.allergens || []).map((a) => a.name).join(", "));
    setEditAvailable(Boolean(it.is_available));
    setEditActive(Boolean(it.is_active));
    setEditFeatured(Boolean(it.is_featured));
    setEditSpecial(Boolean(it.is_todays_special));
    setNewVarName("");
    setNewVarPrice("");
    setNewAddonName("");
    setNewAddonPrice("");
  };

  const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !activeCanteenId) return;
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await api.post(`/menus/canteens/${activeCanteenId}/import-csv`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      pushToast(`CSV imported: ${res.data.created} created, ${res.data.updated} updated`, "success");
      refetchMenu();
      refetchCategories();
    } catch (err) {
      pushToast(getApiError(err, "CSV import failed"), "error");
    }
    e.target.value = "";
  };

  return (
    <div className="space-y-4">
      <Card className="p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2 items-center">
            <Input value={catName} onChange={(e) => setCatName(e.target.value)} placeholder="New Category Name" className="w-48" />
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                const name = catName.trim();
                if (name.length < 2) {
                  return pushToast("Category name must be at least 2 characters", "error");
                }
                try {
                  const slug = toCleanSlug(name, categories.map((c) => c.slug || ""), "cat");
                  await api.post("/menus/categories", { canteen_id: activeCanteenId, name, slug });
                  setCatName("");
                  syncAllMenus();
                  pushToast("Category added", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Add Category
            </Button>
          </div>
          <div className="flex gap-2">
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-800 hover:bg-slate-50">
              <Upload className="h-3.5 w-3.5" /> Import CSV
              <input type="file" accept=".csv" onChange={handleCsvUpload} className="hidden" />
            </label>
            <Button
              size="sm"
              variant="outline"
              onClick={() => downloadBlob(`/menus/canteens/${activeCanteenId}/export-csv`, "menu.csv")}
            >
              <Download className="h-3.5 w-3.5" /> Export Menu CSV
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5 border-t border-slate-100 pt-3">
          {categories.map((c) => (
            <div key={c.id} className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs">
              <span className="font-semibold text-slate-800">{c.name}</span>
              <button
                type="button"
                aria-label={`Delete category ${c.name}`}
                onClick={async () => {
                  try {
                    await api.delete(`/menus/categories/${c.id}`);
                    syncAllMenus();
                    pushToast("Category deleted", "info");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
                className="text-slate-400 hover:text-red-600"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>

        <div className="space-y-2 border-t border-slate-100 pt-3">
          <div className="flex flex-wrap gap-2 items-center">
            <Input value={newDishName} onChange={(e) => setNewDishName(e.target.value)} placeholder="New Dish Name" className="w-48" />
            <Input
              type="number"
              min="0.01"
              max="99999999.99"
              step="0.01"
              value={newDishPrice}
              onChange={(e) => setNewDishPrice(e.target.value)}
              placeholder="Price (₹)"
              className="w-28"
            />
            <Input
              type="number"
              min="1"
              max="240"
              value={newDishPrep}
              onChange={(e) => setNewDishPrep(e.target.value)}
              placeholder="Prep min"
              className="w-24"
            />
            <Select value={newDishCatId || categories[0]?.id || ""} onChange={(e) => setNewDishCatId(e.target.value)} className="w-44">
              {categories.length === 0 ? (
                <option value="">No Categories Yet</option>
              ) : (
                categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))
              )}
            </Select>
            <Select value={isVeg ? "veg" : "nonveg"} onChange={(e) => setIsVeg(e.target.value === "veg")} className="w-28">
              <option value="veg">Veg</option>
              <option value="nonveg">Non-Veg</option>
            </Select>
            <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-700">
              <input
                type="checkbox"
                checked={newDishAvailable}
                onChange={(e) => setNewDishAvailable(e.target.checked)}
              />
              Available Now
            </label>
          </div>
          <div className="flex flex-wrap gap-2 items-center">
            <Input
              value={newDishDesc}
              onChange={(e) => setNewDishDesc(e.target.value)}
              placeholder="Description (optional, shown on customer menu)"
              className="flex-1 min-w-[220px]"
            />
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
              <Upload className="h-3.5 w-3.5" />
              {newDishFile ? newDishFile.name.slice(0, 20) : "Food Photo"}
              <input
                type="file"
                accept="image/*"
                onChange={(e) => setNewDishFile(e.target.files?.[0] || null)}
                className="hidden"
              />
            </label>
            <Button
              size="sm"
              disabled={savingDish}
              onClick={async () => {
                const name = newDishName.trim();
                const catId = newDishCatId || categories[0]?.id;
                const priceNum = parseValidPrice(newDishPrice);
                if (name.length < 2) {
                  return pushToast("Dish name must be at least 2 characters", "error");
                }
                if (!catId) {
                  return pushToast("Create or select a food category first", "error");
                }
                if (priceNum === null || priceNum <= 0) {
                  return pushToast("Enter a valid price between 0.01 and 99999999.99", "error");
                }
                setSavingDish(true);
                try {
                  const slug = toCleanSlug(name, menuItems.map((m) => m.slug || ""), "dish");
                  const prepMins = Math.min(240, Math.max(1, Number(newDishPrep) || 10));
                  const created = await api.post<FoodItem>("/menus/items", {
                    canteen_id: activeCanteenId,
                    category_id: catId,
                    name,
                    slug,
                    description: newDishDesc.trim() || null,
                    base_price: priceNum.toFixed(2),
                    prep_time_minutes: prepMins,
                    is_veg: isVeg,
                    is_available: newDishAvailable,
                    is_active: true,
                  });
                  if (newDishFile) {
                    const form = new FormData();
                    form.append("file", newDishFile);
                    await api.post(`/menus/items/${created.data.id}/upload-image`, form, {
                      headers: { "Content-Type": "multipart/form-data" },
                    });
                  }
                  setNewDishName("");
                  setNewDishDesc("");
                  setNewDishFile(null);
                  syncAllMenus();
                  pushToast(`"${created.data.name}" saved to menu`, "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setSavingDish(false);
                }
              }}
            >
              {savingDish ? "Saving..." : "Add Item"}
            </Button>
          </div>
        </div>
      </Card>

      <Card className="p-4 space-y-2">
        {menuItems.map((it) => (
          <div key={it.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 py-2 text-xs">
            <div className="flex items-center gap-2.5">
              {it.images?.[0]?.image_url ? (
                <img
                  src={it.images[0].image_url}
                  alt={it.name}
                  className="h-9 w-9 rounded-lg object-cover border border-slate-200"
                />
              ) : (
                <div className="h-9 w-9 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-400">
                  IMG
                </div>
              )}
              <div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-bold text-slate-900">{it.name}</span>
                  <span>• ₹{it.base_price}</span>
                  <span className="text-slate-500">• {it.category_name || "Menu"}</span>
                  <span className="text-slate-400">• {it.prep_time_minutes}m</span>
                  <Badge tone={it.is_veg ? "green" : "red"}>{it.is_veg ? "Veg" : "Non-Veg"}</Badge>
                  {!it.is_active && <Badge tone="red">Inactive</Badge>}
                  {it.is_featured && <Badge tone="amber">Featured</Badge>}
                  {it.is_todays_special && <Badge tone="blue">Special</Badge>}
                </div>
                {it.description && <div className="text-slate-500 line-clamp-1">{it.description}</div>}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => openEditor(it)}>
                Edit Details & Add-ons
              </Button>
              <Button
                size="sm"
                variant={it.is_available ? "success" : "danger"}
                onClick={async () => {
                  try {
                    await api.patch(`/menus/items/${it.id}`, { is_available: !it.is_available });
                    syncAllMenus();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                {it.is_available ? "Available" : "Disabled"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    await api.patch(`/menus/items/${it.id}`, { is_active: !it.is_active });
                    syncAllMenus();
                    pushToast(it.is_active ? "Item deactivated" : "Item activated", "info");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                {it.is_active ? "Deactivate" : "Activate"}
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={() => setDeleteTarget(it)}
                aria-label={`Delete ${it.name}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        ))}
      </Card>

      {/* Selling Price Approval Queue (from Inventory Manager requests) */}
      <Card className="p-4 space-y-2.5 border-[#76010d]/25 bg-[#fdf8f0]">
        <div className="font-bold text-slate-900 flex items-center justify-between">
          <span>Pending Menu Selling Price Approvals ({pendingPriceRequests.length})</span>
          <Badge tone={pendingPriceRequests.length > 0 ? "amber" : "green"}>
            {pendingPriceRequests.length > 0 ? "Action Needed" : "All Reviewed"}
          </Badge>
        </div>
        {pendingPriceRequests.length === 0 ? (
          <div className="text-xs text-slate-500">No pending selling-price change requests from Inventory Manager.</div>
        ) : (
          <div className="space-y-2 text-xs">
            {pendingPriceRequests.map((req) => (
              <div
                key={req.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#76010d]/20 bg-white p-3"
              >
                <div>
                  <div className="font-bold text-slate-900">{req.food_item_name || "Menu Item"}</div>
                  <div className="text-slate-600">
                    ₹{req.old_price} → <strong className="text-[#76010d]">₹{req.new_price}</strong> • {req.reason} (Requested by{" "}
                    {req.requested_by_name || "Inventory Manager"})
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="success"
                    onClick={async () => {
                      try {
                        await api.post(`/inventory/price-changes/${req.id}/review`, {
                          decision: "approve",
                          review_notes: "Approved from Admin Menu console",
                        });
                        refetchPriceRequests();
                        syncAllMenus();
                        pushToast("Selling price approved and live on menu", "success");
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
                        await api.post(`/inventory/price-changes/${req.id}/review`, {
                          decision: "reject",
                          review_notes: "Rejected from Admin Menu console",
                        });
                        refetchPriceRequests();
                        pushToast("Selling price request rejected", "info");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Reject
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Menu Schedules Management */}
      <Card className="p-4 space-y-3">
        <div className="font-bold text-slate-900 flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-[#76010d]" /> Time-Based Menu Schedules ({schedules.length})
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <Input value={schedName} onChange={(e) => setSchedName(e.target.value)} placeholder="Breakfast Menu (7:30-11:00)" className="w-52" />
          <Select value={schedType} onChange={(e) => setSchedType(e.target.value)} className="w-32">
            <option value="breakfast">Breakfast</option>
            <option value="lunch">Lunch</option>
            <option value="snacks">Snacks</option>
            <option value="special">Special</option>
            <option value="all_day">All Day</option>
          </Select>
          <Input type="time" value={schedStart} onChange={(e) => setSchedStart(e.target.value)} className="w-28" />
          <Input type="time" value={schedEnd} onChange={(e) => setSchedEnd(e.target.value)} className="w-28" />
          <Button
            size="sm"
            onClick={async () => {
              try {
                await api.post("/menus/schedules", {
                  canteen_id: activeCanteenId,
                  name: schedName,
                  schedule_type: schedType,
                  start_time: `${schedStart}:00`,
                  end_time: `${schedEnd}:00`,
                  days_of_week: [0, 1, 2, 3, 4, 5, 6],
                });
                setSchedName("");
                refetchSchedules();
                pushToast("Menu schedule created", "success");
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Add Schedule
          </Button>
        </div>
        <div className="space-y-1.5 text-xs">
          {schedules.map((s) => (
            <div key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 p-2.5">
              <div>
                <span className="font-bold">{s.name}</span> ({s.schedule_type}) • {s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)} •{" "}
                <Badge tone="slate">{s.scheduled_item_ids?.length || 0} dishes</Badge>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setAssignSched(s);
                    setAssignIds(s.scheduled_item_ids || []);
                  }}
                >
                  Assign Dishes
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={async () => {
                    try {
                      await api.delete(`/menus/schedules/${s.id}`);
                      refetchSchedules();
                      refetchMenu();
                      pushToast("Schedule deleted", "info");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  Delete
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Modal open={Boolean(assignSched)} onClose={() => setAssignSched(null)} title={`Assign Dishes • ${assignSched?.name || ""}`}>
        {assignSched && (
          <div className="space-y-3 text-xs">
            <div className="max-h-60 overflow-y-auto space-y-1.5">
              {menuItems.map((it) => {
                const checked = assignIds.includes(it.id);
                return (
                  <label key={it.id} className="flex items-center gap-2 rounded-lg border border-slate-100 p-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        setAssignIds((prev) => (checked ? prev.filter((x) => x !== it.id) : [...prev, it.id]))
                      }
                    />
                    <span className="font-semibold text-slate-800">{it.name}</span>
                    <span className="text-slate-400">₹{it.base_price}</span>
                  </label>
                );
              })}
            </div>
            <Button
              className="w-full"
              onClick={async () => {
                try {
                  await api.put(`/menus/schedules/${assignSched.id}/items`, { food_item_ids: assignIds });
                  refetchSchedules();
                  refetchMenu();
                  setAssignSched(null);
                  pushToast("Schedule items saved", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Save Scheduled Dishes
            </Button>
          </div>
        )}
      </Modal>

      <Modal open={Boolean(editItem)} onClose={() => setEditItem(null)} title={`Edit Dish • ${editItem?.name}`}>
        {editItem && (
          <div className="space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block font-bold text-slate-600">Dish Name</label>
                <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block font-bold text-slate-600">Category</label>
                <Select value={editCatId} onChange={(e) => setEditCatId(e.target.value)}>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="mb-1 block font-bold text-slate-600">Price (₹)</label>
                <Input
                  type="number"
                  min="0.01"
                  max="99999999.99"
                  step="0.01"
                  value={editPrice}
                  onChange={(e) => setEditPrice(e.target.value)}
                />
              </div>
              <div>
                <label className="mb-1 block font-bold text-slate-600">Prep Time (min)</label>
                <Input type="number" min="1" max="240" value={editPrep} onChange={(e) => setEditPrep(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block font-bold text-slate-600">Dietary</label>
                <Select value={editVeg ? "veg" : "nonveg"} onChange={(e) => setEditVeg(e.target.value === "veg")}>
                  <option value="veg">Veg</option>
                  <option value="nonveg">Non-Veg</option>
                </Select>
              </div>
            </div>
            <div>
              <label className="mb-1 block font-bold text-slate-600">Description</label>
              <Input value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <label className="block font-bold text-slate-600">Dish Image URL or File Upload</label>
              <div className="flex gap-2 items-center">
                <Input value={editImg} onChange={(e) => setEditImg(e.target.value)} placeholder="https://... or upload photo" className="flex-1" />
                <label className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-2 font-semibold text-slate-700 hover:bg-slate-50">
                  <Upload className="h-3.5 w-3.5" />
                  {uploadingImg ? "Uploading..." : "Upload Photo"}
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    disabled={uploadingImg}
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file || !editItem) return;
                      setUploadingImg(true);
                      try {
                        const form = new FormData();
                        form.append("file", file);
                        await api.post(`/menus/items/${editItem.id}/upload-image`, form, {
                          headers: { "Content-Type": "multipart/form-data" },
                        });
                        await refreshEditingItem(editItem.id);
                        pushToast("Dish photo uploaded", "success");
                      } catch (err) {
                        pushToast(getApiError(err, "Image upload failed"), "error");
                      } finally {
                        setUploadingImg(false);
                        e.target.value = "";
                      }
                    }}
                  />
                </label>
              </div>
            </div>
            <div>
              <label className="mb-1 block font-bold text-slate-600">Allergens (comma-separated)</label>
              <Input value={editAllergens} onChange={(e) => setEditAllergens(e.target.value)} placeholder="Dairy, Gluten, Nuts" />
            </div>
            <div className="flex flex-wrap items-center gap-4 pt-1">
              <label className="flex items-center gap-1.5 font-semibold">
                <input type="checkbox" checked={editAvailable} onChange={(e) => setEditAvailable(e.target.checked)} />
                Available for Order
              </label>
              <label className="flex items-center gap-1.5 font-semibold">
                <input type="checkbox" checked={editActive} onChange={(e) => setEditActive(e.target.checked)} />
                Active in Menu
              </label>
              <label className="flex items-center gap-1.5 font-semibold">
                <input type="checkbox" checked={editFeatured} onChange={(e) => setEditFeatured(e.target.checked)} />
                Featured Dish
              </label>
              <label className="flex items-center gap-1.5 font-semibold">
                <input type="checkbox" checked={editSpecial} onChange={(e) => setEditSpecial(e.target.checked)} />
                Today&apos;s Special
              </label>
            </div>
            <Button
              className="w-full"
              onClick={async () => {
                const name = editName.trim();
                const priceNum = parseValidPrice(editPrice);
                if (name.length < 2) {
                  return pushToast("Dish name must be at least 2 characters", "error");
                }
                if (priceNum === null || priceNum <= 0) {
                  return pushToast("Enter a valid price between 0.01 and 99999999.99", "error");
                }
                try {
                  const allergens = editAllergens
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean);
                  await api.patch(`/menus/items/${editItem.id}`, {
                    name,
                    category_id: editCatId || editItem.category_id,
                    is_veg: editVeg,
                    base_price: priceNum.toFixed(2),
                    prep_time_minutes: Math.min(240, Math.max(1, Number(editPrep) || 10)),
                    description: editDesc,
                    image_url: editImg.trim() || null,
                    allergen_names: allergens,
                    is_available: editAvailable,
                    is_active: editActive,
                    is_featured: editFeatured,
                    is_todays_special: editSpecial,
                  });
                  pushToast("Dish updated!", "success");
                  setEditItem(null);
                  syncAllMenus();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Save Dish Changes
            </Button>

            {/* Variants Sub-section */}
            <div className="border-t border-slate-100 pt-2 space-y-2">
              <div className="font-bold text-slate-700">Portion Variants ({editItem.variants.length})</div>
              <div className="flex flex-wrap gap-1.5">
                {editItem.variants.map((v) => (
                  <button
                    key={v.id}
                    type="button"
                    onClick={async () => {
                      try {
                        await api.patch(`/menus/variants/${v.id}`, { is_available: !v.is_available });
                        await refreshEditingItem(editItem.id);
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                    className={`rounded-full border px-2.5 py-0.5 font-semibold ${v.is_available ? "bg-white border-slate-200" : "bg-red-50 border-red-200 text-red-700"}`}
                  >
                    {v.name} {v.absolute_price ? `₹${v.absolute_price}` : `+₹${v.price_delta}`} ({v.is_available ? "On" : "Off"})
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <Input value={newVarName} onChange={(e) => setNewVarName(e.target.value)} placeholder="Variant (e.g. Large)" />
                <Input type="number" step="0.01" value={newVarPrice} onChange={(e) => setNewVarPrice(e.target.value)} placeholder="Extra ₹ (20)" className="w-28" />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    if (!newVarName.trim()) return pushToast("Enter variant name", "error");
                    try {
                      await api.post(`/menus/items/${editItem.id}/variants`, {
                        name: newVarName.trim(),
                        price_delta: newVarPrice.trim() || "0",
                      });
                      setNewVarName("");
                      setNewVarPrice("");
                      await refreshEditingItem(editItem.id);
                      pushToast("Variant added", "success");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>

            {/* Addons Sub-section */}
            <div className="border-t border-slate-100 pt-2 space-y-2">
              <div className="font-bold text-slate-700">Add-ons ({editItem.addons.length})</div>
              <div className="flex flex-wrap gap-1.5">
                {editItem.addons.map((a) => (
                  <div
                    key={a.id}
                    className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 font-semibold ${a.is_available ? "bg-white border-slate-200" : "bg-red-50 border-red-200 text-red-700"}`}
                  >
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          await api.patch(`/menus/addons/${a.id}`, { is_available: !a.is_available });
                          await refreshEditingItem(editItem.id);
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                    >
                      {a.name} ₹{a.price} ({a.is_available ? "On" : "Off"})
                    </button>
                    <button
                      type="button"
                      aria-label={`Remove ${a.name}`}
                      onClick={async () => {
                        try {
                          await api.delete(`/menus/items/${editItem.id}/addons/${a.id}`);
                          await refreshEditingItem(editItem.id);
                          pushToast("Add-on removed from dish", "info");
                        } catch (err) {
                          pushToast(getApiError(err), "error");
                        }
                      }}
                      className="text-slate-400 hover:text-red-600"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
              <div className="flex gap-2">
                <Input value={newAddonName} onChange={(e) => setNewAddonName(e.target.value)} placeholder="Add-on (e.g. Extra Cheese)" />
                <Input type="number" min="0" step="0.01" value={newAddonPrice} onChange={(e) => setNewAddonPrice(e.target.value)} placeholder="Price (15)" className="w-28" />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    if (!newAddonName.trim()) return pushToast("Enter add-on name", "error");
                    const p = parseValidPrice(newAddonPrice || "0");
                    if (p === null) return pushToast("Enter a valid add-on price", "error");
                    try {
                      await api.post(`/menus/items/${editItem.id}/addons`, {
                        name: newAddonName.trim(),
                        price: p.toFixed(2),
                        addon_type: "addon",
                      });
                      setNewAddonName("");
                      setNewAddonPrice("");
                      await refreshEditingItem(editItem.id);
                      pushToast("Add-on linked", "success");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </Modal>

      <ConfirmModal
        open={Boolean(deleteTarget)}
        title={`Delete "${deleteTarget?.name || ""}"?`}
        message="Items with no past orders will be permanently deleted. Items referenced in historical orders will be archived and removed from the customer menu so past receipts stay intact."
        confirmLabel="Delete Dish"
        confirmVariant="danger"
        busy={deletingDish}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={async () => {
          if (!deleteTarget) return;
          setDeletingDish(true);
          try {
            const res = await api.delete(`/menus/items/${deleteTarget.id}`);
            setDeleteTarget(null);
            syncAllMenus();
            pushToast(res.data?.message || "Dish removed from menu", "info");
          } catch (err) {
            pushToast(getApiError(err), "error");
          } finally {
            setDeletingDish(false);
          }
        }}
      />
    </div>
  );
};

export const QRTab: React.FC<{ activeCanteenId: string; locationQrs: any[]; refetchQrs: () => void }> = ({
  activeCanteenId,
  locationQrs,
  refetchQrs,
}) => {
  const { pushToast } = useToast();
  const [qrLabel, setQrLabel] = useState("Table T-05 QR");
  const [qrType, setQrType] = useState<"canteen" | "counter" | "table" | "kiosk">("table");
  const [previewQr, setPreviewQr] = useState<any | null>(null);

  return (
    <div className="space-y-4">
      <Card className="p-4 flex flex-wrap items-center gap-3">
        <Select value={qrType} onChange={(e) => setQrType(e.target.value as any)} className="w-40">
          <option value="canteen">Canteen QR</option>
          <option value="counter">Counter QR</option>
          <option value="table">Table QR</option>
          <option value="kiosk">Kiosk QR</option>
        </Select>
        <Input value={qrLabel} onChange={(e) => setQrLabel(e.target.value)} placeholder="QR Label" className="w-60" />
        <Button
          size="sm"
          onClick={async () => {
            try {
              await api.post("/qr/locations", {
                target_type: qrType,
                canteen_id: activeCanteenId,
                label: qrLabel,
              });
              pushToast("Permanent location QR generated", "success");
              refetchQrs();
            } catch (err) {
              pushToast(getApiError(err), "error");
            }
          }}
        >
          <QrCode className="h-3.5 w-3.5" /> Generate Location QR
        </Button>
      </Card>

      <div className="grid gap-3 md:grid-cols-2">
        {locationQrs.map((q) => (
          <Card key={q.id} className="p-4 flex items-center justify-between gap-3 text-xs">
            <div>
              <div className="font-bold text-sm">{q.label}</div>
              <div className="font-mono text-slate-600">{q.code}</div>
              <Badge tone={q.is_active ? "green" : "red"} className="mt-1">
                {q.is_active ? "Active" : "Revoked"}
              </Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => setPreviewQr(q)}>
                <Eye className="h-3.5 w-3.5" /> Preview / Print
              </Button>
              {q.is_active && (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      try {
                        await api.post(`/qr/locations/${q.id}/replace`);
                        refetchQrs();
                        pushToast("QR code rotated", "info");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    <RefreshCw className="h-3.5 w-3.5" /> Replace
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      try {
                        await api.post(`/qr/locations/${q.id}/revoke`);
                        refetchQrs();
                        pushToast("QR code revoked", "info");
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Revoke
                  </Button>
                </>
              )}
            </div>
          </Card>
        ))}
      </div>

      <Modal open={Boolean(previewQr)} onClose={() => setPreviewQr(null)} title={previewQr?.label || "Location QR"}>
        {previewQr && (
          <div className="text-center space-y-4">
            <img
              src={`/api/v1/qr/locations/${previewQr.id}/image`}
              alt={previewQr.label}
              className="mx-auto h-64 w-64 rounded-xl border border-slate-200 p-2"
            />
            <div className="font-mono text-xs text-slate-600 break-all">{previewQr.scan_url}</div>
            <div className="flex justify-center gap-2">
              <Button size="sm" onClick={() => window.print()}>
                Print Poster
              </Button>
              <a href={`/api/v1/qr/locations/${previewQr.id}/image`} download={`${previewQr.code}.png`}>
                <Button size="sm" variant="outline">
                  Download PNG
                </Button>
              </a>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
