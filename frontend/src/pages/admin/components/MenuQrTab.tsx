import React, { useState } from "react";
import { Download, Eye, QrCode, RefreshCw, Upload } from "lucide-react";
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
  const [catName, setCatName] = useState("");
  const [newDishName, setNewDishName] = useState("");
  const [newDishPrice, setNewDishPrice] = useState("60.00");
  const [newDishCatId, setNewDishCatId] = useState("");
  const [isVeg, setIsVeg] = useState(true);

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
          <div key={it.id} className="flex items-center justify-between border-b border-slate-100 py-2 text-xs">
            <div>
              <span className="font-bold text-slate-900">{it.name}</span> • ₹{it.base_price} • {it.category_name}
            </div>
            <Button
              size="sm"
              variant={it.is_available ? "success" : "danger"}
              onClick={async () => {
                await api.patch(`/menus/items/${it.id}`, { is_available: !it.is_available });
                refetchMenu();
              }}
            >
              {it.is_available ? "Available" : "Disabled"}
            </Button>
          </div>
        ))}
      </Card>
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
            await api.post("/qr/locations", {
              target_type: qrType,
              canteen_id: activeCanteenId,
              label: qrLabel,
            });
            pushToast("Permanent location QR generated", "success");
            refetchQrs();
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
                      await api.post(`/qr/locations/${q.id}/replace`);
                      refetchQrs();
                    }}
                  >
                    <RefreshCw className="h-3.5 w-3.5" /> Replace
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      await api.post(`/qr/locations/${q.id}/revoke`);
                      refetchQrs();
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
