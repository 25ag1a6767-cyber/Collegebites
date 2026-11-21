import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CreditCard, Printer, QrCode, Search, ShoppingBag, Trash2 } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, FoodItem, Order, ReceiptSnapshot } from "../../types";
import { ReceiptSlip } from "../../components/receipt/ReceiptSlip";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../components/ui/Primitives";

interface PosLine {
  food: FoodItem;
  variantId?: string;
  variantName?: string;
  unitPrice: number;
  quantity: number;
}

export const CashierPOSPage: React.FC = () => {
  const { pushToast } = useToast();
  const { user, selectedCanteenId } = useAppStore();

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [canteenId, setCanteenId] = useState<string>(user?.assigned_canteen_id || selectedCanteenId || "");
  const activeCanteenId = canteenId || canteens[0]?.id || "";
  const activeCanteen = canteens.find((c) => c.id === activeCanteenId);

  const { data: items = [] } = useQuery<FoodItem[]>({
    queryKey: ["pos-menu", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/items?available_only=true`)).data,
  });

  const { data: currentShift, refetch: refetchShift } = useQuery<any>({
    queryKey: ["pos-shift"],
    queryFn: async () => (await api.get("/pos/shifts/current")).data,
  });

  const [tab, setTab] = useState<"pos" | "orders" | "shift">("pos");
  const [searchMenu, setSearchMenu] = useState("");
  const [posLines, setPosLines] = useState<PosLine[]>([]);
  const [customerName, setCustomerName] = useState("Walk-in Customer");
  const [customerPhone, setCustomerPhone] = useState("");
  const [payMethod, setPayMethod] = useState<"cash" | "upi_pos" | "card_pos">("cash");
  const [couponCode, setCouponCode] = useState("");
  const [busy, setBusy] = useState(false);

  // Order search & receipt modal
  const [orderSearchQ, setOrderSearchQ] = useState("");
  const [foundOrders, setFoundOrders] = useState<Order[]>([]);
  const [activeReceipt, setActiveReceipt] = useState<ReceiptSnapshot | null>(null);

  // Shift forms
  const [openingCash, setOpeningCash] = useState("500.00");
  const [closingCash, setClosingCash] = useState("");
  const [closingNotes, setClosingNotes] = useState("");

  const addLine = (food: FoodItem) => {
    const defVar = food.variants.find((v) => v.is_default) || food.variants[0];
    const price = defVar?.absolute_price
      ? Number(defVar.absolute_price)
      : Number(food.base_price) + Number(defVar?.price_delta || 0);
    setPosLines((prev) => {
      const idx = prev.findIndex((p) => p.food.id === food.id && p.variantId === defVar?.id);
      if (idx >= 0) {
        const copy = [...prev];
        copy[idx] = { ...copy[idx], quantity: copy[idx].quantity + 1 };
        return copy;
      }
      return [...prev, { food, variantId: defVar?.id, variantName: defVar?.name, unitPrice: price, quantity: 1 }];
    });
  };

  const subtotal = posLines.reduce((s, l) => s + l.unitPrice * l.quantity, 0);
  const taxRate = Number(activeCanteen?.tax_rate_percent || 5) / 100;
  const estTotal = subtotal * (1 + taxRate);

  const submitWalkinOrder = async () => {
    if (!activeCanteenId || posLines.length === 0) return;
    setBusy(true);
    try {
      const res = await api.post<Order>("/pos/orders", {
        canteen_id: activeCanteenId,
        customer_name: customerName || "Walk-in Customer",
        customer_phone: customerPhone || null,
        payment_method: payMethod,
        coupon_code: couponCode || null,
        items: posLines.map((l) => ({
          food_item_id: l.food.id,
          variant_id: l.variantId || null,
          quantity: l.quantity,
        })),
      });
      pushToast(`Token ${res.data.pickup_token_code} created!`, "success");
      setPosLines([]);
      setCouponCode("");
      const recRes = await api.get<ReceiptSnapshot>(`/tokens/receipts/${res.data.order_number}`);
      setActiveReceipt(recRes.data);
      refetchShift();
    } catch (err) {
      pushToast(getApiError(err, "POS checkout failed"), "error");
    } finally {
      setBusy(false);
    }
  };

  const searchOrders = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!orderSearchQ.trim()) return;
    try {
      const res = await api.get(`/pos/orders/search?q=${encodeURIComponent(orderSearchQ.trim())}`);
      setFoundOrders(res.data);
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const collectPendingCash = async (orderId: string) => {
    try {
      const res = await api.post<Order>("/payments/counter/collect", {
        order_id: orderId,
        payment_method: "cash",
      });
      pushToast(`Cash collected! Token: ${res.data.pickup_token_code}`, "success");
      const recRes = await api.get<ReceiptSnapshot>(`/tokens/receipts/${res.data.order_number}`);
      setActiveReceipt(recRes.data);
      searchOrders();
      refetchShift();
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const filteredMenu = items.filter((i) => i.name.toLowerCase().includes(searchMenu.toLowerCase()));

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-5 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-slate-900 p-4 text-white">
        <div className="flex items-center gap-3">
          <CreditCard className="h-7 w-7 text-sky-400" />
          <div>
            <h1 className="text-xl font-extrabold">Cashier Point of Sale (POS)</h1>
            <p className="text-xs text-slate-400">
              Walk-in billing, counter cash collection, instant tokens & thermal receipt reprinting
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={activeCanteenId}
            onChange={(e) => setCanteenId(e.target.value)}
            className="w-52 bg-slate-800 border-slate-700 text-white"
          >
            {canteens.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          {(["pos", "orders", "shift"] as const).map((t) => (
            <Button key={t} size="sm" variant={tab === t ? "primary" : "outline"} onClick={() => setTab(t)}>
              {t === "pos" ? "Walk-in POS" : t === "orders" ? "Search & Reprint" : "Cash Shift"}
            </Button>
          ))}
        </div>
      </div>

      {tab === "pos" && (
        <div className="grid gap-5 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-4">
            <div className="relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <Input
                value={searchMenu}
                onChange={(e) => setSearchMenu(e.target.value)}
                placeholder="Quick search dishes..."
                className="pl-9"
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              {filteredMenu.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => addLine(item)}
                  className="rounded-2xl border border-slate-200 bg-white p-3.5 text-left shadow-sm transition hover:border-orange-500 hover:shadow-md active:scale-[0.98]"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${item.is_veg ? "bg-emerald-600" : "bg-red-600"}`} />
                    <span className="font-extrabold text-orange-600 text-sm">₹{item.base_price}</span>
                  </div>
                  <div className="mt-1.5 font-bold text-slate-900 text-sm line-clamp-1">{item.name}</div>
                  <div className="text-[11px] text-slate-500">{item.category_name}</div>
                </button>
              ))}
            </div>
          </div>

          <Card className="p-5 space-y-4 h-fit">
            <div className="flex items-center justify-between">
              <h2 className="font-extrabold text-slate-900 flex items-center gap-2">
                <ShoppingBag className="h-4 w-4 text-orange-600" /> Walk-in Ticket
              </h2>
              {posLines.length > 0 && (
                <button type="button" onClick={() => setPosLines([])} className="text-xs font-bold text-red-600">
                  Clear
                </button>
              )}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <Input value={customerName} onChange={(e) => setCustomerName(e.target.value)} placeholder="Customer Name" />
              <Input value={customerPhone} onChange={(e) => setCustomerPhone(e.target.value)} placeholder="Mobile (Opt)" />
            </div>

            <div className="space-y-2 max-h-60 overflow-y-auto border-y border-slate-100 py-3">
              {posLines.length === 0 ? (
                <div className="text-center text-xs text-slate-400 py-4">Tap items on the left to build order</div>
              ) : (
                posLines.map((l, idx) => (
                  <div key={idx} className="flex items-center justify-between text-xs">
                    <div>
                      <div className="font-bold text-slate-900">{l.food.name}</div>
                      <div className="text-slate-500">₹{l.unitPrice.toFixed(2)}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          setPosLines((p) =>
                            p
                              .map((x, i) => (i === idx ? { ...x, quantity: x.quantity - 1 } : x))
                              .filter((x) => x.quantity > 0)
                          )
                        }
                        className="h-6 w-6 rounded border font-bold"
                      >
                        -
                      </button>
                      <span className="font-bold">{l.quantity}</span>
                      <button
                        type="button"
                        onClick={() =>
                          setPosLines((p) => p.map((x, i) => (i === idx ? { ...x, quantity: x.quantity + 1 } : x)))
                        }
                        className="h-6 w-6 rounded border font-bold"
                      >
                        +
                      </button>
                      <button
                        type="button"
                        onClick={() => setPosLines((p) => p.filter((_, i) => i !== idx))}
                        className="text-slate-400 hover:text-red-600"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>

            <Input value={couponCode} onChange={(e) => setCouponCode(e.target.value)} placeholder="Coupon (optional)" />

            <div className="grid grid-cols-3 gap-2">
              {(["cash", "upi_pos", "card_pos"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setPayMethod(m)}
                  className={`rounded-xl border py-2 text-xs font-bold uppercase ${
                    payMethod === m ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 text-slate-700"
                  }`}
                >
                  {m.replace("_pos", "")}
                </button>
              ))}
            </div>

            <div className="flex justify-between text-base font-extrabold text-slate-900 pt-1">
              <span>Est. Total (incl. tax)</span>
              <span>₹{estTotal.toFixed(2)}</span>
            </div>

            <Button
              variant="primary"
              size="lg"
              className="w-full"
              disabled={busy || posLines.length === 0}
              onClick={submitWalkinOrder}
            >
              {busy ? "Generating Token..." : "Accept Payment & Print Token"}
            </Button>
          </Card>
        </div>
      )}

      {tab === "orders" && (
        <Card className="p-5 space-y-4">
          <form onSubmit={searchOrders} className="flex gap-2 max-w-xl">
            <Input
              value={orderSearchQ}
              onChange={(e) => setOrderSearchQ(e.target.value)}
              placeholder="Search by Token (A001), Order No (CB-...), Name, or Phone..."
            />
            <Button type="submit">
              <Search className="h-4 w-4" /> Search
            </Button>
          </form>

          <div className="space-y-2">
            {foundOrders.map((o) => (
              <div key={o.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-3 text-xs">
                <div>
                  <div className="flex items-center gap-2 font-bold text-sm">
                    <span>{o.order_number}</span>
                    {o.pickup_token_code && <Badge tone="default">Token {o.pickup_token_code}</Badge>}
                    <Badge tone={o.payment_status === "CONFIRMED" ? "green" : "amber"}>{o.payment_status}</Badge>
                    <Badge tone="slate">{o.status}</Badge>
                  </div>
                  <div className="text-slate-500 mt-1">
                    {o.guest_name || "Customer"} • ₹{o.total_amount} ({o.payment_method})
                  </div>
                </div>
                <div className="flex gap-2">
                  {o.payment_status !== "CONFIRMED" && o.status === "PAYMENT_PENDING" && (
                    <Button size="sm" variant="success" onClick={() => collectPendingCash(o.id)}>
                      Accept Cash & Issue Token
                    </Button>
                  )}
                  {o.payment_status === "CONFIRMED" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        const rec = await api.get<ReceiptSnapshot>(`/tokens/receipts/${o.order_number}`);
                        setActiveReceipt(rec.data);
                      }}
                    >
                      <Printer className="h-3.5 w-3.5" /> View / Reprint Slip
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {tab === "shift" && (
        <Card className="p-6 max-w-xl space-y-4">
          <h2 className="text-lg font-extrabold text-slate-900">Cashier Shift Drawer</h2>
          {!currentShift ? (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">No active cash shift open. Enter your opening cash float to begin.</p>
              <Input value={openingCash} onChange={(e) => setOpeningCash(e.target.value)} placeholder="500.00" />
              <Button
                onClick={async () => {
                  await api.post("/pos/shifts/open", {
                    canteen_id: activeCanteenId,
                    opening_cash_amount: openingCash,
                  });
                  pushToast("Cashier shift opened", "success");
                  refetchShift();
                }}
              >
                Open Cash Shift
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-slate-50 p-3">
                  <div className="text-xs text-slate-500">Opening Cash</div>
                  <div className="font-extrabold">₹{currentShift.opening_cash_amount}</div>
                </div>
                <div className="rounded-xl bg-emerald-50 p-3">
                  <div className="text-xs text-emerald-700">Expected Cash in Drawer</div>
                  <div className="font-extrabold text-emerald-900">
                    ₹{currentShift.shift_sales_summary?.expected_cash_in_drawer || "0.00"}
                  </div>
                </div>
              </div>
              <div className="text-xs text-slate-600">
                Total Collected Across All Methods: ₹{currentShift.shift_sales_summary?.total_collected || "0.00"}
              </div>
              <div className="space-y-2 border-t border-slate-100 pt-3">
                <label className="block text-xs font-bold text-slate-700">Counted Closing Cash (₹)</label>
                <Input value={closingCash} onChange={(e) => setClosingCash(e.target.value)} placeholder="Enter counted cash" />
                <Input value={closingNotes} onChange={(e) => setClosingNotes(e.target.value)} placeholder="Shift closing notes" />
                <Button
                  variant="danger"
                  onClick={async () => {
                    await api.post("/pos/shifts/close", {
                      closing_cash_amount: closingCash || currentShift.shift_sales_summary?.expected_cash_in_drawer || "0",
                      closing_notes: closingNotes,
                    });
                    pushToast("Shift closed & audited", "success");
                    refetchShift();
                  }}
                >
                  Close Shift
                </Button>
              </div>
            </div>
          )}
        </Card>
      )}

      <Modal
        open={Boolean(activeReceipt)}
        onClose={() => setActiveReceipt(null)}
        title={`Order Receipt • Token ${activeReceipt?.pickup_token}`}
        maxWidth="max-w-2xl"
      >
        {activeReceipt && <ReceiptSlip receipt={activeReceipt} allowStaffReprint onPrinted={() => {}} />}
      </Modal>
    </div>
  );
};
