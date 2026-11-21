import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Download, Eye, Plus, QrCode, RefreshCw, Trash2, Upload } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import type { FoodItem } from "../../../types";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../../components/ui/Primitives";

export const MenuTab: React.FC<{
  activeCanteenId: string;
  menuItems: FoodItem[];
  categories: any[];
  refetchMenu: () => void;
  refetchCategories: () => void;
  downloadBlob: (url: string, filename: string) => Promise<void>;
}> = ({ activeCanteenId, menuItems, categories, refetchMenu, refetchCategories, downloadBlob }) => {
  const { pushToast } = useToast();
  const { data: schedules = [], refetch: refetchSchedules } = useQuery<any[]>({
    queryKey: ["menu-schedules", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/schedules`)).data,
  });

  const [catName, setCatName] = useState("");
  const [newDishName, setNewDishName] = useState("");
  const [newDishPrice, setNewDishPrice] = useState("60.00");
  const [newDishCatId, setNewDishCatId] = useState("");
  const [isVeg, setIsVeg] = useState(true);
  const [editItem, setEditItem] = useState<FoodItem | null>(null);
  const [editPrice, setEditPrice] = useState("");
  const [editPrep, setEditPrep] = useState("10");
  const [editDesc, setEditDesc] = useState("");
  const [editImg, setEditImg] = useState("");
  const [editAllergens, setEditAllergens] = useState("");
  const [editFeatured, setEditFeatured] = useState(false);
  const [editSpecial, setEditSpecial] = useState(false);
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

  const openEditor = (it: FoodItem) => {
    setEditItem(it);
    setEditPrice(String(it.base_price));
    setEditPrep(String(it.prep_time_minutes));
    setEditDesc(it.description || "");
    setEditImg(it.images?.[0]?.image_url || "");
    setEditAllergens((it.allergens || []).map((a) => a.name).join(", "));
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
                try {
                  const slug = catName.toLowerCase().replace(/[^a-z0-9]+/g, "-");
                  await api.post("/menus/categories", { canteen_id: activeCanteenId, name: catName, slug });
                  setCatName("");
                  refetchCategories();
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
                    refetchCategories();
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

        <div className="flex flex-wrap gap-2 items-center border-t border-slate-100 pt-3">
          <Input value={newDishName} onChange={(e) => setNewDishName(e.target.value)} placeholder="New Dish Name" className="w-48" />
          <Input value={newDishPrice} onChange={(e) => setNewDishPrice(e.target.value)} placeholder="Price" className="w-24" />
          <Select value={newDishCatId} onChange={(e) => setNewDishCatId(e.target.value)} className="w-44">
            <option value="">Select Category</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Select value={isVeg ? "veg" : "nonveg"} onChange={(e) => setIsVeg(e.target.value === "veg")} className="w-32">
            <option value="veg">Veg</option>
            <option value="nonveg">Non-Veg</option>
          </Select>
          <Button
            size="sm"
            onClick={async () => {
              try {
                const slug = newDishName.toLowerCase().replace(/[^a-z0-9]+/g, "-");
                await api.post("/menus/items", {
                  canteen_id: activeCanteenId,
                  category_id: newDishCatId || categories[0]?.id,
                  name: newDishName,
                  slug,
                  base_price: newDishPrice,
                  is_veg: isVeg,
                });
                setNewDishName("");
                refetchMenu();
                pushToast("Dish added", "success");
              } catch (err) {
                pushToast(getApiError(err), "error");
              }
            }}
          >
            Add Item
          </Button>
        </div>
      </Card>

      <Card className="p-4 space-y-2">
        {menuItems.map((it) => (
          <div key={it.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 py-2 text-xs">
            <div>
              <span className="font-bold text-slate-900">{it.name}</span> • ₹{it.base_price} • {it.category_name}{" "}
              {it.is_featured && <Badge tone="amber">Featured</Badge>}
              {it.is_todays_special && <Badge tone="blue">Special</Badge>}
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => openEditor(it)}>
                Edit Price & Details
              </Button>
              <Button
                size="sm"
                variant={it.is_available ? "success" : "danger"}
                onClick={async () => {
                  try {
                    await api.patch(`/menus/items/${it.id}`, { is_available: !it.is_available });
                    refetchMenu();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                {it.is_available ? "Available" : "Disabled"}
              </Button>
            </div>
          </div>
        ))}
      </Card>

      {/* Menu Schedules Management */}
      <Card className="p-4 space-y-3">
        <div className="font-bold text-slate-900 flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-orange-600" /> Time-Based Menu Schedules ({schedules.length})
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
                <label className="mb-1 block font-bold text-slate-600">Price (₹)</label>
                <Input value={editPrice} onChange={(e) => setEditPrice(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block font-bold text-slate-600">Prep Time (min)</label>
                <Input type="number" value={editPrep} onChange={(e) => setEditPrep(e.target.value)} />
              </div>
            </div>
            <div>
              <label className="mb-1 block font-bold text-slate-600">Description</label>
              <Input value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block font-bold text-slate-600">Image URL</label>
              <Input value={editImg} onChange={(e) => setEditImg(e.target.value)} placeholder="https://..." />
            </div>
            <div>
              <label className="mb-1 block font-bold text-slate-600">Allergens (comma-separated)</label>
              <Input value={editAllergens} onChange={(e) => setEditAllergens(e.target.value)} placeholder="Dairy, Gluten, Nuts" />
            </div>
            <div className="flex items-center gap-4 pt-1">
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
                try {
                  const allergens = editAllergens
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean);
                  await api.patch(`/menus/items/${editItem.id}`, {
                    base_price: editPrice,
                    prep_time_minutes: Number(editPrep) || 10,
                    description: editDesc,
                    image_url: editImg.trim() || null,
                    allergen_names: allergens,
                    is_featured: editFeatured,
                    is_todays_special: editSpecial,
                  });
                  pushToast("Dish updated!", "success");
                  setEditItem(null);
                  refetchMenu();
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
                        refetchMenu();
                        setEditItem(null);
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
                <Input value={newVarPrice} onChange={(e) => setNewVarPrice(e.target.value)} placeholder="Extra ₹ (20)" className="w-28" />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    try {
                      await api.post(`/menus/items/${editItem.id}/variants`, {
                        name: newVarName,
                        price_delta: newVarPrice || "0",
                      });
                      setNewVarName("");
                      setNewVarPrice("");
                      refetchMenu();
                      setEditItem(null);
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
                  <button
                    key={a.id}
                    type="button"
                    onClick={async () => {
                      try {
                        await api.patch(`/menus/addons/${a.id}`, { is_available: !a.is_available });
                        refetchMenu();
                        setEditItem(null);
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                    className={`rounded-full border px-2.5 py-0.5 font-semibold ${a.is_available ? "bg-white border-slate-200" : "bg-red-50 border-red-200 text-red-700"}`}
                  >
                    {a.name} ₹{a.price} ({a.is_available ? "On" : "Off"})
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <Input value={newAddonName} onChange={(e) => setNewAddonName(e.target.value)} placeholder="Add-on (e.g. Extra Cheese)" />
                <Input value={newAddonPrice} onChange={(e) => setNewAddonPrice(e.target.value)} placeholder="Price (15)" className="w-28" />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    try {
                      await api.post(`/menus/items/${editItem.id}/addons`, {
                        name: newAddonName,
                        price: newAddonPrice || "0",
                        addon_type: "addon",
                      });
                      setNewAddonName("");
                      setNewAddonPrice("");
                      refetchMenu();
                      setEditItem(null);
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
