import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Receipt, RotateCcw, Search } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { useOfflineStore } from "../../store/useOfflineStore";
import { fetchWithOfflineCache } from "../../utils/offlineSync";
import type { Order } from "../../types";
import { BrandEmptyState, BrandLoadingState } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, useToast } from "../../components/ui/Primitives";

export const MyOrdersPage: React.FC = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { user, guestOrderTokens, saveGuestOrderToken, setSelectedCanteen } = useAppStore();
  const [lookupOrderNum, setLookupOrderNum] = useState("");
  const [lookupToken, setLookupToken] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [recoveredOrders, setRecoveredOrders] = useState<Order[]>([]);
  const [historyFilter, setHistoryFilter] = useState<"all" | "active" | "completed" | "cancelled">("all");
  const [historySearch, setHistorySearch] = useState("");

  const handleReorder = async (o: Order) => {
    try {
      let added = 0;
      const skipped: string[] = [];
      for (const it of o.items) {
        if (!it.food_item_id) continue;
        const addons: { addon_id: string; quantity: number }[] = [];
        let spiceLevel: string | null = null;
        let sugarLevel: string | null = null;
        const removedIngredients: string[] = [];
        for (const c of it.customizations || []) {
          if (c.customization_type === "addon" && c.addon_id) {
            addons.push({ addon_id: c.addon_id, quantity: c.quantity || 1 });
          } else if (c.customization_type === "spice") {
            spiceLevel = c.option_value;
          } else if (c.customization_type === "sugar") {
            sugarLevel = c.option_value;
          } else if (c.customization_type === "remove_ingredient") {
            removedIngredients.push(c.option_value);
          }
        }
        try {
          await api.post("/carts/items", {
            canteen_id: o.canteen_id,
            food_item_id: it.food_item_id,
            variant_id: it.variant_id || null,
            quantity: it.quantity,
            spice_level: spiceLevel,
            sugar_level: sugarLevel,
            removed_ingredients: removedIngredients,
            addons,
            special_instructions: it.special_instructions || null,
          });
          added += 1;
        } catch {
          skipped.push(it.item_name);
        }
      }
      if (added === 0) {
        pushToast("No reorderable menu items are currently available for this order", "error");
        return;
      }
      setSelectedCanteen(o.canteen_id);
      qc.invalidateQueries({ queryKey: ["cart", o.canteen_id] });
      pushToast(
        skipped.length > 0 ? `Added ${added} item(s). Unavailable: ${skipped.join(", ")}` : "Items added back to cart!",
        skipped.length > 0 ? "info" : "success"
      );
      navigate("/checkout");
    } catch (err) {
      pushToast(getApiError(err, "Some items are currently unavailable to reorder"), "error");
    }
  };

  const isOnline = useOfflineStore((s) => s.isOnline);
  const { data: orders = [], isLoading } = useQuery<Order[]>({
    queryKey: ["my-orders"],
    enabled: Boolean(user),
    queryFn: () => fetchWithOfflineCache("orders:my", async () => (await api.get("/orders/my")).data),
    refetchInterval: isOnline ? 15000 : false,
  });

  const filteredOrders = orders.filter((o) => {
    if (historyFilter === "active" && !["PAYMENT_PENDING", "PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING", "READY"].includes(o.status)) return false;
    if (historyFilter === "completed" && o.status !== "COMPLETED") return false;
    if (historyFilter === "cancelled" && !["CANCELLED", "REJECTED", "PAYMENT_FAILED"].includes(o.status)) return false;
    const q = historySearch.trim().toLowerCase();
    if (!q) return true;
    return (
      o.order_number.toLowerCase().includes(q) ||
      (o.pickup_token_code || "").toLowerCase().includes(q) ||
      o.items.some((i) => i.item_name.toLowerCase().includes(q))
    );
  });

  const savedGuestEntries = Object.entries(guestOrderTokens);

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900">Your Orders & Receipts</h1>
          <p className="text-xs text-slate-500">Track live preparation, view pickup QR tokens, and reprint receipts</p>
        </div>
      </div>

      {/* Guest Order Lookup */}
      <Card className="p-4">
        <div className="text-xs font-bold uppercase text-slate-500 mb-2">Track a Guest Order</div>
        <div className="grid gap-2 sm:grid-cols-3">
          <Input
            value={lookupOrderNum}
            onChange={(e) => setLookupOrderNum(e.target.value)}
            placeholder="Order No (e.g. CB-20261121-000001)"
          />
          <Input
            value={lookupToken}
            onChange={(e) => setLookupToken(e.target.value)}
            placeholder="Guest Token (optional if saved on device)"
          />
          <Button
            onClick={() => {
              if (!lookupOrderNum.trim()) return;
              const q = lookupToken.trim() ? `?guest_token=${encodeURIComponent(lookupToken.trim())}` : "";
              navigate(`/orders/${lookupOrderNum.trim()}${q}`);
            }}
          >
            <Search className="h-4 w-4" /> Track Order
          </Button>
        </div>

        {savedGuestEntries.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {savedGuestEntries.map(([ordNo]) => (
              <Link
                key={ordNo}
                to={`/orders/${ordNo}`}
                className="inline-flex items-center gap-1 rounded-full bg-[#fdf8f0] border border-[#76010d]/25 px-3 py-1 text-xs font-bold text-[#76010d]"
              >
                <Receipt className="h-3 w-3" /> {ordNo}
              </Link>
            ))}
          </div>
        )}

        <div className="mt-4 border-t border-slate-100 pt-3 space-y-2">
          <div className="text-[11px] font-bold uppercase text-slate-500">Recover a Guest Order (Order Number + Contact)</div>
          <div className="grid gap-2 sm:grid-cols-3">
            <Input
              aria-label="Guest order number"
              value={lookupOrderNum}
              onChange={(e) => setLookupOrderNum(e.target.value)}
              placeholder="Order # (e.g. CB-2026...)"
            />
            <Input
              aria-label="Guest mobile or email"
              value={guestPhone}
              onChange={(e) => setGuestPhone(e.target.value)}
              placeholder="Guest Mobile or Email"
            />
            <Button
              type="button"
              size="sm"
              disabled={!lookupOrderNum.trim() || !guestPhone.trim()}
              onClick={async () => {
                try {
                  const list = await api.post<Order[]>("/orders/guest/lookup", {
                    order_number: lookupOrderNum.trim(),
                    guest_contact: guestPhone.trim(),
                  });
                  list.data.forEach((o) => {
                    if (o.guest_access_token) saveGuestOrderToken(o.order_number, o.guest_access_token);
                  });
                  setRecoveredOrders(list.data);
                  pushToast(`Found ${list.data.length} matching guest order(s)`, "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Find Guest Order
            </Button>
          </div>
          {recoveredOrders.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-1">
              {recoveredOrders.map((ro) => (
                <Link
                  key={ro.id}
                  to={`/orders/${ro.order_number}${ro.guest_access_token ? `?guest_token=${encodeURIComponent(ro.guest_access_token)}` : ""}`}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-1.5 text-xs font-bold text-emerald-800"
                >
                  {ro.order_number} ({ro.status}) • ₹{ro.total_amount}
                </Link>
              ))}
            </div>
          )}
        </div>
      </Card>

      {user ? (
        isLoading ? (
          <BrandLoadingState message="Loading order history..." />
        ) : orders.length === 0 ? (
          <BrandEmptyState
            title="No orders placed yet"
            description="Explore campus canteens to customize a meal and generate your live QR pickup token."
            action={
              <Link to="/">
                <Button size="sm">Browse menus →</Button>
              </Link>
            }
          />
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap gap-1.5">
                {(["all", "active", "completed", "cancelled"] as const).map((tabKey) => (
                  <Button
                    key={tabKey}
                    size="sm"
                    variant={historyFilter === tabKey ? "secondary" : "outline"}
                    onClick={() => setHistoryFilter(tabKey)}
                  >
                    {tabKey === "all" ? "All Orders" : tabKey === "active" ? "Active" : tabKey === "completed" ? "Completed" : "Cancelled / Failed"}
                  </Button>
                ))}
              </div>
              <Input
                value={historySearch}
                onChange={(e) => setHistorySearch(e.target.value)}
                placeholder="Search order, token, dish..."
                className="w-56"
              />
            </div>

            {filteredOrders.length === 0 ? (
              <Card className="p-6 text-center text-xs text-slate-500">No orders matched the selected filter.</Card>
            ) : (
              filteredOrders.map((o) => (
                <Card key={o.id} className="p-4 flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-extrabold text-slate-900">{o.order_number}</span>
                      {o.pickup_token_code && <Badge tone="default">Token {o.pickup_token_code}</Badge>}
                      <Badge tone={o.status === "COMPLETED" ? "green" : o.status === "READY" ? "green" : "blue"}>
                        {o.status}
                      </Badge>
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {o.canteen_name} / {o.counter_name} • {new Date(o.created_at).toLocaleString()} •{" "}
                      {o.items.map((i) => `${i.quantity}x ${i.item_name}`).join(", ")}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <div className="font-extrabold text-slate-900">₹{o.total_amount}</div>
                      <div className="text-[11px] text-slate-500">{o.payment_status}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button size="sm" variant="ghost" onClick={() => handleReorder(o)}>
                        <RotateCcw className="h-3.5 w-3.5" /> Reorder
                      </Button>
                      {o.payment_status === "CONFIRMED" && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            try {
                              const res = await api.get(`/invoices/${o.id}/pdf`, { responseType: "blob" });
                              const url = URL.createObjectURL(res.data);
                              const a = document.createElement("a");
                              a.href = url;
                              a.download = `Invoice-${o.order_number}.pdf`;
                              a.click();
                              URL.revokeObjectURL(url);
                            } catch (err) {
                              pushToast(getApiError(err, "Failed to download tax invoice"), "error");
                            }
                          }}
                        >
                          <Receipt className="h-3.5 w-3.5" /> Tax Invoice PDF
                        </Button>
                      )}
                      <Link to={`/orders/${o.order_number}`}>
                        <Button size="sm" variant="outline">
                          Receipt & Track <ArrowRight className="h-3.5 w-3.5" />
                        </Button>
                      </Link>
                    </div>
                  </div>
                </Card>
              ))
            )}
          </div>
        )
      ) : (
        <Card className="p-6 text-center text-sm text-slate-600">
          Sign in to view your full order history across devices, or use the Guest Order tracker above.
        </Card>
      )}
    </div>
  );
};
