import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Receipt, RotateCcw, Search } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Order } from "../../types";
import { Badge, Button, Card, Input, useToast } from "../../components/ui/Primitives";

export const MyOrdersPage: React.FC = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { user, guestOrderTokens, setSelectedCanteen } = useAppStore();
  const [lookupOrderNum, setLookupOrderNum] = useState("");
  const [lookupToken, setLookupToken] = useState("");

  const handleReorder = async (o: Order) => {
    try {
      let added = 0;
      for (const it of o.items) {
        if (!it.food_item_id) continue;
        await api.post("/carts/items", {
          canteen_id: o.canteen_id,
          food_item_id: it.food_item_id,
          variant_id: it.variant_id || null,
          quantity: it.quantity,
          special_instructions: it.special_instructions || null,
        });
        added += 1;
      }
      if (added === 0) {
        pushToast("No reorderable menu items found in this order", "info");
        return;
      }
      setSelectedCanteen(o.canteen_id);
      qc.invalidateQueries({ queryKey: ["cart", o.canteen_id] });
      pushToast("Items added back to cart!", "success");
      navigate("/checkout");
    } catch (err) {
      pushToast(getApiError(err, "Some items are currently unavailable to reorder"), "error");
    }
  };

  const { data: orders = [], isLoading } = useQuery<Order[]>({
    queryKey: ["my-orders"],
    enabled: Boolean(user),
    queryFn: async () => (await api.get("/orders/my")).data,
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
                className="inline-flex items-center gap-1 rounded-full bg-orange-50 border border-orange-200 px-3 py-1 text-xs font-bold text-orange-800"
              >
                <Receipt className="h-3 w-3" /> {ordNo}
              </Link>
            ))}
          </div>
        )}
      </Card>

      {user ? (
        isLoading ? (
          <div className="text-sm text-slate-500">Loading order history...</div>
        ) : orders.length === 0 ? (
          <Card className="p-8 text-center text-slate-500">
            No orders placed yet. <Link to="/" className="font-bold text-orange-600">Browse menus →</Link>
          </Card>
        ) : (
          <div className="space-y-3">
            {orders.map((o) => (
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
                    <Link to={`/orders/${o.order_number}`}>
                      <Button size="sm" variant="outline">
                        Receipt & Track <ArrowRight className="h-3.5 w-3.5" />
                      </Button>
                    </Link>
                  </div>
                </div>
              </Card>
            ))}
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
