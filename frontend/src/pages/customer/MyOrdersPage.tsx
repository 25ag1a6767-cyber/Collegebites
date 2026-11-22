import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Receipt, RotateCcw, Search } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
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
  const [guestOtp, setGuestOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [devOtpHint, setDevOtpHint] = useState<string | null>(null);
  const [recoveredOrders, setRecoveredOrders] = useState<Order[]>([]);
  const [busyRecover, setBusyRecover] = useState(false);

  const handleReorder = async (o: Order) => {
    try {
      let added = 0;
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
                className="inline-flex items-center gap-1 rounded-full bg-[#fdf8f0] border border-[#76010d]/25 px-3 py-1 text-xs font-bold text-[#76010d]"
              >
                <Receipt className="h-3 w-3" /> {ordNo}
              </Link>
            ))}
          </div>
        )}

        <div className="mt-4 border-t border-slate-100 pt-3 space-y-2">
          <div className="text-[11px] font-bold uppercase text-slate-500">Lost your guest token? Recover orders by Mobile OTP</div>
          <div className="flex flex-wrap gap-2 items-center">
            <Input
              value={guestPhone}
              onChange={(e) => setGuestPhone(e.target.value)}
              placeholder="+919876543210"
              className="w-44"
            />
            <Button
              size="sm"
              variant="outline"
              disabled={busyRecover || !guestPhone.trim()}
              onClick={async () => {
                setBusyRecover(true);
                try {
                  const res = await api.post("/auth/otp/request", { target: guestPhone.trim(), purpose: "guest_checkout" });
                  setOtpSent(true);
                  setDevOtpHint(res.data.dev_otp || null);
                  pushToast("Recovery OTP sent", "success");
                } catch (err) {
                  pushToast(getApiError(err), "error");
                } finally {
                  setBusyRecover(false);
                }
              }}
            >
              {otpSent ? "Resend OTP" : "Send Recovery OTP"}
            </Button>
            {otpSent && (
              <>
                <Input
                  value={guestOtp}
                  onChange={(e) => setGuestOtp(e.target.value)}
                  placeholder="6-digit OTP"
                  maxLength={6}
                  className="w-32"
                />
                <Button
                  size="sm"
                  disabled={busyRecover || guestOtp.trim().length < 6}
                  onClick={async () => {
                    setBusyRecover(true);
                    try {
                      const ver = await api.post("/auth/otp/verify", {
                        target: guestPhone.trim(),
                        purpose: "guest_checkout",
                        code: guestOtp.trim(),
                      });
                      const list = await api.post<Order[]>("/orders/guest/lookup", {
                        guest_phone: guestPhone.trim(),
                        otp_verification_token: ver.data.verification_token,
                      });
                      list.data.forEach((o) => {
                        if (o.guest_access_token) saveGuestOrderToken(o.order_number, o.guest_access_token);
                      });
                      setRecoveredOrders(list.data);
                      pushToast(`Found ${list.data.length} guest order(s)`, "success");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    } finally {
                      setBusyRecover(false);
                    }
                  }}
                >
                  Find My Orders
                </Button>
              </>
            )}
          </div>
          {devOtpHint && (
            <div className="text-xs text-slate-600">
              Dev OTP: <strong className="font-mono">{devOtpHint}</strong>
            </div>
          )}
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
