import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CreditCard, Printer, QrCode, Search, ShoppingBag, Trash2 } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useRealtimeSync } from "../../hooks/useRealtimeSync";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, FoodItem, Order, ReceiptSnapshot } from "../../types";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { ReceiptSlip } from "../../components/receipt/ReceiptSlip";
import { Badge, Button, Card, Input, Modal, Select, useToast } from "../../components/ui/Primitives";
import { RealtimeStatusBadge } from "../../components/ui/RealtimeStatusBadge";

interface PosLine {
  food: FoodItem;
  variantId?: string;
  variantName?: string;
  unitPrice: number;
  quantity: number;
}

export const CashierPOSPage: React.FC = () => {
  const { pushToast } = useToast();
  const { user, selectedCanteenId, printerWidth, autoPrintPos, setPrinterPrefs } = useAppStore();

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    staleTime: 60_000,
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [canteenId, setCanteenId] = useState<string>(user?.assigned_canteen_id || selectedCanteenId || "");
  const activeCanteenId = canteenId || canteens[0]?.id || "";
  const activeCanteen = canteens.find((c) => c.id === activeCanteenId);
  const [counterId, setCounterId] = useState<string>("");
  const activeCounterId = counterId || activeCanteen?.counters?.find((c) => c.is_active)?.id || "";

  useEffect(() => {
    setCounterId("");
  }, [activeCanteenId]);

  const { status: posSyncStatus, lastSyncedAt: posLastSyncedAt } = useRealtimeSync({
    enabled: Boolean(activeCanteenId),
    ssePath: activeCanteenId ? `/realtime/staff/orders/stream?canteen_id=${activeCanteenId}` : undefined,
    wsPath: activeCanteenId ? `/ws/kitchen/${activeCanteenId}` : undefined,
    queryKeys: [["pos-menu"], ["pos-pending-counter"], ["pos-active-orders"], ["pos-shift"]],
  });

  const { data: items = [] } = useQuery<FoodItem[]>({
    queryKey: ["pos-menu", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    staleTime: 30_000,
    refetchInterval: posSyncStatus === "live" ? 120000 : 30000,
    refetchIntervalInBackground: false,
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/items?available_only=true`)).data,
  });

  const { data: currentShift, refetch: refetchShift } = useQuery<any>({
    queryKey: ["pos-shift"],
    staleTime: 30_000,
    queryFn: async () => (await api.get("/pos/shifts/current")).data,
  });

  const [tab, setTab] = useState<"pos" | "orders" | "shift">("pos");

  const { data: pendingCounterOrders = [], refetch: refetchPendingCounter } = useQuery<Order[]>({
    queryKey: ["pos-pending-counter", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    staleTime: 10_000,
    queryFn: async () => (await api.get(`/pos/orders/pending-counter?canteen_id=${activeCanteenId}`)).data,
    refetchInterval: posSyncStatus === "live" ? 45000 : 12000,
    refetchIntervalInBackground: false,
  });

  const { data: activeOrders = [], refetch: refetchActiveOrders } = useQuery<Order[]>({
    queryKey: ["pos-active-orders", activeCanteenId],
    enabled: Boolean(activeCanteenId),
    staleTime: 10_000,
    queryFn: async () => (await api.get(`/pos/orders/active?canteen_id=${activeCanteenId}`)).data,
    refetchInterval: posSyncStatus === "live" ? 45000 : 12000,
    refetchIntervalInBackground: false,
  });

  const [searchMenu, setSearchMenu] = useState("");
  const [posLines, setPosLines] = useState<PosLine[]>([]);
  const [customerName, setCustomerName] = useState("Walk-in Customer");
  const [customerPhone, setCustomerPhone] = useState("");
  const [payMethod, setPayMethod] = useState<"upi_pos" | "card_pos">("upi_pos");
  const [busy, setBusy] = useState(false);

  // Order search & receipt modal
  const [orderSearchQ, setOrderSearchQ] = useState("");
  const [foundOrders, setFoundOrders] = useState<Order[]>([]);
  const [activeReceipt, setActiveReceipt] = useState<ReceiptSnapshot | null>(null);
  const [shouldAutoPrintReceipt, setShouldAutoPrintReceipt] = useState(false);

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
  const estTotal = subtotal;

  const submitWalkinOrder = async () => {
    if (!activeCanteenId || posLines.length === 0) return;
    setBusy(true);
    try {
      const res = await api.post<Order>("/pos/orders", {
        canteen_id: activeCanteenId,
        counter_id: activeCounterId || null,
        customer_name: customerName || "Walk-in Customer",
        customer_phone: customerPhone || null,
        payment_method: payMethod,
        items: posLines.map((l) => ({
          food_item_id: l.food.id,
          variant_id: l.variantId || null,
          quantity: l.quantity,
        })),
      });
      pushToast(`Token ${res.data.pickup_token_code} created!`, "success");
      setPosLines([]);
      const recRes = await api.get<ReceiptSnapshot>(`/tokens/receipts/${res.data.order_number}`);
      setShouldAutoPrintReceipt(autoPrintPos);
      setActiveReceipt(recRes.data);
      refetchShift();
      refetchActiveOrders();
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

  const collectCounterDigital = async (orderId: string, method: "upi_pos" | "card_pos") => {
    try {
      const res = await api.post<Order>("/payments/counter/collect", {
        order_id: orderId,
        payment_method: method,
      });
      pushToast(`Digital payment confirmed! Token: ${res.data.pickup_token_code}`, "success");
      const recRes = await api.get<ReceiptSnapshot>(`/tokens/receipts/${res.data.order_number}`);
      setActiveReceipt(recRes.data);
      searchOrders();
      refetchPendingCounter();
      refetchActiveOrders();
      refetchShift();
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const filteredMenu = useMemo(
    () => items.filter((i) => i.name.toLowerCase().includes(searchMenu.toLowerCase())),
    [items, searchMenu]
  );

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-5 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-[#380106] p-4 text-white">
        <div className="flex items-center gap-3">
          <BrandLogo size="md" variant="dark" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-extrabold">Cashier Point of Sale (POS)</h1>
              <RealtimeStatusBadge status={posSyncStatus} lastSyncedAt={posLastSyncedAt} darkSurface />
            </div>
            <p className="text-xs text-[#fdedce]/80">
              Digital UPI/Card walk-in billing, instant tokens &amp; thermal receipt reprinting (online-only policy)
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={activeCanteenId}
            onChange={(e) => setCanteenId(e.target.value)}
            className="w-48 bg-slate-800 border-slate-700 text-white"
          >
            {canteens.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          {activeCanteen?.counters && activeCanteen.counters.length > 0 && (
            <Select
              value={activeCounterId}
              onChange={(e) => setCounterId(e.target.value)}
              className="w-40 bg-slate-800 border-slate-700 text-white"
            >
              {activeCanteen.counters
                .filter((c) => c.is_active)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </Select>
          )}
          <label className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 border border-slate-700 px-2.5 py-1.5 text-xs font-semibold text-white cursor-pointer">
            <input
              type="checkbox"
              checked={autoPrintPos}
              onChange={(e) => setPrinterPrefs(printerWidth, e.target.checked)}
            />
            Auto-Print
          </label>
          {(["pos", "orders", "shift"] as const).map((t) => (
            <Button key={t} size="sm" variant={tab === t ? "primary" : "outline"} onClick={() => setTab(t)}>
              {t === "pos"
                ? "Digital Walk-in POS"
                : t === "orders"
                ? `Orders & Reprint (${activeOrders.length + pendingCounterOrders.length})`
                : "POS Shift"}
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
                  className="rounded-2xl border border-slate-200 bg-white p-3.5 text-left shadow-sm transition hover:border-[#76010d] hover:shadow-md active:scale-[0.98]"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${item.is_veg ? "bg-emerald-600" : "bg-red-600"}`} />
                    <span className="font-extrabold text-[#76010d] text-sm">₹{item.base_price}</span>
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
                <ShoppingBag className="h-4 w-4 text-[#76010d]" /> Walk-in Ticket
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

            <div className="grid grid-cols-2 gap-2">
              {(["upi_pos", "card_pos"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setPayMethod(m)}
                  className={`rounded-xl border py-2 text-xs font-bold uppercase ${
                    payMethod === m ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 text-slate-700"
                  }`}
                >
                  {m === "upi_pos" ? "UPI Terminal" : "Card Terminal"}
                </button>
              ))}
            </div>

            <div className="space-y-1 pt-1">
              <div className="flex justify-between text-base font-extrabold text-slate-900">
                <span>Total Payable</span>
                <span>₹{estTotal.toFixed(2)}</span>
              </div>
              <div className="text-[11px] text-slate-500">
                Listed prices inclusive of applicable statutory taxes.
              </div>
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
        <div className="space-y-5">
          <Card className="p-5 space-y-3">
            <h2 className="font-bold text-slate-900">
              Pending Counter Digital Collection ({pendingCounterOrders.length})
            </h2>
            {pendingCounterOrders.length === 0 ? (
              <div className="text-xs text-slate-500">No orders awaiting counter collection in this canteen.</div>
            ) : (
              <div className="space-y-2">
                {pendingCounterOrders.map((o) => (
                  <div key={o.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50/50 p-3 text-xs">
                    <div>
                      <div className="font-bold text-sm">
                        {o.order_number} <Badge tone="amber">{o.payment_method}</Badge>
                      </div>
                      <div className="text-slate-600 mt-0.5">
                        {o.guest_name || "Registered Customer"} • ₹{o.total_amount}
                      </div>
                    </div>
                    <div className="flex gap-1.5">
                      <Button size="sm" variant="success" onClick={() => collectCounterDigital(o.id, "upi_pos")}>
                        Collect UPI & Issue Token
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => collectCounterDigital(o.id, "card_pos")}>
                        Collect Card
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-slate-900">Live Active Canteen Orders ({activeOrders.length})</h2>
              <Badge tone="blue">Auto-refreshing</Badge>
            </div>
            {activeOrders.length === 0 ? (
              <div className="text-xs text-slate-500">No active paid orders in queue right now.</div>
            ) : (
              <div className="space-y-2">
                {activeOrders.map((o) => (
                  <div
                    key={o.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3 text-xs"
                  >
                    <div>
                      <div className="flex flex-wrap items-center gap-2 font-bold text-sm">
                        <span>{o.order_number}</span>
                        {o.pickup_token_code && <Badge tone="amber">Token {o.pickup_token_code}</Badge>}
                        <Badge tone={o.status === "READY" ? "green" : "blue"}>{o.status}</Badge>
                        <Badge tone="slate">{o.payment_method}</Badge>
                      </div>
                      <div className="text-slate-600 mt-1">
                        {o.guest_name || "Customer"} • ₹{o.total_amount} • {o.items.map((it) => `${it.quantity}× ${it.item_name}`).join(", ")}
                      </div>
                    </div>
                      <div className="flex gap-1.5">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            try {
                              setShouldAutoPrintReceipt(false);
                              const rec = await api.get<ReceiptSnapshot>(`/tokens/receipts/${o.order_number}`);
                              setActiveReceipt(rec.data);
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          <Printer className="h-3.5 w-3.5" /> View / Reprint Slip
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={async () => {
                            try {
                              const esc = await api.get(`/printing/kitchen-ticket/${o.order_number}/escpos?width=80mm`);
                              pushToast(`KOT ready (${esc.data.item_count} items, ${esc.data.byte_length} bytes)`, "success");
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          KOT
                        </Button>
                      </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

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
                    <Button size="sm" variant="success" onClick={() => collectCounterDigital(o.id, "upi_pos")}>
                      Accept UPI & Issue Token
                    </Button>
                  )}
                  {o.payment_status === "CONFIRMED" && (
                      <div className="flex gap-1.5">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            try {
                              setShouldAutoPrintReceipt(false);
                              const rec = await api.get<ReceiptSnapshot>(`/tokens/receipts/${o.order_number}`);
                              setActiveReceipt(rec.data);
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          <Printer className="h-3.5 w-3.5" /> View / Reprint Slip
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={async () => {
                            try {
                              const esc = await api.get(`/printing/kitchen-ticket/${o.order_number}/escpos?width=80mm`);
                              pushToast(`KOT ready (${esc.data.item_count} items, ${esc.data.byte_length} bytes)`, "success");
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          KOT
                        </Button>
                      </div>
                  )}
                </div>
              </div>
            ))}
          </div>
          </Card>
        </div>
      )}

      {tab === "shift" && (
        <Card className="p-6 max-w-xl space-y-4">
          <h2 className="text-lg font-extrabold text-slate-900">Cashier POS Terminal Shift</h2>
          {!currentShift ? (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">No active POS shift open. Enter opening settlement balance (e.g. 0.00) to begin.</p>
              <Input value={openingCash} onChange={(e) => setOpeningCash(e.target.value)} placeholder="0.00" />
              <Button
                onClick={async () => {
                  try {
                    await api.post("/pos/shifts/open", {
                      canteen_id: activeCanteenId,
                      counter_id: activeCounterId || null,
                      opening_cash_amount: openingCash,
                    });
                    pushToast("POS shift opened", "success");
                    refetchShift();
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
              >
                Open POS Shift
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-slate-50 p-3">
                  <div className="text-xs text-slate-500">Opening Terminal Balance</div>
                  <div className="font-extrabold">₹{currentShift.opening_cash_amount}</div>
                </div>
                <div className="rounded-xl bg-emerald-50 p-3">
                  <div className="text-xs text-emerald-700">Reconciled POS Settlement</div>
                  <div className="font-extrabold text-emerald-900">
                    ₹{currentShift.shift_sales_summary?.expected_cash_in_drawer || "0.00"}
                  </div>
                </div>
              </div>
              <div className="text-xs text-slate-600">
                Total Collected Across Digital POS Methods: ₹{currentShift.shift_sales_summary?.total_collected || "0.00"}
              </div>
              <div className="space-y-2 border-t border-slate-100 pt-3">
                <label className="block text-xs font-bold text-slate-700">Closing Settlement Amount (₹)</label>
                <Input value={closingCash} onChange={(e) => setClosingCash(e.target.value)} placeholder="Enter closing settlement total" />
                <Input value={closingNotes} onChange={(e) => setClosingNotes(e.target.value)} placeholder="Shift closing notes" />
                <Button
                  variant="danger"
                  onClick={async () => {
                    try {
                      await api.post("/pos/shifts/close", {
                        closing_cash_amount: closingCash || currentShift.shift_sales_summary?.expected_cash_in_drawer || "0",
                        closing_notes: closingNotes,
                      });
                      pushToast("Shift closed & audited", "success");
                      refetchShift();
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
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
        onClose={() => {
          setActiveReceipt(null);
          setShouldAutoPrintReceipt(false);
        }}
        title={`Order Receipt • Token ${activeReceipt?.pickup_token}`}
        maxWidth="max-w-2xl"
      >
        {activeReceipt && (
          <ReceiptSlip
            receipt={activeReceipt}
            allowStaffReprint
            autoPrintOnMount={shouldAutoPrintReceipt}
            onPrinted={async () => {
              try {
                const refreshed = await api.get<ReceiptSnapshot>(`/tokens/receipts/${activeReceipt.order_number}`);
                setActiveReceipt(refreshed.data);
              } catch {
                // ignore refresh failure
              }
            }}
          />
        )}
      </Modal>
    </div>
  );
};
